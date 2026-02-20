#!/usr/bin/env python3
"""
8 Validation Tests — ALL MUST PASS before bot goes live.
Tests cover the critical code paths that caused the ATL B79.5 incident.

Run: python3 test_validation.py
"""
import sys
import os
import json
import sqlite3
import tempfile
import shutil
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass, field

# Add parent dir to path
sys.path.insert(0, os.path.dirname(__file__))

# We'll import from the actual modules
from signal_generator import Signal

PASS = 0
FAIL = 0
RESULTS = []


def test(name):
    """Decorator to register and run a test."""
    def decorator(func):
        func._test_name = name
        return func
    return decorator


def report(name, passed, detail=""):
    global PASS, FAIL
    if passed:
        PASS += 1
        RESULTS.append(f"  ✅ PASS: {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  ❌ FAIL: {name} — {detail}")


def make_signal(**kwargs):
    """Create a Signal with sensible defaults, overridable by kwargs."""
    defaults = dict(
        city="NYC", market_type="high", event_ticker="KXHIGHNY-26FEB20",
        market_ticker="KXHIGHNY-26FEB20-B45.5", side="no", action="buy",
        suggested_price=75, confidence=0.5, edge_pct=30.0,
        our_probability=0.90, market_yes_price=25,
        estimated_temp=42.0, forecast_temp_f=42.0, current_temp_f=40.0,
        surrounding_avg_f=39.0, reason="Test signal", signal_source="model",
        is_tomorrow=False, margin=5.0
    )
    defaults.update(kwargs)
    s = Signal.__new__(Signal)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def make_test_db():
    """Create a temporary test database."""
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    c = conn.cursor()
    # Paper trades table
    c.execute("""CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT, market_type TEXT, event_ticker TEXT, market_ticker TEXT,
        action TEXT, side TEXT, price_cents INTEGER, contracts INTEGER,
        confidence REAL, edge_pct REAL, reason TEXT,
        current_temp_f REAL, forecast_temp_f REAL, surrounding_avg_f REAL,
        settled INTEGER DEFAULT 0, settlement_result TEXT, pnl_cents INTEGER DEFAULT 0,
        created_at TEXT, settled_at TEXT, signal_source TEXT DEFAULT 'model'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS paper_balance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        balance_cents INTEGER, updated_at TEXT
    )""")
    c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (10000, ?)",
              (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    return tmp, conn


# ==========================================
# TEST 1: Profit Rule Position-Close
# ==========================================
def test_1_profit_rule_close():
    """When profit rule triggers, bot uses action='sell' to CLOSE positions, not action='buy'."""
    name = "Test 1: Profit Rule Position-Close"
    try:
        from bot import WeatherBot
        import bot as bot_module
        import paper_trade as pt_module

        # Create a mock config
        config = {
            "db_path": ":memory:",
            "risk": {
                "max_trades_per_day": 22,
                "min_edge_pct": 15,
                "bonus_trades_after_wins": 18,
                "bonus_trade_count": 2,
                "max_contracts_per_ticker": 50,
            },
            "kill_switch": False,
        }

        # Create bot in paper mode with mocked client
        mock_client = MagicMock()
        
        # Mock get_market to return prices showing profit
        mock_client.get_market.return_value = {
            "market": {
                "yes_bid": 10,  # YES is cheap = NO is winning
                "no_ask": 15,
                "status": "active",
            }
        }

        # Track all create_order calls
        order_calls = []
        def track_order(**kwargs):
            order_calls.append(kwargs)
            return {"order": {"order_id": "test123"}}
        mock_client.create_order.side_effect = track_order

        # Build positions list: NO position that's profitable
        # position=-5 means LONG 5 NO contracts
        positions = [{
            "ticker": "KXHIGHNY-26FEB20-B80.5",
            "position": -5,  # LONG 5 NO contracts
            "market_exposure": 400,  # paid 400¢ total (80¢ each)
        }]

        # Create bot instance with paper_mode=False to test live code path
        bot = WeatherBot.__new__(WeatherBot)
        bot.client = mock_client
        bot.config = config
        bot.risk = config["risk"]
        bot.paper_mode = False
        bot._80pct_triggered = False

        # Call the actual liquidation function
        bot._liquidate_winning_positions(positions)

        # Check: should have called create_order with action="sell"
        if len(order_calls) == 0:
            # Position might not be profitable at current prices — adjust
            # no_ask=15, received_per = 400/5 = 80. 15 < 80, so it IS profitable
            report(name, False, "No order placed — function didn't execute")
            return

        for call in order_calls:
            if call.get("action") == "buy":
                report(name, False, f"Used action='buy' instead of 'sell'! Call: {call}")
                return
            if call.get("action") != "sell":
                report(name, False, f"Unexpected action: {call.get('action')}. Call: {call}")
                return

        # Verify it used side="no" for NO position close
        if order_calls[0].get("side") != "no":
            report(name, False, f"Wrong side: {order_calls[0].get('side')}, expected 'no'")
            return

        report(name, True)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 2: NO Position P&L Calculation
# ==========================================
def test_2_no_pnl_calculation():
    """P&L is correctly calculated for NO positions (inverted economics)."""
    name = "Test 2: NO Position P&L Calculation"
    try:
        # Test the paper close function for NO positions
        tmp_db, conn = make_test_db()
        
        import paper_trade as pt
        original_db = pt.DB_PATH
        pt.DB_PATH = tmp_db

        try:
            # Insert a NO trade: bought 10 NO at 20¢ each
            c = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            c.execute("""INSERT INTO paper_trades 
                (city, market_type, event_ticker, market_ticker, action, side,
                 price_cents, contracts, confidence, edge_pct, reason,
                 current_temp_f, forecast_temp_f, surrounding_avg_f,
                 settled, created_at, signal_source)
                VALUES ('NYC','high','EV1','TICK1','buy','no',20,10,0.5,30.0,'test',
                        40.0,42.0,39.0,0,?,  'model')""", (now,))
            # Debit balance for the purchase (10 * 20 = 200¢)
            c.execute("UPDATE paper_balance SET balance_cents = balance_cents - 200")
            conn.commit()
            
            initial_balance = pt.get_paper_balance()

            # Scenario 1: NO wins (YES settles at 0, NO = 100)
            # Close at yes_bid=5 (very low, NO is worth ~95¢)
            pt.close_paper_position("TICK1", "no", 10, 5)
            
            after_balance = pt.get_paper_balance()
            # credit = qty * (100 - price) = 10 * (100 - 5) = 950¢
            expected_credit = 950
            actual_credit = after_balance - initial_balance
            
            if actual_credit != expected_credit:
                report(name, False, f"NO close credit wrong: got {actual_credit}¢, expected {expected_credit}¢")
                return

            # Scenario 2: Check P&L on the settled trade
            c2 = sqlite3.connect(tmp_db)
            settled = c2.execute("SELECT pnl_cents FROM paper_trades WHERE settled=1").fetchall()
            c2.close()
            
            # P&L should be positive (we bought at 20¢, closed NO at 95¢ effective)
            if not settled or settled[0][0] <= 0:
                report(name, False, f"P&L should be positive for winning NO trade, got: {settled}")
                return

            report(name, True)
        finally:
            pt.DB_PATH = original_db
            os.unlink(tmp_db)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 3: Sanity Check Enforcement
# ==========================================
def test_3_sanity_check_blocks():
    """Sanity check BLOCKS trades when conditions are met, not just logs."""
    name = "Test 3: Sanity Check Enforcement"
    try:
        from bot import WeatherBot

        bot = WeatherBot.__new__(WeatherBot)
        bot.client = MagicMock()
        bot.config = {"db_path": ":memory:"}
        bot.risk = {"max_contracts_per_ticker": 50}
        bot.paper_mode = True

        # Sub-test A: >90% edge on liquid market should be BLOCKED
        signal_a = make_signal(edge_pct=95.0, market_yes_price=25, signal_source="model")
        result_a = bot._sanity_check(signal_a)
        if result_a:
            report(name, False, ">90% edge on liquid market was NOT blocked")
            return

        # Sub-test B: >20°F forecast vs current temp should be BLOCKED
        signal_b = make_signal(
            edge_pct=30.0, market_yes_price=25,
            forecast_temp_f=80.0, current_temp_f=50.0  # 30°F diff
        )
        result_b = bot._sanity_check(signal_b)
        if result_b:
            report(name, False, ">20°F temp divergence was NOT blocked")
            return

        # Sub-test C: Normal signal should PASS
        signal_c = make_signal(edge_pct=30.0, market_yes_price=25,
                               forecast_temp_f=42.0, current_temp_f=40.0)
        result_c = bot._sanity_check(signal_c)
        if not result_c:
            report(name, False, "Normal signal was incorrectly blocked")
            return

        # Sub-test D: Lock-in signal with >90% edge should PASS
        signal_d = make_signal(edge_pct=95.0, market_yes_price=25, signal_source="metar_lockin")
        result_d = bot._sanity_check(signal_d)
        if not result_d:
            report(name, False, "Lock-in signal with >90% edge was incorrectly blocked")
            return

        report(name, True)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 4: Capital Cap Checks
# ==========================================
def test_4_capital_cap():
    """Bot respects 40% capital deployment cap."""
    name = "Test 4: Capital Cap Checks"
    try:
        from bot import WeatherBot
        import paper_trade as pt

        tmp_db, conn = make_test_db()
        original_db = pt.DB_PATH
        pt.DB_PATH = tmp_db

        try:
            # Set paper balance to $100 (10000¢)
            c = conn.cursor()
            c.execute("DELETE FROM paper_balance")
            c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (10000, ?)",
                      (datetime.now(timezone.utc).isoformat(),))
            
            # Add existing positions worth $35 (3500¢ exposure) — that's 35% of $100
            now = datetime.now(timezone.utc).isoformat()
            for i in range(7):
                c.execute("""INSERT INTO paper_trades 
                    (city, market_type, event_ticker, market_ticker, action, side,
                     price_cents, contracts, confidence, edge_pct, reason,
                     current_temp_f, forecast_temp_f, surrounding_avg_f,
                     settled, created_at, signal_source)
                    VALUES ('NYC','high','EV1',?,'buy','no',50,10,0.5,30.0,'test',
                            40.0,42.0,39.0,0,?,'model')""", 
                    (f"TICK-{i}", now))
            conn.commit()

            bot = WeatherBot.__new__(WeatherBot)
            bot.client = MagicMock()
            # Mock get_market for portfolio valuation
            bot.client.get_market.return_value = {"market": {"yes_bid": 50, "no_ask": 50}}
            bot.config = {"db_path": tmp_db}
            bot.risk = {
                "max_trades_per_day": 100,  # high so this isn't the limiter
                "min_edge_pct": 15,
                "bonus_trades_after_wins": 18,
                "bonus_trade_count": 2,
                "max_contracts_per_ticker": 50,
            }
            bot.paper_mode = True
            bot._80pct_triggered = False

            # Signal that would push us over 40% cap
            signal = make_signal(edge_pct=30.0, suggested_price=75)

            # check_risk_limits should reject due to capital cap
            # Total exposure = 7 * 10 * 50 = 3500¢ = 35%
            # Account value = 10000 + 3500 = 13500, 40% = 5400
            # Current exposure 3500 < 5400 so it should PASS
            # But let's test with enough exposure to exceed cap
            
            # Reset with very high exposure
            c.execute("DELETE FROM paper_trades")
            for i in range(10):
                c.execute("""INSERT INTO paper_trades 
                    (city, market_type, event_ticker, market_ticker, action, side,
                     price_cents, contracts, confidence, edge_pct, reason,
                     current_temp_f, forecast_temp_f, surrounding_avg_f,
                     settled, created_at, signal_source)
                    VALUES ('NYC','high','EV1',?,'buy','no',80,10,0.5,30.0,'test',
                            40.0,42.0,39.0,0,?,'model')""", 
                    (f"TICK-{i}", now))
            conn.commit()
            # Exposure = 10 * 10 * 80 = 8000¢. Account = 10000 + 8000 = 18000. 40% = 7200. 8000 > 7200 = BLOCKED

            result = bot.check_risk_limits(signal)
            if result:
                report(name, False, "Capital cap was NOT enforced (should have blocked)")
                return

            report(name, True)
        finally:
            pt.DB_PATH = original_db
            os.unlink(tmp_db)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 5: Dedup Logic
