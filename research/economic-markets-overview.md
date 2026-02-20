# Kalshi Economic Data Markets — Overview

*Research Date: February 16, 2026*

---

## Markets Found

### 1. CPI (KXCPI) — ✅ ACTIVE, Best Opportunity
- **See:** [cpi-trading-strategy.md](./cpi-trading-strategy.md) for full analysis
- Monthly frequency, 6 strikes per event
- Good liquidity ($13K-$48K per strike)
- Settles on BLS CPI-U month-over-month change (single decimal)
- **Edge source:** Cleveland Fed inflation nowcast

### 2. GDP (KXGDP) — ✅ ACTIVE, Secondary Opportunity

**Current Event: KXGDP-26APR30 (Q1 2026 GDP)**
- Release: April 30, 2026 (BEA advance estimate)
- 7 strikes from 1.0% to 4.0% (0.5% increments)
- Settles on BEA seasonally adjusted annualized advance estimate (one-decimal)

| Ticker | Strike | Last Price | Yes Bid/Ask | Volume | OI | Liquidity |
|--------|--------|-----------|-------------|--------|-----|-----------|
| KXGDP-26APR30-T1.0 | >1.0% | $0.88 | $0.90/$0.95 | 867 | 421 | $13,219 |
| KXGDP-26APR30-T1.5 | >1.5% | $0.84 | $0.78/$0.91 | 168 | 101 | $19,545 |
| KXGDP-26APR30-T2.0 | >2.0% | $0.82 | $0.81/$0.82 | 1,319 | 715 | $22,039 |
| KXGDP-26APR30-T2.5 | >2.5% | $0.67 | $0.67/$0.72 | 887 | 423 | $15,025 |
| KXGDP-26APR30-T3.0 | >3.0% | $0.60 | $0.55/$0.60 | 643 | 317 | $19,707 |
| KXGDP-26APR30-T3.5 | >3.5% | $0.35 | $0.36/$0.44 | 1,837 | 665 | $22,199 |
| KXGDP-26APR30-T4.0 | >4.0% | $0.25 | $0.26/$0.33 | 503 | 354 | $32,381 |

**Market-implied GDP distribution:**
- Mode: ~2.0-2.5% (most probable range)
- Mean: ~2.8% 
- ~90% chance > 1.0%, ~82% chance > 2.0%, ~60% chance > 3.0%

**Edge sources for GDP:**
- Atlanta Fed GDPNow model (very accurate, updated frequently)
- NY Fed Nowcast
- Both are free and public
- GDP nowcasts improve significantly as quarter progresses

**Assessment:** Similar framework to CPI — use GDPNow vs. market-implied distribution. However:
- Only 4 events per year (quarterly)
- Release is ~1 month after quarter ends (more time for data)
- GDPNow is more widely followed by institutional traders
- **Lower priority than CPI** but worth monitoring

### 3. Federal Funds Rate (KXFED) — ✅ ACTIVE, Different Strategy Needed

**Multiple events open** for future FOMC meetings (e.g., KXFED-27APR for April 2027)
- Very long-dated (some extend 12+ months out)
- Enormous liquidity (>$750K per strike!)
- Strikes in 25bp increments (matching Fed's rate decision grid)
- **Very efficient market** — CME FedWatch tool and futures already price this

**Assessment:** 
- Markets are highly efficient (institutional-dominated)
- Edge is minimal — Fed funds futures are the most liquid rates market in the world
- **Not recommended** for our strategy — too efficient, no Cleveland-Fed-style edge

### 4. NFP/Jobs (KXNFP) — ❌ NO OPEN MARKETS
- Series exists but no currently open events
- May be seasonal or they've paused the market

### 5. PPI (KXPPI) — ❌ NO OPEN MARKETS
- No open events found

### 6. Retail Sales (KXRET) — ❌ NO OPEN MARKETS
- No open events found

### 7. Unemployment (various tickers) — ❌ NO OPEN MARKETS
- KXU3MAX exists (max unemployment before 2030) but it's a long-dated prediction, not monthly data

### 8. Recession (KXRECESSION) — ❌ NO OPEN MARKETS

---

## Priority Ranking for Our Trading Strategy

| Rank | Market | Frequency | Edge Source | Estimated Edge | Liquidity | Priority |
|------|--------|-----------|------------|---------------|-----------|----------|
| 1 | **KXCPI** | Monthly (12/yr) | Cleveland Fed Nowcast | 3-8% | Good | **HIGH** |
| 2 | **KXGDP** | Quarterly (4/yr) | Atlanta Fed GDPNow | 2-5% | Moderate | **MEDIUM** |
| 3 | KXFED | Per FOMC (8/yr) | CME FedWatch (no edge) | ~0% | Excellent | **LOW** |
| 4-8 | NFP/PPI/Retail/etc | N/A | N/A | N/A | N/A | **N/A** |

---

## Recommended Approach

### Phase 1 (Now): CPI Only
- Focus exclusively on KXCPI markets
- Build the nowcast-monitoring infrastructure
- Trade February 2026 CPI as first live trade
- Paper trade March if Feb doesn't present clear edge

### Phase 2 (Q2 2026): Add GDP
- After proving CPI strategy, extend to GDP
- Monitor Atlanta Fed GDPNow vs. KXGDP pricing
- Q1 GDP release (Apr 30) would be first live GDP trade

### Phase 3 (Future): Monitor for New Markets
- Check monthly if Kalshi adds NFP, PPI, or other economic data markets
- These would be the most interesting additions — less efficient than Fed funds
- NFP in particular would be excellent (monthly, hard to forecast, high retail interest)

---

## Key API Endpoints for Monitoring

```
# CPI markets (current)
GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXCPI&status=open&with_nested_markets=true

# GDP markets
GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXGDP&status=open&with_nested_markets=true

# Fed rate markets  
GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXFED&status=open&with_nested_markets=true

# Check for new economic series
GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXNFP&status=open
GET https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXPPI&status=open
```
