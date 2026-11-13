# GAO Protest Outcome Simulator

> **Status: archived 2026-11-13.** Research prototype, paused by decision of the author
> (Surafel) after concluding that GAO bid protests are probably not worth pursuing as a business.
> The methods are reusable; see "What carries over" below. Usage docs follow the summary.

## Summary of the work and discussion (2026-11-11 to 2026-11-13)

### How we got here
Started from "strategic interaction between agents": can Claude agents with different incentives
interact, and can we observe and learn from it? Explored business ideas (competitive bidding, FDA
approval, Senate hearings, networking, trade/AD-CVD data, multi-agent coding, government purchasing)
and picked **GAO bid protests**: niche, game-theoretic, government data, and a concrete buyer
question ("should we protest?"). Goal: something to show CTOs and possibly apply to Y Combinator.

### What was built
- **Multi-agent game** (`sim/`): protester company, protester counsel, agency, GAO (intervenor
  designed, not active). Each agent sees only what its real counterpart would: public, debrief,
  private_protester, agency_internal, protected (APO) record. Company/counsel split under the
  protective order. 100-day clock: file -> agency report or corrective action -> comments ->
  continue/withdraw -> GAO ruling.
- **Scorecards** with game-theory grounding: Bebchuk asymmetric-information settlement, Priest-Klein
  selection, war of attrition and the automatic stay, Bayesian persuasion, fee shifting, repeat
  players. Rule: real outcomes never enter rewards. Observer modes: scientist (fidelity), advisor,
  designer.
- **Rational benchmark** and an **RL decision layer** (tabular Q-learning) for file / defend vs
  corrective action / continue vs withdraw; incentive-swap tests.
- **Single-agent baseline** (`python run.py single`) and **fixed-grounds scoring**: counsel argues the
  grounds actually filed, scored ground by ground against GAO.
- **Backends:** Anthropic API, or Claude Code `claude -p` on a subscription (isolated: empty temp
  dir, no tools, safe mode, no session), parallel via `JOBS=n`. Mock backend for plumbing tests.
- **Test-set pipeline:** facts-only split of GAO PDFs; Haiku builds case packets in one call and,
  separately, the answer key in another, so the packet never sees the outcome; leak scan.

### Data
- **GAO website:** blocked automated access (403 / rate limits). We did not try to get around it.
  Recent decisions were read slowly by hand-saved PDFs instead.
- **Post-cutoff test set:** 88 GAO decisions downloaded by hand (Jun-Nov 2026); 77 dated
  2026-08-01 or later; **66 usable merits cases** after excluding costs requests, reconsiderations
  and facts sections containing GAO conclusions (`data/test_set_v1.json`, frozen with file hashes).
  The Claude 5.5 models' reliable knowledge cutoff is June 2026.
- **HeinOnline (UTulsa):** ~3,300 decisions collected by paced, scripted download (6 s down to 1.5 s
  plus random delay), plus a batch of ~5,200 denials/dismissals in progress at archive time.
  The library approved paced downloads for analysis; when we exceeded the volume first described,
  we disclosed it and the library approved the amount and further collection for **private research
  use** (`docs/HEINONLINE_PERMISSION.md`). **Full texts are not in this repo and must not be
  redistributed**; commercial use is not covered. Coverage ends ~March 2025 (pre-cutoff: dev and
  calibration only).
- **8 dev cases** (`data/cases/`), now burned for testing because we tuned on them.

### Results so far
- Real-path games on the 8 dev cases: win/lose 21/24 and per-ground 19/22, **equal to the
  "protester always loses" baseline**. One false sustain (Casey) came from the model applying
  fairness instead of GAO doctrine.
- What the GAO PDFs cover: the filing, the agency's defence (paraphrased; record cited in 95%),
  and GAO's per-ground rulings. Protests ended by corrective action or withdrawal never appear,
  and the parties' actual filings are not public, so the "will the agency back down?" branch can
  only be calibrated from GAO's annual statistics.

### Reviews
- **Independent methods review** (`docs/REVIEW_2026-11-12.md`): label leakage, base rates (AUROC,
  Brier, sustain recall), dev/test split, freeze before testing, single-LLM baseline, outcome-blind
  extraction, calibrate to aggregate statistics, not published decisions.
- **Blind code review** by a separate Opus 5.5 agent (`docs/CODE_REVIEW_2026-11-12.md`): 14
  confirmed problems (benchmark always filed, delay-cost sign, crashes on supplemental grounds and
  uppercase moves, fake per-ground scoring, usage totals, RL untried-action bias, ...). Fixed with
  regression tests (`tests/test_review_fixes.py`).

