#!/usr/bin/env python3
"""
Signal generator for Kalshi weather trading.
Compares NWS observations + forecasts against Kalshi market prices.
Identifies mispriced temperature brackets and outputs trading signals.
"""

import json
import logging
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


def estimate_temp(city: str, target_date: str = None) -> dict | None:
    """
    Estimate the final high/low temperature for a city based on:
    - Current primary station reading
    - Surrounding station readings (trend detection)
    - NWS forecast (for the target date, defaults to today)
    """
    obs = get_latest_observations(city)
    forecast = get_latest_forecast(city, target_date=target_date)
    is_tomorrow = target_date is not None

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

    # V2 IMPROVEMENT #1: Weight primary station 70%, surrounding 30%
    # Kalshi settles on the primary station, not surrounding averages
    weighted_temp = primary_temp * 0.70 + surr_avg * 0.30

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

    if forecast_high is not None:
        estimated_high = forecast_high

        if is_tomorrow:
            # Tomorrow's markets: use NWS forecast directly, don't adjust with current temps
            high_confidence = 0.4
            log.info("Tomorrow estimate for %s: using NWS forecast %.0f°F (confidence %.0f%%)",
                     city, estimated_high, high_confidence * 100)
        else:
            # V2: Use weighted temp (70% primary, 30% surrounding) for adjustments
            # Adjustment: if current temp already exceeds forecast, adjust up
            if weighted_temp > forecast_high - 2:
                adjustment = (weighted_temp - forecast_high + 2) * 0.7
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

        # MIA high temp bias
        if city == "MIA":
            estimated_high += 2.5
            log.info("MIA high temp bias: adjusted high estimate up 2.5°F to %.1f°F", estimated_high)

        if not is_tomorrow:
            # Time-based confidence (today only)
            if 12 <= now_et_hour <= 16:
                high_confidence += 0.2
            elif 10 <= now_et_hour <= 18:
                high_confidence += 0.1

    # Estimate final low temp
    estimated_low = None
    low_confidence = 0.5

    if forecast_low is not None:
        estimated_low = forecast_low

        if is_tomorrow:
            low_confidence = 0.4
            log.info("Tomorrow low estimate for %s: using NWS forecast %.0f°F", city, estimated_low)
        else:
            # V2 IMPROVEMENT #3: Stronger cloud/wind adjustments for overnight lows
            if cloud_cover in ("CLR", "FEW", "SKC") and wind_mph < 5:
                estimated_low -= 3.5
                low_confidence += 0.15
            elif cloud_cover in ("CLR", "FEW", "SKC") and wind_mph < 10:
                estimated_low -= 2.0
                low_confidence += 0.1
            elif cloud_cover in ("OVC", "BKN") and wind_mph > 15:
                estimated_low += 2.5
                low_confidence += 0.15
            elif cloud_cover in ("OVC", "BKN") and wind_mph > 8:
                estimated_low += 1.5
                low_confidence += 0.1

        if not is_tomorrow:
            # Evening: current temp gives strong signal for overnight low
            if 20 <= now_et_hour or now_et_hour <= 4:
                # Current temp is close to what low will be
                estimated_low = min(primary_temp, estimated_low)
                low_confidence += 0.15

        # MIA overnight bias: airport runs ~2.5°F cooler than surrounding areas overnight
        if city == "MIA" and (20 <= now_et_hour or now_et_hour <= 6):
            estimated_low -= 2.5
            log.info("MIA overnight bias: adjusted low estimate down 2.5°F to %.1f°F", estimated_low)

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

    for city_name, city_config in CONFIG["cities"].items():
        for date_str in date_strs:
            # Use correct forecast for each date
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
                        estimate["high_confidence"], min_edge
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
                        estimate["low_confidence"], min_edge
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
                      min_edge: float) -> list[Signal]:
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
        # V2 IMPROVEMENT #2: Time-based std_dev — afternoon = near-certain, morning = wider
        import math
        now_et_hour = (datetime.now(timezone.utc).hour - 5) % 24
        
        base_std = 4.0 - confidence * 2.0  # 2-4°F base
        
        if market_type == "high":
            if 14 <= now_et_hour <= 17:  # 2-5pm ET: high is nearly locked
                std_dev = base_std * 0.4  # 60% tighter
            elif 11 <= now_et_hour <= 13:  # 11am-1pm: getting close
                std_dev = base_std * 0.7  # 30% tighter
            else:
                std_dev = base_std
        elif market_type == "low":
            if 4 <= now_et_hour <= 7:  # 4-7am ET: low is nearly locked
                std_dev = base_std * 0.4
            elif 0 <= now_et_hour <= 3:  # midnight-3am: getting close
                std_dev = base_std * 0.7
            else:
                std_dev = base_std
        else:
            std_dev = base_std
        
        std_dev = max(1.0, std_dev)  # V2: allow tighter than v1's 1.5 floor
        
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
