"""Offline model fit: python -m riverbrain.fit [--start 2021-10-01] [--quick]

1. Fetch ~5 water years of every input (cached in data/raw/fit/).
2. Leave-one-water-year-out cross-validation of candidate models: each year is scored by
   a model (and lag/kernel) chosen without seeing that year.
3. Select a model by the rule declared in SELECTION_RULE, *before* looking at results.
4. Refit the selected model on all years.
5. Hindcast 48-h forecasts from every 12 h in each held-out year (fold coefficients, data
   truncated at the forecast origin) to measure honest forecast skill by lead time and pick
   how the current model error is carried forward.
6. Write model/coefficients.json and model/fit_report.md (+ figures in model/figures/).
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as cfg
from . import sources as S
from .features import COMPONENTS, FEATURE_DOC, OBSERVED, build_features, build_inputs, tide_terms
from .model import RESID_TAUS, components, hindcast, predict, rmse, save, search
from .qc import merge_bonneville

MODELS = {
    "M0 tide + Bonneville": ["T", "q"],
    "M3 + Willamette, flow-dependent tide": ["T", "Tq", "HT", "HTq", "q", "qw"],
    "M5 + Q², spring–neap (Phase 1 pick)": ["T", "Tq", "HT", "HTq", "q", "q2", "qw", "sn"],
    "M5 + overtides": ["T", "Tq", "HT", "HTq", "T2", "TH", "q", "q2", "qw", "sn"],
    "M5 + fast Bonneville kernel": ["T", "Tq", "HT", "HTq", "q", "q2", "qf", "qw", "sn"],
    "M6 = M5 + Astoria surge": ["T", "Tq", "HT", "HTq", "q", "q2", "qw", "sn", "surge"],
    "M8 = M6 + Sandy River": ["T", "Tq", "HT", "HTq", "q", "q2", "qw", "sn", "surge", "qs"],
    "M9 = M8 + Willamette²": ["T", "Tq", "HT", "HTq", "q", "q2", "qw", "qw2", "sn", "surge", "qs"],
    "M10 all terms": ["T", "Tq", "HT", "HTq", "T2", "TH", "q", "q2", "qf", "qw", "qw2", "sn", "surge", "qs"],
}
SELECTION_RULE = ("lowest pooled cross-validated RMSE; if a model with fewer terms is within 2% "
                  "of the best, prefer the one with fewest terms")
FLOW_BANDS = [0, 100, 150, 200, 250, 300, 400, 700]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def water_year(idx: pd.DatetimeIndex) -> np.ndarray:
    return idx.year + (idx.month >= 10)


def fetch_history(start: pd.Timestamp, end: pd.Timestamp, cache: S.Cache) -> dict:
    warm = start - pd.Timedelta(days=5)
    log("USGS stage (15-min)")
    stage = S.usgs_continuous(cfg.USGS_STAGE_SITE, "00065", warm, end, cache=cache)
    log("USGS Willamette discharge (5-min)")
    wil = S.usgs_continuous(cfg.USGS_WILLAMETTE_SITE, "00060", warm, end, cache=cache)
    log("USGS Sandy River discharge (15-min)")
    sandy = S.usgs_continuous(cfg.USGS_SANDY_SITE, "00060", warm, end, cache=cache)
    log("NOAA Vancouver predictions")
    pred = S.noaa_series("predictions", cfg.NOAA_VANCOUVER, warm, end + pd.Timedelta(days=5), cache=cache)
    log("NOAA Astoria observed + predicted")
    ast_obs = S.noaa_series("water_level", cfg.NOAA_ASTORIA, warm, end, cache=cache)
    ast_pred = S.noaa_series("predictions", cfg.NOAA_ASTORIA, warm, end, cache=cache)
    log("USACE Bonneville (Dataquery + CDA)")
    dq = S.usace_dataquery(warm, end, cache=cache)
    cda = S.usace_cda(warm, end, cache=cache)
    bon, flags = merge_bonneville(dq, cda)
    return dict(stage=stage, wil=wil, sandy=sandy, pred=pred, ast_obs=ast_obs, ast_pred=ast_pred,
                bon=bon, bon_flags=flags, dq=dq, cda=cda)


def select_model(pooled: dict) -> str:
    best = min(pooled.values())
    ok = [m for m, e in pooled.items() if e <= best * 1.02]
    return min(ok, key=lambda m: (len(MODELS[m]), pooled[m]))


def physics_readings(coef: dict, spec: dict) -> dict:
    """Translate coefficients into physical statements at several flows."""
    out = {"by_bonneville_flow": {}}
    for Q in (80, 150, 250, 400):
        dhdq = coef["q"] + 2 * coef.get("q2", 0.0) * Q / 100 ** 2
        a = coef["T"] + coef.get("Tq", 0.0) * Q / 100
        p = coef.get("HT", 0.0) + coef.get("HTq", 0.0) * Q / 100
        ph = float(np.degrees(np.arctan2(p, a)))
        out["by_bonneville_flow"][str(Q)] = {
            "ft_per_10kcfs_bonneville": round(10 * dhdq, 3),
            "tide_gain_vs_noaa": round(float(np.hypot(a, p)), 3),
            "tide_timing_shift_min": round(ph / 360 * 12.42 * 60, 1),
        }
    if "qw" in coef:
        out["ft_per_10kcfs_willamette"] = {str(W): round(10 * (coef["qw"] + 2 * coef.get("qw2", 0.0) * W / 100 ** 2), 3)
                                           for W in (10, 50, 100)}
    if "qs" in coef:
        out["ft_per_10kcfs_sandy"] = round(10 * coef["qs"], 3)
    if "sn" in coef:
        out["ft_mean_level_per_0.1ft_tidal_envelope"] = round(0.1 * coef["sn"], 3)
    if "surge" in coef:
        out["ft_per_ft_astoria_surge"] = round(coef["surge"], 3)
    out["bonneville_lag_centroid_h"] = spec["tau"] + (spec["width"] - 1) / 2
    return out


def tide_edge_check(inp_full: pd.DataFrame, pred6: pd.Series, n: int = 20) -> dict:
    """The live run computes tide terms on a ~50-day window (34 d back, 16 d ahead); the fit
    uses 5 years. Measure how much the window edges change T, HT and sn at 'now'."""
    diffs = []
    rng = np.random.default_rng(1)
    idx = inp_full.index[(inp_full.index > inp_full.index[0] + pd.Timedelta("40D")) &
                         (inp_full.index < inp_full.index[-1] - pd.Timedelta("20D"))]
    for t in rng.choice(idx, n, replace=False):
        t = pd.Timestamp(t)
        w = pd.date_range(t - pd.Timedelta(days=cfg.RUN_HISTORY_DAYS), t + pd.Timedelta(days=cfg.RUN_FUTURE_DAYS), freq="h")
        tt = tide_terms(pred6.reindex(w))
        diffs.append((tt.loc[t] - inp_full.loc[t, ["T", "HT", "sn"]]).abs())
    d = pd.DataFrame(diffs)
    return {k: round(float(v), 4) for k, v in d.max().items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2021-10-01")
    ap.add_argument("--end", default=None, help="default: today 00:00 UTC")
    ap.add_argument("--cache", default=str(cfg.ROOT / "data" / "raw" / "fit"))
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--quick", action="store_true", help="coarse grid, for smoke tests")
    ap.add_argument("--out", default=str(cfg.COEF_PATH))
    args = ap.parse_args(argv)

    t_start = time.time()
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") if args.end else pd.Timestamp.now("UTC").floor("D")
    for attempt in range(6):  # offline only: wait out rate limits; the cache keeps progress
        try:
            raw = fetch_history(start, end, S.Cache(args.cache, args.refresh and attempt == 0))
            break
        except S.RateLimited as e:
            log(f"{e} Waiting {e.retry_after_s // 60 + 1} min, then resuming from cache.")
            time.sleep(e.retry_after_s + 60)
    else:
        raise SystemExit("gave up after repeated rate limiting")

    H = pd.date_range(start - pd.Timedelta(days=5), end + pd.Timedelta(days=5), freq="h", inclusive="left")
    inp = build_inputs(H, stage15=raw["stage"], bon=raw["bon"], wil5=raw["wil"], pred6=raw["pred"],
                       ast_obs6=raw["ast_obs"], ast_pred6=raw["ast_pred"], sandy15=raw["sandy"])
    inp.loc[inp.index >= end, OBSERVED] = np.nan  # keep future clean
    in_period = (inp.index >= start) & (inp.index < end)
    wy = pd.Series(water_year(inp.index), index=inp.index)
    years = sorted(wy[in_period].unique())
    log(f"inputs: {in_period.sum()} hours, water years {years}; "
        f"stage coverage {inp.stage[in_period].notna().mean():.1%}, bon {inp.bon[in_period].notna().mean():.1%}, "
        f"wil {inp.wil[in_period].notna().mean():.1%}, surge {inp.surge[in_period].notna().mean():.1%}, "
        f"sandy {inp.sandy[in_period].notna().mean():.1%}")

    grid = dict(taus=range(0, 25, 4), widths=(1, 24), surge_lags=(0,), fast_taus=(0, 12)) if args.quick \
        else dict(taus=range(0, 25), widths=(1, 6, 12, 24, 36, 48), surge_lags=(0, 6, 12), fast_taus=range(0, 25, 2))
    period = pd.Series(in_period, index=inp.index)
    masks = {f"train_not_WY{y}": period & (wy != y) for y in years}
    masks["all"] = period

    log(f"grid search over {len(MODELS)} models × {len(masks)} training sets")
    best = search(inp, MODELS, masks, **grid)

    # --- cross-validation scores ---
    log("scoring held-out years")
    cv_rows, cv_err = [], {}
    for m in MODELS:
        errs = []
        for y in years:
            b = best[(m, f"train_not_WY{y}")]
            f = build_features(inp, b["spec"])
            test = period & (wy == y)
            e = (predict(f, b["coef"]) - f["y"])[test]
            errs.append(pd.DataFrame({"err": e, "bon": inp["bon"][test], "wy": y}))
            cv_rows.append({"model": m, "water_year": int(y), "rmse_ft": rmse(e), "n": int(e.notna().sum()),
                            "tau": b["spec"]["tau"], "width": b["spec"]["width"]})
        cv_err[m] = pd.concat(errs).dropna(subset=["err"])
    cv = pd.DataFrame(cv_rows)
    pooled = {m: rmse(cv_err[m]["err"]) for m in MODELS}
    y_all = inp["stage"][period]
    pooled_r2 = {m: 1 - float((cv_err[m]["err"] ** 2).mean() / y_all.var()) for m in MODELS}
    chosen = select_model(pooled)
    log("pooled CV RMSE: " + "; ".join(f"{m}: {e:.3f}" for m, e in pooled.items()))
    log(f"selected: {chosen}")

    final = best[(chosen, "all")]
    spec, coef = final["spec"], final["coef"]
    f_all = build_features(inp, spec)
    comp_all = components(f_all, coef)

    band = pd.cut(cv_err[chosen]["bon"], FLOW_BANDS)
    by_band = cv_err[chosen].groupby(band, observed=True)["err"].agg(
        hours="size", bias_ft="mean", rmse_ft=lambda e: rmse(e),
        p95_abs_ft=lambda e: float(e.abs().quantile(0.95)))

    # --- forecast skill by hindcast on held-out years ---
    log("hindcasting 48-h forecasts from every 12 h of each held-out year")
    hc = []
    for y in years:
        b = best[(chosen, f"train_not_WY{y}")]
        origins = inp.index[period & (wy == y) & inp["stage"].notna() & inp["bon"].notna()]
        origins = origins[(origins.hour % 12) == 0]
        if args.quick:
            origins = origins[::8]
        hc.append(hindcast(inp, b["spec"], b["coef"], origins, cfg.FORECAST_HOURS))
    hc = pd.concat(hc).dropna(subset=["err"])
    skill = hc.groupby(["method", "lead_h"])["err"].agg(
        rmse=lambda e: rmse(e), bias="mean", p05=lambda e: e.quantile(0.05), p95=lambda e: e.quantile(0.95), n="size")
    mean_rmse = skill["rmse"].groupby("method").mean()
    carry = mean_rmse.drop("baseline_noaa_plus_offset").idxmin()
    resid_tau = {f"resid_tau_{rt}": rt for rt in RESID_TAUS}[carry]
    log(f"residual carry chosen: {carry} (mean RMSE over leads {mean_rmse[carry]:.3f} ft; "
        f"baseline {mean_rmse['baseline_noaa_plus_offset']:.3f} ft)")

    def skill_dict(method):
        s = skill.loc[method]
        return {str(int(k)): {c: round(float(v), 3) for c, v in r.items()} for k, r in s.iterrows()}

    sn = f_all["sn"][period] if "sn" in f_all else pd.Series(dtype=float)
    edge = tide_edge_check(inp, raw["pred"])
    payload = {
        "schema": 1,
        "model_name": chosen,
        "fitted_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_version": __import__("riverbrain").__version__,
        "equation": "stage = const + Σ coef[k]·feature[k]  (ft, USGS gage datum)",
        "spec": spec,
        "coef": coef,
        "feature_doc": {k: FEATURE_DOC[k] for k in spec["features"]},
        "components": {k: [c for c in v if c in coef] for k, v in COMPONENTS.items() if any(c in coef for c in v)},
        "training": {
            "start_utc": start.isoformat(), "end_utc": end.isoformat(), "hours_used": final["n"],
            "rmse_in_sample_ft": round(final["rmse_in"], 4),
            "bonneville_range_kcfs": [round(float(inp.bon[period].min()), 1), round(float(inp.bon[period].max()), 1)],
            "willamette_range_kcfs": [round(float(inp.wil[period].min()), 1), round(float(inp.wil[period].max()), 1)],
            "stage_range_ft": [round(float(y_all.min()), 2), round(float(y_all.max()), 2)],
            # used by the hourly run to hold an input fixed if its source is down for the whole window
            "input_medians": {c: round(float(inp[c][period].median()), 3) for c in ("bon", "wil", "sandy", "surge")
                              if inp[c][period].notna().any()},
        },
        "cv": {
            "method": "leave-one-water-year-out; lag/kernel re-chosen within each training set",
            "selection_rule": SELECTION_RULE,
            "pooled_rmse_ft": {m: round(e, 4) for m, e in pooled.items()},
            "pooled_r2": {m: round(v, 4) for m, v in pooled_r2.items()},
            "by_year": {m: {str(r.water_year): round(r.rmse_ft, 4) for r in cv[cv.model == m].itertuples()}
                        for m in MODELS},
            "selected_by_flow_band": {str(k): {c: (round(float(v), 4) if c != "hours" else int(v)) for c, v in r.items()}
                                      for k, r in by_band.iterrows()},
        },
        "forecast": {
            "residual_carry": carry,
            "resid_tau_h": "inf" if resid_tau is not None and np.isinf(resid_tau) else resid_tau,
            "resid_window_h": 3,
            "mean_rmse_by_method_ft": {k: round(float(v), 4) for k, v in mean_rmse.items()},
            "skill_ft": skill_dict(carry),
            "baseline_skill_ft": skill_dict("baseline_noaa_plus_offset"),
            "baseline_note": "NOAA's raw prediction plus the observed offset over the previous 24 h",
        },
        "spring_neap_quantiles": {f"p{q}": round(float(sn.quantile(q / 100)), 4) for q in (10, 25, 50, 75, 90)}
        if len(sn) else {},
        "physics": physics_readings(coef, spec),
        "diagnostics": {
            "tide_terms_window_edge_max_abs_diff": edge,
            "bonneville_qc_flags": {k: int(v) for k, v in raw["bon_flags"].sum().items()},
            "dataquery_vs_cda_max_abs_diff_kcfs": round(float((raw["dq"] - raw["cda"]).abs().max()), 3),
        },
    }
    save(__import__("pathlib").Path(args.out), payload)
    log(f"wrote {args.out}")

    from .report import write_report
    write_report(payload, cv, cv_err, comp_all, inp, skill, period, wy, chosen)
    log(f"done in {(time.time() - t_start) / 60:.1f} min")


if __name__ == "__main__":
    main()
