#!/usr/bin/env python3
"""
Advanced backtesting suite for Kalshi weather trading bot.
  1. Walk-Forward Optimization
  2. Monte Carlo Simulation
  3. Per-City Accuracy Analysis

Uses backtest.db (settled_markets) and weather.db (prediction_log, trade_journal).
No numpy required — pure stdlib.
"""

import math
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

BASE = Path(__file__).parent
BACKTEST_DB = BASE / "backtest.db"
WEATHER_DB = BASE / "weather.db"

# ── helpers ──────────────────────────────────────────────────────────────────

def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def bracket_prob(est, std, floor, cap):
    """Probability estimate falls in [floor, cap] given gaussian(est, std)."""
    return norm_cdf((cap - est) / std) - norm_cdf((floor - est) / std)

def median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0: return 0
    if n % 2 == 1: return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2

def percentile(vals, p):
    s = sorted(vals)
    if not s: return 0
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(s) else f
    return s[f] + (k - f) * (s[c] - s[f])

# ── data loading ─────────────────────────────────────────────────────────────

def load_settled_markets():
    """Load settled markets grouped by (date, city, market_type)."""
    conn = sqlite3.connect(str(BACKTEST_DB))
    c = conn.cursor()
    c.execute("""
        SELECT event_date, city, market_type, ticker, floor_strike, cap_strike,
               result, last_price, yes_bid, yes_ask, volume
        FROM settled_markets WHERE result IN ('yes','no')
        ORDER BY event_date, city
    """)
    groups = defaultdict(list)
    for r in c.fetchall():
        groups[(r[0], r[1], r[2])].append({
            "ticker": r[3], "floor": r[4] or 0, "cap": r[5],
            "result": r[6], "last_price": r[7],
            "yes_bid": r[8], "yes_ask": r[9], "volume": r[10],
        })
    conn.close()
    return groups

def load_prediction_log():
    """Load predictions with actuals from weather.db."""
    conn = sqlite3.connect(str(WEATHER_DB))
    c = conn.cursor()
    c.execute("""
        SELECT city, market_type, estimated_temp_f, actual_temp_f, std_dev, confidence
        FROM prediction_log WHERE actual_temp_f IS NOT NULL
    """)
    rows = c.fetchall()
    conn.close()
    return [{"city": r[0], "type": r[1], "est": r[2], "actual": r[3],
             "std_dev": r[4], "confidence": r[5]} for r in rows]

def load_trade_journal():
    """Load settled trades from weather.db."""
    conn = sqlite3.connect(str(WEATHER_DB))
    c = conn.cursor()
    c.execute("""
        SELECT side, settlement_result, pnl_cents, entry_price_cents, contracts, city
        FROM trade_journal WHERE settled = 1
    """)
    rows = c.fetchall()
    conn.close()
    return [{"side": r[0], "result": r[1], "pnl": r[2], "entry": r[3],
             "contracts": r[4], "city": r[5]} for r in rows]

# ── 1. Walk-Forward Optimization ────────────────────────────────────────────

def index_groups_by_date(groups):
    """Pre-index groups by date for fast lookup."""
    by_date = defaultdict(list)
    for key in groups:
        by_date[key[0]].append(key)
    return by_date

