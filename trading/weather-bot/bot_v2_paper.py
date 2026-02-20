#!/usr/bin/env python3
"""
A/B Paper Trading Bot — Compares NEW signal generator (with fixes) vs OLD (pre-fix).

v1 (LIVE) = signal_generator.py — has temp tracker, market validation, ATL bias, rounding buffer
v2 (OLD BASELINE) = signal_generator_v2_old.py — pre-Feb 19 fixes, no market validation

Purpose: Measure how many bad trades the new validation layer catches.
Every signal v2 generates but v1 blocks = a potential loss avoided.
"""

import json
import sys
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from weather_collector import collect_all, CONFIG
from signal_generator_v2_old import generate_signals as generate_signals_v2_old
from signal_generator import generate_signals as generate_signals_v1
from kalshi_trader import KalshiClient

LOG_DIR = Path(CONFIG["log_dir"])
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "v2_paper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("v2_paper")

DB_PATH = CONFIG["db_path"]


def init_v2_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS v2_paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT NOT NULL,
        ticker TEXT NOT NULL,
        city TEXT NOT NULL,
        market_type TEXT NOT NULL,
        side TEXT NOT NULL,
        suggested_price INTEGER,
        confidence REAL,
        edge_pct REAL,
        estimated_temp REAL,
        forecast_temp REAL,
        market_yes_price INTEGER,
        settled INTEGER DEFAULT 0,
        actual_temp REAL,
        pnl_cents INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )''')
    conn.commit()
    conn.close()


def run_comparison():
    """Run both v1 and v2 signal generators, compare outputs, paper trade v2."""
    log.info("=" * 60)
    log.info("V2 Paper Trading — Comparison Run")
    log.info("=" * 60)

    # Collect fresh weather data
    try:
        collect_all()
    except Exception as e:
        log.error("Collection failed: %s", e)
        return

    client = KalshiClient()

    # Generate signals from both versions
    try:
        v1_signals = generate_signals_v1(client)
    except Exception as e:
        log.error("V1 signal gen failed: %s", e)
        v1_signals = []

    try:
        v2_signals = generate_signals_v2_old(client)
    except Exception as e:
        log.error("V2 (old baseline) signal gen failed: %s", e)
        v2_signals = []

    log.info("V1: %d signals | V2: %d signals", len(v1_signals), len(v2_signals))

    # Compare: what's different?
    v1_tickers = {s.market_ticker: s for s in v1_signals}
    v2_tickers = {s.market_ticker: s for s in v2_signals}

    only_v1 = set(v1_tickers.keys()) - set(v2_tickers.keys())
    only_v2 = set(v2_tickers.keys()) - set(v1_tickers.keys())
    both = set(v1_tickers.keys()) & set(v2_tickers.keys())

    if only_v1:
        log.info("V1 (new) only (%d): %s", len(only_v1), ", ".join(only_v1))
    if only_v2:
        log.info("⚠️ V2 (old) would trade but V1 BLOCKED (%d):", len(only_v2))
        for ticker in only_v2:
            s = v2_tickers[ticker]
            log.info("  🛡️ CAUGHT: %s %s edge=%.1f%% — V1 validation prevented this trade",
                     ticker, s.side, s.edge_pct)

    for ticker in both:
        s1 = v1_tickers[ticker]
        s2 = v2_tickers[ticker]
        if abs(s1.edge_pct - s2.edge_pct) > 5:
            log.info("DIFF %s: v1(new) edge=%.1f%% v2(old) edge=%.1f%% (Δ%.1f%%)",
                     ticker, s1.edge_pct, s2.edge_pct, s2.edge_pct - s1.edge_pct)
        if s1.confidence != s2.confidence:
            log.info("CONF %s: v1(new) conf=%.0f%% v2(old) conf=%.0f%%",
                     ticker, s1.confidence * 100, s2.confidence * 100)

    # Paper trade v2 signals
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    v2_count = 0
    for s in v2_signals[:10]:  # max 10 paper trades per cycle
        cur.execute('''INSERT INTO v2_paper_trades 
            (version, ticker, city, market_type, side, suggested_price, confidence,
             edge_pct, estimated_temp, forecast_temp, market_yes_price)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            ("v2", s.market_ticker, s.city, s.market_type, s.side,
             s.suggested_price, s.confidence, s.edge_pct,
             s.forecast_temp_f, s.forecast_temp_f, s.market_yes_price))
        v2_count += 1

    # Also log v1 signals for comparison
    for s in v1_signals[:10]:
        cur.execute('''INSERT INTO v2_paper_trades 
            (version, ticker, city, market_type, side, suggested_price, confidence,
             edge_pct, estimated_temp, forecast_temp, market_yes_price)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            ("v1", s.market_ticker, s.city, s.market_type, s.side,
             s.suggested_price, s.confidence, s.edge_pct,
             s.forecast_temp_f, s.forecast_temp_f, s.market_yes_price))

    conn.commit()
    conn.close()

    log.info("Paper traded %d v2(old) signals + %d v1(new) signals for comparison", v2_count, min(len(v1_signals), 10))
    log.info("🔑 KEY METRIC: %d trades OLD code would take that NEW code blocked", len(only_v2))
    log.info("Review with: sqlite3 weather.db 'SELECT version, count(*), avg(edge_pct) FROM v2_paper_trades GROUP BY version'")


if __name__ == "__main__":
    init_v2_tables()
    run_comparison()
