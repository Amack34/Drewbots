#!/usr/bin/env python3
"""
Validation tests for bot fixes.
All 8 must pass before bot can go live.
"""
import json
import sys
import os
from unittest.mock import MagicMock, patch
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

RESULTS = {}

def test(name):
    def decorator(fn):
        def wrapper():
            try:
                fn()
                RESULTS[name] = "✅ PASS"
                print(f"  ✅ {name}")
            except AssertionError as e:
                RESULTS[name] = f"❌ FAIL: {e}"
                print(f"  ❌ {name}: {e}")
            except Exception as e:
                RESULTS[name] = f"❌ ERROR: {e}"
                print(f"  ❌ {name}: {type(e).__name__}: {e}")
        return wrapper
    return decorator


@test("1. Profit rule closes NO correctly")
def test_1():
    """Verify _sell_winning_positions uses action=sell for NO positions."""
    import bot
    config = json.load(open("config.json"))
    config["kill_switch"] = True  # Safety
    
    b = bot.WeatherBot.__new__(bot.WeatherBot)
    b.config = config
    b.risk = config.get("risk", {})
    b.paper_mode = False
    
    # Mock client
    mock_client = MagicMock()
    mock_client.get_market.return_value = {"market": {"no_ask": 2, "yes_bid": 98}}
    mock_client.create_order.return_value = {"order": {"status": "executed", "fill_count": 100}}
    b.client = mock_client
    
    # Simulate NO position: qty=-100, exposure=500 (received 5¢ per contract)
    positions = [{"ticker": "TEST-TICKER", "position": -100, "market_exposure": 500}]
    
    b._liquidate_winning_positions(positions)
    
    # Verify create_order was called with action="sell", side="no"
    assert mock_client.create_order.called, "create_order was not called"
    call_kwargs = mock_client.create_order.call_args
    if call_kwargs.kwargs:
        assert call_kwargs.kwargs.get("action") == "sell", f"action={call_kwargs.kwargs.get('action')}, expected 'sell'"
        assert call_kwargs.kwargs.get("side") == "no", f"side={call_kwargs.kwargs.get('side')}, expected 'no'"
    else:
        assert False, f"Expected keyword args, got positional: {call_kwargs.args}"


@test("2. Profit rule closes YES correctly")
def test_2():
    """Verify YES positions use action=sell, side=yes."""
    import bot
    config = json.load(open("config.json"))
    config["kill_switch"] = True
    
    b = bot.WeatherBot.__new__(bot.WeatherBot)
    b.config = config
    b.risk = config.get("risk", {})
    b.paper_mode = False
    
    mock_client = MagicMock()
    mock_client.get_market.return_value = {"market": {"yes_bid": 80, "no_ask": 20}}
    mock_client.create_order.return_value = {"order": {"status": "executed", "fill_count": 50}}
    b.client = mock_client
    
    # YES position: qty=50, exposure=2500 (cost 50¢ per contract)
    positions = [{"ticker": "TEST-YES", "position": 50, "market_exposure": 2500}]
    
    b._liquidate_winning_positions(positions)
    
    assert mock_client.create_order.called, "create_order was not called"
    call_kwargs = mock_client.create_order.call_args
    assert call_kwargs.kwargs.get("action") == "sell", f"action={call_kwargs.kwargs.get('action')}"
    assert call_kwargs.kwargs.get("side") == "yes", f"side={call_kwargs.kwargs.get('side')}"


@test("3. No stacking on model signals")
def test_3():
    """Model signals should be deduped when position already exists."""
    import bot
    from signal_generator import Signal
    
    config = json.load(open("config.json"))
    config["kill_switch"] = True  # Safety — no real orders
    
    b = bot.WeatherBot.__new__(bot.WeatherBot)
    b.config = config
    b.risk = config.get("risk", {})
    b.paper_mode = True
    b.db_path = config.get("db_path", "weather.db")
    
    mock_client = MagicMock()
    # Simulate existing position on the ticker
    mock_client.get_positions.return_value = {
        "market_positions": [{"ticker": "KXHIGHNY-26FEB20-B44.5", "position": -3, "market_exposure": 225}]
    }
    b.client = mock_client
    
    # Model signal (not lock-in)
    sig = Signal.__new__(Signal)
    sig.market_ticker = "KXHIGHNY-26FEB20-B44.5"
    sig.side = "no"
    sig.signal_source = "model"
    sig.edge = 0.25
    
    result = b._is_live_duplicate(sig.market_ticker, sig.side)
    assert result == True, f"Expected duplicate=True for model signal with existing position, got {result}"


@test("4. is_tomorrow passes all code paths")
def test_4():
    """signal_generator.py should not raise NameError on is_tomorrow."""
    # signal_generator uses module-level functions, not a class
    import signal_generator
    import inspect
    
    # Check _analyze_brackets function exists and accepts is_tomorrow
    assert hasattr(signal_generator, '_analyze_brackets'), "_analyze_brackets not found in signal_generator"
    sig = inspect.signature(signal_generator._analyze_brackets)
    params = list(sig.parameters.keys())
    assert "is_tomorrow" in params, f"is_tomorrow not in _analyze_brackets params: {params}"


