"""Hourly run: python -m riverbrain.run [--out site/data] [--archive-dir archive]

Fetch the last ~34 days of every source (+16 days of tide predictions), apply the fitted model
in model/coefficients.json, and write the JSON files the PWA reads. A failing source is
recorded as missing and surfaces in now.json's `freshness` and `warnings`; the run carries on.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg
from . import sources as S
from .features import OBSERVED, build_features, build_inputs
from .model import components, dumps, forecast, load, parse_resid_tau, save
from .outputs import build_chem, build_fish, build_history, build_now
from .qc import merge_bonneville

EMPTY = pd.Series(dtype="float64")


def attempt(name: str, fn, errors: dict, default=EMPTY):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - any source failure must not kill the run
        errors[name] = f"{type(e).__name__}: {e}"
        print(f"[warn] {name} failed: {errors[name]}", file=sys.stderr)
        traceback.print_exc(limit=1, file=sys.stderr)
        return default


def fetch_live(t_run: pd.Timestamp, features: list[str]) -> tuple[dict, dict]:
    start = t_run.floor("h") - pd.Timedelta(days=cfg.RUN_HISTORY_DAYS)
    end = t_run.ceil("h") + pd.Timedelta(hours=1)
    fut = t_run.ceil("h") + pd.Timedelta(days=cfg.RUN_FUTURE_DAYS)
    err: dict = {}
    d = {
        "stage": attempt("stage", lambda: S.usgs_continuous(cfg.USGS_STAGE_SITE, "00065", start, end), err),
        "wil": attempt("willamette", lambda: S.usgs_continuous(cfg.USGS_WILLAMETTE_SITE, "00060", start, end), err),
        "pred": attempt("tide_predictions", lambda: S.noaa_series("predictions", cfg.NOAA_VANCOUVER, start, fut), err),
        "cda": attempt("bonneville_cda", lambda: S.usace_cda(start, end), err),
        "nwps": attempt("nwps", S.nwps_stageflow, err, default=(EMPTY, EMPTY, None)),
        "fish": attempt("fish", lambda: S.dart_adult_daily(t_run.year), err, default=pd.DataFrame()),
        "chem": {name: attempt(f"chem_{pc}", lambda pc=pc: S.usgs_continuous(
            cfg.USGS_WILLAMETTE_SITE, pc, t_run - pd.Timedelta(days=15), end), err)
            for pc, (name, _) in cfg.CHEM_PARAMS.items()},
    }
    # Total, spill and powerhouse flow in one Dataquery request (fewer chances to hit its flakiness)
    dq = attempt("bonneville_dataquery", lambda: S.usace_dataquery_many(
        start, end, [cfg.BON_TSID, cfg.BON_SPILL_TSID, cfg.BON_GEN_TSID]), err, default={})
    d["dq"] = dq.get(cfg.BON_TSID, EMPTY)
    d["spill"] = dq.get(cfg.BON_SPILL_TSID, EMPTY)
    d["gen"] = dq.get(cfg.BON_GEN_TSID, EMPTY)
    if "qs" in features:
        d["sandy"] = attempt("sandy", lambda: S.usgs_continuous(cfg.USGS_SANDY_SITE, "00060", start, end), err)
    if "surge" in features:
        d["ast_obs"] = attempt("astoria_observed", lambda: S.noaa_series("water_level", cfg.NOAA_ASTORIA, start, end), err)
        d["ast_pred"] = attempt("astoria_predictions", lambda: S.noaa_series("predictions", cfg.NOAA_ASTORIA, start, end), err)
    return d, err


def run(t_run: pd.Timestamp, out_dir: Path, archive_dir: Path | None, raw: dict | None = None,
        errors: dict | None = None, coef: dict | None = None) -> dict:
    coef = coef or load(cfg.COEF_PATH)
    spec = coef["spec"]
    feats = spec["features"]
    if raw is None:
        raw, errors = fetch_live(t_run, feats)
    errors = errors or {}

    bon, bon_flags = merge_bonneville(raw["dq"], raw["cda"])
    H = pd.date_range(t_run.floor("h") - pd.Timedelta(days=cfg.RUN_HISTORY_DAYS),
                      t_run.floor("h") + pd.Timedelta(days=cfg.RUN_FUTURE_DAYS), freq="h")
    inp = build_inputs(H, stage15=raw["stage"], bon=bon, wil5=raw["wil"], pred6=raw["pred"],
                       ast_obs6=raw.get("ast_obs"), ast_pred6=raw.get("ast_pred"), sandy15=raw.get("sandy"))
    inp.loc[inp.index > t_run, OBSERVED] = np.nan  # nothing observed after now

    # A flow source that is down for the whole window: hold it at its training median so the
    # model still runs; that component then contributes no change, and we say so.
    needs = {"bon": {"q", "q2", "qf", "Tq", "HTq"}, "wil": {"qw", "qw2"}, "sandy": {"qs"}, "surge": {"surge"}}
    held = []
    for col, uses in needs.items():
        if uses & set(feats) and inp.loc[:t_run, col].isna().all():
            med = coef["training"].get("input_medians", {}).get(col)
            if med is not None:
                inp[col] = med
                held.append(col)

    stage_ok = inp["stage"].dropna()
    if stage_ok.empty:
        raise RuntimeError("No USGS stage data: cannot produce a nowcast")
    t_now = stage_ok.index[-1]  # latest hour with an observed stage = analysis time

    f = build_features(inp, spec)
    comp = components(f, coef["coef"])
    fc = forecast(inp, spec, coef["coef"], t_now, cfg.FORECAST_HOURS,
                  parse_resid_tau(coef["forecast"]["resid_tau_h"]), coef["forecast"]["resid_window_h"])

    nwps_obs, nwps_fcst, nwps_issued = raw["nwps"]
    latest = {
        "stage": raw["stage"].last_valid_index() if len(raw["stage"]) else None,
        "bonneville": bon.last_valid_index() if len(bon) else None,
        "willamette": raw["wil"].last_valid_index() if len(raw["wil"]) else None,
        "tide_predictions": None,
        "nwps_forecast": pd.Timestamp(nwps_issued) if nwps_issued else None,
    }
    if isinstance(raw["fish"], pd.DataFrame) and len(raw["fish"]):
        fl = raw["fish"][[c for c in cfg.FISH_SPECIES if c in raw["fish"]]].dropna(how="all").index.max()
        latest["fish"] = pd.Timestamp(fl, tz="UTC") + pd.Timedelta(days=1) if pd.notna(fl) else None
    chem_last = [s.last_valid_index() for s in raw["chem"].values() if len(s)]
    latest["chemistry"] = max(chem_last) if chem_last else None
    for key, name in (("ast_obs", "astoria"), ("sandy", "sandy")):
        if key in raw:
            latest[name] = raw[key].last_valid_index() if len(raw[key]) else None

    recent_flags = bon_flags.loc[bon_flags.index > t_run - pd.Timedelta(days=30)] if len(bon_flags) else bon_flags
    qc_summary = {k: int(v) for k, v in recent_flags[["missing", "range", "spike", "flat", "filled"]].sum().items()} \
        if len(recent_flags) else {}
    # Fetch errors are diagnostics (kept in now.json → qc.fetch_errors). The reader is only warned
    # when a failure actually leaves data missing or stale; that comes from `freshness` below.
    # E.g. Dataquery failing while CWMS fills in is invisible to the reader, as it should be.
    warn = []
    names = {"bon": "Bonneville", "wil": "Willamette", "sandy": "Sandy River", "surge": "Astoria surge"}
    warn += [f"No {names[c]} data at all: its effect is held at a typical value and shows no change." for c in held]
    if qc_summary.get("range") or qc_summary.get("spike") or qc_summary.get("flat"):
        warn.append(f"Bonneville data had suspect values in the last 30 days (QC: {qc_summary}); they were masked.")

    now = build_now(t_run=t_run, t_now=t_now, stage15=raw["stage"], comp=comp, fc=fc, coef=coef, inp=inp,
                    nwps_obs=nwps_obs, nwps_fcst=nwps_fcst, nwps_issued=nwps_issued, latest=latest,
                    extra_warnings=warn)
    now["qc"] = {"bonneville_last_30d": qc_summary, "fetch_errors": errors}

    extra = {}
    for k, key in (("bonneville_spill_kcfs", "spill"), ("bonneville_generation_kcfs", "gen")):
        if len(raw[key]):
            extra[k] = raw[key]
    files = {
        "now.json": now,
        "history_30d.json": build_history(comp, inp, t_now, extra=extra),
        "model.json": coef,
        "fish.json": build_fish(raw["fish"] if isinstance(raw["fish"], pd.DataFrame) else None, t_run),
        "chem.json": build_chem(raw["chem"], t_run),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        save(out_dir / name, payload, indent=None)

    if archive_dir is not None:
        append_archive(archive_dir, now)
    return files


def append_archive(archive_dir: Path, now: dict) -> None:
    """One JSON line per run: our forecast and NWS's, for measuring forecast skill later."""
    rec = {"issued": now["forecast"]["issued"], "generated": now["generated"],
           "observed_now_ft": now["now"]["stage_ft"],
           "model": [[h["t"], h["stage_ft"]] for h in now["forecast"]["hours"]],
           "nws_issued": (now.get("nws_forecast") or {}).get("issued"),
           "nws": (now.get("nws_forecast") or {}).get("points")}
    d = archive_dir / "forecasts"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now['forecast']['issued'][:7]}.jsonl"
    # Skip if this analysis hour was already archived (re-runs within the hour)
    if path.exists() and f'"issued":"{rec["issued"]}"' in path.read_text(encoding="utf-8"):
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write(dumps(rec) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(cfg.ROOT / "site" / "data"))
    ap.add_argument("--archive-dir", default=None)
    args = ap.parse_args(argv)
    t_run = pd.Timestamp.now("UTC")
    files = run(t_run, Path(args.out), Path(args.archive_dir) if args.archive_dir else None)
    now = files["now.json"]
    print(json.dumps({k: now[k] for k in ("generated", "now", "warnings")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
