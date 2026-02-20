#!/usr/bin/env python3
"""
Hourly Portfolio Sanity Check
Pulls NWS forecasts and validates every open position against current data.
Flags positions that should be cut based on actual forecast data, not just model output.
"""

import json
import os
import time
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from kalshi_trader import KalshiClient, CONFIG
from weather_collector import get_latest_observations, get_latest_forecast

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sanity_check.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DB_PATH = Path(CONFIG["db_path"])
RATE_LIMIT = 0.35


def get_nws_forecast(city_name, city_config):
    """Get current NWS forecast high/low for today and tomorrow from DB."""
    try:
        result = {"today_high": None, "today_low": None, "tomorrow_high": None, "tomorrow_low": None}
        
        now_et = datetime.now(timezone.utc) - timedelta(hours=5)
        today = now_et.strftime("%Y-%m-%d")
        tomorrow = (now_et + timedelta(days=1)).strftime("%Y-%m-%d")
        
        fc_today = get_latest_forecast(city_name, today)
        fc_tomorrow = get_latest_forecast(city_name, tomorrow)
        
        if fc_today:
            result["today_high"] = fc_today.get("forecast_high_f")
            result["today_low"] = fc_today.get("forecast_low_f")
        if fc_tomorrow:
            result["tomorrow_high"] = fc_tomorrow.get("forecast_high_f")
            result["tomorrow_low"] = fc_tomorrow.get("forecast_low_f")
        
        # Current temp from latest observation
        obs = get_latest_observations(city_name)
        if obs:
            result["current_temp"] = obs[0].get("temp_f")
        
        return result
    except Exception as e:
        log.error("Failed to get forecast for %s: %s", city_name, e)
        return None


def get_metar_extremes():
    """Get METAR daily extremes from DB."""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        c = conn.cursor()
        c.execute("SELECT station, running_high_f, running_low_f, last_updated FROM metar_daily_extremes")
        rows = c.fetchall()
        conn.close()
        return {r[0]: {"high": r[1], "low": r[2], "updated": r[3]} for r in rows}
    except Exception:
        return {}


def parse_ticker(ticker):
    """Parse a Kalshi weather ticker into components.
    e.g., KXHIGHMIA-26FEB19-B82.5 -> {city: MIA, type: high, date: 26FEB19, bracket: B82.5, strike: 82.5}
    """
    parts = ticker.split("-")
    if len(parts) < 3:
        return None
    
    prefix = parts[0]
    date_str = parts[1]
    bracket = parts[2]
    
    # Extract city and type
    city = None
    mtype = None
    
    city_map = {
        "KXHIGHNY": ("NYC", "high"), "KXLOWTNYC": ("NYC", "low"),
        "KXHIGHPHIL": ("PHI", "high"), "KXLOWTPHIL": ("PHI", "low"),
        "KXHIGHMIA": ("MIA", "high"), "KXLOWTMIA": ("MIA", "low"),
        "KXHIGHTBOS": ("BOS", "high"), "KXLOWTBOS": ("BOS", "low"),
        "KXHIGHTDC": ("DC", "high"), "KXLOWTDC": ("DC", "low"),
        "KXHIGHTATL": ("ATL", "high"), "KXLOWTATL": ("ATL", "low"),
    }
    
    for pfx, (c, t) in city_map.items():
        if prefix == pfx:
            city = c
            mtype = t
            break
    
    if not city:
        return None
    
    # Parse bracket
    strike = None
    bracket_type = None
    if bracket.startswith("B"):
        bracket_type = "between"
        try:
            strike = float(bracket[1:])
        except ValueError:
            pass
    elif bracket.startswith("T"):
        bracket_type = "above"
        try:
            strike = float(bracket[1:])
        except ValueError:
            pass
    
    return {
        "city": city, "type": mtype, "date": date_str,
        "bracket": bracket, "bracket_type": bracket_type, "strike": strike
    }


