# Blind code review, 2026-11-12

Reviewer: independent Claude Opus 5.5 agent. It had no access to the design conversation. It received only a copy of the code, README, GAME_DESIGN, config and two example cases (B-424623, B-424641). Report reproduced as delivered.

---

## Confirmed problems (most severe first)

**1. The rational benchmark files no matter how weak the case is.** `sim/benchmark.py:216-224`
- `ev_company_t1` assumes the agency backs down (corrective action, which gives relief for sure) 30% of the time, independent of `p_relief`. Counsel's `p_relief` already includes corrective action ("incl. corrective action", `agents.py:290`), so that chance is counted twice.
- Scenario: B-424641 with `p_relief=0` still gives a filing EV of +$91k (+$494k for an incumbent; B-424623 gives +$371k). So the benchmark says "file" for every case, and "distance from rational benchmark" means nothing for the filing decision.
- Fix: treat `p_relief` as the total relief probability, or let the corrective-action chance depend on the merits, e.g. `p_ca = f(p_relief)`, with relief at decision `= pr - p_ca`.

**2. The payoff model makes one of the design's "must pass" incentive tests impossible to pass.** `sim/payoffs.py:191-199`, `config/actors.yaml:90`
- Corrective action at turn 2 costs 5+90 = 95 days of delay, while defending costs 70 (100 if sustained). A higher daily delay cost therefore pushes the agency toward *defending*.
- Checked with `benchmark_choice` at p_sustain=0.5: corrective action at $1k and $10k a day, defend at $20k and $40k a day.
- The expected result "agency.delay_cost_per_day high → earlier corrective action" can only show up when p_sustain is above about 0.83. LLM agents that get this scorecard will be pushed the same way.
- Fix: decide whether the re-evaluation days really count as delay (the stay lifts at corrective action). If not, charge only the stay days, or charge the 90 days in both branches, since a sustain also leads to re-evaluation.

**3. Supplemental grounds crash the game.** `sim/game.py:103,114`
- `keep` gets the raw `supplemental` list appended, then line 114 runs `g in grounds` on a dict. The prompt never says what an item looks like, so a model may well return objects.
- Mock check: `supplemental=[{"id":"s1",...}]` raises `TypeError: unhashable type: 'dict'`.
- Even string IDs are dropped before GAO sees them (`if g in grounds`). And if counsel keeps nothing but adds a supplemental, GAO gets an empty "Grounds remaining:" list and still rules.
- Fix: normalise supplementals to `{id,name}`, add them to `grounds`, and pass them to GAO.

**4. Decisions in uppercase abort the run.** `sim/game.py:72`, `sim/agents.py:291,294,299`
- The task text literally says "Decide FILE or DO_NOT_FILE", "CONTINUE or WITHDRAW". A mock answer of `"FILE"` raises `AssertionError: illegal move`, and `run_all.sh` then reports the whole case as FAILED.
- The GAO `overall` value is never validated: `"denied in part"` was accepted as the outcome, and its payoffs were computed as if the protest was denied.
- Fix: `.strip().lower()` the answers, map synonyms, re-ask on an invalid value, and use a raise rather than `assert`.

**5. `--agency policy` / `--company policy` crash when there is no trained policy.** `run.py:68`, `game.py:66`
- `policy=None`, then `self.policy.act` gives `AttributeError` (confirmed). Fix: exit with a clear message.

**6. A game where the company doesn't file breaks `train` and `compare`.** `run.py:46-59`, `sim/rl.py:344`
- That profile has no `agency_p_sustain_any`. Confirmed: `KeyError: 'agency_p_sustain_any'` in `ProtestEnv.episode`, and `cmd_compare` fails the same way.
- Also, each repeat and each scenario or forced-decider run *overwrites* `data/profiles/<case>.json`. RL therefore trains on the last game played (it could be a `full_transparency` or `--agency corrective_action` run), not on an average.
- Fix: average over the realistic-scenario LLM games only, and skip or fill missing keys.

**7. API usage numbers add up across repeats.** `game.py:139`
- The LLM object is shared across repeats, so each log stores the running total. Mock repeats logged calls=6, 12, 18.
- `analyze_runs.py:58` then sums these, overcounting tokens (the "cost per simulation" metric). Fix: store the difference from the start of each game.

**8. The policy table shows a different "best" move from what the policy actually does.** `sim/rl.py:285,293`
- `act()` treats untried actions as Q=0. All agency rewards are negative, so an untried action always wins.
- Confirmed: the saved table says `ps2|d0 best=defend`, but `act()` returns `corrective_action`. Many states have n=1 visits.
- Fix: in `act`, choose only among actions that have been visited (or start Q at a large negative value), and report visit counts.

**9. Payoffs disagree between the game and the RL environment, and some payoff flags are ignored.**
- `game.finish` charges the agency the full 70-day defense when the protester withdraws, giving -$700k, the same as a denial. `rl.py:356` charges half (`*0.5`).
- `costs_recommended` from GAO is ignored: every sustain or partial sustain reimburses protester costs (`payoffs.py:184,199`).
- `p_prejudice` is asked for but never used. `p_any` assumes independent grounds and ignores prejudice, which overstates the agency's P(sustain). The mock gives 0.66, which crosses the corrective-action threshold.

**10. Per-ground scoring is not real.** `game.py:150-152`, `scripts/analyze_runs.py:54`
- `score()` copies the simulated rulings and never compares them. The real rulings for B-424641 use names (`dbb_unstated_criterion`, five grounds), while the simulation uses g1..gN.
- `analyze_runs` falls back to matching by list position, which depends on the order counsel happened to list the grounds.
- Fix: map each case's real grounds to fixed IDs in the case file and require counsel to use them, or match grounds explicitly.

