"""The game: turns, allowed moves, message passing, and observer scoring.

Decision points (who chooses can be 'llm', 'policy' (RL), or 'benchmark'):
  T1 protester_co : file | do_not_file
  T2 agency       : defend | corrective_action
  T3 protester_co : continue | withdraw
LLM agents always provide the reasoning/beliefs; the decision-maker may differ.

Grounds. In free play counsel drafts its own grounds (g1, g2, ...). With
fixed_grounds=True and a packet that lists `filed_grounds`, counsel must argue
exactly the grounds the protester actually filed, under their fixed ids, so the
observer can score GAO's ruling ground by ground.
"""
import json
import re
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
SYNONYMS = {
    "do_not_file": ["don't_file", "dont_file", "no_file", "not_file", "decline"],
    "corrective_action": ["ca", "take_corrective_action", "corrective"],
    "defend": ["defend_the_evaluation"],
    "continue": ["proceed", "continue_protest"],
    "withdraw": ["withdraw_protest"],
}
RULINGS = {"sustained": ["sustain", "sustained", "upheld"],
           "denied": ["deny", "denied", "rejected"],
           "dismissed": ["dismiss", "dismissed", "academic", "untimely"]}


class IllegalMove(ValueError):
    pass


def _norm(s) -> str:
    return re.sub(r"[\s\-]+", "_", str(s).strip().lower().strip(".'\""))


def normalize_move(choice, tag: str) -> str | None:
    c = _norm(choice)
    if c in MOVES[tag]:
        return c
    for move, alts in SYNONYMS.items():
        if move in MOVES[tag] and c in alts:
            return move
    return None


def normalize_ruling(r) -> str | None:
    c = _norm(r)
    for k, alts in RULINGS.items():
        if c == k or c in alts or c.startswith(k[:-2]):
            return k
    return None


def overall_from_rulings(rulings: dict) -> str:
    """GAO's overall outcome follows from the ground-by-ground rulings."""
    vals = [v for v in rulings.values() if v]
    if not vals:
        return "dismissed"
    n_s = vals.count("sustained")
    if n_s == len(vals):
        return "sustained"
    if n_s:
        return "sustained_in_part"
    if all(v == "dismissed" for v in vals):
        return "dismissed"
    if "dismissed" in vals:
        return "denied_in_part_dismissed_in_part"
    return "denied"


def p_any(ps: dict, keep: list | None = None) -> float:
    """P(at least one ground sustained), treating grounds as independent."""
    q = 1.0
    for g, p in ps.items():
        if keep is None or g in keep:
            try:
                q *= 1 - float(p)
            except (TypeError, ValueError):
                continue
    return 1 - q


