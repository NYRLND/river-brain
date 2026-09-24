import numpy as np
import pandas as pd

from riverbrain.qc import qc_flow
from riverbrain.signal import analytic, fill_short_gaps, godin, hold_last, trailing_mean

H = pd.date_range("2026-01-01", periods=24 * 30, freq="h", tz="UTC")
X = np.arange(len(H), dtype=float)


def test_godin_removes_tides_keeps_mean():
    s = pd.Series(3.0 + np.cos(2 * np.pi * X / 12.42) + 0.5 * np.cos(2 * np.pi * X / 23.93), index=H)
    low = godin(s).dropna()
    assert abs(low.mean() - 3.0) < 0.01
    assert (low - 3.0).abs().max() < 0.02  # tidal energy suppressed by >98%


def test_analytic_gives_quadrature():
    x = np.cos(2 * np.pi * X / 12.42)
    a = analytic(x)
    mid = slice(100, -100)  # FFT edge effects
    assert np.allclose(a.real, x)
    assert np.allclose(a.imag[mid], np.sin(2 * np.pi * X / 12.42)[mid], atol=0.05)
    assert np.allclose(np.abs(a)[mid], 1.0, atol=0.05)


def test_fill_short_gaps_leaves_long_gaps_untouched():
    s = pd.Series(np.arange(20, dtype=float))
    s[3:5] = np.nan     # 2-sample gap: fill
    s[10:17] = np.nan   # 7-sample gap: leave completely (pandas' limit= would fill part of it)
    out = fill_short_gaps(s, 3)
    assert out[3:5].tolist() == [3.0, 4.0]
    assert out[10:17].isna().all()


def test_hold_last_only_fills_tail():
    s = pd.Series([1.0, np.nan, 3.0, np.nan, np.nan])
    out = hold_last(s)
    assert np.isnan(out[1]) and out[3] == 3.0 and out[4] == 3.0


def test_trailing_mean_is_causal():
    s = pd.Series(np.arange(10, dtype=float))
    m1 = trailing_mean(s, 3)
    s2 = s.copy()
    s2[6:] = 999
    assert m1[:6].equals(trailing_mean(s2, 3)[:6])


def test_qc_catches_injected_faults():
    rng = np.random.default_rng(0)
    q = pd.Series(150 + 10 * np.sin(X / 20) + rng.normal(0, 1, len(H)), index=H)
    q.iloc[100] = 0.0            # dropout (range)
    q.iloc[200] += 60            # spike
    q.iloc[300:312] = q.iloc[300]  # 12 h stuck (flat)
    q.iloc[400] = -999           # sentinel (range)
    short, long_ = H[500:502], H[600:610]
    q = q.drop(short).drop(long_)  # 2-h hole: fill; 10-h hole: leave
    clean, f = qc_flow(q)
    assert f["range"].iloc[100] and f["range"].iloc[400]
    assert f["spike"].iloc[200]
    assert f["flat"].iloc[300:312].all()
    assert clean[short].notna().all()
    assert clean[long_].isna().all()
    assert clean.iloc[300:312].isna().all()  # a 12-h stuck run is longer than max_fill
    assert clean.dropna().between(10, 700).all()
