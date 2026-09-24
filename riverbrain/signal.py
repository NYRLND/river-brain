"""Small signal-processing helpers (numpy only; SciPy is deliberately not a dependency)."""

import numpy as np
import pandas as pd


def godin(x: pd.Series) -> pd.Series:
    """Godin tidal low-pass: 24 h, 24 h and 25 h centered moving averages in sequence
    (hourly input). Removes diurnal and semidiurnal tides; loses ~36 h at each edge."""
    return x.rolling(24, center=True).mean().rolling(24, center=True).mean().rolling(25, center=True).mean()


def analytic(x: np.ndarray) -> np.ndarray:
    """Analytic signal x + i·H[x] via FFT (same as scipy.signal.hilbert)."""
    n = len(x)
    h = np.zeros(n)
    h[0] = 1
    if n % 2 == 0:
        h[n // 2] = 1
        h[1:n // 2] = 2
    else:
        h[1:(n + 1) // 2] = 2
    return np.fft.ifft(np.fft.fft(x) * h)


def fill_short_gaps(s: pd.Series, max_len: int) -> pd.Series:
    """Linearly interpolate interior NaN runs of <= max_len samples; leave longer runs alone.
    (pandas' interpolate(limit=n) would fill the first n samples of a long gap.)"""
    isna = s.isna()
    run_id = (isna != isna.shift()).cumsum()
    run_len = isna.groupby(run_id).transform("size")
    fillable = isna & (run_len <= max_len)
    return s.where(~fillable, s.interpolate(limit_area="inside"))


def trailing_mean(s: pd.Series, window: int, min_frac: float = 0.8) -> pd.Series:
    """Causal mean over the last `window` samples (inclusive of the current one)."""
    return s.rolling(window, min_periods=max(1, int(np.ceil(min_frac * window)))).mean()


def hold_last(s: pd.Series) -> pd.Series:
    """Persistence: carry the last valid value forward to the end of the index.
    Interior gaps are left as they are."""
    last = s.last_valid_index()
    if last is None:
        return s
    out = s.copy()
    out[out.index > last] = s[last]
    return out
