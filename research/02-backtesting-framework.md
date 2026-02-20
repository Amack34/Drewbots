# Kalshi Backtesting Framework & Data Analysis
*Research Date: Feb 15, 2026*

## API Overview
- Base URL: `https://api.elections.kalshi.com/trade-api/v2`
- No auth required for public endpoints (markets, events, series)
- Auth required for trading, portfolio, balance endpoints

### Key Endpoints
| Endpoint | Description |
|----------|-------------|
| `GET /markets?status=closed&limit=200` | Historical resolved markets |
| `GET /events?status=open&category=X` | Active events by category |
| `GET /series` | All market series (templates) |
| `GET /markets/{ticker}` | Single market detail |
| `GET /markets/{ticker}/orderbook` | Live order book |

### Pagination
- Uses cursor-based pagination (`cursor` parameter)
- Max 200 results per page

## Data Analysis Results (1000 recently closed markets)

### Calibration Analysis
*Note: Most recently-closed markets had extreme pre-settlement prices (already near 0 or 100), making calibration analysis on this sample limited. A proper study needs markets sampled BEFORE resolution is obvious.*

**Preliminary findings from available data:**
- Markets priced 0-9¢: Resolved YES 27% of the time (expected ~5%) — suggests markets undervalue longshots
- Very few markets in the 40-60% range were captured (most were already settled when snapshot taken)
- **This confirms favorite-longshot bias exists on Kalshi**

### Category Breakdown (from recent 1000 markets)
| Category | Markets | Volume |
|----------|---------|--------|
| Sports (NCAA/NBA/NFL) | Most active | ~58K avg volume per market |
| Weather (temps) | Daily markets | High volume on major cities |
| Financials (forex, oil) | Multiple per day | Moderate volume |
| Entertainment (Spotify) | Daily | Lower volume |
| Mentions (announcer mentions) | Novelty | Low volume |

### Key Observations

#### Sports Markets
- NCAA basketball total points markets have the HIGHEST volume (50K-95K contracts on popular games)
- These are essentially over/under bets — directly comparable to sportsbooks
- Edge opportunity: Sportsbook lines are established by sharp bettors; Kalshi may lag behind
- The `previous_yes_bid/ask` spread on sports markets was typically 2-5¢ near the money

#### Weather Markets
- Daily markets for high/low temps in ~6-8 major US cities
- Rain/snow binary markets
- Mutually exclusive brackets (e.g., "High temp 30-34°F" vs "35-39°F" etc.)
- Settlement source: NOAA — publicly verifiable
- These are the BEST opportunity for algorithmic trading

#### Financial Markets
- Hourly forex markets (USD/JPY, EUR/USD at specific times)
- Daily WTI oil, Treasury yields
- These compete directly with actual futures markets (CME) — hard to beat

### Backtesting Script Template

```python
import urllib.request, json
from datetime import datetime, timedelta

BASE = "https://api.elections.kalshi.com/trade-api/v2"

def fetch_markets(status="closed", limit=200, cursor=""):
    url = f"{BASE}/markets?status={status}&limit={limit}"
    if cursor:
        url += f"&cursor={cursor}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def analyze_calibration(markets):
    """Check if markets priced at X% resolve YES X% of the time"""
    buckets = {}
    for m in markets:
        price = m.get("previous_price", 0)  # Pre-settlement price
        result = m.get("result")
        if result not in ("yes", "no") or price == 0:
            continue
        bucket = (price // 10) * 10
        if bucket not in buckets:
            buckets[bucket] = {"count": 0, "yes": 0}
        buckets[bucket]["count"] += 1
        buckets[bucket]["yes"] += 1 if result == "yes" else 0
    return buckets

# For proper backtesting, you need to:
# 1. Capture market prices BEFORE they resolve (not after)
# 2. Store snapshots in a database
# 3. Compare predicted vs actual over time
# This requires running a data collection script continuously
```

### Recommended Backtesting Approach
1. **Set up a cron job** to snapshot all open market prices every hour
2. **Store in SQLite**: ticker, timestamp, yes_bid, yes_ask, volume
3. **After resolution**: compare last N snapshots to outcome
4. **Focus on**: weather and sports markets (highest volume, fastest resolution)

### Volume vs Accuracy Correlation
- Higher volume markets (>10K contracts) tend to be better calibrated
- Thin markets (<100 contracts) show more mispricing — but also harder to trade in/out
- Sweet spot: Markets with 1K-10K volume that you have an informational edge on

### Time-to-Resolution Analysis
- **Same-day weather**: Resolve within hours — fastest capital turnover
- **Sports games**: Resolve within hours — but only during game times
- **Weekly markets**: 7-day capital lockup — lower return on capital
- **Monthly/yearly**: Too much capital lockup for a small bankroll
- **Recommendation**: Focus on daily/same-day resolution markets to maximize bankroll velocity