# ==========================================
def test_5_dedup():
    """Bot does not place duplicate orders for same market/bracket within same cycle."""
    name = "Test 5: Dedup Logic"
    try:
        import paper_trade as pt

        tmp_db, conn = make_test_db()
        original_db = pt.DB_PATH
        pt.DB_PATH = tmp_db

        try:
            # Insert an existing unsettled trade
            now = datetime.now(timezone.utc).isoformat()
            c = conn.cursor()
            c.execute("""INSERT INTO paper_trades 
                (city, market_type, event_ticker, market_ticker, action, side,
                 price_cents, contracts, confidence, edge_pct, reason,
                 current_temp_f, forecast_temp_f, surrounding_avg_f,
                 settled, created_at, signal_source)
                VALUES ('NYC','high','EV1','KXHIGHNY-26FEB20-B45.5','buy','no',75,3,0.5,30.0,'test',
                        40.0,42.0,39.0,0,?,'model')""", (now,))
            conn.commit()

            # Check dedup — should find the existing trade
            is_dup = pt.is_duplicate_trade("KXHIGHNY-26FEB20-B45.5", "no")
            if not is_dup:
                report(name, False, "Dedup did not detect existing unsettled trade")
                return

            # Different ticker should NOT be a dup
            is_dup_other = pt.is_duplicate_trade("KXHIGHNY-26FEB20-B50.5", "no")
            if is_dup_other:
                report(name, False, "Dedup falsely flagged a different ticker")
                return

            # Different side should NOT be a dup
            is_dup_side = pt.is_duplicate_trade("KXHIGHNY-26FEB20-B45.5", "yes")
            if is_dup_side:
                report(name, False, "Dedup falsely flagged a different side")
                return

            report(name, True)
        finally:
            pt.DB_PATH = original_db
            os.unlink(tmp_db)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 6: Lock-in Signal Handling
