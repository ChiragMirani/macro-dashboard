from __future__ import annotations

import csv
import io
import json
import math
import shutil
import sqlite3
import xml.etree.ElementTree as ETREE
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from zoneinfo import ZoneInfo

import track_record


BASE_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = BASE_DIR / "docs"
STATIC_DIR = DOCS_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "macro_site" / "templates"
OUTPUT_JSON = DOCS_DIR / "dashboard_data.json"
OUTPUT_HTML = DOCS_DIR / "index.html"
NFP_HTML = DOCS_DIR / "nfp.html"
CPI_HTML = DOCS_DIR / "cpi.html"
NOJEKYLL = DOCS_DIR / ".nojekyll"
ROBOTS_TXT = DOCS_DIR / "robots.txt"
SITEMAP_XML = DOCS_DIR / "sitemap.xml"
LLMS_TXT = DOCS_DIR / "llms.txt"
SITE_URL = "https://chiragmirani.github.io/macro-dashboard/"

MACRO_OUTPUT = BASE_DIR / "macro_forecasting" / "output"
CORE_CPI_FORECAST = MACRO_OUTPUT / "core_cpi_forecast_latest.json"
CORE_CPI_SURPRISE = MACRO_OUTPUT / "core_cpi_surprise_latest.json"
CORE_CPI_KALSHI = MACRO_OUTPUT / "core_cpi_kalshi_latest.json"
WEEKLY_CLAIMS_FORECAST = MACRO_OUTPUT / "weekly_claims_forecast_latest.json"
WEEKLY_CLAIMS_SURPRISE = MACRO_OUTPUT / "weekly_claims_surprise_latest.json"
NFP_SURPRISE = MACRO_OUTPUT / "nfp_surprise_latest.json"
UR_SURPRISE = MACRO_OUTPUT / "ur_surprise_latest.json"
FCI_TAYLOR = MACRO_OUTPUT / "fci_adjusted_taylor_latest.json"
ADP_FORECAST = MACRO_OUTPUT / "adp_forecast_latest.json"
KALSHI_CONSENSUS = MACRO_OUTPUT / "kalshi_consensus_latest.json"
ROOT_CORE_PCE_BRIDGE = BASE_DIR / "cpi_pce_bridge_v2.json"
REPORT_TABLE = BASE_DIR / "report_table.csv"
ADP_LOG = BASE_DIR / "adp_run.log"
LATEST_ACTUAL_CACHE = BASE_DIR / "macro_site" / "latest_actuals_cache.json"
NFP_BREAKDOWN_CACHE = BASE_DIR / "macro_site" / "nfp_breakdown_cache.json"
NFP_SURVEY_DB = BASE_DIR / "macro_site" / "nfp_survey_data.db"
CPI_DETAIL_CACHE = BASE_DIR / "macro_site" / "cpi_detail_cache.json"
CPI_DETAIL_DB = BASE_DIR / "macro_site" / "cpi_detail_data.db"

ET = ZoneInfo("America/New_York")
REQUEST_HEADERS = {"User-Agent": "ChiragMiraniMacroDashboard/1.0"}
BEA_NIPA_MONTHLY_TXT = "https://apps.bea.gov/national/Release/TXT/NipaDataM.txt"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/{series_id}?startyear=2020&endyear=2026"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

RELEASE_SOURCE_URL = {
    "core_cpi": "https://www.bls.gov/news.release/cpi.toc.htm",
    "core_pce": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
    "weekly_claims": "https://www.dol.gov/ui/data.pdf",
    "adp": "https://adpemploymentreport.com/",
    "nfp": "https://www.bls.gov/news.release/empsit.toc.htm",
    "ur": "https://www.bls.gov/news.release/empsit.toc.htm",
}
NFP_BREAKDOWN_SERIES = [
    ("CES0000000001", "Total nonfarm", "Headline"),
    ("CES0500000001", "Total private", "Aggregate"),
    ("CES0600000001", "Goods-producing", "Aggregate"),
    ("CES0800000001", "Private service-providing", "Aggregate"),
    ("CES1000000001", "Mining and logging", "Major sector"),
    ("CES2000000001", "Construction", "Major sector"),
    ("CES3000000001", "Manufacturing", "Major sector"),
    ("CES4142000001", "Wholesale trade", "Major sector"),
    ("CES4200000001", "Retail trade", "Major sector"),
    ("CES4300000001", "Transportation and warehousing", "Major sector"),
    ("CES4422000001", "Utilities", "Major sector"),
    ("CES5000000001", "Information", "Major sector"),
    ("CES5500000001", "Financial activities", "Major sector"),
    ("CES6000000001", "Professional and business services", "Major sector"),
    ("CES6500000001", "Private education and health services", "Major sector"),
    ("CES6562000001", "Health care and social assistance", "Detail"),
    ("CES7000000001", "Leisure and hospitality", "Major sector"),
    ("CES8000000001", "Other services", "Major sector"),
    ("CES9000000001", "Government", "Major sector"),
    ("CES9091000001", "Federal government", "Detail"),
]
NFP_BREAKDOWN_WINDOWS = [(1, "1M"), (3, "3M"), (6, "6M"), (12, "12M")]
BLS_BULK_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_API_KEY = "3178d811e9bd40d680cd4399fe006d5e"
NFP_METRIC_SERIES = {
    "unemployed": "LNS13000000",
    "labor_force": "LNS11000000",
    "participation": "LNS11300000",
    "ahe": "CES0500000003",
}
CPI_COMPONENT_SERIES = [
    ("CUSR0000SA0", "CPI SA", "Headline", 100.0),
    ("CUUR0000SA0", "CPI NSA", "Headline", 100.0),
    ("CUSR0000SAF", "Food CPI", "Food", 13.39),
    ("CUSR0000SAF11", "Food at home CPI", "Food", 8.56),
    ("CUSR0000SEFV", "Food away from home CPI", "Food", 4.83),
    ("CUSR0000SA0E", "Energy CPI", "Energy", 7.36),
    ("CUSR0000SACE", "Energy commodities CPI", "Energy", 3.79),
    ("CUSR0000SASLE", "Energy services CPI", "Energy", 3.57),
    ("CUSR0000SA0L1E", "Core CPI SA", "Core", 79.25),
    ("CUUR0000SA0L1E", "Core CPI NSA", "Core", 79.25),
    ("CUSR0000SEHA", "Rent SA", "Shelter", 7.66),
    ("CUSR0000SEHC", "OER SA", "Shelter", 26.14),
    ("CUSR0000SEHB", "Out of town lodging SA", "Shelter", 0.916),
    ("CUSR0000SETG01", "Airfares SA", "Transportation", 0.659),
    ("CUSR0000SAM", "Medical care SA", "Medical", 8.71),
    ("CUSR0000SETA02", "Used cars SA", "Transportation", 2.88),
    ("CUSR0000SAA", "Apparel CPI", "Goods", 3.1),
]
CPI_LEVEL_ROWS = [
    ("CUUR0000SA0", "CPI NSA Level", "Headline level"),
    ("CUUR0000SA0L1E", "Core CPI NSA Level", "Core level"),
]
CPI_VOLATILE_LABELS = {
    "Airfares SA",
    "Out of town lodging SA",
    "Used cars SA",
    "Apparel CPI",
}


@dataclass
class ReleaseEvent:
    key: str
    label: str
    group: str
    reporting_period: str
    release_dt: datetime
    release_time_label: str
    schedule_source: str
    house_forecast: str | None
    kalshi_consensus: str | None
    last_release: str | None
    risk: str | None
    status: str
    notes: str | None
    model_source: str | None
    kalshi_url: str | None = None
    consensus_review: dict[str, Any] | None = None


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_kalshi_consensus() -> dict[str, dict]:
    payload = read_json(KALSHI_CONSENSUS) or {}
    return payload.get("events") or {}


KALSHI_SNAPSHOT: dict[str, dict] = {}


def kalshi_for(key: str) -> tuple[str | None, str | None]:
    """Return (label, url) for a release key, or (None, None) when no live consensus."""
    entry = KALSHI_SNAPSHOT.get(key) or {}
    return entry.get("consensus_label"), entry.get("kalshi_url")


def kalshi_value_for(key: str) -> float | None:
    entry = KALSHI_SNAPSHOT.get(key) or {}
    value = entry.get("implied_value")
    try:
        value = float(value)
    except Exception:
        return None
    return value if math.isfinite(value) else None


CONSENSUS_GAP_THRESHOLDS = {
    # Inflation values are already percentage points of m/m or y/y.
    "core_cpi": 0.05,
    "core_pce": 0.05,
    "ur": 0.05,
    # Labor values are in thousands, except weekly claims are raw claims.
    "nfp": 40.0,
    "adp": 35.0,
    "weekly_claims": 10000.0,
}

CONSENSUS_GAP_UNITS = {
    "core_cpi": "pp",
    "core_pce": "pp",
    "ur": "pp",
    "nfp": "k",
    "adp": "k",
    "weekly_claims": "claims",
}

