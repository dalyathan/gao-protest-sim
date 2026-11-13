# GAO Protest Outcome Simulator

Multi-agent simulation of federal bid protests at GAO. Claude agents play the
protester (company + counsel), the agency, and the GAO attorney, each with its
own scorecard and only the information its real counterpart would have. An RL
decision layer learns the strategic moves (file / defend vs. corrective action /
continue vs. withdraw) from simulated payoffs. Outcomes are backtested against
real published decisions. Design: [GAME_DESIGN.md](GAME_DESIGN.md).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...            # needed for real runs only
# optional: export SIM_MODEL=claude-sonnet-5-5

# Offline plumbing test (no API calls)
python run.py play data/cases/b-424641_packet.yaml --mock

# Play a case with Claude agents (~6 API calls per game)
python run.py play data/cases/b-424641_packet.yaml --repeats 5

# Counterfactuals: force or hand off the agency's decision
python run.py play data/cases/b-424641_packet.yaml --agency defend
python run.py play data/cases/b-424641_packet.yaml --agency benchmark   # rational EV choice
python run.py play data/cases/b-424641_packet.yaml --agency policy      # learned RL policy

# Information scenarios
python run.py play data/cases/b-424641_packet.yaml --scenario full_transparency

# In-context learning: agents write lessons between repeats
python run.py play data/cases/b-424641_packet.yaml --repeats 5 --lessons

# Train the RL decision layer (no API calls; seconds on a laptop)
python run.py train --episodes 80000
python run.py compare        # RL policy vs. rational benchmark, per profile
```

## How it fits together

| Piece | File | What it does |
|-------|------|--------------|
| Case packet | `data/cases/*_packet.yaml` | Documents with visibility tags + payoff parameters |
| Outcome (observer only) | `data/cases/*_observer_only.yaml` | Real result; loaded only for scoring |
| Visibility | `sim/case.py` | Builds each agent's context from allowed tags per turn |
| Agents | `sim/agents.py` | Role, scorecard, task prompts; stateless calls |
| LLM | `sim/llm.py` | Anthropic API or mock; text in, text out, no tools |
| Game | `sim/game.py` | Turns, legal moves, message passing, payoffs, scoring |
| Payoffs | `sim/payoffs.py` | Scorecards, computed by the observer |
| Benchmark | `sim/benchmark.py` | Risk-neutral expected-value choice |
| RL layer | `sim/rl.py` | Independent Q-learners for protester and agency |
| Belief profiles | `data/profiles/*.json` | Beliefs from LLM games; the RL training environment |

Each `play` run writes a full JSON log (every prompt response, decision,
who made it, what the LLM would have chosen, payoffs, score) to `runs/`, and
updates the case's belief profile for RL training.

## Data

GAO bid protest decisions are U.S. government works (public domain).

```bash
python scripts/fetch_decisions.py --pages 5 --since 2026-07-01   # needs access to gao.gov
python scripts/make_blind_cases.py
```

Caveat: GAO generally does not publish dismissals or protests resolved by
corrective action, so published decisions over-represent merits rulings.

## Status

1. [x] Repo, data fetcher, blinding step
2. [x] Game design + actor config
3. [x] Run 01: first agent game on B-424641 (`runs/2026-11-11_b-424641_run01.md`)
4. [x] Orchestrator (stateless API agents, visibility filtering, payoffs, scoring)
5. [x] RL decision layer + rational benchmark
6. [ ] ≥30 case packets; backtest scoreboard
7. [ ] Calibrate payoff parameters to real agency behavior (see GAME_DESIGN §8)
8. [ ] Demo page

## Running on your Claude subscription (no API key)

Each agent turn can go through Claude Code's `claude -p` instead of the API:

```bash
SIM_BACKEND=cli bash run_all.sh            # Sonnet (default)
SIM_BACKEND=cli SIM_CLI_MODEL=opus bash run_all.sh
```

Every call runs in an empty temp folder with all tools off, `--safe-mode`, and no saved
session, so agents can't read project files (including observer-only outcomes) or each
other. Usage counts against your plan's limits; there is no temperature control.

## Test set workflow (post-cutoff GAO decisions)

1. `python scripts/split_gao_decision.py` — facts-only text vs. answer key (no LLM).
2. `python scripts/build_test_packets.py --limit 3` then without `--limit` — Haiku 5.5 via `claude -p`
   builds `data/cases_test/` (facts call never sees the outcome; a separate call writes the observer file).
3. Re-run dev cases with the fixed code, freeze the system, then `SIM_BACKEND=cli bash run_test.sh` once.
   It runs the multi-agent game and the single-agent baseline (`python run.py single ...`) on every case.