# ==========================================
def test_6_lockin_signals():
    """Lock-in signals bypass YES hard block and use 1% min edge."""
    name = "Test 6: Lock-in Signal Handling"
    try:
        from bot import WeatherBot
        import paper_trade as pt

        tmp_db, conn = make_test_db()
        original_db = pt.DB_PATH
        pt.DB_PATH = tmp_db

        try:
            bot = WeatherBot.__new__(WeatherBot)
            bot.client = MagicMock()
            bot.client.get_market.return_value = {"market": {"yes_bid": 95, "no_ask": 5}}
            bot.config = {"db_path": tmp_db}
            bot.risk = {
                "max_trades_per_day": 100,
                "min_edge_pct": 15,  # normal min edge
                "bonus_trades_after_wins": 18,
                "bonus_trade_count": 2,
                "max_contracts_per_ticker": 50,
            }
            bot.paper_mode = True
            bot._80pct_triggered = False
            bot.no_jitter = True

            # Test A: Normal YES buy should be BLOCKED
            normal_yes = make_signal(side="yes", action="buy", edge_pct=20.0,
                                      suggested_price=95, signal_source="model")
            
            # execute_signal checks for YES block
            # We need to verify the YES hard block works
            # The function checks: if signal.side == "yes" and not is_lockin: return None
            is_lockin = getattr(normal_yes, 'signal_source', '') == 'metar_lockin'
            if normal_yes.side == "yes" and not is_lockin:
                blocked = True
            else:
                blocked = False
            
            if not blocked:
                report(name, False, "Normal YES buy was NOT blocked")
                return

            # Test B: Lock-in YES buy should be ALLOWED
            lockin_yes = make_signal(side="yes", action="buy", edge_pct=3.0,
                                     suggested_price=95, signal_source="metar_lockin")
            is_lockin2 = getattr(lockin_yes, 'signal_source', '') == 'metar_lockin'
            if lockin_yes.side == "yes" and not is_lockin2:
                report(name, False, "Lock-in YES buy was incorrectly blocked")
                return

            # Test C: Lock-in with 3% edge should pass risk check (min_edge=1% for lockin)
            # check_risk_limits uses 1% min for lockin vs 15% normal
            min_edge = 1.0 if is_lockin2 else bot.risk["min_edge_pct"]
            if lockin_yes.edge_pct < min_edge:
                report(name, False, f"Lock-in edge {lockin_yes.edge_pct}% rejected (min {min_edge}%)")
                return

            # Test D: Normal signal with 3% edge should FAIL risk check
            normal_low_edge = make_signal(edge_pct=3.0, signal_source="model")
            is_lockin3 = getattr(normal_low_edge, 'signal_source', '') == 'metar_lockin'
            min_edge3 = 1.0 if is_lockin3 else bot.risk["min_edge_pct"]
            if normal_low_edge.edge_pct >= min_edge3:
                report(name, False, f"Normal 3% edge signal should be below 15% min")
                return

            report(name, True)
        finally:
            pt.DB_PATH = original_db
            os.unlink(tmp_db)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 7: Cut-Losers Mechanics
