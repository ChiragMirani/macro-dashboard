# MacroForecastbyCM

**Live site:** [chiragmirani.github.io/macro-dashboard](https://chiragmirani.github.io/macro-dashboard/)
**Track record:** [chiragmirani.github.io/macro-dashboard/track-record.html](https://chiragmirani.github.io/macro-dashboard/track-record.html)
**Maintained by:** Chirag Mirani &middot; chiragmirani@gmail.com

A live, auto-updating release schedule for the most market-moving US macroeconomic prints, paired with house model forecasts and live Kalshi market consensus for direct comparison. Built and maintained solo.

---

## What it is

A daily-refreshed dashboard that answers, for every upcoming US macro release:

- **When** does it release (day, date, time ET)?
- **What does my house model expect?** (built from public BLS / FRED / Kalshi data)
- **What does the Kalshi prediction market expect?** (live, with link to the underlying market)
- **What was the last actual print?** (linked to the official source — BLS, BEA, DOL, ADP)
- **Surprise risk:** does my model think this print will deviate materially from consensus?

After each release lands, the [track record page](https://chiragmirani.github.io/macro-dashboard/track-record.html) scores the house forecast and Kalshi consensus against the actual, settled from FRED. No historical backfill — snapshots start the day they're captured, so the record is honest.

## Tracked releases

| Release | Source | Frequency | Kalshi market |
|---|---|---|---|
| Core CPI (m/m + y/y) | BLS | Monthly | KXECONSTATCPICORE / KXCPICOREYOY |
| Core PCE (m/m) | BEA | Monthly | KXPCECORE |
| Nonfarm Payrolls | BLS | Monthly (1st Fri) | KXPAYROLLS |
| Unemployment Rate | BLS | Monthly (1st Fri) | KXECONSTATU3 |
| ADP National Employment | ADP | Monthly (1st Wed) | KXADP |
| Initial Jobless Claims | DOL | Weekly (Thu) | KXJOBLESSCLAIMS |

## How the forecasts are produced

House forecasts come from a stack of model pipelines built on:

- Walk-forward (expanding-window) cross-validation — no look-ahead leakage
- Component-level decomposition for CPI (each subcomponent forecast separately, then aggregated)
- Ensemble of regularized linear + gradient-boosted trees with naive / moving-average baselines as protection
- Surprise-risk classifiers that estimate the probability of a wide miss vs consensus
- CPI/PPI bridge for Core PCE
- Calendar-factor and seasonal-residual features for weekly claims

The model code itself lives in a private repo. **Reach out via email if you want details, methodology, or backtest data.**

## How the data flow works

1. **Local Windows scheduled task** (daily, 6 PM ET) runs a dependency-aware orchestrator that reruns only the models whose FRED inputs have moved (e.g. NFP rebuilds when new claims data arrives), then publishes the JSON outputs to this public repo.
2. **GitHub Actions** (twice a day on weekdays) pulls live Kalshi consensus, refreshes FRED last-release values, re-renders the static site, and commits `docs/`.
3. The static site at GitHub Pages serves the rendered dashboard and a machine-readable feed at [`dashboard_data.json`](https://chiragmirani.github.io/macro-dashboard/dashboard_data.json).

## Machine-readable feeds

- [`dashboard_data.json`](https://chiragmirani.github.io/macro-dashboard/dashboard_data.json) &middot; current release schedule + forecasts
- [`track_record.json`](https://chiragmirani.github.io/macro-dashboard/track_record.json) &middot; historical scoreboard, settled vs actual
- [`llms.txt`](https://chiragmirani.github.io/macro-dashboard/llms.txt) &middot; AI-assistant–friendly summary

## Contact

Questions about the methodology, requests for the model code, partnership ideas, or just want to compare forecasts? Email **chiragmirani@gmail.com**.

## License

The dashboard interface and outputs in this repo are MIT-licensed. Model code is not in this repo and is not currently shared publicly — please email if interested.
