# CPI Prediction Market Trading Strategy — Kalshi (KXCPI)

*Research Date: February 16, 2026*

---

## 1. Kalshi CPI Market Structure

### Series Overview
- **Series Ticker:** KXCPI
- **Category:** Economics
- **Frequency:** Monthly
- **Settlement Source:** Bureau of Labor Statistics (https://www.bls.gov/cpi/)
- **Contract Terms:** https://kalshi-public-docs.s3.amazonaws.com/contract_terms/CPI.pdf
- **CPI Measure:** Headline CPI-U, **month-over-month percentage change**, single-decimal (e.g., 0.3%)
- **NOT** Core CPI, NOT year-over-year — this is the all-items monthly change

### Current Open Event: KXCPI-26FEB (February 2026 CPI)

**Key Dates:**
- Market opened: January 13, 2026
- Market closes: March 11, 2026 at 8:29 AM ET (1 minute before BLS release)
- BLS CPI Release: March 11, 2026 at 8:30 AM ET
- Expected expiration: March 11, 2026 at 10:00 AM ET
- Latest expiration: June 10, 2026 (backup for govt shutdown delays)

### Market Structure: Binary Bracket System
Markets are NOT mutually exclusive — each is an independent binary contract: "Will CPI rise more than X%?"

| Ticker | Strike | Last Price | Yes Bid/Ask | No Bid/Ask | Volume | Open Interest | Liquidity |
|--------|--------|-----------|-------------|------------|--------|---------------|-----------|
| KXCPI-26FEB-T-0.1 | >-0.1% | $0.94 | $0.96/$1.00 | $0.00/$0.04 | 54 | 53 | $29,446 |
| KXCPI-26FEB-T0.0 | >0.0% | $0.95 | $0.94/$1.00 | $0.00/$0.06 | 527 | 274 | $34,384 |
| KXCPI-26FEB-T0.1 | >0.1% | $0.85 | $0.87/$0.89 | $0.11/$0.13 | 6,128 | 5,355 | $26,904 |
| KXCPI-26FEB-T0.2 | >0.2% | $0.56 | $0.55/$0.56 | $0.44/$0.45 | 3,395 | 2,317 | $47,575 |
| KXCPI-26FEB-T0.3 | >0.3% | $0.17 | $0.15/$0.16 | $0.84/$0.85 | 5,022 | 4,617 | $41,012 |
| KXCPI-26FEB-T0.4 | >0.4% | $0.05 | $0.03/$0.06 | $0.94/$0.97 | 1,739 | 1,401 | $13,411 |

### Market-Implied CPI Distribution (from prices)
Using the step-down of YES prices to extract implied probability for each bracket:

| CPI MoM Range | Implied Probability |
|---------------|-------------------|
| ≤ -0.1% | ~4-6% |
| -0.1% to 0.0% | ~0-1% |
| 0.0% to 0.1% | ~7-9% |
| **0.1% to 0.2%** | **~29-32%** |
| **0.2% to 0.3%** | **~39-41%** |
| 0.3% to 0.4% | ~11-13% |
| > 0.4% | ~3-6% |

**Market-implied mode: 0.2% MoM** (most likely outcome per pricing)
**Market-implied mean: ~0.2%** 

### Liquidity Assessment
- **Best liquidity:** 0.2% strike ($47.6K liquidity, tightest spreads at 1¢)
- **Good liquidity:** 0.3% strike ($41K), 0.0% strike ($34.4K)
- **Moderate:** 0.1% and -0.1% strikes (~$27-29K)
- **Thinnest:** 0.4% strike ($13.4K, 3¢ spread)
- **Total volume across all strikes:** ~16,865 contracts
- **Spread:** 1-3¢ on most strikes = very tradeable for our size ($20 account)

### Key Structural Notes
1. **Not mutually exclusive** — each bracket is independent binary. This creates arbitrage constraints but also opportunities
2. **Single-decimal resolution** — CPI rounds to 0.1%, so 0.24% rounds to 0.2% and "above 0.2%" resolves NO
3. **Market closes 1 minute before release** — no last-second info trading possible
4. **$1 notional per contract** — very small size, good for our $20 bankroll
5. **Quadratic fees with maker fees** — fee structure favors providing liquidity

---

## 2. Cleveland Fed Nowcast Edge

### What It Is
The Cleveland Fed produces **daily nowcasts** of CPI (and PCE) inflation using:
- Daily oil prices
- Weekly gasoline prices  
- Monthly CPI and PCE inflation readings

### Key Characteristics
- **Updated daily** throughout the month
- **Available before BLS release** — gives a real-time estimate of what current month's CPI will be
- **Historically more accurate** than consensus survey forecasts and alternative statistical models
- **Free and public** — available at https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting

### Important Note (Oct 2025 disruption)
BLS did not release October 2025 CPI due to federal government shutdown. The Cleveland Fed had to adjust methodology for handling missing data — this may affect recent nowcast accuracy.

### Edge Assessment: Cleveland Fed Nowcast vs. Kalshi Markets

**Similarities to our weather strategy:**
| Factor | Weather (NWS) | CPI (Cleveland Fed) |
|--------|--------------|-------------------|
| Free public data source | ✅ NWS forecasts | ✅ Cleveland Fed nowcast |
| Updated frequently | ✅ Hourly | ✅ Daily |
| Better than market consensus | ✅ Often | ✅ Historically yes |
| Available before settlement | ✅ | ✅ |
| Single-event binary outcome | ✅ | ✅ |

**Key differences (challenges):**
| Factor | Weather | CPI |
|--------|---------|-----|
| Events per month | Many (daily temps in many cities) | **1 per month** |
| Prediction horizon | 1-7 days | ~2-4 weeks |
| Information asymmetry | Low (retail ignores NWS) | **Moderate** (sophisticated traders watch Cleveland Fed) |
| Number of participants | Retail-heavy | Mix of retail + institutional |
| Outcome volatility | Weather varies a lot | CPI typically 0.1-0.4% range |

**Verdict:** The edge is **smaller and harder to exploit** than weather because:
1. Only 12 events per year (vs hundreds for weather)
2. Institutional/macro traders actively follow the Cleveland Fed nowcast
3. CPI outcomes cluster in a narrow range — harder to find mispriced tails

**BUT** there may still be edge because:
1. Kalshi retail participants may not track the nowcast
2. The nowcast improves significantly in the final days before release (as weekly gas data comes in)
3. Tail brackets may be systematically overpriced (longshot bias)

---

## 3. CPI Release Calendar

### 2026 BLS CPI Release Schedule (all at 8:30 AM ET)

| Reference Month | Release Date | Kalshi Event |
|----------------|-------------|--------------|
| January 2026 | Feb 13, 2026 | KXCPI-26JAN (already settled) |
| **February 2026** | **Mar 11, 2026** | **KXCPI-26FEB (ACTIVE — 23 days out)** |
| March 2026 | Apr 10, 2026 | KXCPI-26MAR (not yet open?) |
| April 2026 | May 12, 2026 | |
| May 2026 | Jun 10, 2026 | |
| June 2026 | Jul 14, 2026 | |
| July 2026 | Aug 12, 2026 | |
| August 2026 | Sep 11, 2026 | |
| September 2026 | Oct 14, 2026 | |
| October 2026 | Nov 10, 2026 | |
| November 2026 | Dec 10, 2026 | |

### Timing Pattern
- Markets open ~2 months before release (Jan 13 open for Mar 11 release = 57 days lead time)
- Markets close at 8:29 AM ET on release day
- Settlement at ~10:00 AM ET (300-second settlement timer)

### Typical Pricing Pattern (expected)
1. **Early period (T-60 to T-30):** Wide spreads, low volume, prices near prior month consensus
2. **Mid period (T-30 to T-7):** Prices begin incorporating early-month data, Cleveland Fed nowcast starts updating
3. **Final week (T-7 to T-1):** Highest volume, prices reflect latest nowcast and Wall Street estimates
4. **Final day (T-0):** Prices converge to near-certainty for consensus brackets, tails compress

---

## 4. Historical CPI Accuracy & Bias Analysis

### Consensus Forecast Accuracy
Based on historical data (pre-2026):
- **Wall Street consensus** for monthly CPI is typically accurate to ±0.1 percentage points
- CPI comes in AT consensus about 40-50% of the time (at single-decimal resolution)
- CPI surprises by ±0.1% about 40% of the time
- CPI surprises by ±0.2% or more about 10-15% of the time

### Systematic Biases
1. **Slight upward bias in recent years** — consensus has tended to slightly underestimate CPI during 2021-2024 inflationary period
2. **Rounding creates edge** — actual CPI is continuous but settles at single-decimal. A consensus of 0.3% could easily round to 0.2% or 0.3%
3. **Seasonal adjustment surprises** — January CPI is notorious for upside surprises due to annual seasonal factor revisions

### Longshot Bracket Mispricing (Key Question)
**Are tail brackets systematically overpriced like weather?**

Evidence suggests **yes, but less pronounced:**
- The 0.4%+ bracket priced at 3-6¢ — historically CPI exceeds 0.4% MoM maybe 5-10% of months in normal environments, so pricing seems roughly fair
- The ≤-0.1% bracket priced at 4-6¢ — negative CPI months are rare (~5-10% historically), again roughly fair
- **The potential mispricing is in the 0.1% and 0.3% brackets** — these border the consensus and may overweight recent trends

### Cleveland Fed Nowcast Accuracy
- The nowcast's RMSE for monthly CPI is historically lower than survey consensus (typically 0.05-0.10 pp better)
- Most valuable in the **final 1-2 weeks** before release when weekly gasoline price data is incorporated
- In the very final days, the nowcast can sometimes pin the outcome to within 0.05 pp

---

## 5. Proposed CPI Trading Strategy

### Strategy Overview: "Nowcast-Informed Bracket Trading"

#### Core Thesis
Use the Cleveland Fed inflation nowcast as our primary signal, trading against Kalshi market pricing when the nowcast diverges from market-implied expectations. Focus on the final 1-2 weeks before CPI release when the nowcast is most accurate.

### Entry Timing
1. **Primary entry: T-7 to T-3 (one week before release)**
   - Cleveland Fed nowcast has incorporated most monthly data
   - Markets still have some inefficiency vs. nowcast
   - Enough time for prices to move in our favor before close

2. **Secondary entry: T-14 to T-7 (two weeks before)**
   - If nowcast already shows strong divergence from market pricing
   - Lower confidence but higher potential edge

3. **Avoid: T-1 and final hours**
   - Spreads may widen, market-makers withdraw
   - Nowcast info already priced in by sophisticated traders

### Bracket Selection Rules
1. **Compare Cleveland Fed nowcast to market-implied CPI distribution**
2. **Identify brackets where nowcast implies >10 percentage point probability difference from market price**
3. **Prefer the bracket straddling the nowcast point estimate** — if nowcast says 0.25%, the 0.2% strike (>0.2%) is the key trade
4. **Sell overpriced tail brackets** when nowcast suggests tail outcome is unlikely

### Specific Trade Types

**Trade Type A: Consensus Bracket (highest conviction)**
- When nowcast ≈ consensus and market-implied mode matches → buy the modal bracket for cheap theta if priced <fair
- Example: If nowcast = 0.2%, and >0.2% is priced at 55¢ but >0.1% is at 87¢, the implied 0.2% bracket (0.1 to 0.2%) is 32%. If you think true prob is higher, buy YES on >0.1% or NO on >0.2%

**Trade Type B: Nowcast Divergence (medium conviction)**
- When nowcast diverges from market pricing by ≥0.1 pp
- Example: Market implies mode at 0.2%, nowcast says 0.3% → buy YES on >0.2% (currently 55-56¢, should be higher)

**Trade Type C: Tail Fade (lower conviction, higher payoff)**
- Sell tail brackets that seem overpriced relative to nowcast
- Example: Buy NO on >0.4% at 94-97¢ for 3-6¢ profit if CPI ≤0.4%

### Position Sizing (for $20 bankroll)
- **Max position per CPI event:** $5 (25% of bankroll)
- **Max per bracket:** $3
- **Preferred contract size:** 3-5 contracts per trade
- **Expected frequency:** 1-2 trades per month (12-24/year)
- **Stop loss:** None needed — binary contracts with capped risk

### Expected Edge & Risk Assessment

**Expected edge per trade:** 3-8% (much lower than weather due to more sophisticated market)
**Win rate (estimated):** 55-60%
**Average profit per correct trade:** $0.10-0.30 per contract
**Average loss per incorrect trade:** $0.15-0.55 per contract (depends on bracket)

**Monthly expected P&L:** +$0.50 to +$1.50 with $5 at risk
**Annual expected P&L:** +$6 to +$18 (30-90% return on allocated capital)

**Key Risks:**
1. **Government shutdown** — can delay BLS release indefinitely (happened Oct 2025!)
2. **Model risk** — Cleveland Fed nowcast could be wrong, especially after methodology changes
3. **Seasonal adjustment revisions** — January CPI is particularly hard to forecast
4. **Low frequency** — only 12 opportunities per year, high variance
5. **Fee drag** — Kalshi fees reduce edge, especially on small trades

### Diversification Benefit with Weather Strategy
- **Zero correlation** — CPI outcomes have no relationship to weather outcomes
- **Different timing** — weather is daily, CPI is monthly (smoother P&L)
- **Different edge source** — weather uses NWS models, CPI uses Cleveland Fed nowcast
- **Portfolio effect** — adding uncorrelated strategy with positive expected value reduces overall variance
- **Combined approach** makes the $20 bankroll more efficient — weather generates steady small gains, CPI adds monthly kicker

---

## 6. Immediate Action Items

### For February 2026 CPI (releasing March 11)
1. ✅ Market is open, 23 days to release
2. **Monitor Cleveland Fed nowcast daily** starting now
3. **Current market-implied CPI:** ~0.2% MoM
4. **Enter trade T-7 (around March 4)** once nowcast stabilizes
5. **Key decision:** Does nowcast agree with 0.2% consensus? If so, look for tail fades. If it diverges, trade the directional bracket.

### Infrastructure Needed
- [ ] Set up daily Cleveland Fed nowcast monitoring (scrape or check manually)
- [ ] Track Kalshi CPI market prices daily (API call to KXCPI-26FEB)
- [ ] Build spreadsheet comparing nowcast vs. market-implied distribution
- [ ] Set calendar reminder for T-7 entry window (March 4, 2026)

---

## 7. February 2026 CPI Current Snapshot

**As of Feb 16, 2026 (23 days before release):**
- Market-implied mode: 0.2% MoM
- Most liquid strike: 0.2% ($47.6K liquidity)
- Highest volume strike: 0.1% (6,128 contracts)
- Current market says: ~87% chance CPI > 0.1%, ~56% chance > 0.2%, ~16% chance > 0.3%
- **Next step:** Check Cleveland Fed nowcast for Feb 2026 CPI and compare to these probabilities