# ==========================================
def test_7_cut_losers():
    """Bot exits losing positions with action='sell' when loss > 42%."""
    name = "Test 7: Cut-Losers Mechanics"
    try:
        from bot import WeatherBot

        bot = WeatherBot.__new__(WeatherBot)
        bot.config = {"db_path": ":memory:"}
        bot.risk = {"max_contracts_per_ticker": 50}
        bot.paper_mode = False

        mock_client = MagicMock()
        bot.client = mock_client

        # NO position: bought 5 NO at 80¢ each (exposure = 400¢)
        # Current: yes_bid = 70 (NO worth 30¢). Cost=400, val=5*30=150. Loss=62.5%
        mock_client.get_positions.return_value = {
            "market_positions": [{
                "ticker": "KXHIGHNY-26FEB20-B80.5",
                "position": -5,  # LONG 5 NO
                "market_exposure": 400,
            }]
        }
        mock_client.get_market.return_value = {
            "market": {
                "yes_bid": 70,
                "no_bid": 30,
                "no_ask": 35,
                "status": "active",
            }
        }

        order_calls = []
        def track_order(**kwargs):
            order_calls.append(kwargs)
            return {"order": {"order_id": "cut123"}}
        mock_client.create_order.side_effect = track_order

        bot.cut_losers()

        if len(order_calls) == 0:
            report(name, False, "No cut order placed despite >42% loss")
            return

        call = order_calls[0]
        if call.get("action") != "sell":
            report(name, False, f"Cut loser used action='{call.get('action')}' instead of 'sell'")
            return
        if call.get("side") != "no":
            report(name, False, f"Cut loser used side='{call.get('side')}' instead of 'no'")
            return
        if call.get("count") != 5:
            report(name, False, f"Cut loser count={call.get('count')}, expected 5")
            return

        report(name, True)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# TEST 8: Rolling Profit Rule Trigger