def run_sanity_check():
    """Check every open position against current forecasts and flag concerns."""
    client = KalshiClient()
    
    # Get all open positions
    positions = client.get_positions().get("market_positions", [])
    open_positions = [p for p in positions if p.get("position", 0) != 0]
    
    if not open_positions:
        log.info("No open positions")
        return []
    
    log.info("Checking %d open positions against NWS forecasts", len(open_positions))
    
    # Get forecasts for all cities
    forecasts = {}
    for city_name, city_config in CONFIG["cities"].items():
        fc = get_nws_forecast(city_name, city_config)
        if fc:
            forecasts[city_name] = fc
            log.info("Forecast %s: today_high=%s today_low=%s tomorrow_high=%s tomorrow_low=%s current=%s",
                     city_name, fc.get("today_high"), fc.get("today_low"),
                     fc.get("tomorrow_high"), fc.get("tomorrow_low"), fc.get("current_temp"))
    
    # Get METAR extremes
    metar = get_metar_extremes()
    
    # Check each position
    alerts = []
    for p in open_positions:
        ticker = p.get("ticker", "")
        pos = p.get("position", 0)
        exposure = p.get("market_exposure", 0)
        
        parsed = parse_ticker(ticker)
        if not parsed:
            log.warning("Could not parse ticker: %s", ticker)
            continue
        
        city = parsed["city"]
        mtype = parsed["type"]
        strike = parsed["strike"]
        bracket_type = parsed["bracket_type"]
        
        if not strike or city not in forecasts:
            continue
        
        fc = forecasts[city]
        
        # Determine which forecast to compare against
        # Parse the date from ticker to know if it's today or tomorrow
        now_et = datetime.now(timezone.utc) - timedelta(hours=5)
        today_str = now_et.strftime("%y%b%d").upper()
        
        is_today = parsed["date"] == today_str
        
        if mtype == "high":
            forecast_temp = fc.get("today_high") if is_today else fc.get("tomorrow_high")
        else:
            forecast_temp = fc.get("today_low") if is_today else fc.get("tomorrow_low")
        
        if forecast_temp is None:
            continue
        
        # We're holding NO (pos < 0) = betting the bracket WON'T hit
        # For "between" brackets (B): bracket hits if temp is in range [strike, strike+1)
        # For "top" brackets (T): T80 means ">80°F" (81° or above) — bracket hits if temp > strike
        #   So NO on T80 wins if temp <= 80°F (stays at or below the strike)
        side = "NO" if pos < 0 else "YES"
        contracts = abs(pos)
        
        # Calculate margin of safety
        if side == "NO":
            if bracket_type == "between":
                # We need temp to be OUTSIDE [strike, strike+1]
                # Distance from forecast to bracket
                if forecast_temp >= strike and forecast_temp <= strike + 1:
                    margin = 0  # forecast is IN the bracket — we're in trouble
                elif forecast_temp < strike:
                    margin = strike - forecast_temp
                else:
                    margin = forecast_temp - (strike + 1)
            elif bracket_type == "above":
                # T brackets vary — must check actual market strike_type from API
                try:
                    time.sleep(RATE_LIMIT)
                    mkt_data = client.get_market(ticker).get("market", {})
                    strike_type = mkt_data.get("strike_type", "")
                except Exception:
                    strike_type = ""
                
                if strike_type == "greater":
                    # ">X°F" — YES wins if temp > strike. NO wins if temp <= strike.
                    margin = strike - forecast_temp  # positive = forecast below strike = safe
                elif strike_type == "less":
                    # "<X°F" — YES wins if temp < strike. NO wins if temp >= strike.
                    margin = forecast_temp - strike  # positive = forecast above strike = safe
                else:
                    margin = None
            else:
                margin = None
            
            if margin is not None:
                # Get current market price for context
                try:
                    time.sleep(RATE_LIMIT)
                    mkt = client.get_market(ticker).get("market", {})
                    yes_bid = mkt.get("yes_bid", 0)
                    no_bid = mkt.get("no_bid", 0)
                except Exception:
                    yes_bid = 0
                    no_bid = 0
                
                # Check running temp from temp_tracker for bracket-edge risk
                running_margin = None
                try:
                    import json as _json
                    with open(os.path.join(os.path.dirname(__file__), 'temp_state.json'), 'r') as _f:
                        _ts = _json.load(_f)
                    _city_state = _ts.get('cities', {}).get(city, {})
                    _running_h = _city_state.get('high')
                    _running_l = _city_state.get('low')
                    if mtype == 'high' and _running_h and is_today:
                        running_margin = abs(_running_h - strike)
                    elif mtype == 'low' and _running_l and is_today:
                        running_margin = abs(_running_l - strike)
                except Exception:
                    pass

                status = "✅ SAFE"
                if margin <= 0:
                    status = "🚨 DANGER — forecast IN bracket"
                elif running_margin is not None and running_margin <= 1.0 and is_today:
                    status = "🚨 BRACKET-EDGE — running temp within 1°F of strike (rounding risk!)"
                elif running_margin is not None and running_margin <= 2.0 and is_today:
                    status = "⚠️ BRACKET-EDGE — running temp within 2°F of strike"
                elif margin <= 2:
                    status = "⚠️ TIGHT — <2°F margin"
                elif margin <= 3:
                    status = "🟡 WATCH — <3°F margin"
                
                alert = {
                    "ticker": ticker,
                    "city": city,
                    "type": mtype,
                    "side": side,
                    "contracts": contracts,
                    "strike": strike,
                    "forecast": forecast_temp,
                    "margin": margin,
                    "status": status,
                    "exposure": exposure,
                    "yes_bid": yes_bid,
                    "no_bid": no_bid,
                    "is_today": is_today,
                }
                alerts.append(alert)
                
                log.info("%s %s x%d | strike=%.1f forecast=%.1f margin=%.1f°F | YES@%d¢ NO@%d¢ | %s",
                         ticker, side, contracts, strike, forecast_temp, margin, yes_bid, no_bid, status)
    
    # Summary
    dangers = [a for a in alerts if "DANGER" in a["status"]]
    warnings = [a for a in alerts if "TIGHT" in a["status"] or "WATCH" in a["status"]]
    safe = [a for a in alerts if "SAFE" in a["status"]]
    
    print("\n" + "=" * 70)
    print("PORTFOLIO SANITY CHECK")
    print("=" * 70)
    
    if dangers:
        print(f"\n🚨 DANGER ({len(dangers)} positions):")
        for a in dangers:
            print(f"  {a['ticker']}: {a['side']} x{a['contracts']} | "
                  f"forecast {a['forecast']}°F vs strike {a['strike']}°F | "
                  f"NO bid {a['no_bid']}¢ | exposure {a['exposure']}¢")
            print(f"    → RECOMMEND CUT: sell NO at {a['no_bid']}¢, recover {a['no_bid'] * a['contracts']}¢")
    
    if warnings:
        print(f"\n⚠️ WATCH ({len(warnings)} positions):")
        for a in warnings:
            print(f"  {a['ticker']}: {a['side']} x{a['contracts']} | "
                  f"forecast {a['forecast']}°F vs strike {a['strike']}°F | "
                  f"margin {a['margin']:.1f}°F | NO bid {a['no_bid']}¢")
    
    if safe:
        print(f"\n✅ SAFE ({len(safe)} positions):")
        for a in safe:
            print(f"  {a['ticker']}: {a['side']} x{a['contracts']} | "
                  f"forecast {a['forecast']}°F vs strike {a['strike']}°F | "
                  f"margin {a['margin']:.1f}°F")
    
    print(f"\nTotal: {len(dangers)} danger, {len(warnings)} watch, {len(safe)} safe")
    
    return alerts


if __name__ == "__main__":
    run_sanity_check()
