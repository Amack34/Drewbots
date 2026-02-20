#!/usr/bin/env python3
"""
OMO (One-Minute Observation) Fetcher
Provides access to high-resolution ASOS temperature data that the CLI uses for settlement.

Data sources (in priority order):
1. Synoptic Data API (1-minute, real-time, needs API key)
2. NCEI 5-minute archive (delayed ~1-2 days, free, no key)
3. NWS API observations (5-min with rounding ambiguity, free)

The key insight: METAR 5-min readings go through C/F rounding that can hide ±1°F.
OMO/Synoptic data gives us the ACTUAL temperature the CLI will use.

Usage:
    from omo_fetcher import get_omo_high, get_omo_temps
    high = get_omo_high('KATL')  # Returns actual daily high in °F
    temps = get_omo_temps('KATL', hours=6)  # Last 6 hours of 1-min data
"""

import json
import os
import logging
import urllib.request
from datetime import datetime, timezone, timedelta

log = logging.getLogger("omo_fetcher")

# Synoptic Data API token — set via env or config
SYNOPTIC_TOKEN = os.environ.get('SYNOPTIC_TOKEN', '')

# Our 6 settlement stations
STATIONS = {
    'NYC': 'KNYC', 'PHI': 'KPHL', 'MIA': 'KMIA',
    'BOS': 'KBOS', 'DC': 'KDCA', 'ATL': 'KATL',
}