def simulate_strategy(groups, dates, params, date_index=None):
    """
    Run strategy over given dates with params. Returns list of trade dicts.
    params: {std_dev, min_edge_pct, margin_of_safety, max_entry_price}
    """
    std_dev = params.get("std_dev", 3.0)
    city_std = params.get("city_std", {})  # per-city overrides
    min_edge = params.get("min_edge_pct", 15)
    mos = params.get("margin_of_safety", 0.0)  # extra edge buffer
    max_entry = params.get("max_entry_price", 25)

    if date_index is None:
        date_index = index_groups_by_date(groups)

    trades = []
    for date in dates:
        for key in date_index.get(date, []):
            markets = groups[key]
            city = key[1]
            sd = city_std.get(city, std_dev)

            winners = [m for m in markets if m["result"] == "yes"]
            if not winners:
                continue

            actual = winners[0]
            actual_floor = actual["floor"]
            actual_cap = actual["cap"] or (actual_floor + 5)
            actual_temp = (actual_floor + actual_cap) / 2

            # Simulate our estimate
            est = actual_temp + random.gauss(0, sd)

            # Find bracket for our estimate
            target = None
            for m in markets:
                f = m["floor"]
                c_ = m["cap"] or (f + 5)
                if f <= est <= c_:
                    target = m
                    break
            if not target:
                continue

            tf = target["floor"]
            tc = target["cap"] or (tf + 5)
            our_prob = bracket_prob(est, sd, tf, tc)

            # Simulated market price
            mkt_est = actual_temp + random.gauss(0, 2.0)
            mkt_prob = bracket_prob(mkt_est, 3.0, tf, tc)
            entry = max(1, min(99, int(mkt_prob * 100 + random.gauss(0, 2))))

            if entry > max_entry:
                continue

            mkt_p = entry / 100.0
            if mkt_p <= 0:
                continue
            edge = ((our_prob - mkt_p) / mkt_p) * 100

            if edge < min_edge + mos:
                continue

            won = target["result"] == "yes"
            contracts = 5
            fee = contracts
            pnl = ((100 - entry) * contracts - fee) if won else (-(entry * contracts) - fee)

            trades.append({"date": date, "city": city, "won": won,
                           "pnl": pnl, "entry": entry, "edge": edge})
    return trades

def walk_forward_optimization():
    print("=" * 70)
    print("  WALK-FORWARD OPTIMIZATION")
    print("=" * 70)

    groups = load_settled_markets()
    all_dates = sorted(set(k[0] for k in groups))

    date_idx = index_groups_by_date(groups)

    if len(all_dates) < 7:
        print(f"\n  Only {len(all_dates)} unique dates in settled_markets.")
        print("  Need more history for walk-forward. Running parameter sweep on full data.\n")
        # Do a parameter sweep instead
        param_grid = []
        for std in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
            for edge in [5, 10, 15, 20, 30]:
                for mos in [0, 5, 10]:
                    param_grid.append({"std_dev": std, "min_edge_pct": edge,
                                       "margin_of_safety": mos, "max_entry_price": 25})

        print(f"  Testing {len(param_grid)} parameter combos on {len(all_dates)} dates...\n")
        results = []
        for p in param_grid:
            random.seed(42)
            trades = simulate_strategy(groups, all_dates, p, date_idx)
            if not trades:
                continue
            wins = sum(1 for t in trades if t["won"])
            total_pnl = sum(t["pnl"] for t in trades)
            results.append({"params": p, "trades": len(trades), "wins": wins,
                            "wr": wins / len(trades) * 100, "pnl": total_pnl})

        results.sort(key=lambda x: x["pnl"], reverse=True)
        print(f"  {'Std':>4} {'Edge%':>6} {'MoS':>4} | {'Trades':>6} {'WR%':>6} {'PnL¢':>8}")
        print(f"  {'-'*4} {'-'*6} {'-'*4} | {'-'*6} {'-'*6} {'-'*8}")
        for r in results[:15]:
            p = r["params"]
            print(f"  {p['std_dev']:4.1f} {p['min_edge_pct']:6.0f} {p['margin_of_safety']:4.0f} | "
                  f"{r['trades']:6d} {r['wr']:5.1f}% {r['pnl']:8d}")

        if results:
            best = results[0]["params"]
            print(f"\n  ★ Best: std_dev={best['std_dev']}, min_edge={best['min_edge_pct']}%, "
                  f"margin_of_safety={best['margin_of_safety']}")
        return

    # Real walk-forward with enough data
    # Train 60% of dates, test next 20%, slide
    n = len(all_dates)
    train_size = max(5, int(n * 0.6))
    test_size = max(2, int(n * 0.2))
    step = max(1, test_size)

    windows = []
    i = 0
    while i + train_size + test_size <= n:
        train_dates = all_dates[i:i + train_size]
        test_dates = all_dates[i + train_size:i + train_size + test_size]
        windows.append((train_dates, test_dates))
        i += step

    if not windows:
        windows = [(all_dates[:train_size], all_dates[train_size:])]

    print(f"\n  {len(windows)} walk-forward windows | train={train_size}d, test={test_size}d\n")

    param_grid = []
    for std in [2.0, 3.0, 4.0, 5.0]:
        for edge in [5, 10, 15, 20, 30]:
            for mos in [0, 5, 10]:
                param_grid.append({"std_dev": std, "min_edge_pct": edge,
                                   "margin_of_safety": mos, "max_entry_price": 25})

    window_results = []
    for wi, (train_d, test_d) in enumerate(windows):
        # Optimize on train
        best_pnl = -999999
        best_p = None
        for p in param_grid:
            random.seed(42)
            trades = simulate_strategy(groups, train_d, p, date_idx)
            pnl = sum(t["pnl"] for t in trades) if trades else -999999
            if pnl > best_pnl:
                best_pnl = pnl
                best_p = p

        # Test on out-of-sample
        random.seed(42)
        oos_trades = simulate_strategy(groups, test_d, best_p, date_idx)
        oos_pnl = sum(t["pnl"] for t in oos_trades)
        oos_wins = sum(1 for t in oos_trades if t["won"])
        oos_wr = (oos_wins / len(oos_trades) * 100) if oos_trades else 0

        window_results.append({
            "window": wi + 1, "train": f"{train_d[0]}→{train_d[-1]}",
            "test": f"{test_d[0]}→{test_d[-1]}",
            "best_params": best_p, "train_pnl": best_pnl,
            "oos_trades": len(oos_trades), "oos_pnl": oos_pnl, "oos_wr": oos_wr,
        })

    print(f"  {'Win':>3} {'Train Period':>25} {'Test Period':>25} | {'Std':>4} {'Edge':>5} "
          f"{'Train¢':>7} {'OOS¢':>7} {'OOS WR':>7}")
    print(f"  {'─'*3} {'─'*25} {'─'*25} | {'─'*4} {'─'*5} {'─'*7} {'─'*7} {'─'*7}")
    for w in window_results:
        p = w["best_params"]
        print(f"  {w['window']:3d} {w['train']:>25} {w['test']:>25} | "
              f"{p['std_dev']:4.1f} {p['min_edge_pct']:5.0f} {w['train_pnl']:7d} "
              f"{w['oos_pnl']:7d} {w['oos_wr']:6.1f}%")

    # Parameter stability
    stds = [w["best_params"]["std_dev"] for w in window_results]
    edges = [w["best_params"]["min_edge_pct"] for w in window_results]
    oos_pnls = [w["oos_pnl"] for w in window_results]

    print(f"\n  Parameter Stability:")
    print(f"    std_dev:  {min(stds):.1f} – {max(stds):.1f} (median {median(stds):.1f})")
    print(f"    min_edge: {min(edges):.0f} – {max(edges):.0f} (median {median(edges):.0f})")
    print(f"    OOS PnL:  {min(oos_pnls)} – {max(oos_pnls)} (median {median(oos_pnls):.0f})")

    gap = []
    for w in window_results:
        if w["train_pnl"] != 0:
            gap.append((w["oos_pnl"] - w["train_pnl"]) / abs(w["train_pnl"]) * 100)
    if gap:
        print(f"    OOS vs Train gap: {median(gap):.0f}% median "
              f"({'⚠ possible overfit' if median(gap) < -50 else '✓ looks stable'})")


