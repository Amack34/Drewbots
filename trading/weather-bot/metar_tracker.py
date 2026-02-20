#!/usr/bin/env python3
"""
METAR tracker for Kalshi weather trading bot.
Fetches real-time METAR observations from NWS for the 6 settlement stations
and tracks running daily high and low temperatures for lock-in trading signals.
"""

import json
import sqlite3
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
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
        logging.FileHandler(LOG_DIR / "metar_tracker.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("metar_tracker")

# Same headers and timeout as weather_collector.py
NWS_HEADERS = {"User-Agent": "KalshiWeatherBot/1.0 (drewclawdbot@proton.me)", "Accept": "application/geo+json"}
NWS_TIMEOUT = 10

# Settlement stations mapping from config
SETTLEMENT_STATIONS = {
    "NYC": "KNYC",
    "PHI": "KPHL", 
    "MIA": "KMIA",
    "BOS": "KBOS",
    "DC": "KDCA",
    "ATL": "KATL"
}


def init_metar_db():
    """Create METAR daily extremes table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS metar_daily_extremes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station TEXT NOT NULL,
            date TEXT NOT NULL,
            running_high_f REAL,
            running_low_f REAL,
            last_updated TEXT NOT NULL,
            observation_count INTEGER DEFAULT 0,
            UNIQUE(station, date)
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_metar_station_date ON metar_daily_extremes(station, date)
    """)
    conn.commit()
    conn.close()
    log.info("METAR daily extremes table initialized")


def nws_get(url: str, retries: int = 1) -> dict | None:
    """Make a GET request to NWS API with retries. Same as weather_collector."""
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


def get_latest_metar(station: str) -> dict | None:
    """Get latest METAR observation from NWS for a specific station."""
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

        return {
            "station": station,
            "temp_f": round(temp_c * 9 / 5 + 32, 1),
            "obs_time": p.get("timestamp"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat()
        }
    except (KeyError, TypeError) as e:
        log.warning("Error parsing METAR for %s: %s", station, e)
        return None


def get_today_date_et() -> str:
    """Get today's date in ET timezone (what Kalshi uses for settlement)."""
    now_et = datetime.now(timezone.utc) - timedelta(hours=5)  # UTC-5 for ET
    return now_et.strftime("%Y-%m-%d")


def get_daily_extremes(station: str) -> dict | None:
    """Get current running high and low for today for a station."""
    init_metar_db()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    today_et = get_today_date_et()
    c.execute("""
        SELECT * FROM metar_daily_extremes 
        WHERE station = ? AND date = ?
    """, (station, today_et))
    
    row = c.fetchone()
    conn.close()
    
    if not row:
        return {
            "station": station,
            "date": today_et,
            "running_high_f": None,
            "running_low_f": None,
            "last_updated": None,
            "observation_count": 0
        }
    
    return {
        "station": row["station"],
        "date": row["date"],
        "running_high_f": row["running_high_f"],
        "running_low_f": row["running_low_f"],
        "last_updated": row["last_updated"],
        "observation_count": row["observation_count"]
    }


def update_from_metar(station: str) -> bool:
    """Fetch latest METAR and update running extremes for a station."""
    init_metar_db()
    
    # Get latest METAR observation
    metar = get_latest_metar(station)
    if not metar:
        log.warning("No METAR data for %s", station)
        return False
    
    temp_f = metar["temp_f"]
    today_et = get_today_date_et()
    now_utc = datetime.now(timezone.utc).isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get current extremes
    c.execute("""
        SELECT running_high_f, running_low_f, observation_count 
        FROM metar_daily_extremes 
        WHERE station = ? AND date = ?
    """, (station, today_et))
    
    row = c.fetchone()
    
    if row:
        # Update existing record
        current_high = row[0]
        current_low = row[1]
        count = row[2]
        
        new_high = max(current_high, temp_f) if current_high is not None else temp_f
        new_low = min(current_low, temp_f) if current_low is not None else temp_f
        
        c.execute("""
            UPDATE metar_daily_extremes 
            SET running_high_f = ?, running_low_f = ?, last_updated = ?, observation_count = ?
            WHERE station = ? AND date = ?
        """, (new_high, new_low, now_utc, count + 1, station, today_et))
        
        log.info("Updated %s: %.1f°F (high: %.1f°F, low: %.1f°F, count: %d)", 
                station, temp_f, new_high, new_low, count + 1)
    else:
        # Insert new record
        c.execute("""
            INSERT INTO metar_daily_extremes 
            (station, date, running_high_f, running_low_f, last_updated, observation_count)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (station, today_et, temp_f, temp_f, now_utc))
        
        log.info("New record for %s: %.1f°F (first observation)", station, temp_f)
    
    conn.commit()
    conn.close()
    return True


def update_all_stations() -> int:
    """Update all 6 settlement stations. Returns number of successful updates."""
    log.info("=" * 60)
    log.info("Starting METAR update cycle at %s", datetime.now(timezone.utc).isoformat())
    log.info("=" * 60)
    
    success_count = 0
    
    for city, station in SETTLEMENT_STATIONS.items():
        try:
            if update_from_metar(station):
                success_count += 1
            time.sleep(0.5)  # Be nice to NWS API
        except Exception as e:
            log.error("Failed to update %s (%s): %s", city, station, e, exc_info=True)
    
    log.info("METAR update complete: %d/%d stations updated successfully", 
             success_count, len(SETTLEMENT_STATIONS))
    return success_count


def get_all_daily_extremes() -> dict:
    """Get current running extremes for all settlement stations."""
    extremes = {}
    for city, station in SETTLEMENT_STATIONS.items():
        extremes[city] = get_daily_extremes(station)
    return extremes


def display_current_status():
    """Display current METAR status for all stations."""
    print(f"\nMETAR Daily Extremes - {get_today_date_et()} (ET)")
    print("=" * 70)
    
    for city, station in SETTLEMENT_STATIONS.items():
        data = get_daily_extremes(station)
        if data["running_high_f"] is not None:
            print(f"{city:3} ({station}): High {data['running_high_f']:5.1f}°F  "
                  f"Low {data['running_low_f']:5.1f}°F  "
                  f"({data['observation_count']} obs)")
        else:
            print(f"{city:3} ({station}): No data yet")
    
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="METAR tracker for weather bot")
    parser.add_argument("--update", action="store_true", help="Update all stations")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--station", help="Update specific station")
    
    args = parser.parse_args()
    
    if args.update:
        update_all_stations()
        display_current_status()
    elif args.status:
        display_current_status()
    elif args.station:
        if update_from_metar(args.station.upper()):
            data = get_daily_extremes(args.station.upper())
            print(f"Updated {args.station.upper()}: {data}")
        else:
            print(f"Failed to update {args.station.upper()}")
    else:
        # Default: update all and show status
        update_all_stations()
        display_current_status()