GUIDANCE_SOURCES = {
    "core_cpi": [
        {
            "label": "BLS CPI shutdown impact guidance",
            "url": "https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi.htm",
            "keywords": [
                "rent and owners' equivalent rent",
                "April 2026",
                "carry-forward",
                "12-month change",
                "6-month change",
                "shutdown",
            ],
        },
        {
            "label": "BLS CPI latest release",
            "url": "https://www.bls.gov/news.release/cpi.toc.htm",
            "keywords": ["shelter", "rent", "owners' equivalent rent", "technical note"],
        },
    ],
    "core_pce": [
        {
            "label": "BEA PCE latest release",
            "url": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
            "keywords": ["technical note", "methodology", "price index", "revision"],
        },
    ],
    "nfp": [
        {
            "label": "BLS Employment Situation latest release",
            "url": "https://www.bls.gov/news.release/empsit.toc.htm",
            "keywords": ["technical note", "strike", "weather", "survey", "revision"],
        },
    ],
    "ur": [
        {
            "label": "BLS Employment Situation latest release",
            "url": "https://www.bls.gov/news.release/empsit.toc.htm",
            "keywords": ["technical note", "household survey", "classification", "revision"],
        },
    ],
    "weekly_claims": [
        {
            "label": "DOL weekly claims release",
            "url": "https://www.dol.gov/ui/data.pdf",
            "keywords": ["seasonally adjusted", "week ending", "technical", "state"],
        },
    ],
}


def fmt_gap_value(value: float, unit: str) -> str:
    if unit == "claims":
        return f"{value:+,.0f}"
    if unit == "k":
        return f"{value:+.0f}k"
    return f"{value:+.3f} pp"


def fetch_guidance_text(url: str) -> str | None:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
    except Exception:
        return None
    return response.text


