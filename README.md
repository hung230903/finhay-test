# 📈 Vietnamese Stock Market Data Pipeline

A complete data pipeline for Vietnamese stock market data (HOSE — VN30) that ingests, validates, and analyzes real-time stock information from the SSI iBoard public API.

### Data Flow

1. **Ingest** (`ingest.py`) — Fetches VN30 stock data from SSI iBoard API, normalizes field names, and upserts into SQLite
2. **Quality Check** (`quality_check.py`) — Runs 5 automated quality rules against the database, outputs a structured JSON report
3. **Analytics** (`analytics.py`) — Executes SQL query for intraday volatility analysis, generates a dark-themed HTML report

## 📁 Project Structure

```
finhay-test/
├── README.md                  # This file — setup & run instructions
├── config.py                  # Configuration (API URL, DB path, thresholds, field mapping)
├── main.py                    # Pipeline orchestrator
├── test_pipeline.py           # Unit tests (pytest)
├── ingest.py                  # Deliverable 1 — Data ingestion script
├── quality_check.py           # Deliverable 2 — Data quality checker
├── analytics.py               # Deliverable 3 — SQL + HTML analytics generator
├── requirements.txt           # Dependencies (standard library only)
├── .gitignore                 # Git ignore rules
├── pyproject.toml             # Python project metadata
│
├── market_data.db             # [Generated] SQLite database
├── data_quality_report.json   # [Generated] Quality check output
├── analytics_output.html      # [Generated] Analytics HTML report
└── logs/                      # [Generated] Log files
    ├── ingest.log
    ├── quality_check.log
    ├── pipeline.log
    └── analytics.log

```

## 🚀 Setup & Run

### Prerequisites

- **Python 3.10+** (uses `match` statements and type hints)
- No external dependencies — uses only Python standard library

### Quick Start

```bash
# 1. Clone and navigate to project
cd finhay-test

# 2. Run the full pipeline
python main.py                # Runs Ingest ➔ Quality ➔ Analytics

# 3. View outputs
cat data_quality_report.json  # Quality report
open analytics_output.html    # Analytics dashboard (or xdg-open on Linux)
```

### Running Individual Stages

```bash
python main.py --stage ingest       # Step 1: Fetch & store data
python main.py --stage quality      # Step 2: Run quality checks
python main.py --stage analytics    # Step 3: Generate analytics HTML
```

### Running Tests

```bash
# Ensure pytest is installed (if not already)
pip install pytest

# Run the test suite
pytest test_pipeline.py
```

## 📡 Data Source

### API Details

| Property | Value                                              |
| -------- | -------------------------------------------------- |
| Endpoint | `https://iboard-query.ssi.com.vn/stock/group/VN30` |
| Auth     | None (public API, requires browser-like headers)   |
| Format   | JSON                                               |
| Records  | 30 stocks (VN30 index)                             |
| Update   | Real-time during trading hours (9:00–15:00 ICT)    |

> **💡 Note on Endpoint Selection (VN30 vs HOSE30):**
> The original project requirement suggested using the `HOSE30` endpoint. However, during implementation and testing, it was discovered that the SSI API's `HOSE30` endpoint frequently returns empty data (instability). To ensure pipeline reliability, the primary endpoint was intentionally switched to `VN30` (which reliably returns the exact same top 30 HOSE stocks).
> _As a bonus resilience feature, a fallback mechanism is implemented: if `VN30` fails, it automatically attempts to fetch from `HOSE30`._

### Field Mapping

The SSI iBoard API uses internal field names. This pipeline normalizes them:

| API Field            | Database Column | Description                   |
| -------------------- | --------------- | ----------------------------- |
| `stockSymbol`        | `ticker`        | Stock ticker (e.g., ACB, VCB) |
| `companyNameEn`      | `company_name`  | English Company Name          |
| `matchedPrice`       | `price`         | Last matched price (VND)      |
| `openPrice`          | `open_price`    | Opening price                 |
| `highest`            | `high_price`    | Intraday high                 |
| `lowest`             | `low_price`     | Intraday low                  |
| `priceChangePercent` | `change_pct`    | % change from previous close  |
| `nmTotalTradedQty`   | `volume`        | Total shares traded today     |
| `nmTotalTradedValue` | `market_cap`    | Total traded value (VND)      |

## 🗄️ Database Schema

```sql
CREATE TABLE stock_prices (
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
    UNIQUE(ticker, trading_date)
);
```

### Indexes

