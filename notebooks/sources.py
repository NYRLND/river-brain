"""Data fetchers for the River Brain feasibility notebook.

Each fetcher returns tidy pandas objects indexed by UTC timestamps and caches
the raw API response under data/raw/ so the notebook is reproducible even
after provisional data are revised upstream.  These are written so they can
be lifted into the production GitHub Action with little change.
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import certifi
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
REFRESH = os.environ.get("RB_REFRESH") == "1"  # set to re-download everything

UA = {"User-Agent": "RiverBrain/0.1 (personal non-commercial project)"}

# The USACE Dataquery host serves only its leaf certificate and omits the
# DigiCert intermediate, so Python cannot build a chain with certifi alone.
# We append the (public) intermediate to certifi's bundle rather than turning
# verification off.
_CA_BUNDLE = RAW.parent / "ca_bundle.pem"
if not _CA_BUNDLE.exists() or REFRESH:
    _CA_BUNDLE.write_text(
        Path(certifi.where()).read_text()
        + "\n"
        + (ROOT / "certs" / "digicert_global_g2_tls_rsa_sha256_2020_ca1.pem").read_text()
    )


def _get(url: str, params: dict | None = None, *, headers: dict | None = None,
         verify: str | bool = True, tries: int = 4, timeout: int = 90) -> requests.Response:
    """GET with simple exponential backoff on network errors and 5xx/429."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})},
                             timeout=timeout, verify=verify)
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
                return r
        except requests.RequestException:
            if i == tries - 1:
                raise
        time.sleep(2 ** i)
    r.raise_for_status()
    return r


def _cached(name: str, fetch) -> str:
    """Return cached text for `name`, calling fetch() to populate it if needed."""
    path = RAW / name
    if path.exists() and not REFRESH:
        return path.read_text(encoding="utf-8")
    text = fetch()
    path.write_text(text, encoding="utf-8")
    return text


def _month_chunks(start: pd.Timestamp, end: pd.Timestamp, days: int = 31):
    t = start
    while t < end:
        u = min(t + pd.Timedelta(days=days), end)
        yield t, u
        t = u


# --------------------------------------------------------------------------
# 1. USGS Water Data API (OGC API - Features), https://api.waterdata.usgs.gov
# --------------------------------------------------------------------------
USGS_BASE = "https://api.waterdata.usgs.gov/ogcapi/v1/collections"


def usgs_continuous(site: str, pcode: str, start, end) -> pd.DataFrame:
    """Instantaneous ('continuous') values for one site/parameter.

    Returns DataFrame[value, approval_status, qualifier] indexed by UTC time.
    Requests are chunked by month (~3k rows at 15-min) to stay under the
    10k-row page limit, so no cursor pagination is needed.
    """
    start, end = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    frames = []
    for a, b in _month_chunks(start, end):
        name = f"usgs_{site}_{pcode}_{a:%Y%m%d}_{b:%Y%m%d}.csv"

        def fetch(a=a, b=b):
            return _get(f"{USGS_BASE}/continuous/items", dict(
                f="csv", monitoring_location_id=f"USGS-{site}", parameter_code=pcode,
                time=f"{a:%Y-%m-%dT%H:%M:%SZ}/{b:%Y-%m-%dT%H:%M:%SZ}",
                properties="time,value,approval_status,qualifier", limit=10000)).text

        text = _cached(name, fetch)
        df = pd.read_csv(io.StringIO(text))
        assert len(df) < 10000, "hit page limit; shorten chunks"
        frames.append(df)
    df = pd.concat(frames)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.drop(columns=["x", "y"], errors="ignore").set_index("time").sort_index()
    df = df[~df.index.duplicated()]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


# --------------------------------------------------------------------------
# 2. NOAA CO-OPS, https://api.tidesandcurrents.noaa.gov
# --------------------------------------------------------------------------
COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def noaa_series(product: str, station: str, start, end, datum: str = "MLLW") -> pd.Series:
    """6-minute tide 'predictions' or observed 'water_level' (ft, UTC)."""
    start, end = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    out = []
    for a, b in _month_chunks(start, end, days=30):  # water_level max is 31 d
        name = f"noaa_{station}_{product}_{datum}_{a:%Y%m%d}_{b:%Y%m%d}.json"

        def fetch(a=a, b=b):
            p = dict(product=product, station=station, datum=datum, units="english",
                     time_zone="gmt", format="json", application="RiverBrain",
                     begin_date=f"{a:%Y%m%d %H:%M}", end_date=f"{b:%Y%m%d %H:%M}")
            if product == "predictions":
                p["interval"] = "6"
            return _get(COOPS, p).text

        d = json.loads(_cached(name, fetch))
        if "error" in d:
            raise RuntimeError(d["error"])
        rows = d.get("predictions") or d.get("data")
        s = pd.Series({r["t"]: r["v"] for r in rows})
        out.append(s)
    s = pd.concat(out)
    s.index = pd.to_datetime(s.index, utc=True)
    s = pd.to_numeric(s, errors="coerce")
    return s[~s.index.duplicated()].sort_index()


