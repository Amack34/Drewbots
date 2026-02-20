# OMO (One-Minute Observation) Data Research

## What is OMO?
ASOS stations record temperature, wind, pressure, etc. every minute. Standard METAR reports are only every ~20-60 min. OMO gives us 1-minute granularity — critical for tracking exact high/low temperatures intraday for Kalshi settlement.

## Data Sources

### 1. MADIS (madis.ncep.noaa.gov)
- **What:** NCEP's Meteorological Assimilation Data Ingest System
- **Data types:** METAR, mesonet, maritime, CRN, road weather, citizen weather
- **OMO availability:** MADIS aggregates surface obs but primarily ingests METAR-frequency data. True 1-minute ASOS data is NOT directly available through standard MADIS feeds.
- **Access:** Free for government/research. Requires registration. Data is in netCDF/CSV format.
- **Limitations:** Not real-time 1-minute resolution. Better for bulk historical than live trading signals.

### 2. Synoptic Data API (synopticdata.com)
- **What:** Commercial weather data API aggregating 50,000+ stations
- **OMO availability:** Synoptic ingests data at "reporting frequency of the station" — for ASOS this could include sub-hourly obs. Need to verify if true 1-minute data is available vs 5-minute aggregates.
- **Pricing tiers:**
  - 14-day free trial available
  - Open Access: free for non-commercial/research use
  - Commercial: tiered pricing (Startup/Professional/Enterprise), custom quotes
  - NOAA employees: free via National Mesonet Program
- **Features:** Real-time API, quality control, precipitation service, ArcGIS layers, push streaming
- **Best path:** Start with 14-day free trial to evaluate 1-minute data availability for our 6 stations (KNYC, KPHL, KMIA, KBOS, KDCA, KATL)

### 3. Iowa Environmental Mesonet (IEM) - mesonet.agron.iastate.edu
- **What:** Free, well-known source for ASOS/AWOS data
- **OMO:** IEM archives 1-minute ASOS data for many stations
- **Access:** Free, no registration. CSV download.
- **Limitation:** May have delays (not true real-time). Good for backtesting.

### 4. NCDC/NCEI (ncei.noaa.gov)
- **What:** NOAA's climate data archive
- **OMO:** Has 1-minute ASOS data (DSI-6406) but access is clunky and delayed
- **Best for:** Historical analysis, not real-time trading

## Recommendation

**For live trading (real-time):**
1. **Start with Synoptic Data free trial** — test if 1-min ASOS data is available for our stations
2. If confirmed, evaluate commercial pricing vs edge value

**For backtesting (historical):**
1. **Iowa Environmental Mesonet** — free 1-minute ASOS archives
2. NCEI DSI-6406 as backup

## Next Steps
- [ ] Sign up for Synoptic Data 14-day trial
- [ ] Query our 6 stations for 1-minute data availability
- [ ] Compare OMO temp readings vs METAR for settlement accuracy
- [ ] Calculate edge improvement from OMO (how many minutes earlier can we detect high/low?)

## Edge Value
OMO lets us detect temperature trends 20-59 minutes earlier than METAR. For lock-in signals, this could mean entering positions at better prices before the market moves on METAR updates. Estimated edge improvement: significant for lock-in strategy.
