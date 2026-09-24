"""Build the JSON files the PWA reads. Pure functions of already-fetched data (easy to test).

now.json           the card: stage, trend, why-it-moved, what's in the pipe, 48-h forecast,
                   NWS forecast, drivers, data freshness, warnings
history_30d.json   hourly columnar arrays for charts (components, flows)
model.json         the fitted model: equation, coefficients, CV and forecast skill
fish.json          Bonneville adult passage, season to date, with 10-year averages
chem.json          Willamette water quality, 14 days hourly, plus DO saturation
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

SCHEMA = 1
COMPONENT_ORDER = ["tide", "bonneville", "willamette", "sandy", "spring_neap", "ocean"]


def _t(ts, unit: str = "s") -> str | None:
    """ISO-8601 UTC with a Z suffix, rounded to `unit` ("s" or "min")."""
    if ts is None or pd.isna(ts):
        return None
    t = pd.Timestamp(ts).tz_convert("UTC").round(unit)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ" if unit == "s" else "%Y-%m-%dT%H:%MZ")


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


# --- small calculations ------------------------------------------------------------
def trend_ft_per_h(stage15: pd.Series, t_end: pd.Timestamp, minutes: int = 60) -> float | None:
    """Least-squares slope of 15-min stage over the last `minutes`."""
    s = stage15.loc[t_end - pd.Timedelta(minutes=minutes):t_end].dropna()
    if len(s) < 3:
        return None
    x = (s.index - s.index[0]) / pd.Timedelta("1h")
    return float(np.polyfit(x, s.to_numpy(), 1)[0])


def direction(rate: float | None, steady: float = 0.05) -> str:
    if rate is None:
        return "unknown"
    return "rising" if rate > steady else "falling" if rate < -steady else "steady"


def extrema(s: pd.Series, max_n: int = 4) -> list[dict]:
    """Local highs/lows of an hourly series, refined by fitting a parabola through each
    extreme and its neighbors (≈ ±10 min timing at hourly resolution)."""
    v = s.to_numpy()
    out = []
    for i in range(1, len(v) - 1):
        if not np.isfinite(v[i - 1:i + 2]).all():
            continue
        kind = "high" if v[i] > v[i - 1] and v[i] >= v[i + 1] else "low" if v[i] < v[i - 1] and v[i] <= v[i + 1] else None
        if not kind:
            continue
        denom = v[i - 1] - 2 * v[i] + v[i + 1]
        dx = 0.5 * (v[i - 1] - v[i + 1]) / denom if denom != 0 else 0.0
        dx = float(np.clip(dx, -0.5, 0.5))
        out.append({"type": kind, "time": _t(s.index[i] + pd.Timedelta(hours=dx), "min"),
                    "stage_ft": _r(v[i] - 0.25 * (v[i - 1] - v[i + 1]) * dx, 2)})
        if len(out) >= max_n:
            break
    return out


def do_saturation_mg_l(temp_c):
    """Dissolved-oxygen solubility in fresh water at 1 atm (Benson & Krause 1984; APHA 4500-O)."""
    T = np.asarray(temp_c, dtype=float) + 273.15
    return np.exp(-139.34411 + 1.575701e5 / T - 6.642308e7 / T ** 2 + 1.243800e10 / T ** 3 - 8.621949e11 / T ** 4)


def nwps_offset(nwps_obs: pd.Series, stage15: pd.Series, days: int = 7) -> float | None:
    """Median (NWPS observed − USGS) over recent days, matching times within 5 min."""
    if nwps_obs.dropna().empty or stage15.dropna().empty:
        return None
    n = nwps_obs.dropna()
    n = n[n.index > n.index.max() - pd.Timedelta(days=days)]
    u = stage15.dropna().reindex(n.index, method="nearest", tolerance=pd.Timedelta("5min"))
    d = (n - u).dropna()
    return float(d.median()) if len(d) >= 24 else None


def freshness(latest: dict, t_run: pd.Timestamp, future_ok: bool) -> dict:
    out = {}
    for name, ts in latest.items():
        if name == "tide_predictions":
            out[name] = {"covers_forecast": bool(future_ok), "status": "ok" if future_ok else "missing"}
            continue
        if ts is None or pd.isna(ts):
            out[name] = {"latest": None, "age_h": None, "status": "missing"}
            continue
        age = (t_run - pd.Timestamp(ts)) / pd.Timedelta("1h")
        out[name] = {"latest": _t(ts), "age_h": _r(age, 1),
                     "status": "stale" if age > cfg.STALE_HOURS.get(name, 6) else "ok"}
    return out


def spring_neap_state(sn: pd.Series, t_now: pd.Timestamp, q: dict) -> dict:
    """Where we are in the ~14.8-day spring–neap cycle, and when the next spring/neap peaks are."""
    if sn.dropna().empty or t_now not in sn.index or pd.isna(sn.get(t_now)):
        return {}
    v = float(sn[t_now])
    label = ("spring tides" if q and v >= q["p75"] else "neap tides" if q and v <= q["p25"] else "between spring and neap")
    fut = sn.loc[t_now:].dropna()
    peaks = {"next_spring": None, "next_neap": None}
    a = fut.to_numpy()
    for i in range(1, len(a) - 1):
        if peaks["next_spring"] is None and a[i] > a[i - 1] and a[i] >= a[i + 1]:
            peaks["next_spring"] = _t(fut.index[i])
        if peaks["next_neap"] is None and a[i] < a[i - 1] and a[i] <= a[i + 1]:
            peaks["next_neap"] = _t(fut.index[i])
    trend = "toward spring" if len(a) > 1 and a[1] > a[0] else "toward neap"
    return {"index_ft": _r(v), "state": label, "trend": trend, **peaks}


# --- file builders -----------------------------------------------------------------
def build_now(*, t_run, t_now, stage15, comp, fc, coef, inp, nwps_obs, nwps_fcst, nwps_issued,
              latest, extra_warnings=()) -> dict:
    """The main card. `comp` = nowcast components (hourly), `fc` = forecast from t_now."""
    spec = coef["spec"]
    comps = [c for c in COMPONENT_ORDER if c in comp.columns]
    warnings = list(extra_warnings)

    # Now
    stage_now = stage15.dropna()
    t_obs = stage_now.index[-1] if len(stage_now) else None
    rate = trend_ft_per_h(stage15, t_obs) if t_obs is not None else None
    fut = fc["forecast"]

    # Why it moved: change over the last h hours, split by component
    attribution = {}
    for h in cfg.ATTRIBUTION_HOURS:
        t0 = t_now - pd.Timedelta(hours=h)
        if t0 not in comp.index or pd.isna(comp.at[t_now, "observed"]) or pd.isna(comp.at[t0, "observed"]):
            attribution[f"{h}h"] = None
            continue
        d = {c: _r(comp.at[t_now, c] - comp.at[t0, c]) for c in comps}
        d["unexplained"] = _r(comp.at[t_now, "unexplained"] - comp.at[t0, "unexplained"])
        attribution[f"{h}h"] = {"from": _t(t0), "to": _t(t_now),
                                "observed_change_ft": _r(comp.at[t_now, "observed"] - comp.at[t0, "observed"]),
                                "components_ft": d}

    # In the pipe: Bonneville's effect over the next hours if the dam holds its current release
    bon = inp["bon"].dropna()
    pipe = None
    if len(bon) and "bonneville" in fc:
        b0 = fc["bonneville"].iloc[0]
        ahead = {f"{h}h": _r(fc["bonneville"].iloc[h] - b0) for h in (6, 12, 24) if h < len(fc)}
        def q_at(hours_ago):
            t = bon.index[-1] - pd.Timedelta(hours=hours_ago)
            return _r(bon.get(t, np.nan), 1)
        pipe = {"bonneville_latest_kcfs": _r(bon.iloc[-1], 1), "bonneville_latest_time": _t(bon.index[-1]),
                "bonneville_12h_ago_kcfs": q_at(12), "bonneville_24h_ago_kcfs": q_at(24),
                "lag_centroid_h": spec["tau"] + (spec["width"] - 1) / 2,
                "expected_change_ft": ahead,
                "assumes": "Bonneville release stays at its latest value"}

    # Forecast with uncertainty from hindcast error quantiles (err = forecast − observed)
    skill = coef["forecast"]["skill_ft"]
    rows = []
    for t, r in fc.iterrows():
        k = str(int(r["lead_h"]))
        sk = skill.get(k)
        lo = r["forecast"] - sk["p95"] if sk else None
        hi = r["forecast"] - sk["p05"] if sk else None
        rows.append({"t": _t(t), "stage_ft": _r(r["forecast"], 2), "lo_ft": _r(lo, 2), "hi_ft": _r(hi, 2),
                     **{c: _r(r[c]) for c in comps}})

    # NWS forecast, shifted onto the USGS datum
    off = nwps_offset(nwps_obs, stage15)
    nws = None
    if nwps_fcst is not None and len(nwps_fcst.dropna()):
        o = off if off is not None else 0.13
        nws = {"issued": nwps_issued, "offset_ft_nwps_minus_usgs": _r(o),
               "points": [[_t(t), _r(v - o, 2)] for t, v in nwps_fcst.dropna().items()],
               "flood_stages_ft_usgs_datum": {k: _r(v - o, 2) for k, v in cfg.NWPS_FLOOD_STAGES_FT.items()},
               "source": "NOAA NWS Northwest River Forecast Center via NWPS (gauge VAPW1)"}
        if off is None:
            warnings.append("NWS datum offset could not be measured; using the typical 0.13 ft.")

    # Drivers
    qbar = float(inp["bon"].loc[:t_now].dropna().tail(24).mean()) if len(bon) else np.nan
    c = coef["coef"]
    a = c["T"] + c.get("Tq", 0) * qbar / 100
    p = c.get("HT", 0) + c.get("HTq", 0) * qbar / 100
    lo_b, hi_b = coef["training"]["bonneville_range_kcfs"]
    if np.isfinite(qbar) and not (lo_b <= qbar <= hi_b):
        warnings.append(f"Bonneville flow ({qbar:.0f} kcfs) is outside the model's training range "
                        f"({lo_b:.0f}–{hi_b:.0f} kcfs); the breakdown is an extrapolation.")
    wil = inp["wil"].dropna()
    drivers = {
        "bonneville_24h_mean_kcfs": _r(qbar, 1),
        "willamette_25h_mean_kcfs": _r(wil.iloc[-1], 1) if len(wil) else None,
        "tide_gain_vs_noaa": _r(np.hypot(a, p), 2),
        "tide_timing_shift_min": _r(np.degrees(np.arctan2(p, a)) / 360 * 12.42 * 60, 0),
        "spring_neap": spring_neap_state(inp["sn"], t_now, coef.get("spring_neap_quantiles", {})),
    }
    if "sandy" in comps:
        sa = inp["sandy"].dropna()
        drivers["sandy_12h_mean_kcfs"] = _r(sa.iloc[-1], 2) if len(sa) else None
    if "ocean" in comps:
        su = inp["surge"].dropna()
        drivers["astoria_surge_25h_mean_ft"] = _r(su.iloc[-1], 2) if len(su) else None

    fresh = freshness(latest, t_run, future_ok=bool(fc["tide"].notna().all()) if "tide" in fc else False)
    for name, f in fresh.items():
        if f["status"] != "ok":
            warnings.append(f"{name.replace('_', ' ')} data is {f['status']}.")

    return {
        "schema": SCHEMA,
        "generated": _t(t_run),
        "location": {"name": "Columbia River at Hayden Island (USGS 14144700, Vancouver, WA)",
                     "datum": cfg.USGS_GAGE_DATUM, "units": {"stage": "ft", "flow": "kcfs"}},
        "now": {"time": _t(t_obs), "stage_ft": _r(stage_now.iloc[-1], 2) if t_obs is not None else None,
                "rate_ft_per_h": _r(rate, 2), "direction": direction(rate),
                "model_ft": _r(comp.at[t_now, "model"], 2), "analysis_hour": _t(t_now)},
        "next_tides": extrema(fut.iloc[1:]),
        "why_it_moved": attribution,
        "in_the_pipe": pipe,
        "forecast": {"issued": _t(t_now), "hours": rows,
                     "band": "5–95% range of errors from 5 years of hindcasts at the same lead time"},
        "nws_forecast": nws,
        "drivers": drivers,
        "freshness": fresh,
        "model": {"name": coef["model_name"], "fitted": coef["fitted_utc"],
                  "cv_rmse_ft": _r(coef["cv"]["pooled_rmse_ft"][coef["model_name"]]),
                  "details": "model.json"},
        "warnings": warnings,
    }


def columnar(df: pd.DataFrame, digits: int = 3) -> dict:
    out = {"t": [int(t.timestamp()) for t in df.index]}
    for c in df.columns:
        out[c] = [None if not np.isfinite(v) else round(float(v), digits) for v in df[c].to_numpy(dtype=float)]
    return out


def build_history(comp: pd.DataFrame, inp: pd.DataFrame, t_now, days: int = 30, extra: dict | None = None) -> dict:
    t0 = t_now - pd.Timedelta(days=days)
    cols = ["observed", "model"] + [c for c in COMPONENT_ORDER if c in comp.columns] + ["unexplained"]
    df = comp.loc[t0:t_now, cols].rename(columns={"observed": "stage"})
    df["bonneville_kcfs"] = inp["bon"].loc[t0:t_now]
    df["willamette_kcfs"] = inp["wil"].loc[t0:t_now]
    if inp["sandy"].notna().any():
        df["sandy_kcfs"] = inp["sandy"].loc[t0:t_now]
    df["noaa_tide_osc"] = inp["T"].loc[t0:t_now]
    for k, s in (extra or {}).items():
        df[k] = s.reindex(df.index)
    return {"schema": SCHEMA, "units": "ft (stage, components), kcfs (flows); t = Unix seconds UTC",
            "components_note": "components are contributions relative to the model constant; "
                               "their changes are meaningful, their absolute levels are not",
            **columnar(df)}


def build_fish(df: pd.DataFrame, t_run) -> dict:
    if df is None or df.empty:
        return {"schema": SCHEMA, "available": False}
    last = df[[c for c in cfg.FISH_SPECIES if c in df]].dropna(how="all").index.max()
    season = df.loc[:last]
    species = {}
    for code, name in cfg.FISH_SPECIES.items():
        if code not in df:
            continue
        avg = f"{code}10Yr"
        wk = season.iloc[-7:]
        species[code] = {
            "name": name,
            "daily": [None if pd.isna(v) else int(v) for v in season[code]],
            "daily_10yr_avg": [None if pd.isna(v) else int(v) for v in season[avg]] if avg in season else None,
            "last7": int(wk[code].sum()), "last7_10yr_avg": int(wk[avg].sum()) if avg in wk else None,
            "ytd": int(season[code].sum()), "ytd_10yr_avg": int(season[avg].sum()) if avg in season else None,
        }
    temp = df["TempC"].dropna() if "TempC" in df else pd.Series(dtype=float)
    return {"schema": SCHEMA, "available": True, "generated": _t(t_run), "project": "Bonneville Dam",
            "through": season.index.max().strftime("%Y-%m-%d"),
            "dates": [d.strftime("%Y-%m-%d") for d in season.index], "species": species,
            "ladder_temp_c": {"latest": _r(temp.iloc[-1], 1) if len(temp) else None,
                              "date": temp.index[-1].strftime("%Y-%m-%d") if len(temp) else None},
            "source": "Columbia River DART, Columbia Basin Research, University of Washington"}


def build_chem(series: dict, t_run, days: int = 14) -> dict:
    """series: {name: 15-min Series}. Hourly means over the last `days`."""
    t0 = pd.Timestamp(t_run).floor("h") - pd.Timedelta(days=days)
    hourly = {k: s.loc[t0:].resample("h").mean() for k, s in series.items() if len(s.dropna())}
    if not hourly:
        return {"schema": SCHEMA, "available": False}
    df = pd.DataFrame(hourly)
    if "water_temp" in df and "dissolved_oxygen" in df:
        sat = do_saturation_mg_l(df["water_temp"])
        df["do_saturation_mg_l"] = sat
        df["do_percent_saturation"] = 100 * df["dissolved_oxygen"] / sat
    units = {name: unit for name, unit in cfg.CHEM_PARAMS.values()}
    units.update(do_saturation_mg_l="mg/L (1 atm, Benson & Krause)", do_percent_saturation="%")
    latest = {c: {"value": _r(df[c].dropna().iloc[-1], 3), "time": _t(df[c].dropna().index[-1])}
              for c in df.columns if len(df[c].dropna())}
    return {"schema": SCHEMA, "available": True, "generated": _t(t_run),
            "site": "Willamette River at Portland (USGS 14211720)", "units": units, "latest": latest,
            **columnar(df)}