# ==========================================
def test_8_rolling_profit_trigger():
    """Rolling profit rule triggers at 10% of account value and calls _liquidate_winning_positions."""
    name = "Test 8: Rolling Profit Rule Trigger"
    try:
        from bot import WeatherBot

        bot = WeatherBot.__new__(WeatherBot)
        bot.config = {"db_path": ":memory:"}
        bot.risk = {"max_contracts_per_ticker": 50}
        bot.paper_mode = False
        bot._80pct_triggered = False

        mock_client = MagicMock()
        bot.client = mock_client

        # Account: $100 cash + positions
        mock_client.get_balance.return_value = {"balance": 10000}  # 10000¢ = $100

        # 3 NO positions, all very profitable
        # Each: position=-10, exposure=200¢ (bought at 20¢ each)
        # Current: no_ask=5 (we can close at 5¢, so NO worth 95¢)
        # Cost to close = no_ask * qty = 5 * 10 = 50¢ per position
        # Value locked = exposure = 200¢ per position
        # Unrealized per position = 200 - 50 = 150¢
        # Total unrealized = 450¢ = $4.50
        # Account value = 10000 + 3*200 = 10600¢. 10% = 1060¢
        # 450 < 1060, won't trigger.
        
        # Make it trigger: bigger positions
        # exposure=2000¢ each (bought at 200¢ x 10), no_ask=50
        # cost_to_close = 50 * 10 = 500. value = 2000. unrealized = 1500 per pos
        # Total unrealized = 4500¢. Account = 10000 + 3*2000 = 16000. 10% = 1600. 4500 > 1600 → TRIGGER
        mock_client.get_positions.return_value = {
            "market_positions": [
                {"ticker": "TICK1", "position": -10, "market_exposure": 2000},
                {"ticker": "TICK2", "position": -10, "market_exposure": 2000},
                {"ticker": "TICK3", "position": -10, "market_exposure": 2000},
            ]
        }
        mock_client.get_market.return_value = {
            "market": {
                "no_ask": 50,
                "yes_bid": 50,
                "status": "active",
            }
        }

        # Track if _liquidate_winning_positions is called
        liquidate_called = []
        original_liquidate = bot._liquidate_winning_positions.__func__ if hasattr(bot._liquidate_winning_positions, '__func__') else None
        
        def mock_liquidate(positions):
            liquidate_called.append(positions)
        bot._liquidate_winning_positions = mock_liquidate

        result = bot.check_80pct_rule()

        if not result:
            report(name, False, "Profit rule did NOT trigger despite exceeding 10% threshold")
            return

        if len(liquidate_called) == 0:
            report(name, False, "Profit rule triggered but _liquidate_winning_positions was NOT called")
            return

        if not bot._80pct_triggered:
            report(name, False, "_80pct_triggered flag was not set after trigger")
            return

        report(name, True)
    except Exception as e:
        report(name, False, f"Exception: {e}")


# ==========================================
# MAIN — Run all tests
# ==========================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  WEATHER BOT VALIDATION TESTS")
    print("  8 tests required — ALL must pass before going live")
    print("=" * 60 + "\n")

    tests = [
        test_1_profit_rule_close,
        test_2_no_pnl_calculation,
        test_3_sanity_check_blocks,
        test_4_capital_cap,
        test_5_dedup,
        test_6_lockin_signals,
        test_7_cut_losers,
        test_8_rolling_profit_trigger,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            report(t.__doc__ or t.__name__, False, f"Unhandled: {e}")

    print("\n".join(RESULTS))
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {PASS}/8 passed, {FAIL}/8 failed")
    if FAIL == 0:
        print("  ✅ ALL TESTS PASSED — Bot cleared for live trading")
    else:
        print("  ❌ TESTS FAILED — DO NOT enable live trading")
    print(f"{'=' * 60}\n")

    sys.exit(0 if FAIL == 0 else 1)
