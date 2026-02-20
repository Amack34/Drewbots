#!/usr/bin/env python3
"""
Multi-source weather validation for Kalshi temperature trading.
Cross-checks NWS, Open-Meteo, AccuWeather, and Weather.com forecasts.
"""

import json
import logging
import re
import statistics
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("validator")

CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

NWS_HEADERS = {"User-Agent": "KalshiWeatherBot/1.0 (drewclawdbot@proton.me)", "Accept": "application/geo+json"}
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

CITIES = {
    "NYC": {"lat": 40.7128, "lon": -74.0060, "accuweather_key": "349727", "wcom": "USNY0996"},
    "PHI": {"lat": 39.9526, "lon": -75.1652, "accuweather_key": "350540", "wcom": "USPA1276"},
    "MIA": {"lat": 25.7617, "lon": -80.1918, "accuweather_key": "347936", "wcom": "USFL0316"},
    "BOS": {"lat": 42.3601, "lon": -71.0589, "accuweather_key": "348735", "wcom": "USMA0046"},
    "DC":  {"lat": 38.9072, "lon": -77.0369, "accuweather_key": "327659", "wcom": "USDC0001"},
    "ATL": {"lat": 33.7490, "lon": -84.3880, "accuweather_key": "348181", "wcom": "USGA0028"},
}


def _http_get(url, headers=None, timeout=10):
    """Generic HTTP GET returning response body as string."""
    hdrs = headers or BROWSER_HEADERS
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("HTTP GET failed %s: %s", url, e)
        return None


def _http_get_json(url, headers=None, timeout=10):
    body = _http_get(url, headers, timeout)
    if body:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            log.warning("JSON decode failed for %s", url)
    return None


# --- NWS ---
def fetch_nws(city: str) -> dict:
    """Fetch NWS forecast high/low for tomorrow. Returns {'high': F, 'low': F} or empty."""
    city_cfg = CONFIG["cities"].get(city, {})
    lat, lon = city_cfg.get("lat"), city_cfg.get("lon")
    if not lat or not lon:
        return {}

    point_data = _http_get_json(f"https://api.weather.gov/points/{lat},{lon}", headers=NWS_HEADERS)
    if not point_data:
        return {}

    try:
        forecast_url = point_data["properties"]["forecast"]
    except (KeyError, TypeError):
        return {}

    fc = _http_get_json(forecast_url, headers=NWS_HEADERS)
    if not fc:
        return {}

    try:
        periods = fc["properties"]["periods"]
        high, low = None, None
        tomorrow = (datetime.now(timezone.utc) - timedelta(hours=5)).date() + timedelta(days=1)
        for p in periods[:8]:
            start = p.get("startTime", "")[:10]
            try:
                pdate = datetime.strptime(start, "%Y-%m-%d").date()
            except ValueError:
                continue
            if pdate == tomorrow:
                temp = p.get("temperature")
                if p.get("isDaytime"):
                    high = temp
                else:
                    low = temp
        return {"high": high, "low": low}
    except Exception as e:
        log.warning("NWS parse error for %s: %s", city, e)
        return {}


# --- Open-Meteo ---
def fetch_open_meteo(city: str) -> dict:
    """Fetch Open-Meteo forecast. Returns {'high': F, 'low': F}."""
    info = CITIES[city]
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={info['lat']}&longitude={info['lon']}"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&temperature_unit=fahrenheit&timezone=America/New_York&forecast_days=2"
    )
    data = _http_get_json(url)
    if not data or "daily" not in data:
        return {}
    try:
        daily = data["daily"]
        # Index 1 = tomorrow
        idx = 1 if len(daily["temperature_2m_max"]) > 1 else 0
        return {
            "high": round(daily["temperature_2m_max"][idx], 1),
            "low": round(daily["temperature_2m_min"][idx], 1),
        }
    except (KeyError, IndexError, TypeError) as e:
        log.warning("Open-Meteo parse error for %s: %s", city, e)
        return {}


# --- AccuWeather ---
def fetch_accuweather(city: str) -> dict:
    """Try AccuWeather API (free tier key or scrape). Returns {'high': F, 'low': F}."""
    info = CITIES[city]
    loc_key = info["accuweather_key"]
    url = f"https://www.accuweather.com/en/us/city/{loc_key}/daily-weather-forecast/{loc_key}"
    body = _http_get(url)
    if not body:
        return {}
    try:
        # Look for temperature patterns in the HTML
        # AccuWeather shows temps like "High: 45°" or in structured data
        highs = re.findall(r'"high":\s*{\s*"value":\s*([\d.]+)', body)
        lows = re.findall(r'"low":\s*{\s*"value":\s*([\d.]+)', body)
        if highs and lows:
            # Second entry is typically tomorrow
            idx = 1 if len(highs) > 1 else 0
            return {"high": float(highs[idx]), "low": float(lows[idx])}
        
        # Fallback: try extracting from visible text
        temp_pattern = re.findall(r'(\d+)\s*°', body)
        if len(temp_pattern) >= 4:
            # First pair is today, second pair is tomorrow (high/low)
            return {"high": float(temp_pattern[2]), "low": float(temp_pattern[3])}
    except Exception as e:
        log.warning("AccuWeather parse error for %s: %s", city, e)
    return {}


