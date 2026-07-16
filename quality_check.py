"""
Data Quality Check Module for Vietnamese Stock Market Pipeline.

Runs automated quality checks against the ingested stock data and
generates a structured JSON report (data_quality_report.json).

Checks implemented:
  1. No NULL prices — every record must have a non-null price
  2. Price change within bounds — change_pct within ±30%
  3. Volume positivity — volume > 0 during trading hours (9:00–15:00 ICT)
  4. [Bonus] No duplicate tickers — each ticker appears at most once per trading day
  5. [Bonus] Data completeness — all expected fields should be populated

Usage:
    python quality_check.py              # Check against default DB
    python quality_check.py --db <path>  # Custom DB path
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config

# ─── Logging Setup ──────────────────────────────────────────────────────────

logger = logging.getLogger("quality_check")


def setup_logging(log_level: str = config.LOG_LEVEL) -> None:
    log_file = config.LOG_DIR / "quality_check.log"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file), encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=config.LOG_FORMAT,
        datefmt=config.LOG_DATE_FORMAT,
        handlers=handlers,
    )


# ─── Quality Check Framework ────────────────────────────────────────────────

ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class QualityCheck:
    """Base class for a data quality rule."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def run(self, conn: sqlite3.Connection) -> dict:
        """
        Execute the check and return a result dict.

        Returns:
            {
                "rule": str,
                "description": str,
                "status": "pass" | "fail",
                "total_records": int,
                "violations": int,
                "details": any  # Rule-specific details
            }
        """
        raise NotImplementedError


class NullPriceCheck(QualityCheck):
    """Rule 1: Every record must have a non-null price."""

    def __init__(self):
        super().__init__(
            "no_null_prices", "Every record must have a non-null price value"
        )

    def run(self, conn: sqlite3.Connection) -> dict:
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]
        null_count = cursor.execute(
            "SELECT COUNT(*) FROM stock_prices WHERE price IS NULL"
        ).fetchone()[0]

        return {
            "rule": self.name,
            "description": self.description,
            "status": "pass" if null_count == 0 else "fail",
            "total_records": total,
            "violations": null_count,
            "details": {
                "null_price_count": null_count,
                "message": (
                    "All records have valid prices"
                    if null_count == 0
                    else f"{null_count} records have NULL price"
                ),
            },
        }


class PriceChangeBoundsCheck(QualityCheck):
    """Rule 2: change_pct must be within ±30%."""

    def __init__(self, max_change_pct: float = config.MAX_PRICE_CHANGE_PCT):
        super().__init__(
            "price_change_within_bounds",
            f"Price change percentage must be within ±{max_change_pct}%",
        )
        self.max_change_pct = max_change_pct

    def run(self, conn: sqlite3.Connection) -> dict:
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]

        # Find tickers with out-of-bounds price changes
        anomalous = cursor.execute(
            """
            SELECT ticker, change_pct
            FROM stock_prices
            WHERE change_pct IS NOT NULL
              AND (change_pct > ? OR change_pct < ?)
            ORDER BY ABS(change_pct) DESC
            """,
            (self.max_change_pct, -self.max_change_pct),
        ).fetchall()

        anomalous_tickers = [
            {"ticker": row[0], "change_pct": row[1]} for row in anomalous
        ]

        return {
            "rule": self.name,
            "description": self.description,
            "status": "pass" if len(anomalous) == 0 else "fail",
            "total_records": total,
            "violations": len(anomalous),
            "details": {
                "threshold": f"±{self.max_change_pct}%",
                "anomalous_tickers": anomalous_tickers,
                "message": (
                    "All price changes within bounds"
                    if not anomalous
                    else f"{len(anomalous)} tickers have out-of-bounds price changes"
                ),
            },
        }


class VolumePositivityCheck(QualityCheck):
    """Rule 3: volume > 0 during trading hours (9:00–15:00 ICT)."""

    def __init__(self):
        super().__init__(
            "volume_positivity",
            "Volume must be positive (> 0) during trading hours (9:00-15:00 ICT)",
        )

    def run(self, conn: sqlite3.Connection) -> dict:
        cursor = conn.cursor()

        now_ict = datetime.now(ICT)
        current_hour = now_ict.hour
        is_trading_hours = (
            config.TRADING_HOUR_START <= current_hour < config.TRADING_HOUR_END
        )

        # Check for zero/null volume records
        zero_volume = cursor.execute(
            """
            SELECT COUNT(*) FROM stock_prices
            WHERE (volume IS NULL OR volume <= 0)
            """
        ).fetchone()[0]

        total = cursor.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]

        # Zero-volume tickers
        zero_tickers = cursor.execute(
            """
            SELECT ticker, volume FROM stock_prices
            WHERE (volume IS NULL OR volume <= 0)
            """
        ).fetchall()

        # During non-trading hours, zero volume is expected for some records
        if is_trading_hours:
            status = "pass" if zero_volume == 0 else "fail"
        else:
            # Outside trading hours, we still flag but mark as "pass" with warning
            status = "pass" if zero_volume == 0 else "warning"

        return {
            "rule": self.name,
            "description": self.description,
            "status": status,
            "total_records": total,
            "violations": zero_volume,
            "details": {
                "zero_volume_count": zero_volume,
                "zero_volume_tickers": [
                    {"ticker": row[0], "volume": row[1]} for row in zero_tickers
                ],
                "is_trading_hours": is_trading_hours,
                "current_time_ict": now_ict.strftime("%Y-%m-%d %H:%M:%S ICT"),
                "message": (
                    "All records have positive volume"
                    if zero_volume == 0
                    else (
                        f"{zero_volume} records have zero/null volume"
                        + (" (outside trading hours)" if not is_trading_hours else "")
                    )
                ),
            },
        }