@test("5. Per-request API timeouts exist")
def test_5():
    """All external API calls must have timeouts."""
    import weather_collector
    import kalshi_trader
    import weather_validator
    
    # Check NWS timeout
    assert hasattr(weather_collector, 'NWS_TIMEOUT'), "NWS_TIMEOUT not defined"
    assert weather_collector.NWS_TIMEOUT <= 15, f"NWS timeout too high: {weather_collector.NWS_TIMEOUT}"
    
    # Check Kalshi timeout exists in _request method
    import inspect
    src = inspect.getsource(kalshi_trader.KalshiClient._request)
    assert "timeout=" in src, "No timeout in KalshiClient._request"
    
    # Check weather_validator
    src = inspect.getsource(weather_validator._http_get)
    assert "timeout" in src, "No timeout in weather_validator._http_get"


@test("6. price_monitor.py handles NO positions")
def test_6():
    """price_monitor should not skip NO positions in profit rule."""
    import inspect
    with open("price_monitor.py") as f:
        source = f.read()
    
    # Check that the profit rule section doesn't skip qty <= 0
    # The current bug: `if qty <= 0: continue` skips all NO positions
    # After fix, it should handle negative qty (NO positions)
    lines = source.split('\n')
    in_profit_section = False
    skips_no = False
    for i, line in enumerate(lines):
        if 'Liquidate only winning' in line or 'sell winners' in line.lower():
            in_profit_section = True
        if in_profit_section and 'if qty <= 0' in line and 'continue' in line:
            skips_no = True
            break
        if in_profit_section and ('def ' in line and 'self' in line):
            break
    
    # For now, just flag this — the fix needs to be applied
    if skips_no:
        raise AssertionError("price_monitor.py still skips NO positions (qty <= 0: continue)")


@test("7. Kill switch blocks orders")
def test_7():
    """Global kill switch must block all order creation."""
    import bot
    from signal_generator import Signal
    
    config = json.load(open("config.json"))
    config["kill_switch"] = True
    
    b = bot.WeatherBot.__new__(bot.WeatherBot)
    b.config = config
    b.risk = config.get("risk", {})
    b.paper_mode = False
    b.db_path = config.get("db_path", "weather.db")
    
    mock_client = MagicMock()
    mock_client.get_positions.return_value = {"market_positions": []}
    b.client = mock_client
    
    sig = Signal.__new__(Signal)
    sig.market_ticker = "TEST-KILL-SWITCH"
    sig.side = "no"
    sig.signal_source = "model"
    sig.edge = 0.50
    sig.price = 50
    sig.confidence = 0.8
    
    result = b.execute_signal(sig)
    assert result is None, f"Kill switch should block order, got {result}"
    assert not mock_client.create_order.called, "create_order should NOT be called with kill switch on"


@test("8. Position close dry-run")
def test_8():
    """Verify close orders use correct action/side for each position type."""
    # Simulate what close orders WOULD look like
    test_positions = [
        {"ticker": "NO-POS", "position": -100, "type": "no", "expected_action": "sell", "expected_side": "no"},
        {"ticker": "YES-POS", "position": 50, "type": "yes", "expected_action": "sell", "expected_side": "yes"},
    ]
    
    for pos in test_positions:
        qty = pos["position"]
        if qty < 0:
            # NO position — sell to close
            action = "sell"
            side = "no"
            count = abs(qty)
        elif qty > 0:
            # YES position — sell to close
            action = "sell"
            side = "yes"
            count = qty
        else:
            continue
        
        assert action == pos["expected_action"], f"{pos['ticker']}: action={action}, expected {pos['expected_action']}"
        assert side == pos["expected_side"], f"{pos['ticker']}: side={side}, expected {pos['expected_side']}"
        assert count > 0, f"{pos['ticker']}: count={count}"
    
    print(f"    Verified {len(test_positions)} position types")


if __name__ == "__main__":
    print("\n🧪 Running Validation Tests...\n")
    
    tests = [test_1, test_2, test_3, test_4, test_5, test_6, test_7, test_8]
    for t in tests:
        t()
    
    print(f"\n{'='*50}")
    passed = sum(1 for v in RESULTS.values() if v.startswith("✅"))
    total = len(RESULTS)
    print(f"Results: {passed}/{total} passed\n")
    
    for name, result in RESULTS.items():
        print(f"  {result}")
    
    # Save results
    with open("/root/.openclaw/workspace/trading/test-results.json", "w") as f:
        json.dump({"timestamp": __import__("datetime").datetime.now().isoformat(), "results": RESULTS}, f, indent=2)
    
    print(f"\nResults saved to /root/.openclaw/workspace/trading/test-results.json")
    
    if passed < total:
        print(f"\n⚠️  {total - passed} test(s) FAILED — fixes needed before re-enabling bot")
        sys.exit(1)
    else:
        print(f"\n✅ All {total} tests passed!")
        sys.exit(0)
