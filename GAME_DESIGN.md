# Game Design: GAO Bid Protest Simulator

A multi-agent simulation of a GAO bid protest. Each party is a separate Claude
instance with its own objective, its own information, and its own allowed moves.
A neutral observer (code) runs the game, enforces the rules, scores outcomes,
and measures how well the simulation reproduces real cases.

---

## 1. Actors

| ID | Actor | Wants | Allowed moves |
|----|-------|-------|---------------|
| `protester_co` | Protester company (business side) | Reopen competition and win the work; for incumbents, keep earning during the stay | file / don't file; approve or cut legal budget; withdraw |
| `protester_counsel` | Protester's outside counsel | Win on the merits for the client; credibility with GAO | draft initial grounds; file supplemental grounds; request documents/hearing |
| `agency` | Contracting officer + agency counsel | Keep the award, minimize delay, avoid a public loss and cost reimbursement | defend; take corrective action (any turn); override stay (rare) |
| `intervenor` | Awardee (optional; absent in pre-award protests) | Keep the contract | intervene / stay out; argue in support of agency |
| `gao` | GAO attorney (adjudicator) | Correct, precedent-consistent, timely decision | request info; hold hearing; outcome-prediction ADR; rule per ground |

Background (not agents): other offerors, GSA/OIG, SBA, Court of Federal Claims (alternative forum).

Both cases read so far (B-424672, B-424641) had **no intervenor** — the engine must handle a missing actor.

---

## 2. The Stage (turn structure, 100-day clock)

| Turn | Day (approx.) | Event | Decision-maker(s) |
|------|---------------|-------|-------------------|
| 0 | pre-filing | Debriefing / notice of exclusion | — (information release) |
| 1 | ≤10 | Protest filed with initial grounds (automatic stay begins) | protester_co approves, protester_counsel drafts |
| 1b | ~1–5 | Intervenor decides whether to join | intervenor |
| 2 | ~30 | Agency report produced — **key fork: defend or corrective action** | agency |
| 3 | ~40 | Comments + supplemental grounds (counsel now sees protected record) | protester_counsel, protester_co (budget), intervenor |
| 4 | ~40–90 | Development: info requests, hearing, outcome-prediction ADR; late corrective action possible | gao, then agency |
| 5 | ≤100 | Decision per ground: sustained / denied / dismissed; recommendation; costs | gao |

Terminal outcomes: `denied`, `sustained`, `sustained_in_part`, `dismissed`,
`corrective_action`, `withdrawn`.

---

## 3. Information design (who sees what)

Every document carries a **visibility tag**. Before each turn the observer
builds each agent's context from only the documents its tag allows. Each agent
runs in an isolated conversation — nothing leaks between agents.

| Tag | protester_co | protester_counsel | agency | intervenor | gao |
|-----|:---:|:---:|:---:|:---:|:---:|
| `public` (solicitation, published decisions) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `debrief` (own evaluation, awardee name, sometimes price/overall ratings) | ✓ | ✓ | ✓ | — | ✓ |
| `filed_redacted` (public versions of filings) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `apo` (protected record: awardee proposal, full evaluation) — from turn 2 | — | ✓ | ✓ | ✓ (own counsel) | ✓ |
| `agency_internal` (deliberations, true record quality) | — | — | ✓ | — | — |
| `private_<actor>` (scorecard, beliefs, payoffs) | own only | own only | own only | own only | own only |

**Company/counsel split:** counsel sees the protected record but may only give
the company non-specific advice (e.g., "strong argument on past performance").
The company decides budget and whether to continue without seeing the details.

**Memory across repeated rounds:** an agent remembers its *own* past actions
and payoffs plus *public* knowledge (published decisions). Never other
parties' private payoffs or beliefs.

---

## 4. Scorecards (rewards)

Rewards are computed by the observer, never by the agents. Agents are given
their own scorecard and must reason with it explicitly (stated expected values).

**Protester company**
```
U = P(relief) * V_contract * P(win_recompete)
  + incumbent * stay_days * daily_margin
  - legal_cost
  - relationship_cost
```

**Protester counsel**
```
U = client_U  +  w_rep * credibility   (penalty for frivolous / fabricated grounds)
```

**Agency**
```
U = - delay_cost_per_day * stay_days
    - P(sustain) * (public_loss + cost_reimbursement)
    - corrective_action_cost * took_corrective_action
```
Cost reimbursement is recommended when grounds are clearly meritorious and the
agency unduly delayed corrective action — so early corrective action on a weak
record should dominate late corrective action.

**Intervenor**
```
U = P(keep_award) * V_contract - legal_cost
```

**GAO** — not self-interested. Scored on consistency with law and precedent;
its rulings are compared with real outcomes.

### Where each parameter comes from

