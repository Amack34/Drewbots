#!/usr/bin/env python3
"""
CLI vs METAR Backtest
Compares NWS Daily Climate Report settled temps against max METAR readings.
Answers: How often does the CLI report a different high than the max 5-min METAR?

Uses our historical trade data + Kalshi settlement data to find discrepancies.
"""

import json
import sqlite3
import logging
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger()

DB_PATH = 'weather.db'

# Map cities to NWS CLI product URLs
CLI_URLS = {
    'NYC': 'https://forecast.weather.gov/product.php?site=OKX&issuedby=NYC&product=CLI&format=txt',
    'PHI': 'https://forecast.weather.gov/product.php?site=PHI&issuedby=PHL&product=CLI&format=txt',
    'MIA': 'https://forecast.weather.gov/product.php?site=MFL&issuedby=MIA&product=CLI&format=txt',
    'BOS': 'https://forecast.weather.gov/product.php?site=BOX&issuedby=BOS&product=CLI&format=txt',
    'DC':  'https://forecast.weather.gov/product.php?site=LWX&issuedby=DCA&product=CLI&format=txt',
    'ATL': 'https://forecast.weather.gov/product.php?site=FFC&issuedby=ATL&product=CLI&format=txt',
}


def fetch_cli_report(city: str) -> str | None:
    """Fetch latest CLI report for a city."""
    url = CLI_URLS.get(city)
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'DrewOps/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode()
    except Exception as e:
        log.debug("CLI fetch failed for %s: %s", city, e)
        return None


def parse_cli_high(text: str) -> int | None:
    """Extract the high temperature from a CLI report."""
    import re
    # Look for "MAXIMUM TEMPERATURE" or "TEMPERATURE (F)" section
    # Format varies but typically: "MAXIMUM TEMPERATURE (F)    79"
    patterns = [
        r'MAXIMUM\s+TEMPERATURE[^\d]*(\d+)',
        r'TODAY\s*\n\s*MAXIMUM\s+TEMPERATURE[^\d]*(\d+)',
        r'TEMPERATURE.*MAXIMUM[^\d]*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_cli_low(text: str) -> int | None:
    """Extract the low temperature from a CLI report."""
    import re
    patterns = [
        r'MINIMUM\s+TEMPERATURE[^\d]*(\d+)',
        r'TEMPERATURE.*MINIMUM[^\d]*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def check_all_cities():
    """Fetch CLI reports for all cities and compare to our METAR data."""
    log.info("CLI vs METAR Comparison")
    log.info("=" * 60)
    
    from omo_fetcher import get_omo_high
    
    for city, url in CLI_URLS.items():
        log.info(f"\n--- {city} ---")
        
        # Get CLI report
        report = fetch_cli_report(city)
        if report:
            cli_high = parse_cli_high(report)
            cli_low = parse_cli_low(report)
            log.info(f"CLI: High={cli_high}°F Low={cli_low}°F")
        else:
            log.info("CLI: Not available")
            cli_high = None
        
        # Get our METAR-based high
        omo = get_omo_high(city)
        if omo:
            metar_high = omo['temp_f']
            source = omo['source']
            rng = omo['rounding_range']
            log.info(f"METAR: High={metar_high:.1f}°F (source={source}, range={rng[0]:.1f}-{rng[1]:.1f}°F)")
        else:
            metar_high = None
            log.info("METAR: Not available")
        
        # Compare
        if cli_high and metar_high:
            diff = cli_high - metar_high
            if abs(diff) > 0.5:
                log.info(f"⚠️ DISCREPANCY: CLI={cli_high}°F vs METAR={metar_high:.1f}°F (diff={diff:+.1f}°F)")
            else:
                log.info(f"✅ MATCH: CLI={cli_high}°F ≈ METAR={metar_high:.1f}°F")


if __name__ == '__main__':
    check_all_cities()


def daily_cli_check():
    """Run after 10am ET — compare today's CLI to yesterday's METAR data.
    Logs results to DB for long-term analysis."""
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    db.execute('''CREATE TABLE IF NOT EXISTS cli_vs_metar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, city TEXT, cli_high INTEGER, cli_low INTEGER,
        metar_max_5min REAL, metar_max_speci REAL,
        diff_high REAL, source TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    db.commit()
    
    from omo_fetcher import get_nws_detailed_temps, STATIONS
    
    for city in CLI_URLS:
        report = fetch_cli_report(city)
        if not report:
            continue
        cli_high = parse_cli_high(report)
        cli_low = parse_cli_low(report)
        if not cli_high:
            continue
        
        # Get yesterday's METAR data
        station = STATIONS.get(city, city)
        temps = get_nws_detailed_temps(station, hours=36)
        if not temps:
            continue
        
        speci = [t for t in temps if t['is_speci']]
        max_5min = max(t['temp_f'] for t in temps) if temps else None
        max_speci = max(t['temp_f'] for t in speci) if speci else None
        
        diff = cli_high - max_5min if max_5min else None
        
        db.execute('''INSERT INTO cli_vs_metar 
            (date, city, cli_high, cli_low, metar_max_5min, metar_max_speci, diff_high, source)
            VALUES (date('now', '-1 day'), ?, ?, ?, ?, ?, ?, 'auto')''',
            (city, cli_high, cli_low, max_5min, max_speci, diff))
    
    db.commit()
    db.close()
    log.info("CLI vs METAR data saved to DB")
