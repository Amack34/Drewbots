#!/usr/bin/env python3
"""
Sync actual temperatures and fees into trade_journal and prediction_log.
Pulls settlement data from Kalshi API to backfill:
1. Actual temps into prediction_log (for model calibration)
2. Fees into trade_journal (for true P&L)
3. Bracket data for early trades missing it

Run daily or on-demand.
"""

import sqlite3
import logging
import time
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from kalshi_trader import KalshiClient, CONFIG

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sync_actuals.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DB_PATH = Path(CONFIG["db_path"])
RATE_LIMIT = 0.35  # seconds between API calls

# Map city codes to Kalshi event prefixes
CITY_MAP = {
    "NYC": "KXHIGHNY",
    "PHI": "KXHIGHPHIL", 
    "MIA": "KXHIGHMIA",
    "BOS": "KXHIGHTBOS",
    "DC": "KXHIGHTDC",
    "ATL": "KXHIGHTATL",
}


def sync_prediction_actuals():
    """Backfill actual_temp_f in prediction_log using actuals already in trade_journal."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # First, build a map of (city, market_type, date) -> actual_temp from trade_journal
    c.execute("""SELECT city, market_type, date(created_at), actual_temp_f 
                 FROM trade_journal 
                 WHERE actual_temp_f IS NOT NULL
                 GROUP BY city, market_type, date(created_at)""")
    actuals_map = {}
    for city, mtype, dt, actual in c.fetchall():
        actuals_map[(city, mtype, dt)] = actual
    
    # Now update prediction_log entries that match
    c.execute("""SELECT id, city, market_type, estimated_temp_f, created_at 
                 FROM prediction_log WHERE actual_temp_f IS NULL""")
    missing = c.fetchall()
    
    if not missing:
        log.info("All predictions have actuals — nothing to sync")
        return
    
    updated = 0
    for row_id, city, market_type, est_temp, created_at in missing:
        pred_date = created_at[:10]
        key = (city, market_type, pred_date)
        actual = actuals_map.get(key)
        
        if actual is not None:
            error = actual - est_temp if est_temp else None
            c.execute("""UPDATE prediction_log 
                        SET actual_temp_f=?, error_f=?, settled_at=datetime('now')
                        WHERE id=?""", (actual, error, row_id))
            updated += 1
    
    conn.commit()
    conn.close()
    log.info("Updated %d/%d predictions with actuals (from trade_journal)", updated, len(missing))


def _get_actual_temp(client, city, market_type, date_str):
    """Get actual temperature from a settled Kalshi market's expiration_value."""
    # Build event ticker: e.g., KXHIGHNY-26FEB18
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_suffix = dt.strftime("-%y%b%d").upper()  # -26FEB18
    except ValueError:
        return None
    
    # Determine the event prefix
    prefix_map = {
        ("NYC", "high"): "KXHIGHNY",
        ("NYC", "low"): "KXLOWTNYC",
        ("PHI", "high"): "KXHIGHPHIL",
        ("PHI", "low"): "KXLOWTPHIL",
        ("MIA", "high"): "KXHIGHMIA",
        ("MIA", "low"): "KXLOWTMIA",
        ("BOS", "high"): "KXHIGHTBOS",
        ("DC", "high"): "KXHIGHTDC",
        ("ATL", "high"): "KXHIGHTATL",
    }
    
    prefix = prefix_map.get((city, market_type))
    if not prefix:
        return None
    
    event_ticker = prefix + date_suffix
    
    # Try a known bracket ticker to get expiration_value
    # Use B-bracket with a common strike — any market in the event has the same expiration_value
    for strike in ["B75.5", "B40.5", "B50.5", "B80.5", "B35.5", "B60.5", "B70.5", "B45.5"]:
        test_ticker = f"{event_ticker}-{strike}"
        try:
            time.sleep(RATE_LIMIT)
            resp = client.get_market(test_ticker)
            mkt = resp.get("market", {})
            exp_val = mkt.get("expiration_value", "")
            if exp_val:
                return float(exp_val)
        except Exception:
            continue
    
    return None


