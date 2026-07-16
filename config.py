"""
Configuration module for the Vietnamese Stock Market Data Pipeline.

Centralizes all configurable parameters so they can be adjusted
without modifying business logic. Supports environment variable overrides
for production deployments (e.g., Docker, CI/CD).
"""

import os
from pathlib import Path

# ─── Project Paths ───────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent

DATABASE_PATH = os.getenv("FINHAY_DB_PATH", str(BASE_DIR / "market_data.db"))
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ─── API Configuration ──────────────────────────────────────────────────────

# The SSI iBoard public API endpoint.
# HOSE30 group returns empty data; VN30 is the correct group for top 30 HOSE stocks.
# Both endpoints are supported — the script will fallback automatically.
API_URL = os.getenv(
    "FINHAY_API_URL", "https://iboard-query.ssi.com.vn/stock/group/VN30"
)


# Browser-like headers required by the SSI iBoard API
# (returns 403 without proper User-Agent and Referer)
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://iboard.ssi.com.vn/",
    "Accept": "application/json",
    "Origin": "https://iboard.ssi.com.vn",
}

API_TIMEOUT_SECONDS = int(os.getenv("FINHAY_API_TIMEOUT", "15"))
API_MAX_RETRIES = int(os.getenv("FINHAY_API_MAX_RETRIES", "3"))
API_RETRY_DELAY_SECONDS = float(os.getenv("FINHAY_API_RETRY_DELAY", "2.0"))

# ─── Data Quality Thresholds ────────────────────────────────────────────────

# Maximum allowed price change percentage (Vietnamese stock exchanges
# have a ±7% daily limit for HOSE, but we use ±30% as a sanity check
# to catch obviously corrupted data while allowing for edge cases)
MAX_PRICE_CHANGE_PCT = float(os.getenv("FINHAY_MAX_CHANGE_PCT", "30.0"))

# Vietnamese stock market trading hours (ICT, UTC+7)
TRADING_HOUR_START = 9  # 09:00 ICT
TRADING_HOUR_END = 15  # 15:00 ICT

# ─── Output Paths ───────────────────────────────────────────────────────────

DATA_QUALITY_REPORT_PATH = os.getenv(
    "FINHAY_QUALITY_REPORT_PATH", str(BASE_DIR / "data_quality_report.json")
)

ANALYTICS_OUTPUT_PATH = os.getenv(
    "FINHAY_ANALYTICS_OUTPUT_PATH", str(BASE_DIR / "analytics_output.html")
)

# ─── Logging ────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("FINHAY_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


import logging
import sys


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.hasHandlers():
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    fh = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger
