# Kalshi Settlement Stations - CONFIRMED FROM API

*Research date: Feb 16, 2026*
*Source: Kalshi API `rules_primary` and `rules_secondary` fields from live markets*

## Settlement Stations by City

| City | Kalshi Settlement Location | NWS CLI Code | NWS WFO URL | METAR Station |
|------|---------------------------|-------------|-------------|---------------|
| **NYC** | Central Park, New York | CLINYC | weather.gov/wrh/climate?wfo=okx | KNYC (Central Park ASOS) |
| **PHI** | Philadelphia International Airport | CLIPHL | weather.gov/wrh/climate?wfo=phi | KPHL |
| **MIA** | Miami International Airport | CLIMIA | weather.gov/wrh/climate?wfo=mfl | KMIA |
| **BOS** | Boston (Logan Airport), MA | CLIBOS | weather.gov/wrh/climate?wfo=box | KBOS |
| **DC** | Washington-National (DCA) | CLIDCA | weather.gov/wrh/climate?wfo=lwx | KDCA |
| **ATL** | Atlanta, GA | CLIATL | weather.gov/wrh/climate?wfo=ffc | KATL |

## Data Source Details

Kalshi settles ALL weather markets using the **NWS Climatological Report (Daily)** — NOT raw METAR, NOT AccuWeather, NOT any commercial source.

### Key Quotes from Rules

**rules_primary** (NYC example):
> "If the highest temperature recorded in Central Park, New York for [date] as reported by the National Weather Service's Climatological Report (Daily)..."

**rules_primary** (PHI example):
> "If the highest temperature recorded at Philadelphia International Airport for [date] as reported by the National Weather Service's Climatological Report (Daily)..."

**rules_secondary** (all cities):
> "Not all weather data is the same. While checking a source like AccuWeather or Google Weather may help guide your decision, the official and final value used to determine this market is the highest temperature as reported by the corresponding NWS Climatological Report (Daily)..."

> "Preliminary NWS reporting and measurement methods may be subject to underlying rounding and conversion nuances. Traders should exercise caution when interpreting preliminary NWS data."

## Comparison with Our Config

| City | Our Config `primary` | Kalshi Settlement Station | Match? |
|------|---------------------|--------------------------|--------|
| NYC | KNYC | Central Park (KNYC) | ✅ MATCH |
| PHI | KPHL | Philadelphia Intl (KPHL) | ✅ MATCH |
| MIA | KMIA | Miami Intl (KMIA) | ✅ MATCH |
| BOS | KBOS | Logan Airport (KBOS) | ✅ MATCH |
| DC | KDCA | Washington-National (KDCA) | ✅ MATCH |
| ATL | KATL | Atlanta (KATL) | ✅ MATCH |

**All 6 cities are correctly configured.** Our primary stations match Kalshi's settlement stations exactly.

## Critical Nuances

### 1. NWS CLI vs METAR
The NWS Climatological Report is **NOT** identical to raw METAR observations. The CLI report:
- May apply rounding differently
- Uses calibrated/quality-controlled data
- Can be updated/corrected after initial publication
- May differ from real-time METAR by 1-2°F in edge cases

### 2. NYC Special Case: Central Park
NYC settles on **Central Park** (station KNYC), NOT JFK/LGA/EWR airports. This is significant:
- Central Park is an urban park with unique microclimate
- Our config correctly uses KNYC as primary
- Our `metar_stations` list (KJFK, KLGA, KEWR) are for surrounding reference only
- Central Park tends to read slightly warmer than coastal airports in summer, cooler on clear winter nights

### 3. Settlement Timing
From `early_close_condition`:
> "Expiration will occur on the sooner of the first 7:00 or 8:00 AM ET following the release of the data, or one week after [date]."

Markets typically settle by 7-8 AM ET the next day when the NWS CLI report is published (~6-7 AM ET).

## NWS CLI Report URLs (Bookmark These)

- **NYC**: https://www.weather.gov/wrh/climate?wfo=okx → "Observed Weather" → "New York-Central Park, NY"
- **PHI**: https://www.weather.gov/wrh/climate?wfo=phi → "Philadelphia Intl Airport, PA"
- **MIA**: https://www.weather.gov/wrh/climate?wfo=mfl → "Miami Intl Airport, FL"
- **BOS**: https://www.weather.gov/wrh/climate?wfo=box → "Boston (Logan Airport), MA"
- **DC**: https://www.weather.gov/wrh/Climate?wfo=lwx → "Washington-National"
- **ATL**: https://www.weather.gov/wrh/climate?wfo=ffc → "Atlanta, GA"
