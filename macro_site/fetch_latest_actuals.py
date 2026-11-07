"""Fetch the latest published weekly jobless claims and ADP employment actuals.

Runs on Chirag's computer in the nightly publish step, where FRED downloads work
(they time out from GitHub Actions). Writes
macro_forecasting/output/latest_actuals_local.json, which the publish step already
syncs to the public repo, and refresh_dashboard.py picks the newest value it can find.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
OUT_PATH = BASE_DIR / "macro_forecasting" / "output" / "latest_actuals_local.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MacroForecastbyCM"}
DOL_CLAIMS_URL = "https://oui.doleta.gov/unemploy/wkclaims/report.asp"


def fred(series_id: str) -> pd.Series | None:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    for timeout in (30, 90):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            frame = pd.read_csv(io.StringIO(response.text))
            date_col = "observation_date" if "observation_date" in frame.columns else "DATE"
            frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
            values = pd.to_numeric(frame[series_id], errors="coerce")
            series = pd.Series(values.values, index=frame[date_col]).dropna().sort_index()
            return series if len(series) else None
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: FRED {series_id} attempt failed: {exc!r}", file=sys.stderr)
    return None


def dol_claims() -> pd.Series | None:
    """Seasonally adjusted initial claims straight from the Department of Labor (no key)."""
    import xml.etree.ElementTree as ET

    year = datetime.now().year
    try:
        response = requests.post(
            DOL_CLAIMS_URL,
            data={"level": "US", "strtdate": str(year - 1), "enddate": str(year), "filetype": "xml", "final": "Submit"},
            headers=HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Department of Labor claims fetch failed: {exc!r}", file=sys.stderr)
        return None
    rows = {}
    for week in root.findall("week"):
        sa = (week.find("InitialClaims").findtext("SA") or "").replace(",", "").strip()
        if sa.isdigit():
            rows[pd.to_datetime(week.findtext("weekEnded"), format="%m/%d/%Y")] = float(sa)
    return pd.Series(rows).sort_index() if rows else None


def main() -> None:
    out: dict = {"fetched_at_utc": datetime.now(timezone.utc).isoformat()}

    claims = fred("ICSA")
    dol = dol_claims()
    if dol is not None and (claims is None or dol.index[-1] > claims.index[-1]):
        claims = dol
    if claims is not None:
        out["weekly_claims"] = {
            "period_end": claims.index[-1].strftime("%Y-%m-%d"),
            "value": float(claims.iloc[-1]),
            "display": f"Week ending {claims.index[-1].strftime('%b %d, %Y')}: {int(round(claims.iloc[-1])):,}",
        }

    adp = fred("ADPMNUSNERSA")
    if adp is not None and len(adp) >= 2:
        change_k = (adp.iloc[-1] - adp.iloc[-2]) / 1000.0
        out["adp"] = {
            "period_end": adp.index[-1].strftime("%Y-%m-%d"),
            "value_k": round(float(change_k), 1),
            "display": f"{adp.index[-1].strftime('%B %Y')}: {change_k:,.0f}k",
        }

    # Never replace a value with an older period (FRED's ADP series can lag the press release).
    try:
        previous = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        previous = {}
    for key in ("weekly_claims", "adp"):
        old, new = previous.get(key), out.get(key)
        if old and (not new or old.get("period_end", "") > new.get("period_end", "")):
            out[key] = old

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
