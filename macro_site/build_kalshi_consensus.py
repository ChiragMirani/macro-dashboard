"""Fetch Kalshi consensus for tracked macro releases and persist to JSON."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
OUTPUT = Path(__file__).resolve().parents[1] / "macro_forecasting" / "output" / "kalshi_consensus_latest.json"

MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
ET = ZoneInfo("America/New_York")
CORE_PCE_RELEASE_DATES = [
    date(2026, 3, 27),
    date(2026, 4, 30),
    date(2026, 5, 28),
    date(2026, 6, 26),
]


def yy(d: date) -> str:
    return f"{d.year % 100:02d}"


def fetch_event(event_ticker: str) -> dict | None:
    try:
        r = requests.get(f"{KALSHI_API}/events/{event_ticker}", timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def market_mid(m: dict) -> float | None:
    yb = m.get("yes_bid_dollars") or m.get("yes_bid")
    ya = m.get("yes_ask_dollars") or m.get("yes_ask")
    if yb is None or ya is None:
        return None
    yb = float(yb)
    ya = float(ya)
    if yb > 1 or ya > 1:
        yb /= 100.0
        ya /= 100.0
    return (yb + ya) / 2.0


def implied_mean_from_thresholds(markets: list[dict], scale: float = 1.0) -> float | None:
    """Markets are >= floor_strike binaries; derive expected value from threshold CDF."""
    rows = []
    for m in markets:
        strike = m.get("floor_strike")
        prob = market_mid(m)
        if strike is None or prob is None:
            continue
        rows.append((float(strike) * scale, prob))
    rows.sort(key=lambda r: r[0])
    if len(rows) < 2:
        return None
    bins = []
    for i in range(len(rows) - 1):
        k_lo, p_lo = rows[i]
        k_hi, p_hi = rows[i + 1]
        bins.append((k_lo, k_hi, max(0.0, p_lo - p_hi)))
    step = rows[1][0] - rows[0][0]
    left_tail = max(0.0, 1.0 - rows[0][1])
    right_tail = max(0.0, rows[-1][1])
    mean = (rows[0][0] - step / 2.0) * left_tail + (rows[-1][0] + step / 2.0) * right_tail
    for lo, hi, p in bins:
        mean += ((lo + hi) / 2.0) * p
    return mean


def _parse_exact_strike(ticker: str) -> float | None:
    """Pull the exact-bucket strike from the ticker suffix, e.g. '...-T-0.2' -> -0.2."""
    if not ticker:
        return None
    suffix = ticker.rsplit("-T", 1)[-1] if "-T" in ticker else None
    if suffix is None:
        return None
    try:
        return float(suffix)
    except ValueError:
        return None


def implied_mean_from_buckets(markets: list[dict]) -> float | None:
    """Exact-bucket binaries (CPI-style). Strike is on the market or in the ticker suffix."""
    rows = []
    for m in markets:
        floor = m.get("floor_strike")
        cap = m.get("cap_strike")
        prob = market_mid(m)
        if prob is None:
            continue
        if floor is None and cap is None:
            mid = _parse_exact_strike(m.get("ticker", ""))
            if mid is None:
                continue
        elif floor is None:
            mid = float(cap)
        elif cap is None:
            mid = float(floor)
        else:
            mid = (float(floor) + float(cap)) / 2.0
        rows.append((float(mid), prob))
    if not rows:
        return None
    total_p = sum(p for _, p in rows)
    if total_p <= 0:
        return None
    return sum(mid * p for mid, p in rows) / total_p


def kalshi_event_url(event_ticker: str) -> str:
    return f"https://kalshi.com/markets/{event_ticker.lower()}"


def build_for_event(key: str, event_ticker: str, kind: str, value_scale: float, formatter) -> dict:
    payload = fetch_event(event_ticker) or {}
    markets = payload.get("markets") or []
    if kind == "threshold":
        implied = implied_mean_from_thresholds(markets, scale=value_scale)
    else:
        implied = implied_mean_from_buckets(markets)
        if implied is not None:
            implied *= value_scale
    return {
        "key": key,
        "event_ticker": event_ticker,
        "kind": kind,
        "market_count": len(markets),
        "implied_value": implied,
        "consensus_label": formatter(implied) if implied is not None else None,
        "kalshi_url": kalshi_event_url(event_ticker),
        "title": (payload.get("event") or {}).get("title"),
    }


def fmt_claims(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:,.0f}"


def fmt_k(v: float | None) -> str | None:
    if v is None:
        return None
    sign = "-" if v < 0 else ""
    return f"{sign}{abs(v):.0f}k"


def fmt_pct_3dp(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:.3f}% m/m"


def fmt_pct_2dp_yoy(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:.2f}% y/y"


def fmt_pct_2dp(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:.2f}%"


def upcoming_month_ticker(prefix: str, today: date) -> str:
    """Pick the next month for events listed monthly (e.g. KXADP-26APR)."""
    target = today.replace(day=1)
    return f"{prefix}-{yy(target)}{MONTH_ABBR[target.month - 1]}"


def upcoming_claims_ticker(now_et: datetime) -> str:
    """Initial Jobless Claims releases Thursdays. Find next Thursday."""
    today = now_et.date()
    days_ahead = (3 - today.weekday()) % 7
    if days_ahead == 0 and now_et.time() >= time(8, 30):
        days_ahead = 7
    release = today + timedelta(days=max(days_ahead, 1) if today.weekday() == 3 else days_ahead)
    return f"KXJOBLESSCLAIMS-{yy(release)}{MONTH_ABBR[release.month - 1]}{release.day:02d}"


def upcoming_core_pce_ticker(now_et: datetime) -> str:
    """Kalshi Core PCE tickers use the release month, not the data month."""
    release_time = time(8, 30)
    for release_date in CORE_PCE_RELEASE_DATES:
        release_dt = datetime.combine(release_date, release_time, tzinfo=ET)
        if now_et < release_dt:
            return f"KXPCECORE-{yy(release_date)}{MONTH_ABBR[release_date.month - 1]}"
    fallback_month = now_et.month + 1
    fallback_year = now_et.year + (fallback_month - 1) // 12
    fallback_month = ((fallback_month - 1) % 12) + 1
    return f"KXPCECORE-{fallback_year % 100:02d}{MONTH_ABBR[fallback_month - 1]}"


def main() -> None:
    now_et = datetime.now(tz=ET)
    today = now_et.date()
    events = [
        build_for_event(
            "weekly_claims",
            upcoming_claims_ticker(now_et),
            "threshold",
            value_scale=1.0,
            formatter=fmt_claims,
        ),
        build_for_event(
            "adp",
            upcoming_month_ticker("KXADP", today),
            "threshold",
            value_scale=1 / 1000.0,
            formatter=fmt_k,
        ),
        build_for_event(
            "core_cpi",
            upcoming_month_ticker("KXECONSTATCPICORE", today),
            "bucket",
            value_scale=1.0,
            formatter=fmt_pct_3dp,
        ),
        build_for_event(
            "core_cpi_yoy",
            upcoming_month_ticker("KXCPICOREYOY", today),
            "threshold",
            value_scale=1.0,
            formatter=fmt_pct_2dp_yoy,
        ),
        build_for_event(
            "nfp",
            upcoming_month_ticker("KXPAYROLLS", today),
            "threshold",
            value_scale=1 / 1000.0,
            formatter=fmt_k,
        ),
        build_for_event(
            "ur",
            upcoming_month_ticker("KXECONSTATU3", today),
            "bucket",
            value_scale=1.0,
            formatter=fmt_pct_2dp,
        ),
        build_for_event(
            "core_pce",
            upcoming_core_pce_ticker(now_et),
            "threshold",
            value_scale=1.0,
            formatter=fmt_pct_3dp,
        ),
    ]

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "events": {ev["key"]: ev for ev in events},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    for ev in events:
        marker = ev["consensus_label"] or "(no live consensus)"
        print(f"  {ev['key']:<14} {ev['event_ticker']:<28} markets={ev['market_count']:<3} {marker}")


if __name__ == "__main__":
    main()
