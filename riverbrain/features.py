"""Hourly inputs and model features. The ONE place features are defined, shared by the
offline fit, the hindcast skill test and the hourly run.

Causality rule: every river-flow feature at time t uses only observations at or before t
(trailing windows). Tide features may use future *predictions*, which are published ahead.
Beyond the last observation, flows are held constant (persistence); that is also how the
48-h forecast treats the unknown future.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .signal import analytic, fill_short_gaps, godin, hold_last, trailing_mean

# Which features make up each physical component (used for attribution and plotting).
COMPONENTS = {
    "tide": ["T", "Tq", "HT", "HTq", "T2", "TH"],
    "bonneville": ["q", "q2", "qf"],
    "willamette": ["qw", "qw2"],
    "sandy": ["qs"],
    "spring_neap": ["sn"],
    "ocean": ["surge"],
}
FEATURE_DOC = {
    "T": "NOAA tidal oscillation (Godin high-pass of the prediction), ft",
    "Tq": "T × trailing-24h Bonneville flow / 100 kcfs: tide amplitude varies with flow",
    "HT": "Hilbert quadrature of T (T shifted 90°): lets the fit shift tide timing",
    "HTq": "HT × trailing-24h Bonneville flow / 100 kcfs: tide timing varies with flow",
    "T2": "T²: shallow-water overtide distortion",
    "TH": "T·HT: shallow-water overtide distortion (quadrature part)",
    "q": "Bonneville outflow, trailing w-hour mean ending τ hours ago, kcfs",
    "q2": "(q / 100)²: curved stage response to flow",
    "qf": "short-term Bonneville deviation (3-h mean ending τf hours ago − q), kcfs",
    "qw": "Willamette at Portland, trailing 25-h mean (net of tidal reversal), kcfs",
    "qw2": "(qw / 100)²: Willamette backwater effect bends at flood flows",
    "qs": "Sandy River (joins below Bonneville), trailing 12-h mean, kcfs",
    "sn": "spring–neap index: Godin low-pass of the tidal envelope |T + i·HT|, ft",
    "surge": "Astoria storm surge (observed − predicted), trailing 25-h mean, ft",
}


# Observed (not predicted) input columns: hidden after `asof`, then held at their last value.
OBSERVED = ["bon", "wil", "surge", "sandy", "stage"]


def build_inputs(index: pd.DatetimeIndex, *, stage15: pd.Series, bon: pd.Series, wil5: pd.Series,
                 pred6: pd.Series, ast_obs6: pd.Series | None = None,
                 ast_pred6: pd.Series | None = None, sandy15: pd.Series | None = None) -> pd.DataFrame:
    """Align every source onto an hourly UTC grid and precompute the tide terms.

    stage15: USGS gage height (15-min), ft.  bon: QC'd Bonneville outflow, hourly kcfs.
    wil5: Willamette discharge (5-min), cfs.  pred6: NOAA Vancouver predictions (6-min), ft,
    extending past the end of observations.  ast_*: Astoria observed/predicted (6-min), ft.
    sandy15: Sandy River discharge (15-min), cfs.
    """
    inp = pd.DataFrame(index=index)
    st = stage15.dropna()
    inp["stage"] = st.reindex(index, method="nearest", tolerance=pd.Timedelta("10min")) if len(st) else np.nan
    inp["bon"] = bon.reindex(index)

    if len(wil5.dropna()):
        g5 = pd.date_range(index[0] - pd.Timedelta("26h"), index[-1], freq="5min")
        w = fill_short_gaps(wil5.reindex(g5), 24)          # bridge gaps up to 2 h
        inp["wil"] = (trailing_mean(w, 300, 0.9) / 1000.0).reindex(index)  # 25 h, kcfs
    else:
        inp["wil"] = np.nan

    if sandy15 is not None and len(sandy15.dropna()):
        g15 = pd.date_range(index[0] - pd.Timedelta("13h"), index[-1], freq="15min")
        sa = fill_short_gaps(sandy15.reindex(g15), 8)
        inp["sandy"] = (trailing_mean(sa, 48, 0.9) / 1000.0).reindex(index)  # 12 h, kcfs
    else:
        inp["sandy"] = np.nan

    if ast_obs6 is not None and ast_pred6 is not None and len(ast_obs6.dropna()):
        su = (ast_obs6 - ast_pred6).reindex(index)  # value at the top of the hour
        inp["surge"] = trailing_mean(fill_short_gaps(su, 3), 25)
    else:
        inp["surge"] = np.nan

    pred = pred6.reindex(index)
    inp["pred"] = pred
    inp = inp.join(tide_terms(pred))
    return inp


def tide_terms(pred: pd.Series) -> pd.DataFrame:
    """T (tidal oscillation), HT (quadrature) and sn (spring–neap index) from hourly predictions.

    The prediction's low-pass part is NOAA's built-in 'average seasonal river' and is discarded,
    otherwise river flow would be counted twice. The Hilbert transform runs over each contiguous
    stretch of predictions."""
    osc = pred - godin(pred)
    T = pd.Series(np.nan, index=pred.index)
    HT = pd.Series(np.nan, index=pred.index)
    env = pd.Series(np.nan, index=pred.index)
    ok = osc.notna()
    seg = (ok != ok.shift()).cumsum()
    for _, idx in osc[ok].groupby(seg[ok]).groups.items():
        if len(idx) < 48:
            continue
        a = analytic(osc[idx].to_numpy())
        T[idx] = a.real
        HT[idx] = a.imag
        env[idx] = np.abs(a)
    return pd.DataFrame({"T": T, "HT": HT, "sn": godin(env)})


def build_features(inp: pd.DataFrame, spec: dict, asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """Feature matrix for a model spec. `asof` hides observations after that time (hindcast);
    flows then persist from the last observation, exactly as in the live forecast.

    spec: {"features": [...], "tau": int, "width": int, "fast_tau": int|None, "surge_lag": int}
    """
    bon, wil, surge, sandy, stage = (inp[c] for c in OBSERVED)
    if asof is not None:
        after = inp.index > asof
        bon, wil, surge, sandy, stage = (s.mask(after) for s in (bon, wil, surge, sandy, stage))
    bon, wil, surge, sandy = hold_last(bon), hold_last(wil), hold_last(surge), hold_last(sandy)

    tau, width = int(spec["tau"]), int(spec["width"])
    qbar = trailing_mean(bon, 24)
    qk = trailing_mean(bon, width).shift(tau)
    T, HT = inp["T"], inp["HT"]
    all_f = {
        "T": T, "Tq": T * qbar / 100, "HT": HT, "HTq": HT * qbar / 100,
        "T2": T ** 2, "TH": T * HT,
        "q": qk, "q2": (qk / 100) ** 2, "qw": wil, "qw2": (wil / 100) ** 2, "qs": sandy, "sn": inp["sn"],
        "surge": surge.shift(int(spec.get("surge_lag") or 0)),
    }
    if "qf" in spec["features"]:
        all_f["qf"] = trailing_mean(bon, 3).shift(int(spec["fast_tau"])) - qk
    f = pd.DataFrame({k: all_f[k] for k in spec["features"]}, index=inp.index)
    f.insert(0, "y", stage)
    f["qbar"] = qbar          # carried along for diagnostics (tide gain/phase), not a regressor
    return f
