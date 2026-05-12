"""Track-record persistence for the macro dashboard, backed by SQLite.

DB lives at `macro_site/track_record.db` (committed to the public repo so the
history survives across runs and across machines / GitHub Actions). The
public page reads `docs/track_record.json` which is exported from the DB on
every render.

Snapshots are append-only and never overwritten, so the record is honest:
once a (house, Kalshi) pair is captured it is the value the actual is scored
against.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "macro_site" / "track_record.db"
EXPORT_PATH = REPO_ROOT / "docs" / "track_record.json"
REQUEST_HEADERS = {"User-Agent": "ChiragMiraniMacroDashboard/1.0"}
BEA_NIPA_MONTHLY_TXT = "https://apps.bea.gov/national/Release/TXT/NipaDataM.txt"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/{series_id}?startyear=2020&endyear=2026"


ACTUAL_SOURCES: dict[str, dict[str, Any]] = {
    "weekly_claims":  {"series": "ICSA",         "kind": "weekly_level",   "unit": "claims"},
    "core_cpi":       {"series": "CPILFESL",     "bls_series": "CUSR0000SA0L1E", "kind": "monthly_mom_pct","unit": "% m/m"},
    "core_pce":       {"series": "PCEPILFE",     "kind": "monthly_mom_pct","unit": "% m/m"},
    "adp":            {"series": "ADPMNUSNERSA", "kind": "monthly_diff_k", "unit": "k jobs", "diff_scale": 1 / 1000.0},
    "nfp":            {"series": "PAYEMS",       "bls_series": "CES0000000001", "kind": "monthly_diff_k", "unit": "k jobs", "diff_scale": 1.0},
    "ur":             {"series": "UNRATE",       "bls_series": "LNS14000000", "kind": "monthly_level",  "unit": "% UR"},
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    release_key TEXT NOT NULL,
    release_label TEXT,
    release_group TEXT,
    target_period TEXT,
    release_iso TEXT NOT NULL,
    snapshot_at_utc TEXT NOT NULL,
    house_raw TEXT,
    house_value REAL,
    kalshi_raw TEXT,
    kalshi_value REAL,
    kalshi_url TEXT,
    release_source_url TEXT,
    fred_series TEXT,
    unit TEXT,
    actual_value REAL,
    house_error_abs REAL,
    kalshi_error_abs REAL,
    winner TEXT,
    actual_consensus_side TEXT,
    house_consensus_side TEXT,
    house_direction_correct INTEGER,
    settled_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_release  ON snapshots(release_key, release_iso);
CREATE INDEX IF NOT EXISTS idx_settled  ON snapshots(settled_at_utc);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
    additions = {
        "actual_consensus_side": "TEXT",
        "house_consensus_side": "TEXT",
        "house_direction_correct": "INTEGER",
    }
    for col, col_type in additions.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {col_type}")


def _first_number(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_forecast(raw: str | None, key: str) -> float | None:
    """First numeric in the label — e.g. '0.305% m/m | 2.88% y/y' -> 0.305 (the m/m)."""
    return _first_number(raw)


def fetch_fred_csv(series_id: str) -> pd.DataFrame | None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception:
        return None
    date_col = "DATE" if "DATE" in df.columns else "observation_date" if "observation_date" in df.columns else None
    if date_col is None or series_id not in df.columns:
        return None
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    df = df.dropna(subset=[date_col, series_id]).sort_values(date_col).reset_index(drop=True)
    df.rename(columns={date_col: "date"}, inplace=True)
    return df


def fetch_bls_series(series_id: str) -> pd.DataFrame | None:
    try:
        resp = requests.get(BLS_API.format(series_id=series_id), headers=REQUEST_HEADERS, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None
    try:
        rows = payload["Results"]["series"][0]["data"]
    except Exception:
        return None
    parsed = []
    for row in rows:
        period = str(row.get("period", ""))
        if not re.match(r"M\d\d", period):
            continue
        parsed.append(
            {
                "date": pd.to_datetime(f"{row['year']}-{period[1:]}-01", errors="coerce"),
                series_id: pd.to_numeric(row.get("value"), errors="coerce"),
            }
        )
    if not parsed:
        return None
    df = pd.DataFrame(parsed).dropna(subset=["date", series_id]).sort_values("date").reset_index(drop=True)
    return df


def fetch_bea_monthly_series(series_code: str) -> pd.DataFrame | None:
    try:
        resp = requests.get(BEA_NIPA_MONTHLY_TXT, headers=REQUEST_HEADERS, timeout=60)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), dtype=str)
    except Exception:
        return None
    required = {"%SeriesCode", "Period", "Value"}
    if not required.issubset(df.columns):
        return None
    df = df[df["%SeriesCode"] == series_code].copy()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["Period"].str.replace("M", "-", regex=False) + "-01", errors="coerce")
    df[series_code] = pd.to_numeric(df["Value"].str.replace(",", "", regex=False), errors="coerce")
    df = df.dropna(subset=["date", series_code]).sort_values("date").reset_index(drop=True)
    return df[["date", series_code]]


def actual_for(release_key: str, target_period: str | None) -> float | None:
    cfg = ACTUAL_SOURCES.get(release_key)
    if not cfg:
        return None
    if release_key == "core_pce":
        df = fetch_bea_monthly_series("DPCCRG")
        if df is not None and not df.empty:
            cfg = {**cfg, "series": "DPCCRG"}
        else:
            df = fetch_fred_csv(cfg["series"])
    elif cfg.get("bls_series"):
        df = fetch_bls_series(cfg["bls_series"])
        if df is not None and not df.empty:
            cfg = {**cfg, "series": cfg["bls_series"]}
        else:
            df = fetch_fred_csv(cfg["series"])
    else:
        df = fetch_fred_csv(cfg["series"])
    if df is None or df.empty:
        return None

    if cfg["kind"] == "weekly_level":
        m = re.search(r"([A-Za-z]+\s+\d{1,2},\s+\d{4})", target_period or "")
        if not m:
            return None
        try:
            target_date = pd.to_datetime(m.group(1))
        except Exception:
            return None
        within = df[(df["date"] >= target_date - pd.Timedelta(days=3)) & (df["date"] <= target_date + pd.Timedelta(days=3))]
        if within.empty:
            return None
        return float(within.iloc[-1][cfg["series"]])

    m = re.match(r"([A-Za-z]+)\s+(\d{4})", target_period or "")
    if not m:
        return None
    month_dt = pd.to_datetime(f"{m.group(1)} 1, {m.group(2)}")
    row = df[df["date"] == month_dt]
    if row.empty:
        return None
    val = float(row.iloc[0][cfg["series"]])

    if cfg["kind"] == "monthly_level":
        return val

    if cfg["kind"] == "monthly_diff_k":
        prev = df[df["date"] < month_dt].tail(1)
        if prev.empty:
            return None
        prev_val = float(prev.iloc[0][cfg["series"]])
        scale = float(cfg.get("diff_scale", 1.0 if cfg["series"] == "PAYEMS" else 1 / 1000.0))
        return (val - prev_val) * scale

    if cfg["kind"] == "monthly_mom_pct":
        prev = df[df["date"] < month_dt].tail(1)
        if prev.empty:
            return None
        prev_val = float(prev.iloc[0][cfg["series"]])
        return (val / prev_val - 1.0) * 100.0

    return None


def _side(value: float | None, consensus: float | None) -> str | None:
    if value is None or consensus is None:
        return None
    diff = value - consensus
    if abs(diff) < 1e-9:
        return "in_line"
    return "above" if diff > 0 else "below"


def _direction_score(actual: float | None, house: float | None, consensus: float | None) -> tuple[str | None, str | None, int | None]:
    actual_side = _side(actual, consensus)
    house_side = _side(house, consensus)
    if actual_side in (None, "in_line") or house_side in (None, "in_line"):
        return actual_side, house_side, None
    return actual_side, house_side, int(actual_side == house_side)


def snapshot(payload: dict[str, Any]) -> int:
    """Insert any never-seen snapshots for events releasing in the next 14 days."""
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    with _connect() as conn:
        for ev in payload.get("events", []):
            if ev.get("hours_until_release") is None or ev["hours_until_release"] < 0:
                continue
            if ev["hours_until_release"] > 14 * 24:
                continue
            sid = f"{ev['key']}_{ev['release_iso'][:10]}"
            existing = conn.execute("SELECT 1 FROM snapshots WHERE id = ?", (sid,)).fetchone()
            if existing:
                continue
            cfg = ACTUAL_SOURCES.get(ev["key"], {})
            conn.execute(
                """
                INSERT INTO snapshots (
                    id, release_key, release_label, release_group, target_period,
                    release_iso, snapshot_at_utc, house_raw, house_value,
                    kalshi_raw, kalshi_value, kalshi_url, release_source_url,
                    fred_series, unit
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid, ev["key"], ev["label"], ev["group"], ev["reporting_period"],
                    ev["release_iso"], now, ev.get("house_forecast"),
                    parse_forecast(ev.get("house_forecast"), ev["key"]),
                    ev.get("kalshi_consensus"),
                    parse_forecast(ev.get("kalshi_consensus"), ev["key"]),
                    ev.get("kalshi_url"), ev.get("release_source_url"),
                    cfg.get("series"), cfg.get("unit"),
                ),
            )
            added += 1
        conn.commit()
    return added


