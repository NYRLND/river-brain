"""Fit, apply, decompose and forecast. Ordinary least squares on physically motivated features."""

from __future__ import annotations

import json
from itertools import product

import numpy as np
import pandas as pd

from .features import COMPONENTS, build_features

REGRESSORS_EXCLUDE = {"y", "qbar"}


def regressors(f: pd.DataFrame) -> list[str]:
    return [c for c in f.columns if c not in REGRESSORS_EXCLUDE]


def ols(f: pd.DataFrame, cols: list[str] | None = None, mask: pd.Series | None = None) -> tuple[dict, float, int]:
    """Least-squares fit of y on `cols` (+ intercept) over rows where all are finite.
    Returns (coefficients, in-sample RMSE, rows used)."""
    cols = cols or regressors(f)
    y = f["y"].to_numpy()
    X = f[cols].to_numpy()
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
    if mask is not None:
        ok &= mask.reindex(f.index, fill_value=False).to_numpy()
    A = np.column_stack([np.ones(ok.sum()), X[ok]])
    beta, *_ = np.linalg.lstsq(A, y[ok], rcond=None)
    e = y[ok] - A @ beta
    return dict(zip(["const"] + cols, map(float, beta))), float(np.sqrt(np.mean(e ** 2))), int(ok.sum())


def predict(f: pd.DataFrame, coef: dict) -> pd.Series:
    cols = [c for c in coef if c != "const"]
    return coef["const"] + (f[cols] * pd.Series({c: coef[c] for c in cols})).sum(axis=1, min_count=len(cols))


def components(f: pd.DataFrame, coef: dict) -> pd.DataFrame:
    """Each physical component's contribution (ft). const is kept separately; they sum to the model."""
    out = {}
    for name, feats in COMPONENTS.items():
        used = [c for c in feats if c in coef]
        if used:
            out[name] = (f[used] * pd.Series({c: coef[c] for c in used})).sum(axis=1, min_count=len(used))
    out = pd.DataFrame(out, index=f.index)
    out["const"] = coef["const"]
    out["model"] = predict(f, coef)
    out["observed"] = f["y"]
    out["unexplained"] = f["y"] - out["model"]
    return out


def rmse(e) -> float:
    e = np.asarray(e, dtype=float)
    e = e[np.isfinite(e)]
    return float(np.sqrt(np.mean(e ** 2))) if len(e) else float("nan")


def search(inp: pd.DataFrame, models: dict[str, list[str]], masks: dict[str, pd.Series], *,
           taus=range(0, 25), widths=(1, 6, 12, 24, 36, 48), surge_lags=(0, 6, 12),
           fast_taus=range(0, 25, 2)) -> dict:
    """Grid-search τ (lag), w (kernel width), surge lag and fast-kernel lag by in-sample RMSE,
    for every (model, training mask) pair at once. Each feature frame is built once and every
    model/mask is scored against it. Returns {(model, mask_key): {spec, coef, rmse_in, n}}."""
    union = sorted({c for fs in models.values() for c in fs if c != "qf"})
    best: dict = {}
    for tau, w, sl in product(taus, widths, surge_lags):
        f = build_features(inp, dict(features=union, tau=tau, width=w, fast_tau=None, surge_lag=sl))
        for m, fs in models.items():
            if sl and "surge" not in fs:
                continue  # surge lag only matters for models that use surge
            cols = [c for c in fs if c != "qf"]
            for k, mask in masks.items():
                coef, e, n = ols(f, cols, mask)
                if (m, k) not in best or e < best[(m, k)]["rmse_in"]:
                    best[(m, k)] = dict(spec=dict(features=cols, tau=tau, width=w, fast_tau=None,
                                                  surge_lag=sl if "surge" in fs else 0),
                                        coef=coef, rmse_in=e, n=n)
    # Second stage for models with a fast kernel: its lag, with the main kernel held fixed.
    for m, fs in models.items():
        if "qf" not in fs:
            continue
        for k, mask in masks.items():
            spec0, cur = best[(m, k)]["spec"], None
            for ft in fast_taus:
                spec = dict(spec0, features=list(fs), fast_tau=ft)
                coef, e, n = ols(build_features(inp, spec), list(fs), mask)
                if cur is None or e < cur["rmse_in"]:
                    cur = dict(spec=spec, coef=coef, rmse_in=e, n=n)
            best[(m, k)] = cur
    return best


