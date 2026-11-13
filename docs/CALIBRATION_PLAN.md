# Calibration plan: fit the simulator to GAO's published statistics (inverse modeling)

**Status: TO DO. Must happen before the system is frozen for the 66-case test.**
Requested by Surafel, 2026-11-12: "DON'T FORGET THIS."

## Idea
Like differentiable-simulation work (e.g. Pasteur Labs' Tesseract), tune the simulator's free
parameters until its *aggregate* behaviour matches measured reality, then test predictions on
unseen cases. Calibrate to GAO's annual statistics, never to individual published decisions
(published decisions are a selected sample: the reviewer called fitting to them circular).

## Targets (GAO Bid Protest Annual Report to Congress, FY2025, released 2025-12-12)
| Statistic | FY2025 | FY2024 | FY2023 | FY2022 | FY2021 |
|---|---|---|---|---|---|
| Cases filed | 1,688 | 1,803 | 2,025 | 1,658 | 1,897 |
| Cases closed | 1,737 | 1,706 | 2,041 | 1,655 | 2,017 |
| Merits decisions (sustain + deny) | 380 | 386 | 608 | 455 | 581 |
| Sustains | 53 | 61 | 188 | 59 | 85 |
| Sustain rate (of merits decisions) | 14% | 16% | 31%* | 13% | 15% |
| Effectiveness rate (relief via corrective action or sustain, of cases) | 52% | 52% | 57% | 51% | 48% |
*FY2023 inflated by the CIO-SP4 protests; exclude.

Derived targets for free play (all LLM deciders, realistic scenario):
- P(relief | filed) ≈ 0.50  (effectiveness rate)
- P(merits decision | filed) ≈ 0.22  (380 / 1,737 closed)
- P(sustain | merits decision) ≈ 0.14–0.16
- So most relief (~45 of the 52 points) must come from agency corrective action, not sustains;
  most non-relief cases end by dismissal/withdrawal, not a denial.
Most prevalent sustain grounds FY2025: unreasonable technical evaluation; unreasonable cost/price
evaluation; unreasonable rejection of proposal.

## Parameters to fit
agency_delay_cost_per_day, corrective_action_cost, agency_public_loss, corrective_action_days,
protester_legal_cost / legal_cost_early, relationship_cost, ca_share_of_relief (benchmark).

## Method
1. Calibration pool: dev cases + a sample of pre-cutoff HeinOnline decisions turned into packets
   (NOT the 66 test cases). Note the pool over-represents merits decisions; weight accordingly.
2. Grid or Bayesian search over the parameters; for each setting play free games (cheap model / mock
   for plumbing, Haiku for real) and record the outcome mix.
3. Loss = distance between simulated and target rates above (relief rate, merits share, sustain rate).
4. Freeze the best setting in config; record it in this file with the date.
5. Only then run run_test.sh on the 66 post-cutoff cases.

## Sources
- Pillsbury, Jenner & Block, Crowell & Moring, Fox Rothschild summaries of the FY2025 report (Dec 2025).
