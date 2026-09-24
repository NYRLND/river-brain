"""Fetchers for every data source. Each returns pandas objects indexed by UTC time.

Pass a `Cache` to keep raw responses on disk (the offline fit does; the hourly run
doesn't). Set USGS_API_KEY in the environment to send a USGS Water Data API key:
anonymous requests are rate-limited per IP, and GitHub Actions runners share IPs.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time
from pathlib import Path

import certifi
import pandas as pd
import requests

from . import config as cfg

UA = {"User-Agent": "RiverBrain/0.2 (personal non-commercial project; github.com)"}


class Cache:
    """Raw-response cache keyed by file name. refresh=True re-downloads."""

    def __init__(self, directory: Path | str, refresh: bool = False):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.refresh = refresh

    def get(self, name: str, fetch) -> str:
        p = self.dir / name
        if p.exists() and not self.refresh:
            return p.read_text(encoding="utf-8")
        text = fetch()
        p.write_text(text, encoding="utf-8")
        return text


def _cached(cache: Cache | None, name: str, fetch) -> str:
    return cache.get(name, fetch) if cache else fetch()


# The USACE Dataquery host omits its DigiCert intermediate from the TLS handshake.
# Build certifi + that (public) intermediate into a bundle instead of disabling verification.
_CA_BUNDLE = Path(tempfile.gettempdir()) / "riverbrain_ca_bundle.pem"


def ca_bundle() -> str:
    if not _CA_BUNDLE.exists():
        _CA_BUNDLE.write_text(Path(certifi.where()).read_text() + "\n" + cfg.CERT_PATH.read_text())
    return str(_CA_BUNDLE)


class RateLimited(RuntimeError):
    def __init__(self, msg: str, retry_after_s: int = 3600):
        super().__init__(msg)
        self.retry_after_s = retry_after_s


def get(url: str, params: dict | None = None, *, headers: dict | None = None,
        verify: str | bool = True, tries: int = 4, timeout: int = 120) -> requests.Response:
    """GET with exponential backoff on network errors, 429 and 5xx."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})},
                             timeout=timeout, verify=verify)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "60") or 60)
                if wait > 120:
                    raise RateLimited(
                        f"rate limited by {url.split('/')[2]} (limit {r.headers.get('X-Ratelimit-Limit', '?')}/h); "
                        f"retry in {wait // 60} min. For USGS, set USGS_API_KEY (free) to raise the limit.", wait)
                time.sleep(wait)
                continue
            if r.status_code < 500:
                r.raise_for_status()
                return r
            last = requests.HTTPError(f"{r.status_code} for {r.url}")
        except RateLimited:
            raise
        except requests.RequestException as e:
            last = e
        time.sleep(2 ** i)
    raise last


def _chunks(start: pd.Timestamp, end: pd.Timestamp, days: int):
    t = start
    while t < end:
        u = min(t + pd.Timedelta(days=days), end)
        yield t, u
        t = u


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


# --- USGS Water Data API (OGC API - Features, v1) -----------------------------
USGS = "https://api.waterdata.usgs.gov/ogcapi/v1/collections"


def usgs_continuous(site: str, pcode: str, start, end, *, chunk_days: int = 31,
                    cache: Cache | None = None) -> pd.Series:
    """Instantaneous values (float), indexed by UTC time. Chunks keep each page < 10k rows
    (31 days of 5-min data is 8,928 rows)."""
    start, end = _utc(start), _utc(end)
    headers = {"X-Api-Key": os.environ["USGS_API_KEY"]} if os.environ.get("USGS_API_KEY") else {}
    frames = []
    for a, b in _chunks(start, end, chunk_days):
        def fetch(a=a, b=b):
            return get(f"{USGS}/continuous/items", dict(
                f="csv", monitoring_location_id=f"USGS-{site}", parameter_code=pcode,
                time=f"{a:%Y-%m-%dT%H:%M:%SZ}/{b:%Y-%m-%dT%H:%M:%SZ}",
                properties="time,value", limit=10000), headers=headers).text
        text = _cached(cache, f"usgs_{site}_{pcode}_{a:%Y%m%dT%H}_{b:%Y%m%dT%H}.csv", fetch)
        df = pd.read_csv(io.StringIO(text))
        if len(df) >= 10000:
            raise RuntimeError(f"USGS page limit hit for {site}/{pcode} {a}..{b}; shorten chunks")
        frames.append(df)
    df = pd.concat(frames)
    if df.empty:
        return pd.Series(dtype="float64", name=pcode)
    s = pd.Series(pd.to_numeric(df["value"], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df["time"], utc=True), name=pcode)
    return s[~s.index.duplicated()].sort_index()


