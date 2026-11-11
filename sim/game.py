"""The game: turns, allowed moves, message passing, and observer scoring.

Decision points (who chooses can be 'llm', 'policy' (RL), or 'benchmark'):
  T1 protester_co : file | do_not_file
  T2 agency       : defend | corrective_action
  T3 protester_co : continue | withdraw
LLM agents always provide the reasoning/beliefs; the decision-maker may differ.
"""
import json
import time

from .agents import TASKS, prompt
from .case import Case, load_outcome
from .llm import extract_json
from .payoffs import agency_payoff, protester_payoff

MOVES = {
    "COMPANY_T1": ["file", "do_not_file"],
    "AGENCY_T2": ["defend", "corrective_action"],
    "COMPANY_T3": ["continue", "withdraw"],
}


def p_any(ps: dict, keep: list | None = None) -> float:
    """P(at least one ground sustained), treating grounds as independent."""
    q = 1.0
    for g, p in ps.items():
        if keep is None or g in keep:
            q *= 1 - float(p)
    return 1 - q


class Game:
    def __init__(self, case: Case, llm, scenario="realistic", deciders=None, policy=None,
                 temperature=0.7, memory=None):
        self.case, self.llm, self.scenario = case, llm, scenario
        self.p = case.params
        self.deciders = {"COMPANY_T1": "llm", "AGENCY_T2": "llm", "COMPANY_T3": "llm", **(deciders or {})}
        self.policy, self.temperature = policy, temperature
        self.memory = memory or {}
        self.log = {"case_id": case.case_id, "scenario": scenario, "deciders": self.deciders, "turns": []}

    # --- helpers -----------------------------------------------------------
    def ask(self, actor, tag, turn, extra_context=""):
        ctx = self.case.context_for(actor, turn, self.scenario)
        if extra_context:
            ctx += "\n\n" + extra_context
        system, user = prompt(actor, tag, ctx, self.p, TASKS[tag], self.memory.get(actor, ""))
        t0 = time.time()
        text = self.llm(system, user, self.temperature)
        out = extract_json(text)
        self.log["turns"].append({"turn": turn, "actor": actor, "task": tag, "json": out,
                                  "raw": text, "secs": round(time.time() - t0, 1)})
        return out

    def decide(self, tag, llm_choice, state):
        who = self.deciders[tag]
        if who == "llm":
            choice = llm_choice
        elif who == "policy":
            choice = self.policy.act(tag, state, explore=False)
        elif who == "benchmark":
            from .benchmark import benchmark_choice
            choice = benchmark_choice(tag, state, self.p)
        else:
            choice = who  # forced move, e.g. "defend" for counterfactual branches
        assert choice in MOVES[tag], f"illegal move {choice} for {tag}"
        self.log["turns"].append({"decision": tag, "by": who, "choice": choice,
                                  "llm_would_choose": llm_choice, "state": state})
        return choice

    # --- the game ----------------------------------------------------------
    def run(self) -> dict:
        p = self.p
        # T1: counsel drafts grounds, advises client (no protected info yet)
        c1 = self.ask("protester_counsel", "COUNSEL_T1", 1)
        grounds = {g["id"]: g for g in c1["grounds"]}
        advice = (f"COUNSEL ADVICE: {c1.get('client_advice', '')}\nProposed grounds: "
                  + "; ".join(f"{g['id']} {g['name']} (~{g['p_sustain']:.0%})" for g in c1["grounds"])
                  + f"\nCounsel's overall P(relief): {c1['p_relief']:.0%}")
        co1 = self.ask("protester_co", "COMPANY_T1", 1, advice)
        state1 = {"p_relief": c1["p_relief"], "incumbent": int(p.get("incumbent", 0))}
        filed = self.decide("COMPANY_T1", co1["decision"], state1) == "file"
        if not filed:
            return self.finish(filed=False)

        # T2: agency sees the protest and its own internal view
        protest = "PROTEST FILED. Grounds:\n" + "\n".join(f"{g['id']}: {g['name']}" for g in c1["grounds"])
        a2 = self.ask("agency", "AGENCY_T2", 2, protest)
        a_ps = {g: a2["p_sustain"].get(g, 0.1) for g in grounds}
        state2 = {"p_sustain_any": p_any(a_ps), "delay_cost": p["agency_delay_cost_per_day"]}
        if self.decide("AGENCY_T2", a2["decision"], state2) == "corrective_action":
            return self.finish(filed=True, ca_turn=2, beliefs={"counsel_t1": c1, "agency": a_ps})

        # T3: counsel sees the record; company decides whether to continue
        report = "AGENCY REPORT (agency defends): " + a2.get("report_summary", "")
        c3 = self.ask("protester_counsel", "COUNSEL_T3", 3, protest + "\n\n" + report)
        keep = [g for g in c3.get("keep", grounds) if g in grounds] + list(c3.get("supplemental", []))
        co3 = self.ask("protester_co", "COMPANY_T3", 3, "COUNSEL MESSAGE: " + c3.get("client_message", ""))
        state3 = {"p_relief": c3["p_relief"], "incumbent": int(p.get("incumbent", 0))}
        if self.decide("COMPANY_T3", co3["decision"], state3) == "withdraw":
            return self.finish(filed=True, withdrawn=True)

        # T5: GAO rules on the remaining grounds
        filings = (protest + "\n\n" + report + "\n\nPROTESTER COMMENTS: " + c3.get("comments_summary", "")
                   + "\nGrounds remaining: " + ", ".join(f"{g}: {grounds[g]['name']}" for g in keep if g in grounds))
        gao = self.ask("gao", "GAO_T5", 5, filings)
        return self.finish(filed=True, rulings=gao["rulings"], overall=gao["overall"],
                           beliefs={"counsel_t1": c1, "agency": a_ps, "counsel_t3": c3})

    def finish(self, filed, ca_turn=None, withdrawn=False, rulings=None, overall=None, beliefs=None):
        p = self.p
        if not filed:
            outcome = "not_filed"
        elif ca_turn:
            outcome = "corrective_action"
        elif withdrawn:
            outcome = "withdrawn"
        else:
            outcome = overall
        sustained = outcome in ("sustained", "sustained_in_part")
        relief = sustained or outcome == "corrective_action"
        path = "early" if outcome in ("corrective_action", "withdrawn") else "full"
        self.log["result"] = {
            "outcome": outcome, "rulings": rulings or {},
            "payoffs": {
                "protester_co": protester_payoff(p, filed, path, relief, sustained),
                "agency": agency_payoff(p, filed, bool(ca_turn), ca_turn, sustained),
            },
        }
        self.log["usage"] = dict(self.llm.usage)
        return self.log


def score(log: dict, case: Case) -> dict:
    """Observer only: compare with the real outcome."""
    actual = load_outcome(case)
    if not actual:
        return {}
    sim = log["result"]
    per_ground = {}
    real_grounds = actual.get("grounds", {})
    for g, r in sim["rulings"].items():
        per_ground[g] = r
    return {"sim_outcome": sim["outcome"], "actual_outcome": actual["outcome"],
            "outcome_match": sim["outcome"] == actual["outcome"],
            "sim_rulings": per_ground, "actual_rulings": real_grounds,
            "agency_move_match": (sim["outcome"] == "corrective_action") == bool(actual.get("corrective_action"))}


def save(log: dict, path):
    with open(path, "w") as f:
        json.dump(log, f, indent=2)
