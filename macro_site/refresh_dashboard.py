from __future__ import annotations

import csv
import io
import json
import math
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

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

ET = ZoneInfo("America/New_York")
REQUEST_HEADERS = {"User-Agent": "ChiragMiraniMacroDashboard/1.0"}

RELEASE_SOURCE_URL = {
    "core_cpi": "https://www.bls.gov/news.release/cpi.toc.htm",
    "core_pce": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
    "weekly_claims": "https://www.dol.gov/ui/data.pdf",
    "adp": "https://adpemploymentreport.com/",
    "nfp": "https://www.bls.gov/news.release/empsit.toc.htm",
    "ur": "https://www.bls.gov/news.release/empsit.toc.htm",
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


def month_label(value: str | None) -> str:
    if not value:
        return "n/a"
    ts = pd.Timestamp(value)
    return ts.strftime("%B %Y")


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
    series = fetch_fred_series("CPILFESL")
    if series is not None and len(series) >= 13:
        mom = (series.iloc[-1] / series.iloc[-2] - 1.0) * 100.0
        yoy = (series.iloc[-1] / series.iloc[-13] - 1.0) * 100.0
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_pct(mom)} m/m, {fmt_pct(yoy)} y/y"
        write_actual_cache("core_cpi", value)
        return value
    return read_actual_cache().get("core_cpi") or load_core_cpi_last_release_local()


def load_core_pce_last_release() -> str | None:
    series = fetch_fred_series("PCEPILFE")
    if series is not None and len(series) >= 13:
        mom = (series.iloc[-1] / series.iloc[-2] - 1.0) * 100.0
        yoy = (series.iloc[-1] / series.iloc[-13] - 1.0) * 100.0
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_pct(mom)} m/m, {fmt_pct(yoy)} y/y"
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
    series = fetch_fred_series("PAYEMS")
    if series is not None and len(series) >= 2:
        change_k = series.iloc[-1] - series.iloc[-2]
        value = f"{series.index[-1].strftime('%B %Y')}: {fmt_k(change_k)}"
        write_actual_cache("nfp", value)
        return value
    return read_actual_cache().get("nfp")


def load_ur_last_release() -> str | None:
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


def build_core_cpi_event(now_et: datetime) -> ReleaseEvent:
    forecast = read_json(CORE_CPI_FORECAST) or {}
    surprise = read_json(CORE_CPI_SURPRISE) or {}
    kalshi = read_json(CORE_CPI_KALSHI) or {}
    reporting_month, release_dt, source = next_seeded_release(now_et, "core_cpi")

    house = None
    if forecast:
        house = f"{fmt_pct(float(forecast.get('final_mom')))} m/m | {fmt_pct(float(forecast.get('core_implied_yoy')))} y/y"

    mom_line, kalshi_link = kalshi_for("core_cpi")
    yoy_line, _ = kalshi_for("core_cpi_yoy")
    parts = [p for p in (mom_line, yoy_line) if p]
    kalshi_line = " | ".join(parts) if parts else "no live Kalshi market found"
    risk_label = surprise.get("live", {}).get("risk_label") or surprise.get("risk_label")
    if not risk_label and surprise.get("big_surprise_prob") is not None:
        risk_label = f"{surprise['big_surprise_prob'] * 100:.0f}% big-surprise risk"

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
        status=event_status(house, kalshi_line),
        notes="Model output from core CPI workflow and surprise model.",
        model_source=str(CORE_CPI_FORECAST.relative_to(BASE_DIR)) if CORE_CPI_FORECAST.exists() else None,
        kalshi_url=kalshi_link,
    )


def build_core_pce_event(now_et: datetime) -> ReleaseEvent:
    bridge = read_json(MACRO_OUTPUT / "core_pce_bridge_latest.json") or read_json(ROOT_CORE_PCE_BRIDGE) or {}
    taylor = read_json(FCI_TAYLOR) or {}
    cpi = read_json(CORE_CPI_FORECAST) or {}
    reporting_month, release_dt, source = next_seeded_release(now_et, "core_pce")

    bridge_mom = ((bridge.get("implied_core_pce") or {}).get("mom_pct"))
    bridge_yoy = ((bridge.get("expected_core_pce") or {}).get("yoy_pct"))
    if bridge_yoy is None:
        bridge_yoy = (((taylor.get("inputs") or {}).get("forecast_core_pce_yoy")))

    if bridge_mom is None and cpi:
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
    if not (MACRO_OUTPUT / "core_pce_bridge_latest.json").exists():
        note += " Local repo does not yet write macro_forecasting/output/core_pce_bridge_latest.json, so this refresh falls back to existing bridge artifacts."

    kalshi_line, kalshi_link = kalshi_for("core_pce")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
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
        status=event_status(house),
        notes=note,
        model_source="macro_forecasting/cpi_to_pce_bridge.py",
        kalshi_url=kalshi_link,
    )