### Methodological decisions
- Test only on decisions issued after the model's training cutoff; freeze model, prompts and
  config first; run the test once. Compare: multi-agent game, single agent, question-path predictor,
  and "always denied".
- Older models do not help: the oldest callable Claude (Sonnet 4.5, retiring 2026-11-30; Sonnet 4
  already retired) was trained past the end of the HeinOnline data.
- **Calibration** (`docs/CALIBRATION_PLAN.md`): fit 2-3 behavioural parameters by ABC to GAO FY2021-25
  statistics (effectiveness ~52% of cases, sustain ~14-16% of merits decisions, ~22% of cases reach
  a merits decision); first check that agents respond to the scorecard numbers at all.
- Persistent single `claude` process rejected: context would accumulate and leak across cases.

### Research directions explored
- **Question-path predictor** (`docs/QUESTION_TREE_PLAN.md`): an LLM answers factual yes/no questions
  about a case; learn which to ask, in what order, and when to stop. Formalised as a stochastic
  shortest path over knowledge states: step weight = lambda - expected information gain (history-
  dependent, negative when worth asking), stop edge = expected log-loss. Nodes pass forward their
  metacognition (confidence, evidence, what is missing). Because LLM answers are noisy, compare
  noise-robust selection (EC2, Golovin-Krause) against greedy information gain. Very short paths,
  even one question, are a possibility the search should allow, not an assumption.
- Related work: ACT, Tree Prompting, GPTree, LLM-generated features (Balek 2025); active feature
  acquisition; adaptive submodularity; Uncertainty of Thoughts, BED-LLM, CA-BED; ABM calibration
  (simulated moments, ABC), Waldfogel's structural Priest-Klein estimates, inverse RL; LLM multi-agent
  organisation (OrgAgent, self-organising agents, "Why do multi-agent LLM systems fail?").
- Conceptual threads: copies of one model still need organisation when they hold different
  information or act for different people; decisions can be brute-forced, judgement cannot,
  because nothing checks it but reality; institutions (courts, contracts) as the coordination
  layer agents will need.

### Market notes
- YC-backed GovCon AI companies (GovDash, Govly, GovEagle, Hazel, Usul, Candor, Revere, Chromie,
  Locke) focus pre-award; CLEATUS markets bid-or-protest support.
- ~1,700 GAO protests/year; legal fees typically $20k-$100k+ (large cases $300k+); filing fee ~$500;
  reimbursement for large firms capped at ~$150/hour. FY2026 NDAA s.875: DoD may withhold up to 5% of
  payments to incumbents whose GAO protest is dismissed as lacking any reasonable basis; GSA asked
  Congress for the same on civilian protests (July 2026).
- RAND (2018): only ~0.3% of DoD contracts protested; poor debriefings drive protests; over half
  filed by small businesses. Many protest partly to learn why they lost.
- Without costs nearly every loser would protest; costs filter cases, which shapes the data.

### Why it was paused
Small market (roughly $100-150M/yr in legal fees), lawyers as gatekeepers, a hard data ceiling
(filings not public, test cases are GAO's summaries), and an emerging competitor.

### What carries over
A hidden-information multi-agent game engine, a cost-aware question-path predictor, post-cutoff
frozen testing, and calibration to an institution's published statistics apply to any adversarial
process with documents, a decision-maker and published outcomes: e.g. PTAB patent challenges
(public filings, clear institution decision), FDA decisions, trade-remedy cases.

### Not in this repo (by design)
HeinOnline full texts (`data/heinonline_raw/`), GAO PDFs and their text, the facts/answer splits,
built test packets, run logs (`runs/*.json`), and `.env`.

---

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

## Before the test is frozen (do not skip)

- **Calibrate to GAO annual statistics** — see `docs/CALIBRATION_PLAN.md` (relief ≈ 52% of filed, sustain ≈ 14–16% of merits decisions).
- Re-run the 8 dev cases with the fixed code.
- Freeze config + prompts + model, then run `run_test.sh` once.

## Status

1. [x] Repo, data fetcher, blinding step
2. [x] Game design + actor config
3. [x] Run 01: first agent game on B-424641 (`runs/2026-11-11_b-424641_run01.md`)
4. [x] Orchestrator (stateless API agents, visibility filtering, payoffs, scoring)
5. [x] RL decision layer + rational benchmark
6. [x] 66 post-cutoff test packets built; test not yet run
7. [ ] Calibrate to GAO annual statistics (docs/CALIBRATION_PLAN.md)
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
