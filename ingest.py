"""
Data Ingestion Script for Vietnamese Stock Market Pipeline.

Fetches real-time stock data from the SSI iBoard public API,
normalizes the response into a clean schema, and persists into SQLite.

Features:
  - Automatic retry with exponential backoff on API failures
  - Graceful handling of: timeouts, malformed JSON, empty responses, partial data
  - Idempotent inserts (UPSERT on ticker + timestamp composite key)
  - Structured logging for observability

Usage:
    python ingest.py                    # Single run
    python ingest.py --url <custom_url> # Override API URL
    python ingest.py --db <path.db>     # Override DB path
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import config

# ─── Logging Setup ──────────────────────────────────────────────────────────

logger = logging.getLogger("ingest")


def setup_logging(log_level: str = config.LOG_LEVEL) -> None:
    """Configure logging to both console and rotating file."""
    log_file = config.LOG_DIR / "ingest.log"

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


# ─── Database Layer ─────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS stock_prices (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT    NOT NULL,
        company_name    TEXT,
        price           REAL,
        open_price      REAL,
        high_price      REAL,
        low_price       REAL,
        change_pct      REAL,
        volume          INTEGER,
        market_cap      REAL,
        trading_date    TEXT    NOT NULL,
        timestamp       TEXT    NOT NULL,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),

        -- Prevent duplicate records for the same ticker on the same trading date
        UNIQUE(ticker, trading_date)
    );
"""

CREATE_INDEXES_SQL = [
    # Primary query pattern: analytics by ticker and date
    "CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker ON stock_prices(ticker);",
    # Date-range queries for time-series analysis
    "CREATE INDEX IF NOT EXISTS idx_stock_prices_trading_date ON stock_prices(trading_date);",
    # Composite index for the UPSERT conflict detection and common joins
    "CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker_date ON stock_prices(ticker, trading_date);",
    # Volume-based queries (e.g., "top movers by volume")
    "CREATE INDEX IF NOT EXISTS idx_stock_prices_volume ON stock_prices(volume DESC);",
    # Timestamp for ordering and filtering recent data
    "CREATE INDEX IF NOT EXISTS idx_stock_prices_timestamp ON stock_prices(timestamp);",
]

UPSERT_SQL = """
    INSERT INTO stock_prices (
        ticker, company_name, price, open_price, high_price, low_price,
        change_pct, volume, market_cap, trading_date, timestamp
    ) VALUES (
        :ticker, :company_name, :price, :open_price, :high_price, :low_price,
        :change_pct, :volume, :market_cap, :trading_date, :timestamp
    )
    ON CONFLICT(ticker, trading_date) DO UPDATE SET
        price           = excluded.price,
        open_price      = excluded.open_price,
        high_price      = excluded.high_price,
        low_price       = excluded.low_price,
        change_pct      = excluded.change_pct,
        volume          = excluded.volume,
        market_cap      = excluded.market_cap,
        timestamp       = excluded.timestamp;
"""


