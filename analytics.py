import sqlite3
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

import config

logger = config.setup_logger("analytics")
ICT = ZoneInfo("Asia/Ho_Chi_Minh")


def generate_html(rows: list[dict], query_date: str) -> str:
    """
    Generate a self-contained dark-themed HTML file with the analytics table.

    Uses modern CSS with glassmorphism, subtle animations, and responsive design.
    No external dependencies — everything is inlined.
    """
    # Build table rows HTML
    table_rows = ""
    for i, row in enumerate(rows):
        vol_pct = row["volatility_pct"]
        vol_ratio = row["volume_ratio"]
        change_pct = row["change_pct"] or 0

        # Color coding for volatility
        if vol_pct >= 5:
            vol_class = "high-vol"
        elif vol_pct >= 2:
            vol_class = "med-vol"
        else:
            vol_class = "low-vol"

        # Color coding for change
        if change_pct > 0:
            change_class = "positive"
            change_icon = "▲"
        elif change_pct < 0:
            change_class = "negative"
            change_icon = "▼"
        else:
            change_class = "neutral"
            change_icon = "—"

        # Color coding for volume ratio
        if vol_ratio >= 1.5:
            ratio_class = "high-ratio"
        elif vol_ratio >= 1.0:
            ratio_class = "normal-ratio"
        else:
            ratio_class = "low-ratio"

        hist_note = f" ({row['hist_days']}d)" if row["hist_days"] < 5 else ""

        table_rows += f"""
            <tr class="data-row" style="animation-delay: {i * 0.05}s">
                <td class="rank">{i + 1}</td>
                <td class="ticker">{row["ticker"]}</td>
                <td class="company">{row["company"] or ""}</td>
                <td class="number">{row["open"]:,.0f}</td>
                <td class="number">{row["high"]:,.0f}</td>
                <td class="number">{row["low"]:,.0f}</td>
                <td class="number {vol_class}">{vol_pct:.2f}%</td>
                <td class="number">{row["today_volume"]:,.0f}</td>
                <td class="number">{row["avg_volume_5d"]:,.0f}{hist_note}</td>
                <td class="number {ratio_class}">{vol_ratio:.2f}x</td>
                <td class="number {change_class}">{change_icon} {abs(change_pct):.2f}%</td>
            </tr>
            """

    if not rows:
        table_rows = """
                <tr>
                    <td colspan="11" class="empty-state">
                        <div class="empty-icon">📊</div>
                        <div>No data available. Run ingest.py first to populate the database.</div>
                    </td>
                </tr>
            """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="description" content="Vietnamese Stock Market Intraday Volatility Analytics - Top 10 HOSE stocks by volatility">
        <title>📈 HOSE Top 10 Intraday Volatility | Finhay Analytics</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        <style>
            /* ─── CSS Reset & Base ─────────────────────────────────────── */
            *, *::before, *::after {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            :root {{
                --bg-primary: #0a0e1a;
                --bg-secondary: #111827;
                --bg-card: rgba(17, 24, 39, 0.8);
                --bg-hover: rgba(55, 65, 81, 0.4);
                --border: rgba(75, 85, 99, 0.3);
                --text-primary: #f9fafb;
                --text-secondary: #9ca3af;
                --text-muted: #6b7280;
                --accent-green: #10b981;
                --accent-green-bg: rgba(16, 185, 129, 0.1);
                --accent-red: #ef4444;
                --accent-red-bg: rgba(239, 68, 68, 0.1);
                --accent-yellow: #f59e0b;
                --accent-yellow-bg: rgba(245, 158, 11, 0.1);
                --accent-blue: #3b82f6;
                --accent-blue-bg: rgba(59, 130, 246, 0.1);
                --accent-purple: #8b5cf6;
                --gradient-start: #667eea;
                --gradient-end: #764ba2;
            }}

            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: var(--bg-primary);
                color: var(--text-primary);
                min-height: 100vh;
                line-height: 1.6;
            }}

            /* ─── Background Effect ────────────────────────────────────── */
            body::before {{
                content: '';
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background:
                    radial-gradient(ellipse at 20% 50%, rgba(102, 126, 234, 0.08) 0%, transparent 50%),
                    radial-gradient(ellipse at 80% 50%, rgba(118, 75, 162, 0.06) 0%, transparent 50%),
                    radial-gradient(ellipse at 50% 0%, rgba(59, 130, 246, 0.05) 0%, transparent 40%);
                pointer-events: none;
                z-index: 0;
            }}

            /* ─── Container ────────────────────────────────────────────── */
            .container {{
                max-width: 1400px;
                margin: 0 auto;
                padding: 2rem 1.5rem;
                position: relative;
                z-index: 1;
            }}

            /* ─── Header ──────────────────────────────────────────────── */
            .header {{
                text-align: center;
                margin-bottom: 2.5rem;
            }}

            .header h1 {{
                font-size: 2rem;
                font-weight: 700;
                background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                margin-bottom: 0.5rem;
                letter-spacing: -0.02em;
            }}

            .header .subtitle {{
                color: var(--text-secondary);
                font-size: 0.95rem;
                font-weight: 400;
            }}

            .header .date-badge {{
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                margin-top: 1rem;
                padding: 0.5rem 1.25rem;
                background: var(--bg-card);
                border: 1px solid var(--border);
                border-radius: 100px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.85rem;
                color: var(--text-secondary);
                backdrop-filter: blur(10px);
            }}

            .date-badge .dot {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: var(--accent-green);
                animation: pulse 2s infinite;
            }}

            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.4; }}
            }}

            /* ─── Stats Bar ───────────────────────────────────────────── */
            .stats-bar {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-bottom: 2rem;
            }}

            .stat-card {{
                background: var(--bg-card);
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 1.25rem;
                backdrop-filter: blur(10px);
                transition: transform 0.2s, border-color 0.2s;
            }}

            .stat-card:hover {{
                transform: translateY(-2px);
                border-color: rgba(102, 126, 234, 0.3);
            }}

            .stat-card .label {{
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: var(--text-muted);
                margin-bottom: 0.35rem;
            }}

            .stat-card .value {{
                font-size: 1.5rem;
                font-weight: 700;
                font-family: 'JetBrains Mono', monospace;
            }}

            .stat-card .sub {{
                font-size: 0.8rem;
                color: var(--text-secondary);
                margin-top: 0.2rem;
            }}

            /* ─── Table Container ─────────────────────────────────────── */
            .table-container {{
                background: var(--bg-card);
                border: 1px solid var(--border);
                border-radius: 16px;
                overflow: hidden;
                backdrop-filter: blur(10px);
            }}

            .table-header {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 1.25rem 1.5rem;
                border-bottom: 1px solid var(--border);
            }}

            .table-header h2 {{
                font-size: 1.1rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }}

            .table-header .badge {{
                background: var(--accent-blue-bg);
                color: var(--accent-blue);
                padding: 0.2rem 0.7rem;
                border-radius: 100px;
                font-size: 0.75rem;
                font-weight: 600;
            }}

            /* ─── Table ───────────────────────────────────────────────── */
            .table-scroll {{
                overflow-x: auto;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 0.875rem;
            }}

            thead th {{
                padding: 0.875rem 1rem;
                text-align: left;
                font-weight: 600;
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: var(--text-muted);
                border-bottom: 1px solid var(--border);
                white-space: nowrap;
                position: sticky;
                top: 0;
                background: var(--bg-secondary);
            }}

            thead th:first-child {{
                padding-left: 1.5rem;
            }}

            tbody td {{
                padding: 0.875rem 1rem;
                border-bottom: 1px solid rgba(75, 85, 99, 0.15);
                white-space: nowrap;
            }}

            tbody td:first-child {{
                padding-left: 1.5rem;
            }}

            .data-row {{
                animation: fadeIn 0.3s ease-out forwards;
                opacity: 0;
                transition: background 0.15s;
            }}

            .data-row:hover {{
                background: var(--bg-hover);
            }}

            @keyframes fadeIn {{
                to {{ opacity: 1; }}
            }}

            .rank {{
                color: var(--text-muted);
                font-family: 'JetBrains Mono', monospace;
                font-weight: 500;
            }}

            .ticker {{
                font-weight: 700;
                color: var(--accent-blue);
                font-family: 'JetBrains Mono', monospace;
                letter-spacing: 0.02em;
            }}

            .company {{
                color: var(--text-secondary);
                font-size: 0.8rem;
                max-width: 200px;
                overflow: hidden;
                text-overflow: ellipsis;
            }}

            .number {{
                font-family: 'JetBrains Mono', monospace;
                text-align: right;
                font-weight: 500;
            }}

            /* ─── Status Colors ───────────────────────────────────────── */
            .positive {{
                color: var(--accent-green);
                background: var(--accent-green-bg);
                padding: 0.2rem 0.6rem;
                border-radius: 6px;
            }}

            .negative {{
                color: var(--accent-red);
                background: var(--accent-red-bg);
                padding: 0.2rem 0.6rem;
                border-radius: 6px;
            }}

            .neutral {{
                color: var(--text-muted);
            }}

            .high-vol {{
                color: var(--accent-red);
                font-weight: 700;
            }}

            .med-vol {{
                color: var(--accent-yellow);
                font-weight: 600;
            }}

            .low-vol {{
                color: var(--accent-green);
            }}

            .high-ratio {{
                color: var(--accent-purple);
                font-weight: 600;
            }}

            .normal-ratio {{
                color: var(--text-primary);
            }}

            .low-ratio {{
                color: var(--text-muted);
            }}

            /* ─── Empty State ─────────────────────────────────────────── */
            .empty-state {{
                text-align: center;
                padding: 3rem !important;
                color: var(--text-muted);
            }}

            .empty-icon {{
                font-size: 3rem;
                margin-bottom: 1rem;
            }}

            /* ─── Footer ──────────────────────────────────────────────── */
            .footer {{
                text-align: center;
                margin-top: 2rem;
                padding: 1rem;
                color: var(--text-muted);
                font-size: 0.8rem;
            }}

            .footer a {{
                color: var(--accent-blue);
                text-decoration: none;
            }}

            /* ─── Responsive ──────────────────────────────────────────── */
            @media (max-width: 768px) {{
                .container {{
                    padding: 1rem;
                }}
                .header h1 {{
                    font-size: 1.5rem;
                }}
                .stats-bar {{
                    grid-template-columns: repeat(2, 1fr);
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <header class="header">
                <h1>📈 HOSE Intraday Volatility Report</h1>
                <p class="subtitle">
                    Top 10 stocks ranked by intraday price volatility with volume analysis
                </p>
                <div class="date-badge">
                    <span class="dot"></span>
                    Trading Date: {query_date}
                </div>
            </header>

            <!-- Stats Summary -->
            <div class="stats-bar">
                <div class="stat-card">
                    <div class="label">Highest Volatility</div>
                    <div class="value" style="color: var(--accent-red)">
                        {rows[0]["volatility_pct"]:.2f}% </div>
                    <div class="sub">{rows[0]["ticker"] if rows else "N/A"}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Avg Volatility (Top 10)</div>
                    <div class="value" style="color: var(--accent-yellow)">
                        {sum(r["volatility_pct"] for r in rows) / max(len(rows), 1):.2f}%
                    </div>
                    <div class="sub">Across {len(rows)} stocks</div>
                </div>
                <div class="stat-card">
                    <div class="label">Max Volume Ratio</div>
                    <div class="value" style="color: var(--accent-purple)">
                        {max((r["volume_ratio"] for r in rows), default=0):.2f}x
                    </div>
                    <div class="sub">vs 5-day average</div>
                </div>
                <div class="stat-card">
                    <div class="label">Total Volume (Top 10)</div>
                    <div class="value" style="color: var(--accent-blue)">
                        {sum(r["today_volume"] for r in rows):,.0f}
                    </div>
                    <div class="sub">shares traded today</div>
                </div>
            </div>

            <!-- Data Table -->
            <div class="table-container">
                <div class="table-header">
                    <h2>
                        🔥 Volatility Ranking
                        <span class="badge">Top 10</span>
                    </h2>
                </div>
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Ticker</th>
                                <th>Company</th>
                                <th>Open</th>
                                <th>High</th>
                                <th>Low</th>
                                <th>Volatility %</th>
                                <th>Today Vol</th>
                                <th>5D Avg Vol</th>
                                <th>Vol Ratio</th>
                                <th>Change</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Footer -->
            <footer class="footer">
                <p>
                    Generated by <strong>Finhay Stock Analytics Pipeline</strong> ·
                    Data source: <a href="https://iboard.ssi.com.vn">SSI iBoard</a> ·
                    Report generated at {datetime.now(ICT).strftime("%Y-%m-%d %H:%M:%S")} ICT
                </p>
                <p style="margin-top: 0.5rem">
                    Query: "Top 10 stocks by intraday volatility (high − low) / open price,
                    with volume comparison to 5-day average"
                </p>
            </footer>
        </div>
    </body>
</html>
"""

    return html


# ─── Query Execution ────────────────────────────────────────────────────────


def run_analytics(db_path: str, output_path: str) -> None:
    logger.info("Running analytics query...")

    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                WITH latest_date AS (
                    SELECT 
                        MAX(trading_date) as max_date 
                    FROM stock_prices
                ),
                today_data AS (
                    SELECT 
                        ticker, 
                        company_name as Company, 
                        open_price, 
                        high_price, 
                        low_price, 
                        price, 
                        change_pct as change, 
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
                    t.ticker as Ticker, 
                    t.Company, 
                    t.open_price as Open, 
                    t.high_price as High, 
                    t.low_price as Low,
                    CASE 
                        WHEN t.open_price > 0 THEN ((t.high_price - t.low_price) / t.open_price) * 100 
                        ELSE 0 
                    END as "Volatility %", 
                    t.volume as "Today Volume", 
                    COALESCE(h.avg_volume_5d, t.volume) as "5-Day Avg Volume",
                    CASE 
                        WHEN h.avg_volume_5d > 0 THEN CAST(t.volume AS REAL) / h.avg_volume_5d 
                        ELSE 1.0 
                    END as "Volume Ratio", 
                    t.change as "Change %", 
                    COALESCE(h.hist_days, 0) as "Hist Days",
                    t.trading_date as QueryDate
                FROM today_data t 
                LEFT JOIN historical_data h ON t.ticker = h.ticker 
                ORDER BY "Volatility %" DESC 
                LIMIT 10;
            """)
            raw_rows = cursor.fetchall()

        except sqlite3.Error as e:
            logger.error(f"Database error during analytics: {e}")
            raise

    query_date = raw_rows[0]["QueryDate"] if raw_rows else "N/A"

    rows = [
        {
            "ticker": r["Ticker"],
            "company": r["Company"],
            "open": r["Open"] or 0,
            "high": r["High"] or 0,
            "low": r["Low"] or 0,
            "volatility_pct": r["Volatility %"] or 0,
            "today_volume": r["Today Volume"] or 0,
            "avg_volume_5d": r["5-Day Avg Volume"] or 0,
            "volume_ratio": r["Volume Ratio"] or 1.0,
            "change_pct": r["Change %"] or 0,
            "hist_days": r["Hist Days"] or 0,
        }
        for r in raw_rows
    ]

    logger.info("Query returned %d rows for date %s", len(rows), query_date)

    html_content = generate_html(rows, query_date)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("✅ Analytics report saved to: %s", output_path)

    if rows:
        logger.info(
            "Top volatility: %s (%.2f%%)", rows[0]["ticker"], rows[0]["volatility_pct"]
        )


if __name__ == "__main__":
    run_analytics(config.DATABASE_PATH, config.ANALYTICS_OUTPUT_PATH)
