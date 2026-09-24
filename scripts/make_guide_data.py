"""Build site/guide/travel_time.json for the guide's interactive travel-time explorer, and copy
the analysis figures the guide shows. Run after a fit:  python scripts/make_guide_data.py

The window is chosen objectively: among 30-day windows (15-day steps) in the training record whose
band-passed (30 h – 10 d) stage-vs-Bonneville cross-correlation peaks at r >= 0.85, take the one
where the travel time is most clearly identified: the largest rise in correlation from zero
delay to the best delay. The "dam-driven" level is observed stage minus the model's tide,
spring–neap, ocean, Willamette and Sandy components, so what's left is mostly Bonneville's influence.
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from riverbrain import config as cfg  # noqa: E402
from riverbrain import sources as S  # noqa: E402
from riverbrain.features import build_features, build_inputs  # noqa: E402
from riverbrain.model import components, dumps, load  # noqa: E402
from riverbrain.qc import merge_bonneville  # noqa: E402
from riverbrain.signal import godin  # noqa: E402

OUT = ROOT / "site" / "guide"


def bandpass(x):
    return godin(x) - x.rolling(240, center=True, min_periods=200).mean()


def main():
    coef = load(cfg.COEF_PATH)
    start, end = pd.Timestamp(coef["training"]["start_utc"]), pd.Timestamp(coef["training"]["end_utc"])
    cache = S.Cache(ROOT / "data" / "raw" / "fit")
    warm = start - pd.Timedelta(days=5)
    stage = S.usgs_continuous(cfg.USGS_STAGE_SITE, "00065", warm, end, cache=cache)
    wil = S.usgs_continuous(cfg.USGS_WILLAMETTE_SITE, "00060", warm, end, cache=cache)
    sandy = S.usgs_continuous(cfg.USGS_SANDY_SITE, "00060", warm, end, cache=cache)
    pred = S.noaa_series("predictions", cfg.NOAA_VANCOUVER, warm, end + pd.Timedelta(days=5), cache=cache)
    ast_obs = S.noaa_series("water_level", cfg.NOAA_ASTORIA, warm, end, cache=cache)
    ast_pred = S.noaa_series("predictions", cfg.NOAA_ASTORIA, warm, end, cache=cache)
    bon, _ = merge_bonneville(S.usace_dataquery(warm, end, cache=cache), S.usace_cda(warm, end, cache=cache))
    H = pd.date_range(warm, end, freq="h", inclusive="left")
    inp = build_inputs(H, stage15=stage, bon=bon, wil5=wil, pred6=pred, ast_obs6=ast_obs, ast_pred6=ast_pred, sandy15=sandy)
    comp = components(build_features(inp, coef["spec"]), coef["coef"])
    # Isolate Bonneville's signal: observed stage minus every other modelled driver
    others = [c for c in ("tide", "spring_neap", "ocean", "willamette", "sandy") if c in comp]
    river = comp["observed"] - comp[others].sum(axis=1)
    rb, bb = bandpass(river), bandpass(inp["bon"])

    best, windows = None, []
    for t0 in pd.date_range(start + pd.Timedelta(days=10), end - pd.Timedelta(days=40), freq="15D"):
        w = slice(t0, t0 + pd.Timedelta(days=30))
        cc = pd.Series({L: rb[w].corr(bb.shift(L)[w]) for L in range(0, 37)})
        if cc.isna().all():
            continue
        windows.append({"start": t0.strftime("%Y-%m-%d"), "bonneville_mean_kcfs": round(float(inp["bon"][w].mean()), 1),
                        "peak_lag_h": int(cc.idxmax()), "peak_r": round(float(cc.max()), 3)})
        score = cc.max() - cc[0] if cc.max() >= 0.85 else -1
        if best is None or score > best[2]:
            best = (t0, cc, score)
    t0, cc, _ = best
    w = slice(t0, t0 + pd.Timedelta(days=30))
    df = pd.DataFrame({"river_bp": rb[w], "bon_bp": bb.shift(-0)[w].reindex(rb[w].index), "stage": comp["observed"][w],
                       "bon": inp["bon"][w]})
    # Bonneville needs 36 h of history before the window so the slider can shift it back
    pre = bb[t0 - pd.Timedelta(hours=36):t0 - pd.Timedelta(hours=1)]
    payload = {
        "window_start": t0.isoformat(), "window_end": (t0 + pd.Timedelta(days=30)).isoformat(),
        "peak_lag_h": int(cc.idxmax()), "peak_r": round(float(cc.max()), 3),
        "note": "Both series band-passed to 30 h – 10 days (Godin low-pass minus 10-day mean). "
                "Dam-driven level = observed − the model's tide, spring–neap, ocean, Willamette and Sandy parts.",
        "t": [int(t.timestamp()) for t in df.index],
        "river_bp": df["river_bp"].round(4).tolist(), "bon_bp": df["bon_bp"].round(3).tolist(),
        "bon_bp_before": pre.round(3).tolist(),
        "stage": df["stage"].round(3).tolist(), "bon": df["bon"].round(1).tolist(),
        "xcorr": [round(float(v), 4) for v in cc.to_numpy()],
        # every 30-day window: does travel time depend on flow? (windows with peak r > 0.6 are shown)
        "windows": windows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "travel_time.json").write_text(dumps(payload), encoding="utf-8")
    print(f"window {t0:%Y-%m-%d} +30 d: peak r={cc.max():.3f} at {cc.idxmax()} h")

    figs = {ROOT / "docs/figures": ["04_tide_split.png", "07_ladder.png", "08_tide_vs_flow.png",
                                    "08_resid_spectrum.png"],
            ROOT / "model/figures": ["five_years.png", "forecast_skill.png"]}
    for d, names in figs.items():
        for n in names:
            shutil.copy(d / n, OUT / n)
    print("copied", sum(len(v) for v in figs.values()), "figures to", OUT)


if __name__ == "__main__":
    main()
