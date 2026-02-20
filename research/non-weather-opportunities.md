# Non-Weather Kalshi Opportunities

*Research date: Feb 16, 2026*

## Overview

Surveyed Kalshi API for non-weather markets with potential algorithmic edge. Focus on markets with:
- Quantitative settlement criteria (not subjective)
- Data-driven resolution (public data sources)
- Settlement within 1-4 weeks
- Longshot bias or systematic mispricing potential

## Economics Markets

### CPI (Series: KXCPI)
- **Current events**: Monthly CPI releases (Jan 2026, Feb 2026 active)
- **Settlement**: BLS Consumer Price Index release
- **Structure**: Bracket-style, similar to weather
- **Edge potential**: HIGH
  - Cleveland Fed Nowcast provides real-time CPI estimates
  - Bloomberg consensus vs actual "surprise" is well-studied
  - Similar longshot bias exists (extreme CPI outcomes overpriced)
- **Liquidity**: Moderate (less than weather, but tradeable)
- **Next settlement**: Jan 2026 CPI report (releasing ~Feb 12, 2026 — may have already settled)
- **Data sources**: Cleveland Fed CPI Nowcast, BLS schedule, component data (energy, food)

### GDP (Series: KXGDP)
- **Current events**: Q4 2025 GDP (settling Jan 30, 2026), Q1 2026 (settling Apr 30)
- **Settlement**: BEA advance GDP estimate
- **Edge potential**: MODERATE
  - Atlanta Fed GDPNow provides real-time tracking
  - But markets price in GDPNow relatively efficiently
  - Edge exists in revision estimates (advance vs final)
- **Liquidity**: Lower than CPI
- **Concern**: Quarterly frequency means fewer trades per year

### Initial Jobless Claims (Series: KXJOBLESS)
- **Status**: Appears inactive/historical only (last events from 2022)
- **Not currently tradeable**

## Financial Markets

### S&P 500 (Series: KXINX)
- **Current events**: Daily close price ranges
- **Settlement**: S&P 500 closing price at 4 PM ET
- **Structure**: Price range brackets (e.g., will S&P close in range X-Y?)
- **Edge potential**: LOW-MODERATE
  - Extremely efficient market with billions in derivatives
  - Hard to beat options market pricing with a prediction market
  - Possible edge: Kalshi retail traders may misprice tail events differently than options
- **Liquidity**: Likely high (popular market)
- **Concern**: Competing against the most efficient market in the world

## Political/World Events

### Near-Term Opportunities Spotted
- **Next Pope** (KXNEWPOPE) — Pope selection, active
- **G7 Leader to Leave Next** (KXG7LEADEROUT) — Political event
- **Israel PM** (KXNEXTISRAELPM) — Geopolitical

### Edge Assessment
- Political markets are inherently harder to model
- No reliable "forecast model" equivalent
- Edge comes from information aggregation, not data analysis
- **Not recommended** for our algorithmic approach

## Recommended Non-Weather Expansion: CPI Markets

### Why CPI is the Best Fit

1. **Structural similarity**: Bracket markets, just like weather. Our infrastructure transfers directly.
2. **Data-driven edge**: Cleveland Fed Nowcast is analogous to NWS forecasts — it's public, quantitative, and more accurate than market pricing suggests.
3. **Longshot bias**: Extreme CPI prints (very high or very low) are systematically overpriced, just like extreme weather brackets.
4. **Monthly frequency**: 12 trades/year minimum, more if we trade multiple brackets.
5. **Complementary timing**: CPI releases are monthly events, not daily — fills gaps when weather is quiet.

### CPI Trading Strategy Draft

```
Strategy: Sell overpriced tail brackets on CPI releases
Data sources:
  - Cleveland Fed CPI Nowcast (daily updates)
  - BLS component data (energy, food, shelter)
  - Bloomberg consensus estimates
  - Historical CPI surprise distribution

Entry: 3-5 days before CPI release
Exit: At settlement (or take profit if edge disappears)
Risk: Same as weather — max 10% of bankroll per trade
```

### CPI Data Sources
- **Cleveland Fed Inflation Nowcasting**: https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting
- **BLS CPI Release Schedule**: https://www.bls.gov/schedule/news_release/cpi.htm
- **CPI Component Tracking**: Energy prices (gasoline), food prices, shelter (Case-Shiller lag)

## Other Series Worth Monitoring

| Series | Category | Frequency | Edge Potential | Priority |
|--------|----------|-----------|---------------|----------|
| KXCPI | Economics | Monthly | HIGH | 🟢 Start now |
| KXGDP | Economics | Quarterly | MODERATE | 🟡 Monitor |
| KXINX | Financials | Daily | LOW | 🔴 Skip |
| KXFEDRATE | Economics | 8x/year | MODERATE | 🟡 Research further |

## Next Steps

1. **Immediate**: Build CPI Nowcast tracker — compare Cleveland Fed Nowcast vs Kalshi CPI bracket prices
2. **Week 1**: Backtest CPI longshot bias using historical Kalshi CPI market data
3. **Week 2**: If edge confirmed, build CPI trading module using same infrastructure as weather bot
4. **Ongoing**: Monitor new Kalshi series for data-driven markets
