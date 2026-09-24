"""Quality control for USACE hourly flow (known for gaps and occasional bad values)."""

import numpy as np
import pandas as pd

from . import config as cfg
from .signal import fill_short_gaps


def qc_flow(s: pd.Series, lo=cfg.QC["lo"], hi=cfg.QC["hi"], spike_kcfs=cfg.QC["spike_kcfs"],
            spike_k=cfg.QC["spike_k"], flat_hours=cfg.QC["flat_hours"], max_fill=cfg.QC["max_fill"]):
    """Return (clean hourly series on a complete grid, per-hour flag DataFrame).

    missing: hour absent/null.  range: outside [lo, hi] kcfs.
    spike: > max(spike_kcfs, spike_k·robust σ) from the 7-h centered median. These are *suspect*,
      not proven bad; real operational changes are steps, which the median follows.
    flat: same value repeated >= flat_hours (stuck telemetry).
    Bad values are masked; interior gaps <= max_fill hours are interpolated.
    """
    s = s.dropna()
    if s.empty:
        return s, pd.DataFrame()
    full = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="h"))
    f = pd.DataFrame(index=full.index)
    f["missing"] = full.isna()
    f["range"] = (full < lo) | (full > hi)
    med = full.rolling(7, center=True, min_periods=3).median()
    dev = (full - med).abs()
    robust_sigma = 1.4826 * dev.rolling(7 * 24, center=True, min_periods=24).median()
    f["spike"] = dev > np.maximum(spike_kcfs, spike_k * robust_sigma)
    runs = (full.diff() != 0).cumsum()
    f["flat"] = full.groupby(runs).transform("size").ge(flat_hours) & full.notna()
    bad = f[["range", "spike", "flat"]].any(axis=1)
    clean = fill_short_gaps(full.mask(bad), max_fill)
    f["filled"] = clean.notna() & (full.isna() | bad)
    f["still_missing"] = clean.isna()
    return clean, f


def merge_bonneville(dataquery: pd.Series, cda: pd.Series):
    """Dataquery is primary (it filled 73 h that CDA lacked in June 2026); CDA fills holes. Then QC."""
    raw = dataquery.combine_first(cda) if len(cda) else dataquery
    return qc_flow(raw)
