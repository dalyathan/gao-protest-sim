"""Scorecards (GAME_DESIGN.md section 4), computed by the observer only.

All money in USD. `p` is the packet's parameter dict.

Timeline assumed (days from filing): GAO decides by ~day 100 (stay_days_expected).
Corrective action at turn 2 ends the protest around day 5; a withdrawal at turn 3
around day 40. Corrective action, and implementing a sustain, both require a
re-evaluation of corrective_action_days, so a sustain costs the agency the stay
*plus* the re-evaluation, while early corrective action costs only the latter.
"""

T2_DAYS, T3_DAYS = 5, 40


def protester_payoff(p: dict, filed: bool, path: str, relief: bool, sustained: bool,
                     incumbent: bool | None = None, costs_reimbursed: bool | None = None) -> float:
    """path: 'early' (ended by corrective action/withdrawal) | 'full' (to decision)."""
    if not filed:
        return 0.0
    incumbent = p.get("incumbent", 0) if incumbent is None else incumbent
    costs_reimbursed = sustained if costs_reimbursed is None else costs_reimbursed
    legal = {"early": p.get("legal_cost_early", 60000), "full": p.get("protester_legal_cost", 250000)}[path]
    stay_days = 35 if path == "early" else p.get("stay_days_expected", 100)
    value = 0.0
    if relief:
        value += p.get("P_win_recompete", 0.27) * p["V_contract_per_seat"] * p.get("profit_margin", 0.10)
    if incumbent:
        value += stay_days * p.get("incumbent_daily_margin", 5000)
    if costs_reimbursed:
        legal = 0.0  # GAO recommended reimbursement of protest costs
    return value - legal - p.get("relationship_cost", 40000)


def agency_payoff(p: dict, filed: bool, took_ca: bool, ca_turn: int | None, sustained: bool,
                  withdrawn: bool = False, costs_reimbursed: bool | None = None) -> float:
    if not filed:
        return 0.0
    d = p["agency_delay_cost_per_day"]
    re_eval = p.get("corrective_action_days", 90)
    stay = p.get("stay_days_expected", 100)
    if took_ca:
        days = (T2_DAYS if ca_turn == 2 else T3_DAYS) + re_eval
        late_penalty = 0 if ca_turn == 2 else p.get("cost_reimbursement", 250000) * 0.5
        return -(d * days + p["corrective_action_cost"] + late_penalty)
    if withdrawn:
        return -(d * T3_DAYS)
    if not sustained:
        return -(d * stay)
    costs_reimbursed = True if costs_reimbursed is None else costs_reimbursed
    return -(d * (stay + re_eval) + p["agency_public_loss"] + p["corrective_action_cost"]
             + (p["cost_reimbursement"] if costs_reimbursed else 0))