def get_synoptic_temps(station: str, hours: int = 24) -> list[dict] | None:
    """Fetch 1-minute temps from Synoptic Data API. Requires SYNOPTIC_TOKEN."""
    if not SYNOPTIC_TOKEN:
        return None
    
    try:
        # Use the 1M (1-minute) station variant
        stid = f"{station}1M"
        url = (f"https://api.synopticdata.com/v2/stations/timeseries?"
               f"stid={stid}&vars=air_temp&units=temp|F"
               f"&recent={hours * 60}&token={SYNOPTIC_TOKEN}")
        req = urllib.request.Request(url, headers={'User-Agent': 'DrewOps-OMO/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        if data.get('SUMMARY', {}).get('RESPONSE_CODE') != 1:
            log.warning("Synoptic API error: %s", data.get('SUMMARY', {}).get('RESPONSE_MESSAGE'))
            return None
        
        station_data = data.get('STATION', [{}])[0]
        obs = station_data.get('OBSERVATIONS', {})
        temps = obs.get('air_temp_set_1', [])
        times = obs.get('date_time', [])
        
        result = []
        for t, ts in zip(temps, times):
            if t is not None:
                result.append({'temp_f': t, 'time': ts, 'source': 'synoptic_1min'})
        
        log.info("Synoptic: got %d 1-min readings for %s", len(result), station)
        return result if result else None
    except Exception as e:
        log.debug("Synoptic fetch failed for %s: %s", station, e)
        return None


def get_iem_hourly_temps(station: str) -> list[dict] | None:
    """Fetch hourly METAR temps from Iowa Environmental Mesonet (IEM).
    These are the official hourly observations (:52 readings) with higher precision.
    FREE, no API key needed."""
    try:
        # Strip the K prefix for IEM (KATL -> ATL)
        iem_station = station[1:] if station.startswith('K') else station
        now = datetime.now(timezone.utc)
        # Use ET date for the trading day
        et = timezone(timedelta(hours=-5))
        now_et = datetime.now(et)
        
        url = (f"https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"
               f"station={iem_station}&data=tmpf&tz=UTC&format=onlycomma&latlon=no"
               f"&elev=no&missing=M&direct=no&report_type=3&report_type=4"
               f"&year1={now_et.year}&month1={now_et.month}&day1={now_et.day}"
               f"&hour1=0&minute1=0"
               f"&year2={now_et.year}&month2={now_et.month}&day2={now_et.day}"
               f"&hour2=23&minute2=59")
        
        req = urllib.request.Request(url, headers={'User-Agent': 'DrewOps-OMO/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode()
        
        result = []
        for line in data.strip().split('\n')[1:]:  # skip header
            parts = line.split(',')
            if len(parts) >= 3:
                try:
                    temp_f = float(parts[2])
                    time_str = parts[1]
                    result.append({
                        'temp_f': temp_f,
                        'time': time_str,
                        'source': 'iem_hourly',
                        'is_speci': True,  # Hourly METARs are precise
                        'rounding_ambiguity': False,
                    })
                except (ValueError, IndexError):
                    continue
        
        if result:
            log.info("IEM: got %d hourly readings for %s", len(result), station)
        return result if result else None
    except Exception as e:
        log.debug("IEM fetch failed for %s: %s", station, e)
        return None


def get_nws_detailed_temps(station: str, hours: int = 24) -> list[dict] | None:
    """Fetch all NWS observations (5-min) for a station. Free, no key needed.
    NOTE: These have C/F rounding ambiguity — actual temp could be ±1°F."""
    try:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        url = f'https://api.weather.gov/stations/{station}/observations?start={start}'
        req = urllib.request.Request(url, headers={'User-Agent': 'DrewOps-OMO/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        result = []
        for feat in data.get('features', []):
            props = feat['properties']
            temp_c = props.get('temperature', {}).get('value')
            if temp_c is None:
                continue
            temp_f = round(temp_c * 9/5 + 32, 1)
            ts = props.get('timestamp', '')
            
            # Detect if this is a SPECI (more precise) or regular 5-min
            minute = int(ts.split(':')[1]) if ':' in ts else -1
            is_speci = minute in (51, 52, 53, 54)
            
            result.append({
                'temp_f': temp_f,
                'temp_c': temp_c,
                'time': ts,
                'is_speci': is_speci,
                'source': 'nws_speci' if is_speci else 'nws_5min',
                'rounding_ambiguity': not is_speci,  # 5-min has ±1°F ambiguity
            })
        
        return result if result else None
    except Exception as e:
        log.debug("NWS fetch failed for %s: %s", station, e)
        return None


def get_omo_high(city_or_station: str, hours: int = 24) -> dict | None:
    """Get the best estimate of actual daily high temperature.
    
    Returns dict with:
        temp_f: float — best estimate of actual high
        source: str — where the data came from
        confidence: str — 'exact' (OMO), 'high' (SPECI), 'ambiguous' (5-min, ±1°F)
        rounding_range: tuple — (min_possible, max_possible) accounting for rounding
    """
    station = STATIONS.get(city_or_station, city_or_station)
    
    # Try Synoptic 1-minute first (best data)
    temps = get_synoptic_temps(station, hours)
    if temps:
        max_temp = max(temps, key=lambda x: x['temp_f'])
        return {
            'temp_f': max_temp['temp_f'],
            'time': max_temp['time'],
            'source': 'synoptic_1min',
            'confidence': 'exact',
            'rounding_range': (max_temp['temp_f'], max_temp['temp_f']),
        }
    
    # Try IEM hourly METARs (precise, free)
    iem_temps = get_iem_hourly_temps(station)
    if iem_temps:
        max_temp = max(iem_temps, key=lambda x: x['temp_f'])
        return {
            'temp_f': max_temp['temp_f'],
            'time': max_temp['time'],
            'source': 'iem_hourly',
            'confidence': 'high',
            'rounding_range': (max_temp['temp_f'] - 0.5, max_temp['temp_f'] + 0.5),
        }
    
    # Fall back to NWS (has rounding issues)
    temps = get_nws_detailed_temps(station, hours)
    if temps:
        # Check SPECI readings first (more precise)
        speci_temps = [t for t in temps if t['is_speci']]
        all_max = max(temps, key=lambda x: x['temp_f'])
        speci_max = max(speci_temps, key=lambda x: x['temp_f']) if speci_temps else None
        
        # Best estimate: use SPECI if it's the highest, otherwise 5-min with ambiguity
        if speci_max and speci_max['temp_f'] >= all_max['temp_f']:
            return {
                'temp_f': speci_max['temp_f'],
                'time': speci_max['time'],
                'source': 'nws_speci',
                'confidence': 'high',
                'rounding_range': (speci_max['temp_f'] - 0.5, speci_max['temp_f'] + 0.5),
            }
        else:
            # 5-min data: ±1°F rounding ambiguity
            return {
                'temp_f': all_max['temp_f'],
                'time': all_max['time'],
                'source': 'nws_5min',
                'confidence': 'ambiguous',
                'rounding_range': (all_max['temp_f'] - 1.0, all_max['temp_f'] + 1.0),
            }
    
    return None


def get_omo_low(city_or_station: str, hours: int = 24) -> dict | None:
    """Same as get_omo_high but for daily low."""
    station = STATIONS.get(city_or_station, city_or_station)
    
    temps = get_synoptic_temps(station, hours)
    if temps:
        min_temp = min(temps, key=lambda x: x['temp_f'])
        return {
            'temp_f': min_temp['temp_f'],
            'time': min_temp['time'],
            'source': 'synoptic_1min',
            'confidence': 'exact',
            'rounding_range': (min_temp['temp_f'], min_temp['temp_f']),
        }
    
    iem_temps = get_iem_hourly_temps(station)
    if iem_temps:
        min_temp = min(iem_temps, key=lambda x: x['temp_f'])
        return {
            'temp_f': min_temp['temp_f'],
            'time': min_temp['time'],
            'source': 'iem_hourly',
            'confidence': 'high',
            'rounding_range': (min_temp['temp_f'] - 0.5, min_temp['temp_f'] + 0.5),
        }
    
    temps = get_nws_detailed_temps(station, hours)
    if temps:
        speci_temps = [t for t in temps if t['is_speci']]
        all_min = min(temps, key=lambda x: x['temp_f'])
        speci_min = min(speci_temps, key=lambda x: x['temp_f']) if speci_temps else None
        
        if speci_min and speci_min['temp_f'] <= all_min['temp_f']:
            return {
                'temp_f': speci_min['temp_f'],
                'time': speci_min['time'],
                'source': 'nws_speci',
                'confidence': 'high',
                'rounding_range': (speci_min['temp_f'] - 0.5, speci_min['temp_f'] + 0.5),
            }
        else:
            return {
                'temp_f': all_min['temp_f'],
                'time': all_min['time'],
                'source': 'nws_5min',
                'confidence': 'ambiguous',
                'rounding_range': (all_min['temp_f'] - 1.0, all_min['temp_f'] + 1.0),
            }
    
    return None


def check_bracket_risk(city: str, bracket_low: float, bracket_high: float, 
                       market_type: str = 'high') -> dict:
    """Check if a bracket is at risk based on OMO data.
    
    Returns:
        risk: 'safe', 'watch', 'danger', 'in_bracket'
        detail: explanation
    """
    if market_type == 'high':
        omo = get_omo_high(city)
    else:
        omo = get_omo_low(city)
    
    if not omo:
        return {'risk': 'unknown', 'detail': 'No OMO data available'}
    
    temp = omo['temp_f']
    low_range, high_range = omo['rounding_range']
    
    # Check if actual temp or rounding range overlaps bracket
    if bracket_low <= temp <= bracket_high:
        return {'risk': 'in_bracket', 'detail': f"OMO {temp:.1f}°F IS in bracket [{bracket_low}-{bracket_high}]",
                'omo': omo}
    
    if bracket_low <= high_range and low_range <= bracket_high:
        return {'risk': 'danger', 'detail': f"OMO {temp:.1f}°F ±rounding could be in bracket [{bracket_low}-{bracket_high}]",
                'omo': omo}
    
    margin = min(abs(temp - bracket_low), abs(temp - bracket_high))
    if margin < 2.0:
        return {'risk': 'watch', 'detail': f"OMO {temp:.1f}°F only {margin:.1f}°F from bracket edge",
                'omo': omo}
    
    return {'risk': 'safe', 'detail': f"OMO {temp:.1f}°F, {margin:.1f}°F from bracket", 'omo': omo}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("OMO Fetcher — Daily Highs for All Cities")
    print("=" * 55)
    for city, station in STATIONS.items():
        high = get_omo_high(city)
        if high:
            print(f"{city} ({station}): {high['temp_f']:.1f}°F | source={high['source']} "
                  f"| confidence={high['confidence']} | range={high['rounding_range']}")
        else:
            print(f"{city} ({station}): No data")
    
    print("\n--- Bracket Risk Check: ATL 79-80°F ---")
    risk = check_bracket_risk('ATL', 79.0, 80.0, 'high')
    print(f"Risk: {risk['risk']} — {risk['detail']}")
