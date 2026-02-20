#!/usr/bin/env python3
"""
Continuous price monitor for Kalshi positions.
Polls open positions every N seconds and auto-sells at take-profit threshold.
Designed to run as a persistent background process.
"""

import json
import time
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from kalshi_trader import KalshiClient, CONFIG

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "price_monitor.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("price_monitor")

# Config
POLL_INTERVAL = 30          # seconds between checks when positions exist
IDLE_INTERVAL = 300         # seconds between checks when no positions
TAKE_PROFIT_PCT = CONFIG["risk"].get("take_profit_pct", 35)
RATE_LIMIT_DELAY = 0.2      # seconds between API calls
PID_FILE = Path(__file__).parent / "price_monitor.pid"


def get_metar_temp(station: str) -> float | None:
    """Fetch current temp from a METAR station via NWS API."""
    import urllib.request
    try:
        url = f"https://api.weather.gov/stations/{station}/observations/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "DrewOps/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            temp_c = data["properties"]["temperature"]["value"]
            if temp_c is not None:
                return round(temp_c * 9 / 5 + 32, 1)
    except Exception:
        pass
    return None


def parse_position_bracket(ticker: str) -> dict | None:
    """Parse a Kalshi weather ticker to extract city, type, and bracket bounds.
    
    Examples:
        KXHIGHNY-26FEB15-B36.5 -> NYC high, bracket [36, 37]
        KXLOWTPHIL-26FEB16-T29 -> PHI low, threshold <=29
    """
    # Map Kalshi prefixes to city and METAR station
    CITY_MAP = {
        "KXHIGHNY": ("NYC", "KNYC", "high"),
        "KXHIGHPHIL": ("PHI", "KPHL", "high"),
        "KXHIGHMIA": ("MIA", "KMIA", "high"),
        "KXHIGHTBOS": ("BOS", "KBOS", "high"),
        "KXHIGHTDC": ("DC", "KDCA", "high"),
        "KXHIGHTATL": ("ATL", "KATL", "high"),
        "KXLOWTNYC": ("NYC", "KNYC", "low"),
        "KXLOWTPHIL": ("PHI", "KPHL", "low"),
        "KXLOWTMIA": ("MIA", "KMIA", "low"),
    }
    
    parts = ticker.split("-")
    if len(parts) < 3:
        return None
    
    prefix = parts[0]
    bracket_part = parts[-1]
    
    city_info = CITY_MAP.get(prefix)
    if not city_info:
        return None
    
    city, station, market_type = city_info
    
    if bracket_part.startswith("B"):
        # Bracket: B36.5 -> [36, 37]
        try:
            mid = float(bracket_part[1:])
            return {
                "city": city, "station": station, "type": market_type,
                "kind": "bracket", "low": int(mid - 0.5), "high": int(mid + 0.5)
            }
        except ValueError:
            return None
    elif bracket_part.startswith("T"):
        # Threshold: T29 -> <=29 or >=29 depending on market type
        try:
            threshold = float(bracket_part[1:])
            return {
                "city": city, "station": station, "type": market_type,
                "kind": "threshold", "threshold": threshold
            }
        except ValueError:
            return None
    return None