# --- Weather.com ---
def fetch_weather_com(city: str) -> dict:
    """Try Weather.com forecast page. Returns {'high': F, 'low': F}."""
    info = CITIES[city]
    lat, lon = info["lat"], info["lon"]
    # Use the Weather.com API-like endpoint
    url = f"https://weather.com/weather/tenday/l/{lat},{lon}"
    body = _http_get(url)
    if not body:
        return {}
    try:
        # Weather.com embeds JSON data in script tags
        match = re.search(r'"temperature":\s*{\s*"max":\s*(\d+)\s*,\s*"min":\s*(\d+)', body)
        if match:
            return {"high": float(match.group(1)), "low": float(match.group(2))}
        
        # Try getSunV3DailyForecastUrlConfig pattern
        temps = re.findall(r'"temperatureMax":\s*\[([^\]]+)\]', body)
        temps_min = re.findall(r'"temperatureMin":\s*\[([^\]]+)\]', body)
        if temps and temps_min:
            maxes = [float(x.strip()) for x in temps[0].split(",") if x.strip() not in ("null", "")]
            mins = [float(x.strip()) for x in temps_min[0].split(",") if x.strip() not in ("null", "")]
            if len(maxes) > 1 and len(mins) > 1:
                return {"high": maxes[1], "low": mins[1]}
            elif maxes and mins:
                return {"high": maxes[0], "low": mins[0]}
    except Exception as e:
        log.warning("Weather.com parse error for %s: %s", city, e)
    return {}


# --- Validation Logic ---

def validate_city(city: str, target: str = "high") -> dict:
    """
    Fetch all sources for a city, compute consensus.
    target: 'high' or 'low'
    Returns dict with source values, consensus, divergence, confidence.
    """
    log.info("Validating %s (%s)...", city, target)
    
    sources = {}
    
    # NWS
    nws = fetch_nws(city)
    if nws.get(target) is not None:
        sources["nws"] = nws[target]
    
    time.sleep(0.2)
    
    # Open-Meteo
    om = fetch_open_meteo(city)
    if om.get(target) is not None:
        sources["open_meteo"] = om[target]
    
    # AccuWeather and Weather.com disabled — JS-rendered pages always fail
    # and waste 10-15s per city on HTTP timeouts. Re-enable when we have
    # a headless browser solution or find their APIs.
    # time.sleep(0.2)
    # aw = fetch_accuweather(city)
    # wc = fetch_weather_com(city)
    
    # Compute consensus
    values = list(sources.values())
    result = {
        "nws": sources.get("nws"),
        "open_meteo": sources.get("open_meteo"),
        "accuweather": sources.get("accuweather"),
        "weather_com": sources.get("weather_com"),
        "consensus": None,
        "max_divergence": None,
        "confidence": "no_data",
        "source_count": len(values),
        "divergent_sources": [],
    }
    
    if not values:
        return result
    
    consensus = statistics.median(values)
    result["consensus"] = round(consensus, 1)
    
    max_div = 0
    divergent = []
    for src, val in sources.items():
        div = abs(val - consensus)
        if div > max_div:
            max_div = div
        if div > 3:
            divergent.append(f"{src}({val})")
    
    result["max_divergence"] = round(max_div, 1)
    result["divergent_sources"] = divergent
    
    # Confidence scoring
    if len(values) >= 3 and max_div <= 2:
        result["confidence"] = "high"
    elif len(values) >= 2 and max_div <= 3:
        result["confidence"] = "medium"
    elif len(values) >= 2 and max_div <= 5:
        result["confidence"] = "low"
    else:
        result["confidence"] = "very_low"
    
    return result


def validate_all(target: str = "high") -> dict:
    """Validate all cities. Returns {city: validation_result}."""
    results = {}
    for city in CITIES:
        results[city] = validate_city(city, target)
        time.sleep(0.3)
    return results


_consensus_cache = {}
_consensus_cache_ts = 0

def get_consensus_forecast(city: str) -> dict:
    """
    Convenience function for signal_generator.py.
    Returns {'high': consensus_high, 'low': consensus_low, 'confidence': str, 'source_count': int}
    Caches results for 10 minutes to avoid redundant API calls within a bot cycle.
    """
    global _consensus_cache, _consensus_cache_ts
    now = time.time()
    if now - _consensus_cache_ts > 600:  # 10 min cache
        _consensus_cache = {}
        _consensus_cache_ts = now
    if city in _consensus_cache:
        return _consensus_cache[city]

    high_result = validate_city(city, "high")
    low_result = validate_city(city, "low")
    result = {
        "high": high_result["consensus"],
        "low": low_result["consensus"],
        "high_confidence": high_result["confidence"],
        "low_confidence": low_result["confidence"],
        "high_sources": high_result["source_count"],
        "low_sources": low_result["source_count"],
        "high_max_divergence": high_result["max_divergence"],
        "low_max_divergence": low_result["max_divergence"],
    }
    _consensus_cache[city] = result
    return result


# --- CLI ---

def print_table(target: str = "high"):
    results = validate_all(target)
    
    print(f"\n{'='*90}")
    print(f"  Weather Validation — Tomorrow's {target.upper()} temps (°F)")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*90}")
    print(f"{'City':<6} {'NWS':>6} {'O-Meteo':>8} {'AccuWx':>8} {'Wx.com':>8} {'Consens':>8} {'Diverg':>7} {'Conf':<10} {'Flags'}")
    print(f"{'-'*90}")
    
    for city, r in results.items():
        def fmt(v):
            return f"{v:>6.0f}" if v is not None else "   N/A"
        
        flags = ", ".join(r["divergent_sources"]) if r["divergent_sources"] else ""
        conf_emoji = {"high": "✅", "medium": "⚠️", "low": "🔶", "very_low": "❌", "no_data": "❓"}.get(r["confidence"], "?")
        
        print(f"{city:<6} {fmt(r['nws'])} {fmt(r['open_meteo'])} {fmt(r['accuweather'])} {fmt(r['weather_com'])} {fmt(r['consensus'])} {fmt(r['max_divergence'])} {conf_emoji} {r['confidence']:<8} {flags}")
    
    print(f"{'='*90}\n")


if __name__ == "__main__":
    print_table("high")
    print_table("low")
