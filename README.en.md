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
- **Open interest is compared contract by contract**, to tell newly opened positions from closed ones.
- **"Unusual" is measured against each ticker's own history** (percentile rank, then z-score), never in absolute terms.
- **No gaps are ever filled**: missing data stays `INDISPONIBLE` (unavailable).
- **A tracking journal** records every flag so you can measure the real hit rate after a few months.

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

## Disclaimer

Options volume does not reveal direction: every contract has a buyer and a seller. yfinance is an unofficial, delayed data source for personal use. **Nothing here is investment advice.**

Adapted from a three-agent system described by Ray Fu (French version by Core Labs). MIT licensed.
