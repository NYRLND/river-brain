# CLAUDE.md: River Brain

## What this is
A gift PWA for the user's dad, who lives on a floating home on Hayden Island (Portland, OR).
It explains why the Columbia River under his house is rising or falling, split into tide,
Bonneville Dam release, and everything else. He is scientific (chemistry/biology teacher,
engineer): **accuracy and method transparency matter more than polish.**

## Working agreement
* The user reviews and learns; Claude writes the code. **Explain key decisions briefly as
  you go.**
* Verify external APIs live before relying on them (several changed recently).
* Report results honestly, including negative results and out-of-sample scores.

## Hard constraints
* **Zero ongoing cost.** No paid APIs, no runtime LLM calls.
* Architecture: an hourly GitHub Action (Python) fetches data, runs the analysis and writes
  JSON → a static PWA on GitHub Pages reads it.

## Status
* **Phase 1 (feasibility): done.** `notebooks/01_feasibility.ipynb`, README "Phase 1".
* **Phase 2 (production pipeline): done.** `riverbrain/` package, 5-year fit
  (`model/fit_report.md`), hourly run verified live 2026-09-24, workflows written. **Not yet
  pushed** at the time; now deployed (see below).
* **Phase 3 (UI): built** (`site/`: index.html, app.css, app.js, chart.js, sw.js, manifest,
  icons). No framework or build step; views are Now/Forecast/Explore/Fish/Chemistry/Method.
  Set `REPO` in `site/app.js` once the GitHub repo exists.
* **Deployed 2026-09-24:** repo https://github.com/NYRLND/river-brain (public), site
  https://nyrlnd.github.io/river-brain/ (Pages via Actions), hourly workflow verified green.
  Commits use the no-reply email 265278505+NYRLND@users.noreply.github.com (repo-local git
  config); never commit the user's personal email. `gh` is at
  "C:\Program Files\GitHub CLI\gh.exe" (may not be on PATH in older shells).
  USGS_API_KEY secret: not yet set (the user adds it; never handle the key).