# --- NOAA CO-OPS -------------------------------------------------------------
COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def noaa_series(product: str, station: str, start, end, *, datum: str = "MLLW",
                cache: Cache | None = None) -> pd.Series:
    """6-minute 'predictions' (1-year chunks allowed) or 'water_level' (31-day limit), ft."""
    start, end = _utc(start), _utc(end)
    days = 365 if product == "predictions" else 30
    out = []
    for a, b in _chunks(start, end, days):
        def fetch(a=a, b=b):
            p = dict(product=product, station=station, datum=datum, units="english",
                     time_zone="gmt", format="json", application="RiverBrain",
                     begin_date=f"{a:%Y%m%d %H:%M}", end_date=f"{b:%Y%m%d %H:%M}")
            if product == "predictions":
                p["interval"] = "6"
            return get(COOPS, p).text
        d = json.loads(_cached(cache, f"noaa_{station}_{product}_{a:%Y%m%dT%H}_{b:%Y%m%dT%H}.json", fetch))
        if "error" in d:
            # water_level returns an error for windows with no data; treat as a gap
            if product == "water_level":
                continue
            raise RuntimeError(f"NOAA {product} {station}: {d['error']}")
        rows = d.get("predictions") or d.get("data") or []
        out.append(pd.Series({r["t"]: r["v"] for r in rows}, dtype="object"))
    if not out:
        return pd.Series(dtype="float64")
    s = pd.concat(out)
    s.index = pd.to_datetime(s.index, utc=True)
    s = pd.to_numeric(s, errors="coerce")
    return s[~s.index.duplicated()].sort_index()


# --- USACE ---------------------------------------------------------------------
def usace_dataquery(start, end, tsid: str = cfg.BON_TSID, *, cache: Cache | None = None) -> pd.Series:
    """Hourly values (kcfs for flows) from NWD Dataquery 2.0."""
    start, end = _utc(start), _utc(end)
    site = tsid.split(".")[0]
    out = []
    for a, b in _chunks(start, end, 366):
        def fetch(a=a, b=b):
            return get("https://www.nwd-wc.usace.army.mil/dd/common/web_service/webexec/getjson",
                       dict(query=json.dumps([tsid]), timezone="GMT",
                            startdate=f"{a:%m/%d/%Y %H:%M}", enddate=f"{b:%m/%d/%Y %H:%M}"),
                       verify=ca_bundle()).text
        d = json.loads(_cached(cache, f"dq_{tsid}_{a:%Y%m%dT%H}_{b:%Y%m%dT%H}.json", fetch))
        ts = d.get(site, {}).get("timeseries", {}).get(tsid)
        if ts:
            out.append(pd.Series({v[0]: v[1] for v in ts["values"]}, dtype="float64"))
    if not out:
        return pd.Series(dtype="float64")
    s = pd.concat(out)
    s.index = pd.to_datetime(s.index, utc=True)
    return s[~s.index.duplicated()].sort_index()


def usace_cda(start, end, tsid: str = cfg.BON_TSID, *, cache: Cache | None = None) -> pd.Series:
    """Hourly values from the CWMS Data API, converted cfs -> kcfs. Nulls kept as NaN."""
    start, end = _utc(start), _utc(end)
    out = []
    for a, b in _chunks(start, end, 366):
        def fetch(a=a, b=b):
            return get("https://cwms-data.usace.army.mil/cwms-data/timeseries",
                       {"name": tsid, "office": cfg.USACE_OFFICE, "begin": f"{a:%Y-%m-%dT%H:%M:%SZ}",
                        "end": f"{b:%Y-%m-%dT%H:%M:%SZ}", "page-size": 20000},
                       headers={"Accept": "application/json;version=2"}).text
        d = json.loads(_cached(cache, f"cda_{tsid}_{a:%Y%m%dT%H}_{b:%Y%m%dT%H}.json", fetch))
        vals = d.get("values") or []
        if vals:
            df = pd.DataFrame(vals, columns=["t", "v", "q"])
            out.append(pd.Series(df["v"].to_numpy(dtype="float64") / 1000.0,
                                 index=pd.to_datetime(df["t"], unit="ms", utc=True)))
    if not out:
        return pd.Series(dtype="float64")
    s = pd.concat(out)
    return s[~s.index.duplicated()].sort_index()


# --- NWS NWPS --------------------------------------------------------------------
NWPS = "https://api.water.noaa.gov/nwps/v1"


def nwps_stageflow(lid: str = cfg.NWPS_LID) -> tuple[pd.Series, pd.Series, str | None]:
    """(observed stage, forecast stage, forecast issuedTime). NWPS datum, ft.
    Only the current forecast is available, so callers should archive it."""
    d = get(f"{NWPS}/gauges/{lid}/stageflow").json()
    out = []
    for key in ("observed", "forecast"):
        rows = d.get(key, {}).get("data", [])
        s = pd.Series({r["validTime"]: r["primary"] for r in rows}, dtype="float64")
        s.index = pd.to_datetime(s.index, utc=True)
        out.append(s.where(s > -999).sort_index())
    return out[0], out[1], d.get("forecast", {}).get("issuedTime")


# --- DART ------------------------------------------------------------------------
def dart_adult_daily(year: int, proj: str = "BON", *, cache: Cache | None = None) -> pd.DataFrame:
    """Daily adult counts by species with <Species>10Yr columns and TempC."""
    text = _cached(cache, f"dart_{proj}_{year}.csv", lambda: get(
        "https://www.cbr.washington.edu/dart/cs/php/rpt/adult_daily.php",
        dict(sc=1, outputFormat="csv", year=year, proj=proj, span="no",
             startdate="1/1", enddate="12/31", avg=1)).text)
    # Keep the header and data rows (second field is a date); drop the footnotes.
    lines = [ln for ln in text.splitlines()
             if ln.startswith("Project,") or re.match(r"^[^,]*,\d{4}-\d{2}-\d{2},", ln)]
    df = pd.read_csv(io.StringIO("\n".join(lines)))
    # With avg=1 DART emits a Feb 29 row (10-yr average) even in non-leap years.
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df.dropna(subset=["Date"]).set_index("Date")