| Index                           | Columns                | Purpose                 |
| ------------------------------- | ---------------------- | ----------------------- |
| `idx_stock_prices_ticker`       | `ticker`               | Filter by stock         |
| `idx_stock_prices_trading_date` | `trading_date`         | Time-series queries     |
| `idx_stock_prices_ticker_date`  | `ticker, trading_date` | UPSERT conflict + joins |
| `idx_stock_prices_volume`       | `volume DESC`          | Volume rankings         |
| `idx_stock_prices_timestamp`    | `timestamp`            | Recent data filtering   |

## ✅ Data Quality Checks

| #   | Rule                     | Logic                                   | Status   |
| --- | ------------------------ | --------------------------------------- | -------- |
| 1   | **No NULL prices**       | `price IS NOT NULL` for all records     | Required |
| 2   | **Price change bounds**  | `change_pct` within ±30%                | Required |
| 3   | **Volume positivity**    | `volume > 0` during 9:00–15:00 ICT      | Required |
| 4   | **No duplicate tickers** | Max 1 record per ticker per trading day | Bonus    |
| 5   | **Data completeness**    | No NULLs in critical columns            | Bonus    |

## 🧪 Unit Testing

The project includes a comprehensive suite of unit tests written in native `pytest` format, ensuring the reliability of data parsing, ingestion logic, database upserts, and quality validation rules.

```bash
# Run the test suite
pytest test_pipeline.py
```

- **In-memory SQLite:** Tests use an isolated `:memory:` database to prevent polluting production data.
- **Fixtures:** Utilizes `@pytest.fixture` for clean database setup and teardown.
- **Coverage:** Tests API JSON parsing, graceful fallbacks, UPSERT idempotency.

## 📊 Analytics Query

```sql
-- Top 10 stocks by intraday volatility with volume comparison to 5-day average
WITH latest_date AS (
    SELECT MAX(trading_date) as max_date
    FROM stock_prices
),
today_data AS (
    SELECT
        ticker,
        company_name,
        open_price,
        high_price,
        low_price,
        price,
        change_pct,
        volume,
        trading_date
    FROM stock_prices
    WHERE trading_date = (SELECT max_date FROM latest_date)
),
historical_data AS (
    SELECT
        ticker,
        AVG(volume) as avg_volume_5d,
        COUNT(*) as hist_days
    FROM (
        SELECT
            ticker,
            volume,
            trading_date,
            ROW_NUMBER() OVER (
                PARTITION BY ticker
                ORDER BY trading_date DESC
            ) as rn
        FROM stock_prices
        WHERE trading_date < (SELECT max_date FROM latest_date)
    )
    WHERE rn <= 5
    GROUP BY ticker
)
SELECT
    t.ticker,
    t.open_price,
    t.high_price,
    t.low_price,
    CASE
        WHEN t.open_price > 0
        THEN ((t.high_price - t.low_price) / t.open_price) * 100
        ELSE 0
    END as "Volatility %",
    t.volume as "Today Volume",
    COALESCE(h.avg_volume_5d, t.volume) as "5-Day Avg Volume",
    CASE
        WHEN h.avg_volume_5d > 0
        THEN CAST(t.volume AS REAL) / h.avg_volume_5d
        ELSE 1.0
    END as "Volume Ratio"
FROM today_data t
LEFT JOIN historical_data h ON t.ticker = h.ticker
ORDER BY "Volatility %" DESC
LIMIT 10;
```

The HTML output features:

- 🌙 Dark theme with glassmorphism
- 📊 Summary statistics cards
- 🎨 Color-coded volatility and change indicators
- ✨ Subtle fade-in animations
- 📱 Responsive design

## 🔧 Configuration

All configuration is centralized in `config.py` and can be overridden via environment variables:

| Variable                | Default            | Description                |
| ----------------------- | ------------------ | -------------------------- |
| `FINHAY_API_URL`        | SSI VN30 endpoint  | Primary API URL            |
| `FINHAY_DB_PATH`        | `./market_data.db` | SQLite database path       |
| `FINHAY_API_TIMEOUT`    | `15`               | API timeout (seconds)      |
| `FINHAY_MAX_CHANGE_PCT` | `30.0`             | Max price change threshold |
| `FINHAY_LOG_LEVEL`      | `INFO`             | Logging verbosity          |

## 🛡️ Error Handling

| Scenario                 | Behavior                                       |
| ------------------------ | ---------------------------------------------- |
| API timeout              | Retries up to 3 times with exponential backoff |
| Malformed JSON           | Logs error, fails gracefully                   |
| Empty API response       | Falls back to alternate endpoint (HOSE30)      |
| Missing ticker field     | Skips record, logs warning                     |
| Market holiday / no data | Reports empty data, exits with warning         |
| Database locked          | WAL mode for concurrent reads                  |
| Partial data             | Inserts valid records, skips invalid ones      |
