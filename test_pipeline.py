import sqlite3
from datetime import datetime
import pytest

import ingest
from quality_check import NullPriceCheck, PriceChangeBoundsCheck

# --- Fixtures ---

@pytest.fixture
def db_connection():
    """Provides an in-memory SQLite database setup with the schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute(ingest.CREATE_TABLE_SQL)
    yield conn
    conn.close()

# --- Ingest Logic Tests ---

def test_parse_trading_date_valid():
    assert ingest.parse_trading_date("20260715") == "2026-07-15"

def test_parse_trading_date_invalid():
    # Should gracefully fallback to today's date
    today = datetime.now(ingest.ICT).strftime("%Y-%m-%d")
    assert ingest.parse_trading_date("invalid_date_format") == today

def test_normalize_record_valid():
    raw_api_data = {
        "stockSymbol": "FPT",
        "matchedPrice": 135000,
        "nmTotalTradedQty": 5000000,
        "tradingDate": "20260715",
        "exchange": "HOSE"
    }
    clean = ingest.normalize_record(raw_api_data)
    
    assert clean is not None
    assert clean["ticker"] == "FPT"
    assert clean["price"] == 135000
    assert clean["volume"] == 5000000
    assert clean["trading_date"] == "2026-07-15"
    assert clean["exchange"] == "HOSE"

def test_normalize_record_missing_ticker():
    # A record without a ticker should be skipped (returns None)
    raw_api_data = {"matchedPrice": 135000}
    assert ingest.normalize_record(raw_api_data) is None

# --- Database Operations Tests ---

def test_upsert_logic(db_connection):
    record1 = {
        "ticker": "VNM", "company_name": "Vinamilk", "exchange": "HOSE",
        "price": 65000, "open_price": 64000, "high_price": 66000, "low_price": 63000,
        "ref_price": 64500, "ceiling_price": 69000, "floor_price": 60000,
        "price_change": 500, "change_pct": 0.77, "volume": 1000, "market_cap": 65000000,
        "foreign_buy_vol": 0, "foreign_sell_vol": 0, "foreign_remaining": 0,
        "best_bid": 64900, "best_offer": 65100, "session": "CONTINUOUS",
        "trading_date": "2026-07-15", "timestamp": "2026-07-15 10:00:00"
    }
    
    # 1. Insert new record
    ingest.insert_records(db_connection, [record1])
    cnt = db_connection.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]
    assert cnt == 1

    # 2. Update (Upsert) - same ticker and date, but new price and timestamp
    record2 = record1.copy()
    record2["price"] = 66000
    record2["timestamp"] = "2026-07-15 10:05:00"
    
    ingest.insert_records(db_connection, [record2])
    cnt = db_connection.execute("SELECT COUNT(*) FROM stock_prices").fetchone()[0]
    assert cnt == 1, "Should not create a duplicate row for the same date"
    
    updated_price = db_connection.execute("SELECT price FROM stock_prices WHERE ticker='VNM'").fetchone()[0]
    assert updated_price == 66000, "Price should be updated by the upsert"

# --- Quality Checks Tests ---

def test_null_price_check(db_connection):
    # Insert a valid record
    db_connection.execute(
        "INSERT INTO stock_prices (ticker, trading_date, timestamp, price) VALUES (?, ?, ?, ?)",
        ("ACB", "2026-07-15", "10:00", 25000)
    )
    
    check = NullPriceCheck()
    res = check.run(db_connection)
    assert res["status"] == "pass"
    assert res["violations"] == 0

    # Insert a null price record
    db_connection.execute(
        "INSERT INTO stock_prices (ticker, trading_date, timestamp, price) VALUES (?, ?, ?, NULL)",
        ("BID", "2026-07-15", "10:00")
    )
    res = check.run(db_connection)
    assert res["status"] == "fail"
    assert res["violations"] == 1
    
def test_price_change_bounds_check(db_connection):
    # Insert a valid record (5% change)
    db_connection.execute(
        "INSERT INTO stock_prices (ticker, trading_date, timestamp, change_pct) VALUES (?, ?, ?, ?)",
        ("TCB", "2026-07-15", "10:00", 5.0)
    )
    
    # Insert an anomalous record (50% change, exceeds default 30% max)
    db_connection.execute(
        "INSERT INTO stock_prices (ticker, trading_date, timestamp, change_pct) VALUES (?, ?, ?, ?)",
        ("HPG", "2026-07-15", "10:00", 50.0)
    )
    
    check = PriceChangeBoundsCheck(max_change_pct=30.0)
    res = check.run(db_connection)
    assert res["status"] == "fail"
    assert res["violations"] == 1
    assert res["details"]["anomalous_tickers"][0]["ticker"] == "HPG"
