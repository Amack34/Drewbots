# Exchange Tricks & Countermeasures
## How Prediction Markets Extract Money from Traders and Bots

*Researched: 2026-02-16 | Focus: Kalshi, with comparisons to Polymarket, PredictIt, Betfair*

---

## 1. Fee Structure Tricks

### Kalshi's Fee Model
Kalshi charges **transaction fees on expected earnings**, not on trade value. The full fee schedule is at [kalshi.com/docs/kalshi-fee-schedule.pdf](https://kalshi.com/docs/kalshi-fee-schedule.pdf) (PDF, titled "Fee Schedule for Feb 2026 - 2.5.26 Update").

**Key fee components:**
- **Taker fees**: Charged when you take liquidity (match a resting order)
- **Maker fees**: Some markets charge fees even for providing liquidity (resting orders). These are only charged when the order actually executes, not on cancellation.
- **Settlement**: Winning contracts pay out $1.00 minus any applicable fees. No separate settlement fee is explicitly listed, but fees are baked into execution.
- **No withdrawal fees** mentioned in help docs, but deposit methods may have bank-side costs.
- **Some markets have special/different fee rates** — elections, major sporting events, awards ceremonies often have altered fee structures.

### Hidden Costs That Eat Small Edges

1. **Fee on expected earnings, not notional**: If you buy YES at 90¢ expecting to earn 10¢, the fee is calculated on that 10¢ expected profit, not the 90¢ you paid. This means fees are a **much larger percentage of your actual edge** than they appear.
   - Example: Buy YES at 95¢, true probability 97%. Expected profit = 2¢. If fee is even 1¢, that's **50% of your edge gone**.

2. **Maker fees are a trap for bot strategies**: Many bot strategies rely on being the maker (posting limit orders). If maker fees exist on a market, your spread-capture strategy loses a chunk of profit on every fill.

3. **Round-trip cost**: You need to account for fees on both entry AND exit if you're trading before settlement. Buying at 50¢ and selling at 55¢ means fees on both transactions.

4. **Minimum contract value = 1¢**: Contracts trade in 1¢ increments. This means the minimum spread is 1¢, and fees can easily be 30-50%+ of a 1-2¢ edge.

### Fee Math for High-Frequency Small-Profit Trades

| Edge per trade | Fee estimate | Net after fees | Fee as % of edge |
|---|---|---|---|
| 5¢ | ~1.5¢ | 3.5¢ | 30% |
| 3¢ | ~1¢ | 2¢ | 33% |
| 2¢ | ~0.7¢ | 1.3¢ | 35% |
| 1¢ | ~0.5¢ | 0.5¢ | 50% |

**Conclusion**: Edges under 3¢ are extremely difficult to profitably trade after fees. The exchange structurally discourages high-frequency small-edge trading.

### Comparison: Other Exchanges
- **Polymarket**: No trading fees (as of recent), makes money through spread and market maker arrangements. Much more bot-friendly for small edges.
- **PredictIt**: 10% fee on profits + 5% withdrawal fee. Brutal for any strategy. A 10¢ profit becomes 9¢ after profit fee, then 8.55¢ after withdrawal.
- **Betfair**: Commission on net profit per market (2-5% for most users, can be reduced with volume). More favorable for active traders than PredictIt.

---

## 2. Market Maker / Exchange Tactics

### Does Kalshi Run Its Own Market Makers?

Kalshi explicitly states: **"You are always trading against another member of the platform, not the exchange itself."** They operate a neutral exchange model.

However, Kalshi has a **formal Market Maker Program** that is:
- "Highly selective"
- Requires "stringent criteria" including financial resources, experience, and business reputation
- Offers **reduced fees, different position limits, and enhanced access** (including higher API tiers)
- Market makers must maintain 98% availability per 1-hour increment on covered products
- Covers a huge range of products: stock indices, crypto, sports, and more

**What this means for us:**
- Professional market makers have **lower fees** than us
- They have **higher API rate limits** (Premier/Prime tiers)
- They have **larger position limits**
- They are required to provide liquidity, meaning their orders are likely the ones we see on the book
- **They are NOT the exchange**, but they have structural advantages we don't

### Order Matching: Price-Time Priority

Kalshi uses a standard **price-time priority** (FIFO) matching engine:
- Best price gets filled first
- At the same price, first order placed gets filled first
- This is standard and fair, but it means market makers who are faster (better API tiers, co-location advantages) get priority at the same price

### Spoofing and Layering

- No public evidence of spoofing on Kalshi specifically
- As a CFTC-regulated exchange, spoofing is illegal (Dodd-Frank Act)
- However, prediction markets are newer and less surveilled than traditional futures markets
- **Practical concern**: Large orders that appear and disappear quickly on the order book could be spoofing, but could also be legitimate market makers adjusting quotes
- The order book shows depth, which could theoretically be exploited by sophisticated players

### Stop Hunting

- Kalshi does not appear to offer stop-loss orders natively
- Without stop orders, traditional stop-hunting doesn't apply
- However, if you manually set price alerts and react, large players could push prices to trigger your manual stops

---

## 3. Settlement Manipulation Risk

### Weather Markets Settlement (Critical for Our Bot)

**Settlement source**: National Weather Service (NWS) Daily Climate Report — **this is the ONLY source**.

**Key details:**
- Apps like AccuWeather, iOS Weather, Google Weather **do NOT determine outcomes**
- Settlement uses **local standard time**, not daylight saving time. During DST, the high temp is recorded between 1:00 AM and 12:59 AM local time the following day
- The final climate report is typically released the **following morning**
- Market determination may be **delayed** if:
  - High temperature is inconsistent with 6-hr or 24-hr highs reported by METAR
  - Final NWS report high is lower than preliminary reports

**Settlement gaming risks:**
1. **Data timing**: The NWS report comes out the morning after. If you know how NWS reports are compiled vs. real-time station data, you might have an information edge
2. **Station-specific quirks**: NWS climate reports come from specific weather stations (usually at airports: JFK, ORD, LAX, etc.). Microclimates, urban heat islands, and station-specific calibration matter
3. **Preliminary vs. final reports**: Preliminary data may differ from final. If you trade based on preliminary data, the final settlement could surprise you

### Has There Been Settlement Controversy?

- No major public scandals, but the help page explicitly addresses the fact that settlement can be delayed when data is inconsistent
- The DST timing issue is a known source of confusion — many traders likely don't realize the measurement window shifts
- This is actually an **edge for informed traders**: if most people think "midnight to midnight" but it's actually 1AM to 12:59AM during DST, you can exploit mispricing

### Other Markets Settlement

- Each market has specific rules linked in the market page
- Political markets: Typically settled by official results (AP call, certification, etc.)
- Financial markets: Settled by official closing prices from specified sources
- Crypto: Settled by specific exchange prices at specific times

---

## 4. Liquidity Traps

### Wide Bid-Ask Spreads

- Weather markets and niche markets often have **3-5¢+ spreads**
- Popular markets (elections, major crypto) can have 1-2¢ spreads
- Wide spreads mean you lose money the moment you enter a position if you're taking liquidity
- **Rule of thumb**: If your edge is smaller than the half-spread, don't take liquidity

### Phantom Liquidity

- Market makers are required to maintain 98% availability on covered products
- However, they can **adjust prices and sizes** at any time
- Fast market makers can pull quotes before you can hit them (especially if you're on Basic tier with 10 writes/second)
- The order book depth you see is **not guaranteed to be there when your order arrives**

### Thin Markets and Self-Impact

- Many weather markets for specific cities/dates have very thin order books
- Placing a 100-contract order in a thin market can easily move the price 2-3¢ against you
- **This is our biggest practical risk**: We need to size our orders relative to book depth

### Slippage on Limit Orders

- Limit orders on Kalshi are safe from slippage by definition (you get your price or better)
- But limit orders may **not fill** if the market moves away
- Market orders (quick orders) will fill at the best available price, which may be worse than expected in thin books

---

## 5. Information Asymmetry

### API Rate Limit Tiers — The Big Disadvantage

| Tier | Read | Write | How to Get |
|---|---|---|---|
| **Basic** | 20/sec | 10/sec | Signup |
| **Advanced** | 30/sec | 30/sec | Application form |
| **Premier** | 100/sec | 100/sec | 3.75% of exchange volume/month |
| **Prime** | 400/sec | 400/sec | 7.5% of exchange volume/month |

**We are on Basic tier** (10 writes/second). This means:
- We can place at most 10 orders per second
- Market makers on Prime can place **40x more orders per second**
- They can update quotes, cancel and replace orders, and react to news much faster
- **We already hit 429 rate limits** — this confirms we're at a structural disadvantage

**To get Advanced**: Fill out https://kalshi.typeform.com/advanced-api — **we should do this immediately**.

### Do Market Makers See Pending Orders?

- No evidence of front-running or order preview
- Kalshi is CFTC-regulated, which prohibits such practices
- However, market makers can see the public order book and react faster than us
- They can observe our order patterns over time and adapt

### Data Speed Advantages

- Market makers likely use direct weather data feeds (NWS API, METAR, etc.) with lower latency
- For financial/crypto markets, they likely have direct exchange feeds
- We're parsing the same public data but may be slower due to rate limits on both Kalshi API and data source APIs

---

## 6. Psychological Tricks

### Gamification

- **Leaderboard**: Kalshi has a public leaderboard showing top traders. This encourages:
  - Overtrading to climb rankings
  - Risk-taking to get on the board
  - Competitive behavior that leads to poor risk management

- **Market variety**: Hundreds of markets on everything from weather to Spotify streams. This encourages browsing and impulse trading on markets you know nothing about.

- **Quick Orders**: The "quick order" (market order) feature makes it easy to impulse trade without thinking about the spread or fees.

### Near-Miss Psychology in Bracket Markets

- Weather markets with temperature brackets (e.g., "55-59°F") create near-miss scenarios
- If the temp comes in at 60°F and you had the 55-59 bracket, you feel like you "almost won"
- This encourages doubling down on similar bets next time
- **Bracket markets are the exchange's best friend**: They split a single outcome into multiple markets, each with its own spread and fees

### Loss Aversion Exploitation

- Contract prices are 0-100¢, making losses feel like "just cents"
- $20 account feels like "play money"
- The interface emphasizes potential payout, not risk

---

## 7. Bot-Specific Traps

### Automated Trading Policy

- Kalshi **explicitly allows** API-based automated trading
- They have a **Developer Agreement** that governs API usage
- No evidence of disadvantaging automated traders specifically
- However, the tiered rate limit system naturally disadvantages smaller automated traders

### Detection and Throttling

- Rate limits are the primary control mechanism
- 429 errors we've experienced are standard rate limiting, not bot-specific punishment
- Batch APIs exist (BatchCreateOrders, BatchCancelOrders) — cancels count as only 0.2 transactions each
- **Key insight**: Use batch operations to maximize our limited rate budget

### Adversarial Market Making Against Bots

- Sophisticated market makers can detect bot patterns:
  - Regular interval order placement
  - Systematic order sizes
  - Predictable reaction to price changes
  - Always buying/selling at the same levels
- They can then **adjust their quotes** to extract value from predictable bot behavior
- Example: If our bot always buys YES when price drops below a threshold, a market maker can place a sell just above that threshold and immediately buy back cheaper

### Terms of Service Risks

- API usage requires agreeing to the Developer Agreement
- Kalshi can downgrade API tier for lack of activity
- They can also presumably restrict access for abuse or manipulation
- "Technical competency" is required for Premier/Prime — they evaluate your practices

---

## 8. Countermeasures

### Fee Optimization

1. **Only trade edges > 3¢**: After fees, anything less is marginal
2. **Use limit orders exclusively**: Avoid quick/market orders that cross the spread AND pay taker fees
3. **Focus on markets with lower fees**: Check each market's specific fee structure
4. **Consider maker vs taker**: If maker fees exist, factor them in. If no maker fee, always be the maker
5. **Trade before settlement, not to settlement**: Capture price moves, avoid settlement fee structures

### Order Execution Tactics

1. **Always use limit orders**: Never cross the spread unless edge is very large
2. **Post-only orders if available**: Ensure you're always the maker
3. **Use batch APIs**: BatchCancelOrders counts as 0.2 per cancel — use this for mass quote updates
4. **Stagger order sizes**: Don't always use the same lot size (avoids pattern detection)
5. **Add randomized delays**: Don't place orders at exact intervals (avoids detection as a bot)

### Detecting Manipulation

1. **Watch order book depth changes**: If large orders appear and disappear rapidly, potential spoofing
2. **Monitor spread changes**: Sudden spread widening before data releases = informed traders positioning
3. **Track fill rates**: If your limit orders are consistently being missed by 1¢, someone may be front-running your pattern
4. **Compare order book to trade tape**: If there are trades at prices not on the visible book, something's off

### Optimal Order Sizing

1. **Size relative to book depth**: Never more than 10-20% of visible depth at your price level
2. **For weather markets**: Start with 5-10 contracts per order, scale up only as liquidity confirms
3. **Iceberg approach**: Break large orders into smaller pieces over time
4. **Minimum viable size**: With $20 account, we're naturally limited — this is actually protective

### Limit vs Market Orders — Decision Framework

| Situation | Order Type | Reasoning |
|---|---|---|
| Edge > 5¢, high confidence | Limit (aggressive, near best ask) | Capture edge while controlling cost |
| Edge 3-5¢ | Limit (at mid or maker side) | Must avoid taker fees to preserve edge |
| Edge < 3¢ | Don't trade | Fees eat the edge |
| Time-sensitive (data release) | Limit (aggressive) | Speed matters but don't market order |
| Building position slowly | Limit (passive) | Let the market come to you |
| Exiting emergency | Market/Quick order | Acceptable to pay spread to exit risk |

### Reading the Order Book for Manipulation Signals

1. **Stacked book with no trades**: Lots of resting orders but no actual fills = display liquidity, not real liquidity
2. **Asymmetric depth**: Much more depth on one side = potential bluff or legitimate flow
3. **Rapid quote updates**: If the best bid/ask updates many times per second, active market maker is present
4. **Gap in the book**: No orders for several cents = potential for price jumps when order flow arrives
5. **Size at round numbers**: Large orders at 50¢, 25¢, 75¢ are often market maker anchors, not directional bets

### Immediate Action Items

1. **Apply for Advanced API tier** at https://kalshi.typeform.com/advanced-api (3x our current rate limits)
2. **Use batch cancel API** to save rate limit budget (0.2 per cancel vs 1.0)
3. **Implement randomized timing** in order placement to avoid pattern detection
4. **Set minimum edge threshold at 3¢** — don't trade anything smaller
5. **Track per-market fees** and only trade on markets where our edge exceeds fees
6. **Study NWS reporting** — understand exactly which station, what time window, and DST effects for each city we trade
7. **Monitor our own fill rates** to detect if we're being adversarially traded against

---

## Summary: The House Edge on Kalshi

| Revenue Source | Impact on Us | Mitigation |
|---|---|---|
| Transaction fees on expected earnings | 30-50% of small edges | Only trade edges > 3¢ |
| Maker fees on some markets | Reduces spread-capture profits | Check per-market fee structure |
| Tiered rate limits | 40x disadvantage vs top tier | Apply for Advanced tier |
| Market maker information advantages | Faster data, better API access | Focus on markets where speed matters less (weather) |
| Bid-ask spreads | Immediate loss on entry | Always use limit orders, be the maker |
| Bracket market structure | Splits edge across multiple markets | Focus on the most likely bracket |
| Psychological design | Encourages overtrading | Stick to systematic, rules-based trading |

**Bottom line**: Kalshi is not predatory by exchange standards, but the fee structure and rate limit tiers create a significant structural disadvantage for small automated traders. Our best strategy is to focus on markets where our **analytical edge** (weather forecasting) matters more than speed or capital advantages, use limit orders exclusively, and apply for higher API tiers as soon as possible.