# --- Forecasting -----------------------------------------------------------------
def residual_carry(r0: float, lead_h: np.ndarray, tau_h: float | None) -> np.ndarray:
    """Carry the current model error forward: none, hold (inf), or decay with e-folding tau_h."""
    if tau_h is None:
        return np.zeros(len(lead_h))
    if np.isinf(tau_h):
        return np.full(len(lead_h), r0)
    return r0 * np.exp(-np.asarray(lead_h, dtype=float) / tau_h)


def forecast(inp: pd.DataFrame, spec: dict, coef: dict, t0: pd.Timestamp, hours: int,
             resid_tau_h: float | None, resid_window_h: int = 3) -> pd.DataFrame:
    """Components and stage forecast for t0..t0+hours using only data up to t0.

    Flows persist from their last observation; tide terms come from predictions. The current
    model error (mean over the last `resid_window_h` hours) is carried forward and decays
    with e-folding time resid_tau_h. Columns: components, model, forecast, residual_carry, lead_h."""
    hi = t0 + pd.Timedelta(hours=hours)
    f = build_features(inp.loc[t0 - pd.Timedelta(hours=96):hi], spec, asof=t0)
    c = components(f, coef)
    recent = c["unexplained"].loc[t0 - pd.Timedelta(hours=resid_window_h - 1):t0]
    r0 = float(recent.mean()) if recent.notna().any() else 0.0
    fut = c.loc[t0:hi].copy()
    fut["lead_h"] = ((fut.index - t0) / pd.Timedelta("1h")).astype(int)
    fut["residual_carry"] = residual_carry(r0, fut["lead_h"].to_numpy(), resid_tau_h)
    fut["forecast"] = fut["model"] + fut["residual_carry"]
    fut.attrs["r0"] = r0
    return fut


RESID_TAUS = (None, 3.0, 6.0, 12.0, 24.0, 48.0, float("inf"))


def hindcast(inp: pd.DataFrame, spec: dict, coef: dict, origins, hours: int,
             resid_taus=RESID_TAUS) -> pd.DataFrame:
    """Forecast from each origin with data truncated there; errors (forecast − observed) by lead
    for every residual-carry option. Also scores a baseline anyone could do with a tide table:
    NOAA's raw prediction plus the observed offset over the last 24 h."""
    rows = []
    for t0 in origins:
        fc = forecast(inp, spec, coef, t0, hours, None)
        obs = inp["stage"].reindex(fc.index).to_numpy()
        lead = fc["lead_h"].to_numpy()
        off = (inp["stage"] - inp["pred"]).loc[t0 - pd.Timedelta("23h"):t0].mean()
        rows.append(pd.DataFrame({"origin": t0, "lead_h": lead, "method": "baseline_noaa_plus_offset",
                                  "err": inp["pred"].reindex(fc.index).to_numpy() + off - obs}))
        for rt in resid_taus:
            fcst = fc["model"].to_numpy() + residual_carry(fc.attrs["r0"], lead, rt)
            rows.append(pd.DataFrame({"origin": t0, "lead_h": lead, "method": f"resid_tau_{rt}",
                                      "err": fcst - obs}))
    return pd.concat(rows, ignore_index=True)


# --- Persistence of the fitted model ------------------------------------------------
def clean_json(o):
    """Recursively make an object strict-JSON safe: NaN/±inf -> None, numpy/pandas scalars -> Python."""
    if isinstance(o, dict):
        return {str(k): clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_json(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def dumps(payload, indent=None) -> str:
    return json.dumps(clean_json(payload), indent=indent, default=_json_default, allow_nan=False,
                      ensure_ascii=False, separators=(",", ":") if indent is None else None)


def save(path, payload: dict, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(payload, indent), encoding="utf-8")


def parse_resid_tau(v):
    """coefficients.json stores the residual e-folding time as a number, null (no carry) or "inf"."""
    return float("inf") if v == "inf" else (None if v is None else float(v))


def load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    raise TypeError(type(o))
