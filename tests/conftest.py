import numpy as np
import pandas as pd
import pytest

M2 = 12.4206  # principal lunar semidiurnal period, hours
S2 = 12.0
K1 = 23.9345


@pytest.fixture
def synthetic():
    """60 days of synthetic raw inputs at native cadence, plus the 'true' generating model.

    Stage is built from the same physics the model assumes, so the fit should recover it."""
    rng = np.random.default_rng(42)
    t0 = pd.Timestamp("2026-01-01", tz="UTC")
    h = pd.date_range(t0, periods=60 * 24, freq="h")
    hrs = np.arange(len(h))

    six = pd.date_range(t0, h[-1], freq="6min")
    x6 = (six - t0) / pd.Timedelta("1h")
    pred6 = pd.Series(1.0 + 0.2 * np.sin(2 * np.pi * x6 / (24 * 30))           # slow 'seasonal river'
                      + 1.0 * np.cos(2 * np.pi * x6 / M2) + 0.3 * np.cos(2 * np.pi * x6 / S2)
                      + 0.4 * np.cos(2 * np.pi * x6 / K1), index=six)

    bon = pd.Series(150 + 40 * np.sin(2 * np.pi * hrs / (24 * 20)) + 10 * np.sin(2 * np.pi * hrs / 24)
                    + rng.normal(0, 2, len(h)), index=h)

    five = pd.date_range(t0, h[-1], freq="5min")
    x5 = (five - t0) / pd.Timedelta("1h")
    wil5 = pd.Series(20000 + 8000 * np.sin(2 * np.pi * x5 / (24 * 15)) + 30000 * np.cos(2 * np.pi * x5 / M2),
                     index=five)  # tidal reversal on top of net flow

    q15 = pd.date_range(t0, h[-1], freq="15min")
    stage15 = pd.Series(np.nan, index=q15)  # filled by tests via the model
    return dict(h=h, pred6=pred6, bon=bon, wil5=wil5, stage15=stage15, rng=rng)