**11. Resume can skip runs it shouldn't.** `run.py:72-74`
- The run tag leaves out `--company`, `--temperature` and the model. Running `--company file` after a default run silently skips every repeat as "already done".

**12. A fresh install fails.** `requirements.txt`
- PyYAML is imported everywhere but isn't listed, and none of the listed packages pulls it in. A fresh venv from the README fails on `import yaml`.
- `run_all.sh` hard-requires `.venv`, which the CLI section of the README doesn't create.

**13. The mock gives a false "match".** `sim/llm.py:415-434`
- The canned answers are tuned to B-424641's real result (g1 sustained, `sustained_in_part`). A mock run reports `outcome_match: True`, which someone could read as validation.
- The same canned answer scores wrong on B-424623 (real result: denied). Label mock scores as not meaningful.

**14. `fetch_decisions.py` duplicates records on re-runs.** `fetch_decisions.py:255`
- It opens `decisions.jsonl` with `"a"`, so each re-run appends duplicates, and `make_blind_cases` carries them through.

## Suspicions (not fully verified)
- **The case files may leak the outcome.** The case files were written from the GAO decisions, so they may give away the answer:
  - B-424641's public synopsis says it "states no preference for any project delivery method".
  - Its `agency_internal` says the DBB preference "does not appear in the synopsis or Q&A". That is close to GAO's holding stated as fact.
  - B-424623's `agency_internal` is word-for-word the APO agency report, so the agency has no private information about record quality (the Bebchuk mechanism has nothing to work on).
- **`make_blind_cases.py` probably doesn't blind well.** Its regex drops sentences containing deny/sustain/dismiss, but GAO "DIGEST" lines with other wording ("agency unreasonably…") would likely survive. Also, the README's data pipeline doesn't produce the case files: `extracted_to_packets.py` reads a `data/extracted/` folder that nothing creates.
- **The temperature fallback probably never runs.** `AnthropicLLM` catches `TypeError` when temperature is rejected, but the API returns `BadRequestError`, so the fallback likely never triggers.
- **The RL company can't learn from merits.** Its state is counsel's noisy `p_relief`, but outcomes are drawn from the agency's `true_p`. Within a case the state carries no signal, so the learned "continue" policy reflects only the mix of cases.
- **`no_apo_access` misleads counsel.** In that scenario the T3 prompt still tells counsel "You now see the protected record".
- **CLI flags.** `--safe-mode`, `--tools ""` and `--no-session-persistence` appear in `claude --help`; `--system-prompt-file` is mentioned there; `--max-turns` isn't shown, so I couldn't verify it.

## What is solid
- Information filtering in `case.py` is correct for the realistic scenario:
  - Protected (APO) material reaches the agency at turn 2 and counsel/GAO at turn 3.
  - The company never sees APO or agency-internal documents.
  - Loading an observer-only file is refused.
  - The real outcome is never put into a prompt or a reward.
- Each call is stateless, and the CLI backend is well isolated (empty temp folder, no tools, API key removed).
- Every log records each decision, who made it, and what the LLM would have chosen.
- Forced, benchmark and policy deciders are cleanly separated.
- The RL training loop is simple, deterministic (seeded) and fast.
- The mock path runs end to end on both cases.

---

## Status of fixes (same day)

Regression tests: `python tests/test_review_fixes.py` (11 tests, all passing).

| # | Status | Change |
|---|---|---|
| 1 | Fixed | Benchmark treats `p_relief` as total relief; `ca_share_of_relief` (default 0.6) only splits it into early vs. decided relief. B-424641 now files only above ~22% (non-incumbent). |
| 2 | Fixed | Sustain = stay + re-evaluation; denial = stay; early CA = 5 days + re-evaluation; withdrawal = 40 days. Higher delay cost now pushes toward corrective action. Agency scorecard text updated. |
| 3 | Fixed | Supplemental grounds normalised to `{id, name}`, added to grounds and sent to GAO. |
| 4 | Fixed | Moves normalised (case, spaces, synonyms); invalid answers get one repair round, then a clear error. GAO's overall outcome is now derived from its per-ground rulings (stated overall kept for reference). |
| 5 | Fixed | Policy decider without a trained policy exits with a message. |
| 6 | Fixed | Profiles: only realistic, unforced LLM games; running mean across games; incomplete profiles skipped by train/compare. |
| 7 | Fixed | Logs store per-game usage. |
| 8 | Fixed | Policy never prefers an untried action; explores untried ones during training. |
| 9 | Partly | Withdrawal payoff now identical in game and RL; `costs_recommended` respected. `p_prejudice` still unused. |
| 10 | Fixed | Packets carry `filed_grounds` with ids shared with the observer file; `--fixed-grounds` (automatic with `--real-path`) makes counsel argue exactly those; score reports per-ground match and each agent's probability. Free-play grounds reported as not comparable. |
| 11 | Fixed | Run name includes deciders, fixed grounds, model and temperature. |
| 12 | Fixed | PyYAML added to requirements. |
| 13 | Fixed | Mock runs print that their scores are not meaningful. |
| 14 | Open | fetch_decisions.py append duplicates (script is blocked by GAO anyway). |
| Suspicion: temperature fallback | Fixed | Fallback also catches the API's 400 error mentioning temperature. |
| Suspicion: no_apo_access prompt | Fixed | Separate T3 task text for counsel without protected-record access. |
| Suspicion: case-file leakage | Addressed for the test set | `scripts/split_gao_decision.py` builds facts-only files (intro minus outcome sentences + BACKGROUND), answers stored separately; costs requests, reconsiderations and facts with GAO-voice conclusions excluded. 66 usable merits cases (`data/test_set_v1.json` → `merits_test_set`). Hand-written dev packet B-424641 left as is (dev only). |
