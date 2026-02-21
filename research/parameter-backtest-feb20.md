# Parameter Backtest - Feb 18-19 (Task F)

**Task:** Backtest new parameters (biases + std_dev) against Feb 18-19 settled data  
**Author:** WorkerBot  
**Date:** Feb 21, 2026  
**Status:** REQUIRES SERVER ACCESS

## Note

**⚠️ LIMITATION:** The weather.db database is on DrewOps' server, not accessible from this worker bot. The analysis below provides the methodology and SQL queries needed. DrewOps will need to run these queries and provide results.

---

## Objective

Quantify how the **new parameters** (from commit 0deb41e) would have performed on Feb 18-19 compared to the old parameters:

### New Parameters
- **HIGH_BIASES:** MIA +5.0, ATL +5.0, NYC +3.0
- **LOW_BIASES:** MIA -6.0, NYC -4.0
- **CITY_STD_FLOOR:** ATL 5.0, MIA 4.5, NYC/DC 3.5, BOS/PHI 2.5

### Old Parameters (for comparison)
- **HIGH_BIASES:** MIA +4.0, ATL +3.0, NYC +3.0
- **LOW_BIASES:** MIA -5.0, NYC -4.0
- **STD_DEV:** 2.0-4.0 based on confidence (floor 1.5)

---

## Key Questions to Answer

1. **ATL B79.5 losses:** How many of the 36 ATL B79.5 losses would the NEW parameters have avoided?
2. **MIA B63.5 losses:** How many of the 32 MIA B63.5 losses would have been avoided?
3. **Overall P&L:** What would the new parameters' P&L have been vs actual?

---

## SQL Queries to Run

### Query 1: Get all Feb 18-19 paper trades with details

```sql
SELECT 
    city,
    bracket,
    side,
    settlement_price,
    entry_price,
    profit_loss,
    edge_pct,
    confidence,
    CASE 
        WHEN settlement_price > entry_price THEN 'LOSS'
        ELSE 'WIN'
    END as outcome
FROM v2_paper_trades
WHERE date(timestamp) IN ('2026-02-18', '2026-02-19')
ORDER BY city, bracket, timestamp;
```

### Query 2: Summary by city/bracket

```sql
SELECT 
    city,
    bracket,
    COUNT(*) as total_trades,
    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as losses,
    SUM(profit_loss) as net_pnl,
    AVG(edge_pct) as avg_edge
FROM v2_paper_trades
WHERE date(timestamp) IN ('2026-02-18', '2026-02-19')
GROUP BY city, bracket
ORDER BY city, net_pnl;
```

### Query 3: ATL specifically - high brackets around 79.5

```sql
SELECT *
FROM v2_paper_trades
WHERE city = 'ATL'
    AND bracket LIKE '%79%'
    AND date(timestamp) IN ('2026-02-18', '2026-02-19')
ORDER BY timestamp;
```

### Query 4: MIA specifically - low brackets around 63.5

```sql
SELECT *
FROM v2_paper_trades
WHERE city = 'MIA'
    AND bracket LIKE '%63%'
    AND date(timestamp) IN ('2026-02-18', '2026-02-19')
ORDER BY timestamp;
```

---

## Expected Analysis (Manual)

For each losing trade, determine:

### Would NEW HIGH_BIAS have changed the signal?

| City | Old Bias | New Bias | Change | Impact |
|------|----------|----------|--------|--------|
| ATL | +3.0 | +5.0 | +2.0 | Higher estimate → less likely to buy YES |
| MIA | +4.0 | +5.0 | +1.0 | Higher estimate → less likely to buy YES |

### Would NEW STD_DEV FLOOR have changed probability?

| City | Old Floor | New Floor | Impact |
|------|-----------|-----------|--------|
| ATL | 1.5 | 5.0 | Wider distribution → lower edge → fewer signals |
| MIA | 1.5 | 4.5 | Wider distribution → lower edge → fewer signals |

### Hypothetical Calculation Example

For an ATL "high 79-80" bracket at $0.30 (YES):
- **Old params:** estimated high = forecast + 3.0, std_dev = 2.0 → P(high≥80) might be 15% → edge = 15% - 30% = -15% → NO TRADE
- **New params:** estimated high = forecast + 5.0, std_dev = 5.0 → P(high≥80) might be 8% → edge = 8% - 30% = -22% → NO TRADE

The new parameters would have been **more conservative**, avoiding some marginal trades that turned into losses.

---

## Manual Estimation (Without Database Access)

Based on DrewOps' notes:
- **36 ATL B79.5 losses** on Feb 18-19
- **32 MIA B63.5 losses** on Feb 18-19

**Hypothetical estimate:**
- With ATL bias +5.0 (vs +3.0), we'd estimate temps 2°F higher
- With ATL std_dev 5.0 (vs ~2.0), probability distributions are much wider
- Estimated reduction: **30-50%** of marginal ATL trades avoided
- Estimated ATL losses avoided: **10-18 trades**
- Estimated MIA losses avoided: **8-16 trades**

**Estimated new P&L improvement:** +$15-30 (from reduced losses)

---

## Recommendation

**NEXT STEP:** DrewOps to run the SQL queries above and provide actual numbers. With real data, I can complete a precise analysis.

Alternatively, if database access is not possible:
- Manually review the 36 ATL and 32 MIA losing trades
- For each, apply the new bias formula: new_estimated = old_estimated + (new_bias - old_bias)
- Recalculate edge with new std_dev floor
- Count how many would have been avoided

---

## Output Format

When results are available, update this file with:

```
ACTUAL RESULTS:
- Total trades: X
- Wins: Y  
- Losses: Z
- Net P&L: $X.XX

ATL ANALYSIS:
- Old params loss count: 36
- New params loss count: X
- Losses avoided: Y (Z%)

MIA ANALYSIS:
- Old params loss count: 32  
- New params loss count: X
- Losses avoided: Y (Z%)

CONCLUSION: [parameters improved / did not help / inconclusive]
```
