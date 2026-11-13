"""Rational benchmark: risk-neutral expected-value choice at each decision point
(GAME_DESIGN.md section 5). Used to measure how far LLM and RL choices deviate
from textbook rationality.

p_relief is counsel's TOTAL probability of relief (corrective action or sustain),
as the COUNSEL_T1 task defines it. `ca_share_of_relief` is the part of that relief
expected to arrive early, through corrective action (GAO statistics: most relief
comes that way); it never adds relief on top of p_relief.
"""
from .payoffs import agency_payoff, protester_payoff


def ev_agency(state: dict, p: dict) -> dict:
    ps = state["p_sustain_any"]
    pp = {**p, "agency_delay_cost_per_day": state.get("delay_cost", p["agency_delay_cost_per_day"])}
    defend = ps * agency_payoff(pp, True, False, None, True) + (1 - ps) * agency_payoff(pp, True, False, None, False)
    ca = agency_payoff(pp, True, True, 2, False)
    return {"defend": defend, "corrective_action": ca}


def ev_company_t1(state: dict, p: dict) -> dict:
    pr = min(max(float(state["p_relief"]), 0.0), 1.0)
    s = p.get("ca_share_of_relief", 0.6)
    inc = state.get("incumbent", 0)
    early_win = protester_payoff(p, True, "early", True, False, inc)
    full_win = protester_payoff(p, True, "full", True, True, inc)
    full_lose = protester_payoff(p, True, "full", False, False, inc)
    file = pr * (s * early_win + (1 - s) * full_win) + (1 - pr) * full_lose
    return {"file": file, "do_not_file": 0.0}


def ev_company_t3(state: dict, p: dict) -> dict:
    pr = min(max(float(state["p_relief"]), 0.0), 1.0)
    inc = state.get("incumbent", 0)
    cont = pr * protester_payoff(p, True, "full", True, True, inc) + \
        (1 - pr) * protester_payoff(p, True, "full", False, False, inc)
    withdraw = protester_payoff(p, True, "early", False, False, inc)
    return {"continue": cont, "withdraw": withdraw}


def benchmark_choice(tag: str, state: dict, p: dict) -> str:
    ev = {"AGENCY_T2": ev_agency, "COMPANY_T1": ev_company_t1, "COMPANY_T3": ev_company_t3}[tag](state, p)
    return max(ev, key=ev.get)