def is_position_dead(bracket_info: dict, current_temp: float, side: str) -> tuple[bool, str]:
    """Determine if a position is mathematically dead given current temp.
    
    For YES positions on HIGH temp brackets:
      - If current temp already EXCEEDS cap and it's afternoon = bracket is dead
        (high was already recorded above this bracket)
      - If current temp is far below floor late in the day = unlikely to reach
    
    For NO positions: inverse logic.
    
    Returns (is_dead, reason)
    """
    now_utc = datetime.now(timezone.utc)
    hour_et = (now_utc.hour - 5) % 24
    
    if bracket_info["kind"] == "bracket":
        low = bracket_info["low"]
        high = bracket_info["high"]
        mtype = bracket_info["type"]
        
        if mtype == "high" and side == "yes":
            # YES on a high bracket: we need the daily high to land IN [low, high]
            # Dead if: current temp already well above the bracket (high already exceeded cap)
            if current_temp > high + 2 and hour_et >= 12:
                return True, f"Current {current_temp}°F already above bracket [{low}-{high}]°F — high is past this range"
            # Dead if: it's late and temp is way below the bracket floor
            if current_temp < low - 5 and hour_et >= 15:
                return True, f"Current {current_temp}°F, {low - current_temp:.0f}°F below bracket [{low}-{high}]°F at {hour_et}:00 ET — can't reach"
                
        elif mtype == "high" and side == "no":
            # NO on a high bracket: we need the daily high to NOT land in [low, high]
            # Dead if: current temp is solidly in the bracket and it's peak hours
            if low <= current_temp <= high and 13 <= hour_et <= 16:
                return True, f"Current {current_temp}°F is IN bracket [{low}-{high}]°F during peak — high likely lands here"

        elif mtype == "low" and side == "yes":
            # YES on low bracket: we need overnight low to land in [low, high]
            # Dead if: temp already dropped well below the bracket
            if current_temp < low - 3 and hour_et >= 4:
                return True, f"Current {current_temp}°F already below bracket [{low}-{high}]°F — low already passed"
            # Dead if: temp is still way above the bracket and it's past midnight
            # (not enough cooling time left to reach bracket)
            if current_temp > high + 4 and hour_et >= 2:
                return True, f"Current {current_temp}°F, {current_temp - high:.0f}°F above bracket [{low}-{high}]°F at {hour_et}:00 ET — won't cool enough"

        elif mtype == "low" and side == "no":
            # NO on low bracket: need low NOT in [low, high]
            # Dead if: temp is in the bracket during coldest hours (4-7am ET)
            if low <= current_temp <= high and 4 <= hour_et <= 7:
                return True, f"Current {current_temp}°F is IN bracket [{low}-{high}]°F during coldest hours"
            # Dead if: temp is in the bracket and dropping toward it after midnight
            if low <= current_temp <= high and hour_et >= 2:
                return True, f"Current {current_temp}°F is IN bracket [{low}-{high}]°F overnight — likely settling here"

    elif bracket_info["kind"] == "threshold":
        threshold = bracket_info["threshold"]
        mtype = bracket_info["type"]
        
        if mtype == "high" and side == "yes":
            # YES on >=threshold: dead if late in day and temp never got close
            if current_temp < threshold - 5 and hour_et >= 15:
                return True, f"Current {current_temp}°F, never reaching {threshold}°F threshold at {hour_et}:00 ET"

        elif mtype == "low" and side == "yes":
            # YES on low >=threshold: need low to stay ABOVE threshold
            # Dead if: temp already dropped below threshold
            if current_temp < threshold - 1 and hour_et >= 3:
                return True, f"Current {current_temp}°F already below {threshold}°F threshold — low already breached"

        elif mtype == "low" and side == "no":
            # NO on low threshold: we bet the low WILL drop below threshold
            # Dead if: temp is still well above threshold and it's early morning (low is locked)
            if current_temp > threshold + 3 and 5 <= hour_et <= 8:
                return True, f"Current {current_temp}°F still {current_temp - threshold:.0f}°F above {threshold}°F threshold at {hour_et}:00 ET — low won't reach it"
            # Dead if: temp is within the threshold range during coldest hours
            if current_temp > threshold and current_temp < threshold + 10 and 4 <= hour_et <= 7:
                return True, f"Current {current_temp}°F in threshold range (>{threshold}°F) during coldest hours — NO position dead"
                
        elif mtype == "high" and side == "no":
            # NO on >=threshold: dead if temp already exceeded threshold
            if current_temp > threshold + 2 and hour_et >= 12:
                return True, f"Current {current_temp}°F already exceeded {threshold}°F threshold"

    return False, ""