class Game:
    def __init__(self, case: Case, llm, scenario="realistic", deciders=None, policy=None,
                 temperature=0.7, memory=None, fixed_grounds=False):
        self.case, self.llm, self.scenario = case, llm, scenario
        self.p = case.params
        self.deciders = {"COMPANY_T1": "llm", "AGENCY_T2": "llm", "COMPANY_T3": "llm", **(deciders or {})}
        if "policy" in self.deciders.values() and policy is None:
            raise SystemExit("A 'policy' decider needs a trained policy: run `python run.py train` first.")
        self.policy, self.temperature = policy, temperature
        self.memory = memory or {}
        self.filed = case.extra.get("filed_grounds") if fixed_grounds else None
        if fixed_grounds and not self.filed:
            raise SystemExit(f"{case.case_id}: fixed_grounds needs a `filed_grounds` list in the packet")
        self.usage0 = dict(llm.usage)
        self.log = {"case_id": case.case_id, "scenario": scenario, "deciders": self.deciders,
                    "fixed_grounds": bool(self.filed), "turns": []}

    # --- helpers -----------------------------------------------------------
    def ask(self, actor, tag, turn, extra_context="", task=None, check=None):
        """Ask one agent. `check(out)` returns an error string if the answer is unusable;
        the agent then gets one chance to correct it."""
        ctx = self.case.context_for(actor, turn, self.scenario)
        if extra_context:
            ctx += "\n\n" + extra_context
        system, user = prompt(actor, tag, ctx, self.p, task or TASKS[tag], self.memory.get(actor, ""))
        t0 = time.time()
        text = self.llm(system, user, self.temperature)
        try:
            out = extract_json(text)
            err = check(out) if check else None
        except ValueError:
            out, err = None, "Your previous answer was cut off or had no JSON block."
        if err:  # one repair round, same agent, same information
            text += "\n\n[repair]\n" + self.llm(
                system, user + f"\n\nPROBLEM WITH YOUR ANSWER: {err}\nReply with ONLY the corrected ```json``` block.", 0.0)
            out = extract_json(text)
            err = check(out) if check else None
            if err:
                raise IllegalMove(f"{actor} {tag}: {err}")
        self.log["turns"].append({"turn": turn, "actor": actor, "task": tag, "json": out,
                                  "raw": text, "secs": round(time.time() - t0, 1)})
        return out

    def move_check(self, tag):
        def check(out):
            if normalize_move(out.get("decision"), tag) is None:
                return f"'decision' must be one of {MOVES[tag]} (got {out.get('decision')!r})."
            out["decision"] = normalize_move(out["decision"], tag)
        return check

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
        choice = normalize_move(choice, tag)
        if choice is None:
            raise IllegalMove(f"illegal move {who!r} for {tag}")
        self.log["turns"].append({"decision": tag, "by": who, "choice": choice,
                                  "llm_would_choose": llm_choice, "state": state})
        return choice

    # --- the game ----------------------------------------------------------
    def counsel_t1(self):
        if not self.filed:
            def check(out):
                gs = out.get("grounds")
                if not isinstance(gs, list) or not gs or not all(isinstance(g, dict) and "id" in g for g in gs):
                    return "'grounds' must be a non-empty list of {id, name, p_sustain}."
            return self.ask("protester_counsel", "COUNSEL_T1", 1, check=check)
        listing = "\n".join(f"{g['id']}: {g['name']}" for g in self.filed)
        ids = [g["id"] for g in self.filed]
        task = ("The protest has been filed on exactly these grounds (use these ids; do not add, merge or "
                f"rename grounds):\n{listing}\n\n" + TASKS["COUNSEL_T1_FIXED"])

        def check(out):
            got = {g.get("id") for g in out.get("grounds", []) if isinstance(g, dict)}
            missing = [i for i in ids if i not in got]
            if missing:
                return f"'grounds' must contain one entry for each id {ids}; missing {missing}."
        out = self.ask("protester_counsel", "COUNSEL_T1", 1, task=task, check=check)
        names = {g["id"]: g["name"] for g in self.filed}
        out["grounds"] = [{**g, "name": names[g["id"]]} for g in out["grounds"] if g.get("id") in names]
        return out

    def run(self) -> dict:
        p = self.p
        # T1: counsel drafts (or assesses the filed) grounds, advises client (no protected info yet)
        c1 = self.counsel_t1()
        grounds = {str(g["id"]): {"id": str(g["id"]), "name": g.get("name", str(g["id"])),
                                  "p_sustain": g.get("p_sustain")} for g in c1["grounds"]}

        def pct(x):
            try:
                return f"{float(x):.0%}"
            except (TypeError, ValueError):
                return "?"
        advice = (f"COUNSEL ADVICE: {c1.get('client_advice', '')}\nProposed grounds: "
                  + "; ".join(f"{g['id']} {g['name']} (~{pct(g['p_sustain'])})" for g in grounds.values())
                  + f"\nCounsel's overall P(relief): {pct(c1.get('p_relief'))}")
        co1 = self.ask("protester_co", "COMPANY_T1", 1, advice, check=self.move_check("COMPANY_T1"))
        state1 = {"p_relief": float(c1.get("p_relief") or 0), "incumbent": int(p.get("incumbent", 0))}
        filed = self.decide("COMPANY_T1", co1["decision"], state1) == "file"
        if not filed:
            return self.finish(filed=False, beliefs={"counsel_t1": c1})

        # T2: agency sees the protest and its own internal view
        protest = "PROTEST FILED. Grounds:\n" + "\n".join(f"{g['id']}: {g['name']}" for g in grounds.values())
        a2 = self.ask("agency", "AGENCY_T2", 2, protest, check=self.move_check("AGENCY_T2"))
        raw_ps = a2.get("p_sustain") if isinstance(a2.get("p_sustain"), dict) else {}
        a_ps = {g: raw_ps.get(g, 0.1) for g in grounds}
        state2 = {"p_sustain_any": p_any(a_ps), "delay_cost": p["agency_delay_cost_per_day"]}
        if self.decide("AGENCY_T2", a2["decision"], state2) == "corrective_action":
            return self.finish(filed=True, ca_turn=2, beliefs={"counsel_t1": c1, "agency": a_ps})

        # T3: counsel sees the record; company decides whether to continue
        report = "AGENCY REPORT (agency defends): " + str(a2.get("report_summary", ""))
        c3 = self.ask("protester_counsel", "COUNSEL_T3", 3, protest + "\n\n" + report,
                      task=TASKS["COUNSEL_T3" if self.scenario != "no_apo_access" else "COUNSEL_T3_NO_APO"])
        keep_raw = c3.get("keep", list(grounds))
        keep = [str(g) for g in (keep_raw if isinstance(keep_raw, list) else []) if str(g) in grounds]
        for i, s in enumerate(c3.get("supplemental") or [], 1):  # new grounds raised after seeing the record
            sid = str(s.get("id") or f"s{i}") if isinstance(s, dict) else f"s{i}"
            sname = (s.get("name") or s.get("claim") or sid) if isinstance(s, dict) else str(s)
            if sid in grounds:
                sid = f"s{i}"
            grounds[sid] = {"id": sid, "name": sname, "p_sustain": None, "supplemental": True}
            keep.append(sid)
        if not keep:  # counsel abandoned every ground: that is a withdrawal, not a GAO ruling
            self.log["turns"].append({"note": "counsel kept no grounds -> withdrawn"})
            return self.finish(filed=True, withdrawn=True, beliefs={"counsel_t1": c1, "agency": a_ps, "counsel_t3": c3})
        co3 = self.ask("protester_co", "COMPANY_T3", 3, "COUNSEL MESSAGE: " + str(c3.get("client_message", "")),
                       check=self.move_check("COMPANY_T3"))
        state3 = {"p_relief": float(c3.get("p_relief") or 0), "incumbent": int(p.get("incumbent", 0))}
        if self.decide("COMPANY_T3", co3["decision"], state3) == "withdraw":
            return self.finish(filed=True, withdrawn=True, beliefs={"counsel_t1": c1, "agency": a_ps, "counsel_t3": c3})

        # T5: GAO rules on the remaining grounds
        filings = (protest + "\n\n" + report + "\n\nPROTESTER COMMENTS: " + str(c3.get("comments_summary", ""))
                   + "\nGrounds remaining for decision:\n" + "\n".join(f"{g}: {grounds[g]['name']}" for g in keep))

        def gao_check(out):
            r = out.get("rulings")
            if not isinstance(r, dict):
                return "'rulings' must map each remaining ground id to sustained|denied|dismissed."
            missing = [g for g in keep if g not in r]
            bad = {g: v for g, v in r.items() if normalize_ruling(v) is None}
            if missing or bad:
                return f"Give a ruling (sustained|denied|dismissed) for every id in {keep}; missing {missing}, invalid {bad}."
            out["rulings"] = {g: normalize_ruling(r[g]) for g in keep}
        gao = self.ask("gao", "GAO_T5", 5, filings, check=gao_check)
        overall = overall_from_rulings(gao["rulings"])
        costs = gao.get("costs_recommended")
        costs = (overall in ("sustained", "sustained_in_part")) if costs is None else bool(costs)
        return self.finish(filed=True, rulings=gao["rulings"], overall=overall, costs_recommended=costs,
                           gao_stated_overall=gao.get("overall"),
                           beliefs={"counsel_t1": c1, "agency": a_ps, "counsel_t3": c3,
                                    "gao_confidence": gao.get("confidence", {})})

    def finish(self, filed, ca_turn=None, withdrawn=False, rulings=None, overall=None, beliefs=None,
               costs_recommended=False, gao_stated_overall=None):
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
            "outcome": outcome, "rulings": rulings or {}, "costs_recommended": costs_recommended,
            "gao_stated_overall": gao_stated_overall,
            "payoffs": {
                "protester_co": protester_payoff(p, filed, path, relief, sustained,
                                                 costs_reimbursed=sustained and costs_recommended),
                "agency": agency_payoff(p, filed, bool(ca_turn), ca_turn, sustained, withdrawn=withdrawn,
                                        costs_reimbursed=sustained and costs_recommended),
            },
        }
        self.log["beliefs"] = beliefs or {}
        u = self.llm.usage  # this game's usage only, not the running total of the LLM object
        self.log["usage"] = {k: u.get(k, 0) - self.usage0.get(k, 0) for k in u}
        return self.log


