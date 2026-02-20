# CLI vs METAR Settlement Differences

## Background
Kalshi weather markets settle based on **NWS Daily Climate Report (CLI)**, NOT raw METAR observations. Understanding the differences is critical for our trading edge.

## What is CLI?
- NWS **Daily Climate Report** issued once daily (typically after midnight local time)
- Reports official daily high/low temperature for the climate day (midnight to midnight local)
- Published by NWS forecast offices for first-order stations
- Uses quality-controlled data from ASOS with manual corrections

## What is METAR?
- Routine aviation weather reports issued every ~20-60 minutes
- Reports current temperature (rounded to nearest °C, then converted to °F)
- Raw, automated readings without manual QC adjustments
- Max/min derived by scanning all METAR reports in the period

## Key Differences

### 1. Rounding
- **METAR:** Temps reported in °C rounded to nearest degree, then converted to °F. Creates ±1°F rounding artifacts.
- **CLI:** Uses higher-precision source data. May report values that don't match any individual METAR.
- **Impact:** 1-2°F differences are common due to rounding alone.

### 2. Time Window
- **METAR max/min:** Depends on observation frequency. If METAR reports every 53 min, a brief spike between reports is missed.
- **CLI:** Uses continuous ASOS recording (1-minute data internally), capturing true extremes.
- **Impact:** CLI high can be 1-3°F higher than max METAR if peak occurred between reports.

### 3. Quality Control
- **METAR:** Automated, no human review. Sensor errors pass through.
- **CLI:** NWS meteorologists review and may adjust for known sensor issues, maintenance periods, or erroneous readings.
- **Impact:** CLI may EXCLUDE a rogue high/low that METAR captured. Rare but significant when it happens.

### 4. Observation Time
- **METAR:** Available in near real-time.
- **CLI:** Published after midnight, sometimes delayed hours.
- **Impact:** We can estimate CLI from METAR during the day, but final CLI is only known next morning.

## Estimated Frequency of Differences

Based on NWS procedures and ASOS characteristics:

| Difference | Frequency (est.) | Cause |
|---|---|---|
| 0°F (exact match) | ~40-50% | Temp was stable around reporting times |
| ±1°F | ~35-40% | Rounding artifacts (°C→°F) |
| ±2°F | ~10-15% | Peak between METAR reports |
| ±3°F+ | ~2-5% | QC correction, sensor issue, or brief extreme |

**Conservative estimate:** CLI differs from max/min METAR by ≥1°F roughly 50-60% of the time.

## Per-City Considerations

### ATL (KATL)
- Large airport, reliable ASOS. CLI generally close to METAR.
- Summer afternoon thunderstorms can cause rapid temp swings between reports.

### MIA (KMIA)
- Maritime influence = more stable temps, fewer METAR gaps.
- But MIA has known forecast bias (ONBOARDING.md notes this).
- Higher std_dev needed (~4.65°F vs default 3.0°F).

### NYC (KNYC)
- Central Park station, NOT a standard ASOS. Unique reporting characteristics.
- CLI may use different observation source than what METAR shows.
- **This is our highest-risk station for CLI/METAR divergence.**

### BOS (KBOS), DCA (KDCA), PHL (KPHL)
- Standard ASOS stations. Relatively predictable CLI/METAR alignment.
- Sea breeze effects (BOS, PHL) can cause rapid temp changes.

## Trading Implications

1. **3°F safety margin is appropriate** — covers ~95%+ of CLI/METAR differences
2. **Lock-in signals based on METAR need caution** — CLI could differ by 1-2°F
3. **KNYC is highest risk** — non-standard station, verify CLI source
4. **OMO data would eliminate this gap** — 1-minute data = same source CLI uses

## Research Needed (Quantitative)
- [ ] Pull 30-60 days of CLI reports for all 6 stations from NWS archives
- [ ] Pull corresponding METAR max/min for same dates from IEM
- [ ] Calculate actual divergence statistics per station
- [ ] Identify if divergence correlates with weather patterns (fronts, storms)

**Note:** Quantitative analysis requires data access. IEM (mesonet.agron.iastate.edu) has both METAR archives and CLI products. Recommend pulling data programmatically for proper backtest.