class DuplicateTickerCheck(QualityCheck):
    """Bonus Rule 4: Each ticker should appear at most once per trading day."""

    def __init__(self):
        super().__init__(
            "no_duplicate_tickers",
            "Each ticker should appear at most once per trading day",
        )

    def run(self, conn: sqlite3.Connection) -> dict:
        cursor = conn.cursor()
        total = cursor.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]

        duplicates = cursor.execute(
            """
            SELECT ticker, trading_date, COUNT(*) as cnt
            FROM stock_prices
            GROUP BY ticker, trading_date
            HAVING cnt > 1
            ORDER BY cnt DESC
            """
        ).fetchall()

        dup_details = [
            {"ticker": row[0], "trading_date": row[1], "count": row[2]}
            for row in duplicates
        ]

        return {
            "rule": self.name,
            "description": self.description,
            "status": "pass" if not duplicates else "fail",
            "total_records": total,
            "violations": len(duplicates),
            "details": {
                "duplicate_entries": dup_details,
                "message": (
                    "No duplicate tickers found"
                    if not duplicates
                    else f"{len(duplicates)} duplicate ticker-date combinations found"
                ),
            },
        }


class DataCompletenessCheck(QualityCheck):
    """Bonus Rule 6: Check for missing values in critical columns."""

    CRITICAL_COLUMNS = [
        "ticker",
        "price",
        "open_price",
        "high_price",
        "low_price",
        "volume",
        "change_pct",
        "trading_date",
    ]

    def __init__(self):
        super().__init__(
            "data_completeness", "Critical columns should have no NULL values"
        )

    def run(self, conn: sqlite3.Connection) -> dict:
        cursor = conn.cursor()
        total = cursor.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]

        column_nulls = {}
        total_nulls = 0

        for col in self.CRITICAL_COLUMNS:
            null_count = cursor.execute(
                f"SELECT COUNT(*) FROM stock_prices WHERE {col} IS NULL"
            ).fetchone()[0]
            if null_count > 0:
                column_nulls[col] = null_count
                total_nulls += null_count

        return {
            "rule": self.name,
            "description": self.description,
            "status": "pass" if total_nulls == 0 else "fail",
            "total_records": total,
            "violations": total_nulls,
            "details": {
                "columns_checked": self.CRITICAL_COLUMNS,
                "null_counts_by_column": column_nulls if column_nulls else "none",
                "message": (
                    "All critical columns are fully populated"
                    if total_nulls == 0
                    else f"{total_nulls} NULL values found across {len(column_nulls)} columns"
                ),
            },
        }


# ─── Report Generator ───────────────────────────────────────────────────────


def run_all_checks(db_path: str) -> dict:
    """
    Execute all quality checks and compile a comprehensive report.

    Returns a structured report dict that is also saved as JSON.
    """
    checks = [
        NullPriceCheck(),
        PriceChangeBoundsCheck(),
        VolumePositivityCheck(),
        DuplicateTickerCheck(),
        DataCompletenessCheck(),
    ]

    conn = sqlite3.connect(db_path)
    now_ict = datetime.now(ICT)

    results = []
    passed = 0
    failed = 0
    warnings = 0

    for check in checks:
        logger.info("Running check: %s", check.name)
        try:
            result = check.run(conn)
            results.append(result)

            status = result["status"]
            if status == "pass":
                passed += 1
                logger.info("  ✅ %s — PASS", check.name)
            elif status == "warning":
                warnings += 1
                logger.warning("  ⚠️  %s — WARNING", check.name)
            else:
                failed += 1
                logger.error(
                    "  ❌ %s — FAIL (%d violations)", check.name, result["violations"]
                )

        except Exception as e:
            logger.error("  💥 %s — ERROR: %s", check.name, e)
            results.append(
                {
                    "rule": check.name,
                    "description": check.description,
                    "status": "error",
                    "error": str(e),
                }
            )
            failed += 1

    conn.close()

    report = {
        "report_generated_at": now_ict.strftime("%Y-%m-%d %H:%M:%S ICT"),
        "database_path": db_path,
        "summary": {
            "total_checks": len(checks),
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "overall_status": "pass" if failed == 0 else "fail",
        },
        "checks": results,
    }

    return report


def save_report(report: dict, output_path: str) -> None:
    """Save the quality report as a formatted JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Report saved to: %s", output_path)


# ─── Main Entry Point ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Run data quality checks on Vietnamese stock market data"
    )
    parser.add_argument(
        "--db",
        default=config.DATABASE_PATH,
        help=f"SQLite database path (default: {config.DATABASE_PATH})",
    )
    parser.add_argument(
        "--output",
        default=config.DATA_QUALITY_REPORT_PATH,
        help=f"Output report path (default: {config.DATA_QUALITY_REPORT_PATH})",
    )
    parser.add_argument(
        "--log-level",
        default=config.LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    # Verify database exists
    if not Path(args.db).exists():
        logger.error("Database not found: %s — run ingest.py first", args.db)
        sys.exit(1)

    logger.info("Starting data quality checks on: %s", args.db)
    report = run_all_checks(args.db)
    save_report(report, args.output)

    # Print summary to stdout
    print(json.dumps(report["summary"], indent=2))

    # Exit with non-zero if any check failed
    sys.exit(0 if report["summary"]["overall_status"] == "pass" else 1)


if __name__ == "__main__":
    main()
