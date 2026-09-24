import json

import numpy as np
import pandas as pd
import pytest

from riverbrain.features import build_features, build_inputs
from riverbrain.model import predict
from riverbrain.run import run

from .test_model import SPEC, TRUE

EMPTY = pd.Series(dtype="float64")


def fake_coef():
    skill = {str(h): {"rmse": 0.2 + 0.01 * h, "bias": 0.0, "p05": -0.3, "p95": 0.3, "n": 100} for h in range(49)}
    return {
        "schema": 1, "model_name": "test", "fitted_utc": "2026-01-01T00:00:00+00:00",
        "spec": SPEC, "coef": TRUE,
        "training": {"bonneville_range_kcfs": [70, 460], "input_medians": {"bon": 150.0, "wil": 20.0}},
        "cv": {"pooled_rmse_ft": {"test": 0.3}},
        "forecast": {"resid_tau_h": 24.0, "resid_window_h": 3, "skill_ft": skill},
        "spring_neap_quantiles": {"p25": 0.9, "p75": 1.1},
    }


@pytest.fixture
def raw(synthetic):
    s = synthetic
    inp = build_inputs(s["h"], stage15=EMPTY, bon=s["bon"], wil5=s["wil5"], pred6=s["pred6"])
    y = predict(build_features(inp, SPEC), TRUE)
    stage15 = y.reindex(pd.date_range(s["h"][0], s["h"][-1], freq="15min")).interpolate(limit_area="inside")
    obs_nwps = (stage15 + 0.13).iloc[::2]
    fc_idx = pd.date_range("2026-02-10 01:00", periods=48, freq="h", tz="UTC")
    return dict(stage=stage15, wil=s["wil5"], pred=s["pred6"], dq=s["bon"], cda=EMPTY, spill=EMPTY, gen=EMPTY,
                nwps=(obs_nwps, pd.Series(3.0, index=fc_idx), "2026-02-10T00:00:00Z"),
                fish=pd.DataFrame(), chem={})


def test_run_writes_valid_outputs(raw, tmp_path):
    t_run = pd.Timestamp("2026-02-10 00:20", tz="UTC")
    for k in ("stage", "wil", "dq"):
        raw[k] = raw[k][raw[k].index <= t_run]
    files = run(t_run, tmp_path / "data", tmp_path / "archive", raw=raw, errors={}, coef=fake_coef())

    for name in ("now.json", "history_30d.json", "model.json", "fish.json", "chem.json"):
        json.loads((tmp_path / "data" / name).read_text(encoding="utf-8"))  # strict JSON parses

    now = files["now.json"]
    assert now["now"]["analysis_hour"] == "2026-02-10T00:00:00Z"
    for h in ("3h", "6h", "24h"):
        a = now["why_it_moved"][h]
        assert sum(a["components_ft"].values()) == pytest.approx(a["observed_change_ft"], abs=0.01)
    assert len(now["forecast"]["hours"]) == 49
    assert all(r["lo_ft"] <= r["stage_ft"] <= r["hi_ft"] for r in now["forecast"]["hours"])
    assert now["nws_forecast"]["offset_ft_nwps_minus_usgs"] == pytest.approx(0.13, abs=0.01)
    assert len(now["next_tides"]) >= 2
    assert now["drivers"]["spring_neap"]["state"]
    assert now["freshness"]["stage"]["status"] == "ok"

    hist = files["history_30d.json"]
    assert len(hist["t"]) == len(hist["stage"]) == 30 * 24 + 1

    # Archive: one line per analysis hour, not duplicated on re-run
    run(t_run, tmp_path / "data", tmp_path / "archive", raw=raw, errors={}, coef=fake_coef())
    lines = (tmp_path / "archive" / "forecasts" / "2026-02.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_run_survives_missing_bonneville(raw, tmp_path):
    t_run = pd.Timestamp("2026-02-10 00:20", tz="UTC")
    raw["dq"] = raw["dq"][raw["dq"].index <= t_run - pd.Timedelta("20h")]  # dam data 20 h stale
    raw["stage"] = raw["stage"][raw["stage"].index <= t_run]
    files = run(t_run, tmp_path, None, raw=raw, errors={"bonneville_cda": "boom"}, coef=fake_coef())
    now = files["now.json"]
    assert now["freshness"]["bonneville"]["status"] == "stale"
    assert any("bonneville" in w.lower() for w in now["warnings"])
    assert np.isfinite(now["forecast"]["hours"][10]["stage_ft"])


def test_run_holds_missing_source_at_typical_value(raw, tmp_path):
    t_run = pd.Timestamp("2026-02-10 00:20", tz="UTC")
    raw["stage"] = raw["stage"][raw["stage"].index <= t_run]
    raw["dq"] = raw["dq"][raw["dq"].index <= t_run]
    raw["wil"] = EMPTY  # Willamette API down all month
    now = run(t_run, tmp_path, None, raw=raw, errors={"willamette": "down"}, coef=fake_coef())["now.json"]
    assert now["why_it_moved"]["6h"]["components_ft"]["willamette"] == 0
    assert any("No Willamette data" in w for w in now["warnings"])
    assert all(np.isfinite(h["stage_ft"]) for h in now["forecast"]["hours"])