def init_database(db_path: str) -> sqlite3.Connection:
    """
    Initialize SQLite database with schema and indexes.

    Uses WAL mode for better concurrent read performance (relevant if
    this pipeline is later extended with a dashboard reading the DB).
    """
    logger.info("Initializing database at: %s", db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(CREATE_TABLE_SQL)
    for idx_sql in CREATE_INDEXES_SQL:
        conn.execute(idx_sql)
    conn.commit()
    logger.info("Database schema and indexes created successfully")
    return conn


# ─── API Layer ───────────────────────────────────────────────────────────────


def fetch_stock_data(
    api_url: str,
    timeout: int = config.API_TIMEOUT_SECONDS,
    max_retries: int = config.API_MAX_RETRIES,
    retry_delay: float = config.API_RETRY_DELAY_SECONDS,
) -> list[dict]:
    """
    Fetch stock data from SSI iBoard API with retry logic.

    Returns:
        List of raw stock dictionaries from the API response.

    Raises:
        RuntimeError: If all retries are exhausted or the response is invalid.
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Fetching data from %s (attempt %d/%d)",
                api_url,
                attempt,
                max_retries,
            )

            req = urllib.request.Request(api_url, headers=config.API_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8")

            # Validate JSON structure
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Malformed JSON response: {e}") from e

            # Validate expected response structure
            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"Unexpected response type: {type(payload).__name__}"
                )

            code = payload.get("code", "")
            if code != "SUCCESS":
                raise RuntimeError(
                    f"API returned non-success code: {code} — "
                    f"{payload.get('message', 'no message')}"
                )

            data = payload.get("data", [])
            if not isinstance(data, list):
                raise RuntimeError(
                    f"Expected 'data' to be a list, got {type(data).__name__}"
                )

            logger.info("API returned %d records", len(data))
            return data

        except urllib.error.URLError as e:
            last_error = e
            logger.warning("Network error on attempt %d: %s", attempt, e)
        except urllib.error.HTTPError as e:
            last_error = e
            logger.warning(
                "HTTP %d error on attempt %d: %s",
                e.code,
                attempt,
                e.reason,
            )
        except RuntimeError as e:
            last_error = e
            logger.warning("Data error on attempt %d: %s", attempt, e)

        if attempt < max_retries:
            wait = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
            logger.info("Retrying in %.1f seconds...", wait)
            time.sleep(wait)

    raise RuntimeError(
        f"All {max_retries} API attempts failed. Last error: {last_error}"
    )


# ─── Data Transformation ────────────────────────────────────────────────────

# Vietnam timezone: UTC+7
ICT = ZoneInfo("Asia/Ho_Chi_Minh")


def safe_float(val: any) -> float | None:
    try:
        return float(val) if val is not None and str(val).strip() != "" else None
    except (ValueError, TypeError):
        return None


def safe_int(val: any) -> int | None:
    try:
        return int(val) if val is not None and str(val).strip() != "" else None
    except (ValueError, TypeError):
        return None


def parse_trading_date(raw_date: str) -> str:
    """
    Convert SSI date format "YYYYMMDD" → ISO "YYYY-MM-DD".

    Falls back to today's date if the raw value is invalid.
    """
    try:
        dt = datetime.strptime(raw_date, "%Y%m%d")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        logger.warning("Invalid trading_date '%s', using today's date", raw_date)
        return datetime.now(ICT).strftime("%Y-%m-%d")


def normalize_record(raw: dict) -> dict | None:
    """
    Transform a raw API record into our clean schema.

    Returns None if the record is missing critical fields (ticker),
    allowing the caller to skip it gracefully.
    """
    ticker = raw.get("stockSymbol")
    if not ticker:
        logger.warning("Skipping record with missing ticker: %s", raw)
        return None

    # SSI returns prices in VND (no decimal scaling needed for stocks)
    now_ict = datetime.now(ICT)
    trading_date_raw = raw.get("tradingDate", "")
    trading_date = parse_trading_date(trading_date_raw)

    return {
        "ticker": ticker,
        "company_name": raw.get("companyNameEn"),
        "price": safe_float(raw.get("matchedPrice")),
        "open_price": safe_float(raw.get("openPrice")),
        "high_price": safe_float(raw.get("highest")),
        "low_price": safe_float(raw.get("lowest")),
        "change_pct": safe_float(raw.get("priceChangePercent")),
        "volume": safe_int(raw.get("nmTotalTradedQty")),
        "market_cap": safe_float(raw.get("nmTotalTradedValue")),
        "trading_date": trading_date,
        "timestamp": now_ict.strftime("%Y-%m-%d %H:%M:%S"),
    }


def normalize_all(raw_records: list[dict]) -> list[dict]:
    """
    Normalize a batch of raw API records.

    Skips records that fail validation (missing ticker) and logs warnings.
    """
    clean_records = []
    skipped = 0

    for raw in raw_records:
        record = normalize_record(raw)
        if record:
            clean_records.append(record)
        else:
            skipped += 1

    if skipped:
        logger.warning("Skipped %d records due to missing required fields", skipped)

    logger.info(
        "Normalized %d of %d records successfully",
        len(clean_records),
        len(raw_records),
    )
    return clean_records


# ─── Persistence Layer ──────────────────────────────────────────────────────


def insert_records(conn: sqlite3.Connection, records: list[dict]) -> int:
    """
    Insert or update records in the database.

    Uses UPSERT (INSERT ... ON CONFLICT DO UPDATE) for idempotent writes.
    Returns the number of rows affected.
    """
    if not records:
        logger.warning("No records to insert")
        return 0

    cursor = conn.cursor()
    try:
        cursor.executemany(UPSERT_SQL, records)
        affected = cursor.rowcount
        logger.info("Successfully upserted %d records into stock_prices", affected)
        return affected
    except sqlite3.Error as e:
        conn.rollback()
        logger.error("Database insert failed: %s", e)
        raise


# ─── Ingestion Log ──────────────────────────────────────────────────────────

CREATE_LOG_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS ingestion_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at      TEXT    NOT NULL,
        status      TEXT    NOT NULL,  -- 'success' or 'failure'
        api_url     TEXT,
        rows_fetched INTEGER DEFAULT 0,
        rows_inserted INTEGER DEFAULT 0,
        duration_ms  INTEGER,
        error_message TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );
"""


def log_ingestion_run(
    conn: sqlite3.Connection,
    status: str,
    api_url: str,
    rows_fetched: int = 0,
    rows_inserted: int = 0,
    duration_ms: int = 0,
    error_message: str | None = None,
) -> None:
    """Record an ingestion run in the database for audit trail."""
    conn.execute(
        """
        INSERT INTO ingestion_log
            (run_at, status, api_url, rows_fetched, rows_inserted, duration_ms, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(ICT).strftime("%Y-%m-%d %H:%M:%S"),
            status,
            api_url,
            rows_fetched,
            rows_inserted,
            duration_ms,
            error_message,
        ),
    )


# ─── Main Entry Point ───────────────────────────────────────────────────────


def run_ingestion(api_url: str, db_path: str) -> dict:
    """
    Execute a full ingestion cycle.

    Returns a summary dict with run statistics.
    """
    start_time = time.monotonic()
    conn = None
    summary = {
        "status": "failure",
        "api_url": api_url,
        "rows_fetched": 0,
        "rows_inserted": 0,
        "duration_ms": 0,
        "error": None,
    }

    try:
        # 1. Initialize database
        conn = init_database(db_path)
        conn.execute(CREATE_LOG_TABLE_SQL)
        conn.commit()

        # 2. Fetch data
        raw_data = fetch_stock_data(api_url)
        summary["rows_fetched"] = len(raw_data)

        if not raw_data:
            msg = "API returned empty data"
            logger.warning(msg)
            summary["error"] = msg
            log_ingestion_run(conn, "failure", api_url, error_message=msg)
            return summary

        # 3. Normalize
        clean_records = normalize_all(raw_data)

        # 4. Insert into database
        rows_inserted = insert_records(conn, clean_records)
        summary["rows_inserted"] = rows_inserted
        summary["status"] = "success"

        # 5. Log success
        elapsed = int((time.monotonic() - start_time) * 1000)
        summary["duration_ms"] = elapsed
        log_ingestion_run(
            conn,
            "success",
            api_url,
            rows_fetched=len(raw_data),
            rows_inserted=rows_inserted,
            duration_ms=elapsed,
        )

        # 6. Commit single transaction
        conn.commit()

        logger.info(
            "✅ Ingestion complete — %d rows fetched, %d rows upserted in %dms",
            len(raw_data),
            rows_inserted,
            elapsed,
        )

    except Exception as e:
        elapsed = int((time.monotonic() - start_time) * 1000)
        summary["duration_ms"] = elapsed
        summary["error"] = str(e)
        logger.error("❌ Ingestion failed: %s", e, exc_info=True)

        if conn:
            conn.rollback()
            try:
                log_ingestion_run(
                    conn,
                    "failure",
                    api_url,
                    duration_ms=elapsed,
                    error_message=str(e),
                )
                conn.commit()
            except Exception as log_err:
                logger.error("Failed to log ingestion error: %s", log_err)

    finally:
        if conn:
            conn.close()

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Vietnamese stock market data from SSI iBoard API"
    )
    parser.add_argument(
        "--url",
        default=config.API_URL,
        help=f"API URL to fetch stock data (default: {config.API_URL})",
    )
    parser.add_argument(
        "--db",
        default=config.DATABASE_PATH,
        help=f"SQLite database path (default: {config.DATABASE_PATH})",
    )
    parser.add_argument(
        "--log-level",
        default=config.LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    summary = run_ingestion(args.url, args.db)

    # Print summary as JSON to stdout for pipeline orchestration
    print(json.dumps(summary, indent=2))

    sys.exit(0 if summary["status"] == "success" else 1)


if __name__ == "__main__":
    main()
