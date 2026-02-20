#!/usr/bin/env python3
"""
Daily data ingestion — pulls newly settled Kalshi weather markets into backtest.db.
Run once daily (after midnight ET when markets settle) to keep backtest data current.
Every day's settlements become tomorrow's backtest data.
"""

import sqlite3
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from kalshi_trader import KalshiClient, CONFIG

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(__file__).parent / "backtest.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "daily_ingest.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("daily_ingest")


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS settled_markets (
            ticker TEXT PRIMARY KEY,
            event_ticker TEXT,
            series_ticker TEXT,
            city TEXT,
            market_type TEXT,
            event_date TEXT,
            floor_strike REAL,
            cap_strike REAL,
            result TEXT,
            last_price INTEGER,
            yes_bid INTEGER,
            yes_ask INTEGER,
            volume INTEGER,
            open_time TEXT,
            close_time TEXT,
            collected_at TEXT
        )
    """)
    conn.commit()
    return conn


def ingest_recent(days_back: int = 3) -> dict:
    """
    Pull recently settled markets from Kalshi API.
    Only fetches markets that closed in the last N days to be efficient.
    Returns stats dict.
    """
    conn = init_db()
    c = conn.cursor()
    client = KalshiClient()
    
    c.execute("SELECT COUNT(*) FROM settled_markets")
    before = c.fetchone()[0]
    
    # Cutoff: only fetch markets closing after this time
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff_iso = cutoff.isoformat()
    
    new_count = 0
    updated_count = 0
    
    for city, cfg in CONFIG["cities"].items():
        for market_type, series_key in [("high", "kalshi_high"), ("low", "kalshi_low")]:
            series = cfg.get(series_key)
            if not series:
                continue
            
            log.info("Ingesting %s %s (%s)...", city, market_type, series)
            cursor = None
            
            while True:
                time.sleep(0.35)  # Rate limit
                try:
                    resp = client.get_markets(
                        series_ticker=series, 
                        status="settled", 
                        limit=200, 
                        cursor=cursor
                    )
                except Exception as e:
                    log.error("API error for %s: %s", series, e)
                    break
                
                markets = resp.get("markets", [])
                if not markets:
                    break
                
                # Check if we've gone past our cutoff
                oldest_close = markets[-1].get("close_time", "")
                if oldest_close and oldest_close < cutoff_iso:
                    # Filter to only recent ones and stop
                    markets = [m for m in markets if m.get("close_time", "") >= cutoff_iso]
                    _insert_markets(c, markets, city, market_type, series)
                    new_count += len(markets)
                    break
                
                _insert_markets(c, markets, city, market_type, series)
                new_count += len(markets)
                
                cursor = resp.get("cursor")
                if not cursor:
                    break
    
    conn.commit()
    
    c.execute("SELECT COUNT(*) FROM settled_markets")
    after = c.fetchone()[0]
    
    stats = {
        "before": before,
        "after": after,
        "new": after - before,
        "scanned": new_count,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    log.info("Ingestion complete: %d → %d (+%d new, %d scanned)", 
             before, after, stats["new"], new_count)
    
    conn.close()
    return stats


def _insert_markets(cursor, markets, city, market_type, series):
    """Insert/update markets into DB."""
    for m in markets:
        ticker = m.get("ticker", "")
        parts = ticker.split("-")
        event_date_str = parts[1] if len(parts) >= 2 else ""
        try:
            event_date = datetime.strptime(event_date_str, "%y%b%d").strftime("%Y-%m-%d")
        except ValueError:
            event_date = event_date_str
        
        cursor.execute("""INSERT OR REPLACE INTO settled_markets
            (ticker, event_ticker, series_ticker, city, market_type, event_date,
             floor_strike, cap_strike, result, last_price, yes_bid, yes_ask,
             volume, open_time, close_time, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ticker,
             "-".join(parts[:2]) if len(parts) >= 2 else ticker,
             series, city, market_type, event_date,
             m.get("floor_strike"), m.get("cap_strike"),
             m.get("result", ""), m.get("last_price", 0),
             m.get("yes_bid", 0), m.get("yes_ask", 0),
             m.get("volume", 0), m.get("open_time", ""),
             m.get("close_time", ""),
             datetime.now(timezone.utc).isoformat()))


def show_stats():
    """Show current backtest DB stats."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM settled_markets")
    total = c.fetchone()[0]
    
    c.execute("SELECT MIN(event_date), MAX(event_date) FROM settled_markets")
    date_range = c.fetchone()
    
    c.execute("""SELECT city, market_type, COUNT(*) 
                 FROM settled_markets GROUP BY city, market_type ORDER BY 3 DESC""")
    breakdown = c.fetchall()
    
    c.execute("""SELECT event_date, COUNT(*) FROM settled_markets 
                 WHERE event_date >= date('now', '-7 days') 
                 GROUP BY event_date ORDER BY 1""")
    recent = c.fetchall()
    
    print(f"\n📊 Backtest DB: {total:,} settled markets")
    print(f"   Date range: {date_range[0]} → {date_range[1]}")
    print(f"\n   By city/type:")
    for city, mtype, count in breakdown:
        print(f"     {city:3} {mtype:4}: {count:,}")
    
    if recent:
        print(f"\n   Last 7 days:")
        for date, count in recent:
            print(f"     {date}: {count}")
    
    print(f"\n   📈 At ~50/day, 30K target in ~{(30000 - total) // 50} days")
    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily backtest data ingestion")
    parser.add_argument("--days", type=int, default=3, help="Days back to scan (default: 3)")
    parser.add_argument("--stats", action="store_true", help="Show DB stats only")
    parser.add_argument("--full", action="store_true", help="Full re-scrape (all history)")
    args = parser.parse_args()
    
    if args.stats:
        show_stats()
    elif args.full:
        from backtest import init_db as bt_init, collect_settled_markets
        conn = bt_init()
        client = KalshiClient()
        collect_settled_markets(client, conn)
        conn.close()
        show_stats()
    else:
        stats = ingest_recent(days_back=args.days)
        show_stats()