| Parameter | Source |
|-----------|--------|
| `V_contract` | Decision text; USAspending / FPDS |
| `incumbent` | Award history (USAspending / FPDS) |
| `stay_days` | GAO docket filed/decided dates |
| `P(win_recompete)` | Number of offerors (decision text); base rates |
| Priors for `P(sustain)` by ground type | Historical GAO decisions + annual reports |
| `legal_cost`, `relationship_cost`, `public_loss`, `delay_cost_per_day`, `corrective_action_cost` | **Not public** — assumed ranges, varied in sensitivity analysis, or fitted (§8) |

---

## 5. Game-theory models built in

| Model | Where it applies | Testable prediction |
|-------|------------------|---------------------|
| Settlement under asymmetric information (Bebchuk 1984) | Agency's corrective-action fork; agency privately knows record quality | Weak records → corrective action before agency report |
| Selection effect (Priest & Klein 1984) | Published decisions are a filtered sample of close cases | Published-decision base rates ≠ all-protest base rates |
| War of attrition / value of delay | Incumbent protester earns during automatic stay | Incumbents protest more on weaker grounds |
| Bayesian persuasion / disclosure | Debriefing quality, agency report, supplemental grounds | Thin debriefings → more protests, more grounds |
| Fee-shifting (Shavell) | GAO cost reimbursement for undue delay | Corrective action timing shifts earlier |
| Repeat players (Galanter) | Agencies, large firms, serial protesters | Reputation for fighting → more early corrective actions |

The theory sets the rules and the **rational benchmark**; agents are not
scripted to play equilibrium. Deviations from the benchmark are findings.

---

## 6. The Observer

**Drive: fidelity.** Make the simulated world behave like the real one, then
measure. No preference for harmony, no forcing of equilibrium.

Three modes — never mixed within a run:

| Mode | Objective | Product |
|------|-----------|---------|
| Scientist (default) | Reproduce real outcomes on unseen cases | Accuracy scoreboard |
| Advisor | Maximize one client's payoff | "Should we protest?" / "Protest-proof this award" |
| Designer | Choose rules to improve system welfare | Policy what-ifs |

Observer duties: enforce turn order and allowed moves; filter documents by
visibility tag; compute payoffs; compute rational benchmark; log everything.

---

## 7. Experiments

### 7.1 Differentiation levers (add one at a time)

| Config | Adds |
|--------|------|
| A | Role name only |
| B | + numeric scorecard |
| C | + hidden information (visibility tags) |
| D | + enforced action space |
| E | + neutral referee scoring |
| F | + repeated rounds with own-payoff feedback |
| G | + variation (temperature / model mix) |

### 7.2 Scorecard variants (on best config)
- Risk-neutral expected value
- Risk-averse (concave utility)
- Myopic vs. reputation-aware (repeat players)
- Fee-shifting rules: current / loser-pays / no reimbursement

### 7.3 Information scenarios
- **Realistic** (§3)
- **Full transparency** — everyone sees everything
- **No protective-order access** — counsel sees only redacted record
- **Thin vs. thorough debriefing**

### 7.4 Incentive-swap test (must pass)
Swap scorecards (e.g., make the protester an incumbent with high daily margin)
and confirm behavior shifts in the predicted direction. If it doesn't, the
incentives are cosmetic.

### 7.5 Metrics
1. Accuracy vs. actual outcome (blind cases), vs. base-rate baseline
2. Incentive sensitivity (§7.4)
3. Distance from rational benchmark
4. Behavioral diversity across agents
5. Cost (tokens per simulation)

---

## 8. Data flow and the leakage rule

```
Public data (decisions, docket, USAspending)
 ├─ Facts      → each agent's context (filtered by visibility tag)
 ├─ Values     → scorecard parameters
 ├─ Base rates → agents' prior beliefs
 └─ Outcomes   → LOCKED; observer scoring only
```

- **Outcomes never enter rewards or agent context.**
- **Time split:** calibrate on decisions before 2026; test on decisions after
  mid-2026 (also avoids cases seen in model training).
- **Structural estimation (inverse RL):** for parameters that aren't public,
  search for weights that make simulated behavior match historical behavior
  (who protested, when agencies took corrective action), then test on new cases.

---

## 9. Build order

1. Data: expand fetcher — GAO docket + USAspending values (≥30 blind cases)
2. Case schema with visibility tags (`config/case_schema.yaml`)
3. Agent prompts per actor + scorecards (`config/actors.yaml`)
4. Observer/orchestrator: turns, filtering, payoffs, logs
5. Rational benchmark calculator
6. Run 2 known cases through configs A–G (sanity check)
7. Scale to ≥30 cases × 5 runs; scoreboard
8. Demo page

Running at scale requires an Anthropic API key on the user's machine.
