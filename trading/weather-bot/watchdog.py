#!/usr/bin/env python3
"""
Trading Watchdog — Dead Man's Switch

Runs as a systemd service. Checks if the bot has run a cycle recently.
If not (Claude rate-limited / offline), runs the bot cycle directly.

Logic:
1. Every CHECK_INTERVAL, look at bot.log for the last successful cycle timestamp
2. If no cycle in STALE_THRESHOLD seconds, run bot.py directly
3. Respects trading hours (6am-11pm ET) and daily trade caps
4. Logs everything for review when Claude comes back online

This is a FALLBACK only — does nothing when Claude is running cycles normally.
"""

import subprocess
import time
import sys
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BOT_DIR = Path(__file__).parent
LOG_DIR = BOT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "watchdog.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("watchdog")

# How often to check (seconds)
CHECK_INTERVAL = 300  # 5 minutes

# How long before we consider Claude "down" and take over (seconds)
STALE_THRESHOLD = 2700  # 45 minutes (normal cycle is every 30 min)

# Trading hours in ET (UTC-5)
TRADING_HOUR_START = 6   # 6am ET
TRADING_HOUR_END = 23    # 11pm ET

# Track if we've taken over this "outage"
fallback_cycles_run = 0


def get_et_now():
    """Current time in US/Eastern (UTC-5, no DST handling — close enough)."""
    return datetime.now(timezone(timedelta(hours=-5)))


def in_trading_hours():
    """Check if we're within trading hours."""
    now = get_et_now()
    return TRADING_HOUR_START <= now.hour < TRADING_HOUR_END


def get_last_cycle_time():
    """Parse bot.log for the most recent successful cycle timestamp."""
    bot_log = LOG_DIR / "bot.log"
    if not bot_log.exists():
        return None

    # Read last 200 lines
    try:
        lines = bot_log.read_text().strip().split("\n")[-200:]
    except Exception:
        return None

    # Look for cycle completion markers
    # bot.py logs lines like: "2026-02-15 19:00:05,123 [INFO] === Weather Bot Cycle ==="
    # or paper trade summaries, etc.
    last_ts = None
    for line in lines:
        match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if match and ("Cycle" in line or "cycle" in line or "trades placed" in line.lower() or "paper" in line.lower()):
            try:
                last_ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    return last_ts


def is_claude_stale():
    """Check if Claude hasn't run a cycle within the threshold."""
    last = get_last_cycle_time()
    if last is None:
        log.warning("No cycle timestamps found in bot.log — assuming stale")
        return True

    age = (datetime.now(timezone.utc) - last).total_seconds()
    log.info(f"Last cycle: {last.isoformat()} ({age:.0f}s ago, threshold: {STALE_THRESHOLD}s)")
    return age > STALE_THRESHOLD


def run_bot_cycle(mode="--paper"):
    """Run bot.py directly as a subprocess."""
    global fallback_cycles_run
    cmd = [sys.executable, str(BOT_DIR / "bot.py"), mode, "--yes"]
    log.info(f"FALLBACK: Running bot cycle: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(BOT_DIR),
        )
        fallback_cycles_run += 1
        if result.returncode == 0:
            log.info(f"FALLBACK cycle #{fallback_cycles_run} completed successfully")
            if result.stdout:
                # Log last 20 lines of output
                for line in result.stdout.strip().split("\n")[-20:]:
                    log.info(f"  bot: {line}")
        else:
            log.error(f"FALLBACK cycle #{fallback_cycles_run} failed (rc={result.returncode})")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    log.error(f"  err: {line}")
    except subprocess.TimeoutExpired:
        log.error("FALLBACK cycle timed out after 120s")
    except Exception as e:
        log.error(f"FALLBACK cycle error: {e}")


def main():
    log.info("Watchdog started — monitoring for Claude outages")
    log.info(f"Check interval: {CHECK_INTERVAL}s, Stale threshold: {STALE_THRESHOLD}s")
    log.info(f"Trading hours: {TRADING_HOUR_START}:00-{TRADING_HOUR_END}:00 ET")

    global fallback_cycles_run

    while True:
        try:
            if not in_trading_hours():
                log.debug("Outside trading hours — sleeping")
                time.sleep(CHECK_INTERVAL)
                continue

            if is_claude_stale():
                log.warning("Claude appears offline — running fallback cycle")
                run_bot_cycle("--live --yes")  # LIVE MODE — approved by Drew Feb 16
                # After running, wait longer before next check (avoid rapid-fire)
                time.sleep(STALE_THRESHOLD // 2)
            else:
                # Claude is running fine — reset fallback counter
                if fallback_cycles_run > 0:
                    log.info(f"Claude back online — ran {fallback_cycles_run} fallback cycles during outage")
                    fallback_cycles_run = 0
                time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Watchdog stopped")
            break
        except Exception as e:
            log.error(f"Watchdog error: {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
