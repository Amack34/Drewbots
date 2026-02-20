#!/usr/bin/env python3
"""
Weather Trading Bot — Main Orchestrator
Runs the collector, generates signals, and executes trades within risk limits.
Can run as a long-running process or single-shot for cron.
"""

import json
import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

from weather_collector import collect_all, CONFIG
from signal_generator import generate_signals, Signal
from kalshi_trader import KalshiClient
from paper_trade import (paper_trade, get_paper_summary, get_todays_trade_count, init_paper_db,
                         is_duplicate_trade, get_paper_positions, get_paper_portfolio_value,
                         close_paper_position, get_paper_total_account_value)
from lockin_signals import generate_lockin_signals
from metar_tracker import update_all_stations

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("bot")


class WeatherBot:
    """Main bot orchestrator."""

    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.client = KalshiClient()
        self.risk = CONFIG["risk"]
        self._80pct_triggered = False
        init_paper_db()

    def is_trading_window(self) -> tuple[bool, str]:
        """Check if we're in a valid trading window."""
        now_utc = datetime.now(timezone.utc)
        hour_et = (now_utc.hour - 5) % 24  # rough ET

        windows = CONFIG["trading_windows"]
        high_start = windows["high_temp"]["start_hour_et"]
        high_end = windows["high_temp"]["end_hour_et"]
        low_start = windows["low_temp"]["start_hour_et"]
        low_end = windows["low_temp"]["end_hour_et"]

        if high_start <= hour_et <= high_end:
            return True, "high"
        if low_start <= hour_et or hour_et <= low_end:
            return True, "low"

        return False, "none"

    def _get_live_trade_count(self) -> int:
        """Count live trades placed today (ET) by checking Kalshi orders."""
        try:
            from datetime import timedelta
            now_et = datetime.now(timezone.utc) - timedelta(hours=5)
            today_str = now_et.strftime("%Y-%m-%d")
            orders = self.client.get_orders(status="resting")
            filled = self.client.get_orders(status="executed")
            count = 0
            for order_set in [orders.get("orders", []), filled.get("orders", [])]:
                for o in order_set:
                    created_utc = o.get("created_time", "")[:19]
                    if not created_utc:
                        continue
                    # Convert UTC to ET for proper day boundary
                    dt = datetime.fromisoformat(created_utc)
                    dt_et = dt - timedelta(hours=5)
                    if dt_et.strftime("%Y-%m-%d") == today_str:
                        count += 1
            return count
        except Exception as e:
            log.warning("Failed to get live trade count: %s — falling back to 0", e)
            return 0

    def _get_daily_deployed(self) -> int:
        """Get capital deployed TODAY in cents (live mode). Only counts orders placed today, not prior days' unsettled positions."""
        try:
            from datetime import timedelta
            now_et = datetime.now(timezone.utc) - timedelta(hours=5)
            today_str = now_et.strftime("%Y-%m-%d")
            
            # Check filled orders from today (ET)
            orders = self.client.get_orders(status="executed")
            today_cost = 0
            for o in orders.get("orders", []):
                created_utc = o.get("created_time", "")[:19]
                if not created_utc:
                    continue
                dt = datetime.fromisoformat(created_utc)
                dt_et = dt - timedelta(hours=5)
                if dt_et.strftime("%Y-%m-%d") == today_str:
                    # Each filled order's cost — use fill_count (not count, which is remaining unfilled)
                    yes_price = o.get("yes_price", 0)
                    no_price = o.get("no_price", 0)
                    fill_count = o.get("fill_count", 0) or o.get("initial_count", 0) or 0
                    price = yes_price or no_price or 0
                    today_cost += price * fill_count
            return today_cost
        except Exception as e:
            log.warning("Failed to get daily deployed: %s — using 0", e)
            return 0

    def check_risk_limits(self, signal: Signal) -> bool:
        """Verify trade passes risk checks."""
        # Dynamic capital cap: 40% of total account value based on ACTUAL position exposure
        # Not just today's orders — unsettled positions from prior days count too
        if self.paper_mode:
            try:
                total_account = get_paper_total_account_value(self.client)
                paper_positions = get_paper_positions()
                total_exposure = sum(abs(p.get("market_exposure", 0)) for p in paper_positions if p.get("position", 0) != 0)
                max_exposure_cents = int(total_account * 0.40)
                if total_exposure >= max_exposure_cents:
                    log.info("Risk: Paper capital cap hit — exposure $%.2f >= 40%% cap $%.2f (of $%.2f account)",
                             total_exposure / 100, max_exposure_cents / 100, total_account / 100)
                    return False
            except Exception:
                pass  # fallback: no cap enforcement in paper mode
        else:
            try:
                bal = self.client.get_balance()
                balance = bal.get("balance", 0)
                positions = self.client.get_positions().get("market_positions", [])
                total_exposure = sum(abs(p.get("market_exposure", 0)) for p in positions if p.get("position", 0) != 0)
                total_account = balance + total_exposure
                max_exposure_cents = int(total_account * 0.40)
            except Exception:
                max_exposure_cents = 1000  # fallback $10
                total_exposure = 0
            
            if total_exposure >= max_exposure_cents:
                log.info("Risk: Capital cap hit — exposure $%.2f >= 40%% cap $%.2f (of $%.2f account)",
                         total_exposure / 100, max_exposure_cents / 100, total_account / 100)
                return False

        # Max trades per day — scales with account size
        # Config values are calibrated for $80 base. Scale proportionally.
        today_count = self._get_live_trade_count() if not self.paper_mode else get_todays_trade_count()
        scale_factor = self._get_account_scale_factor()
        base_max = max(8, int(self.risk["max_trades_per_day"] * scale_factor))
        bonus_threshold = max(6, int(self.risk.get("bonus_trades_after_wins", 18) * scale_factor))
        bonus_count = self.risk.get("bonus_trade_count", 2)

        # Check today's wins for bonus trades
        today_wins = self._get_todays_wins()
        effective_max = base_max
        is_bonus_slot = False

        # 80% profit rule: unlocks 10 additional trades
        if self._80pct_triggered:
            effective_max = base_max + 10
            log.info("80%% rule active: %d/%d trades allowed", today_count, effective_max)

        if today_wins >= bonus_threshold:
            effective_max = max(effective_max, base_max + bonus_count)
            if today_count >= base_max:
                is_bonus_slot = True
                # Bonus trades must be longshot take-profit plays only
                if signal.side != "yes" or signal.suggested_price > 10:
                    log.info("Risk: Bonus trade slot — only longshot YES plays allowed (got %s @ %d¢)",
                             signal.side, signal.suggested_price)
                    return False
                log.info("🎯 BONUS TRADE: %d wins today, using bonus slot %d/%d (longshot take-profit only)",
                         today_wins, today_count - base_max + 1, bonus_count)

        # "Looking good" rule: positions in profit = +3 bonus trades (scales with account)
        if today_count >= effective_max:
            looking_good = self._count_looking_good()
            looking_good_threshold = max(7, int(17 * scale_factor))
            if looking_good >= looking_good_threshold:
                looking_good_max = effective_max + 3
                if today_count < looking_good_max:
                    log.info("🔥 MOMENTUM BONUS: %d positions in profit — unlocking 3 extra trades (%d/%d)",
                             looking_good, today_count + 1, looking_good_max)
                    effective_max = looking_good_max

        if today_count >= effective_max:
            log.info("Risk: Max daily trades reached (%d/%d, wins=%d)",
                     today_count, effective_max, today_wins)
            return False

        # Min edge — lower threshold for METAR lock-in confirmed brackets (near-guaranteed)
        is_lockin = getattr(signal, 'signal_source', '') == 'metar_lockin'
        min_edge = 1.0 if is_lockin else self.risk["min_edge_pct"]
        if signal.edge_pct < min_edge:
            log.info("Risk: Edge too low (%.1f%% < %.1f%%)",
                     signal.edge_pct, min_edge)
            return False

        return True

    def _get_account_scale_factor(self) -> float:
        """Scale thresholds proportionally with account size.
        Base calibration: $80 = 1.0x. Account grows → thresholds grow.
        Account shrinks → thresholds shrink. Floors prevent going below minimums."""
        BASE_BALANCE_CENTS = 8000  # $80 calibration point
        if self.paper_mode:
            from paper_trade import get_paper_balance
            balance = get_paper_balance()
        else:
            try:
                bal = self.client.get_balance()
                balance = bal.get("balance", 0)
                # Add approximate position value for total account size
                positions = self.client.get_positions().get("market_positions", [])
                for p in positions:
                    balance += abs(p.get("market_exposure", 0))
            except Exception:
                return 1.0  # fallback to no scaling
        factor = balance / BASE_BALANCE_CENTS
        log.debug("Account scale factor: %.2f (balance %d¢ / base %d¢)", factor, balance, BASE_BALANCE_CENTS)
        return max(0.5, factor)  # floor at 0.5x to prevent over-shrinking

    def _get_todays_wins(self) -> int:
        """Count today's winning trades (resolved with positive P&L)."""
        import sqlite3
        from datetime import date
        try:
            conn = sqlite3.connect(CONFIG["db_path"])
            cur = conn.cursor()
            today = date.today().isoformat()
            cur.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE settled=1 AND pnl_cents>0 AND date(created_at)=?",
                (today,))
            wins = cur.fetchone()[0]
            conn.close()
            return wins
        except Exception:
            return 0

    def _count_looking_good(self) -> int:
        """Count positions currently in profit (unrealized winners). 
        Used for the '7 looking good = +3 bonus trades' rule."""
        try:
            if self.paper_mode:
                _, _, enriched = get_paper_portfolio_value(self.client)
                winners = 0
                for p in enriched:
                    if p["current_value"] > p["market_exposure"]:
                        winners += 1
                return winners

            positions = self.client.get_positions().get("market_positions", [])
            winners = 0
            for pos in positions:
                qty = pos.get("position", 0)
                exposure = pos.get("market_exposure", 0)
                if qty == 0:
                    continue
                import time
                time.sleep(0.15)
                market = self.client.get_market(pos.get("ticker", "")).get("market", {})
                yes_bid = market.get("yes_bid", 0) or 0
                
                if qty < 0:  # NO position
                    current_val = abs(qty) * (100 - yes_bid)
                else:  # YES position
                    current_val = qty * yes_bid
                
                if current_val > exposure:
                    winners += 1
            return winners
        except Exception as e:
            log.warning("Failed to count looking-good positions: %s", e)
            return 0

    def calculate_position_size(self, signal: Signal) -> int:
        """Determine number of contracts based on signal type and risk limits.
        
        For NO trades (selling longshots): cost = (100 - yes_price)¢ per contract
        For YES trades: cost = yes_price¢ per contract
        """
        price = signal.suggested_price
        if price <= 0:
            return 0

        # For NO trades, our cost is the NO price (100 - yes_price)
        # For YES trades, our cost is the YES price
        cost_per_contract = price  # this is already the correct price for our side

        # Determine tier and limits
        min_risk_cents = 0
        max_risk_cents = 100
        max_contracts = 10

        # Check if this is a stack (adding to existing position)
        is_stacking = False
        if not self.paper_mode:
            is_stacking = self._is_live_duplicate(signal.market_ticker, signal.side)
        else:
            is_stacking = is_duplicate_trade(signal.market_ticker, signal.side)

        # Stacking multiplier
        is_lockin = getattr(signal, 'signal_source', '') == 'metar_lockin'
        is_tomorrow = getattr(signal, 'is_tomorrow', False)
        stack_multiplier = 1.0

        if is_stacking and is_lockin:
            # Lock-in signals: always allowed to stack
            if signal.edge_pct >= 80:
                stack_multiplier = 5.0
            elif signal.edge_pct >= 40:
                stack_multiplier = 3.0
            log.info("🔒 LOCK-IN STACK SIZING: %.1fx multiplier (edge %.0f%%)", stack_multiplier, signal.edge_pct)
        elif is_tomorrow and signal.edge_pct >= 40 and signal.side == "no":
            # Tomorrow's model signals with strong edge: allow sizing up
            # Not full stacking, but 2x sizing (we have 24h+ of forecast updates as safety net)
            stack_multiplier = 2.0
            log.info("📅 TOMORROW STRONG SIGNAL: 2x sizing (edge %.0f%%, margin %.1f°F)",
                     signal.edge_pct, getattr(signal, 'margin', 0))

        if signal.side == "no":
            # Selling overpriced longshots — 3 contracts target (bankroll-gated)
            actual_risk_per_contract = signal.market_yes_price
            log.info("SELL LONGSHOT: %s YES@%d¢ → buying NO@%d¢, risk %d¢/contract",
                     signal.market_ticker, signal.market_yes_price,
                     cost_per_contract, actual_risk_per_contract)
            min_risk_cents = 175
            max_risk_cents = int(225 * stack_multiplier)
            contracts_by_risk = max_risk_cents // cost_per_contract
        elif price >= 50:
            # High-conviction plays — min 3 contracts, max $1.75 per trade
            log.info("HIGH CONVICTION: %s YES@%d¢", signal.market_ticker, price)
            min_risk_cents = 0  # use min_contracts instead
            max_risk_cents = int(175 * stack_multiplier)
            contracts_by_risk = max(3, max_risk_cents // price)
        else:
            # Standard bracket plays — min $1.00, max $1.25
            min_price = self.risk.get("min_entry_price", 2)
            if price < min_price:
                log.info("Skipping %s: price %d¢ below min %d¢", signal.market_ticker, price, min_price)
                return 0
            min_risk_cents = 100
            max_risk_cents = int(125 * stack_multiplier)
            contracts_by_risk = max_risk_cents // price

        contracts = min(contracts_by_risk, max_contracts)

        # Enforce minimum deployment (round up, allow slight cap overshoot)
        if min_risk_cents > 0 and price > 0:
            min_contracts = max(1, -(-min_risk_cents // price))  # ceiling division
            contracts = max(contracts, min_contracts)
            log.info("Sizing: %d contracts × %d¢ = %d¢ (min=%d¢ max=%d¢)",
                     contracts, price, contracts * price, min_risk_cents, max_risk_cents)

        # Also check bankroll limit
        if self.paper_mode:
            from paper_trade import get_paper_balance
            balance = get_paper_balance()
        else:
            try:
                bal = self.client.get_balance()
                balance = bal.get("balance", 0)
            except Exception as e:
                log.error("Failed to get balance: %s", e)
                return 0

        max_by_bankroll = int(balance * self.risk["max_position_pct"] / 100) // price
        contracts = min(contracts, max_by_bankroll)

        # Anti-pattern detection: randomly adjust contract count by ±1
        # Makes our order flow less fingerprint-able by other bots
        import random
        if contracts >= 3:
            contracts += random.choice([-1, 0, 0, 1])  # bias toward no change
            contracts = max(1, contracts)

        return max(0, contracts)

    def check_80pct_rule(self) -> bool:
        """Check if unrealized profit on open positions >= 10% of total account value.
        If triggered, sell all winning positions and unlock 10 bonus trades.
        The 10% threshold scales with account — as account grows, trigger grows too."""
        PROFIT_TRIGGER_PCT = 10  # 10% of total account value

        if self.paper_mode:
            try:
                cash, total_exposure, enriched = get_paper_portfolio_value(self.client)
                total_cost = sum(p["market_exposure"] for p in enriched)
                total_value = sum(p["current_value"] for p in enriched)
                unrealized_pnl = total_value - total_cost
                account_value = cash + total_value
                trigger_amount = int(account_value * PROFIT_TRIGGER_PCT / 100)

                log.info("Paper profit rule check: unrealized P&L=%d¢ vs trigger=%d¢ (10%% of $%.2f)",
                         unrealized_pnl, trigger_amount, account_value / 100)

                if unrealized_pnl >= trigger_amount and trigger_amount > 0:
                    log.info("🚨 PAPER 10%% PROFIT RULE TRIGGERED! Unrealized: +%d¢ (trigger: %d¢). Selling all winners!",
                             unrealized_pnl, trigger_amount)
                    # Build positions list matching Kalshi format for _liquidate_winning_positions
                    positions = [{"ticker": p["ticker"], "position": p["position"],
                                  "market_exposure": p["market_exposure"]} for p in enriched]
                    self._liquidate_winning_positions(positions)
                    self._80pct_triggered = True
                    return True
            except Exception as e:
                log.error("Paper profit rule check failed: %s", e)
            return False

        try:
            bal = self.client.get_balance()
            cash = bal.get("balance", 0)

            positions_resp = self.client.get_positions()
            positions = positions_resp.get("market_positions", [])

            total_cost = 0
            total_value = 0
            for pos in positions:
                ticker = pos.get("ticker", "")
                qty = pos.get("position", 0)
                exposure = pos.get("market_exposure", 0)
                if qty == 0 and exposure == 0:
                    continue  # fully settled, skip
                try:
                    import time
                    time.sleep(0.15)
                    mkt = self.client.get_market(ticker).get("market", {})
                    if qty < 0:
                        # NO position: we sold YES, profit = exposure - (no_ask * abs(qty))
                        # exposure = what we received, current cost to close = no_ask * qty
                        no_ask = mkt.get("no_ask", 0)
                        abs_qty = abs(qty)
                        total_cost += no_ask * abs_qty  # cost to close
                        total_value += exposure  # what we locked in
                    else:
                        # YES position
                        yes_bid = mkt.get("yes_bid", 0)
                        total_cost += exposure
                        total_value += yes_bid * qty
                except Exception:
                    pass  # skip if can't price

            unrealized_pnl = total_value - total_cost
            account_value = cash + total_value
            trigger_amount = int(account_value * PROFIT_TRIGGER_PCT / 100)

            log.info("Profit rule check: unrealized P&L=%d¢ vs trigger=%d¢ (10%% of $%.2f)",
                     unrealized_pnl, trigger_amount, account_value / 100)

            if unrealized_pnl >= trigger_amount and trigger_amount > 0:
                log.info("🚨 10%% PROFIT RULE TRIGGERED! Unrealized: +%d¢ (trigger: %d¢). Selling all winners!",
                         unrealized_pnl, trigger_amount)
                self._liquidate_winning_positions(positions)
                self._80pct_triggered = True  # unlocks 10 bonus trades
                return True
        except Exception as e:
            log.error("Profit rule check failed: %s", e)

        return False

    def _liquidate_winning_positions(self, positions):
        """Sell only positions that are currently profitable."""
        if self.paper_mode:
            for pos in positions:
                ticker = pos.get("ticker", "")
                qty = pos.get("position", 0)
                exposure = pos.get("market_exposure", 0)
                if qty == 0:
                    continue
                try:
                    import time
                    time.sleep(0.15)
                    mkt = self.client.get_market(ticker).get("market", {})
                    if qty < 0:  # NO position
                        abs_qty = abs(qty)
                        received_per = exposure / abs_qty if abs_qty > 0 else 0
                        no_ask = mkt.get("no_ask", 0)
                        if no_ask < received_per and no_ask > 0:
                            close_paper_position(ticker, "no", abs_qty, mkt.get("yes_bid", 0) or 0)
                            log.info("🔒 Paper locked NO profit: %s sold %d NO @ %d¢ (received %d¢)",
                                     ticker, abs_qty, no_ask, received_per)
                    elif qty > 0:  # YES position
                        yes_bid = mkt.get("yes_bid", 0)
                        avg_cost = exposure / qty if qty > 0 else 0
                        if yes_bid > avg_cost:
                            close_paper_position(ticker, "yes", qty, yes_bid)
                            log.info("🔒 Paper locked YES profit: %s sold %d @ %d¢ (cost %d¢)",
                                     ticker, qty, yes_bid, avg_cost)
                except Exception as e:
                    log.error("Paper failed to close %s: %s", ticker, e)
            return

        for pos in positions:
            ticker = pos.get("ticker", "")
            qty = pos.get("position", 0)
            exposure = pos.get("market_exposure", 0)
            if qty == 0 and exposure == 0:
                continue
            try:
                import time
                time.sleep(0.15)
                mkt = self.client.get_market(ticker).get("market", {})
                if qty < 0:
                    # NO position: profitable if no_ask < what we received per contract
                    abs_qty = abs(qty)
                    received_per = exposure / abs_qty if abs_qty > 0 else 0
                    no_ask = mkt.get("no_ask", 0)
                    if no_ask < received_per and no_ask > 0:
                        # Sell NO to close (action=sell reduces position)
                        result = self.client.create_order(
                            ticker=ticker, action="sell", side="no",
                            count=abs_qty, order_type="limit", no_price=no_ask)
                        log.info("🔒 Locked NO profit: %s sold %d NO @ %d¢ (received %d¢)",
                                 ticker, abs_qty, no_ask, received_per)
                    else:
                        log.info("⏭️ Skipping %s — NO not profitable (close@%d¢ vs received@%d¢)",
                                 ticker, no_ask, received_per)
                elif qty > 0:
                    # YES position
                    yes_bid = mkt.get("yes_bid", 0)
                    avg_cost = exposure / qty if qty > 0 else 0
                    if yes_bid > avg_cost:
                        result = self.client.create_order(
                            ticker=ticker, action="sell", side="yes",
                            count=qty, order_type="limit", yes_price=yes_bid)
                        log.info("🔒 Locked YES profit: %s sold %d @ %d¢ (cost %d¢)",
                                 ticker, qty, yes_bid, avg_cost)
                    else:
                        log.info("⏭️ Skipping %s — YES not profitable (bid %d¢ vs cost %d¢)",
                                 ticker, yes_bid, avg_cost)
            except Exception as e:
                log.error("Failed to close %s: %s", ticker, e)

    def _liquidate_all_positions(self):
        """Sell all open positions at market."""
        if self.paper_mode:
            positions = get_paper_positions()
            for pos in positions:
                ticker = pos.get("ticker", "")
                qty = pos.get("position", 0)
                if qty == 0:
                    continue
                import time
                time.sleep(0.15)
                try:
                    market = self.client.get_market(ticker).get("market", {})
                    if qty < 0:  # NO position
                        close_paper_position(ticker, "no", abs(qty), market.get("yes_bid", 0) or 0)
                        log.info("Paper LIQUIDATE NO: %s x%d", ticker, abs(qty))
                    else:  # YES position
                        yes_bid = market.get("yes_bid", 0)
                        if yes_bid > 0:
                            close_paper_position(ticker, "yes", qty, yes_bid)
                            log.info("Paper LIQUIDATE YES: %s x%d @ %d¢", ticker, qty, yes_bid)
                except Exception as e:
                    log.error("Paper liquidate failed for %s: %s", ticker, e)
            return

        try:
            positions_resp = self.client.get_positions()
            positions = positions_resp.get("market_positions", [])
            for pos in positions:
                ticker = pos.get("ticker", "")
                qty = pos.get("position", 0)
                if qty == 0:
                    continue
                import time
                time.sleep(0.15)
                try:
                    market = self.client.get_market(ticker).get("market", {})
                    if qty < 0:  # NO position
                        no_bid = market.get("no_bid", 0)
                        if no_bid > 0:
                            result = self.client.create_order(
                                ticker=ticker, action="sell", side="no",
                                count=abs(qty), order_type="limit", no_price=no_bid)
                            log.info("LIQUIDATE NO: %s x%d @ %d¢ → %s", ticker, abs(qty), no_bid, result)
                    else:  # YES position
                        yes_bid = market.get("yes_bid", 0)
                        if yes_bid > 0:
                            result = self.client.create_order(
                                ticker=ticker, action="sell", side="yes",
                                count=qty, order_type="limit", yes_price=yes_bid)
                            log.info("LIQUIDATE YES: %s x%d @ %d¢ → %s", ticker, qty, yes_bid, result)
                except Exception as e:
                    log.error("Liquidate failed for %s: %s", ticker, e)
        except Exception as e:
            log.error("Failed to get positions for liquidation: %s", e)

    def _sanity_check(self, signal: Signal) -> bool:
        """Sanity check before executing a trade. Catches 'too good to be true' signals.
        Returns True if trade passes, False if it should be blocked."""
        # Flag 1: Edge > 90% on a liquid market — likely a data error
        if signal.edge_pct > 90 and signal.market_yes_price >= 20:
            log.warning("⚠️ SANITY CHECK: %s has %.0f%% edge but YES@%d¢ — suspiciously high edge on liquid market. "
                       "Verify estimate is correct for the right date.",
                       signal.market_ticker, signal.edge_pct, signal.market_yes_price)
            # BLOCK trades with >90% edge on liquid markets unless it's a lock-in signal
            is_lockin = getattr(signal, 'signal_source', '') == 'metar_lockin'
            if not is_lockin:
                log.warning("🚫 BLOCKED: >90%% edge on model signal — likely data error. Only lock-ins allowed at this edge.")
                return False
        
        # Flag 2: Large position (>$5 cost) — extra scrutiny
        cost_estimate = signal.suggested_price * 3  # rough 3-contract estimate
        if cost_estimate > 500:
            log.info("📋 SANITY: Large position %s ~$%.2f — double-check inputs", 
                    signal.market_ticker, cost_estimate / 100)
        
        # Flag 3: Cross-validate forecast vs current temp — catch wrong-date bugs
        # If estimate differs from current temp by >20°F, something is likely wrong
        if signal.current_temp_f and signal.forecast_temp_f:
            temp_diff = abs(signal.forecast_temp_f - signal.current_temp_f)
            if temp_diff > 20:
                log.warning("🚫 SANITY BLOCK: %s forecast %.0f°F vs current %.0f°F — %.0f°F difference is suspicious. "
                           "Possible wrong-date data.",
                           signal.market_ticker, signal.forecast_temp_f, signal.current_temp_f, temp_diff)
                return False
        
        # Flag 4: Cross-validate primary station vs surrounding stations
        # If primary differs from surrounding by >8°F, data may be stale or wrong
        if signal.current_temp_f and signal.surrounding_avg_f:
            station_diff = abs(signal.current_temp_f - signal.surrounding_avg_f)
            if station_diff > 8:
                log.warning("⚠️ SANITY: %s primary station %.0f°F vs surrounding avg %.0f°F — %.0f°F divergence. "
                           "Primary station data may be stale.",
                           signal.market_ticker, signal.current_temp_f, signal.surrounding_avg_f, station_diff)
                # Warning only, don't block — surrounding stations can legitimately differ
        
        # Flag 5: Bracket-edge policy — block today's trades where running temp is within 2°F of bracket
        # Without OMO data, we can't tell if the real temp crossed the bracket due to rounding
        is_lockin = getattr(signal, 'signal_source', '') == 'metar_lockin'
        if not is_lockin and not getattr(signal, 'is_tomorrow', False):
            try:
                import json as _json
                with open(os.path.join(os.path.dirname(__file__), 'temp_state.json'), 'r') as _f:
                    _ts = _json.load(_f)
                _city_state = _ts.get('cities', {}).get(signal.city, {})
                _running_h = _city_state.get('high')
                _running_l = _city_state.get('low')
                
                # Parse bracket from the signal reason (extract bracket bounds)
                margin = getattr(signal, 'margin', None)
                if margin is not None and margin < 2.0:
                    log.warning("🚫 BRACKET-EDGE BLOCK: %s margin only %.1f°F — need OMO data to trade this close to the edge. "
                               "Without 1-minute observations, rounding ambiguity makes this too risky.",
                               signal.market_ticker, margin)
                    return False
            except Exception:
                pass  # temp_state.json not available, skip check
        
        return True

    def _is_live_duplicate(self, ticker: str, side: str) -> bool:
        """Check if we already have a position on this market in live mode."""
        try:
            positions = self.client.get_positions().get("market_positions", [])
            for p in positions:
                if p.get("ticker") == ticker and p.get("position", 0) != 0:
                    return True
            return False
        except Exception:
            return False

    def _get_existing_position_size(self, ticker: str) -> int:
        """Get the current number of contracts we hold on a ticker."""
        try:
            positions = self.client.get_positions().get("market_positions", [])
            for p in positions:
                if p.get("ticker") == ticker:
                    return abs(p.get("position", 0))
            return 0
        except Exception:
            return 0

    def execute_signal(self, signal: Signal) -> dict | None:
        """Execute a single trading signal."""
        # GLOBAL KILL SWITCH — blocks ALL order creation
        if self.config.get("kill_switch", False):
            log.warning("🛑 KILL SWITCH ON — order blocked: %s", signal.market_ticker)
            return None

        # MAX POSITION CAP PER TICKER
        max_per_ticker = self.risk.get("max_contracts_per_ticker", 50)
        try:
            positions = self.client.get_positions().get("market_positions", [])
            for pos in positions:
                if pos.get("ticker") == signal.market_ticker:
                    current_qty = abs(pos.get("position", 0))
                    if current_qty >= max_per_ticker:
                        log.warning("🛑 MAX POSITION CAP: %s already has %d contracts (cap=%d)",
                                    signal.market_ticker, current_qty, max_per_ticker)
                        return None
        except Exception as e:
            log.error("Position cap check failed: %s — blocking trade for safety", e)
            return None

        # HARD BLOCK: No YES buys — EXCEPT METAR lock-in confirmed brackets (guaranteed money)
        is_lockin = getattr(signal, 'signal_source', '') == 'metar_lockin'
        if signal.side == "yes" and not is_lockin:
            log.warning("🚫 BLOCKED YES BUY: %s — NO sells only (non-lockin)", signal.market_ticker)
            return None
        if signal.side == "yes" and is_lockin:
            log.info("✅ YES BUY ALLOWED: %s — METAR lock-in confirmed bracket", signal.market_ticker)

        # Sanity check — catches too-good-to-be-true signals
        if not self._sanity_check(signal):
            log.warning("🚫 Trade blocked by sanity check: %s", signal.market_ticker)
            return None
        
        # Stacking only allowed for METAR lock-in signals (sure things)
        # Model-based signals always dedup — no concentration risk on predictions
        is_lockin = getattr(signal, 'signal_source', '') == 'metar_lockin'
        
        if self.paper_mode:
            if is_duplicate_trade(signal.market_ticker, signal.side):
                if is_lockin:
                    log.info("🔒 LOCK-IN STACK: %s %s (edge %.0f%%) — METAR confirmed, adding contracts",
                             signal.market_ticker, signal.side, signal.edge_pct)
                else:
                    log.info("Skipping %s (DEDUP): already traded %s today (model signal, no stacking)", signal.market_ticker, signal.side)
                    return None
        else:
            if self._is_live_duplicate(signal.market_ticker, signal.side):
                if is_lockin:
                    # Check existing position size — cap at 10 contracts per ticker
                    existing = self._get_existing_position_size(signal.market_ticker)
                    if existing >= 25:
                        log.info("Skipping %s (MAX STACK): already %d contracts, cap is 25", signal.market_ticker, existing)
                        return None
                    log.info("🔒 LOCK-IN STACK: %s %s (edge %.0f%%, existing %d) — METAR confirmed, adding contracts",
                             signal.market_ticker, signal.side, signal.edge_pct, existing)
                else:
                    log.info("Skipping %s (DEDUP): already have live position (model signal, no stacking)", signal.market_ticker)
                    return None

        if not self.check_risk_limits(signal):
            return None

        contracts = self.calculate_position_size(signal)
        if contracts <= 0:
            log.info("Skipping %s: position size = 0", signal.market_ticker)
            return None

        if self.paper_mode:
            result = paper_trade(signal, contracts)
            return result
        else:
            # LIVE TRADING
            try:
                result = self.client.create_order(
                    ticker=signal.market_ticker,
                    action=signal.action,
                    side=signal.side,
                    count=contracts,
                    order_type="limit",
                    yes_price=signal.suggested_price if signal.side == "yes" else None,
                    no_price=signal.suggested_price if signal.side == "no" else None,
                )
                log.info("LIVE ORDER PLACED: %s", json.dumps(result, indent=2))
                self._journal_trade(signal, contracts, result)
                return result
            except Exception as e:
                log.error("Failed to place order: %s", e)
                return None

    def _journal_trade(self, signal, contracts, order_result):
        """Log a live trade to the trade_journal table."""
        import sqlite3
        try:
            conn = sqlite3.connect(CONFIG["db_path"])
            cur = conn.cursor()
            
            # Add signal_source column if it doesn't exist
            try:
                cur.execute("ALTER TABLE trade_journal ADD COLUMN signal_source TEXT DEFAULT 'model'")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            order_id = order_result.get("order", {}).get("order_id", "") if isinstance(order_result, dict) else ""
            signal_source = getattr(signal, 'signal_source', 'model')
            
            # Parse bracket from signal
            floor_strike = None
            cap_strike = None
            try:
                from signal_generator import parse_bracket_from_ticker
                bracket = parse_bracket_from_ticker(signal.market_ticker)
                if bracket:
                    floor_strike, cap_strike = bracket
            except Exception:
                pass

            cur.execute('''INSERT OR IGNORE INTO trade_journal 
                (order_id, ticker, event_ticker, city, market_type, side, contracts,
                 entry_price_cents, estimated_temp_f, forecast_temp_f, primary_temp_f,
                 surrounding_avg_f, confidence, edge_pct, floor_strike, cap_strike,
                 our_probability, market_probability, signal_source, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))''',
                (order_id, signal.market_ticker, signal.event_ticker, signal.city,
                 signal.market_type, signal.side, contracts, signal.suggested_price,
                 signal.forecast_temp_f, signal.forecast_temp_f, signal.current_temp_f,
                 signal.surrounding_avg_f, signal.confidence, signal.edge_pct,
                 floor_strike, cap_strike,
                 1.0 - (signal.market_yes_price / 100) if signal.side == "no" else signal.market_yes_price / 100,
                 signal.market_yes_price / 100, signal_source))
            conn.commit()
            conn.close()
            log.info("📓 Trade journaled: %s %s x%d (%s)", signal.market_ticker, signal.side, contracts, signal_source)
        except Exception as e:
            log.error("Failed to journal trade: %s", e)

    def sync_settlements(self):
        """Sync trade_journal with Kalshi — mark settled trades, calculate P&L."""
        import sqlite3
        try:
            conn = sqlite3.connect(CONFIG["db_path"])
            cur = conn.cursor()
            
            # Get all unsettled journal entries
            cur.execute("SELECT id, ticker, side, contracts, entry_price_cents FROM trade_journal WHERE settled=0")
            unsettled = cur.fetchall()
            if not unsettled:
                return
            
            # Get positions from Kalshi (includes realized P&L for closed positions)
            positions = self.client.get_positions().get("market_positions", [])
            pos_map = {p["ticker"]: p for p in positions}
            
            # Check each market's settlement status via API
            settled_count = 0
            for row_id, ticker, side, contracts, entry_price in unsettled:
                try:
                    mkt = self.client.get_market(ticker).get("market", {})
                    status = mkt.get("status", "")
                    result_str = mkt.get("result", "")  # "yes" or "no" or ""
                    
                    if status not in ("settled", "finalized") or not result_str:
                        continue
                    
                    # Calculate P&L
                    # For NO sells: we bought NO at (100 - yes_price). 
                    # If result="no", NO pays $1 → profit = (100 - entry_price) * contracts
                    # If result="yes", NO pays $0 → loss = entry_price * contracts
                    if side == "no":
                        if result_str == "no":
                            # NO wins — bracket didn't hit
                            pnl = (100 - entry_price) * contracts
                            outcome = "win"
                        else:
                            # NO loses — bracket hit
                            pnl = -entry_price * contracts
                            outcome = "loss"
                    else:  # yes side
                        if result_str == "yes":
                            pnl = (100 - entry_price) * contracts
                            outcome = "win"
                        else:
                            pnl = -entry_price * contracts
                            outcome = "loss"
                    
                    # Get actual temp if available
                    actual_temp = None
                    
                    cur.execute('''UPDATE trade_journal 
                        SET settled=1, settlement_result=?, pnl_cents=?, final_pnl_cents=?,
                            actual_temp_f=?, settled_at=datetime('now')
                        WHERE id=?''',
                        (outcome, pnl, pnl, actual_temp, row_id))
                    
                    settled_count += 1
                    log.info("📊 SETTLED: %s %s x%d → %s (%+d¢)", ticker, side, contracts, outcome, pnl)
                    
                except Exception as e:
                    log.error("Failed to check settlement for %s: %s", ticker, e)
                    continue
            
            conn.commit()
            conn.close()
            if settled_count:
                log.info("📊 Settlement sync: %d trades updated", settled_count)
        except Exception as e:
            log.error("Settlement sync failed: %s", e)

    def _log_predictions(self, signals):
        """Log all temperature predictions for later accuracy tracking."""
        import sqlite3
        try:
            conn = sqlite3.connect(CONFIG["db_path"])
            cur = conn.cursor()
            seen = set()
            for s in signals:
                key = f"{s.city}_{s.market_type}"
                if key in seen:
                    continue
                seen.add(key)
                cur.execute('''INSERT INTO prediction_log 
                    (city, market_type, estimated_temp_f, forecast_temp_f, primary_temp_f,
                     surrounding_avg_f, confidence, created_at)
                    VALUES (?,?,?,?,?,?,?,datetime('now'))''',
                    (s.city, s.market_type, s.forecast_temp_f, s.forecast_temp_f,
                     s.current_temp_f, s.surrounding_avg_f, s.confidence))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error("Failed to log predictions: %s", e)

    def get_ab_stats(self) -> dict:
        """Get A/B testing statistics comparing model vs metar_lockin signals."""
        import sqlite3
        try:
            conn = sqlite3.connect(CONFIG["db_path"])
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            
            # Get stats by signal source from trade_journal
            stats = {}
            for source in ['model', 'metar_lockin']:
                cur.execute('''
                    SELECT 
                        COUNT(*) as total_trades,
                        AVG(CASE WHEN final_pnl_cents > 0 THEN 1.0 ELSE 0.0 END) as win_rate,
                        AVG(final_pnl_cents) as avg_pnl_cents,
                        SUM(final_pnl_cents) as total_pnl_cents
                    FROM trade_journal 
                    WHERE signal_source = ? AND final_pnl_cents IS NOT NULL
                ''', (source,))
                
                row = cur.fetchone()
                if row and row['total_trades'] > 0:
                    stats[source] = {
                        'total_trades': row['total_trades'],
                        'win_rate': round(row['win_rate'] * 100, 1) if row['win_rate'] else 0,
                        'avg_pnl_cents': round(row['avg_pnl_cents'], 1) if row['avg_pnl_cents'] else 0,
                        'total_pnl_cents': row['total_pnl_cents'] or 0
                    }
                else:
                    stats[source] = {
                        'total_trades': 0,
                        'win_rate': 0,
                        'avg_pnl_cents': 0,
                        'total_pnl_cents': 0
                    }
            
            conn.close()
            return stats
        except Exception as e:
            log.error("Failed to get A/B stats: %s", e)
            return {'model': {'total_trades': 0}, 'metar_lockin': {'total_trades': 0}}

    def check_take_profits(self):
        """Check open positions for take-profit opportunities (35%+ gain)."""
        take_profit_pct = self.risk.get("take_profit_pct", 35)
        log.info("Checking positions for take-profit (>=%d%% gain)...", take_profit_pct)

        if self.paper_mode:
            positions = get_paper_positions()
        else:
            try:
                positions_resp = self.client.get_positions()
                positions = positions_resp.get("market_positions", [])
            except Exception as e:
                log.error("Failed to get positions for take-profit: %s", e)
                return

        for pos in positions:
            ticker = pos.get("ticker", "")
            qty = pos.get("position", 0)
            exposure = pos.get("market_exposure", 0)
            if qty == 0:
                continue

            try:
                import time
                time.sleep(0.15)
                market = self.client.get_market(ticker).get("market", {})
                yes_bid = market.get("yes_bid", 0) or 0
                no_bid = market.get("no_bid", 0) or 0
                status = market.get("status", "")

                if status != "active":
                    continue

                if qty < 0:  # NO position
                    abs_qty = abs(qty)
                    cost = exposure
                    current_val = abs_qty * (100 - yes_bid)
                    if cost > 0:
                        gain_pct = ((current_val - cost) / cost) * 100
                    else:
                        gain_pct = 0
                    sell_side = "no"
                    sell_price = no_bid
                    sell_qty = abs_qty
                else:  # YES position
                    cost = exposure
                    avg_price = cost / qty if qty > 0 else 0
                    current_val = qty * yes_bid
                    if cost > 0:
                        gain_pct = ((current_val - cost) / cost) * 100
                    else:
                        gain_pct = 0
                    sell_side = "yes"
                    sell_price = yes_bid
                    sell_qty = qty

                if sell_price <= 0:
                    continue

                if gain_pct >= take_profit_pct:
                    profit_cents = current_val - cost
                    log.info("🎯 TAKE PROFIT: %s %s x%d | cost=%d¢ now=%d¢ | gain: %.0f%% | profit: %d¢",
                             ticker, sell_side.upper(), sell_qty, cost, current_val, gain_pct, profit_cents)
                    try:
                        if self.paper_mode:
                            close_paper_position(ticker, sell_side, sell_qty, yes_bid)
                        else:
                            if sell_side == "yes":
                                result = self.client.create_order(
                                    ticker=ticker, action="sell", side="yes",
                                    count=sell_qty, order_type="limit", yes_price=sell_price)
                            else:
                                result = self.client.create_order(
                                    ticker=ticker, action="sell", side="no",
                                    count=sell_qty, order_type="limit", no_price=sell_price)
                            log.info("TAKE PROFIT ORDER: %s", json.dumps(result, indent=2))
                    except Exception as e:
                        log.error("Failed to place take-profit order on %s: %s", ticker, e)
                else:
                    log.debug("  %s: cost=%d¢, val=%d¢, gain=%.0f%% (below %d%%)",
                              ticker, cost, current_val, gain_pct, take_profit_pct)

            except Exception as e:
                log.error("Failed to check market %s: %s", ticker, e)

    def log_portfolio_status(self):
        """Log current portfolio P&L for all open positions."""
        if self.paper_mode:
            try:
                cash, total_exposure, enriched = get_paper_portfolio_value(self.client)
                if not enriched:
                    log.info("📊 PAPER PORTFOLIO: No open positions | Cash: $%.2f", cash / 100)
                    return
                log.info("📊 PAPER PORTFOLIO STATUS:")
                total_cost = 0
                total_value = 0
                for p in enriched:
                    cost = p["market_exposure"]
                    val = p["current_value"]
                    pnl = val - cost
                    total_cost += cost
                    total_value += val
                    side = "NO" if p["position"] < 0 else "YES"
                    qty = abs(p["position"])
                    emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
                    log.info("  %s %s %s x%d | cost=%d¢ now=%d¢ pnl=%+d¢",
                             emoji, p["ticker"], side, qty, cost, val, pnl)
                total_pnl = total_value - total_cost
                log.info("  💰 Cash: $%.2f | Cost: $%.2f | Value: $%.2f | Unrealized: %+d¢",
                         cash / 100, total_cost / 100, total_value / 100, total_pnl)
            except Exception as e:
                log.error("Paper portfolio status failed: %s", e)
            return

        try:
            positions_resp = self.client.get_positions()
            positions = positions_resp.get("market_positions", [])
            bal = self.client.get_balance()
            cash = bal.get("balance", 0)
        except Exception as e:
            log.error("Portfolio status: failed to get data: %s", e)
            return

        total_cost = 0
        total_value = 0
        log.info("📊 PORTFOLIO STATUS:")

        for pos in positions:
            ticker = pos.get("ticker", "")
            qty = pos.get("position", 0)
            exposure = pos.get("market_exposure", 0)
            if qty == 0:
                continue

            import time
            time.sleep(0.15)
            try:
                market = self.client.get_market(ticker).get("market", {})
                yes_bid = market.get("yes_bid", 0)

                if qty < 0:  # NO position
                    cost = exposure
                    current_val = abs(qty) * (100 - yes_bid) if yes_bid is not None else abs(qty) * 99
                    pnl = current_val - cost
                    side = "NO"
                    display_qty = abs(qty)
                else:  # YES position
                    cost = exposure
                    current_val = qty * yes_bid
                    pnl = current_val - cost
                    side = "YES"
                    display_qty = qty

                total_cost += cost
                total_value += current_val
                emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
                log.info("  %s %s %s x%d | cost=%d¢ now=%d¢ pnl=%+d¢ %s",
                         emoji, ticker, side, display_qty, cost, current_val, pnl, f"YES@{yes_bid}¢")
            except Exception as e:
                log.error("  Failed to price %s: %s", ticker, e)

        total_pnl = total_value - total_cost
        log.info("  💰 Cash: $%.2f | Positions cost: $%.2f | Current value: $%.2f | Unrealized P&L: %+.2f¢",
                 cash / 100, total_cost / 100, total_value / 100, total_pnl)

    def cut_losers(self):
        """Exit positions that have moved heavily against us (>42% loss) while there's still some bid."""
        if self.paper_mode:
            positions = get_paper_positions()
        else:
            try:
                positions_resp = self.client.get_positions()
                positions = positions_resp.get("market_positions", [])
            except Exception as e:
                log.error("Cut losers: failed to get positions: %s", e)
                return

        for pos in positions:
            ticker = pos.get("ticker", "")
            qty = pos.get("position", 0)
            exposure = pos.get("market_exposure", 0)
            if qty == 0:
                continue

            import time
            time.sleep(0.15)
            try:
                market = self.client.get_market(ticker).get("market", {})
                status = market.get("status", "")
                if status != "active":
                    continue

                yes_bid = market.get("yes_bid", 0) or 0
                no_bid = market.get("no_bid", 0) or 0

                if qty < 0:
                    # NO position — we lose if YES wins
                    cost = exposure
                    current_val = abs(qty) * (100 - yes_bid)
                    sell_side = "no"
                    sell_price = no_bid
                    sell_qty = abs(qty)
                else:
                    # YES position
                    cost = exposure
                    current_val = qty * yes_bid
                    sell_side = "yes"
                    sell_price = yes_bid
                    sell_qty = qty

                if cost == 0:
                    continue
                loss_pct = ((cost - current_val) / cost) * 100

                # Cut if >42% underwater and there's still a bid to sell into
                if loss_pct >= 42 and sell_price >= 2:
                    log.info("✂️ CUT LOSER: %s | cost=%d¢ now=%d¢ (%.0f%% loss) | selling %s x%d @ %d¢",
                             ticker, cost, current_val, loss_pct, sell_side, sell_qty, sell_price)
                    try:
                        if self.paper_mode:
                            close_paper_position(ticker, sell_side, sell_qty, yes_bid)
                        elif sell_side == "yes":
                            result = self.client.create_order(
                                ticker=ticker, action="sell", side="yes",
                                count=sell_qty, order_type="limit", yes_price=sell_price)
                            log.info("  CUT ORDER: %s", json.dumps(result, indent=2))
                        else:
                            result = self.client.create_order(
                                ticker=ticker, action="sell", side="no",
                                count=sell_qty, order_type="limit", no_price=sell_price)
                            log.info("  CUT ORDER: %s", json.dumps(result, indent=2))
                    except Exception as e:
                        log.error("  Failed to cut %s: %s", ticker, e)

            except Exception as e:
                log.error("Cut losers: failed on %s: %s", ticker, e)

    def run_cycle(self):
        """Run one complete cycle: collect → signal → trade."""
        # Anti-front-running: random delay so we don't trade on the clock
        # Use --no-jitter flag or NO_JITTER env var to skip (for tight cron windows)
        import random
        if not getattr(self, 'no_jitter', False) and not os.environ.get('NO_JITTER'):
            jitter = random.randint(0, 300)
            log.info("Anti-front-run jitter: waiting %ds before cycle", jitter)
            time.sleep(jitter)
        else:
            log.info("Jitter disabled, starting immediately")

        log.info("=" * 70)
        log.info("Starting bot cycle [%s mode]",
                 "PAPER" if self.paper_mode else "LIVE")
        log.info("=" * 70)

        # Step 0: Sync settlements from Kalshi
        if not self.paper_mode:
            self.sync_settlements()

        # Step 0a: Log portfolio status
        self.log_portfolio_status()

        # Step 0b: Check 80% profit rule
        self.check_80pct_rule()

        # Step 0c: Check take-profits on existing positions
        self.check_take_profits()

        # Step 0d: Cut losers (>42% underwater with bids available)
        self.cut_losers()

        # Step 1: Collect weather data
        try:
            obs_count = collect_all()
            log.info("Collected %d observations", obs_count)
        except Exception as e:
            log.error("Collection failed: %s", e, exc_info=True)
            return

        # Step 1b: Update METAR data for lock-in signals
        try:
            metar_count = update_all_stations()
            log.info("Updated %d METAR stations", metar_count)
        except Exception as e:
            log.error("METAR update failed: %s", e, exc_info=True)
            # Don't return - continue with regular signals

        # Step 2: Check trading window
        in_window, window_type = self.is_trading_window()
        if not in_window:
            log.info("Outside trading window. Skipping signal generation.")
            return

        log.info("In %s temp trading window", window_type)

        # Step 3: Generate regular signals
        try:
            model_signals = generate_signals(self.client)
            # Tag signals with source
            for signal in model_signals:
                signal.signal_source = "model"
            log.info("Generated %d model signals", len(model_signals))
        except Exception as e:
            log.error("Model signal generation failed: %s", e, exc_info=True)
            model_signals = []

        # Step 3b: Generate lock-in signals
        try:
            lockin_signals = generate_lockin_signals(self.client)
            # Tag signals with source
            for signal in lockin_signals:
                signal.signal_source = "metar_lockin"
            log.info("Generated %d lock-in signals", len(lockin_signals))
        except Exception as e:
            log.error("Lock-in signal generation failed: %s", e, exc_info=True)
            lockin_signals = []

        # Combine signals with lock-in signals prioritized first
        all_signals = lockin_signals + model_signals

        # Filter signals for current window type
        # Today's markets: must match current window (high/low)
        # Tomorrow's markets: always eligible (early entry edge)
        from datetime import timedelta
        now_utc = datetime.now(timezone.utc)
        tomorrow_str = (now_utc + timedelta(days=1)).strftime("%y%b%d").upper()
        
        window_signals = [s for s in all_signals 
                         if s.market_type == window_type 
                         or tomorrow_str in s.event_ticker]
        
        # Count by signal source
        model_count = len([s for s in window_signals if getattr(s, 'signal_source', 'model') == 'model'])
        lockin_count = len([s for s in window_signals if getattr(s, 'signal_source', 'model') == 'metar_lockin'])
        
        log.info("Generated %d total signals (%d model + %d lock-in) → %d for current window",
                 len(all_signals), len(model_signals), len(lockin_signals), len(window_signals))
        log.info("Window signals: %d model + %d lock-in", model_count, lockin_count)

        # Log predictions for accuracy tracking
        self._log_predictions(all_signals)

        if not window_signals:
            log.info("No actionable signals for %s window", window_type)
            return

        # Step 4: Execute top signals (max 2 brackets per event)
        executed = 0
        event_bracket_count = {}  # track brackets per event
        max_per_event = self.risk.get("max_brackets_per_event", 2)

        # Early exit if daily trade limit already reached
        today_count = self._get_live_trade_count() if not self.paper_mode else get_todays_trade_count()
        base_max = self.risk["max_trades_per_day"]
        if today_count >= base_max:
            log.info("Daily trade limit already reached (%d/%d) — skipping signal execution.",
                     today_count, base_max)
            return

        for signal in window_signals:
            if executed >= 3:  # Max 3 trades per cycle
                break

            # Enforce max brackets per event
            evt = signal.event_ticker
            if event_bracket_count.get(evt, 0) >= max_per_event:
                log.info("Skipping %s: max %d brackets for event %s",
                         signal.market_ticker, max_per_event, evt)
                continue

            result = self.execute_signal(signal)
            if result:
                executed += 1
                event_bracket_count[evt] = event_bracket_count.get(evt, 0) + 1
                log.info("Trade %d executed: %s", executed, signal)

        # Step 5: Log summary
        if self.paper_mode:
            summary = get_paper_summary()
            log.info("Paper balance: %s | Trades today: %d | Total P&L: %s",
                     summary["balance_usd"], summary["total_trades"],
                     summary["total_pnl_usd"])
        
        # Step 6: A/B Testing Report
        try:
            ab_stats = self.get_ab_stats()
            log.info("=== A/B Testing Stats ===")
            for source, stats in ab_stats.items():
                if stats['total_trades'] > 0:
                    log.info("%s: %d trades, %.1f%% win rate, avg P&L %.1f¢ (total: %d¢)", 
                            source.upper(), stats['total_trades'], stats['win_rate'], 
                            stats['avg_pnl_cents'], stats['total_pnl_cents'])
                else:
                    log.info("%s: No completed trades yet", source.upper())
        except Exception as e:
            log.error("A/B stats failed: %s", e)

    def run_continuous(self, interval_min: int = None):
        """Run continuously with specified interval."""
        interval = (interval_min or CONFIG["collector_interval_min"]) * 60
        log.info("Starting continuous mode (interval: %d min)", interval // 60)

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                log.info("Bot stopped by user")
                break
            except Exception as e:
                log.error("Cycle failed: %s", e, exc_info=True)

            log.info("Next cycle in %d minutes...", interval // 60)
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                log.info("Bot stopped by user")
                break


def main():
    parser = argparse.ArgumentParser(description="Kalshi Weather Trading Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading (default: paper)")
    parser.add_argument("--yes", action="store_true", help="Skip live trading confirmation")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=None, help="Interval in minutes (default: from config)")
    parser.add_argument("--status", action="store_true", help="Show paper trading summary")
    parser.add_argument("--paper-portfolio", action="store_true", help="Show paper portfolio with live prices")
    parser.add_argument("--no-jitter", action="store_true", help="Skip anti-front-running delay")
    args = parser.parse_args()

    if args.paper_portfolio:
        init_paper_db()
        client = KalshiClient()
        positions = get_paper_positions()
        if not positions:
            print("\nNo open paper positions.")
        else:
            cash, total_exp, enriched = get_paper_portfolio_value(client)
            print(f"\n=== Paper Portfolio (Cash: ${cash/100:.2f}) ===")
            total_cost = 0
            total_val = 0
            for p in enriched:
                side = "NO" if p["position"] < 0 else "YES"
                qty = abs(p["position"])
                cost = p["market_exposure"]
                val = p["current_value"]
                pnl = val - cost
                total_cost += cost
                total_val += val
                emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
                print(f"  {emoji} {p['ticker']} {side} x{qty} | cost={cost}¢ val={val}¢ pnl={pnl:+d}¢ (YES@{p['yes_bid']}¢)")
            print(f"\n  Total: cost=${total_cost/100:.2f} val=${total_val/100:.2f} unrealized={total_val-total_cost:+d}¢")
            print(f"  Account value: ${(cash + total_val)/100:.2f}")
        return

    if args.status:
        init_paper_db()
        summary = get_paper_summary()
        print("\n=== Paper Trading Summary ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        return

    paper_mode = not args.live
    if not paper_mode:
        log.warning("⚠️  LIVE TRADING MODE — Real money at risk!")
        if not args.yes:
            confirm = input("Type 'YES' to confirm live trading: ")
            if confirm != "YES":
                print("Aborted.")
                return

    bot = WeatherBot(paper_mode=paper_mode)
    bot.no_jitter = args.no_jitter

    if args.continuous:
        bot.run_continuous(args.interval)
    else:
        bot.run_cycle()


if __name__ == "__main__":
    main()