class PriceMonitor:
    """Watches open positions and executes take-profit orders + dead position exits."""

    PROFIT_TRIGGER_PCT = 10         # sell winners when unrealized >= 10% of account
    # PROFIT_TRIGGER_PCT defined above (10%)

    def __init__(self):
        self.client = KalshiClient()
        self.running = True
        self.profit_rule_triggered = False
        self.stats = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "checks": 0,
            "take_profits_triggered": 0,
            "take_profits_filled": 0,
            "dead_exits_triggered": 0,
            "dead_exits_filled": 0,
            "profit_rule_triggered": 0,
            "errors": 0,
            "last_check": None,
            "positions_tracked": 0,
        }
        # Track position cost basis (ticker -> avg_cost_cents)
        self.cost_basis = {}

        # Handle graceful shutdown
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        log.info("Shutdown signal received (sig=%d)", signum)
        self.running = False

    def _write_pid(self):
        PID_FILE.write_text(str(sys.modules['os'].getpid()))
        log.info("PID file written: %s", PID_FILE)

    def _remove_pid(self):
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def get_open_positions(self) -> list[dict]:
        """Fetch positions with qty > 0."""
        try:
            resp = self.client.get_positions()
            positions = resp.get("market_positions", [])
            return [p for p in positions if p.get("position", 0) > 0]
        except Exception as e:
            log.error("Failed to fetch positions: %s", e)
            self.stats["errors"] += 1
            return []

    def get_current_price(self, ticker: str) -> dict | None:
        """Get current market price for a ticker."""
        try:
            time.sleep(RATE_LIMIT_DELAY)
            resp = self.client.get_market(ticker)
            market = resp.get("market", resp)
            return {
                "yes_bid": market.get("yes_bid", 0),
                "yes_ask": market.get("yes_ask", 0),
                "last_price": market.get("last_price", 0),
                "status": market.get("status", "unknown"),
                "volume": market.get("volume", 0),
            }
        except Exception as e:
            log.error("Failed to get price for %s: %s", ticker, e)
            self.stats["errors"] += 1
            return None

    def check_take_profit(self, position: dict, market_data: dict) -> bool:
        """Check if position meets take-profit criteria and execute if so."""
        ticker = position.get("ticker", "")
        qty = position.get("position", 0)
        exposure = position.get("market_exposure", 0)
        avg_cost = exposure / qty if qty > 0 else 0

        yes_bid = market_data.get("yes_bid", 0)
        status = market_data.get("status", "")

        if status != "active" or yes_bid <= 0 or avg_cost <= 0:
            return False

        gain_pct = ((yes_bid - avg_cost) / avg_cost) * 100
        profit_cents = (yes_bid - avg_cost) * qty

        # Log every price check for positions with any gain
        if gain_pct > 0:
            log.info("📈 %s: cost=%d¢ bid=%d¢ gain=%.0f%% (target: %d%%)",
                     ticker, avg_cost, yes_bid, gain_pct, TAKE_PROFIT_PCT)

        if gain_pct >= TAKE_PROFIT_PCT:
            log.info("🎯 TAKE PROFIT TRIGGERED: %s | %d¢ → %d¢ | +%.0f%% | profit: %d¢ (%d contracts)",
                     ticker, avg_cost, yes_bid, gain_pct, profit_cents, qty)
            self.stats["take_profits_triggered"] += 1

            try:
                result = self.client.create_order(
                    ticker=ticker,
                    action="sell",
                    side="yes",
                    count=qty,
                    order_type="limit",
                    yes_price=yes_bid,
                )
                order = result.get("order", result)
                order_status = order.get("status", "unknown")
                log.info("✅ TAKE PROFIT ORDER PLACED: %s | status=%s | %s",
                         ticker, order_status, json.dumps(order, indent=2))

                if order_status in ("executed", "filled"):
                    self.stats["take_profits_filled"] += 1

                # Log to a separate take-profit log for easy review
                tp_log = LOG_DIR / "take_profits.jsonl"
                with open(tp_log, "a") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ticker": ticker,
                        "qty": qty,
                        "cost_cents": avg_cost,
                        "sell_price_cents": yes_bid,
                        "gain_pct": round(gain_pct, 1),
                        "profit_cents": round(profit_cents, 1),
                        "order_status": order_status,
                    }) + "\n")

                return True

            except Exception as e:
                log.error("❌ TAKE PROFIT ORDER FAILED for %s: %s", ticker, e)
                self.stats["errors"] += 1
                return False

        return False

    def check_dead_position(self, position: dict, market_data: dict) -> bool:
        """Check if position is mathematically dead and exit at market."""
        ticker = position.get("ticker", "")
        qty = position.get("position", 0)
        side = position.get("market_outcome", "yes")  # which side we hold
        
        bracket_info = parse_position_bracket(ticker)
        if not bracket_info:
            return False
        
        # Get current METAR temp for the city
        current_temp = get_metar_temp(bracket_info["station"])
        if current_temp is None:
            return False
        
        dead, reason = is_position_dead(bracket_info, current_temp, side)
        if not dead:
            return False
        
        # Position is dead — exit at whatever we can get
        yes_bid = market_data.get("yes_bid", 0)
        status = market_data.get("status", "")
        
        if status != "active":
            return False
        
        log.warning("💀 DEAD POSITION: %s | %s | Current: %.0f°F", ticker, reason, current_temp)
        self.stats["dead_exits_triggered"] += 1
        
        try:
            # Sell whatever side we hold at market bid
            if side == "yes" and yes_bid > 0:
                result = self.client.create_order(
                    ticker=ticker,
                    action="sell",
                    side="yes",
                    count=qty,
                    order_type="limit",
                    yes_price=yes_bid,
                )
            elif side == "no":
                no_bid = market_data.get("no_bid", 0) or (100 - market_data.get("yes_ask", 100))
                if no_bid > 0:
                    result = self.client.create_order(
                        ticker=ticker,
                        action="sell",
                        side="no",
                        count=qty,
                        order_type="limit",
                        no_price=no_bid,
                    )
                else:
                    log.warning("No bid available for dead position %s", ticker)
                    return False
            else:
                log.warning("No bid available for dead position %s (yes_bid=%d)", ticker, yes_bid)
                return False
            
            order = result.get("order", result)
            order_status = order.get("status", "unknown")
            log.info("💀 DEAD POSITION EXIT: %s | status=%s | recovered what we could", ticker, order_status)
            
            if order_status in ("executed", "filled"):
                self.stats["dead_exits_filled"] += 1
            
            # Log to take_profits.jsonl for review
            tp_log = LOG_DIR / "take_profits.jsonl"
            with open(tp_log, "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "dead_exit",
                    "ticker": ticker,
                    "qty": qty,
                    "side": side,
                    "exit_price": yes_bid if side == "yes" else (100 - market_data.get("yes_ask", 100)),
                    "reason": reason,
                    "current_temp_f": current_temp,
                    "order_status": order_status,
                }) + "\n")
            
            return True
            
        except Exception as e:
            log.error("❌ DEAD POSITION EXIT FAILED for %s: %s", ticker, e)
            self.stats["errors"] += 1
            return False

    def check_80pct_rule(self, positions: list[dict]) -> bool:
        """Check if total portfolio value is up 80%+. If so, liquidate everything.
        
        Portfolio value = cash balance + sum of (position_qty * current_yes_bid) for all positions.
        """
        if self.profit_rule_triggered:
            return False  # already triggered this session

        try:
            time.sleep(RATE_LIMIT_DELAY)
            bal_resp = self.client.get_balance()
            cash = bal_resp.get("balance", 0)  # cents
        except Exception as e:
            log.error("80%% rule: failed to get balance: %s", e)
            return False

        # Estimate total portfolio value using current bids
        position_value = 0
        for pos in positions:
            ticker = pos.get("ticker", "")
            qty = pos.get("position", 0)
            if qty <= 0:
                continue
            try:
                time.sleep(RATE_LIMIT_DELAY)
                mkt = self.client.get_market(ticker).get("market", {})
                yes_bid = mkt.get("yes_bid", 0)
                position_value += yes_bid * qty
            except Exception:
                # If we can't price it, use exposure as fallback
                position_value += pos.get("market_exposure", 0)

        # Calculate unrealized P&L (current value - cost basis)
        total_cost = 0
        for pos in positions:
            qty = pos.get("position", 0)
            if qty <= 0:
                continue
            total_cost += pos.get("market_exposure", 0)

        total_value = cash + position_value
        unrealized_pnl = position_value - total_cost
        trigger_amount = int(total_value * self.PROFIT_TRIGGER_PCT / 100)

        log.info("💰 Portfolio: cash=%d¢ + positions=%d¢ = %d¢ | Unrealized P&L: %+d¢ (trigger: %d¢ = 10%%)",
                 cash, position_value, total_value, unrealized_pnl, trigger_amount)

        if unrealized_pnl >= trigger_amount and trigger_amount > 0:
            log.warning("🚨🚨🚨 10%% PROFIT RULE TRIGGERED! Unrealized: +%d¢ (trigger: %d¢). SELLING WINNERS!",
                        unrealized_pnl, trigger_amount)
            self.stats["profit_rule_triggered"] += 1
            self.profit_rule_triggered = True

            # Liquidate only winning positions
            for pos in positions:
                ticker = pos.get("ticker", "")
                qty = pos.get("position", 0)
                if qty <= 0:
                    continue
                exposure = pos.get("market_exposure", 0)
                avg_cost = exposure / qty if qty > 0 else 0
                try:
                    time.sleep(RATE_LIMIT_DELAY)
                    mkt = self.client.get_market(ticker).get("market", {})
                    yes_bid = mkt.get("yes_bid", 0)
                    if yes_bid > avg_cost:  # only sell winners
                        result = self.client.create_order(
                            ticker=ticker, action="sell", side="yes",
                            count=qty, order_type="limit", yes_price=yes_bid)
                        log.info("🔒 Locked profit: %s x%d @ %d¢ (cost %d¢) → %s",
                                 ticker, qty, yes_bid, avg_cost, result.get("order", {}).get("status", "?"))
                    else:
                        log.info("⏭️ Skip %s — not profitable (bid %d¢ vs cost %d¢)", ticker, yes_bid, avg_cost)
                except Exception as e:
                    log.error("Profit rule: failed to sell %s: %s", ticker, e)

            # Log the event
            tp_log = LOG_DIR / "take_profits.jsonl"
            with open(tp_log, "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "80pct_rule",
                    "total_value_cents": total_value,
                    "cash_cents": cash,
                    "position_value_cents": position_value,
                    "profit_pct": round(profit_pct, 1),
                    "positions_liquidated": len([p for p in positions if p.get("position", 0) > 0]),
                }) + "\n")

            return True
        return False

    def run_check(self) -> int:
        """Run one check cycle. Returns number of open positions."""
        self.stats["checks"] += 1
        self.stats["last_check"] = datetime.now(timezone.utc).isoformat()

        positions = self.get_open_positions()
        self.stats["positions_tracked"] = len(positions)

        if not positions:
            return 0

        log.info("Checking %d open position(s)...", len(positions))

        # Check 80% profit rule first (one balance + position valuation call)
        if self.check_80pct_rule(positions):
            log.info("80%% rule fired — skipping individual position checks this cycle")
            return len(positions)

        for pos in positions:
            ticker = pos.get("ticker", "")
            market_data = self.get_current_price(ticker)
            if market_data:
                # Check take-profit first (higher priority)
                if not self.check_take_profit(pos, market_data):
                    # Then check if position is dead
                    self.check_dead_position(pos, market_data)

        return len(positions)

    def run(self):
        """Main loop — runs until shutdown signal."""
        import os
        self._write_pid()
        log.info("=" * 60)
        log.info("Price Monitor started (PID %d)", os.getpid())
        log.info("Take-profit threshold: %d%%", TAKE_PROFIT_PCT)
        log.info("Poll interval: %ds (active) / %ds (idle)", POLL_INTERVAL, IDLE_INTERVAL)
        log.info("=" * 60)

        try:
            while self.running:
                try:
                    num_positions = self.run_check()
                    interval = POLL_INTERVAL if num_positions > 0 else IDLE_INTERVAL
                except Exception as e:
                    log.error("Check cycle error: %s", e, exc_info=True)
                    self.stats["errors"] += 1
                    interval = POLL_INTERVAL

                # Sleep in small increments so shutdown is responsive
                for _ in range(int(interval)):
                    if not self.running:
                        break
                    time.sleep(1)

        finally:
            self._remove_pid()
            log.info("Price Monitor stopped. Stats: %s", json.dumps(self.stats, indent=2))


