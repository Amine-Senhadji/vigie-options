<div align="center">

# 🔭 vigie-options

**Three Claude Code agents that flag unusual options activity on your watchlist every day, and never tell you what to buy.**

[Version française](README.md) · [Architecture (FR)](docs/architecture.md) · [Methodology (FR)](docs/methodologie.md)

</div>

---

*Vigie* is French for a ship's lookout. The full documentation is in French; this page is a summary.

## What it does

| Agent | Its only job | What it may never do |
|---|---|---|
| **collecteur** (collector) | Fetch prices, the full options chain, open interest and upcoming events via yfinance | Analyse, or estimate missing data |
| **analyste** (analyst) | Describe options activity against the ticker's own history | Recommend trades, call activity bullish or bearish |
| **vigie** (lookout) | List at most 5 tickers worth a look, each with its most likely boring explanation | Recommend entries, exits or position sizes |

Run them all with the `/bourse` command in Claude Code.

## Design choices

- **Numbers are computed in tested Python** (`scripts/compare.py`), never by the model. Agents describe a file of computed results.
- **Open interest is compared contract by contract, on the contracts where volume concentrated**, to tell newly opened positions from closed ones. Stale or one-session-late open interest is detected.
- **No collection during the US session**: partial volumes would pollute the history (`--forcer` overrides it on US holidays).
- **"Unusual" is measured against each ticker's own history** (percentile rank, then z-score), never in absolute terms.
- **No gaps are ever filled**: missing data stays `INDISPONIBLE` (unavailable).
- **A tracking journal kept by Python** (`scripts/suivi.py`, never by an agent) records every flag, fills in the price 14 days later and compares it with the other, unflagged tickers. `python3 scripts/suivi.py bilan` summarises it, without drawing conclusions under 30 flags.

yfinance provides no options history, so the project builds its own from daily snapshots: flags become possible after 10 sessions and reliable after 20.

## Quick start

```bash
git clone https://github.com/Amine-Senhadji/vigie-options.git
cd vigie-options
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# put your tickers in watchlist.txt, one per line
claude
> /bourse
```

Tests run on simulated data with no network access: `pip install -r requirements-dev.txt && pytest`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `collect.py` refuses to collect | The US session is open, so volumes would be partial | Run it in the morning, before 9:30 a.m. New York time |
| No data on a weekday | US market holiday, unknown to the script | Run again with `--forcer` (the file is excluded from the history) |
| Yahoo Finance download error | yfinance changed or Yahoo is blocking temporarily | `.venv/bin/pip install -U yfinance`, then run again |
| A ticker returns nothing | No listed options, or wrong Yahoo symbol | Check the symbol on Yahoo Finance (mostly US stocks) |
| No volume flagged as unusual | History too short (fewer than 10 sessions) | Expected in the first month: automate collection with cron |
| Open interest identical to the day before | Yahoo's open interest lags one session | The lag is detected and flagged; run again later in the morning |

## Disclaimer

Options volume does not reveal direction: every contract has a buyer and a seller. yfinance is an unofficial, delayed data source for personal use. **Nothing here is investment advice.**

Adapted from a three-agent system described by Ray Fu (French version by Core Labs). MIT licensed.
