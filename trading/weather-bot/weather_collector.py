#!/usr/bin/env python3
"""
Weather data collector for Kalshi temperature trading.
Pulls real-time observations from NWS API and forecasts.
Stores everything in SQLite for signal generation.
"""

import json
import sqlite3
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Load config
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

DB_PATH = CONFIG["db_path"]
LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "collector.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("collector")

NWS_HEADERS = {"User-Agent": "KalshiWeatherBot/1.0 (drewclawdbot@proton.me)", "Accept": "application/geo+json"}
NWS_TIMEOUT = 10


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station TEXT NOT NULL,
            city TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            temp_f REAL,
            humidity REAL,
            wind_mph REAL,
            wind_dir INTEGER,
            pressure_mb REAL,
            cloud_cover TEXT,
            obs_time TEXT,
            collected_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            forecast_date TEXT NOT NULL,
            forecast_high_f REAL,
            forecast_low_f REAL,
            period_name TEXT,
            short_forecast TEXT,
            collected_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_obs_station_time ON observations(station, collected_at)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_obs_city_time ON observations(city, collected_at)
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized at %s", DB_PATH)


def nws_get(url: str, retries: int = 1) -> dict | None:
    """Make a GET request to NWS API with retries."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=NWS_HEADERS)
            with urllib.request.urlopen(req, timeout=NWS_TIMEOUT) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ConnectionError, json.JSONDecodeError) as e:
            log.warning("NWS request failed (attempt %d/%d) %s: %s", attempt + 1, retries + 1, url, e)
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    return None


def get_observation(station: str) -> dict | None:
    """Get latest observation from a NWS station."""
    url = f"https://api.weather.gov/stations/{station}/observations/latest"
    data = nws_get(url)
    if not data:
        return None

    try:
        p = data["properties"]
        temp_c = p.get("temperature", {}).get("value")
        if temp_c is None:
            log.debug("No temp data for station %s", station)
            return None

        humidity = p.get("relativeHumidity", {}).get("value")
        wind_speed_kmh = p.get("windSpeed", {}).get("value")
        wind_dir = p.get("windDirection", {}).get("value")
        pressure_pa = p.get("barometricPressure", {}).get("value")

        # Extract cloud cover from text description
        cloud_layers = p.get("cloudLayers", [])
        cloud_cover = cloud_layers[0].get("amount") if cloud_layers else None

        return {
            "temp_f": round(temp_c * 9 / 5 + 32, 1),
            "humidity": round(humidity, 1) if humidity is not None else None,
            "wind_mph": round(wind_speed_kmh * 0.621371, 1) if wind_speed_kmh is not None else None,
            "wind_dir": int(wind_dir) if wind_dir is not None else None,
            "pressure_mb": round(pressure_pa / 100, 1) if pressure_pa is not None else None,
            "cloud_cover": cloud_cover,
            "obs_time": p.get("timestamp"),
        }
    except (KeyError, TypeError) as e:
        log.warning("Error parsing observation for %s: %s", station, e)
        return None


def get_forecast(lat: float, lon: float) -> list[dict] | None:
    """Get NWS point forecast (high/low temps)."""
    # Step 1: Get forecast office from point
    point_url = f"https://api.weather.gov/points/{lat},{lon}"
    point_data = nws_get(point_url)
    if not point_data:
        return None

    try:
        forecast_url = point_data["properties"]["forecast"]
    except KeyError:
        log.warning("No forecast URL for point %s,%s", lat, lon)
        return None

    # Step 2: Get the forecast
    forecast_data = nws_get(forecast_url)
    if not forecast_data:
        return None

    try:
        periods = forecast_data["properties"]["periods"]
        results = []
        for p in periods[:4]:  # Next ~2 days
            results.append({
                "period_name": p.get("name"),
                "temperature": p.get("temperature"),
                "is_daytime": p.get("isDaytime"),
                "short_forecast": p.get("shortForecast"),
                "start_time": p.get("startTime"),
            })
        return results
    except (KeyError, TypeError) as e:
        log.warning("Error parsing forecast: %s", e)
        return None


def collect_city(city_name: str, city_config: dict, conn: sqlite3.Connection):
    """Collect all observations and forecasts for a city."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    collected = 0

    # Primary station
    obs = get_observation(city_config["primary"])
    if obs:
        cursor.execute(
            """INSERT INTO observations
               (station, city, is_primary, temp_f, humidity, wind_mph, wind_dir, pressure_mb, cloud_cover, obs_time, collected_at)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (city_config["primary"], city_name, obs["temp_f"], obs["humidity"],
             obs["wind_mph"], obs["wind_dir"], obs["pressure_mb"], obs["cloud_cover"],
             obs["obs_time"], now),
        )
        collected += 1
        log.info("  %s [PRIMARY] %s: %.1f°F", city_name, city_config["primary"], obs["temp_f"])
    else:
        log.warning("  %s [PRIMARY] %s: NO DATA", city_name, city_config["primary"])

    # Surrounding stations
    for station in city_config["surrounding"]:
        obs = get_observation(station)
        if obs:
            cursor.execute(
                """INSERT INTO observations
                   (station, city, is_primary, temp_f, humidity, wind_mph, wind_dir, pressure_mb, cloud_cover, obs_time, collected_at)
                   VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (station, city_name, obs["temp_f"], obs["humidity"],
                 obs["wind_mph"], obs["wind_dir"], obs["pressure_mb"], obs["cloud_cover"],
                 obs["obs_time"], now),
            )
            collected += 1
            log.info("  %s [SURR]    %s: %.1f°F", city_name, station, obs["temp_f"])
        else:
            log.debug("  %s [SURR]    %s: no data", city_name, station)
        time.sleep(0.3)  # Be nice to NWS API

    # Forecast
    forecasts = get_forecast(city_config["lat"], city_config["lon"])
    if forecasts:
        for fc in forecasts:
            temp = fc["temperature"]
            is_high = fc["is_daytime"]
            cursor.execute(
                """INSERT INTO forecasts
                   (city, forecast_date, forecast_high_f, forecast_low_f, period_name, short_forecast, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (city_name, fc["start_time"][:10],
                 temp if is_high else None,
                 temp if not is_high else None,
                 fc["period_name"], fc["short_forecast"], now),
            )
        log.info("  %s forecast: %d periods collected", city_name, len(forecasts))

    conn.commit()
    return collected


def collect_all():
    """Run a full collection cycle for all cities."""
    log.info("=" * 60)
    log.info("Starting collection cycle at %s", datetime.now(timezone.utc).isoformat())
    log.info("=" * 60)

    init_db()
    conn = sqlite3.connect(DB_PATH)
    total = 0

    for city_name, city_config in CONFIG["cities"].items():
        try:
            n = collect_city(city_name, city_config, conn)
            total += n
        except Exception as e:
            log.error("Failed to collect %s: %s", city_name, e, exc_info=True)
        time.sleep(0.5)  # Pause between cities

    conn.close()
    log.info("Collection complete: %d observations stored", total)
    return total


def get_latest_observations(city: str = None) -> list[dict]:
    """Get the most recent observation for each station, optionally filtered by city."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if city:
        c.execute("""
            SELECT * FROM observations
            WHERE city = ? AND id IN (
                SELECT MAX(id) FROM observations WHERE city = ? GROUP BY station
            )
            ORDER BY is_primary DESC, station
        """, (city, city))
    else:
        c.execute("""
            SELECT * FROM observations
            WHERE id IN (
                SELECT MAX(id) FROM observations GROUP BY station
            )
            ORDER BY city, is_primary DESC, station
        """)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_latest_forecast(city: str, target_date: str = None) -> dict | None:
    """Get the latest forecast high and low for a city.
    
    Args:
        city: City name
        target_date: Optional YYYY-MM-DD string. If provided, returns forecast 
                     for that specific date. If None, returns the nearest forecast.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if target_date:
        # Get forecast for a specific date
        c.execute("""
            SELECT * FROM forecasts
            WHERE city = ? AND forecast_date = ?
            ORDER BY collected_at DESC
            LIMIT 4
        """, (city, target_date))
    else:
        c.execute("""
            SELECT * FROM forecasts
            WHERE city = ?
            ORDER BY collected_at DESC
            LIMIT 4
        """, (city,))

    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        return None

    high = None
    low = None
    for r in rows:
        if r["forecast_high_f"] is not None and high is None:
            high = r["forecast_high_f"]
        if r["forecast_low_f"] is not None and low is None:
            low = r["forecast_low_f"]

    return {"city": city, "forecast_high_f": high, "forecast_low_f": low}


if __name__ == "__main__":
    collect_all()