# --------------------------------------------------------------------------
# 3. USACE Bonneville outflow: Dataquery 2.0 and CWMS Data API (CDA)
# --------------------------------------------------------------------------
BON_TSID = "BON.Flow-Out.Ave.1Hour.1Hour.CBT-REV"


def usace_dataquery(start, end, tsid: str = BON_TSID) -> pd.Series:
    """Hourly outflow in kcfs from NWD Dataquery 2.0 (getjson)."""
    start, end = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    name = f"dataquery_{tsid}_{start:%Y%m%d}_{end:%Y%m%d}.json"
    text = _cached(name, lambda: _get(
        "https://www.nwd-wc.usace.army.mil/dd/common/web_service/webexec/getjson",
        dict(query=json.dumps([tsid]), timezone="GMT",
             startdate=f"{start:%m/%d/%Y %H:%M}", enddate=f"{end:%m/%d/%Y %H:%M}"),
        verify=str(_CA_BUNDLE)).text)
    site = tsid.split(".")[0]
    vals = json.loads(text)[site]["timeseries"][tsid]["values"]
    s = pd.Series({v[0]: v[1] for v in vals}, dtype="float64")
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


def usace_cda(start, end, tsid: str = BON_TSID, office: str = "NWDP") -> pd.DataFrame:
    """Hourly outflow from the CWMS Data API. Returns DataFrame[kcfs, quality]."""
    start, end = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    name = f"cda_{tsid}_{start:%Y%m%d}_{end:%Y%m%d}.json"
    text = _cached(name, lambda: _get(
        "https://cwms-data.usace.army.mil/cwms-data/timeseries",
        {"name": tsid, "office": office, "begin": f"{start:%Y-%m-%dT%H:%M:%SZ}",
         "end": f"{end:%Y-%m-%dT%H:%M:%SZ}", "page-size": 20000},
        headers={"Accept": "application/json;version=2"}).text)
    d = json.loads(text)
    assert d["total"] <= 20000
    df = pd.DataFrame(d["values"], columns=["t", "cfs", "quality"])
    df.index = pd.to_datetime(df.pop("t"), unit="ms", utc=True)
    df["kcfs"] = df.pop("cfs") / 1000.0
    return df[["kcfs", "quality"]]


# --------------------------------------------------------------------------
# 4. NWS National Water Prediction Service, https://api.water.noaa.gov/nwps/v1
# --------------------------------------------------------------------------
NWPS = "https://api.water.noaa.gov/nwps/v1"


def nwps_stageflow(lid: str = "VAPW1", snapshot: str | None = None):
    """Observed + forecast stage.  NWPS only serves the *current* forecast, so
    each call is a snapshot; `snapshot` names the cache file to pin one."""
    name = f"nwps_{lid}_stageflow_{snapshot or pd.Timestamp.now('UTC'):%Y%m%dT%H}.json" \
        if snapshot is None else f"nwps_{lid}_stageflow_{snapshot}.json"
    d = json.loads(_cached(name, lambda: _get(f"{NWPS}/gauges/{lid}/stageflow").text))
    out = {}
    for key in ("observed", "forecast"):
        blk = d[key]
        s = pd.Series({r["validTime"]: r["primary"] for r in blk["data"]}, dtype="float64")
        s.index = pd.to_datetime(s.index, utc=True)
        s[s <= -999] = float("nan")
        s.attrs = {"issuedTime": blk.get("issuedTime"), "units": blk.get("primaryUnits")}
        out[key] = s.sort_index()
    return out["observed"], out["forecast"]


def nwps_gauge(lid: str = "VAPW1") -> dict:
    return json.loads(_cached(f"nwps_{lid}_gauge.json", lambda: _get(f"{NWPS}/gauges/{lid}").text))


# --------------------------------------------------------------------------
# 5. Columbia River DART adult passage, https://www.cbr.washington.edu/dart
# --------------------------------------------------------------------------
def dart_adult_daily(year: int, start: str = "1/1", end: str = "12/31",
                     proj: str = "BON", avg: bool = True) -> pd.DataFrame:
    """Daily adult counts by species; with avg=True adds <Species>10Yr columns."""
    name = f"dart_{proj}_{year}_{start.replace('/', '-')}_{end.replace('/', '-')}_avg{int(avg)}.csv"
    text = _cached(name, lambda: _get(
        "https://www.cbr.washington.edu/dart/cs/php/rpt/adult_daily.php",
        dict(sc=1, outputFormat="csv", year=year, proj=proj, span="no",
             startdate=start, enddate=end, **({"avg": 1} if avg else {}))).text)
    # CSV body ends at the first blank / footnote line
    lines = [ln for ln in text.splitlines() if ln.startswith(("Project,", "Bonneville,"))]
    df = pd.read_csv(io.StringIO("\n".join(lines)))
    # With avg=1 DART emits a Feb 29 row (10-yr average) even in non-leap years.
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df.dropna(subset=["Date"]).set_index("Date")
