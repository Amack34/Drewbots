#!/usr/bin/env python3
"""Daily P&L Dashboard for Kalshi Weather Trading Bot."""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Use same config/auth as bot.py
CONFIG_PATH = Path(__file__).parent / "config.json"
DB_PATH = Path(__file__).parent / "weather.db"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

def get_kalshi_client():
    """Get authenticated Kalshi client."""
    try:
        from kalshi_trader import KalshiClient
        return KalshiClient()
    except Exception as e:
        return None

def query_db(sql, params=()):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def fmt_dollars(cents):
    """Format cents as dollars."""
    if cents is None:
        return "$0.00"
    return f"${cents / 100:.2f}"

def pct(n, d):
    if not d:
        return "N/A"
    return f"{n / d * 100:.1f}%"

def build_report():
    lines = []
    now = datetime.now(timezone.utc)
    lines.append(f"📊 <b>Weather Bot Daily Dashboard</b>")
    lines.append(f"🕐 {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # ── Portfolio Summary (Kalshi API) ──
    client = get_kalshi_client()
    if client:
        try:
            bal = client.get_balance()
            cash_cents = bal.get("balance", 0)
            lines.append("<b>💰 Portfolio</b>")
            lines.append(f"  Cash: {fmt_dollars(cash_cents)}")

            pos_data = client.get_positions()
            positions = pos_data.get("market_positions", [])
            open_pos = [p for p in positions if p.get("total_traded", 0) > 0
                        and (p.get("position", 0) != 0 or p.get("market_exposure", 0) != 0)]
            # Calculate unrealized from positions
            total_exposure = sum(abs(p.get("market_exposure", 0)) for p in open_pos)
            lines.append(f"  Open positions: {len(open_pos)}")
            lines.append(f"  Exposure: {fmt_dollars(total_exposure)}")
            lines.append(f"  Total value: {fmt_dollars(cash_cents + total_exposure)}")
        except Exception as e:
            lines.append(f"  ⚠️ API error: {e}")
    else:
        lines.append("💰 <b>Portfolio:</b> API unavailable")
    lines.append("")

    # ── Today's Trades ──
    today_start = now.strftime("%Y-%m-%d 00:00:00")
    today_trades = query_db(
        "SELECT * FROM trade_journal WHERE created_at >= ? ORDER BY created_at",
        (today_start,))

    lines.append("<b>📈 Today's Trades</b>")
    if today_trades:
        today_pnl = sum(r["pnl_cents"] or 0 for r in today_trades if r["settled"])
        settled_today = [r for r in today_trades if r["settled"]]
        won_today = sum(1 for r in settled_today if (r["pnl_cents"] or 0) > 0)
        lines.append(f"  Trades: {len(today_trades)} | Settled: {len(settled_today)} | Won: {won_today}")
        lines.append(f"  P&L: {fmt_dollars(today_pnl)}")
        for t in today_trades[:10]:
            status = "✅" if t["settled"] and (t["pnl_cents"] or 0) > 0 else "❌" if t["settled"] else "⏳"
            pnl_str = fmt_dollars(t["pnl_cents"]) if t["settled"] else "open"
            lines.append(f"  {status} {t['ticker']} {t['side']} x{t['contracts']} @ {t['entry_price_cents']}¢ → {pnl_str}")
    else:
        lines.append("  No trades today")
    lines.append("")

    # ── Win Rate by Period ──
    all_settled = query_db("SELECT * FROM trade_journal WHERE settled = 1")
    wins_all = sum(1 for r in all_settled if (r["pnl_cents"] or 0) > 0)
    total_pnl_all = sum(r["pnl_cents"] or 0 for r in all_settled)

    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    settled_7d = query_db("SELECT * FROM trade_journal WHERE settled = 1 AND created_at >= ?", (week_ago,))
    wins_7d = sum(1 for r in settled_7d if (r["pnl_cents"] or 0) > 0)
    pnl_7d = sum(r["pnl_cents"] or 0 for r in settled_7d)

    lines.append("<b>🏆 Performance</b>")
    lines.append(f"  All-time: {pct(wins_all, len(all_settled))} win ({wins_all}/{len(all_settled)}) | P&L: {fmt_dollars(total_pnl_all)}")
    lines.append(f"  7-day:    {pct(wins_7d, len(settled_7d))} win ({wins_7d}/{len(settled_7d)}) | P&L: {fmt_dollars(pnl_7d)}")
    lines.append("")

    # ── Win Rate by City ──
    lines.append("<b>🌆 Win Rate by City</b>")
    cities = query_db(
        "SELECT city, COUNT(*) as total, SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as wins, "
        "SUM(pnl_cents) as pnl FROM trade_journal WHERE settled = 1 GROUP BY city ORDER BY pnl DESC")
    for c in cities:
        # 7d for this city
        c7 = query_db(
            "SELECT COUNT(*) as t, SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as w "
            "FROM trade_journal WHERE settled = 1 AND city = ? AND created_at >= ?",
            (c["city"], week_ago))
        w7 = f"{pct(c7[0]['w'], c7[0]['t'])}" if c7[0]["t"] else "—"
        lines.append(f"  {c['city']}: {pct(c['wins'], c['total'])} ({c['wins']}/{c['total']}) {fmt_dollars(c['pnl'])} | 7d: {w7}")
    lines.append("")

    # ── Win Rate by Signal Source ──
    lines.append("<b>🔬 Win Rate by Signal</b>")
    signals = query_db(
        "SELECT signal_source, COUNT(*) as total, "
        "SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END) as wins, "
        "SUM(pnl_cents) as pnl FROM trade_journal WHERE settled = 1 "
        "GROUP BY signal_source")
    for s in signals:
        src = s["signal_source"] or "unknown"
        lines.append(f"  {src}: {pct(s['wins'], s['total'])} ({s['wins']}/{s['total']}) | P&L: {fmt_dollars(s['pnl'])}")
    lines.append("")

    # ── Prediction Accuracy by City ──
    lines.append("<b>🎯 Prediction Accuracy (avg |error| °F)</b>")
    acc = query_db(
        "SELECT city, ROUND(AVG(ABS(estimated_temp_f - actual_temp_f)), 1) as mae, COUNT(*) as n "
        "FROM prediction_log WHERE actual_temp_f IS NOT NULL "
        "GROUP BY city ORDER BY mae")
    for a in acc:
        lines.append(f"  {a['city']}: {a['mae']}°F error (n={a['n']})")
    lines.append("")

    # ── Cumulative P&L Curve (daily) ──
    lines.append("<b>📉 Cumulative P&L (last 14 days)</b>")
    daily_pnl = query_db(
        "SELECT DATE(created_at) as day, SUM(pnl_cents) as pnl "
        "FROM trade_journal WHERE settled = 1 "
        "GROUP BY DATE(created_at) ORDER BY day")
    cum = 0
    for d in daily_pnl[-14:]:
        cum += d["pnl"] or 0
        bar = "🟢" if (d["pnl"] or 0) >= 0 else "🔴"
        lines.append(f"  {d['day']} {bar} {fmt_dollars(d['pnl']):>8} | cum: {fmt_dollars(cum)}")
    if not daily_pnl:
        lines.append("  No settled trades yet")

    return "\n".join(lines)


if __name__ == "__main__":
    print(build_report())
