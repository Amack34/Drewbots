#!/usr/bin/env python3
"""
Paper Trade Settlement Sync — resolves paper trades against Kalshi market outcomes.

Checks all unsettled paper trades (both V1 and V2), queries Kalshi API for settlement
results, and updates P&L. Also generates accuracy reports.

Usage:
  python3 settle_paper.py              # Settle all unsettled trades
  python3 settle_paper.py --report     # Settle + print performance report
  python3 settle_paper.py --accuracy   # Settle + print prediction accuracy by city
"""
import sys
import os
import json
import time
import sqlite3
import logging
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

DB_PATH = CONFIG.get("db_path", os.path.join(os.path.dirname(__file__), "weather.db"))


def get_kalshi_client():
    """Initialize Kalshi API client."""
    from kalshi_trader import KalshiClient
    kalshi_cfg = CONFIG.get("kalshi", {})
    return KalshiClient(
        api_key_id=kalshi_cfg["api_key_id"],
        private_key_path=kalshi_cfg["private_key_path"]
    )


def settle_v2_paper_trades(client):
    """Settle V2 paper trades (A/B test) against Kalshi market outcomes."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get all unsettled V2 paper trades
    rows = c.execute("""
        SELECT id, ticker, side, suggested_price, estimated_temp, market_yes_price, version, city, market_type
        FROM v2_paper_trades WHERE settled = 0
    """).fetchall()
    
    if not rows:
        log.info("No unsettled V2 paper trades")
        conn.close()
        return 0
    
    # Group by ticker to minimize API calls
    ticker_trades = {}
    for row in rows:
        tid, ticker = row[0], row[1]
        if ticker not in ticker_trades:
            ticker_trades[ticker] = []
        ticker_trades[ticker].append(row)
    
    log.info("Checking %d unique tickers for %d unsettled V2 paper trades", len(ticker_trades), len(rows))
    
    settled_count = 0
    for ticker, trades in ticker_trades.items():
        try:
            time.sleep(0.35)  # rate limit
            mkt = client.get_market(ticker).get("market", {})
            status = mkt.get("status", "")
            result_str = mkt.get("result", "")  # "yes" or "no" or ""
            
            if status not in ("settled", "finalized") or not result_str:
                continue
            
            for trade in trades:
                tid, _, side, price, est_temp, mkt_yes, version, city, mtype = trade
                
                # Determine win/loss
                if side == "no":
                    won = (result_str == "no")  # NO wins when bracket didn't hit
                else:
                    won = (result_str == "yes")
                
                if won:
                    pnl = (100 - price)  # per contract, cents
                else:
                    pnl = -price
                
                # Try to get actual temp from settlement
                actual_temp = _get_actual_temp(client, ticker, city, mtype)
                
                c.execute("""UPDATE v2_paper_trades 
                    SET settled = 1, actual_temp = ?, pnl_cents = ?
                    WHERE id = ?""", (actual_temp, pnl, tid))
                
                settled_count += 1
                outcome = "WIN" if won else "LOSS"
                log.info("V2 SETTLED [%s]: %s %s @ %d¢ → %s (%+d¢) | est=%.0f°F actual=%s",
                         version, ticker, side, price, outcome, pnl,
                         est_temp, f"{actual_temp:.0f}°F" if actual_temp else "?")
        
        except Exception as e:
            log.error("Failed to check %s: %s", ticker, e)
            continue
    
    conn.commit()
    conn.close()
    log.info("V2 settlement sync: %d trades settled", settled_count)
    return settled_count


def settle_v1_paper_trades(client):
    """Settle V1 paper trades against Kalshi market outcomes."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    rows = c.execute("""
        SELECT id, market_ticker, side, price_cents, contracts, city, market_type
        FROM paper_trades WHERE settled = 0
    """).fetchall()
    
    if not rows:
        log.info("No unsettled V1 paper trades")
        conn.close()
        return 0
    
    ticker_trades = {}
    for row in rows:
        ticker = row[1]
        if ticker not in ticker_trades:
            ticker_trades[ticker] = []
        ticker_trades[ticker].append(row)
    
    log.info("Checking %d unique tickers for %d unsettled V1 paper trades", len(ticker_trades), len(rows))
    
    settled_count = 0
    now = datetime.now(timezone.utc).isoformat()
    
    for ticker, trades in ticker_trades.items():
        try:
            time.sleep(0.35)
            mkt = client.get_market(ticker).get("market", {})
            status = mkt.get("status", "")
            result_str = mkt.get("result", "")
            
            if status not in ("settled", "finalized") or not result_str:
                continue
            
            for trade in trades:
                tid, _, side, price, contracts, city, mtype = trade
                
                if side == "no":
                    won = (result_str == "no")
                else:
                    won = (result_str == "yes")
                
                if won:
                    pnl = (100 - price) * contracts
                    result_text = "WON"
                else:
                    pnl = -(price * contracts)
                    result_text = "LOST"
                
                c.execute("""UPDATE paper_trades 
                    SET settled = 1, settlement_result = ?, pnl_cents = ?, settled_at = ?
                    WHERE id = ?""", (result_text, pnl, now, tid))
                
                # Update balance
                if won:
                    balance = c.execute("SELECT balance_cents FROM paper_balance ORDER BY id DESC LIMIT 1").fetchone()[0]
                    new_balance = balance + 100 * contracts
                    c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (?, ?)",
                              (new_balance, now))
                
                settled_count += 1
                log.info("V1 SETTLED: %s %s x%d @ %d¢ → %s (%+d¢)",
                         ticker, side, contracts, price, result_text, pnl)
        
        except Exception as e:
            log.error("Failed to check %s: %s", ticker, e)
            continue
    
    conn.commit()
    conn.close()
    log.info("V1 settlement sync: %d trades settled", settled_count)
    return settled_count


def _get_actual_temp(client, ticker, city, market_type):
    """Try to extract actual temperature from market data or NWS observations."""
    try:
        # Parse the event date from the ticker (e.g., KXHIGHNY-26FEB19)
        parts = ticker.split("-")
        if len(parts) >= 2:
            date_part = parts[1]  # e.g., "26FEB19"
            # Could query NWS for actual temp but for now just check the event
            event_ticker = "-".join(parts[:2])
            time.sleep(0.35)
            event = client.get_event(event_ticker)
            if event and "event" in event:
                # Some events have settlement data in title/description
                pass
    except Exception:
        pass
    return None


def print_performance_report():
    """Print comprehensive performance report from settled paper trades."""
    conn = sqlite3.connect(DB_PATH)
    
    print("\n" + "=" * 70)
    print("  PAPER TRADING PERFORMANCE REPORT")
    print("=" * 70)
    
    # V2 Paper (A/B Test)
    print("\n--- V2 PAPER TRADES (A/B Test) ---")
    for version in ['v1', 'v2']:
        stats = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl_cents < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN settled = 0 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN settled = 1 THEN pnl_cents ELSE 0 END) as total_pnl,
                AVG(CASE WHEN settled = 1 AND pnl_cents > 0 THEN pnl_cents END) as avg_win,
                AVG(CASE WHEN settled = 1 AND pnl_cents < 0 THEN pnl_cents END) as avg_loss
            FROM v2_paper_trades WHERE version = ?
        """, (version,)).fetchone()
        
        total, wins, losses, pending, total_pnl, avg_win, avg_loss = stats
        wins = wins or 0
        losses = losses or 0
        settled = wins + losses
        wr = (wins / settled * 100) if settled > 0 else 0
        label = "NEW CODE (with fixes)" if version == "v1" else "OLD CODE (baseline)"
        
        print(f"\n  {version.upper()} — {label}")
        print(f"  Total: {total} | Settled: {settled} ({wins}W/{losses}L) | Pending: {pending}")
        print(f"  Win Rate: {wr:.1f}% | P&L: ${(total_pnl or 0)/100:+.2f}")
        if avg_win:
            print(f"  Avg Win: {avg_win:+.0f}¢ | Avg Loss: {avg_loss or 0:.0f}¢")
    
    # By city
    print("\n--- BY CITY (V2 settled only) ---")
    cities = conn.execute("""
        SELECT city, version,
            COUNT(*) as total,
            SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as wins,
            SUM(pnl_cents) as pnl
        FROM v2_paper_trades WHERE settled = 1
        GROUP BY city, version ORDER BY city, version
    """).fetchall()
    
    for city, version, total, wins, pnl in cities:
        wins = wins or 0
        wr = (wins / total * 100) if total > 0 else 0
        print(f"  {city} [{version}]: {total} trades, {wr:.0f}% WR, ${(pnl or 0)/100:+.2f}")
    
    # Prediction accuracy
    print("\n--- PREDICTION ACCURACY (V2 settled with actuals) ---")
    accuracy = conn.execute("""
        SELECT city, version,
            COUNT(*) as n,
            AVG(ABS(estimated_temp - actual_temp)) as mae,
            MAX(ABS(estimated_temp - actual_temp)) as max_err
        FROM v2_paper_trades 
        WHERE settled = 1 AND actual_temp IS NOT NULL
        GROUP BY city, version ORDER BY city, version
    """).fetchall()
    
    if accuracy:
        for city, version, n, mae, max_err in accuracy:
            print(f"  {city} [{version}]: n={n}, MAE={mae:.1f}°F, Max Error={max_err:.1f}°F")
    else:
        print("  No accuracy data yet (actuals not populated)")
    
    # V1 Paper
    print("\n--- V1 PAPER TRADES ---")
    v1 = conn.execute("""
        SELECT COUNT(*),
            SUM(CASE WHEN settlement_result='WON' THEN 1 ELSE 0 END),
            SUM(CASE WHEN settlement_result='LOST' THEN 1 ELSE 0 END),
            SUM(CASE WHEN settled=0 THEN 1 ELSE 0 END),
            SUM(pnl_cents)
        FROM paper_trades
    """).fetchone()
    total, wins, losses, pending, pnl = v1
    wins = wins or 0
    losses = losses or 0
    settled = wins + losses
    wr = (wins / settled * 100) if settled > 0 else 0
    print(f"  Total: {total} | Settled: {settled} ({wins}W/{losses}L) | Pending: {pending}")
    print(f"  Win Rate: {wr:.1f}% | P&L: ${(pnl or 0)/100:+.2f}")
    
    print("\n" + "=" * 70)
    conn.close()


