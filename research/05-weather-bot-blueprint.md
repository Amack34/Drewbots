# Weather Trading Bot Blueprint
*Ready-to-implement plan for Drew's first automated strategy*

## Architecture

```
NWS API (free) → Weather Data Collector → Signal Generator → Kalshi API → Trade Execution
     ↓                                         ↓
  SQLite DB                              Alert to Drew (Telegram)
```

## Step 1: Data Collector (Run every 30 min)

```python
#!/usr/bin/env python3
"""Collect weather observations and forecasts for Kalshi trading."""

import json, urllib.request, sqlite3
from datetime import datetime

DB_PATH = "/root/.openclaw/workspace/research/weather.db"

# Target cities and their surrounding stations
CITIES = {
    "NYC": {
        "primary": "KNYC",
        "surrounding": ["KEWR", "KJFK", "KLGA", "KHPN", "KTEB"],
        "kalshi_high": "KXHIGHNY",
        "kalshi_low": "KXLOWTNYC",
        "lat": 40.7128, "lon": -74.0060
    },
    "PHI": {
        "primary": "KPHL",
        "surrounding": ["KILG", "KTTN", "KACY"],
        "kalshi_high": "KXHIGHPHIL",
        "kalshi_low": "KXLOWTPHIL",
        "lat": 39.9526, "lon": -75.1652
    },
    "MIA": {
        "primary": "KMIA",
        "surrounding": ["KFLL", "KPBI"],
        "kalshi_high": "KXHIGHMIA",
        "kalshi_low": "KXLOWTMIA",
        "lat": 25.7617, "lon": -80.1918
    },
    "BOS": {
        "primary": "KBOS",
        "surrounding": ["KPVD", "KBED", "KORH"],
        "kalshi_high": "KXHIGHTBOS",
        "kalshi_low": None,
        "lat": 42.3601, "lon": -71.0589
    },
    "DC": {
        "primary": "KDCA",
        "surrounding": ["KIAD", "KBWI"],
        "kalshi_high": "KXHIGHTDC",
        "kalshi_low": None,
        "lat": 38.9072, "lon": -77.0369
    },
    "ATL": {
        "primary": "KATL",
        "surrounding": ["KPDK", "KFTY"],
        "kalshi_high": "KXHIGHTATL",
        "kalshi_low": None,
        "lat": 33.7490, "lon": -84.3880
    }
}

def get_obs(station):
    url = f"https://api.weather.gov/stations/{station}/observations/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "KalshiWeatherBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        p = data["properties"]
        temp_c = p["temperature"]["value"]
        if temp_c is None:
            return None
        return {
            "temp_f": round(temp_c * 9/5 + 32, 1),
            "humidity": p.get("relativeHumidity", {}).get("value"),
            "wind_mph": round((p.get("windSpeed", {}).get("value") or 0) * 0.621371, 1),
            "timestamp": p["timestamp"]
        }
    except Exception as e:
        return None

def get_kalshi_market(event_ticker):
    """Get current market prices for a weather event."""
    url = f"https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker={event_ticker}&limit=50"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return data.get("markets", [])

def analyze_signal(city_name, city_config):
    """Generate trading signal based on weather data vs market prices."""
    # Get current observations
    primary_obs = get_obs(city_config["primary"])
    surrounding_obs = [get_obs(s) for s in city_config["surrounding"]]
    surrounding_obs = [o for o in surrounding_obs if o]
    
    if not primary_obs:
        return None
    
    # Calculate average surrounding temp
    if surrounding_obs:
        avg_surrounding = sum(o["temp_f"] for o in surrounding_obs) / len(surrounding_obs)
    else:
        avg_surrounding = primary_obs["temp_f"]
    
    return {
        "city": city_name,
        "current_temp": primary_obs["temp_f"],
        "surrounding_avg": round(avg_surrounding, 1),
        "timestamp": primary_obs["timestamp"]
    }

if __name__ == "__main__":
    print(f"=== Weather Check {datetime.utcnow().isoformat()} ===")
    for city, config in CITIES.items():
        signal = analyze_signal(city, config)
        if signal:
            print(f"{city}: Current {signal['current_temp']}°F, "
                  f"Surrounding avg {signal['surrounding_avg']}°F")
```

## Step 2: Signal Logic

### For HIGH temp markets (trade in morning):
```
IF current_temp > market_implied_high - 5°F AND time < 2PM:
    → BUY the bracket containing current_temp + expected_afternoon_rise
    
IF NWS_forecast_high > market_implied_high by 3°F+:
    → BUY higher brackets
    
IF surrounding_stations_avg > primary_station by 2°F+:
    → Warm air may be moving in → BUY higher brackets
```

### For LOW temp markets (trade in evening):
```
IF current_temp at 10PM < market_implied_low + 3°F:
    → Temps still dropping → BUY lower brackets
    
IF clear_sky AND low_humidity AND low_wind:
    → Radiative cooling = colder than forecast → BUY lower brackets
    
IF cloudy AND wind > 10mph:
    → Insulation effect = warmer than forecast → BUY higher brackets
```

## Step 3: Kalshi API Trading (requires auth)

```python
# Trading requires API key from Kalshi account
# POST /trade-api/v2/login with email/password
# Then POST /trade-api/v2/portfolio/orders with:
# {
#   "ticker": "KXHIGHNY-26FEB15-35",  
#   "action": "buy",
#   "side": "yes",
#   "count": 2,
#   "type": "limit",
#   "yes_price": 45  # in cents
# }
```

## Next Steps
1. [ ] Test the NWS API data collection script
2. [ ] Set up SQLite database for historical tracking
3. [ ] Paper trade for 1 week (track what you WOULD have traded)
4. [ ] Go live with 1-2 contracts per day
5. [ ] Build Telegram alerts for trade signals
