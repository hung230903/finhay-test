#!/usr/bin/env python3
"""
Pipeline Orchestrator for Vietnamese Stock Market Data Pipeline.

Runs all three pipeline stages in sequence:
  1. Ingest  — Fetch data from SSI iBoard API → SQLite
  2. Quality — Run automated data quality checks → JSON report
  3. Analytics — Generate volatility analysis → HTML report

Usage:
    python main.py              # Run full pipeline
    python main.py --stage ingest       # Run only ingestion
    python main.py --stage quality      # Run only quality checks
    python main.py --stage analytics    # Run only analytics
    python main.py --log-level DEBUG    # Verbose logging
"""

import argparse
import sys
import time
from pathlib import Path

import config
from analytics import run_analytics
from ingest import run_ingestion
from quality_check import run_all_checks, save_report

# Set up all loggers so child module output is visible
logger = config.setup_logger("pipeline")
config.setup_logger("ingest")
config.setup_logger("quality_check")
config.setup_logger("analytics")


def run_stage_ingest(log_level: str) -> bool:
    """Stage 1: Data Ingestion."""
    logger.info("=" * 60)
    logger.info("📡 STAGE 1: DATA INGESTION")
    logger.info("=" * 60)

    summary = run_ingestion(config.API_URL, config.DATABASE_PATH)

    if summary["status"] == "success":
        logger.info(
            "✅ Ingestion succeeded: %d rows fetched, %d upserted (%dms)",
            summary["rows_fetched"],
            summary["rows_inserted"],
            summary["duration_ms"],
        )
        return True
    else:
        logger.error("❌ Ingestion failed: %s", summary.get("error"))
        return False


def run_stage_quality(log_level: str) -> bool:
    """Stage 2: Data Quality Checks."""
    logger.info("=" * 60)
    logger.info("🔍 STAGE 2: DATA QUALITY CHECKS")
    logger.info("=" * 60)

    if not Path(config.DATABASE_PATH).exists():
        logger.error("Database not found. Run ingestion first.")
        return False

    report = run_all_checks(config.DATABASE_PATH)
    save_report(report, config.DATA_QUALITY_REPORT_PATH)

    summary = report["summary"]
    logger.info(
        "Quality results: %d/%d passed, %d failed, %d warnings",
        summary["passed"],
        summary["total_checks"],
        summary["failed"],
        summary["warnings"],
    )

    if summary["overall_status"] == "pass":
        logger.info("✅ All quality checks passed")
        return True
    else:
        logger.warning(
            "⚠️  Some quality checks failed — review %s",
            config.DATA_QUALITY_REPORT_PATH,
        )
        return True  # Don't block pipeline on quality failures


def run_stage_analytics(log_level: str) -> bool:
    """Stage 3: Analytics Report Generation."""
    logger.info("=" * 60)
    logger.info("📊 STAGE 3: ANALYTICS REPORT")
    logger.info("=" * 60)

    if not Path(config.DATABASE_PATH).exists():
        logger.error("Database not found. Run ingestion first.")
        return False

    try:
        run_analytics(config.DATABASE_PATH, config.ANALYTICS_OUTPUT_PATH)
        logger.info("✅ Analytics report saved to: %s", config.ANALYTICS_OUTPUT_PATH)
        return True
    except Exception as e:
        logger.error("❌ Analytics failed: %s", e, exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run the Vietnamese Stock Market Data Pipeline"
    )
    parser.add_argument(
        "--stage",
        choices=["ingest", "quality", "analytics", "all"],
        default="all",
        help="Which pipeline stage to run (default: all)",
    )
    parser.add_argument(
        "--log-level",
        default=config.LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    logger.info("🚀 Finhay Stock Market Pipeline — Starting")
    logger.info("   Database: %s", config.DATABASE_PATH)
    logger.info("   API URL:  %s", config.API_URL)
    start_time = time.monotonic()

    stages = {
        "ingest": run_stage_ingest,
        "quality": run_stage_quality,
        "analytics": run_stage_analytics,
    }

    if args.stage == "all":
        run_stages = ["ingest", "quality", "analytics"]
    else:
        run_stages = [args.stage]

    results = {}
    for stage_name in run_stages:
        try:
            results[stage_name] = stages[stage_name](args.log_level)
        except Exception as e:
            logger.error("💥 Stage '%s' crashed: %s", stage_name, e, exc_info=True)
            results[stage_name] = False

        if not results[stage_name] and stage_name == "ingest":
            logger.error("Ingestion failed — skipping remaining stages")
            break

    elapsed = time.monotonic() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info("📋 PIPELINE SUMMARY")
    logger.info("=" * 60)
    for stage_name, success in results.items():
        icon = "✅" if success else "❌"
        logger.info("   %s %s", icon, stage_name.capitalize())
    logger.info("   ⏱️  Total time: %.1fs", elapsed)
    logger.info("=" * 60)

    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
