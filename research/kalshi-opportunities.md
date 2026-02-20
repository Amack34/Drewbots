# Kalshi Market Opportunities Research
*Feb 15, 2026*

## Currently Trading (Weather Bot)
Already automated with signal generator + paper trading:
- **NYC High** (KXHIGHNY): 130K vol, most liquid weather market
- **MIA High** (KXHIGHMIA): 81K vol, 2nd most liquid
- **PHI High** (KXHIGHPHIL): 21K vol
- **DC High** (KXHIGHTDC): 20K vol
- **NYC Low** (KXLOWTNYC): 20K vol
- **ATL High** (KXHIGHTATL): 15K vol
- **MIA Low** (KXLOWTMIA): 11K vol
- **PHI Low** (KXLOWTPHIL): 11K vol
- **BOS High** (KXHIGHTBOS): 5K vol

## New Opportunities to Explore

### 1. GDP (KXGDP) — HIGHEST VOLUME (801K)
- 10 open markets on Q4 2025 GDP growth
- Resolves based on BEA advance estimate
- Example: "GDP > 1.25%" at 95-97¢ (very high confidence)
- **Edge opportunity**: Cheap tail-risk brackets if we can predict GDP surprises
- **Strategy**: Track economic indicators (jobs, retail sales, ISM) for GDP nowcasting
- **Risk**: Monthly/quarterly events, low frequency

### 2. CPI / Inflation (KXCPI) — 11K vol
- Monthly CPI release markets
- "CPI > 0.1%" at 82-83¢, "CPI > 0.3%" at 20-21¢
- **Edge opportunity**: Cleveland Fed Inflation Nowcasting model is public and good
- **Strategy**: Build CPI nowcaster using public data (gas prices, food prices, shelter)
- **Risk**: Monthly events, need to be right on the margin

### 3. Gas Prices (KXGAS*) — Not found in search
- NYC, LA, Chicago, Houston, SF gas price brackets
- Could use GasBuddy API or AAA data for edge
- **Status**: Need to find correct series tickers

### 4. S&P 500 / Stock Index Intraday — Not found
- Kalshi reportedly has intraday S&P 500 bracket markets
- Series tickers unknown — may need browser scraping to find
- **Edge**: Intraday momentum models, VIX correlation
- **Priority**: HIGH if we can find the tickers

### 5. Rain/Snow/Wind — Not found
- Weather beyond temperature — precipitation, wind speed
- Would extend our existing NWS data infrastructure
- **Status**: Need to search for correct series tickers

## Priority Ranking
1. **S&P 500 / Stock Index** — Daily frequency, huge volume potential, quantitative edge possible
2. **CPI Nowcasting** — Monthly but high-conviction plays possible with public data
3. **GDP** — Quarterly, but 800K volume shows massive interest
4. **Gas Prices** — Daily, could use similar surrounding-signal strategy as weather
5. **Extended Weather** (rain/snow) — Low effort to add with existing infrastructure

## Confirmed Daily/Recurring Markets (with tickers)

### Rain Markets — HIGH PRIORITY 🎯
- **KXRAINHOUM** (Rain Houston): 37K vol, 7 markets — "Rain in Houston in Feb?"
  - 23-35¢ range — SWEET SPOT for our strategy
  - NWS precipitation forecasts are public + surrounding city strategy works
- **KXRAINSEAM** (Rain Seattle): 34K vol, 7 markets — "Rain in Seattle in Feb?"
  - 86-92¢ (it always rains in Seattle lol) — look for NO opportunities
- **KXSEASNOWM** (Seattle Snow): 47K vol, 5 markets — "Snow in Seattle in Feb?"
  - 57-60¢ — balanced market, edge possible with NWS snow forecasts

### Treasury/FX Markets
- **KXTNOTED** (10Y Treasury Daily Yield): 841 vol, 10 markets
  - Daily yield above/below brackets — low volume but automatable
- **EURUSD** (EUR/USD Daily Range): Found in series list

### Crypto Intraday
- **KXETH15M** (ETH 15min): 4K vol — "ETH price up in next 15 mins?"
  - 38-39¢ — essentially a coin flip, hard to get edge
- **KXXRPD** (XRP Daily): No volume — skip
- **KXSOLE** (SOL Range): No volume — skip

### NOT Found Yet
- S&P 500 / NASDAQ intraday bracket markets — may be under different tickers
- Gas price daily markets — not in current series

## Priority Ranking (Updated)
1. **Rain/Precipitation** — Same NWS infrastructure, same edge strategy, good volume, sweet-spot pricing
2. **Snow markets** — Extension of weather strategy
3. **CPI Nowcasting** — Monthly but high-conviction
4. **Treasury yields** — Daily, automatable, but low volume currently
5. **Crypto intraday** — Hard to get edge, basically gambling

## Next Steps
- [ ] Add rain/snow to weather bot (NWS has precipitation forecasts)
- [ ] Build precipitation signal generator
- [ ] Paper trade rain markets alongside temperature
- [ ] Build CPI nowcaster for monthly plays
- [ ] Keep searching for S&P 500 intraday tickers
