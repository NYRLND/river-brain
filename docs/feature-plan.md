# River Brain: app feature plan

Audience: one scientifically minded reader (chemistry and biology teacher, engineer) who
lives on the river. Design principles:

* **Show your work.** Every number can be expanded to show the method, the data source,
  the data's age and its uncertainty. No black boxes.
* **Physics first.** Every explanation is a mechanism he can check against the river
  outside the window.
* **Honest uncertainty.** "Unexplained" is always shown as its own bar. Stale data is
  flagged, never hidden.
* **Zero cost.** Everything comes from free public APIs, computed in the hourly GitHub
  Action, and ships as static JSON. No runtime LLMs or paid services.

Status key: ✅ data source verified live · 🔎 exists but endpoint or name still to verify ·
🧮 computed from data we already have.

---

## Tier 1: MVP (the core question)

### 1. "Now" card
* Current stage, trend arrow, rate (ft/h), next high/low water (time and height).
  ✅ USGS, 🧮 model
* **"Why it moved" bar:** the last 3 h, 6 h or 24 h change split into tide / Bonneville /
  Willamette / Sandy River and local streams / spring–neap / ocean (Astoria surge) /
  unexplained. Signed bars that sum to the observed change. 🧮 (`now.json → why_it_moved`, live)
* **"Already in the pipe":** Bonneville takes ~12 h to arrive, so the last 12 h of dam
  releases tell us what's coming. For example: "Dam cut 20 kcfs at 3 am; expect −0.3 ft
  arriving around 3 pm." ✅ Dataquery, 🧮
* Data-freshness strip: latest timestamp per source, plus QC status. 🧮

### 2. Next 48 hours
* Our forecast: flow-corrected tide (from NOAA predictions) + Bonneville in the pipe +
  persistence of the rest, with an uncertainty band from the residual RMSE. 🧮
* The NWS forecast overlaid (offset-corrected), with flood-stage lines (15/16/20/25 ft). ✅ NWPS