* **Update trigger:** GitHub's `schedule` never fired for this repo (5 slots missed on day 1),
  so cron-job.org (user's account) POSTs to the workflow_dispatch API at :00 and :30 with a
  fine-grained PAT (NYRLND/river-brain only, Actions read/write). The token is stored only at
  cron-job.org; it expires within a year and must be renewed (cron-job.org emails on failure).
  The workflow's own cron (:17/:47) is kept as a backup. `nextUpdate()` in app.js assumes :00/:30.
* **Next:** Tier 2 items in `docs/feature-plan.md`. Model to-dos: overtides × low-flow for flood–ebb asymmetry; flow-dependent Bonneville
  lag (guide analysis: median 8 h < 120 kcfs → ~20 h > 250 kcfs). Keep guide prose numbers in
  sync with the fit when refitting (prose says "September 2026 fit").

## Repo layout
```
riverbrain/config.py            site IDs, thresholds, run windows
riverbrain/sources.py           fetchers (optional Cache; USGS_API_KEY env; USACE CA bundle)
riverbrain/qc.py                Bonneville QC + Dataquery/CDA merge
riverbrain/signal.py            godin, analytic (Hilbert), fill_short_gaps, trailing_mean, hold_last
riverbrain/features.py          build_inputs + build_features: the ONE feature definition (fit = hindcast = live)
riverbrain/model.py             OLS, grid search, components, forecast, hindcast, strict JSON
riverbrain/fit.py / report.py   offline fit → model/coefficients.json + model/fit_report.md
riverbrain/run.py / outputs.py  hourly run → site/data/*.json (+ forecast archive)
model/                          fitted coefficients + report (committed; refit via PR)
site/                           the PWA (app.js views, chart.js SVG charts, sw.js network-first); site/data/ is generated (gitignored)
scripts/make_icons.py           renders site/icon-*.png from the icon.svg geometry
site/guide.html + guide.js      long-form guide (the "wiki"); live tables from data/model.json
scripts/make_guide_data.py      site/guide/travel_time.json + copies figures (run after each refit)
tests/                          offline pytest suite (synthetic data)
.github/workflows/              hourly.yml, refit.yml, ci.yml
notebooks/01_feasibility.py     Phase 1 jupytext source (EDIT THIS, then regenerate the .ipynb)
notebooks/01_feasibility.ipynb  executed notebook (committed with outputs)
notebooks/sources.py            Phase 1 fetchers, frozen for reproducibility (production code is riverbrain/)
certs/                          DigiCert intermediate for the USACE Dataquery TLS chain
docs/figures/                   PNGs saved by the notebook (used in README)
docs/feature-plan.md            app feature roadmap
```

## Data sources: verified 2026-09-23 (details and gotchas in README)
* USGS Water Data API **v1**: `https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items`.
  NOT waterservices.usgs.gov (decommissioned Q1 2027). Use `f=csv`, chunk by month (10k-row limit).
  * 14144700 Columbia at Vancouver: `00065` stage (15-min). Also 72137, 00060, turbidity, SSC.
  * 14211720 Willamette at Portland: `00060` Q is **5-min and reverses sign with the tide**;
    also real-time water quality (DO, pH, SpC, temp, nitrate, fDOM, fChl, fPC, turbidity).
  * `72137` tide-filtered discharge lags ~36 h, so it can't be used for nowcasting.
* NOAA CO-OPS 9440083 (Vancouver) predictions, 6-min. **High-pass them (Godin) before use**:
  they contain a seasonal river signal and the MSf spring–neap term. 9439040 Astoria for surge.
* USACE Bonneville `BON.Flow-Out.Ave.1Hour.1Hour.CBT-REV`: Dataquery 2.0 is primary (needs
  `certs/` appended to certifi; the server omits its intermediate). CWMS Data API
  (`cwms-data.usace.army.mil`, office NWDP) is the fallback (it had 73 missing hours in June 2026).
  Also verified: `BON.Flow-Spill…`, `BON.Flow-Gen…`, `BON.Elev-Forebay.Inst.1Hour.0.CBT-REV`.
* NWPS `api.water.noaa.gov/nwps/v1/gauges/VAPW1/stageflow`: current forecast only (archive it).
* DART `cbr.washington.edu/dart/cs/php/rpt/adult_daily.php?outputFormat=csv&proj=BON&avg=1`:
  drop the fake Feb 29 row.

## Datums
USGS gage datum = NGVD29 + 1.82 ft. NWPS stage ≈ USGS + 0.13 ft (flood stages 15/16/20/25 ft
are NWPS datum). NOAA MLLW ≈ USGS − 1.69 ft. Always state which datum a number is in.

## Model decisions
* **Production model M8** (5-year fit, leave-one-water-year-out CV RMSE 0.42 ft, R² 0.97):
  flow-dependent tide (T, HT, each also × trailing-24h Bonneville/100) + Bonneville
  trailing-24h kernel (τ = 1 h) + Q² + Willamette (trailing 25-h mean) + spring–neap
  (Godin-filtered tidal envelope) + Astoria surge (trailing 25-h mean) + Sandy River
  (trailing 12-h mean; probably also a proxy for other local rain-fed streams, so say so in the UI).
* Model selection is by the pre-declared `SELECTION_RULE` in `fit.py`: never hand-pick after
  seeing results. New candidate terms go into `MODELS` and compete.
* Bonneville → Vancouver centroid lag ≈ 12.5 h.
* Forecast: flows persist from their last observation; the current error (mean over 3 h)
  decays with an e-folding time of 48 h (chosen by hindcast). The band is the 5–95% hindcast
  error at each lead.
* **All flow features must be causal (trailing windows).** Only tide-derived terms may use
  future predictions.
* Attributions are presented as *changes* over 3/6/24 h (levels need a reference, deltas
  don't). Always show "unexplained".
* Rejected: single-hour lag, flow-dependent spring–neap, overtides, fast Bonneville kernel,
  Willamette² (each < 1% CV gain), USGS 72137 (36 h latency).

## Conventions
* Store everything in UTC; display in America/Los_Angeles. Stage in ft, flow in kcfs.
* One color per component everywhere (notebook and app): tide `#2a78d6`, Bonneville
  `#eb6834`, Willamette `#1baf7a`, spring–neap `#4a3aa7`, ocean `#e87ba4`, unexplained gray.
* Sandy River component color: `#eda100`.
* Bonneville QC: `riverbrain/qc.py` (range, spike, flatline, fill gaps ≤ 3 h only).
* UI: insert data-derived text with textContent only (never innerHTML). Charts keep one
  y-scale per chart (no dual axes); component small multiples share a scale.
* JSON outputs must be strict (no NaN/Infinity): always write through `model.save`/`dumps`.
* Timestamps in JSON: ISO UTC with `Z`, seconds precision (tide times to the minute).

## Rate limits
USGS Water Data API: 1,000 requests/hour/IP anonymous (we hit it twice fitting). The fit waits
out `Retry-After` and resumes from the cache in `data/raw/fit/`. Set `USGS_API_KEY`.
The hourly run makes about 12 USGS requests.

## Local environment quirks (Windows)
* Windows Application Control blocks SciPy's DLLs and the venv `Scripts\*.exe` launchers.
  Run tools as `.venv/Scripts/python -m jupytext|nbconvert|pip …`. Don't add SciPy (a numpy
  FFT Hilbert transform is in `riverbrain/signal.py`). Don't try to change the security setting.
* Tests: `.venv/Scripts/python -m pytest -q`. Preview the site: `.claude/launch.json` config "site".
* Regenerate the notebook: `cd notebooks && ../.venv/Scripts/python -m jupytext --to ipynb 01_feasibility.py && ../.venv/Scripts/python -m nbconvert --to notebook --execute --inplace 01_feasibility.ipynb`