def print_accuracy_report():
    """Print detailed prediction accuracy analysis."""
    conn = sqlite3.connect(DB_PATH)
    
    print("\n" + "=" * 70)
    print("  PREDICTION ACCURACY ANALYSIS")
    print("=" * 70)
    
    # From prediction_log if available
    predictions = conn.execute("""
        SELECT city, 
            COUNT(*) as n,
            AVG(ABS(estimated_temp - actual_temp)) as mae,
            AVG((estimated_temp - actual_temp)) as bias,
            MAX(ABS(estimated_temp - actual_temp)) as max_err
        FROM prediction_log
        WHERE actual_temp IS NOT NULL
        GROUP BY city ORDER BY mae DESC
    """).fetchall()
    
    if predictions:
        print("\n--- FROM PREDICTION LOG ---")
        for city, n, mae, bias, max_err in predictions:
            direction = "warm" if bias > 0 else "cold"
            print(f"  {city}: n={n}, MAE={mae:.1f}°F, Bias={bias:+.1f}°F ({direction}), Max={max_err:.1f}°F")
            
            # Recommend std_dev adjustment
            current_std = 3.0  # default
            if mae > current_std:
                print(f"    ⚠️ RECOMMEND: Increase std_dev to {mae * 1.2:.1f}°F (currently {current_std})")
    else:
        print("\n  No prediction accuracy data in prediction_log")
    
    # From v2 paper trades with actuals
    v2_acc = conn.execute("""
        SELECT city, version,
            COUNT(*) as n,
            AVG(ABS(estimated_temp - actual_temp)) as mae,
            AVG((estimated_temp - actual_temp)) as bias
        FROM v2_paper_trades
        WHERE settled = 1 AND actual_temp IS NOT NULL
        GROUP BY city, version ORDER BY city
    """).fetchall()
    
    if v2_acc:
        print("\n--- FROM V2 PAPER TRADES ---")
        for city, ver, n, mae, bias in v2_acc:
            print(f"  {city} [{ver}]: n={n}, MAE={mae:.1f}°F, Bias={bias:+.1f}°F")
    
    print("\n" + "=" * 70)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Trade Settlement Sync")
    parser.add_argument("--report", action="store_true", help="Print performance report after settling")
    parser.add_argument("--accuracy", action="store_true", help="Print prediction accuracy report")
    parser.add_argument("--dry-run", action="store_true", help="Check settlements without updating DB")
    args = parser.parse_args()
    
    client = get_kalshi_client()
    
    # Settle both V1 and V2
    v2_count = settle_v2_paper_trades(client)
    v1_count = settle_v1_paper_trades(client)
    
    print(f"\nSettled: {v2_count} V2 trades, {v1_count} V1 trades")
    
    if args.report or (v2_count + v1_count > 0):
        print_performance_report()
    
    if args.accuracy:
        print_accuracy_report()
