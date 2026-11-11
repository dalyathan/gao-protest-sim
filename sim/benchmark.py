"""Rational benchmark: risk-neutral expected-value choice at each decision point
(GAME_DESIGN.md section 5). Used to measure how far LLM and RL choices deviate
from textbook rationality.
"""
from .payoffs import agency_payoff, protester_payoff


def ev_agency(state: dict, p: dict) -> dict:
    ps = state["p_sustain_any"]
    pp = {**p, "agency_delay_cost_per_day": state.get("delay_cost", p["agency_delay_cost_per_day"])}
    defend = ps * agency_payoff(pp, True, False, None, True) + (1 - ps) * agency_payoff(pp, True, False, None, False)
    ca = agency_payoff(pp, True, True, 2, False)
    return {"defend": defend, "corrective_action": ca}


def ev_company_t1(state: dict, p: dict, p_agency_ca: float = 0.3) -> dict:
    pr = state["p_relief"]
    inc = state.get("incumbent", 0)
    # Relief arrives early (CA) with prob p_agency_ca, otherwise via a sustain at decision.
    early = protester_payoff(p, True, "early", True, False, inc)
    win_full = protester_payoff(p, True, "full", True, True, inc)
    lose_full = protester_payoff(p, True, "full", False, False, inc)
    file = p_agency_ca * early + (1 - p_agency_ca) * (pr * win_full + (1 - pr) * lose_full)
    return {"file": file, "do_not_file": 0.0}


def ev_company_t3(state: dict, p: dict) -> dict:
    pr = state["p_relief"]
    inc = state.get("incumbent", 0)
    cont = pr * protester_payoff(p, True, "full", True, True, inc) + \
        (1 - pr) * protester_payoff(p, True, "full", False, False, inc)
    withdraw = protester_payoff(p, True, "early", False, False, inc)
    return {"continue": cont, "withdraw": withdraw}


def benchmark_choice(tag: str, state: dict, p: dict) -> str:
    ev = {"AGENCY_T2": ev_agency, "COMPANY_T1": ev_company_t1, "COMPANY_T3": ev_company_t3}[tag](state, p)
    return max(ev, key=ev.get)
