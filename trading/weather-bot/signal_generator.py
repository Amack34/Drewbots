#!/usr/bin/env python3
"""
Signal generator for Kalshi weather trading.
Compares NWS observations + forecasts against Kalshi market prices.
Identifies mispriced temperature brackets and outputs trading signals.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass

from weather_collector import get_latest_observations, get_latest_forecast, CONFIG
from kalshi_trader import KalshiClient

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "signals.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("signal_gen")


@dataclass
class Signal:
    """A trading signal."""
    city: str
    market_type: str        # "high" or "low"
    event_ticker: str
    market_ticker: str      # specific bracket ticker
    action: str             # "buy" or "sell"
    side: str               # "yes" or "no"
    suggested_price: int    # in cents
    confidence: float       # 0-1
    edge_pct: float         # estimated edge percentage
    reason: str
    current_temp_f: float
    forecast_temp_f: float
    surrounding_avg_f: float
    market_yes_price: int   # current market yes price in cents
    is_tomorrow: bool = False  # True if tomorrow market (stale pricing edge)
    margin: float = 0.0       # degrees F margin of safety from bracket edge
    signal_source: str = "model"  # "model" or "metar_lockin"

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "market_type": self.market_type,
            "event_ticker": self.event_ticker,
            "market_ticker": self.market_ticker,
            "action": self.action,
            "side": self.side,
            "suggested_price": self.suggested_price,
            "confidence": round(self.confidence, 3),
            "edge_pct": round(self.edge_pct, 1),
            "reason": self.reason,
            "current_temp_f": self.current_temp_f,
            "forecast_temp_f": self.forecast_temp_f,
            "surrounding_avg_f": self.surrounding_avg_f,
            "market_yes_price": self.market_yes_price,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def __str__(self):
        return (f"[{self.confidence:.0%} conf] {self.city} {self.market_type}: "
                f"{self.action} {self.side} {self.market_ticker} @ {self.suggested_price}¢ "
                f"(edge: {self.edge_pct:.1f}%) — {self.reason}")


def _get_running_extremes(city: str) -> dict:
    """Get running daily high/low from temp_tracker state file."""
    try:
        state_file = os.path.join(os.path.dirname(__file__), 'temp_state.json')
        with open(state_file, 'r') as f:
            state = json.load(f)
        city_state = state.get('cities', {}).get(city, {})
        return {
            'running_high': city_state.get('high'),
            'running_low': city_state.get('low'),
            'high_time': city_state.get('high_time'),
            'low_time': city_state.get('low_time'),
        }
    except Exception:
        return {'running_high': None, 'running_low': None, 'high_time': None, 'low_time': None}


def estimate_temp(city: str, target_date: str = None) -> dict | None:
    """
    Estimate the final high/low temperature for a city based on:
    - Running daily high/low from temp_tracker (real-time ground truth)
    - Current primary station reading
    - Surrounding station readings (trend detection)
    - NWS forecast (for the target date, defaults to today)
    
    Args:
        city: City name
        target_date: Optional YYYY-MM-DD for tomorrow's forecast. If None, uses today's.
    """
    obs = get_latest_observations(city)
    forecast = get_latest_forecast(city, target_date=target_date)
    
    # For tomorrow's markets, reduce confidence since forecast is further out
    is_tomorrow = target_date is not None

    # Get running extremes from temp_tracker
    running = _get_running_extremes(city)
    running_high = running['running_high']
    running_low = running['running_low']
    if running_high:
        log.info("%s running high: %.1f°F (set at %s)", city, running_high, running.get('high_time', '?'))
    if running_low:
        log.info("%s running low: %.1f°F (set at %s)", city, running_low, running.get('low_time', '?'))

    if not obs:
        log.warning("No observations for %s", city)
        return None

    # Separate primary and surrounding
    primary = [o for o in obs if o["is_primary"]]
    surrounding = [o for o in obs if not o["is_primary"]]

    primary_temp = primary[0]["temp_f"] if primary else None
    if primary_temp is None:
        log.warning("No primary temp for %s", city)
        return None

    surr_temps = [o["temp_f"] for o in surrounding if o["temp_f"] is not None]
    surr_avg = sum(surr_temps) / len(surr_temps) if surr_temps else primary_temp

    # Get weather conditions for adjustment
    primary_obs = primary[0] if primary else {}
    wind_mph = primary_obs.get("wind_mph", 0) or 0
    humidity = primary_obs.get("humidity") or 50
    cloud_cover = primary_obs.get("cloud_cover", "")

    forecast_high = forecast["forecast_high_f"] if forecast else None
    forecast_low = forecast["forecast_low_f"] if forecast else None

    # Estimate final high temp
    # If it's morning and current temp is already near/above forecast, high will likely be higher
    now_et_hour = (datetime.now(timezone.utc).hour - 5) % 24  # rough ET

    estimated_high = None
    high_confidence = 0.5

    # Multi-source validation: ONLY for tomorrow's markets
    # The weather_validator pulls tomorrow's forecasts — using it for today would mix dates
    consensus = None
    if is_tomorrow:
        try:
            from weather_validator import get_consensus_forecast
            consensus = get_consensus_forecast(city)
            if consensus and consensus.get("high") and forecast_high:
                divergence = abs(consensus["high"] - forecast_high)
                if divergence > 3:
                    log.warning("⚠️ %s HIGH divergence: NWS=%.0f°F vs consensus=%.0f°F (%.1f°F apart, %s confidence)",
                                city, forecast_high, consensus["high"], divergence, consensus.get("high_confidence", "?"))
                else:
                    log.info("✅ %s HIGH sources agree: NWS=%.0f°F, consensus=%.0f°F (%.1f°F apart)",
                             city, forecast_high, consensus["high"], divergence)
        except Exception as e:
            log.debug("Weather validator unavailable: %s", e)

    if forecast_high is not None:
        if is_tomorrow and consensus and consensus.get("high"):
            # Tomorrow: use multi-source consensus
            estimated_high = consensus["high"]
            log.info("Using multi-source consensus for %s high: %.1f°F (%d sources, %s confidence)",
                     city, estimated_high, consensus.get("high_sources", 1), consensus.get("high_confidence", "?"))
        else:
            # Today: use NWS forecast from weather_collector (correct date)
            estimated_high = forecast_high

        if is_tomorrow:
            high_confidence = 0.4 if not consensus else (0.5 if consensus.get("high_confidence") == "high" else 0.4)
            log.info("Tomorrow estimate for %s: %.0f°F (confidence %.0f%%, %s)",
                     city, estimated_high, high_confidence * 100,
                     f"{consensus.get('high_sources', 1)} sources" if consensus else "NWS only")
        else:
            # TODAY's markets: running high is the FLOOR — can only go higher
            if running_high is not None and running_high > estimated_high:
                log.warning("⚠️ %s running high %.1f°F EXCEEDS forecast %.1f°F — using running high as floor",
                            city, running_high, estimated_high)
                estimated_high = running_high
                high_confidence += 0.15  # We have real data, more confident

            # ROUNDING AMBIGUITY: METAR 5-min data has ±1°F uncertainty from C/F conversion
            # If running high is within 1°F of a bracket edge, actual could be 1°F higher
            if running_high is not None:
                estimated_high = max(estimated_high, running_high + 1.0)
                log.info("%s rounding buffer: estimated high %.1f°F (running %.1f°F + 1°F ambiguity)",
                         city, estimated_high, running_high)

            # Adjustment: if current temp already near/above estimate, adjust up
            if primary_temp > estimated_high - 2:
                adjustment = (primary_temp - estimated_high + 2) * 0.7
                estimated_high += adjustment
                high_confidence += 0.1

            # Adjustment: surrounding stations warmer → warm air incoming
            if surr_avg > primary_temp + 1.5:
                estimated_high += (surr_avg - primary_temp) * 0.5
                high_confidence += 0.05

            # Adjustment: surrounding stations cooler → cold air incoming
            if surr_avg < primary_temp - 1.5:
                estimated_high -= (primary_temp - surr_avg) * 0.3
                high_confidence += 0.05

        # City-specific HIGH biases from prediction_log analysis (Feb 19)
        # Positive = forecast undershoots actual (actual hotter than predicted)
        HIGH_BIASES = {"MIA": 5.0, "ATL": 5.0, "NYC": 3.0}
        if city in HIGH_BIASES:
            bias = HIGH_BIASES[city]
            estimated_high += bias
            log.info("%s high temp bias: adjusted up %.1f°F to %.1f°F", city, bias, estimated_high)

        if not is_tomorrow:
            # Time-based confidence: closer to peak = more certain (today only)
            if 12 <= now_et_hour <= 16:
                high_confidence += 0.2  # afternoon — very close to actual high
            elif 10 <= now_et_hour <= 18:
                high_confidence += 0.1

    # Estimate final low temp
    estimated_low = None
    low_confidence = 0.5

    if forecast_low is not None:
        if is_tomorrow and consensus and consensus.get("low"):
            # Tomorrow: use multi-source consensus
            estimated_low = consensus["low"]
            log.info("Using multi-source consensus for %s low: %.1f°F (%d sources, %s confidence)",
                     city, estimated_low, consensus.get("low_sources", 1), consensus.get("low_confidence", "?"))
        else:
            # Today: use NWS forecast from weather_collector (correct date)
            estimated_low = forecast_low

        if is_tomorrow:
            low_confidence = 0.4 if not consensus else (0.5 if consensus.get("low_confidence") == "high" else 0.4)
            log.info("Tomorrow low estimate for %s: %.0f°F (confidence %.0f%%, %s)",
                     city, estimated_low, low_confidence * 100,
                     f"{consensus.get('low_sources', 1)} sources" if consensus else "NWS only")
        elif not is_tomorrow and running_low is not None:
            # TODAY: running low is the CEILING for low — can only go lower
            if running_low < estimated_low:
                log.warning("⚠️ %s running low %.1f°F BELOW forecast low %.1f°F — using running low as ceiling",
                            city, running_low, estimated_low)
                estimated_low = running_low
                low_confidence += 0.15
            # Rounding ambiguity: actual low could be 1°F lower than displayed
            estimated_low = min(estimated_low, running_low - 1.0)
            log.info("%s low rounding buffer: estimated low %.1f°F (running %.1f°F - 1°F ambiguity)",
                     city, estimated_low, running_low)
        else:
            # Today's low: adjust based on current conditions
            # Clear sky + low wind = more radiative cooling = colder than forecast
            if cloud_cover in ("CLR", "FEW", "SKC") and wind_mph < 8:
                estimated_low -= 1.5
                low_confidence += 0.1

            # Cloudy + windy = insulation = warmer than forecast
            if cloud_cover in ("OVC", "BKN") and wind_mph > 10:
                estimated_low += 1.5
                low_confidence += 0.1

            # Evening: current temp gives strong signal for overnight low
            if 20 <= now_et_hour or now_et_hour <= 4:
                # Current temp is close to what low will be
                estimated_low = min(primary_temp, estimated_low)
                low_confidence += 0.15

        # City-specific LOW biases from prediction_log analysis (Feb 19)
        # Negative = forecast overshoots actual (actual colder than predicted)
        LOW_BIASES = {"MIA": -6.0, "NYC": -4.0}
        if city in LOW_BIASES:
            bias = LOW_BIASES[city]
            estimated_low += bias  # bias is negative, so this subtracts
            log.info("%s low temp bias: adjusted %.1f°F to %.1f°F", city, bias, estimated_low)

    return {
        "city": city,
        "primary_temp": primary_temp,
        "surrounding_avg": round(surr_avg, 1),
        "forecast_high": forecast_high,
        "forecast_low": forecast_low,
        "estimated_high": round(estimated_high, 1) if estimated_high else None,
        "estimated_low": round(estimated_low, 1) if estimated_low else None,
        "high_confidence": min(high_confidence, 0.95),
        "low_confidence": min(low_confidence, 0.95),
        "wind_mph": wind_mph,
        "humidity": humidity,
        "cloud_cover": cloud_cover,
        "running_high": running_high,
        "running_low": running_low,
    }


def parse_bracket_from_ticker(ticker: str) -> tuple[float, float] | None:
    """Extract temperature bracket [low, high] from market ticker.
    
    Kalshi weather tickers use two formats:
    - "B40.5" style: bracket market, temp is the midpoint-ish (e.g. 40-41°F range)
    - "T43" style: threshold market (>43°F or <36°F)
    
    Returns (low, high) bounds for the bracket.
    """
    parts = ticker.split("-")
    if not parts:
        return None
    last = parts[-1]
    
    is_threshold = last.startswith("T")
    is_bracket = last.startswith("B")
    
    # Strip leading letter
    num_str = last.lstrip("BTbt")
    if not num_str:
        return None
    
    try:
        temp_val = float(num_str)
    except ValueError:
        return None
    
    if is_bracket:
        # Bracket markets: "B40.5" means the bracket centered around that value
        # Typically 2°F wide brackets: e.g. B40.5 = [40, 41]
        bracket_low = int(temp_val - 0.5)
        bracket_high = int(temp_val + 0.5)
        return (bracket_low, bracket_high)
    elif is_threshold:
        # Threshold markets: "T43" means ">43°F" or "<36°F"
        # Treat as a wide bracket for signal purposes
        return (temp_val, temp_val + 4)
    else:
        # Plain number
        return (temp_val, temp_val + 4)


def generate_signals(client: KalshiClient = None) -> list[Signal]:
    """Generate trading signals for all configured cities."""
    if client is None:
        client = KalshiClient()

    signals = []
    min_edge = CONFIG["risk"]["min_edge_pct"]
    
    # Scan today AND tomorrow's markets (tomorrow opens ~10am ET, early entry = edge)
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc)
    date_strs = [
        now_utc.strftime("%y%b%d").upper(),
        (now_utc + timedelta(days=1)).strftime("%y%b%d").upper(),
    ]

    disabled = CONFIG.get("disabled_cities", [])
    for city_name, city_config in CONFIG["cities"].items():
        if city_name in disabled:
            log.info("Skipping %s (disabled)", city_name)
            continue
        for date_str in date_strs:
            # Use the correct forecast for each date (today vs tomorrow)
            # Convert Kalshi date format (e.g. "26FEB18") to YYYY-MM-DD for forecast lookup
            is_tomorrow = (date_str == date_strs[1]) if len(date_strs) > 1 else False
            if is_tomorrow:
                tomorrow_date = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
                estimate = estimate_temp(city_name, target_date=tomorrow_date)
            else:
                estimate = estimate_temp(city_name)
            if not estimate:
                continue
            # Process HIGH temp markets
            if city_config.get("kalshi_high") and estimate["estimated_high"]:
                event_ticker = f"{city_config['kalshi_high']}-{date_str}"
                try:
                    markets = client.get_weather_markets(event_ticker)
                except Exception as e:
                    log.warning("Failed to get markets for %s: %s", event_ticker, e)
                    markets = []

                if markets:
                    signals.extend(_analyze_brackets(
                        markets, estimate, city_name, "high",
                        event_ticker, estimate["estimated_high"],
                        estimate["high_confidence"], min_edge,
                        is_tomorrow=is_tomorrow
                    ))

            # Process LOW temp markets
            if city_config.get("kalshi_low") and estimate["estimated_low"]:
                event_ticker = f"{city_config['kalshi_low']}-{date_str}"
                try:
                    markets = client.get_weather_markets(event_ticker)
                except Exception as e:
                    log.warning("Failed to get markets for %s: %s", event_ticker, e)
                    markets = []

                if markets:
                    signals.extend(_analyze_brackets(
                        markets, estimate, city_name, "low",
                        event_ticker, estimate["estimated_low"],
                        estimate["low_confidence"], min_edge,
                        is_tomorrow=is_tomorrow
                    ))

    # FILTER: Only keep high-probability plays
    # Night 1 lesson: YES bracket buys under 50¢ are losers. Our edge is selling longshots.
    # Night 1 lesson 2: NO sells on 2-3¢ YES brackets risk $0.97 to make $0.02 — terrible R/R.
    filtered = []
    for s in signals:
        # KEEP: NO trades where YES price >= 10¢ (decent risk/reward)
        # SKIP: NO trades where YES price < 10¢ (risking $0.90+ to make pennies)
        if s.side == "no":
            if s.market_yes_price < 10:
                log.info("  FILTERED OUT: %s NO (YES@%d¢) — risk $%.2f to make $%.2f, terrible R/R",
                         s.market_ticker, s.market_yes_price,
                         (100 - s.market_yes_price) / 100, s.market_yes_price / 100)
                continue
            filtered.append(s)
        # KEEP: YES on threshold/bracket at high prices (near-certain plays, ≥50¢)
        elif s.side == "yes" and s.suggested_price >= 50:
            filtered.append(s)
        # SKIP: YES under 50¢ — not enough conviction, proven drag on P&L
        else:
            log.info("  FILTERED OUT: %s YES @ %d¢ (YES buys under 50¢ = losers)", 
                     s.market_ticker, s.suggested_price)
    
    signals = filtered

    # Sort by strategy priority:
    # 1. SELL overpriced longshots (buy NO on 5-25¢ YES brackets) — proven 5-10% edge
    # 2. Threshold markets where current temp already exceeds threshold — near-certain
    # 3. Mid-range bracket plays
    def signal_score(s):
        base = s.confidence * min(s.edge_pct, 100)  # cap edge to prevent runaway scores

        # HIGHEST PRIORITY: Selling overpriced longshots (buying NO)
        if s.side == "no" and s.market_yes_price <= 25:
            base *= 5.0  # 5x weight — this is our proven edge

        # HIGH PRIORITY: Threshold markets with high confidence
        elif s.side == "yes" and s.suggested_price >= 80:
            base *= 3.0  # near-certain plays

        # MODERATE: NO trades on mid-range brackets
        elif s.side == "no":
            base *= 2.0

        # STANDARD: YES on mid-range brackets  
        elif s.side == "yes" and s.suggested_price >= 10:
            base *= 1.0

        # LOW: Everything else
        else:
            base *= 0.3

        # Boost MIA and NYC (most profitable in backtest)
        if s.city in ("MIA", "NYC"):
            base *= 1.3
        return base

    signals.sort(key=signal_score, reverse=True)

    log.info("Generated %d signals", len(signals))
    for s in signals:
        log.info("  %s", s)

    return signals


def _norm_cdf(x: float) -> float:
    """Approximate normal CDF using the error function."""
    import math
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _analyze_brackets(markets: list[dict], estimate: dict, city: str,
                      market_type: str, event_ticker: str,
                      estimated_temp: float, confidence: float,
                      min_edge: float, is_tomorrow: bool = False) -> list[Signal]:
    """Analyze market brackets against our temperature estimate."""
    signals = []

    for market in markets:
        ticker = market.get("ticker", "")
        
        # Use floor_strike/cap_strike from API if available (more reliable)
        floor_strike = market.get("floor_strike")
        cap_strike = market.get("cap_strike")
        
        is_above_threshold = floor_strike is not None and cap_strike is None  # ">X°F"
        is_below_threshold = cap_strike is not None and floor_strike is None  # "<X°F"
        is_bracket = floor_strike is not None and cap_strike is not None      # "X-Y°F"
        
        if not (is_above_threshold or is_below_threshold or is_bracket):
            bracket = parse_bracket_from_ticker(ticker)
            if not bracket:
                continue
            floor_strike, cap_strike = bracket[0], bracket[1]
            is_bracket = True

        # Get current market prices
        yes_bid = market.get("yes_bid", 0) or 0
        yes_ask = market.get("yes_ask", 100) or 100
        no_bid = market.get("no_bid", 0) or 0
        no_ask = market.get("no_ask", 100) or 100

        # Skip illiquid markets
        if yes_bid == 0 and yes_ask == 100:
            continue

        # Skip 1¢ brackets (backtest: 1% win rate, negative EV)
        min_entry = CONFIG["risk"].get("min_entry_price", 2)
        if yes_ask < min_entry:
            continue

        # Calculate our estimated probability using a gaussian model
        # Standard deviation based on confidence: higher confidence = tighter distribution
        # Per-city std_dev from prediction accuracy analysis (Feb 20):
        #   BOS/PHI: ±1°F → tight std_dev ok
        #   NYC: ±3-4°F → moderate
        #   MIA: ±4-5°F → wide
        #   ATL: ±5-11°F → very wide
        import math
        CITY_STD_FLOOR = {"ATL": 5.0, "MIA": 4.5, "NYC": 3.5, "DC": 3.5, "BOS": 2.5, "PHI": 2.5}
        base_std = 4.0 - confidence * 2.0  # 2-4°F base
        city_floor = CITY_STD_FLOOR.get(city, 3.0)
        std_dev = max(city_floor, base_std)
        
        if is_bracket:
            # P(floor <= temp <= cap) using normal CDF approximation
            bracket_low = float(floor_strike)
            bracket_high = float(cap_strike)
            bracket_mid = (bracket_low + bracket_high) / 2
            
            z_low = (bracket_low - estimated_temp) / std_dev
            z_high = (bracket_high + 1 - estimated_temp) / std_dev  # +1 because cap is inclusive
            our_prob = _norm_cdf(z_high) - _norm_cdf(z_low)
        elif is_above_threshold:
            # P(temp > floor)
            z = (float(floor_strike) - estimated_temp) / std_dev
            our_prob = 1.0 - _norm_cdf(z)
            bracket_low = float(floor_strike)
            bracket_high = bracket_low + 10
            bracket_mid = bracket_low
        elif is_below_threshold:
            # P(temp < cap)
            z = (float(cap_strike) - estimated_temp) / std_dev
            our_prob = _norm_cdf(z)
            bracket_high = float(cap_strike)
            bracket_low = bracket_high - 10
            bracket_mid = bracket_high
        
        our_prob = max(0.01, min(0.99, our_prob))
        our_price_cents = int(our_prob * 100)

        # Compare our estimate to market
        # BUY YES if our probability > market ask price (market undervalues this bracket)
        if our_price_cents > yes_ask and yes_ask > 0:
            edge = ((our_price_cents - yes_ask) / yes_ask) * 100
            if edge >= min_edge:
                signals.append(Signal(
                    city=city,
                    market_type=market_type,
                    event_ticker=event_ticker,
                    market_ticker=ticker,
                    action="buy",
                    side="yes",
                    suggested_price=yes_ask,
                    confidence=confidence,
                    edge_pct=edge,
                    reason=f"Est temp {estimated_temp:.0f}°F, bracket [{bracket_low:.0f}-{bracket_high:.0f}]°F, "
                           f"our prob {our_prob:.0%} vs market {yes_ask}¢",
                    current_temp_f=estimate["primary_temp"],
                    forecast_temp_f=estimate.get(f"forecast_{market_type}", 0) or 0,
                    surrounding_avg_f=estimate["surrounding_avg"],
                    market_yes_price=yes_ask,
                ))

        # SELL YES (buy NO) if our probability < market bid price (market overvalues this bracket)
        # Margin of safety: skip NO trades where our estimate is too close to the bracket edge
        if our_price_cents < yes_bid and yes_bid > 0:
            # For NO trades, the danger is the NEAREST edge of the bracket
            nearest_edge = min(abs(estimated_temp - bracket_low), abs(estimated_temp - bracket_high))
            if nearest_edge < 3.0:
                log.info("  SKIP NO %s: estimate %.0f°F only %.1f°F from nearest bracket edge (need 3°F margin)",
                         ticker, estimated_temp, nearest_edge)
                continue
            edge = ((yes_bid - our_price_cents) / yes_bid) * 100

            # MARKET VALIDATION: Enhanced checks when our model disagrees with market pricing.
            # Don't blindly trust Kalshi OR our model — run extra validation on flagged signals.
            market_implied_prob = yes_bid / 100.0  # What Kalshi thinks
            prob_disagreement = abs(our_prob - market_implied_prob)
            flagged = False
            flag_reasons = []

            # Flag 1: Running high is close to bracket edge but model claims big edge
            running_h = estimate.get("running_high")
            running_l = estimate.get("running_low")
            if market_type == "high" and running_h is not None:
                running_margin = abs(running_h - bracket_low)
                if running_margin < 2.0 and edge > 50:
                    flagged = True
                    flag_reasons.append(f"running high {running_h:.1f}°F only {running_margin:.1f}°F from bracket edge")
            if market_type == "low" and running_l is not None:
                running_margin_low = abs(running_l - bracket_high)
                if running_margin_low < 2.0 and edge > 50:
                    flagged = True
                    flag_reasons.append(f"running low {running_l:.1f}°F only {running_margin_low:.1f}°F from bracket edge")

            # Flag 2: Large disagreement with market on today's markets
            if yes_bid >= 15 and edge > 80 and not is_tomorrow:
                flagged = True
                flag_reasons.append(f"market prices YES at {yes_bid}¢ but model claims {edge:.0f}% edge")

            # Flag 3: Forecast vs running reality diverges >3°F
            if not is_tomorrow and running_h is not None and market_type == "high":
                forecast_val = estimate.get("forecast_high")
                if forecast_val and abs(running_h - forecast_val) > 3:
                    flagged = True
                    flag_reasons.append(f"forecast ({forecast_val:.0f}°F) diverges from running high ({running_h:.1f}°F) by >{abs(running_h - forecast_val):.0f}°F")
            if not is_tomorrow and running_l is not None and market_type == "low":
                forecast_val = estimate.get("forecast_low")
                if forecast_val and abs(running_l - forecast_val) > 3:
                    flagged = True
                    flag_reasons.append(f"forecast ({forecast_val:.0f}°F) diverges from running low ({running_l:.1f}°F) by >{abs(running_l - forecast_val):.0f}°F")

            # ENHANCED VALIDATION for flagged signals
            if flagged:
                log.warning("🔍 FLAGGED %s: %s — running enhanced validation", ticker, "; ".join(flag_reasons))

                # Enhanced check A: Cross-reference multiple data points
                # Does running temp + rounding ambiguity put us inside the bracket?
                effective_high = (running_h + 1.0) if running_h and market_type == "high" else None
                effective_low = (running_l - 1.0) if running_l and market_type == "low" else None

                if effective_high and is_bracket and bracket_low <= effective_high <= bracket_high + 1:
                    log.warning("  ❌ ENHANCED CHECK FAILED: running high + 1°F rounding (%.1f°F) falls IN bracket [%.0f-%.0f]. BLOCKING.",
                                effective_high, bracket_low, bracket_high)
                    continue
                if effective_low and is_bracket and bracket_low <= effective_low <= bracket_high + 1:
                    log.warning("  ❌ ENHANCED CHECK FAILED: running low - 1°F rounding (%.1f°F) falls IN bracket [%.0f-%.0f]. BLOCKING.",
                                effective_low, bracket_low, bracket_high)
                    continue

                # Enhanced check B: Is our estimate based on stale/wrong forecast?
                # If running data already exceeds our estimate, our model is wrong
                if market_type == "high" and running_h and running_h > estimated_temp:
                    log.warning("  ❌ ENHANCED CHECK FAILED: running high %.1f°F > our estimate %.1f°F. Model input stale. BLOCKING.",
                                running_h, estimated_temp)
                    continue
                if market_type == "low" and running_l and running_l < estimated_temp:
                    log.warning("  ❌ ENHANCED CHECK FAILED: running low %.1f°F < our estimate %.1f°F. Model input stale. BLOCKING.",
                                running_l, estimated_temp)
                    continue

                # Enhanced check C: Margin of safety after rounding — need 4°F not 3°F for flagged signals
                if nearest_edge < 4.0:
                    log.warning("  ❌ ENHANCED CHECK FAILED: flagged signal only has %.1f°F margin (need 4°F for flagged). BLOCKING.",
                                nearest_edge)
                    continue

                # Passed all enhanced checks — allow but with reduced confidence
                log.info("  ✅ FLAGGED signal passed enhanced validation — allowing with reduced confidence")
                confidence = max(confidence - 0.15, 0.2)  # Penalize confidence

            if edge >= min_edge:
                signals.append(Signal(
                    city=city,
                    market_type=market_type,
                    event_ticker=event_ticker,
                    market_ticker=ticker,
                    action="buy",
                    side="no",
                    suggested_price=100 - yes_bid,
                    confidence=confidence,
                    edge_pct=edge,
                    reason=f"Est temp {estimated_temp:.0f}°F, NOT in [{bracket_low:.0f}-{bracket_high:.0f}]°F, "
                           f"our prob {our_prob:.0%} vs market {yes_bid}¢",
                    current_temp_f=estimate["primary_temp"],
                    forecast_temp_f=estimate.get(f"forecast_{market_type}", 0) or 0,
                    surrounding_avg_f=estimate["surrounding_avg"],
                    market_yes_price=yes_bid,
                    is_tomorrow=is_tomorrow,
                    margin=nearest_edge,
                ))

    return signals


if __name__ == "__main__":
    print("\n=== Signal Generator ===\n")
    sigs = generate_signals()
    if not sigs:
        print("No signals generated. (Need weather data — run weather_collector.py first)")
    for s in sigs:
        print(s)
        print(json.dumps(s.to_dict(), indent=2))
        print()
