#!/usr/bin/env python3
"""
Lock-in signal generator for Kalshi weather trading.
Uses real-time METAR data to identify brackets that are now IMPOSSIBLE
based on observed daily high/low temperatures.

Lock-in windows (ET):
  - HIGH temp: After 6pm ET, the daily high is locked (temp only drops from here)
  - LOW temp: After 8am ET, the daily low is locked (temp only rises from here)

These signals are tagged "metar_lockin" for A/B testing against the base model.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from weather_collector import CONFIG
from kalshi_trader import KalshiClient
from signal_generator import Signal
from metar_tracker import (
    update_all_stations, get_daily_extremes, SETTLEMENT_STATIONS,
    get_today_date_et
)

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "lockin_signals.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("lockin_signals")

# Safety buffer: how many °F above/below running extreme before we consider
# a bracket "impossible". Using 1°F since METAR is actual observed data.
LOCKIN_SAFETY_BUFFER_F = 1.0


def get_et_hour() -> int:
    """Get current hour in ET (0-23)."""
    return (datetime.now(timezone.utc).hour - 5) % 24


def is_high_locked() -> bool:
    """Is the daily high temperature locked? (After 6pm ET)"""
    return get_et_hour() >= 18


def is_low_locked() -> bool:
    """Is the daily low temperature locked? (After 8am ET)"""
    return get_et_hour() >= 8


def generate_lockin_signals(client: KalshiClient = None) -> list[Signal]:
    """
    Generate trading signals for brackets that are now impossible
    based on METAR lock-in logic.
    
    For HIGH temp lock-in (after 6pm ET):
      - Running high is X°F. Any bracket ABOVE (X + buffer) is impossible.
      - Sell NO on those brackets (buy NO = bet the temp WON'T be in that range).
    
    For LOW temp lock-in (after 8am ET):
      - Running low is Y°F. Any bracket BELOW (Y - buffer) is impossible.
      - Sell NO on those brackets.
    """
    if client is None:
        client = KalshiClient()

    # First, update METAR data
    update_all_stations()

    high_locked = is_high_locked()
    low_locked = is_low_locked()

    if not high_locked and not low_locked:
        log.info("No lock-in window active (ET hour: %d). High locks at 18, Low locks at 8.",
                 get_et_hour())
        return []

    log.info("Lock-in check: HIGH=%s, LOW=%s (ET hour: %d)",
             "LOCKED" if high_locked else "open",
             "LOCKED" if low_locked else "open",
             get_et_hour())

    signals = []
    min_edge = CONFIG["risk"]["min_edge_pct"]

    # Build date strings for today's markets
    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%y%b%d").upper()

    disabled = CONFIG.get("disabled_cities", [])
    for city_name, station in SETTLEMENT_STATIONS.items():
        if city_name in disabled:
            continue
        extremes = get_daily_extremes(station)
        if not extremes or extremes["observation_count"] == 0:
            log.info("No METAR data for %s, skipping", city_name)
            continue

        running_high = extremes["running_high_f"]
        running_low = extremes["running_low_f"]
        city_config = CONFIG["cities"].get(city_name, {})

        # --- HIGH TEMP LOCK-IN ---
        if high_locked and running_high is not None and city_config.get("kalshi_high"):
            locked_ceiling = running_high + LOCKIN_SAFETY_BUFFER_F
            event_ticker = f"{city_config['kalshi_high']}-{date_str}"

            try:
                markets = client.get_weather_markets(event_ticker)
            except Exception as e:
                log.warning("Failed to get markets for %s: %s", event_ticker, e)
                markets = []

            for market in markets:
                # Check impossible brackets (sell NO)
                sig = _check_impossible_bracket(
                    market, city_name, "high", event_ticker,
                    running_high, locked_ceiling, "above", min_edge
                )
                if sig:
                    signals.append(sig)
                # Check confirmed brackets (buy YES)
                sig = _check_confirmed_bracket(
                    market, city_name, "high", event_ticker,
                    running_high, locked_ceiling, "above", min_edge
                )
                if sig:
                    signals.append(sig)

        # --- LOW TEMP LOCK-IN ---
        if low_locked and running_low is not None and city_config.get("kalshi_low"):
            locked_floor = running_low - LOCKIN_SAFETY_BUFFER_F
            event_ticker = f"{city_config['kalshi_low']}-{date_str}"

            try:
                markets = client.get_weather_markets(event_ticker)
            except Exception as e:
                log.warning("Failed to get markets for %s: %s", event_ticker, e)
                markets = []

            for market in markets:
                # Check impossible brackets (sell NO)
                sig = _check_impossible_bracket(
                    market, city_name, "low", event_ticker,
                    running_low, locked_floor, "below", min_edge
                )
                if sig:
                    signals.append(sig)
                # Check confirmed brackets (buy YES)
                sig = _check_confirmed_bracket(
                    market, city_name, "low", event_ticker,
                    running_low, locked_floor, "below", min_edge
                )
                if sig:
                    signals.append(sig)

    # Sort by edge (highest first)
    signals.sort(key=lambda s: s.edge_pct, reverse=True)

    log.info("Generated %d METAR lock-in signals", len(signals))
    for s in signals:
        log.info("  🔒 %s", s)

    return signals


def _check_impossible_bracket(market: dict, city: str, market_type: str,
                               event_ticker: str, running_extreme: float,
                               locked_bound: float, direction: str,
                               min_edge: float) -> Signal | None:
    """
    Check if a market bracket is now impossible based on lock-in data.
    
    direction="above": bracket is impossible if its LOW edge > locked_bound (high temp can't go higher)
    direction="below": bracket is impossible if its HIGH edge < locked_bound (low temp can't go lower)
    """
    ticker = market.get("ticker", "")
    floor_strike = market.get("floor_strike")
    cap_strike = market.get("cap_strike")

    # Need at least one strike
    if floor_strike is None and cap_strike is None:
        return None

    # Get market prices
    yes_bid = market.get("yes_bid", 0) or 0
    yes_ask = market.get("yes_ask", 100) or 100
    no_bid = market.get("no_bid", 0) or 0
    no_ask = market.get("no_ask", 100) or 100

    # Skip illiquid
    if yes_bid == 0 and yes_ask == 100:
        return None

    # Determine if bracket is impossible
    is_impossible = False
    bracket_desc = ""

    if direction == "above":
        # For high temp lock-in: bracket is impossible if its FLOOR > locked_bound
        # (temp can't reach this bracket anymore)
        if floor_strike is not None and float(floor_strike) > locked_bound:
            is_impossible = True
            bracket_desc = f">{floor_strike}°F impossible (high locked at {running_extreme:.1f}°F + {LOCKIN_SAFETY_BUFFER_F}°F buffer)"
        elif floor_strike is not None and cap_strike is not None:
            # Range bracket: impossible if entire range is above locked_bound
            if float(floor_strike) > locked_bound:
                is_impossible = True
                bracket_desc = f"[{floor_strike}-{cap_strike}]°F impossible (high locked at {running_extreme:.1f}°F)"

    elif direction == "below":
        # For low temp lock-in: bracket is impossible if its CAP < locked_bound
        # (temp can't drop into this bracket anymore)
        if cap_strike is not None and float(cap_strike) < locked_bound:
            is_impossible = True
            bracket_desc = f"<{cap_strike}°F impossible (low locked at {running_extreme:.1f}°F - {LOCKIN_SAFETY_BUFFER_F}°F buffer)"
        elif floor_strike is not None and cap_strike is not None:
            # Range bracket: impossible if entire range is below locked_bound
            if float(cap_strike) < locked_bound:
                is_impossible = True
                bracket_desc = f"[{floor_strike}-{cap_strike}]°F impossible (low locked at {running_extreme:.1f}°F)"

    if not is_impossible:
        return None

    # Skip if YES price too low (bad R/R for NO sell)
    if yes_bid < 10:
        log.info("  SKIP lock-in %s: YES@%d¢ too low (need ≥10¢)", ticker, yes_bid)
        return None

    # Calculate edge: our probability of this bracket = ~0% (it's impossible)
    # Market is pricing YES at yes_bid¢, so edge = yes_bid / yes_bid * 100 ≈ 100%
    # More precisely: we believe true prob ≈ 1%, market says yes_bid%
    our_prob = 0.01  # near-zero probability
    our_price_cents = 1
    edge = ((yes_bid - our_price_cents) / yes_bid) * 100

    if edge < min_edge:
        return None

    no_price = 100 - yes_bid

    return Signal(
        city=city,
        market_type=market_type,
        event_ticker=event_ticker,
        market_ticker=ticker,
        action="buy",
        side="no",
        suggested_price=no_price,
        confidence=0.95,  # High confidence — based on actual observed data
        edge_pct=edge,
        reason=f"METAR_LOCKIN: {bracket_desc}",
        current_temp_f=running_extreme,
        forecast_temp_f=running_extreme,  # Use running extreme as "forecast"
        surrounding_avg_f=running_extreme,
        market_yes_price=yes_bid,
    )


def _check_confirmed_bracket(market: dict, city: str, market_type: str,
                              event_ticker: str, running_extreme: float,
                              locked_bound: float, direction: str,
                              min_edge: float) -> Signal | None:
    """
    Check if a market bracket is CONFIRMED (guaranteed to settle YES) based on lock-in data.
    This is the mirror of _check_impossible_bracket.
    
    For HIGH temp lock-in (after 6pm ET):
      - Running high is X°F. Any bracket that CONTAINS X (or is below X) is confirmed YES.
      - e.g., "Will high be <48°F?" — if running high is 45°F and locked, YES is confirmed.
    
    For LOW temp lock-in (after 8am ET):
      - Running low is Y°F. Any bracket that CONTAINS Y (or is above Y) is confirmed YES.
      - e.g., "Will low be >30°F?" — if running low is 35°F and locked, YES is confirmed.
    """
    ticker = market.get("ticker", "")
    floor_strike = market.get("floor_strike")
    cap_strike = market.get("cap_strike")
    strike_type = market.get("strike_type", "")

    if floor_strike is None and cap_strike is None:
        return None

    yes_bid = market.get("yes_bid", 0) or 0
    yes_ask = market.get("yes_ask", 100) or 100

    # Skip if already priced near 100 (no edge)
    if yes_ask >= 99:
        return None

    # Skip illiquid
    if yes_bid == 0 and yes_ask == 100:
        return None

    is_confirmed = False
    bracket_desc = ""
    safety_buffer = LOCKIN_SAFETY_BUFFER_F

    if direction == "above" and market_type == "high":
        # High is locked at running_extreme. 
        # "Less than X" brackets (strike_type=less): confirmed if running_high < (cap_strike - buffer)
        # Range brackets [floor, cap]: confirmed if running_high is within range with buffer
        if strike_type == "less" and cap_strike is not None:
            cap = float(cap_strike)
            if running_extreme < (cap - safety_buffer):
                is_confirmed = True
                bracket_desc = f"<{cap}°F CONFIRMED (high locked at {running_extreme:.1f}°F, {cap - running_extreme:.1f}°F margin)"
        elif strike_type == "greater" and floor_strike is not None:
            floor = float(floor_strike)
            if running_extreme > (floor + safety_buffer):
                is_confirmed = True
                bracket_desc = f">{floor}°F CONFIRMED (high locked at {running_extreme:.1f}°F, {running_extreme - floor:.1f}°F margin)"
        elif floor_strike is not None and cap_strike is not None:
            floor = float(floor_strike)
            cap = float(cap_strike)
            if floor + safety_buffer < running_extreme < cap - safety_buffer:
                is_confirmed = True
                bracket_desc = f"[{floor}-{cap}]°F CONFIRMED (high locked at {running_extreme:.1f}°F)"

    elif direction == "below" and market_type == "low":
        # Low is locked at running_extreme.
        # "Greater than X" brackets (strike_type=greater): confirmed if running_low > (floor_strike + buffer)
        # "Less than X" brackets: confirmed if running_low < (cap_strike - buffer)
        if strike_type == "greater" and floor_strike is not None:
            floor = float(floor_strike)
            if running_extreme > (floor + safety_buffer):
                is_confirmed = True
                bracket_desc = f">{floor}°F CONFIRMED (low locked at {running_extreme:.1f}°F, {running_extreme - floor:.1f}°F margin)"
        elif strike_type == "less" and cap_strike is not None:
            cap = float(cap_strike)
            if running_extreme < (cap - safety_buffer):
                is_confirmed = True
                bracket_desc = f"<{cap}°F CONFIRMED (low locked at {running_extreme:.1f}°F, {cap - running_extreme:.1f}°F margin)"
        elif floor_strike is not None and cap_strike is not None:
            floor = float(floor_strike)
            cap = float(cap_strike)
            if floor + safety_buffer < running_extreme < cap - safety_buffer:
                is_confirmed = True
                bracket_desc = f"[{floor}-{cap}]°F CONFIRMED (low locked at {running_extreme:.1f}°F)"

    if not is_confirmed:
        return None

    # For confirmed brackets, we BUY YES
    # Edge: true prob ≈ 99%, market says yes_ask%
    our_prob = 0.99
    our_price_cents = 99
    edge = ((our_price_cents - yes_ask) / yes_ask) * 100 if yes_ask > 0 else 0

    # Need meaningful edge — at 97¢ ask, edge is only ~2%
    # But the risk is near-zero, so even small edge = free money
    # Use a lower min_edge for confirmed signals: 1% (basically any discount to 100¢)
    if yes_ask >= 99:
        return None  # no edge at all

    if edge < 1.0:
        return None  # need at least 1% edge

    log.info("  🔒 CONFIRMED: %s YES@%d¢ (edge: %.1f%%) — %s", ticker, yes_ask, edge, bracket_desc)

    return Signal(
        city=city,
        market_type=market_type,
        event_ticker=event_ticker,
        market_ticker=ticker,
        action="buy",
        side="yes",
        suggested_price=yes_ask,
        confidence=0.95,
        edge_pct=edge,
        reason=f"METAR_LOCKIN: {bracket_desc}",
        current_temp_f=running_extreme,
        forecast_temp_f=running_extreme,
        surrounding_avg_f=running_extreme,
        market_yes_price=yes_ask,
        signal_source="metar_lockin",
    )


if __name__ == "__main__":
    print("\n=== Lock-In Signal Generator ===\n")
    print(f"ET Hour: {get_et_hour()}")
    print(f"High Locked: {is_high_locked()}")
    print(f"Low Locked: {is_low_locked()}")
    print()
    
    sigs = generate_lockin_signals()
    if not sigs:
        print("No lock-in signals (may be outside lock-in window or no impossible brackets)")
    for s in sigs:
        print(s)
        print(json.dumps(s.to_dict(), indent=2))
        print()
