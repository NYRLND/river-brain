"""Site identifiers, thresholds and paths. Anything a reviewer might want to check lives here."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
COEF_PATH = MODEL_DIR / "coefficients.json"
CERT_PATH = ROOT / "certs" / "digicert_global_g2_tls_rsa_sha256_2020_ca1.pem"

# --- Sites ------------------------------------------------------------------
USGS_STAGE_SITE = "14144700"      # Columbia River at Vancouver, WA (across from Hayden Island)
USGS_WILLAMETTE_SITE = "14211720"  # Willamette River at Portland (5-min Q, reverses with tide)
USGS_SANDY_SITE = "14142500"       # Sandy River below Bull Run: enters between Bonneville and Vancouver
NOAA_VANCOUVER = "9440083"         # tide predictions
NOAA_ASTORIA = "9439040"           # ocean end: storm surge = observed - predicted
NWPS_LID = "VAPW1"
BON_TSID = "BON.Flow-Out.Ave.1Hour.1Hour.CBT-REV"
BON_SPILL_TSID = "BON.Flow-Spill.Ave.1Hour.1Hour.CBT-REV"
BON_GEN_TSID = "BON.Flow-Gen.Ave.1Hour.1Hour.CBT-REV"
USACE_OFFICE = "NWDP"

# Willamette at Portland real-time water quality (all verified live 2026-09-23)
CHEM_PARAMS = {
    "00010": ("water_temp", "°C"),
    "00300": ("dissolved_oxygen", "mg/L"),
    "00400": ("ph", "pH units"),
    "00095": ("specific_conductance", "µS/cm at 25 °C"),
    "63680": ("turbidity", "FNU"),
    "99137": ("nitrate", "mg/L as N"),
    "32295": ("fdom", "QSE"),
    "32315": ("chlorophyll_fchl", "RFU"),
    "32321": ("phycocyanin_fpc", "RFU"),
}

# DART species columns -> display names
FISH_SPECIES = {
    "Chin": "Chinook (adult)", "JChin": "Chinook (jack)", "Stlhd": "Steelhead", "Coho": "Coho",
    "Sock": "Sockeye", "Shad": "Shad", "LmpryDay": "Lamprey (daytime)",
}

# --- Datums (see README) ----------------------------------------------------
USGS_GAGE_DATUM = "USGS gage datum (NGVD29 + 1.82 ft)"
NWPS_FLOOD_STAGES_FT = {"action": 15.0, "minor": 16.0, "moderate": 20.0, "major": 25.0}  # NWPS datum

# --- Bonneville QC ----------------------------------------------------------
QC = dict(lo=10.0, hi=700.0, spike_kcfs=25.0, spike_k=6.0, flat_hours=8, max_fill=3)

# --- Freshness: a source older than this (hours) is flagged stale ------------
STALE_HOURS = {"stage": 2, "bonneville": 6, "willamette": 3, "sandy": 3, "astoria": 3, "tide_predictions": 0,
               "nwps_forecast": 12, "fish": 72, "chemistry": 6}

# --- Hourly run windows -------------------------------------------------------
RUN_HISTORY_DAYS = 34     # 30 days shown + warm-up for trailing windows / Godin filter
RUN_FUTURE_DAYS = 16      # tide predictions ahead: 48 h forecast + next spring/neap
FORECAST_HOURS = 48
ATTRIBUTION_HOURS = (3, 6, 24)