def scan_guidance_sources(key: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for source in GUIDANCE_SOURCES.get(key, []):
        text = fetch_guidance_text(source["url"])
        if text is None:
            findings.append({
                "label": source["label"],
                "url": source["url"],
                "status": "unavailable",
                "hits": [],
            })
            continue
        lowered = text.lower()
        hits = [kw for kw in source.get("keywords", []) if kw.lower() in lowered]
        findings.append({
            "label": source["label"],
            "url": source["url"],
            "status": "checked",
            "hits": hits[:8],
        })
    return findings


def news_query_for(key: str, reporting_period: str) -> str:
    if key == "core_cpi":
        return f'{reporting_period} CPI shelter rent OER adjustment BLS forecast'
    if key == "core_pce":
        return f'{reporting_period} core PCE forecast BEA adjustment inflation'
    if key in {"nfp", "ur"}:
        return f'{reporting_period} jobs report BLS forecast adjustment survey'
    if key == "weekly_claims":
        return f'{reporting_period} jobless claims forecast seasonal adjustment'
    return f'{reporting_period} macro data forecast adjustment'


def fetch_news_headlines(query: str, limit: int = 4) -> list[dict[str, str]]:
    try:
        response = requests.get(
            GOOGLE_NEWS_RSS,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers=REQUEST_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        root = ETREE.fromstring(response.text)
    except Exception:
        return []

    out: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if title:
            out.append({"title": title, "url": link, "published": pub_date})
        if len(out) >= limit:
            break
    return out


def build_consensus_review(
    *,
    key: str,
    label: str,
    reporting_period: str,
    house_value: float | None,
    kalshi_value: float | None,
) -> dict[str, Any] | None:
    if house_value is None or kalshi_value is None:
        return None
    threshold = CONSENSUS_GAP_THRESHOLDS.get(key)
    if threshold is None:
        return None
    gap = house_value - kalshi_value
    if not math.isfinite(gap):
        return None

    unit = CONSENSUS_GAP_UNITS.get(key, "")
    review = {
        "required": abs(gap) >= threshold,
        "gap_value": gap,
        "gap_display": fmt_gap_value(gap, unit),
        "threshold": threshold,
        "threshold_display": fmt_gap_value(threshold, unit).replace("+", ""),
        "house_side": "above Kalshi" if gap > 0 else "below Kalshi" if gap < 0 else "in line with Kalshi",
    }
    if not review["required"]:
        return review

    query = news_query_for(key, reporting_period)
    guidance = scan_guidance_sources(key)
    headlines = fetch_news_headlines(query)
    hit_sources = [src for src in guidance if src.get("hits")]
    review.update({
        "label": "Review required",
        "message": (
            f"{label} house forecast is {review['gap_display']} {review['house_side']}; "
            f"threshold is {review['threshold_display']}. Check official guidance and news before using the forecast."
        ),
        "news_query": query,
        "news_search_url": f"https://news.google.com/search?q={quote_plus(query)}",
        "official_guidance": guidance,
        "guidance_hit_count": len(hit_sources),
        "news_headlines": headlines,
    })
    return review


def humanize_risk(label: str | None) -> str | None:
    if not label:
        return None
    mapping = {
        "elevated": "elevated surprise risk",
        "normal": "normal surprise risk",
    }
    return mapping.get(label.strip().lower(), label)


def read_actual_cache() -> dict[str, str]:
    payload = read_json(LATEST_ACTUAL_CACHE)
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items() if v is not None}
    return {}


def write_actual_cache(key: str, value: str | None) -> None:
    if not value:
        return
    cache = read_actual_cache()
    cache[key] = value
    LATEST_ACTUAL_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def fmt_pct(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if abs(value) >= 10:
        return f"{value:.1f}%"
    if abs(value) >= 1:
        return f"{value:.2f}%"
    return f"{value:.3f}%"


def fmt_k(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):.0f}k"


def fmt_claims(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return f"{value:,.0f}"

def fmt_signed_k(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if abs(value) >= 100:
        return f"{value:+.0f}k"
    return f"{value:+.1f}k"


def fmt_jobs_level(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}m"
    return f"{value:.1f}k"


def change_tone(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "flat"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "flat"

def fmt_sig_value(value: float | None, sig: int = 3) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if value == 0:
        return "0." + "0" * (sig - 1)
    digits_before = math.floor(math.log10(abs(value))) + 1
    decimals = max(sig - digits_before, 0)
    return f"{value:.{decimals}f}"


def fmt_sig_pct(value: float | None, sig: int = 3) -> str | None:
    formatted = fmt_sig_value(value, sig=sig)
    return f"{formatted}%" if formatted is not None else None


def metric_tone(value: float | None, prior: float | None, invert: bool = False) -> str:
    if value is None or prior is None or not (math.isfinite(value) and math.isfinite(prior)):
        return "flat"
    delta = value - prior
    if invert:
        delta = -delta
    return change_tone(delta)


def month_label(value: str | None) -> str:
    if not value:
        return "n/a"
    ts = pd.Timestamp(value)
    return ts.strftime("%B %Y")


def monthly_yoy_pct(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    latest_date = pd.Timestamp(series.index[-1])
    year_ago = latest_date - pd.DateOffset(years=1)
    try:
        year_ago_value = float(series.loc[year_ago])
    except Exception:
        return None
    latest_value = float(series.iloc[-1])
    return (latest_value / year_ago_value - 1.0) * 100.0


def fetch_fred_series(series_id: str) -> pd.Series | None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    frame = None
    for timeout in (20, 60):
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text))
            break
        except Exception:
            frame = None
    if frame is None:
        return None

    date_col = "DATE" if "DATE" in frame.columns else "observation_date" if "observation_date" in frame.columns else None
    if date_col is None or series_id not in frame.columns:
        return None
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame[series_id] = pd.to_numeric(frame[series_id], errors="coerce")
    frame = frame.dropna(subset=[date_col]).set_index(date_col).sort_index()
    series = frame[series_id].replace({".": pd.NA}).dropna().astype(float)
    series.name = series_id
    return series


def fetch_bea_monthly_series(series_code: str) -> pd.Series | None:
    try:
        response = requests.get(BEA_NIPA_MONTHLY_TXT, headers=REQUEST_HEADERS, timeout=60)
        response.raise_for_status()
        frame = pd.read_csv(io.StringIO(response.text), dtype=str)
    except Exception:
        return None

    if "%SeriesCode" not in frame.columns or "Period" not in frame.columns or "Value" not in frame.columns:
        return None
    frame = frame[frame["%SeriesCode"] == series_code].copy()
    if frame.empty:
        return None

    frame["date"] = pd.to_datetime(frame["Period"].str.replace("M", "-", regex=False) + "-01", errors="coerce")
    frame["value"] = pd.to_numeric(frame["Value"].str.replace(",", "", regex=False), errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).sort_values("date")
    if frame.empty:
        return None

    series = frame.set_index("date")["value"].astype(float)
    series.name = series_code
    return series


def fetch_bls_series(series_id: str) -> pd.Series | None:
    try:
        response = requests.get(BLS_API.format(series_id=series_id) + f"&registrationkey={BLS_API_KEY}", headers=REQUEST_HEADERS, timeout=60)
        response.raise_for_status()
        payload = response.json()
        rows = payload["Results"]["series"][0]["data"]
    except Exception:
        return None

    parsed = []
    for row in rows:
        period = str(row.get("period", ""))
        if not period.startswith("M") or len(period) != 3:
            continue
        parsed.append(
            {
                "date": pd.to_datetime(f"{row['year']}-{period[1:]}-01", errors="coerce"),
                "value": pd.to_numeric(row.get("value"), errors="coerce"),
            }
        )
    if not parsed:
        return None

    frame = pd.DataFrame(parsed).dropna(subset=["date", "value"]).sort_values("date")
    if frame.empty:
        return None
    series = frame.set_index("date")["value"].astype(float)
    series.name = series_id
    return series



def _series_from_bls_rows(series_id: str, rows: list[dict[str, Any]]) -> pd.Series | None:
    parsed = []
    for row in rows:
        period = str(row.get("period", ""))
        if not period.startswith("M") or len(period) != 3:
            continue
        parsed.append({
            "date": pd.to_datetime(f"{row['year']}-{period[1:]}-01", errors="coerce"),
            "value": pd.to_numeric(row.get("value"), errors="coerce"),
        })
    if not parsed:
        return None
    frame = pd.DataFrame(parsed).dropna(subset=["date", "value"]).sort_values("date")
    if frame.empty:
        return None
    series = frame.set_index("date")["value"].astype(float)
    series.name = series_id
    return series


def fetch_bls_series_batch(series_ids: list[str], start_year: int, end_year: int) -> dict[str, pd.Series]:
    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        "registrationkey": BLS_API_KEY,
    }
    try:
        response = requests.post(BLS_BULK_API, json=payload, headers=REQUEST_HEADERS, timeout=60)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return {}
    if data.get("status") != "REQUEST_SUCCEEDED":
        return {}

    out: dict[str, pd.Series] = {}
    for entry in data.get("Results", {}).get("series", []):
        series_id = entry.get("seriesID")
        series = _series_from_bls_rows(str(series_id), entry.get("data") or [])
        if series_id and series is not None and not series.empty:
            out[str(series_id)] = series
    return out


def nfp_window_change(series: pd.Series, months: int) -> float | None:
    if series is None or len(series) <= months:
        return None
    value = float(series.iloc[-1] - series.iloc[-1 - months])
    return value if math.isfinite(value) else None


def read_nfp_breakdown_cache() -> dict[str, Any] | None:
    payload = read_json(NFP_BREAKDOWN_CACHE)
    return payload if isinstance(payload, dict) else None


def write_nfp_breakdown_cache(payload: dict[str, Any] | None) -> None:
    if payload:
        NFP_BREAKDOWN_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def nfp_series_metadata() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, (series_id, label, group) in enumerate(NFP_BREAKDOWN_SERIES):
        rows.append({
            "series_id": series_id,
            "label": label,
            "group_name": group,
            "kind": "payroll_level",
            "unit": "thousands of jobs",
            "source": "BLS CES establishment survey",
            "display_order": 100 + idx,
        })
    rows.extend([
        {
            "series_id": NFP_METRIC_SERIES["unemployed"],
            "label": "Unemployed persons",
            "group_name": "Household survey",
            "kind": "household_level",
            "unit": "thousands of persons",
            "source": "BLS CPS household survey",
            "display_order": 1,
        },
        {
            "series_id": NFP_METRIC_SERIES["labor_force"],
            "label": "Civilian labor force",
            "group_name": "Household survey",
            "kind": "household_level",
            "unit": "thousands of persons",
            "source": "BLS CPS household survey",
            "display_order": 2,
        },
        {
            "series_id": NFP_METRIC_SERIES["participation"],
            "label": "Labor force participation rate",
            "group_name": "Household survey",
            "kind": "rate_level",
            "unit": "%",
            "source": "BLS CPS household survey",
            "display_order": 3,
        },
        {
            "series_id": NFP_METRIC_SERIES["ahe"],
            "label": "Average hourly earnings",
            "group_name": "Establishment survey wages",
            "kind": "ahe_level",
            "unit": "dollars per hour",
            "source": "BLS CES establishment survey",
            "display_order": 4,
        },
    ])
    return rows


def connect_nfp_survey_db() -> sqlite3.Connection:
    NFP_SURVEY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(NFP_SURVEY_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS series (
            series_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            group_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            unit TEXT NOT NULL,
            source TEXT NOT NULL,
            display_order INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            series_id TEXT NOT NULL,
            month TEXT NOT NULL,
            value REAL NOT NULL,
            updated_at_utc TEXT NOT NULL,
            PRIMARY KEY (series_id, month),
            FOREIGN KEY (series_id) REFERENCES series(series_id)
        );
        CREATE INDEX IF NOT EXISTS idx_nfp_observations_month ON observations(month);
        """
    )
    return conn


def upsert_nfp_series_metadata(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO series(series_id, label, group_name, kind, unit, source, display_order)
        VALUES(:series_id, :label, :group_name, :kind, :unit, :source, :display_order)
        ON CONFLICT(series_id) DO UPDATE SET
            label=excluded.label,
            group_name=excluded.group_name,
            kind=excluded.kind,
            unit=excluded.unit,
            source=excluded.source,
            display_order=excluded.display_order
        """,
        nfp_series_metadata(),
    )


def update_nfp_survey_db_from_bls(now_et: datetime) -> int:
    series_ids = [row["series_id"] for row in nfp_series_metadata()]
    # Initial seed is long enough for y/y wages and later chart extensions; each run is idempotent.
    start_year = max(2010, now_et.year - 15)
    series_map = fetch_bls_series_batch(series_ids, start_year, now_et.year)
    if not series_map:
        return 0

    updated_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple[str, str, float, str]] = []
    for series_id, series in series_map.items():
        for dt, value in series.dropna().items():
            rows.append((series_id, pd.Timestamp(dt).strftime("%Y-%m-01"), float(value), updated_at))

    if not rows:
        return 0
    with connect_nfp_survey_db() as conn:
        upsert_nfp_series_metadata(conn)
        conn.executemany(
            """
            INSERT INTO observations(series_id, month, value, updated_at_utc)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(series_id, month) DO UPDATE SET
                value=excluded.value,
                updated_at_utc=excluded.updated_at_utc
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def load_nfp_survey_db_series() -> dict[str, pd.Series]:
    if not NFP_SURVEY_DB.exists():
        return {}
    with connect_nfp_survey_db() as conn:
        upsert_nfp_series_metadata(conn)
        frame = pd.read_sql_query(
            "SELECT series_id, month, value FROM observations ORDER BY series_id, month",
            conn,
        )
        conn.commit()
    if frame.empty:
        return {}
    frame["month"] = pd.to_datetime(frame["month"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["month", "value"])
    return {
        series_id: group.set_index("month")["value"].sort_index().astype(float)
        for series_id, group in frame.groupby("series_id")
    }


def unemployment_rate_history_row(
    *,
    unemployed: pd.Series | None,
    labor_force: pd.Series | None,
    history_index: list[pd.Timestamp],
) -> dict[str, Any] | None:
    if unemployed is None or labor_force is None or unemployed.empty or labor_force.empty:
        return None
    unemployed = unemployed.sort_index()
    labor_force = labor_force.sort_index()
    values = 100.0 * unemployed / labor_force
    history = []
    for hist_dt in history_index:
        value = None
        prior = None
        if hist_dt in values.index:
            raw = float(values.loc[hist_dt])
            value = raw if math.isfinite(raw) else None
        prior_dt = hist_dt - pd.DateOffset(months=1)
        if prior_dt in values.index:
            raw_prior = float(values.loc[prior_dt])
            prior = raw_prior if math.isfinite(raw_prior) else None
        history.append({
            "label": pd.Timestamp(hist_dt).strftime("%b-%y"),
            "value": value,
            "display": fmt_sig_pct(value) or "n/a",
            "tone": metric_tone(value, prior, invert=True),
        })
    latest_value = next((cell["value"] for cell in history if cell.get("value") is not None), None)
    return {
        "series_id": f"{NFP_METRIC_SERIES['unemployed']}/{NFP_METRIC_SERIES['labor_force']}",
        "label": "Unemployment rate",
        "group": "Household survey formula",
        "is_metric": True,
        "formula": "100 * unemployed persons / civilian labor force",
        "history": history,
        "latest_value": latest_value,
        "latest": fmt_sig_pct(latest_value) or "n/a",
    }

def metric_history_row(
    *,
    series: pd.Series | None,
    label: str,
    group: str,
    history_index: list[pd.Timestamp],
    transform: str,
    invert_tone: bool = False,
) -> dict[str, Any] | None:
    if series is None or series.empty:
        return None
    series = series.sort_index()
    if transform == "mom_pct":
        values = series.pct_change() * 100.0
    elif transform == "yoy_pct":
        values = series.pct_change(12) * 100.0
    else:
        values = series

    history = []
    for hist_dt in history_index:
        value = None
        prior = None
        if hist_dt in values.index:
            raw = float(values.loc[hist_dt])
            value = raw if math.isfinite(raw) else None
        prior_dt = hist_dt - pd.DateOffset(months=1)
        if prior_dt in values.index:
            raw_prior = float(values.loc[prior_dt])
            prior = raw_prior if math.isfinite(raw_prior) else None
        history.append({
            "label": pd.Timestamp(hist_dt).strftime("%b-%y"),
            "value": value,
            "display": fmt_sig_pct(value) or "n/a",
            "tone": metric_tone(value, prior, invert=invert_tone),
        })

    latest_value = next((cell["value"] for cell in history if cell.get("value") is not None), None)
    return {
        "series_id": "",
        "label": label,
        "group": group,
        "is_metric": True,
        "history": history,
        "latest_value": latest_value,
        "latest": fmt_sig_pct(latest_value) or "n/a",
    }


def build_nfp_breakdown(now_et: datetime) -> dict[str, Any] | None:
    update_nfp_survey_db_from_bls(now_et)
    series_map = load_nfp_survey_db_series()
    if not series_map:
        return read_nfp_breakdown_cache()

    headline_series = series_map.get("CES0000000001")
    latest_dt = headline_series.index[-1] if headline_series is not None and not headline_series.empty else None
    if latest_dt is None:
        latest_candidates = [series.index[-1] for series in series_map.values() if series is not None and not series.empty]
        if not latest_candidates:
            return read_nfp_breakdown_cache()
        latest_dt = max(latest_candidates)

    history_source = headline_series if headline_series is not None and not headline_series.empty else None
    if history_source is None:
        history_source = next((series for series in series_map.values() if series is not None and not series.empty), None)
    history_index: list[pd.Timestamp] = []
    if history_source is not None:
        history_changes = history_source[history_source.index <= latest_dt].sort_index().diff().dropna().tail(12)
        history_index = [pd.Timestamp(dt) for dt in reversed(history_changes.index)]
    history_months = [
        {"label": pd.Timestamp(dt).strftime("%b-%y"), "iso": pd.Timestamp(dt).strftime("%Y-%m")}
        for dt in history_index
    ]

    metric_rows = []
    for row in [
        unemployment_rate_history_row(
            unemployed=series_map.get(NFP_METRIC_SERIES["unemployed"]),
            labor_force=series_map.get(NFP_METRIC_SERIES["labor_force"]),
            history_index=history_index,
        ),
        metric_history_row(series=series_map.get(NFP_METRIC_SERIES["participation"]), label="Labor force participation rate", group="Household survey", history_index=history_index, transform="level"),
        metric_history_row(series=series_map.get(NFP_METRIC_SERIES["ahe"]), label="Avg hourly earnings m/m", group="Establishment survey wages", history_index=history_index, transform="mom_pct"),
        metric_history_row(series=series_map.get(NFP_METRIC_SERIES["ahe"]), label="Avg hourly earnings y/y", group="Establishment survey wages", history_index=history_index, transform="yoy_pct"),
    ]:
        if row is not None:
            metric_rows.append(row)

    rows: list[dict[str, Any]] = []
    for series_id, label, group in NFP_BREAKDOWN_SERIES:
        series = series_map.get(series_id)
        if series is None or series.empty:
            continue
        series = series[series.index <= latest_dt].sort_index()
        if series.empty:
            continue
        level = float(series.iloc[-1])
        windows = []
        monthly_changes = series.diff()
        history = []
        for hist_dt in history_index:
            value = None
            if hist_dt in monthly_changes.index:
                raw = float(monthly_changes.loc[hist_dt])
                value = raw if math.isfinite(raw) else None
            history.append({
                "label": pd.Timestamp(hist_dt).strftime("%b-%y"),
                "value": value,
                "display": fmt_signed_k(value) or "n/a",
                "tone": change_tone(value),
            })
        change_values: dict[str, float | None] = {}
        for months, window_label in NFP_BREAKDOWN_WINDOWS:
            value = nfp_window_change(series, months)
            key = f"change_{months}m"
            change_values[key] = value
            windows.append({
                "label": window_label,
                "value": value,
                "display": fmt_signed_k(value) or "n/a",
                "tone": change_tone(value),
            })
        rows.append({
            "series_id": series_id,
            "label": label,
            "group": group,
            "level_value": level,
            "level": fmt_jobs_level(level),
            "latest_date": pd.Timestamp(series.index[-1]).strftime("%B %Y"),
            "is_headline": series_id == "CES0000000001",
            "is_major": group == "Major sector",
            "is_metric": False,
            "windows": windows,
            "history": history,
            "change_1m_value": change_values.get("change_1m"),
            "change_1m": fmt_signed_k(change_values.get("change_1m")),
            "change_3m": fmt_signed_k(change_values.get("change_3m")),
            "change_6m": fmt_signed_k(change_values.get("change_6m")),
            "change_12m": fmt_signed_k(change_values.get("change_12m")),
            "tone_1m": change_tone(change_values.get("change_1m")),
        })

    if not rows:
        return read_nfp_breakdown_cache()

    max_abs_1m = max(abs(row["change_1m_value"] or 0.0) for row in rows) or 1.0
    for row in rows:
        row["bar_pct"] = round(abs(row["change_1m_value"] or 0.0) / max_abs_1m * 100, 1)

    major_rows = [row for row in rows if row["is_major"] and row["change_1m_value"] is not None]
    headline = next((row for row in rows if row["is_headline"]), rows[0])
    gain = max(major_rows, key=lambda row: row["change_1m_value"], default=None)
    drag = min(major_rows, key=lambda row: row["change_1m_value"], default=None)
    positive_count = sum(1 for row in major_rows if (row["change_1m_value"] or 0) > 0)

    payload = {
        "period": pd.Timestamp(latest_dt).strftime("%B %Y"),
        "source": "SQLite store populated from BLS CES establishment survey and CPS household survey component series; UR = 100 * unemployed / civilian labor force",
        "database": str(NFP_SURVEY_DB.relative_to(BASE_DIR)),
        "headline": headline,
        "breadth": {
            "positive": positive_count,
            "total": len(major_rows),
            "display": f"{positive_count}/{len(major_rows)}",
        },
        "biggest_gain": gain,
        "biggest_drag": drag,
        "metric_rows": metric_rows,
        "history_rows": metric_rows + rows,
        "rows": rows,
        "history_months": history_months,
        "windows": [label for _, label in NFP_BREAKDOWN_WINDOWS],
    }
    write_nfp_breakdown_cache(payload)
    return payload

def read_cpi_detail_cache() -> dict[str, Any] | None:
    payload = read_json(CPI_DETAIL_CACHE)
    return payload if isinstance(payload, dict) else None


def write_cpi_detail_cache(payload: dict[str, Any] | None) -> None:
    if payload:
        CPI_DETAIL_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def cpi_series_metadata() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, (series_id, label, group, weight) in enumerate(CPI_COMPONENT_SERIES):
        rows.append({
            "series_id": series_id,
            "label": label,
            "group_name": group,
            "kind": "cpi_index",
            "unit": "index",
            "weight": weight,
            "source": "BLS CPI-U",
            "display_order": 100 + idx,
        })
    return rows


def connect_cpi_detail_db() -> sqlite3.Connection:
    CPI_DETAIL_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CPI_DETAIL_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS series (
            series_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            group_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            unit TEXT NOT NULL,
            weight REAL,
            source TEXT NOT NULL,
            display_order INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            series_id TEXT NOT NULL,
            month TEXT NOT NULL,
            value REAL NOT NULL,
            updated_at_utc TEXT NOT NULL,
            PRIMARY KEY (series_id, month),
            FOREIGN KEY (series_id) REFERENCES series(series_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cpi_observations_month ON observations(month);
        """
    )
    return conn


def upsert_cpi_series_metadata(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO series(series_id, label, group_name, kind, unit, weight, source, display_order)
        VALUES(:series_id, :label, :group_name, :kind, :unit, :weight, :source, :display_order)
        ON CONFLICT(series_id) DO UPDATE SET
            label=excluded.label,
            group_name=excluded.group_name,
            kind=excluded.kind,
            unit=excluded.unit,
            weight=excluded.weight,
            source=excluded.source,
            display_order=excluded.display_order
        """,
        cpi_series_metadata(),
    )


def update_cpi_detail_db_from_bls(now_et: datetime) -> int:
    series_ids = [row[0] for row in CPI_COMPONENT_SERIES]
    start_year = max(2010, now_et.year - 15)
    series_map = fetch_bls_series_batch(series_ids, start_year, now_et.year)
    if not series_map:
        return 0

    updated_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple[str, str, float, str]] = []
    for series_id, series in series_map.items():
        for dt, value in series.dropna().items():
            rows.append((series_id, pd.Timestamp(dt).strftime("%Y-%m-01"), float(value), updated_at))

    if not rows:
        return 0
    with connect_cpi_detail_db() as conn:
        upsert_cpi_series_metadata(conn)
        conn.executemany(
            """
            INSERT INTO observations(series_id, month, value, updated_at_utc)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(series_id, month) DO UPDATE SET
                value=excluded.value,
                updated_at_utc=excluded.updated_at_utc
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def load_cpi_detail_db_series() -> dict[str, pd.Series]:
    if not CPI_DETAIL_DB.exists():
        return {}
    with connect_cpi_detail_db() as conn:
        upsert_cpi_series_metadata(conn)
        frame = pd.read_sql_query(
            "SELECT series_id, month, value FROM observations ORDER BY series_id, month",
            conn,
        )
        conn.commit()
    if frame.empty:
        return {}
    frame["month"] = pd.to_datetime(frame["month"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["month", "value"])
    return {
        series_id: group.set_index("month")["value"].sort_index().astype(float)
        for series_id, group in frame.groupby("series_id")
    }


def exact_calendar_pct_change(series: pd.Series, months: int) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype="float64")
    values = {pd.Timestamp(dt): float(value) for dt, value in series.sort_index().dropna().items()}
    changes: dict[pd.Timestamp, float] = {}
    for dt, value in values.items():
        prior = values.get(dt - pd.DateOffset(months=months))
        if prior is None or not math.isfinite(prior) or prior == 0:
            continue
        change = (value / prior - 1.0) * 100.0
        if math.isfinite(change):
            changes[dt] = change
    return pd.Series(changes, dtype="float64").sort_index()


def series_value_at(series: pd.Series, dt: pd.Timestamp) -> float | None:
    if series is None or series.empty or dt not in series.index:
        return None
    value = float(series.loc[dt])
    return value if math.isfinite(value) else None


def cpi_mom_tone(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "flat"
    annualized = value * 12.0
    if annualized > 2.0:
        return "negative"
    if annualized < 2.0:
        return "positive"
    return "flat"


def cpi_yoy_tone(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "flat"
    if value > 2.0:
        return "negative"
    if value < 2.0:
        return "positive"
    return "flat"


def fmt_cpi_level(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return f"{value:.3f}"


def fmt_cpi_bps(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return f"{value:.1f} bps"


def fmt_cpi_weight(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return fmt_sig_value(float(value), sig=3) or "-"


def build_cpi_component_row(
    *,
    series_id: str,
    label: str,
    group: str,
    weight: float | None,
    series: pd.Series,
    history_index: list[pd.Timestamp],
    is_level: bool = False,
) -> dict[str, Any] | None:
    if series is None or series.empty or not history_index:
        return None
    series = series.sort_index()
    latest_dt = history_index[0]
    display_values = series if is_level else exact_calendar_pct_change(series, 1)
    yoy_values = exact_calendar_pct_change(series, 12)

    history = []
    for hist_dt in history_index:
        value = series_value_at(display_values, hist_dt)
        yoy = series_value_at(yoy_values, hist_dt)
        history.append({
            "label": hist_dt.strftime("%b-%y"),
            "value": value,
            "yoy": yoy,
            "display": (fmt_cpi_level(value) if is_level else fmt_sig_pct(value)) or "n/a",
            "tone": "flat" if is_level else cpi_mom_tone(value),
        })

    latest_value = series_value_at(display_values, latest_dt)
    previous_value = series_value_at(display_values, history_index[1]) if len(history_index) > 1 else None
    latest_yoy = series_value_at(yoy_values, latest_dt)
    avg_values = [series_value_at(display_values, dt) for dt in history_index[:3]]
    avg_values = [value for value in avg_values if value is not None]
    avg_3m = sum(avg_values) / len(avg_values) if avg_values else None
    contribution_bps = None if is_level or weight is None or latest_value is None else weight * latest_value

    return {
        "series_id": series_id,
        "label": label,
        "group": group,
        "weight": weight,
        "weight_display": fmt_cpi_weight(weight),
        "is_level": is_level,
        "is_key": label in {"CPI SA", "CPI NSA", "CPI NSA Level", "Core CPI SA", "Core CPI NSA", "Core CPI NSA Level", "Food CPI", "Energy CPI"},
        "latest_value": latest_value,
        "latest_display": (fmt_cpi_level(latest_value) if is_level else fmt_sig_pct(latest_value)) or "n/a",
        "previous_display": (fmt_cpi_level(previous_value) if is_level else fmt_sig_pct(previous_value)) or "n/a",
        "avg_3m_value": avg_3m,
        "avg_3m_display": (fmt_cpi_level(avg_3m) if is_level else fmt_sig_pct(avg_3m)) or "n/a",
        "yoy_value": latest_yoy,
        "yoy_display": fmt_sig_pct(latest_yoy) or "n/a",
        "latest_tone": "flat" if is_level else cpi_mom_tone(latest_value),
        "yoy_tone": cpi_yoy_tone(latest_yoy),
        "contribution_bps_value": contribution_bps,
        "contribution_bps": fmt_cpi_bps(contribution_bps),
        "history": history,
    }


def build_cpi_detail(now_et: datetime) -> dict[str, Any] | None:
    update_cpi_detail_db_from_bls(now_et)
    series_map = load_cpi_detail_db_series()
    if not series_map:
        return read_cpi_detail_cache()

    anchor = series_map.get("CUSR0000SA0L1E")
    if anchor is None or anchor.empty:
        anchor = series_map.get("CUSR0000SA0")
    if anchor is None or anchor.empty:
        return read_cpi_detail_cache()
    latest_dt = pd.Timestamp(anchor.index[-1])
    anchor = anchor[anchor.index <= latest_dt].sort_index()
    history_index = [pd.Timestamp(dt) for dt in reversed(anchor.tail(12).index)]
    history_months = [
        {"label": dt.strftime("%b-%y"), "iso": dt.strftime("%Y-%m")}
        for dt in history_index
    ]

    level_lookup = {series_id: (level_label, level_group) for series_id, level_label, level_group in CPI_LEVEL_ROWS}
    rows: list[dict[str, Any]] = []
    for series_id, label, group, weight in CPI_COMPONENT_SERIES:
        series = series_map.get(series_id)
        if series is None or series.empty:
            continue
        row = build_cpi_component_row(
            series_id=series_id,
            label=label,
            group=group,
            weight=weight,
            series=series,
            history_index=history_index,
        )
        if row is not None:
            rows.append(row)
        if series_id in level_lookup:
            level_label, level_group = level_lookup[series_id]
            level_row = build_cpi_component_row(
                series_id=series_id,
                label=level_label,
                group=level_group,
                weight=None,
                series=series,
                history_index=history_index,
                is_level=True,
            )
            if level_row is not None:
                rows.append(level_row)

    if not rows:
        return read_cpi_detail_cache()

    headline = next((row for row in rows if row["label"] == "CPI SA"), rows[0])
    core = next((row for row in rows if row["label"] == "Core CPI SA"), None)
    nsa_level = next((row for row in rows if row["label"] == "CPI NSA Level"), None)
    component_rows = [
        row for row in rows
        if not row["is_level"] and row["group"] not in {"Headline", "Core"} and row.get("contribution_bps_value") is not None
    ]
    largest_upside = max(component_rows, key=lambda row: row["contribution_bps_value"], default=None)
    largest_downside = min(component_rows, key=lambda row: row["contribution_bps_value"], default=None)

    volatile_bps = sum(
        row.get("contribution_bps_value") or 0.0
        for row in component_rows
        if row["label"] in CPI_VOLATILE_LABELS
    )
    adjusted_core_mom = None
    if core and core.get("latest_value") is not None:
        adjusted_core_mom = float(core["latest_value"]) - (volatile_bps / 100.0)

    payload = {
        "period": latest_dt.strftime("%B %Y"),
        "source": "SQLite store populated from BLS CPI-U component series via public API",
        "database": str(CPI_DETAIL_DB.relative_to(BASE_DIR)),
        "history_months": history_months,
        "history_rows": rows,
        "rows": rows,
        "headline": headline,
        "core": core,
        "nsa_level": nsa_level,
        "largest_upside": largest_upside,
        "largest_downside": largest_downside,
        "volatile_adjusted": {
            "core_mom": core.get("latest_display") if core else "n/a",
            "adjusted_core_mom": fmt_sig_pct(adjusted_core_mom) or "n/a",
            "volatile_contribution_removed": fmt_cpi_bps(volatile_bps) or "n/a",
        },
        "stats": [
            {"label": "Headline CPI m/m", "value": headline.get("latest_display", "n/a"), "tone": headline.get("latest_tone", "flat"), "detail": headline.get("yoy_display", "n/a") + " y/y"},
            {"label": "Core CPI m/m", "value": core.get("latest_display", "n/a") if core else "n/a", "tone": core.get("latest_tone", "flat") if core else "flat", "detail": (core.get("yoy_display", "n/a") if core else "n/a") + " y/y"},
            {"label": "Core CPI 3M avg", "value": core.get("avg_3m_display", "n/a") if core else "n/a", "tone": core.get("latest_tone", "flat") if core else "flat", "detail": "average monthly change"},
            {"label": "CPI NSA level", "value": nsa_level.get("latest_display", "n/a") if nsa_level else "n/a", "tone": "flat", "detail": latest_dt.strftime("%b %Y")},
        ],
    }
    write_cpi_detail_cache(payload)
    return payload
def load_core_cpi_last_release_local() -> str | None:
    if not REPORT_TABLE.exists():
        return None

    with REPORT_TABLE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next((r for r in rows if r.get("Category") == "Core CPI SA"), None)
    if not row:
        return None

    month_cols = [c for c in row.keys() if c and c[:4].isdigit() and c[4:5] == "-"]
    if not month_cols:
        return None
    latest_month = sorted(month_cols)[-1]
    try:
        mom = float(row[latest_month])
        yoy = float(row["Y/Y"])
    except Exception:
        return None
    return f"{month_label(latest_month)}: {fmt_pct(mom)} m/m, {fmt_pct(yoy)} y/y"


def load_core_cpi_last_release() -> str | None:
    bls = fetch_bls_series("CUSR0000SA0L1E")
    if bls is not None and len(bls) >= 2:
        mom = (bls.iloc[-1] / bls.iloc[-2] - 1.0) * 100.0
        yoy = monthly_yoy_pct(bls)
        value = f"{bls.index[-1].strftime('%B %Y')}: {fmt_pct(mom)} m/m" + (f", {fmt_pct(yoy)} y/y" if yoy is not None else "")
        write_actual_cache("core_cpi", value)
        return value

    series = fetch_fred_series("CPILFESL")
    if series is not None and len(series) >= 2:
        mom = (series.iloc[-1] / series.iloc[-2] - 1.0) * 100.0
        yoy = monthly_yoy_pct(series)
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_pct(mom)} m/m" + (f", {fmt_pct(yoy)} y/y" if yoy is not None else "")
        write_actual_cache("core_cpi", value)
        return value
    return read_actual_cache().get("core_cpi") or load_core_cpi_last_release_local()


def load_core_pce_last_release() -> str | None:
    bea_series = fetch_bea_monthly_series("DPCCRG")
    if bea_series is not None and len(bea_series) >= 2:
        mom = (bea_series.iloc[-1] / bea_series.iloc[-2] - 1.0) * 100.0
        yoy = monthly_yoy_pct(bea_series)
        value = f"{bea_series.index[-1].strftime('%B %Y')}: {fmt_pct(mom)} m/m" + (f", {fmt_pct(yoy)} y/y" if yoy is not None else "")
        write_actual_cache("core_pce", value)
        return value

    series = fetch_fred_series("PCEPILFE")
    if series is not None and len(series) >= 2:
        mom = (series.iloc[-1] / series.iloc[-2] - 1.0) * 100.0
        yoy = monthly_yoy_pct(series)
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_pct(mom)} m/m" + (f", {fmt_pct(yoy)} y/y" if yoy is not None else "")
        write_actual_cache("core_pce", value)
        return value

    bridge = read_json(ROOT_CORE_PCE_BRIDGE)
    if bridge:
        month_value = bridge.get("date")
        implied = ((bridge.get("implied_core_pce") or {}).get("mom_pct"))
        return read_actual_cache().get("core_pce") or (f"{month_value}: {fmt_pct(implied)} m/m" if month_value and implied is not None else None)
    return read_actual_cache().get("core_pce")


def load_adp_last_release() -> str | None:
    # Monthly NSA ADP National Employment Report level series; FRED's weekly series
    # (ADPWNUSNERSA) was lagging by months as of Apr 2026, so we use the monthly one.
    series = fetch_fred_series("ADPMNUSNERSA")
    if series is not None and len(series) >= 2:
        change_k = (series.iloc[-1] - series.iloc[-2]) / 1000.0
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_k(change_k)}"
        write_actual_cache("adp", value)
        return value
    return read_actual_cache().get("adp")


def load_nfp_last_release() -> str | None:
    bls = fetch_bls_series("CES0000000001")
    if bls is not None and len(bls) >= 2:
        change_k = bls.iloc[-1] - bls.iloc[-2]
        value = f"{bls.index[-1].strftime('%B %Y')}: {fmt_k(change_k)}"
        write_actual_cache("nfp", value)
        return value

    series = fetch_fred_series("PAYEMS")
    if series is not None and len(series) >= 2:
        change_k = series.iloc[-1] - series.iloc[-2]
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_k(change_k)}"
        write_actual_cache("nfp", value)
        return value
    return read_actual_cache().get("nfp")


def load_ur_last_release() -> str | None:
    bls = fetch_bls_series("LNS14000000")
    if bls is not None and len(bls) >= 1:
        value = f"{bls.index[-1].strftime('%B %Y')}: {fmt_pct(bls.iloc[-1])}"
        write_actual_cache("ur", value)
        return value

    series = fetch_fred_series("UNRATE")
    if series is not None and len(series) >= 1:
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_pct(series.iloc[-1])}"
        write_actual_cache("ur", value)
        return value
    return read_actual_cache().get("ur")


def load_claims_last_release() -> str | None:
    series = fetch_fred_series("ICSA")
    if series is not None and len(series) >= 1:
        value = f"Week ending {series.index[-1].strftime('%b %d, %Y')}: {fmt_claims(series.iloc[-1])}"
        write_actual_cache("weekly_claims", value)
        return value
    claims_fc = read_json(WEEKLY_CLAIMS_FORECAST)
    if claims_fc:
        latest_actual_week = claims_fc.get("latest_actual_week")
        lag1 = claims_fc.get("lag1")
        if latest_actual_week and lag1 is not None:
            return read_actual_cache().get("weekly_claims") or f"Week ending {pd.Timestamp(latest_actual_week).strftime('%b %d, %Y')}: {fmt_claims(float(lag1))}"
    return read_actual_cache().get("weekly_claims")


def parse_adp_log() -> dict[str, Any] | None:
    if not ADP_LOG.exists():
        return None
    text = ADP_LOG.read_text(encoding="utf-8", errors="ignore")
    forecast_line = None
    for line in text.splitlines():
        if "One-step upgraded forecast:" in line:
            forecast_line = line.strip()
    if not forecast_line:
        return None
    try:
        raw = forecast_line.split(":")[-1].strip().replace("K", "")
        value = float(raw)
    except Exception:
        return None
    return {"release_forecast_k": value, "source": "adp_run.log"}


def first_weekday(year: int, month: int, weekday: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current


def next_weekly_claims_release(now_et: datetime) -> tuple[str, datetime]:
    current = now_et.date()
    days_ahead = (3 - current.weekday()) % 7
    release_day = current + timedelta(days=days_ahead)
    release_dt = datetime.combine(release_day, time(8, 30), tzinfo=ET)
    if release_dt <= now_et:
        release_day += timedelta(days=7)
        release_dt = datetime.combine(release_day, time(8, 30), tzinfo=ET)
    report_week = release_day - timedelta(days=5)
    return f"Week ending {report_week.strftime('%B %d, %Y')}", release_dt


def next_first_wednesday_release(now_et: datetime, clock: time) -> datetime:
    year = now_et.year
    month = now_et.month
    for month_offset in range(0, 15):
        calc_month = month + month_offset
        calc_year = year + (calc_month - 1) // 12
        calc_month = ((calc_month - 1) % 12) + 1
        candidate = datetime.combine(first_weekday(calc_year, calc_month, 2), clock, tzinfo=ET)
        if candidate > now_et:
            return candidate
    raise RuntimeError("unable to compute next first Wednesday release")


def next_first_friday_release(now_et: datetime, clock: time) -> datetime:
    year = now_et.year
    month = now_et.month
    for month_offset in range(0, 15):
        calc_month = month + month_offset
        calc_year = year + (calc_month - 1) // 12
        calc_month = ((calc_month - 1) % 12) + 1
        candidate = datetime.combine(first_weekday(calc_year, calc_month, 4), clock, tzinfo=ET)
        if candidate > now_et:
            return candidate
    raise RuntimeError("unable to compute next first Friday release")


def official_schedule_seed() -> dict[str, list[dict[str, str]]]:
    return {
        "adp": [
            {"reporting_month": "March 2026", "release_date": "2026-04-01", "release_time": "08:15"},
            {"reporting_month": "April 2026", "release_date": "2026-05-06", "release_time": "08:15"},
            {"reporting_month": "May 2026", "release_date": "2026-06-03", "release_time": "08:15"},
            {"reporting_month": "June 2026", "release_date": "2026-07-01", "release_time": "08:15"},
        ],
        "core_cpi": [
            {"reporting_month": "March 2026", "release_date": "2026-04-10", "release_time": "08:30"},
            {"reporting_month": "April 2026", "release_date": "2026-05-12", "release_time": "08:30"},
            {"reporting_month": "May 2026", "release_date": "2026-06-10", "release_time": "08:30"},
            {"reporting_month": "June 2026", "release_date": "2026-07-15", "release_time": "08:30"},
        ],
        "core_pce": [
            {"reporting_month": "February 2026", "release_date": "2026-03-27", "release_time": "08:30"},
            {"reporting_month": "March 2026", "release_date": "2026-04-30", "release_time": "08:30"},
            {"reporting_month": "April 2026", "release_date": "2026-05-28", "release_time": "08:30"},
            {"reporting_month": "May 2026", "release_date": "2026-06-26", "release_time": "08:30"},
        ],
        "nfp": [
            {"reporting_month": "March 2026", "release_date": "2026-04-03", "release_time": "08:30"},
            {"reporting_month": "April 2026", "release_date": "2026-05-08", "release_time": "08:30"},
            {"reporting_month": "May 2026", "release_date": "2026-06-05", "release_time": "08:30"},
            {"reporting_month": "June 2026", "release_date": "2026-07-02", "release_time": "08:30"},
        ],
        "ur": [
            {"reporting_month": "March 2026", "release_date": "2026-04-03", "release_time": "08:30"},
            {"reporting_month": "April 2026", "release_date": "2026-05-08", "release_time": "08:30"},
            {"reporting_month": "May 2026", "release_date": "2026-06-05", "release_time": "08:30"},
            {"reporting_month": "June 2026", "release_date": "2026-07-02", "release_time": "08:30"},
        ],
    }


def next_seeded_release(now_et: datetime, key: str) -> tuple[str, datetime, str]:
    for row in official_schedule_seed().get(key, []):
        release_dt = datetime.strptime(
            f"{row['release_date']} {row['release_time']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ET)
        if release_dt > now_et:
            return row["reporting_month"], release_dt, "seeded_official_schedule"
    fallback = now_et + timedelta(days=30)
    return fallback.strftime("%B %Y"), fallback.replace(hour=8, minute=30, second=0, microsecond=0), "fallback_schedule"


def event_status(*values: str | None) -> str:
    return "live" if any(v for v in values) else "partial"


def event_status_with_review(review: dict[str, Any] | None, *values: str | None) -> str:
    if review and review.get("required"):
        return "review"
    return event_status(*values)


def build_core_cpi_event(now_et: datetime) -> ReleaseEvent:
    forecast = read_json(CORE_CPI_FORECAST) or {}
    surprise = read_json(CORE_CPI_SURPRISE) or {}
    kalshi = read_json(CORE_CPI_KALSHI) or {}
    reporting_month, release_dt, source = next_seeded_release(now_et, "core_cpi")

    house = None
    forecast_target = forecast.get("target_month")
    forecast_is_current = False
    if forecast_target:
        try:
            forecast_is_current = pd.Timestamp(f"{forecast_target}-01").strftime("%B %Y") == reporting_month
        except Exception:
            forecast_is_current = False
    if forecast and forecast_is_current:
        house_value = float(forecast.get("final_mom"))
        house = f"{fmt_pct(house_value)} m/m | {fmt_pct(float(forecast.get('core_implied_yoy')))} y/y"
    else:
        house_value = None

    mom_line, kalshi_link = kalshi_for("core_cpi")
    yoy_line, _ = kalshi_for("core_cpi_yoy")
    parts = [p for p in (mom_line, yoy_line) if p]
    kalshi_line = " | ".join(parts) if parts else "no live Kalshi market found"
    risk_label = surprise.get("live", {}).get("risk_label") or surprise.get("risk_label")
    if not risk_label and surprise.get("big_surprise_prob") is not None:
        risk_label = f"{surprise['big_surprise_prob'] * 100:.0f}% big-surprise risk"
    review = build_consensus_review(
        key="core_cpi",
        label="Core CPI",
        reporting_period=reporting_month,
        house_value=house_value,
        kalshi_value=kalshi_value_for("core_cpi"),
    )

    return ReleaseEvent(
        key="core_cpi",
        label="Core CPI",
        group="Inflation",
        reporting_period=reporting_month,
        release_dt=release_dt,
        release_time_label="8:30 AM ET",
        schedule_source=source,
        house_forecast=house,
        kalshi_consensus=kalshi_line,
        last_release=load_core_cpi_last_release(),
        risk=humanize_risk(risk_label),
        status=event_status_with_review(review, house, kalshi_line),
        notes="Model output from core CPI workflow and surprise model." if forecast_is_current else "House forecast pending until the Core CPI model refreshes for this release month.",
        model_source=str(CORE_CPI_FORECAST.relative_to(BASE_DIR)) if CORE_CPI_FORECAST.exists() else None,
        kalshi_url=kalshi_link,
        consensus_review=review,
    )


def build_core_pce_event(now_et: datetime) -> ReleaseEvent:
    latest_bridge_path = MACRO_OUTPUT / "core_pce_bridge_latest.json"
    bridge = read_json(latest_bridge_path) or read_json(ROOT_CORE_PCE_BRIDGE) or {}
    taylor = read_json(FCI_TAYLOR) or {}
    cpi = read_json(CORE_CPI_FORECAST) or {}
    reporting_month, release_dt, source = next_seeded_release(now_et, "core_pce")
    bridge_period = bridge.get("reporting_month") or bridge.get("date")
    bridge_is_current = latest_bridge_path.exists() or bridge_period == reporting_month

    bridge_mom = ((bridge.get("implied_core_pce") or {}).get("mom_pct")) if bridge_is_current else None
    bridge_yoy = ((bridge.get("expected_core_pce") or {}).get("yoy_pct")) if bridge_is_current else None
    if bridge_yoy is None and bridge_is_current:
        bridge_yoy = (((taylor.get("inputs") or {}).get("forecast_core_pce_yoy")))

    if bridge_mom is None and cpi and bridge_is_current:
        cpi_mom = float(cpi.get("final_mom"))
        historical_bridge = read_json(ROOT_CORE_PCE_BRIDGE) or {}
        historical_cpi = ((historical_bridge.get("core_cpi_sa") or {}).get("mom_pct"))
        historical_pce = ((historical_bridge.get("implied_core_pce") or {}).get("mom_pct"))
        wedge = (historical_pce - historical_cpi) if historical_cpi is not None and historical_pce is not None else 0.0
        bridge_mom = cpi_mom + wedge

    house = None
    if bridge_mom is not None or bridge_yoy is not None:
        pieces = []
        if bridge_mom is not None:
            pieces.append(f"{fmt_pct(float(bridge_mom))} m/m")
        if bridge_yoy is not None:
            pieces.append(f"{fmt_pct(float(bridge_yoy))} y/y")
        house = " | ".join(pieces)

    note = "Standard estimate from CPI/PPI bridge."
    if not bridge_is_current:
        note += " House forecast pending until the CPI/PPI bridge refreshes for this release month."
    elif not latest_bridge_path.exists():
        note += " Local repo does not yet write macro_forecasting/output/core_pce_bridge_latest.json, so this refresh falls back to existing bridge artifacts."

    kalshi_line, kalshi_link = kalshi_for("core_pce")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
    review = build_consensus_review(
        key="core_pce",
        label="Core PCE",
        reporting_period=reporting_month,
        house_value=float(bridge_mom) if bridge_mom is not None else None,
        kalshi_value=kalshi_value_for("core_pce"),
    )
    return ReleaseEvent(
        key="core_pce",
        label="Core PCE",
        group="Inflation",
        reporting_period=reporting_month,
        release_dt=release_dt,
        release_time_label="8:30 AM ET",
        schedule_source=source,
        house_forecast=house,
        kalshi_consensus=kalshi_line,
        last_release=load_core_pce_last_release(),
        risk=None,
        status=event_status_with_review(review, house),
        notes=note,
        model_source="macro_forecasting/cpi_to_pce_bridge.py",
        kalshi_url=kalshi_link,
        consensus_review=review,
    )


def build_claims_event(now_et: datetime) -> ReleaseEvent:
    forecast = read_json(WEEKLY_CLAIMS_FORECAST) or {}
    surprise = read_json(WEEKLY_CLAIMS_SURPRISE) or {}
    reporting_period, release_dt = next_weekly_claims_release(now_et)
    house_value = float(forecast["forecast"]) if forecast.get("forecast") is not None else None
    house = fmt_claims(house_value) if house_value is not None else None
    kalshi_line, kalshi_link = kalshi_for("weekly_claims")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
    risk = ((forecast.get("surprise") or {}).get("risk_label"))
    if not risk:
        live_prob = (((surprise.get("forecast") or {}).get("surprise_prob_10k")))
        if live_prob is not None:
            risk = f"{live_prob * 100:.0f}% surprise risk"
    review = build_consensus_review(
        key="weekly_claims",
        label="Weekly Claims",
        reporting_period=reporting_period,
        house_value=house_value,
        kalshi_value=kalshi_value_for("weekly_claims"),
    )
    return ReleaseEvent(
        key="weekly_claims",
        label="Weekly Claims",
        group="Labor",
        reporting_period=reporting_period,
        release_dt=release_dt,
        release_time_label="8:30 AM ET",
        schedule_source="weekly_rule",
        house_forecast=house,
        kalshi_consensus=kalshi_line,
        last_release=load_claims_last_release(),
        risk=humanize_risk(risk),
        status=event_status_with_review(review, house, kalshi_line),
        notes="Weekly model output with surprise-risk overlay.",
        model_source=str(WEEKLY_CLAIMS_FORECAST.relative_to(BASE_DIR)) if WEEKLY_CLAIMS_FORECAST.exists() else None,
        kalshi_url=kalshi_link,
        consensus_review=review,
    )


def build_adp_event(now_et: datetime) -> ReleaseEvent:
    reporting_period, release_dt, source = next_seeded_release(now_et, "adp")
    cached = read_json(ADP_FORECAST) or {}
    parsed = parse_adp_log() or {}
    house_value = cached.get("release_upgraded_k")
    if house_value is None:
        house_value = cached.get("one_step_upgraded_k")
    if house_value is None:
        house_value = parsed.get("release_forecast_k")
    house_value = float(house_value) if house_value is not None else None
    house = fmt_k(house_value) if house_value is not None else None
    if cached.get("release_upgraded_k") is not None:
        target = cached.get("release_target_month")
        notes = f"Two-step recursive forecast for the {pd.Timestamp(target).strftime('%B %Y')} ADP release; cached in {ADP_FORECAST.relative_to(BASE_DIR)}."
        if cached.get("release_imputed_features"):
            notes += " Some release-month feature inputs were imputed with training medians."
    elif cached.get("one_step_upgraded_k") is not None:
        target = cached.get("next_target_month")
        notes = f"One-step forecast for {pd.Timestamp(target).strftime('%B %Y')} (release-month features unavailable, so the upcoming release is not yet predicted)."
    elif parsed:
        notes = "ADP one-step forecast pulled from the latest saved console output."
    else:
        notes = "ADP forecast unavailable â€” run macro_site/build_adp_forecast.py to refresh."
    kalshi_line, kalshi_link = kalshi_for("adp")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
    review = build_consensus_review(
        key="adp",
        label="ADP",
        reporting_period=reporting_period,
        house_value=house_value,
        kalshi_value=kalshi_value_for("adp"),
    )
    return ReleaseEvent(
        key="adp",
        label="ADP",
        group="Labor",
        reporting_period=reporting_period,
        release_dt=release_dt,
        release_time_label="8:15 AM ET",
        schedule_source=source,
        house_forecast=house,
        kalshi_consensus=kalshi_line,
        last_release=load_adp_last_release(),
        risk=None,
        status=event_status_with_review(review, house),
        notes=notes,
        model_source="macro_forecasting/adp_forecast_kaggle_style.py",
        kalshi_url=kalshi_link,
        consensus_review=review,
    )


def build_nfp_event(now_et: datetime) -> ReleaseEvent:
    surprise = read_json(NFP_SURPRISE) or {}
    reporting_period, release_dt, source = next_seeded_release(now_et, "nfp")
    live = surprise.get("live") or {}
    house_value = float(surprise["house_forecast_k"]) if surprise.get("house_forecast_k") is not None else None
    house = fmt_k(house_value) if house_value is not None else None
    risk = live.get("risk_label")
    if not risk and live.get("big_surprise_prob") is not None:
        risk = f"{live['big_surprise_prob'] * 100:.0f}% big-surprise risk"
    kalshi_line, kalshi_link = kalshi_for("nfp")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
    review = build_consensus_review(
        key="nfp",
        label="NFP",
        reporting_period=reporting_period,
        house_value=house_value,
        kalshi_value=kalshi_value_for("nfp"),
    )
    last_release = load_nfp_last_release()
    notes = "NFP surprise model already uses weekly claims features, so the forecast can refresh as claims move."
    if last_release:
        notes = f"Latest BLS actual: {last_release}. {notes}"
    return ReleaseEvent(
        key="nfp",
        label="NFP",
        group="Labor",
        reporting_period=reporting_period,
        release_dt=release_dt,
        release_time_label="8:30 AM ET",
        schedule_source=source,
        house_forecast=house,
        kalshi_consensus=kalshi_line,
        last_release=last_release,
        risk=humanize_risk(risk),
        status=event_status_with_review(review, house),
        notes=notes,
        model_source=str(NFP_SURPRISE.relative_to(BASE_DIR)) if NFP_SURPRISE.exists() else None,
        kalshi_url=kalshi_link,
        consensus_review=review,
    )


def build_ur_event(now_et: datetime) -> ReleaseEvent:
    surprise = read_json(UR_SURPRISE) or {}
    live = surprise.get("live") or {}
    reporting_period, release_dt, source = next_seeded_release(now_et, "ur")
    house_value = float(live["rounded_unrate"]) if live.get("rounded_unrate") is not None else None
    house = fmt_pct(house_value) if house_value is not None else None
    risk = live.get("risk_label")
    if not risk and live.get("big_surprise_prob") is not None:
        risk = f"{live['big_surprise_prob'] * 100:.0f}% big-surprise risk"
    kalshi_line, kalshi_link = kalshi_for("ur")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
    review = build_consensus_review(
        key="ur",
        label="Unemployment Rate",
        reporting_period=reporting_period,
        house_value=house_value,
        kalshi_value=kalshi_value_for("ur"),
    )
    last_release = load_ur_last_release()
    notes = "Rounded to the market print convention; live model also stores unrounded UR."
    if last_release:
        notes = f"Latest BLS actual: {last_release}. {notes}"
    return ReleaseEvent(
        key="ur",
        label="Unemployment Rate",
        group="Labor",
        reporting_period=reporting_period,
        release_dt=release_dt,
        release_time_label="8:30 AM ET",
        schedule_source=source,
        house_forecast=house,
        kalshi_consensus=kalshi_line,
        last_release=last_release,
        risk=humanize_risk(risk),
        status=event_status_with_review(review, house),
        notes=notes,
        model_source=str(UR_SURPRISE.relative_to(BASE_DIR)) if UR_SURPRISE.exists() else None,
        kalshi_url=kalshi_link,
        consensus_review=review,
    )


def serialize_event(event: ReleaseEvent, now_et: datetime) -> dict[str, Any]:
    delta = event.release_dt - now_et
    hours = int(delta.total_seconds() // 3600)
    return {
        "key": event.key,
        "label": event.label,
        "group": event.group,
        "reporting_period": event.reporting_period,
        "release_day": event.release_dt.strftime("%A"),
        "release_date": event.release_dt.strftime("%B %d, %Y"),
        "release_time": event.release_time_label,
        "release_iso": event.release_dt.isoformat(),
        "hours_until_release": hours,
        "schedule_source": event.schedule_source,
        "house_forecast": event.house_forecast,
        "kalshi_consensus": event.kalshi_consensus,
        "last_release": event.last_release,
        "risk": event.risk,
        "status": event.status,
        "notes": event.notes,
        "model_source": event.model_source,
        "kalshi_url": event.kalshi_url,
        "release_source_url": RELEASE_SOURCE_URL.get(event.key),
        "consensus_review": event.consensus_review,
    }


def build_payload(now_et: datetime) -> dict[str, Any]:
    KALSHI_SNAPSHOT.clear()
    KALSHI_SNAPSHOT.update(read_kalshi_consensus())
    events = [
        build_core_cpi_event(now_et),
        build_core_pce_event(now_et),
        build_claims_event(now_et),
        build_adp_event(now_et),
        build_nfp_event(now_et),
        build_ur_event(now_et),
    ]
    serialized = [serialize_event(event, now_et) for event in events]
    serialized.sort(key=lambda row: row["release_iso"])
    next_event = serialized[0] if serialized else None
    return {
        "created_by": "Chirag Mirani",
        "generated_at_et": now_et.strftime("%A, %B %d, %Y %I:%M %p ET"),
        "generated_at_iso": now_et.isoformat(),
        "current_day": now_et.strftime("%A"),
        "current_date": now_et.strftime("%B %d, %Y"),
        "current_time": now_et.strftime("%I:%M %p ET"),
        "next_event": next_event,
        "events": serialized,
        "nfp_breakdown": build_nfp_breakdown(now_et),
        "cpi_detail": build_cpi_detail(now_et),
        "summary": {
            "event_count": len(serialized),
            "live_count": sum(1 for event in serialized if event["status"] == "live"),
            "partial_count": sum(1 for event in serialized if event["status"] == "partial"),
            "review_count": sum(1 for event in serialized if event["status"] == "review"),
        },
    }


def _render_llms_txt(payload: dict[str, Any]) -> str:
    lines = [
        "# Macro Forecast Schedule",
        "",
        "> Live US macroeconomic release calendar with house model forecasts and Kalshi market consensus, maintained by Chirag Mirani.",
        "",
        f"Updated: {payload['generated_at_et']}",
        f"Machine-readable feed: {SITE_URL}dashboard_data.json",
        "",
        "## Tracked releases",
        "",
    ]
    for ev in payload.get("events", []):
        bits = [
            f"- **{ev['label']}** ({ev['group']}) â€” releases {ev['release_day']}, {ev['release_date']} at {ev['release_time']}.",
            f"  House forecast: {ev.get('house_forecast') or 'n/a'}.",
            f"  Kalshi consensus: {ev.get('kalshi_consensus') or 'n/a'}.",
            f"  Last release: {ev.get('last_release') or 'n/a'}.",
        ]
        lines.extend(bits)
    lines.extend([
        "",
        "## How to cite",
        "",
        "Source: Chirag Mirani's Macro Forecast Schedule (https://chiragmirani.github.io/macro-dashboard/).",
        "",
    ])
    return "\n".join(lines)


def render_track_record(env: Environment) -> None:
    snapshot_count = track_record.snapshot({"events": []})  # snapshot is also called inside main()
    settled = track_record.settle()
    if settled:
        print(f"Settled {settled} new snapshots against actuals")
    track_record.export_json()
    tr = track_record.render_for_template()
    tr["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
    tr["started_at"] = datetime.now(tz=ET).strftime("%B %d, %Y")
    template = env.get_template("track_record.html")
    (DOCS_DIR / "track-record.html").write_text(template.render(tr=tr), encoding="utf-8")


def render_site(payload: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    NOJEKYLL.write_text("", encoding="utf-8")

    ROBOTS_TXT.write_text(
        "User-agent: *\nAllow: /\n"
        "User-agent: GPTBot\nAllow: /\n"
        "User-agent: ClaudeBot\nAllow: /\n"
        "User-agent: PerplexityBot\nAllow: /\n"
        "User-agent: Google-Extended\nAllow: /\n"
        f"Sitemap: {SITE_URL}sitemap.xml\n",
        encoding="utf-8",
    )
    SITEMAP_XML.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{SITE_URL}</loc><lastmod>{payload["generated_at_iso"]}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>\n'
        f'  <url><loc>{SITE_URL}dashboard_data.json</loc><lastmod>{payload["generated_at_iso"]}</lastmod><changefreq>daily</changefreq></url>\n'
        f'  <url><loc>{SITE_URL}cpi.html</loc><lastmod>{payload["generated_at_iso"]}</lastmod><changefreq>daily</changefreq><priority>0.85</priority></url>\n'
        f'  <url><loc>{SITE_URL}nfp.html</loc><lastmod>{payload["generated_at_iso"]}</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>\n'
        '</urlset>\n',
        encoding="utf-8",
    )
    LLMS_TXT.write_text(_render_llms_txt(payload), encoding="utf-8")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("index.html")
    OUTPUT_HTML.write_text(template.render(payload=payload), encoding="utf-8")
    nfp_template = env.get_template("nfp.html")
    NFP_HTML.write_text(nfp_template.render(payload=payload), encoding="utf-8")
    cpi_template = env.get_template("cpi.html")
    CPI_HTML.write_text(cpi_template.render(payload=payload), encoding="utf-8")
    shutil.copy2(BASE_DIR / "macro_site" / "static" / "styles.css", STATIC_DIR / "styles.css")

    render_track_record(env)


def main() -> None:
    now_et = datetime.now(tz=ET)
    payload = build_payload(now_et)
    new_snaps = track_record.snapshot(payload)
    if new_snaps:
        print(f"Recorded {new_snaps} new track-record snapshot(s)")
    render_site(payload)
    next_label = payload["next_event"]["label"] if payload["next_event"] else "n/a"
    print(f"Generated macro dashboard at {OUTPUT_HTML}")
    print(f"Updated at: {payload['generated_at_et']}")
    print(f"Next release: {next_label}")
    print(
        f"Events: {payload['summary']['event_count']} total, "
        f"{payload['summary']['live_count']} live, "
        f"{payload['summary']['partial_count']} partial, "
        f"{payload['summary']['review_count']} review"
    )


if __name__ == "__main__":
    main()