# ── 2. Monte Carlo Simulation ───────────────────────────────────────────────

def monte_carlo_simulation():
    print("\n" + "=" * 70)
    print("  MONTE CARLO SIMULATION")
    print("=" * 70)

    # Pull actual trade stats from journal
    trades = load_trade_journal()

    if len(trades) < 5:
        print(f"\n  Only {len(trades)} settled trades. Using default assumptions.\n")
        # Defaults from task description
        win_rate = 0.72  # blended (NO sell ~92%, YES buy lower)
        avg_win_cents = 66
        avg_loss_cents = 98
    else:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(trades) if trades else 0.5
        avg_win_cents = sum(t["pnl"] for t in wins) / len(wins) if wins else 66
        avg_loss_cents = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 98
        print(f"\n  From {len(trades)} settled trades:")
        print(f"    Win rate:  {win_rate*100:.1f}%")
        print(f"    Avg win:   {avg_win_cents:.0f}¢")
        print(f"    Avg loss:  {avg_loss_cents:.0f}¢")

    # Also compute NO-sell specific stats
    no_sells = [t for t in trades if t["side"] == "no"]
    if no_sells:
        ns_wins = [t for t in no_sells if t["pnl"] > 0]
        ns_wr = len(ns_wins) / len(no_sells) * 100
        print(f"    NO-sell:   {len(no_sells)} trades, {ns_wr:.0f}% win rate")

    # Also run with NO-sell only stats if available
    no_sell_stats = None
    if no_sells:
        ns_w = [t for t in no_sells if t["pnl"] > 0]
        ns_l = [t for t in no_sells if t["pnl"] <= 0]
        if ns_w and ns_l:
            no_sell_stats = {
                "wr": len(ns_w) / len(no_sells),
                "avg_win": sum(t["pnl"] for t in ns_w) / len(ns_w),
                "avg_loss": abs(sum(t["pnl"] for t in ns_l) / len(ns_l)),
            }
            print(f"    NO-sell avg win: {no_sell_stats['avg_win']:.0f}¢, "
                  f"avg loss: {no_sell_stats['avg_loss']:.0f}¢")

    starting_bankroll = 15000  # $150
    n_simulations = 10000
    n_trades = 500  # simulate ~500 trades forward

    print(f"\n  Simulating {n_simulations:,} paths of {n_trades} trades")
    print(f"  Starting bankroll: ${starting_bankroll/100:.2f}")
    print(f"  Win rate: {win_rate*100:.1f}%, Avg win: {avg_win_cents:.0f}¢, Avg loss: {avg_loss_cents:.0f}¢\n")

    # Kelly criterion
    b = avg_win_cents / avg_loss_cents  # odds ratio
    p = win_rate
    q = 1 - p
    kelly = (b * p - q) / b if b > 0 else 0
    print(f"  Kelly Criterion: {kelly*100:.1f}% of bankroll per trade")
    print(f"    (Full Kelly={kelly*100:.1f}%, Half Kelly={kelly*50:.1f}%, Quarter={kelly*25:.1f}%)")

    # Run simulations at different position sizes
    for label, frac in [("Current (fixed 5¢ risk)", None),
                        ("Half Kelly", kelly / 2),
                        ("Quarter Kelly", kelly / 4)]:
        endpoints = []
        max_drawdowns = []
        ruins = 0
        hit_270 = 0  # $2.70 = $270 total (80% profit from $150)
        hit_500 = 0
        hit_1000 = 0

        for _ in range(n_simulations):
            bankroll = starting_bankroll
            peak = bankroll
            max_dd = 0

            for _ in range(n_trades):
                if bankroll <= 0:
                    ruins += 1
                    break

                if frac is not None:
                    # Kelly sizing: risk frac of bankroll
                    risk = max(1, int(bankroll * frac))
                else:
                    risk = 500  # 5 contracts × ~$1 risk

                risk = min(risk, bankroll)

                if random.random() < win_rate:
                    # Win — scale by ratio
                    pnl = int(risk * (avg_win_cents / avg_loss_cents))
                else:
                    pnl = -risk

                bankroll += pnl
                if bankroll > peak:
                    peak = bankroll
                dd = peak - bankroll
                if dd > max_dd:
                    max_dd = dd

            endpoints.append(bankroll)
            max_drawdowns.append(max_dd)

            if bankroll >= 27000: hit_270 += 1
            if bankroll >= 50000: hit_500 += 1
            if bankroll >= 100000: hit_1000 += 1

        print(f"\n  ── {label} ──")
        print(f"    Ruin probability:    {ruins/n_simulations*100:.2f}%")
        print(f"    Median final:        ${median(endpoints)/100:.2f}")
        print(f"    P10/P90:             ${percentile(endpoints,10)/100:.2f} / ${percentile(endpoints,90)/100:.2f}")
        print(f"    Median max drawdown: ${median(max_drawdowns)/100:.2f}")
        print(f"    P(reach $270):       {hit_270/n_simulations*100:.1f}%")
        print(f"    P(reach $500):       {hit_500/n_simulations*100:.1f}%")
        print(f"    P(reach $1000):      {hit_1000/n_simulations*100:.1f}%")

    # NO-sell specific Monte Carlo
    if no_sell_stats and no_sell_stats["avg_win"] > 0:
        ns_wr = no_sell_stats["wr"]
        ns_aw = no_sell_stats["avg_win"]
        ns_al = no_sell_stats["avg_loss"]
        ns_b = ns_aw / ns_al
        ns_kelly = (ns_b * ns_wr - (1 - ns_wr)) / ns_b if ns_b > 0 else 0

        print(f"\n  ── NO-Sell Strategy Only (WR={ns_wr*100:.0f}%, "
              f"W={ns_aw:.0f}¢, L={ns_al:.0f}¢) ──")
        print(f"    Kelly: {ns_kelly*100:.1f}%")

        for sz_label, sz_frac in [("Half Kelly", max(0.01, ns_kelly/2)),
                                   ("Fixed $5 risk", None)]:
            endpoints = []
            ruins = 0
            hit_270 = hit_500 = hit_1000 = 0
            for _ in range(n_simulations):
                bankroll = starting_bankroll
                for _ in range(n_trades):
                    if bankroll <= 0:
                        ruins += 1
                        break
                    if sz_frac is not None:
                        risk = max(1, min(int(bankroll * sz_frac), bankroll))
                    else:
                        risk = min(500, bankroll)
                    if random.random() < ns_wr:
                        bankroll += int(risk * ns_b)
                    else:
                        bankroll -= risk
                endpoints.append(bankroll)
                if bankroll >= 27000: hit_270 += 1
                if bankroll >= 50000: hit_500 += 1
                if bankroll >= 100000: hit_1000 += 1

            print(f"\n    {sz_label}:")
            print(f"      Ruin:     {ruins/n_simulations*100:.2f}%")
            print(f"      Median:   ${median(endpoints)/100:.2f}")
            print(f"      P10/P90:  ${percentile(endpoints,10)/100:.2f} / ${percentile(endpoints,90)/100:.2f}")
            print(f"      P($270):  {hit_270/n_simulations*100:.1f}%")
            print(f"      P($500):  {hit_500/n_simulations*100:.1f}%")
            print(f"      P($1000): {hit_1000/n_simulations*100:.1f}%")