def settle() -> int:
    """Score any snapshots whose release time has passed and FRED has the actual."""
    settled = 0
    now_utc = datetime.now(timezone.utc)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE actual_value IS NULL"
        ).fetchall()
        for row in rows:
            try:
                release_dt = datetime.fromisoformat(row["release_iso"])
            except Exception:
                continue
            if release_dt.tzinfo is None:
                release_dt = release_dt.replace(tzinfo=timezone.utc)
            if release_dt > now_utc:
                continue
            actual = actual_for(row["release_key"], row["target_period"])
            if actual is None:
                continue
            house_err = abs(row["house_value"] - actual) if row["house_value"] is not None else None
            kalshi_err = abs(row["kalshi_value"] - actual) if row["kalshi_value"] is not None else None
            winner = None
            if house_err is not None and kalshi_err is not None:
                winner = "tie" if abs(house_err - kalshi_err) < 1e-9 else ("house" if house_err < kalshi_err else "kalshi")
            actual_side, house_side, direction_correct = _direction_score(actual, row["house_value"], row["kalshi_value"])
            conn.execute(
                """
                UPDATE snapshots SET actual_value=?, house_error_abs=?, kalshi_error_abs=?,
                                     winner=?, actual_consensus_side=?, house_consensus_side=?,
                                     house_direction_correct=?, settled_at_utc=?
                WHERE id = ?
                """,
                (actual, house_err, kalshi_err, winner, actual_side, house_side, direction_correct, now_utc.isoformat(), row["id"]),
            )
            settled += 1
        _backfill_direction_scores(conn)
        conn.commit()
    return settled