def sync_trade_fees():
    """Backfill fees from Kalshi order data into trade_journal."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # Get trades missing fees
    c.execute("""SELECT id, order_id FROM trade_journal 
                 WHERE (fees_cents IS NULL OR fees_cents=0) AND order_id IS NOT NULL AND order_id != ''""")
    missing = c.fetchall()
    
    if not missing:
        log.info("All trades have fees — nothing to sync")
        return
    
    log.info("Found %d trades missing fees", len(missing))
    
    client = KalshiClient()
    updated = 0
    
    for row_id, order_id in missing:
        try:
            time.sleep(RATE_LIMIT)
            order = client.get_order(order_id)
            if isinstance(order, dict):
                order_data = order.get("order", order)
                # Kalshi reports fees in the order response
                taker_fee = order_data.get("taker_fees", 0)
                if taker_fee:
                    c.execute("UPDATE trade_journal SET fees_cents=? WHERE id=?", (taker_fee, row_id))
                    updated += 1
        except Exception as e:
            log.error("Failed to get fees for order %s: %s", order_id, e)
    
    conn.commit()
    conn.close()
    log.info("Updated %d/%d trades with fees", updated, len(missing))


def sync_trade_actuals():
    """Backfill actual_temp_f in trade_journal from settled markets."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    c = conn.cursor()
    
    c.execute("""SELECT id, ticker, city, market_type, created_at 
                 FROM trade_journal WHERE actual_temp_f IS NULL AND settled=1""")
    missing = c.fetchall()
    
    if not missing:
        log.info("All settled trades have actual temps")
        return
    
    log.info("Found %d settled trades missing actual temps", len(missing))
    
    client = KalshiClient()
    seen = {}
    updated = 0
    
    for row_id, ticker, city, market_type, created_at in missing:
        # Extract event ticker from market ticker (everything before the last dash+bracket)
        event_ticker = "-".join(ticker.split("-")[:-1]) if ticker else None
        
        if event_ticker and event_ticker in seen:
            actual = seen[event_ticker]
        elif ticker:
            try:
                time.sleep(RATE_LIMIT)
                resp = client.get_market(ticker)
                mkt = resp.get("market", {})
                exp_val = mkt.get("expiration_value", "")
                actual = float(exp_val) if exp_val else None
                if event_ticker:
                    seen[event_ticker] = actual
            except Exception as e:
                log.error("Failed to get actual for %s: %s", ticker, e)
                actual = None
        else:
            actual = None
        
        if actual is not None:
            est_temp = None
            c.execute("SELECT estimated_temp_f FROM trade_journal WHERE id=?", (row_id,))
            row = c.fetchone()
            if row and row[0]:
                est_temp = row[0]
            
            error = actual - est_temp if est_temp else None
            c.execute("""UPDATE trade_journal 
                        SET actual_temp_f=?, prediction_error_f=?
                        WHERE id=?""", (actual, error, row_id))
            updated += 1
    
    conn.commit()
    conn.close()
    log.info("Updated %d/%d trades with actual temps", updated, len(missing))


def generate_daily_summary():
    """Generate a daily P&L summary and print it."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    c.execute("""SELECT date(created_at) as dt,
        COUNT(*) as trades,
        SUM(CASE WHEN settlement_result='win' THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN settlement_result='loss' THEN 1 ELSE 0 END) as losses,
        SUM(CASE WHEN settled=0 THEN 1 ELSE 0 END) as open_trades,
        COALESCE(SUM(CASE WHEN settled=1 THEN pnl_cents ELSE 0 END), 0) as realized_pnl,
        COALESCE(SUM(fees_cents), 0) as total_fees
        FROM trade_journal
        GROUP BY date(created_at)
        ORDER BY date(created_at)""")
    
    print("\n=== DAILY P&L SUMMARY ===")
    print(f"{'Date':<12} {'Trades':>6} {'W-L':>7} {'WR':>5} {'Gross':>8} {'Fees':>6} {'Net':>8} {'Open':>5}")
    print("-" * 65)
    
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0
    total_fees = 0
    
    for row in c.fetchall():
        dt, trades, wins, losses, open_t, pnl, fees = row
        wins = wins or 0
        losses = losses or 0
        wr = wins/(wins+losses)*100 if (wins+losses) > 0 else 0
        net = pnl - fees
        print(f"{dt:<12} {trades:>6} {wins}W-{losses}L {wr:>4.0f}% {pnl/100:>+7.2f} {fees/100:>5.2f} {net/100:>+7.2f} {open_t:>5}")
        total_trades += trades
        total_wins += wins
        total_losses += losses
        total_pnl += pnl
        total_fees += fees
    
    print("-" * 65)
    total_wr = total_wins/(total_wins+total_losses)*100 if (total_wins+total_losses) > 0 else 0
    print(f"{'TOTAL':<12} {total_trades:>6} {total_wins}W-{total_losses}L {total_wr:>4.0f}% {total_pnl/100:>+7.2f} {total_fees/100:>5.2f} {(total_pnl-total_fees)/100:>+7.2f}")
    
    # Prediction accuracy
    c.execute("""SELECT city, market_type, COUNT(*), AVG(ABS(error_f)), AVG(error_f)
                 FROM prediction_log WHERE actual_temp_f IS NOT NULL
                 GROUP BY city, market_type""")
    rows = c.fetchall()
    if rows:
        print("\n=== PREDICTION ACCURACY ===")
        print(f"{'City':<5} {'Type':<5} {'Count':>5} {'MAE':>6} {'Bias':>7}")
        for city, mtype, cnt, mae, bias in rows:
            print(f"{city:<5} {mtype:<5} {cnt:>5} {mae:>5.1f}°F {bias:>+6.1f}°F")
    
    conn.close()


if __name__ == "__main__":
    import sys
    log.info("=== Starting actuals sync ===")
    sync_trade_actuals()      # API calls — gets actuals into trade_journal
    sync_prediction_actuals() # Local — propagates from trade_journal to prediction_log
    # sync_trade_fees()  # TODO: need get_order API method
    generate_daily_summary()
    log.info("=== Sync complete ===")
