# Intraday Pricing Patterns - Kalshi Weather Markets

*Research date: Feb 16, 2026*

## Market Structure & Timing

### Trading Hours
- Markets open: **10:00 AM ET** (day before the settlement date, typically)
- Markets close: **11:59 PM ET** on the settlement date
- New day's markets created: ~5:30-6:30 AM ET each day
- Settlement: Next morning 7-8 AM ET when NWS CLI publishes

### Weather Data Release Schedule (Key Price Catalysts)

| Time (ET) | Data Release | Impact |
|-----------|-------------|--------|
| Continuous | METAR observations (hourly + special) | Real-time temp updates |
| 4-5 AM | NWS morning forecast discussion | Updated forecast narrative |
| ~6 AM | NWS CLI previous day report | Settles previous day's markets |
| 6-7 AM | Morning model runs (GFS, NAM, HRRR) | Multi-day forecast updates |
| ~10 AM | NWS day forecast update | Refined same-day forecast |
| 12-1 PM | Afternoon model runs begin arriving | Updated guidance |
| 2-5 PM | Peak temperature window (most cities) | Real high temp often reached |
| 6 PM | NWS evening forecast discussion | Next day outlook |

## Hypothesized Mispricing Windows

### 1. Early Morning (6-9 AM ET) — HIGHEST EXPECTED EDGE
- Markets just opened or very thin
- Overnight model runs not yet fully digested by market
- Retail traders haven't engaged yet
- **Hypothesis**: Longshot brackets overpriced due to wider uncertainty being priced in, but morning models already constraining the range

### 2. Late Morning (10 AM - 12 PM ET) — MODERATE EDGE
- First wave of retail trading
- Some informed traders entering
- Forecast models converging but market may lag

### 3. Afternoon (2-5 PM ET) — CONFIRMATION EDGE (Same-Day)
- For same-day markets: actual temperatures are being recorded
- METAR data confirms or denies bracket outcomes
- Rapid price corrections as reality matches/mismatches prices
- Best window for our "intraday_certainty" tier

### 4. Evening (6-11 PM ET) — THIN MARKETS
- Lower volume, wider spreads
- Good for next-day positioning if evening model runs shift forecasts

## Observed Spread Data (From Live API, Feb 17 2026 NYC Markets)

| Bracket | Yes Bid | Yes Ask | Spread | Volume | Open Interest |
|---------|---------|---------|--------|--------|--------------|
| 48-49° (peak bracket) | 25¢ | 26¢ | 1¢ | 2,427 | 1,789 |
| 44-45° | 19¢ | 20¢ | 1¢ | 957 | 910 |
| 52°+ (tail) | 4¢ | 5¢ | 1¢ | 4,677 | 2,111 |

**Key observations:**
- Bid-ask spreads are typically **1¢** across all brackets — very tight
- Tail/longshot brackets (≤5¢ or ≥95¢) show **higher volume** than mid-range brackets
- Liquidity (in dollar terms) is $5k-14k per bracket

### Spread Patterns by Price Range
- **2-10¢ brackets**: 1¢ spread (50-100% effective spread on 2¢ contracts!)
- **10-25¢ brackets**: 1¢ spread (4-10% effective spread)
- **25-50¢ brackets**: 1¢ spread (2-4% effective spread)
- **Peak brackets (40-60¢)**: 1¢ spread, deepest liquidity

## Data Collection Plan

### What to Track
1. **Snapshot every 30 min**: For each active weather market, record:
   - All bracket yes_bid, yes_ask, last_price
   - Volume, open_interest
   - Current METAR temp at settlement station
   - Current NWS forecast high/low
   - Timestamp

2. **Settlement outcome**: Record actual NWS CLI settlement value

3. **Model forecast evolution**: Track NWS point forecast changes over time

### Implementation
```
Schedule: Every 30 minutes, 6 AM - midnight ET
Duration: Minimum 30 days (ideally 60-90 for seasonal variety)
Storage: SQLite table with columns:
  - timestamp, event_ticker, bracket_ticker
  - yes_bid, yes_ask, last_price, volume, open_interest
  - metar_temp_f, forecast_high, forecast_low
  - hours_to_settlement
```

### Analysis After Collection
1. **Edge decay curve**: Plot our model's predicted probability vs market price at different times-to-settlement
2. **Volume patterns**: When does most volume trade? Are we competing with bots at those times?
3. **Price correction speed**: How fast do prices adjust after new METAR observations?
4. **Optimal entry time**: When is the gap between our probability and market price largest?

### Expected Timeline
- Week 1-2: Collection, initial patterns
- Week 3-4: Statistical analysis, strategy refinement
- Ongoing: Live monitoring and adaptation