def _backfill_direction_scores(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT * FROM snapshots
        WHERE actual_value IS NOT NULL
          AND kalshi_value IS NOT NULL
          AND house_value IS NOT NULL
          AND (actual_consensus_side IS NULL OR house_consensus_side IS NULL)
        """
    ).fetchall()
    for row in rows:
        actual_side, house_side, direction_correct = _direction_score(
            row["actual_value"], row["house_value"], row["kalshi_value"]
        )
        conn.execute(
            """
            UPDATE snapshots
               SET actual_consensus_side=?, house_consensus_side=?, house_direction_correct=?
             WHERE id=?
            """,
            (actual_side, house_side, direction_correct, row["id"]),
        )


def _summary(rows: list[sqlite3.Row]) -> dict[str, Any]:
    settled_rows = [r for r in rows if r["actual_value"] is not None]
    pending_rows = [r for r in rows if r["actual_value"] is None]

    def avg(vals: list[float | None]) -> float | None:
        clean = [v for v in vals if v is not None]
        return sum(clean) / len(clean) if clean else None

    direction_calls = sum(1 for r in settled_rows if r["house_direction_correct"] in (0, 1))
    direction_hits = sum(1 for r in settled_rows if r["house_direction_correct"] == 1)
    return {
        "total_snapshots": len(rows),
        "settled_count": len(settled_rows),
        "pending_count": len(pending_rows),
        "house_wins":  sum(1 for r in settled_rows if r["winner"] == "house"),
        "kalshi_wins": sum(1 for r in settled_rows if r["winner"] == "kalshi"),
        "ties":        sum(1 for r in settled_rows if r["winner"] == "tie"),
        "house_direction_hits": direction_hits,
        "house_direction_misses": sum(1 for r in settled_rows if r["house_direction_correct"] == 0),
        "house_direction_call_count": direction_calls,
        "house_direction_hit_rate": (direction_hits / direction_calls) if direction_calls else None,
        "house_mean_abs_error":  avg([r["house_error_abs"]  for r in settled_rows]),
        "kalshi_mean_abs_error": avg([r["kalshi_error_abs"] for r in settled_rows]),
    }


def _format_side(side: str | None) -> str | None:
    if side == "above":
        return "above consensus"
    if side == "below":
        return "below consensus"
    if side == "in_line":
        return "in line"
    return None


def _format_value(v: float | None, unit: str | None) -> str | None:
    if v is None:
        return None
    if unit == "% m/m":
        return f"{v:.3f}% m/m"
    if unit == "% UR":
        return f"{v:.2f}%"
    if unit == "k jobs":
        sign = "-" if v < 0 else ""
        return f"{sign}{abs(v):.0f}k"
    if unit == "claims":
        return f"{v:,.0f}"
    return f"{v:.4g}"


def _format_error(v: float | None, unit: str | None) -> str | None:
    if v is None:
        return None
    if unit in ("% m/m", "% UR"):
        return f"{v:.3f} pp"
    if unit == "k jobs":
        return f"{v:.0f}k"
    if unit == "claims":
        return f"{v:,.0f}"
    return f"{v:.4g}"


def render_for_template() -> dict[str, Any]:
    """Pull everything sorted newest-first for the Jinja template."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM snapshots ORDER BY release_iso DESC").fetchall()
    rows_list = [dict(r) for r in rows]
    snaps = []
    for r in rows_list:
        snaps.append({
            **r,
            "release_date_pretty": datetime.fromisoformat(r["release_iso"]).strftime("%b %d, %Y"),
            "house_display":  r.get("house_raw") or "n/a",
            "kalshi_display": r.get("kalshi_raw") or "n/a",
            "actual_display": _format_value(r.get("actual_value"), r.get("unit")) if r.get("actual_value") is not None else None,
            "house_error_display":  _format_error(r.get("house_error_abs"),  r.get("unit")),
            "kalshi_error_display": _format_error(r.get("kalshi_error_abs"), r.get("unit")),
            "actual_consensus_side_display": _format_side(r.get("actual_consensus_side")),
            "house_consensus_side_display": _format_side(r.get("house_consensus_side")),
        })
    summary = _summary(rows)
    return {"snapshots": snaps, "summary": summary}


def export_json() -> None:
    """Write the public-facing track_record.json for the rendered page."""
    payload = render_for_template()
    payload["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
