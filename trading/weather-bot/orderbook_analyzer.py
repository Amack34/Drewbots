#!/usr/bin/env python3
"""
Kalshi Order Book Analyzer for Weather Trading Bot.
Snapshots order books, stores in SQLite, and provides analysis functions.
"""

import json
import logging
import sqlite3
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

from kalshi_trader import KalshiClient, CONFIG

DB_PATH = CONFIG["db_path"]
LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "orderbook.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("orderbook")

SERIES_TICKERS = ["KXHIGHNY", "KXHIGHPHIL", "KXHIGHMIA", "KXHIGHTBOS", "KXHIGHTDC", "KXHIGHTATL",
                   "KXLOWTNYC", "KXLOWTPHIL", "KXLOWTMIA"]


def init_db():
    """Create orderbook_snapshots table if not exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            snapshot_time TEXT NOT NULL,
            yes_bids TEXT,
            yes_asks TEXT,
            no_bids TEXT,
            no_asks TEXT,
            spread_cents REAL,
            yes_depth_total REAL,
            no_depth_total REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ob_ticker_time ON orderbook_snapshots(ticker, snapshot_time)")
    conn.commit()
    conn.close()


def get_active_weather_tickers(client: KalshiClient) -> list[str]:
    """Discover all active weather market tickers from configured series."""
    tickers = []
    # Also check city config for series tickers
    series_set = set(SERIES_TICKERS)
    for city_cfg in CONFIG.get("cities", {}).values():
        for key in ("kalshi_high", "kalshi_low"):
            v = city_cfg.get(key)
            if v:
                series_set.add(v)

    for series in sorted(series_set):
        try:
            resp = client.get_markets(series_ticker=series, status="open", limit=100)
            markets = resp.get("markets", [])
            for m in markets:
                t = m.get("ticker")
                if t:
                    tickers.append(t)
            log.info("Series %s: %d active markets", series, len(markets))
        except Exception as e:
            log.warning("Failed to get markets for series %s: %s", series, e)

    log.info("Total active weather tickers: %d", len(tickers))
    return tickers


def _compute_spread(yes_bids, yes_asks) -> float | None:
    """Compute spread in cents between best yes bid and best yes ask."""
    if not yes_bids or not yes_asks:
        return None
    best_bid = max(p for p, q in yes_bids)
    best_ask = min(p for p, q in yes_asks)
    return best_ask - best_bid


def _total_depth(levels) -> int:
    """Sum quantity across all price levels."""
    if not levels:
        return 0
    return sum(q for p, q in levels)


def snapshot_orderbook(client: KalshiClient, ticker: str) -> dict | None:
    """Fetch and store a single orderbook snapshot."""
    try:
        resp = client.get_orderbook(ticker)
    except Exception as e:
        log.warning("Failed to get orderbook for %s: %s", ticker, e)
        return None

    ob = resp.get("orderbook", {})
    yes_levels = ob.get("yes", [])
    no_levels = ob.get("no", [])

    # Kalshi returns [[price, quantity], ...] for each side
    # yes side: bids are buy-yes orders, asks are implied from no side
    # Actually the API returns yes and no as separate books
    # yes = list of [price, quantity] resting yes orders
    # no = list of [price, quantity] resting no orders
    # A yes order at price P is equivalent to a no order at (100-P)
    # Best yes bid = highest price in yes list
    # Best yes ask = 100 - highest price in no list

    yes_bids = yes_levels or []  # people wanting to buy yes
    no_bids = no_levels or []    # people wanting to buy no (= sell yes)

    # Compute yes asks from no bids: a no bid at P means yes ask at 100-P
    yes_asks = [[100 - p, q] for p, q in no_bids] if no_bids else []

    spread = _compute_spread(yes_bids, yes_asks) if yes_bids and yes_asks else None
    yes_depth = _total_depth(yes_levels)
    no_depth = _total_depth(no_levels)

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO orderbook_snapshots
        (ticker, snapshot_time, yes_bids, yes_asks, no_bids, no_asks, spread_cents, yes_depth_total, no_depth_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker, now,
        json.dumps(yes_bids), json.dumps(yes_asks),
        json.dumps(no_bids), json.dumps([]),
        spread, yes_depth, no_depth
    ))
    conn.commit()
    conn.close()

    return {
        "ticker": ticker,
        "spread_cents": spread,
        "yes_depth": yes_depth,
        "no_depth": no_depth,
        "yes_levels": len(yes_bids),
        "no_levels": len(no_bids),
    }


def snapshot_all_markets(client: KalshiClient = None) -> list[dict]:
    """Snapshot order books for all active weather markets."""
    if client is None:
        client = KalshiClient()

    tickers = get_active_weather_tickers(client)
    results = []

    for i, ticker in enumerate(tickers):
        result = snapshot_orderbook(client, ticker)
        if result:
            results.append(result)
        # KalshiClient._request already has 350ms rate limiting

    log.info("Snapshotted %d/%d markets", len(results), len(tickers))
    return results


# ---- Analysis Functions ----

def get_spread_history(ticker: str, hours: int = 24) -> list[dict]:
    """Get spread over time for a ticker."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT snapshot_time, spread_cents FROM orderbook_snapshots
        WHERE ticker = ? AND snapshot_time > ?
        ORDER BY snapshot_time
    """, (ticker, cutoff)).fetchall()
    conn.close()
    return [{"time": r[0], "spread": r[1]} for r in rows]


def detect_spoofing(ticker: str) -> list[dict]:
    """Detect potential spoofing: large orders (>10 contracts) that vanish within 2 snapshots."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT id, snapshot_time, yes_bids, no_bids FROM orderbook_snapshots
        WHERE ticker = ?
        ORDER BY snapshot_time DESC LIMIT 20
    """, (ticker,)).fetchall()
    conn.close()

    if len(rows) < 3:
        return []

    alerts = []
    # Compare consecutive snapshots
    for i in range(len(rows) - 2):
        curr_bids = set()
        for side_json in [rows[i][2], rows[i][3]]:
            if side_json:
                levels = json.loads(side_json)
                if levels:
                    for p, q in levels:
                        if q > 10:
                            curr_bids.add((p, q))

        if not curr_bids:
            continue

        # Check if these large orders are gone 2 snapshots later
        future_bids = set()
        for j in [i + 1, i + 2]:
            if j < len(rows):
                for side_json in [rows[j][2], rows[j][3]]:
                    if side_json:
                        levels = json.loads(side_json)
                        if levels:
                            for p, q in levels:
                                if q > 5:
                                    future_bids.add((p, q))

        vanished = curr_bids - future_bids
        for p, q in vanished:
            alerts.append({
                "time": rows[i][1],
                "price": p,
                "quantity": q,
                "note": f"Large order ({q} contracts @ {p}¢) appeared then vanished"
            })

    return alerts


def best_entry_windows(ticker: str) -> list[dict]:
    """Find hours of day when spreads are historically widest (cheapest entry)."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT snapshot_time, spread_cents FROM orderbook_snapshots
        WHERE ticker = ? AND spread_cents IS NOT NULL
    """, (ticker,)).fetchall()
    conn.close()

    if not rows:
        return []

    by_hour = defaultdict(list)
    for ts, spread in rows:
        try:
            hour = datetime.fromisoformat(ts).hour
            by_hour[hour].append(spread)
        except (ValueError, TypeError):
            continue

    results = []
    for hour in sorted(by_hour.keys()):
        spreads = by_hour[hour]
        avg = sum(spreads) / len(spreads)
        results.append({"hour_utc": hour, "avg_spread": round(avg, 2), "samples": len(spreads)})

    results.sort(key=lambda x: x["avg_spread"], reverse=True)
    return results


def liquidity_score(ticker: str) -> dict:
    """Total depth within 5¢ of mid price from latest snapshot."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("""
        SELECT yes_bids, no_bids FROM orderbook_snapshots
        WHERE ticker = ?
        ORDER BY snapshot_time DESC LIMIT 1
    """, (ticker,)).fetchone()
    conn.close()

    if not row:
        return {"ticker": ticker, "score": 0, "detail": "no data"}

    yes_bids = json.loads(row[0]) if row[0] else []
    no_bids = json.loads(row[1]) if row[1] else []

    # Find mid price
    best_yes_bid = max((p for p, q in yes_bids), default=None)
    best_no_bid = max((p for p, q in no_bids), default=None)

    if best_yes_bid is None and best_no_bid is None:
        return {"ticker": ticker, "score": 0, "detail": "empty book"}

    if best_yes_bid and best_no_bid:
        yes_ask = 100 - best_no_bid
        mid = (best_yes_bid + yes_ask) / 2
    elif best_yes_bid:
        mid = best_yes_bid
    else:
        mid = 100 - best_no_bid

    # Count depth within 5¢ of mid
    depth = 0
    for p, q in yes_bids:
        if abs(p - mid) <= 5:
            depth += q
    for p, q in no_bids:
        equiv = 100 - p
        if abs(equiv - mid) <= 5:
            depth += q

    return {"ticker": ticker, "score": depth, "mid_price": round(mid, 1)}


def print_summary(results: list[dict]):
    """Print a summary of the snapshot cycle."""
    print(f"\n{'='*70}")
    print(f"  ORDERBOOK SNAPSHOT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}")
    print(f"  {'Ticker':<30} {'Spread':>8} {'Yes Depth':>10} {'No Depth':>10}")
    print(f"  {'-'*30} {'-'*8} {'-'*10} {'-'*10}")

    for r in sorted(results, key=lambda x: x["ticker"]):
        spread_str = f"{r['spread_cents']}¢" if r['spread_cents'] is not None else "N/A"
        print(f"  {r['ticker']:<30} {spread_str:>8} {r['yes_depth']:>10} {r['no_depth']:>10}")

    print(f"\n  Total markets: {len(results)}")

    # Spoofing check on markets with data
    spoof_alerts = []
    for r in results:
        alerts = detect_spoofing(r["ticker"])
        if alerts:
            spoof_alerts.extend([(r["ticker"], a) for a in alerts])

    if spoof_alerts:
        print(f"\n  ⚠️  SPOOFING ALERTS:")
        for ticker, alert in spoof_alerts[:10]:
            print(f"    {ticker}: {alert['note']}")
    else:
        print(f"\n  ✅ No spoofing detected")

    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Kalshi Order Book Analyzer")
    parser.add_argument("--continuous", action="store_true", help="Run every 5 minutes")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds (default: 300)")
    args = parser.parse_args()

    init_db()
    client = KalshiClient()

    if args.continuous:
        log.info("Starting continuous mode (every %ds)", args.interval)
        while True:
            try:
                results = snapshot_all_markets(client)
                print_summary(results)
            except Exception as e:
                log.error("Snapshot cycle failed: %s", e)
            time.sleep(args.interval)
    else:
        results = snapshot_all_markets(client)
        print_summary(results)


if __name__ == "__main__":
    main()