### 3. Method page ("Model card")
* The equation, every coefficient with its physical reading (for example "+10 kcfs at
  Bonneville → +0.22 ft here at current flow"), in- and out-of-sample fit statistics,
  training period and refit date. 🧮
* Links to the notebook and the GitHub repo. Download the last 30 days as CSV. 🧮

---

## Tier 2: drill-down for the scientist

### Hydraulics and engineering
* **Component explorer:** interactive time series (1 d → 1 yr) with toggles per component
  and a stacked "contribution" view. Hover crosshair reads every value. 🧮
* **Travel-time visualizer:** dam outflow and river stage on aligned axes, with a slider
  to shift the dam curve by τ and watch the correlation peak near 12 h. It's a hands-on
  version of notebook Section 6. 🧮
* **What-if sliders:** "If Bonneville releases 300 kcfs and the Willamette 40 kcfs, how
  high at the next spring tide?" Uses the fitted model and marks clearly where it
  extrapolates beyond the training range. 🧮
* **Dam operations:** Bonneville outflow split into **powerhouse vs spill**, with the daily
  load-following pattern and the weekend dip ("you can see the Northwest power grid in the
  river"). Also spill season for juvenile fish, and forebay elevation.
  ✅ `BON.Flow-Spill…`, `BON.Flow-Gen…`, `BON.Elev-Forebay…`
* **Gangway angle** (configurable gangway length and landing heights): today's angle and
  its min/max over the next 48 h. Practical, and very engineer. 🧮
* **Rating curve and hysteresis:** stage vs Bonneville flow scatter, colored by season,
  showing loops and the tidal "fuzz". 🧮

### Tide physics
* **Why the tide is bigger at low flow:** a live scatter of observed/predicted tidal
  amplitude vs flow (notebook fig 8a), with today's point highlighted. 🧮
* **Spring–neap calendar** with moon phase: spring tides lag new/full moon by ~1–2 days,
  and the fortnightly mean-level "setup". 🧮 (moon phase computed; no API)
* **Tide timing:** how late the high water arrives vs NOAA's prediction at current flow. 🧮
* **Explainer cards:** tidal friction, why the ebb is longer than the flood upriver,
  overtides, the flood wave as a diffusive wave. Short text plus one figure each.

### Historical context
* Today's stage and flow as a **percentile for this calendar date**, from USGS daily
  statistics since 1998 for stage and 1963 for discharge. ✅ USGS `daily`
* Flood history markers: 1948 (Vanport), 1964, 1996, 2011 freshet. 🔎 peaks collection
* Annual hydrograph: this year vs the median and 10th–90th band. ✅ USGS daily

### Forecast verification (science in action)
* Archive every NWS forecast and our own. Show **skill by lead time** (RMSE at 6/12/24/48 h)
  as it accumulates over weeks and months. 🧮 (needs the archive, from launch day onward)

---

## Tier 2: chemistry

Source: USGS 14211720 (Willamette at Portland, ~5 miles away), 15-minute real-time.
All ✅ verified live: water temp, dissolved O₂, pH, specific conductance, turbidity, nitrate,
fDOM, chlorophyll (fChl), phycocyanin (fPC), suspended sediment and load.

* **Dissolved-oxygen saturation:** compute saturation from temperature (and barometric
  pressure, from NWS observations 🔎) with the Benson–Krause equations. Plot measured DO vs
  saturation, which shows when the river is super- or under-saturated. 🧮
* **Diel photosynthesis cycle:** DO and pH rise in the afternoon and fall overnight as algae
  photosynthesize and then respire. It's CO₂–carbonate chemistry happening live. Plot a
  "typical day" averaged over the last 2 weeks. 🧮
* **Dilution and hysteresis:** specific conductance vs discharge. Snowmelt dilutes it, and
  first-flush storms spike it. 🧮
* **Nitrate and fDOM** vs flow and season. 🧮
* **Sediment:** turbidity/SSC and sediment load (tons/day) at both gauges. The Columbia at
  Vancouver also reports SSC and turbidity. ✅
* **Total dissolved gas below Bonneville:** spill entrains air, and Henry's law predicts
  supersaturation (110–125%), which regulators cap because it causes gas-bubble trauma in
  fish. A great chemistry + biology crossover. 🔎 USACE TDG stations below the dam (Cascade
  Island / Warrendale). The series names still need finding in Dataquery/CDA.

## Tier 2: biology

* **Fish passage today vs the 10-year average** for each species, plus year-to-date. ✅ DART
  For example, the week to Sep 22: adult Chinook 89% of the 10-yr average, jacks 130%,
  steelhead only 19%.
* **Run-timing curves:** cumulative % of the season's run, this year vs the 10-yr average.
  Early or late? 🧮 from DART
* **Species calendar:** spring/summer/fall Chinook, sockeye (Jun–Jul), steelhead,
  coho, shad (2.8 M this year, an introduced species), lamprey (night vs day counts). ✅
* **Temperature stress:** ladder and river water temperature against salmonid thresholds
  (stress above ~20 °C; it was 20.2 °C on Sep 9). Degree-days. ✅ DART TempC, USGS
* **Harmful algal bloom watch:** phycocyanin (a cyanobacteria pigment) and chlorophyll on the
  Willamette, with a plain note on what elevated values mean. Relevant for dogs and
  swimming. ✅ (a relative index, not a toxin measurement; say so)
* **Productivity:** chlorophyll + DO + pH together tell the algae story. 🧮

---

## Tier 3: later / nice to have
* **Snowpack and water-supply outlook:** NWRFC seasonal volume forecasts and NRCS SNOTEL
  for "how big will next spring's freshet be?" 🔎
* **Upstream system:** Grand Coulee / John Day storage, and flows at The Dalles. 🔎 Dataquery
* **Ocean influence:** Astoria surge once the model supports it (needs winter data). ✅ data
* **Weekly "river report"** card generated from templates (no LLM): the biggest mover,
  a fish highlight, a chemistry oddity.
* Units toggle (ft/m, kcfs/m³/s, °C/°F) and a print-friendly "lab report" view.

---

## How it fits the zero-cost architecture
* **Hourly Action** writes a small `now.json` (~50 KB): card, attributions, 48-h
  forecast, freshness.
* **Lazy-loaded panel files** written by the same run: `history_30d.json` (hourly
  components), `chem_14d.json`, `fish_season.json`, `model.json`. Each is < 200 KB,
  fetched only when a panel opens.
* **Daily archive commit** (`data/archive/YYYY/MM.json.gz`) supports the forecast-skill,
  percentile and history panels, and keeps scheduled workflows alive.
* **Front end:** a static PWA with a small time-series chart library (uPlot, ~45 KB) for
  interactive plots. A service worker caches the last JSON for offline viewing.
* One color per physical component, everywhere (tide blue, Bonneville orange, Willamette
  aqua, Sandy River yellow, spring–neap violet, ocean magenta, unexplained gray), matching
  the notebook figures.

## Suggested build order
1. ~~Production pipeline (fetch → QC → features → `now.json`) plus a multi-year model fit.~~ Done (Phase 2).
2. MVP UI: Now card, why-it-moved, next 48 h, model card.
3. Component explorer, travel-time visualizer, dam operations.
4. Fish + chemistry panels (data is already verified; mostly UI work).
5. Archive-dependent features (skill scores, history) once data accrues.
