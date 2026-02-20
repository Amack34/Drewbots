# Counterparty Analysis - Kalshi Weather Markets

*Research date: Feb 16, 2026*

## Market Participants

### Who Trades Weather on Kalshi?

**1. Retail Traders (Estimated 60-70% of participants)**
- Weather enthusiasts and hobbyists
- Sports bettors looking for new markets
- Crypto/meme stock crowd seeking novelty
- Tend to exhibit strong **longshot bias** (overpay for unlikely outcomes)
- Characteristics: trade during peak hours (10 AM - 10 PM ET), smaller positions

**2. Algorithmic/Bot Traders (Estimated 20-30%)**
- Weather model-based bots (like ours)
- Market-making bots providing liquidity
- Arbitrage bots watching for stale prices
- Characteristics: trade 24/7, react quickly to data, tight spreads

**3. Institutional/Professional (Estimated 5-10%)**
- Weather derivatives traders looking for retail markets
- Prop trading firms testing prediction market strategies
- Characteristics: larger positions, sophisticated models

## Volume & Liquidity Analysis

### Observed Data (Feb 16-17, 2026 NYC Markets)

| Metric | Value |
|--------|-------|
| Volume per bracket (typical) | 500-5,000 contracts/day |
| Open interest per bracket | 300-2,500 contracts |
| Liquidity per bracket | $2,000-$14,000 |
| Total event volume (all brackets) | ~15,000-25,000 contracts/day |
| Bid-ask spread | 1¢ (universal) |

### Volume by City (Relative)
- **NYC**: Highest volume (~100% baseline) — most liquid market
- **MIA**: ~60-70% of NYC volume
- **PHI**: ~40-50% of NYC volume
- **DC**: ~30-40% of NYC volume
- **ATL**: ~25-35% of NYC volume
- **BOS**: ~20-30% of NYC volume (newest market, started Feb 2026)

### Liquidity Characteristics
- The 1¢ bid-ask is maintained by market makers (likely Kalshi's own or contracted MMs)
- Depth at best bid/ask is typically 50-200 contracts
- Slippage on orders >100 contracts can be 1-2¢
- Markets are thin overnight (12-6 AM ET)

## Known Bot Strategies in Weather Prediction Markets

### 1. Model-Based Directional (Our Strategy)
- Use NWS/ensemble forecasts to estimate bracket probabilities
- Buy underpriced, sell overpriced brackets
- Edge: Better probability estimation than retail

### 2. Market Making
- Provide liquidity on both sides
- Earn spread while hedging across correlated brackets
- Challenge: 1¢ spread is already very tight

### 3. METAR-Reactive Trading
- Monitor real-time METAR feeds
- As actual temps approach/exceed bracket boundaries, rapidly adjust positions
- Fastest bots with lowest latency win here

### 4. Ensemble Spread Exploitation
- Track divergence between weather model ensembles (GFS, ECMWF, NAM)
- When models disagree, implied volatility should be higher
- Trade tail brackets when models converge (tails overpriced)

### 5. Cross-City Correlation
- Weather systems move geographically
- If PHI is already 5° above forecast, NYC (2 hours later in weather system) may follow
- Not many bots exploit spatial correlations

## Longshot Bias Durability

### Why the Edge Exists
1. **Behavioral**: Humans systematically overvalue unlikely outcomes (documented across all betting markets)
2. **Entertainment value**: $5 to potentially win $100 feels exciting
3. **Kalshi's market structure**: Binary brackets create natural longshot opportunities at the tails
4. **Low stakes**: Most traders aren't doing rigorous probability analysis for a few dollars

### Threats to Edge Durability

| Threat | Timeline | Severity | Mitigation |
|--------|----------|----------|------------|
| More bots enter | 6-12 months | Medium | Improve model, add more data sources |
| Kalshi changes structure | Unknown | Low | Diversify to other markets |
| Professional weather traders | Already happening | Medium | Focus on execution speed & data |
| Reduced retail participation | Recession/novelty fades | High | Diversify to non-weather markets |

### Edge Sustainability Assessment
- **Short-term (0-6 months)**: Strong. Weather markets still growing, retail dominant
- **Medium-term (6-18 months)**: Moderate. More bots expected, spreads may tighten on tails
- **Long-term (18+ months)**: Uncertain. Depends on retail growth vs bot sophistication
- **Key indicator**: If tail bracket prices start consistently matching model probabilities, edge is eroding

### How to Monitor Edge Erosion
1. Track our win rate over rolling 30-day windows
2. Compare theoretical edge (model prob - market price) trend over time
3. Watch for decreased volume on tail brackets (indicates informed traders avoiding them)
4. Monitor if bid-ask widens (indicates market makers see less retail flow)
