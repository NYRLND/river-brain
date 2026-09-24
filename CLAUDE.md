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
* **Phase 1 (feasibility): done.** See `README.md` (findings, recommended production
  approach) and `notebooks/01_feasibility.ipynb`.
* **Next:** the production pipeline plus a multi-year model fit, then the MVP UI. The
  feature roadmap is in `docs/feature-plan.md`.

## Repo layout
```
notebooks/01_feasibility.py     jupytext percent source (EDIT THIS, then regenerate the .ipynb)
notebooks/01_feasibility.ipynb  executed notebook (committed with outputs)
notebooks/sources.py            fetchers for every source; cache to data/raw/ (gitignored)
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

## Model decisions (from Phase 1)
* Recommended **M5**: flow-dependent tide (NOAA oscillation T and its Hilbert quadrature,
  each × trailing-24h Bonneville mean) + Bonneville via a trailing 24-h kernel (+ Q²) +
  Willamette (trailing 25-h mean) + spring–neap setup (Godin-filtered tidal envelope).
  Season out-of-sample R² 0.92, RMSE 0.34 ft.
* Bonneville → Vancouver centroid lag ≈ 12 h (± 3).
* **All flow features must be causal (trailing windows).** Only tide-derived terms may use
  future predictions.
* Attributions are presented as *changes* over 3/6/24 h (levels need a reference, deltas
  don't). Always show "unexplained".
* Rejected or deferred: single-hour lag, flow-dependent spring–neap (M5b), Astoria surge
  (M6, overfits summer data; re-test with winter data), USGS 72137.
* Production should fit on 2–3+ years offline → `coefficients.json`; the hourly job only
  applies coefficients.

## Conventions
* Store everything in UTC; display in America/Los_Angeles. Stage in ft, flow in kcfs.
* One color per component everywhere (notebook and app): tide `#2a78d6`, Bonneville
  `#eb6834`, Willamette `#1baf7a`, spring–neap `#4a3aa7`, ocean `#e87ba4`, unexplained gray.
* Bonneville QC: `qc_flow()` in the notebook (range, spike, flatline, fill gaps ≤ 3 h only).

## Local environment quirks (Windows)
* Windows Application Control blocks SciPy's DLLs and the venv `Scripts\*.exe` launchers.
  Run tools as `.venv/Scripts/python -m jupytext|nbconvert|pip …`. Don't add SciPy (a numpy
  FFT Hilbert transform is in the notebook). Don't try to change the security setting.
* Regenerate the notebook: `cd notebooks && ../.venv/Scripts/python -m jupytext --to ipynb 01_feasibility.py && ../.venv/Scripts/python -m nbconvert --to notebook --execute --inplace 01_feasibility.ipynb`