# ── 3. Per-City Accuracy Analysis ───────────────────────────────────────────

def per_city_accuracy():
    print("\n" + "=" * 70)
    print("  PER-CITY ACCURACY ANALYSIS")
    print("=" * 70)

    preds = load_prediction_log()
    if not preds:
        print("\n  No prediction_log entries with actuals. Skipping.\n")
        return

    by_city = defaultdict(list)
    for p in preds:
        by_city[p["city"]].append(p)

    print(f"\n  {'City':<6} {'N':>4} {'MAE°F':>6} {'RMSE°F':>7} {'Bias°F':>7} "
          f"{'Cur σ':>6} {'Opt σ':>6} {'Δ':>6}")
    print(f"  {'─'*6} {'─'*4} {'─'*6} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*6}")

    recommendations = {}
    for city in sorted(by_city):
        entries = by_city[city]
        errors = [e["est"] - e["actual"] for e in entries]
        abs_errors = [abs(e) for e in errors]
        n = len(errors)
        mae = sum(abs_errors) / n
        rmse = math.sqrt(sum(e**2 for e in errors) / n)
        bias = sum(errors) / n

        # Current std_dev used (from config, default ~3.0)
        cur_std = entries[0]["std_dev"] if entries[0]["std_dev"] else 3.0

        # Optimal std_dev = RMSE (by definition for gaussian model)
        opt_std = rmse
        delta = opt_std - cur_std

        recommendations[city] = {"current": cur_std, "optimal": round(opt_std, 2), "n": n}

        print(f"  {city:<6} {n:4d} {mae:6.2f} {rmse:7.2f} {bias:+7.2f} "
              f"{cur_std:6.1f} {opt_std:6.2f} {delta:+6.2f}")

    print(f"\n  Recommendations:")
    for city, r in sorted(recommendations.items()):
        direction = "↑ increase" if r["optimal"] > r["current"] else "↓ decrease"
        if abs(r["optimal"] - r["current"]) < 0.3:
            direction = "✓ good"
        print(f"    {city}: set std_dev to {r['optimal']}°F ({direction}, n={r['n']})")

    # Also analyze from settled_markets for broader picture
    print(f"\n  Note: Only {sum(len(v) for v in by_city.values())} predictions with actuals available.")
    print(f"  For robust std_dev estimates, need 50+ predictions per city.")


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "█" * 70)
    print("  KALSHI WEATHER BOT — ADVANCED BACKTESTING SUITE")
    print("█" * 70)
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Data: {BACKTEST_DB.name} + {WEATHER_DB.name}\n")

    walk_forward_optimization()
    monte_carlo_simulation()
    per_city_accuracy()

    print("\n" + "=" * 70)
    print("  DONE")
    print("=" * 70 + "\n")
