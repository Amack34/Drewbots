#!/usr/bin/env python3
"""
Lightweight real-time temperature tracker for all 6 trading cities.
Polls NWS METAR every 2 minutes, tracks running daily highs/lows.
Stores state in a small JSON file for other tools to read.

Usage:
    python3 temp_tracker.py              # Run daemon (foreground)
    python3 temp_tracker.py --status     # Print current readings
    python3 temp_tracker.py --json       # Print JSON for other tools

Memory: ~5MB RSS. CPU: negligible (one HTTP call per station every 2 min).
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

STATE_FILE = os.path.join(os.path.dirname(__file__), 'temp_state.json')

# Settlement stations for each city
CITIES = {
    'NYC': {'station': 'KNYC', 'name': 'New York (Central Park)'},
    'PHI': {'station': 'KPHL', 'name': 'Philadelphia'},
    'MIA': {'station': 'KMIA', 'name': 'Miami'},
    'BOS': {'station': 'KBOS', 'name': 'Boston'},
    'DC':  {'station': 'KDCA', 'name': 'Washington DC'},
    'ATL': {'station': 'KATL', 'name': 'Atlanta'},
}

POLL_INTERVAL = 120  # seconds


def get_temp(station):
    """Fetch latest temp from NWS. Returns (temp_f, timestamp_utc, is_speci) or (None, None, False)."""
    try:
        url = f'https://api.weather.gov/stations/{station}/observations/latest'
        req = urllib.request.Request(url, headers={'User-Agent': 'DrewOps-TempTracker/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        props = data['properties']
        temp_c = props['temperature']['value']
        if temp_c is None:
            return None, None, False
        temp_f = round(temp_c * 9 / 5 + 32, 1)
        ts = props['timestamp']
        # SPECI detection: special observations typically at :51-:54 (hourly) or odd minutes
        # The :52 readings are hourly reports with higher precision
        minute = int(ts.split(':')[1]) if ':' in ts else -1
        is_speci = minute in (51, 52, 53, 54)  # Hourly obs = more precise
        return temp_f, ts, is_speci
    except Exception:
        return None, None, False


def get_et_date():
    """Get current date in ET (for daily reset)."""
    et = timezone(timedelta(hours=-5))
    return datetime.now(et).strftime('%Y-%m-%d')


def load_state():
    """Load state from file, reset if date changed."""
    today = get_et_date()
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
        if state.get('date') != today:
            return new_state(today)
        return state
    except (FileNotFoundError, json.JSONDecodeError):
        return new_state(today)


def new_state(date):
    """Create fresh state for a new day."""
    state = {'date': date, 'cities': {}, 'updated': None}
    for city in CITIES:
        state['cities'][city] = {
            'current': None,
            'high': None,
            'low': None,
            'high_time': None,
            'low_time': None,
            'last_obs': None,
        }
    return state


def save_state(state):
    """Atomic write to state file."""
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def update_city(state, city, temp_f, obs_time, is_speci=False):
    """Update running high/low for a city."""
    c = state['cities'][city]
    c['current'] = temp_f
    c['last_obs'] = obs_time
    c['is_speci'] = is_speci

    if c['high'] is None or temp_f > c['high']:
        c['high'] = temp_f
        c['high_time'] = obs_time
        c['high_is_speci'] = is_speci

    if c['low'] is None or temp_f < c['low']:
        c['low'] = temp_f
        c['low_time'] = obs_time
        c['low_is_speci'] = is_speci


def poll_all(state):
    """Poll all cities, update state."""
    today = get_et_date()
    if state.get('date') != today:
        state = new_state(today)

    for city, info in CITIES.items():
        temp_f, obs_time, is_speci = get_temp(info['station'])
        if temp_f is not None:
            update_city(state, city, temp_f, obs_time, is_speci)
        time.sleep(0.2)  # Be nice to NWS API

    state['updated'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return state


def print_status(state):
    """Pretty print current readings."""
    print(f"🌡️  Temperature Tracker — {state.get('date', '?')} (ET)")
    print(f"   Updated: {state.get('updated', 'never')}")
    print(f"{'City':<6} {'Current':>8} {'High':>8} {'Low':>8}  {'High Time'}")
    print("-" * 55)
    for city in ['NYC', 'PHI', 'MIA', 'BOS', 'DC', 'ATL']:
        c = state['cities'].get(city, {})
        cur = f"{c['current']:.1f}°F" if c.get('current') else '  --  '
        hi = f"{c['high']:.1f}°F" if c.get('high') else '  --  '
        lo = f"{c['low']:.1f}°F" if c.get('low') else '  --  '
        ht = c.get('high_time', '')
        if ht:
            # Extract just the time portion
            try:
                ht = ht.split('T')[1][:5] + ' UTC'
            except:
                pass
        print(f"{city:<6} {cur:>8} {hi:>8} {lo:>8}  {ht}")


def main():
    if '--status' in sys.argv:
        state = load_state()
        print_status(state)
        return

    if '--json' in sys.argv:
        state = load_state()
        print(json.dumps(state, indent=2))
        return

    # Daemon mode
    print(f"[temp_tracker] Starting — polling {len(CITIES)} cities every {POLL_INTERVAL}s")
    print(f"[temp_tracker] State file: {STATE_FILE}")

    state = load_state()
    while True:
        try:
            state = poll_all(state)
            # Log compact status
            parts = []
            for city in ['NYC', 'PHI', 'MIA', 'BOS', 'DC', 'ATL']:
                c = state['cities'][city]
                if c['current']:
                    parts.append(f"{city}:{c['current']:.0f}(H{c['high']:.0f}/L{c['low']:.0f})")
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {' | '.join(parts)}")
        except Exception as e:
            print(f"[temp_tracker] Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
