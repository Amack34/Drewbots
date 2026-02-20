# Microclimate & Settlement Accuracy Analysis

*Research date: Feb 16, 2026*

## Urban Heat Island (UHI) Effects by City

The Urban Heat Island effect is critical because Kalshi settles on specific stations that may or may not reflect broader city temperatures.

### NYC — Central Park (KNYC)
- **UHI magnitude**: 5-8°F above rural surroundings on calm, clear nights
- **Central Park specifics**: Park itself is a **cool island** within Manhattan's UHI
  - Summer nights: Central Park is 2-4°F cooler than surrounding streets
  - Summer days: Minimal difference (solar radiation dominates)
  - Winter: Less pronounced, 1-3°F difference
- **vs Airport stations**: Central Park reads **warmer** than JFK/LGA on summer afternoons (less coastal cooling), **cooler** than JFK/LGA on some winter days (coastal moderation at airports)
- **Key differential**: Central Park high temps can differ from JFK by 3-5°F in summer, 1-3°F in winter
- **Trading implication**: Don't use JFK/LGA METAR as direct proxy — Central Park has its own microclimate

### PHI — Philadelphia International Airport (KPHL)
- **UHI magnitude**: 4-7°F downtown vs rural on clear nights
- **Airport location**: Southwest of city, near Delaware River
- **Characteristics**: Airport captures some UHI but also river cooling
- **vs Downtown**: Airport runs 1-2°F cooler than downtown on summer nights, similar during day
- **Seasonal bias**: Slight coastal influence from Delaware Bay in spring/summer (fog, moderation)
- **Trading implication**: KPHL is a reasonable proxy; no major systematic bias to exploit

### MIA — Miami International Airport (KMIA)
- **UHI magnitude**: 3-5°F vs Everglades (moderate due to coastal influence)
- **Airport location**: Inland from coast, surrounded by urban development
- **Coastal effects**: 
  - Sea breeze typically arrives 10 AM-12 PM, capping afternoon highs 2-4°F below inland locations
  - Airport is 8 miles inland — partially shielded from immediate sea breeze
  - On strong sea breeze days, coastal stations (MIA Beach) can be 5-8°F cooler than KMIA
- **Humidity**: Very high humidity means heat index and actual temp diverge, but Kalshi only uses dry-bulb
- **Trading implication**: KMIA is slightly warmer than pure coastal readings but cooler than deep inland; relatively predictable in tropical climate

### BOS — Logan Airport (KBOS)
- **UHI magnitude**: 4-6°F vs western suburbs on clear nights
- **Airport location**: On a peninsula in Boston Harbor — HEAVY maritime influence
- **Coastal effects**:
  - Sea breeze can drop temps 10-15°F in minutes during summer
  - Fog is common (reduces highs)
  - Winter: Harbor moderates, Logan is often 2-5°F warmer than inland suburbs
- **vs Downtown**: Logan and downtown Boston are both maritime-influenced; minimal difference
- **Key risk**: Summer sea breeze timing is highly variable — forecast model uncertainty is HIGH
- **Trading implication**: BOS has the **highest forecast uncertainty** of our 6 cities due to sea breeze effects. Wider brackets may be underpriced.

### DC — Washington-National (KDCA / Reagan Airport)
- **UHI magnitude**: 5-9°F (DC has one of the strongest UHIs on the East Coast)
- **Airport location**: On the Potomac River, very close to downtown
- **Characteristics**:
  - DCA is an urban station — captures full UHI effect
  - Potomac River provides some moderation
  - vs Dulles (KIAD): DCA typically runs 3-5°F warmer in winter, 1-3°F in summer
- **Seasonal patterns**: 
  - Summer: DCA records some of the highest temps on the East Coast due to UHI + inland position
  - Winter: River moderation prevents extreme cold
- **Trading implication**: DCA skews warm. NWS forecasts for "Washington DC" may not account for DCA's warm bias. Check if NWS point forecast matches DCA's historical warm skew.

### ATL — Hartsfield-Jackson Airport (KATL)
- **UHI magnitude**: 4-7°F vs rural Georgia
- **Airport location**: 7 miles south of downtown, large impervious surface area (one of world's busiest airports)
- **Characteristics**:
  - Massive tarmac/runway complex acts as heat source
  - Elevation: 1,026 ft — highest of our 6 cities, affects absolute temps
  - No significant water body influence
- **vs Downtown**: Minimal systematic difference; both urban-heated
- **Trading implication**: KATL is well-characterized by NWS models; less microclimate uncertainty than coastal cities

## Airport vs Downtown Temperature Differentials Summary

| City | Settlement Station | Downtown Differential (Day) | Downtown Differential (Night) |
|------|-------------------|---------------------------|------------------------------|
| NYC | Central Park | IS downtown (park) | IS downtown (park) |
| PHI | Airport | -1 to 0°F vs downtown | -1 to -2°F vs downtown |
| MIA | Airport | 0 to +1°F vs coast | +1 to +2°F vs coast |
| BOS | Airport (harbor) | -1 to 0°F vs downtown | +1 to +2°F vs downtown |
| DC | Airport (river) | 0 to +1°F vs downtown | +1 to +3°F vs downtown |
| ATL | Airport | -1 to 0°F vs downtown | 0 to -1°F vs downtown |

## Implications for Trading

### High Uncertainty Cities (Wider spread = potential edge)
1. **BOS** — Sea breeze variability makes forecasting hardest. Summer tail brackets may be underpriced.
2. **NYC** — Central Park microclimate differs from surrounding stations. Most surrounding METAR won't perfectly predict it.
3. **DC** — Strong UHI means DCA reads warm; models may underestimate highs in summer.

### Low Uncertainty Cities (Tight forecasting = consistent small edge)
1. **ATL** — Inland, no coastal effects, well-modeled
2. **PHI** — Airport well-characterized
3. **MIA** — Tropical climate = narrow temperature range, but sea breeze timing adds some uncertainty

### METAR Cross-Validation Strategy
For each city, compare settlement station METAR with surrounding stations:
- **If surrounding stations agree**: High confidence, bet larger
- **If surrounding stations diverge**: Microclimate effects at play, reduce position size
- **Key differential threshold**: If settlement station reads >3°F different from average of surrounding stations, investigate why before trading
