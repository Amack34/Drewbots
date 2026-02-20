# Trading Bot Validation Tests

8 tests required before bot goes live. All must pass.

## Test 1: Profit Rule Position-Close

**What it tests:** When profit rule triggers, the bot correctly CLOSES the position (action="sell") instead of adding to it.

- **Input:** Paper portfolio with 1 NO position (e.g., NYC high >80°F, qty=5, avg_price=0.15). Current price drops to 0.05 (profit target hit).
- **Expected:** Bot calls `action="sell"` with `side="no"` to close. Position count goes to 0. P&L reflects realized gain.
- **Pass/Fail:** PASS if position is fully closed and no new position is opened. FAIL if position size increases or action="buy" is called.
- **Why critical:** The bug that took the bot offline — profit rule used wrong API call, doubled position instead of closing.

## Test 2: NO Position P&L Calculation

**What it tests:** P&L is correctly calculated for NO positions (which have inverted economics).

- **Input:** NO position: bought 10 contracts at $0.20. Event settles NO (we win).
- **Expected:** P&L = 10 × ($1.00 - $0.20) = $8.00 profit. For loss scenario: event settles YES → P&L = -10 × $0.20 = -$2.00.
- **Pass/Fail:** PASS if P&L matches expected for both win and loss scenarios. FAIL if P&L formula treats NO like YES.
- **Why critical:** `position: -N` = LONG N NO contracts (NOT short). Misreading this breaks all P&L.

## Test 3: Sanity Check Enforcement

**What it tests:** Sanity check BLOCKS trades (not just logs warnings) when forecast vs actual diverges beyond threshold.

- **Input:** NWS forecast: 75°F. Current METAR reading: 82°F (7°F divergence, above 3°F threshold). Bot attempts to place trade.
- **Expected:** Trade is REJECTED. No API call to Kalshi. Log entry shows "sanity check blocked trade."
- **Pass/Fail:** PASS if trade is blocked and no order is placed. FAIL if trade executes with only a log warning.
- **Why critical:** "A safety check that logs but doesn't block is MORE dangerous than no check."

## Test 4: Capital Cap Checks

**What it tests:** Bot respects maximum capital allocation per trade and total exposure limits.

- **Input:** Account balance: $153. Capital cap: 10% per trade ($15.30). Bot wants to buy 200 NO contracts at $0.10 ($20 total).
- **Expected:** Order is reduced to 153 contracts ($15.30) or rejected entirely.
- **Pass/Fail:** PASS if order size is capped or rejected. FAIL if full $20 order goes through.
- **Secondary check:** Total open exposure across all positions must not exceed defined limit.

## Test 5: Dedup Logic

**What it tests:** Bot does not place duplicate orders for the same market/bracket within the same trading cycle.

- **Input:** Bot generates signal for NYC high 75-79°F NO at $0.25. Signal fires again 5 minutes later for same bracket (same cycle).
- **Expected:** Second signal is deduplicated. Only one order exists.
- **Pass/Fail:** PASS if only 1 order placed. FAIL if 2 orders placed for same bracket in same cycle.
- **Edge case:** Different cycles (AM vs PM) should allow re-entry if conditions changed.

## Test 6: Lock-in Signal Handling

**What it tests:** Lock-in signals (METAR confirms temperature is already in/past a bracket with high confidence) trigger correct YES buys with reduced edge threshold (1% vs normal 15%).

- **Input:** METAR shows current temp 85°F at 2pm. Market: "NYC high >82°F" priced at $0.95 (YES). Lock-in confidence: high.
- **Expected:** Bot buys YES at $0.95 (1% edge acceptable for lock-in). Normal 15% edge rule is bypassed.
- **Pass/Fail:** PASS if lock-in signal triggers YES buy with reduced edge threshold. FAIL if lock-in is ignored or uses standard 15% edge.
- **Safety:** Lock-in must verify data is for CORRECT DATE (not yesterday's temp for tomorrow's market).

## Test 7: Cut-Losers Mechanics

**What it tests:** Bot exits losing positions when loss exceeds defined threshold.

- **Input:** NO position bought at $0.15. Current price rises to $0.45 (we're losing). Cut-loss threshold: 100% of entry (loss > $0.15 per contract).
- **Expected:** Bot closes position via `action="sell"`. Realized loss is logged.
- **Pass/Fail:** PASS if position is closed and loss is booked. FAIL if position is held or averaged down.
- **Verify:** Uses `action="sell"` (not `action="buy"` which would ADD to position).

## Test 8: Rolling Profit Rule Trigger

**What it tests:** Rolling profit tracking correctly identifies when cumulative session profit hits target and triggers appropriate action (partial close or full close).

- **Input:** 3 open NO positions with combined unrealized P&L of +$12. Rolling profit target: $10.
- **Expected:** Bot triggers profit-taking. At minimum, logs the trigger event. If configured for auto-close, closes most profitable position first.
- **Pass/Fail:** PASS if rolling profit trigger fires at correct threshold. FAIL if threshold is never checked or fires at wrong value.
- **Verify:** Trigger resets after profit-taking (doesn't fire repeatedly on same P&L).

---

## Execution Plan

1. All tests run against paper_trade.py (never live)
2. Each test is independent — can run in any order
3. Tests 1 and 7 are highest priority (both involve position closing, the original bug)
4. Need access to: bot.py, paper_trade.py, kalshi_trader.py to implement
5. Mock Kalshi API responses for deterministic testing
6. 48-hour paper trading minimum after all 8 pass before going live