def build_claims_event(now_et: datetime) -> ReleaseEvent:
    forecast = read_json(WEEKLY_CLAIMS_FORECAST) or {}
    surprise = read_json(WEEKLY_CLAIMS_SURPRISE) or {}
    reporting_period, release_dt = next_weekly_claims_release(now_et)
    house = fmt_claims(float(forecast["forecast"])) if forecast.get("forecast") is not None else None
    kalshi_line, kalshi_link = kalshi_for("weekly_claims")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
    risk = ((forecast.get("surprise") or {}).get("risk_label"))
    if not risk:
        live_prob = (((surprise.get("forecast") or {}).get("surprise_prob_10k")))
        if live_prob is not None:
            risk = f"{live_prob * 100:.0f}% surprise risk"
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
        status=event_status(house, kalshi_line),
        notes="Weekly model output with surprise-risk overlay.",
        model_source=str(WEEKLY_CLAIMS_FORECAST.relative_to(BASE_DIR)) if WEEKLY_CLAIMS_FORECAST.exists() else None,
        kalshi_url=kalshi_link,
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
        notes = "ADP forecast unavailable — run macro_site/build_adp_forecast.py to refresh."
    kalshi_line, kalshi_link = kalshi_for("adp")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
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
        status=event_status(house),
        notes=notes,
        model_source="macro_forecasting/adp_forecast_kaggle_style.py",
        kalshi_url=kalshi_link,
    )


def build_nfp_event(now_et: datetime) -> ReleaseEvent:
    surprise = read_json(NFP_SURPRISE) or {}
    reporting_period, release_dt, source = next_seeded_release(now_et, "nfp")
    live = surprise.get("live") or {}
    house = fmt_k(float(surprise["house_forecast_k"])) if surprise.get("house_forecast_k") is not None else None
    risk = live.get("risk_label")
    if not risk and live.get("big_surprise_prob") is not None:
        risk = f"{live['big_surprise_prob'] * 100:.0f}% big-surprise risk"
    kalshi_line, kalshi_link = kalshi_for("nfp")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
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
        last_release=load_nfp_last_release(),
        risk=humanize_risk(risk),
        status=event_status(house),
        notes="NFP surprise model already uses weekly claims features, so the forecast can refresh as claims move.",
        model_source=str(NFP_SURPRISE.relative_to(BASE_DIR)) if NFP_SURPRISE.exists() else None,
        kalshi_url=kalshi_link,
    )


def build_ur_event(now_et: datetime) -> ReleaseEvent:
    surprise = read_json(UR_SURPRISE) or {}
    live = surprise.get("live") or {}
    reporting_period, release_dt, source = next_seeded_release(now_et, "ur")
    house = fmt_pct(float(live["rounded_unrate"])) if live.get("rounded_unrate") is not None else None
    risk = live.get("risk_label")
    if not risk and live.get("big_surprise_prob") is not None:
        risk = f"{live['big_surprise_prob'] * 100:.0f}% big-surprise risk"
    kalshi_line, kalshi_link = kalshi_for("ur")
    if not kalshi_line:
        kalshi_line = "no live Kalshi market found"
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
        last_release=load_ur_last_release(),
        risk=humanize_risk(risk),
        status=event_status(house),
        notes="Rounded to the market print convention; live model also stores unrounded UR.",
        model_source=str(UR_SURPRISE.relative_to(BASE_DIR)) if UR_SURPRISE.exists() else None,
        kalshi_url=kalshi_link,
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
        "summary": {
            "event_count": len(serialized),
            "live_count": sum(1 for event in serialized if event["status"] == "live"),
            "partial_count": sum(1 for event in serialized if event["status"] == "partial"),
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
            f"- **{ev['label']}** ({ev['group']}) — releases {ev['release_day']}, {ev['release_date']} at {ev['release_time']}.",
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
    print(f"Events: {payload['summary']['event_count']} total, {payload['summary']['live_count']} live, {payload['summary']['partial_count']} partial")


if __name__ == "__main__":
    main()
