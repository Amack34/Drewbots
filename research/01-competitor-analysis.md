# Kalshi Competitor & Strategy Analysis
*Research Date: Feb 15, 2026*

## How Top Prediction Market Traders Win

### 1. Information Speed Advantage
The #1 edge in prediction markets is **being faster than the market**. Top traders:
- Use automated feeds (weather APIs, sports score APIs, economic data releases)
- Have scripts that place orders within seconds of new information
- Monitor primary data sources, not secondary reporting

### 2. Market Making (Providing Liquidity)
Market makers profit by:
- Posting both YES and NO limit orders with a spread (e.g., buy YES at 45¢, sell YES at 55¢)
- Earning the spread on every fill
- Kalshi uses **quadratic fees** (fee_type: "quadratic"), meaning fees are lower on extreme prices and higher near 50¢
- Fee formula: `fee = min(price, 1-price) * fee_multiplier * some_factor`
- This means market making is most profitable on markets near the extremes where fees are minimal

### 3. Calibration Exploitation
Academic research (Strumpf, Rhode) consistently shows:
- Prediction markets are well-calibrated overall but have **known biases**
- **Favorite-longshot bias**: Events priced at 90%+ resolve YES slightly less often than price implies; events at 5-10% resolve YES more often
- This creates a systematic edge: **sell extreme YES (95¢+), buy extreme NO (5¢-)**
- The effect is small (~2-5%) but consistent

### 4. Cross-Platform Arbitrage
- Kalshi is CFTC-regulated (US), Polymarket is crypto-based (non-US focus)
- Same events can be priced differently due to different user bases
- Political markets historically showed biggest cross-platform divergences
- Key challenge: Kalshi uses USD, Polymarket uses USDC; settlement timing differs

### 5. Category Specialization
Top traders specialize in ONE category and develop deep expertise:
- **Weather specialists**: Use NWS/ECMWF models, understand microclimate effects
- **Sports specialists**: Use advanced stats models (KenPom for basketball, etc.)
- **Political specialists**: Follow polling aggregates, early voting data
- **Financial specialists**: Trade around scheduled data releases (CPI, NFP, FOMC)

## Kalshi Platform Specifics (from API analysis)

### Market Structure
- Binary markets: YES/NO at $1.00 notional
- Prices in cents (1-99)
- Mutually exclusive markets (MECNET collateral): only need to post collateral for worst-case loss across the set
- Settlement: most markets auto-settle within 300 seconds of determination
- Early close conditions on many markets (sports end when game ends)

### Categories Available (from series data)
- **Climate & Weather**: Daily high/low temps (NYC, Boston, Miami, Philly, DC, Atlanta, Chicago), rain, snow, hurricanes
- **Sports**: NBA, NFL, NCAA basketball, soccer, esports, NHL
- **Entertainment**: Spotify charts, Oscars, Netflix rankings, Rotten Tomatoes scores
- **Financials**: WTI oil, forex (USD/JPY, EUR/USD), Treasury yields, S&P 500, Bitcoin, NASDAQ
- **Politics**: Elections, cabinet exits, legislation
- **Economics**: CPI, jobs, gas prices, recession probability
- **Crypto**: Airdrops, token prices

### Fee Structure
- Quadratic fee type with multiplier of 1x
- Fees favor trading at extreme prices (near 0¢ or 100¢)
- This is important: it means the edge in **capturing small moves at extremes is larger** because fees eat less of your profit

## Key Insight from Koleman Strumpf Interview
> "2024 was a huge vindication for the markets. Nobody came close to the markets."

Markets are excellent at aggregating info, but they can be temporarily wrong when:
1. News breaks and takes time to price in
2. Recreational traders pile into one side (sentiment bias)
3. Low-liquidity markets where one large order moves price significantly

## Actionable Takeaways for Drew ($20 bankroll)
1. **Start with weather** — most predictable category, daily resolution, high volume
2. **Use free weather APIs** to get an info edge before market prices update
3. **Avoid 50/50 markets** — the fee burden is highest there
4. **Target markets priced 80-95¢ or 5-20¢** — where you can be confident AND fees are low
5. **Build to market making** once bankroll grows — post limit orders on both sides
