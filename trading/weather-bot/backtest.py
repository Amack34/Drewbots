#!/usr/bin/env python3
"""
Backtester for Kalshi weather trading strategy.
Uses settled market results to simulate various accuracy scenarios.
Key question: If our NWS model estimates temp within ±X°F, what's the P&L?
"""

import json
import time
import math
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from kalshi_trader import KalshiClient, CONFIG

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(__file__).parent / "backtest.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "backtest.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("backtest")


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


def collect_settled_markets(client: KalshiClient, conn: sqlite3.Connection):
    """Download all settled weather markets from Kalshi."""
    c = conn.cursor()
    total = 0
    for city, cfg in CONFIG["cities"].items():
        for market_type, series_key in [("high", "kalshi_high"), ("low", "kalshi_low")]:
            series = cfg.get(series_key)
            if not series:
                continue
            log.info("Fetching %s (%s)...", series, city)
            cursor = None
            while True:
                time.sleep(0.2)
                try:
                    resp = client.get_markets(series_ticker=series, status="settled", limit=200, cursor=cursor)
                except Exception as e:
                    log.error("Failed: %s", e)
                    break
                markets = resp.get("markets", [])
                if not markets:
                    break
                for m in markets:
                    ticker = m.get("ticker", "")
                    parts = ticker.split("-")
                    event_date_str = parts[1] if len(parts) >= 2 else ""
                    try:
                        event_date = datetime.strptime(event_date_str, "%y%b%d").strftime("%Y-%m-%d")
                    except ValueError:
                        event_date = event_date_str
                    c.execute("""INSERT OR REPLACE INTO settled_markets
                        (ticker,event_ticker,series_ticker,city,market_type,event_date,
                         floor_strike,cap_strike,result,last_price,yes_bid,yes_ask,
                         volume,open_time,close_time,collected_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (ticker, "-".join(parts[:2]) if len(parts) >= 2 else ticker,
                         series, city, market_type, event_date,
                         m.get("floor_strike"), m.get("cap_strike"),
                         m.get("result", ""), m.get("last_price", 0),
                         m.get("yes_bid", 0), m.get("yes_ask", 0),
                         m.get("volume", 0), m.get("open_time", ""),
                         m.get("close_time", ""), datetime.now(timezone.utc).isoformat()))
                    total += 1
                cursor = resp.get("cursor")
                if not cursor:
                    break
    conn.commit()
    log.info("Collected %d settled markets", total)
    return total


def run_backtest(conn: sqlite3.Connection, config: dict) -> dict:
    """
    Simulate our strategy against historical settled markets.
    
    Strategy simulation:
    - For each day/city, find the winning bracket (result=yes) = actual temp
    - Simulate our NWS estimate with configurable accuracy (±error °F)
    - Our estimate picks a bracket; we buy it if price is cheap enough
    - Use gaussian probability model (same as signal_generator.py)
    - Track P&L with fees, position sizing, take-profit
    """
    c = conn.cursor()
    
    # Config
    accuracy_std = config.get("accuracy_std_f", 3.0)  # Our NWS estimate std dev in °F
    max_entry_price = config.get("max_entry_price", 15)  # Max price we'd pay (cents)
    min_edge_pct = config.get("min_edge_pct", CONFIG["risk"]["min_edge_pct"])
    max_trades_day = config.get("max_trades_per_day", CONFIG["risk"]["max_trades_per_day"])
    max_contracts = config.get("max_contracts", CONFIG["risk"]["max_contracts_per_trade"])
    take_profit_pct = config.get("take_profit_pct", CONFIG["risk"].get("take_profit_pct", 35))
    bankroll_start = config.get("bankroll_cents", 3000)
    max_position_pct = config.get("max_position_pct", CONFIG["risk"]["max_position_pct"])
    
    # Get unique event dates with their markets
    c.execute("""
        SELECT event_date, city, market_type, ticker, floor_strike, cap_strike, 
               result, last_price, yes_bid, yes_ask, volume
        FROM settled_markets 
        WHERE result IN ('yes', 'no')
        ORDER BY event_date, city
    """)
    rows = c.fetchall()
    
    # Group by (date, city, market_type)
    day_city = defaultdict(list)
    for r in rows:
        key = (r[0], r[1], r[2])
        day_city[key].append({
            "ticker": r[3], "floor": r[4], "cap": r[5],
            "result": r[6], "last_price": r[7],
            "yes_bid": r[8], "yes_ask": r[9], "volume": r[10],
        })
    
    # Simulation
    import random
    random.seed(42)  # Reproducible
    
    bankroll = bankroll_start
    peak = bankroll
    max_dd = 0
    all_trades = []
    daily_pnl = []
    dates_seen = set()
    
    sorted_keys = sorted(day_city.keys())
    
    for date_str, city, mtype in sorted_keys:
        markets = day_city[(date_str, city, mtype)]
        
        # Find actual winning bracket
        winners = [m for m in markets if m["result"] == "yes"]
        if not winners:
            continue
        
        actual_bracket = winners[0]
        actual_floor = actual_bracket["floor"] or 0
        actual_cap = actual_bracket["cap"] or (actual_floor + 5)
        actual_temp = (actual_floor + actual_cap) / 2  # Midpoint of winning bracket
        
        # Simulate our NWS estimate (actual + gaussian noise)
        estimate_error = random.gauss(0, accuracy_std)
        our_estimate = actual_temp + estimate_error
        
        # Check daily trade limit
        today_trades = sum(1 for t in all_trades if t["date"] == date_str)
        if today_trades >= max_trades_day:
            continue
        
        # Find which bracket our estimate falls in
        target_bracket = None
        for m in markets:
            floor = m["floor"] or 0
            cap = m["cap"] or (floor + 5)
            if floor <= our_estimate <= cap:
                target_bracket = m
                break
        
        if not target_bracket:
            continue
        
        # Calculate our probability using gaussian CDF (same as signal_generator)
        bracket_floor = target_bracket["floor"] or 0
        bracket_cap = target_bracket["cap"] or (bracket_floor + 5)
        
        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        
        prob_in_bracket = norm_cdf((bracket_cap - our_estimate) / accuracy_std) - \
                          norm_cdf((bracket_floor - our_estimate) / accuracy_std)
        
        # Simulate realistic pre-settlement market price
        # Settled prices are always 99/1 — useless for entry price
        # Model: market consensus is close to actual temp, priced via gaussian
        # Market knows actual temp ±2°F (market is well-calibrated)
        market_consensus = actual_temp + random.gauss(0, 2.0)
        bracket_mid = (bracket_floor + bracket_cap) / 2
        bracket_width = bracket_cap - bracket_floor
        
        # Market-implied probability (how the market would price this bracket)
        market_prob_est = norm_cdf((bracket_cap - market_consensus) / 3.0) - \
                          norm_cdf((bracket_floor - market_consensus) / 3.0)
        
        # Convert to price in cents (1-99), add some noise
        entry_price = max(1, min(99, int(market_prob_est * 100 + random.gauss(0, 2))))
        
        if entry_price > max_entry_price:
            continue
        
        market_prob = entry_price / 100.0
        
        # Edge check
        if market_prob > 0:
            edge_pct = ((prob_in_bracket - market_prob) / market_prob) * 100
        else:
            edge_pct = 0
        
        if edge_pct < min_edge_pct:
            continue
        
        # Position sizing
        position_cost = entry_price * max_contracts
        max_risk = bankroll * max_position_pct / 100
        if position_cost > max_risk:
            contracts = max(1, int(max_risk / entry_price))
        else:
            contracts = max_contracts
        
        if contracts <= 0 or bankroll < entry_price:
            continue
        
        # Execute
        won = target_bracket["result"] == "yes"
        fee = contracts  # 1¢ per contract
        
        if won:
            pnl = (100 - entry_price) * contracts - fee
        else:
            pnl = -(entry_price * contracts) - fee
        
        bankroll += pnl
        
        trade = {
            "date": date_str, "city": city, "type": mtype,
            "ticker": target_bracket["ticker"],
            "entry_price": entry_price, "contracts": contracts,
            "our_prob": round(prob_in_bracket, 3),
            "market_prob": round(market_prob, 3),
            "edge_pct": round(edge_pct, 1),
            "estimate": round(our_estimate, 1),
            "actual": round(actual_temp, 1),
            "error": round(estimate_error, 1),
            "won": won, "pnl": pnl,
        }
        all_trades.append(trade)
        
        # Track peak/drawdown
        if bankroll > peak:
            peak = bankroll
        dd = peak - bankroll
        if dd > max_dd:
            max_dd = dd
        
        dates_seen.add(date_str)
    
    # Aggregate daily P&L
    daily = defaultdict(lambda: {"trades": 0, "pnl": 0})
    running = bankroll_start
    for t in all_trades:
        daily[t["date"]]["trades"] += 1
        daily[t["date"]]["pnl"] += t["pnl"]
    
    for d in sorted(daily.keys()):
        running += daily[d]["pnl"]
        daily_pnl.append({"date": d, "trades": daily[d]["trades"], "pnl": daily[d]["pnl"], "bankroll": running})
    
    # Stats
    wins = sum(1 for t in all_trades if t["won"])
    losses = len(all_trades) - wins
    total_pnl = sum(t["pnl"] for t in all_trades)
    total_fees = sum(t["contracts"] for t in all_trades)
    win_rate = wins / max(len(all_trades), 1) * 100
    
    # Sharpe
    if daily_pnl:
        pnls = [d["pnl"] for d in daily_pnl]
        avg = sum(pnls) / len(pnls)
        std = math.sqrt(sum((p - avg)**2 for p in pnls) / max(len(pnls)-1, 1)) if len(pnls) > 1 else 1
        sharpe = (avg / std) * math.sqrt(252) if std > 0 else 0
    else:
        sharpe = 0
    
    # Avg error
    errors = [abs(t["error"]) for t in all_trades]
    avg_error = sum(errors) / len(errors) if errors else 0
    
    return {
        "config": config,
        "accuracy_std": accuracy_std,
        "dates": f"{sorted(dates_seen)[0] if dates_seen else '?'} to {sorted(dates_seen)[-1] if dates_seen else '?'}",
        "total_days": len(dates_seen),
        "total_trades": len(all_trades),
        "wins": wins, "losses": losses,
        "win_rate": f"{win_rate:.1f}%",
        "total_pnl": f"${total_pnl/100:.2f}",
        "fees": f"${total_fees/100:.2f}",
        "net_pnl": f"${(total_pnl)/100:.2f}",
        "sharpe": f"{sharpe:.2f}",
        "max_drawdown": f"${max_dd/100:.2f}",
        "final_bankroll": f"${bankroll/100:.2f}",
        "return_pct": f"{((bankroll - bankroll_start) / bankroll_start * 100):.1f}%",
        "avg_error_f": f"{avg_error:.1f}°F",
        "daily_pnl": daily_pnl,
        "trades": all_trades,
    }


def print_report(r: dict):
    print("\n" + "=" * 70)
    print(f"  BACKTEST: NWS Accuracy ±{r['accuracy_std']}°F std dev")
    print("=" * 70)
    print(f"  Period:          {r['dates']}")
    print(f"  Trading Days:    {r['total_days']}")
    print(f"  Total Trades:    {r['total_trades']}")
    print(f"  Wins / Losses:   {r['wins']} / {r['losses']}")
    print(f"  Win Rate:        {r['win_rate']}")
    print(f"  Net P&L:         {r['net_pnl']} (fees: {r['fees']})")
    print(f"  Return:          {r['return_pct']}")
    print(f"  Sharpe:          {r['sharpe']}")
    print(f"  Max Drawdown:    {r['max_drawdown']}")
    print(f"  Final Bankroll:  {r['final_bankroll']}")
    print(f"  Avg Est Error:   {r['avg_error_f']}")
    print("=" * 70)
    
    # City breakdown
    city_stats = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0})
    for t in r.get("trades", []):
        s = city_stats[t["city"]]
        if t["won"]: s["w"] += 1
        else: s["l"] += 1
        s["pnl"] += t["pnl"]
    
    print("\n  City  | W   | L   | Win%   | P&L")
    print("  " + "-" * 45)
    for city in sorted(city_stats):
        s = city_stats[city]
        tot = s["w"] + s["l"]
        print(f"  {city:<5} | {s['w']:>3} | {s['l']:>3} | {s['w']/tot*100:>5.1f}% | ${s['pnl']/100:.2f}")
    
    # Price bucket breakdown
    price_stats = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0})
    for t in r.get("trades", []):
        bucket = f"{t['entry_price']}¢"
        s = price_stats[bucket]
        if t["won"]: s["w"] += 1
        else: s["l"] += 1
        s["pnl"] += t["pnl"]
    
    print("\n  Price | W   | L   | Win%   | P&L")
    print("  " + "-" * 45)
    for p in sorted(price_stats, key=lambda x: int(x.replace("¢",""))):
        s = price_stats[p]
        tot = s["w"] + s["l"]
        print(f"  {p:<5} | {s['w']:>3} | {s['l']:>3} | {s['w']/tot*100:>5.1f}% | ${s['pnl']/100:.2f}")
    
    # Daily P&L (last 20 days)
    dp = r.get("daily_pnl", [])
    if dp:
        print(f"\n  Daily P&L (last {min(20, len(dp))} of {len(dp)} trading days):")
        print("  Date       | Trades | P&L       | Bankroll")
        print("  " + "-" * 50)
        for d in dp[-20:]:
            m = "📈" if d["pnl"] > 0 else "📉"
            print(f"  {d['date']} | {d['trades']:>6} | ${d['pnl']/100:>8.2f} | ${d['bankroll']/100:.2f} {m}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weather Bot Backtester")
    parser.add_argument("--collect", action="store_true", help="Download settled markets")
    parser.add_argument("--run", action="store_true", help="Run backtest")
    parser.add_argument("--sweep", action="store_true", help="Sweep accuracy levels")
    parser.add_argument("--std", type=float, default=3.0, help="NWS estimate std dev in °F")
    parser.add_argument("--max-price", type=int, default=15, help="Max entry price (cents)")
    parser.add_argument("--bankroll", type=int, default=3000, help="Starting bankroll (cents)")
    args = parser.parse_args()

    conn = init_db()

    if args.collect:
        client = KalshiClient()
        collect_settled_markets(client, conn)

    if args.run:
        config = {
            "accuracy_std_f": args.std,
            "max_entry_price": args.max_price,
            "bankroll_cents": args.bankroll,
        }
        results = run_backtest(conn, config)
        print_report(results)

    if args.sweep:
        print("\n" + "=" * 70)
        print("  ACCURACY SWEEP — How model accuracy affects P&L")
        print("=" * 70)
        print(f"  {'Std Dev':>8} | {'Trades':>6} | {'Win%':>6} | {'Net P&L':>10} | {'Return':>8} | {'Sharpe':>7} | {'MaxDD':>8}")
        print("  " + "-" * 72)
        
        for std in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0]:
            config = {
                "accuracy_std_f": std,
                "max_entry_price": args.max_price,
                "bankroll_cents": args.bankroll,
            }
            r = run_backtest(conn, config)
            print(f"  {std:>6.1f}°F | {r['total_trades']:>6} | {r['win_rate']:>6} | {r['net_pnl']:>10} | {r['return_pct']:>8} | {r['sharpe']:>7} | {r['max_drawdown']:>8}")

    if not args.collect and not args.run and not args.sweep:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    main()
