# GAO Protest Outcome Simulator

Multi-agent simulation that predicts the outcome of federal bid protests at GAO
(sustain / deny / dismiss / agency corrective action), backtested on real
published decisions.

## Data

GAO bid protest decisions are U.S. government works and are in the public domain.

- Recent decisions: https://www.gao.gov/legal/bid-protests/recent
- Each decision: `https://www.gao.gov/products/b-XXXXXX`
- Docket (all filings, last 12 months): https://www.gao.gov/legal/bid-protests/search

Caveat: GAO generally does not publish dismissals or protests resolved by
corrective action, so published decisions over-represent merits rulings
(sustain/deny). The docket fills part of that gap.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Pull decisions (run on a machine that can reach gao.gov)
python scripts/fetch_decisions.py --pages 5 --since 2026-07-01

# 2. Build blind cases (facts + protest grounds, outcome held back as label)
python scripts/make_blind_cases.py
```

Only decisions issued after mid-2026 are used for scoring, so the model cannot
have seen them in training.

## Roadmap

1. [x] Repo + data fetcher + blinding step
1b. [x] Game design (GAME_DESIGN.md) + actor config (config/actors.yaml)
2. [ ] Agent simulation: protester counsel, agency counsel, intervenor, GAO attorney
3. [ ] Backtest: accuracy vs. actual outcomes and vs. a base-rate baseline
4. [ ] Demo page: case picker, agent debate, prediction vs. actual, scoreboard

## Layout

```
scripts/fetch_decisions.py   scrape + parse decisions
scripts/make_blind_cases.py  strip outcome/analysis for backtesting
data/seed_recent_decisions.json  8 recent decisions (Oct-Nov 2026) for a first test
data/raw/                    raw HTML (git-ignored)
data/processed/              JSONL outputs
```