def status():
    """Check if monitor is running."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        import os
        try:
            os.kill(pid, 0)
            print(f"Price Monitor is RUNNING (PID {pid})")
            return True
        except ProcessLookupError:
            print(f"Price Monitor is NOT RUNNING (stale PID file, PID {pid})")
            PID_FILE.unlink(missing_ok=True)
            return False
    else:
        print("Price Monitor is NOT RUNNING (no PID file)")
        return False


def stop():
    """Stop the monitor gracefully."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        import os
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to PID {pid}")
            # Wait for it to die
            for _ in range(10):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    print("Monitor stopped.")
                    return True
            print("Monitor didn't stop in 5s — sending SIGKILL")
            os.kill(pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            print("Monitor was not running.")
            PID_FILE.unlink(missing_ok=True)
            return False
    else:
        print("No PID file — monitor not running.")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kalshi Price Monitor")
    parser.add_argument("action", choices=["start", "stop", "status", "once"],
                        help="start=daemon, stop=kill, status=check, once=single check")
    args = parser.parse_args()

    if args.action == "start":
        if status():
            print("Already running. Stop first.")
            sys.exit(1)
        monitor = PriceMonitor()
        monitor.run()
    elif args.action == "stop":
        stop()
    elif args.action == "status":
        status()
    elif args.action == "once":
        monitor = PriceMonitor()
        n = monitor.run_check()
        print(f"Checked {n} positions. Stats: {json.dumps(monitor.stats, indent=2)}")