def _p(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def score(log: dict, case: Case) -> dict:
    """Observer only: compare with the real outcome, overall and ground by ground.

    Per-ground scoring needs ids shared between simulation and reality: it is exact
    when the game ran with fixed (actually filed) grounds. In free play, counsel's own
    g1..gN are not the real grounds, so per-ground results are reported as not comparable.
    """
    actual = load_outcome(case)
    if not actual:
        return {}
    sim = log["result"]
    win = {"sustained", "sustained_in_part", "corrective_action"}
    actual_won = actual["outcome"] in win or bool(actual.get("corrective_action"))
    out = {"sim_outcome": sim["outcome"], "actual_outcome": actual["outcome"],
           "outcome_match": sim["outcome"] == actual["outcome"],
           "protester_won_match": (sim["outcome"] in win) == actual_won,
           "agency_move_match": (sim["outcome"] == "corrective_action") == bool(actual.get("corrective_action"))}
    real = actual.get("grounds") or {}
    if not log.get("fixed_grounds"):
        out["per_ground"] = "not comparable (free play: counsel drafted its own grounds)"
        return out
    b = log.get("beliefs", {})
    c1 = {str(g["id"]): _p(g.get("p_sustain")) for g in b.get("counsel_t1", {}).get("grounds", [])}
    c3 = b.get("counsel_t3", {}).get("p_sustain", {}) if isinstance(b.get("counsel_t3", {}).get("p_sustain"), dict) else {}
    ag = b.get("agency", {})
    conf = b.get("gao_confidence", {}) if isinstance(b.get("gao_confidence"), dict) else {}
    single = b.get("single_p_sustain", {}) if isinstance(b.get("single_p_sustain"), dict) else {}
    rows = []
    for gid, real_r in real.items():
        sim_r = sim["rulings"].get(gid)
        if sim_r is None:
            sim_r = {"corrective_action": "corrective_action", "withdrawn": "withdrawn",
                     "not_filed": "not_filed"}.get(sim["outcome"], "dropped")
        rows.append({"id": gid, "actual": real_r, "sim": sim_r,
                     "match": sim_r == real_r if sim_r in ("sustained", "denied", "dismissed") else None,
                     "sustain_match": (sim_r == "sustained") == (real_r == "sustained")
                                      if sim_r in ("sustained", "denied", "dismissed") else None,
                     "p_counsel_t1": c1.get(gid), "p_counsel_t3": _p(c3.get(gid)), "p_agency": _p(ag.get(gid)),
                     "gao_confidence": _p(conf.get(gid)), "p_single": _p(single.get(gid))})
    out["per_ground"] = rows
    ruled = [r for r in rows if r["match"] is not None]
    out["grounds_ruled"] = len(ruled)
    out["grounds_exact_match"] = sum(r["match"] for r in ruled)
    out["grounds_sustain_match"] = sum(r["sustain_match"] for r in ruled)
    return out


def save(log: dict, path):
    with open(path, "w") as f:
        json.dump(log, f, indent=2)
