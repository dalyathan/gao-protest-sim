"""Scorecards (GAME_DESIGN.md section 4), computed by the observer only.

All money in USD. `p` is the packet's parameter dict.
"""


def protester_payoff(p: dict, filed: bool, path: str, relief: bool, sustained: bool,
                     incumbent: bool | None = None) -> float:
    """path: 'none' | 'early' (ended by corrective action/withdrawal at ~turn 2-3) | 'full' (to decision)."""
    if not filed:
        return 0.0
    incumbent = p.get("incumbent", 0) if incumbent is None else incumbent
    legal = {"early": p.get("legal_cost_early", 60000), "full": p.get("protester_legal_cost", 250000)}[path]
    stay_days = 35 if path == "early" else p.get("stay_days_expected", 100)
    value = 0.0
    if relief:
        value += p.get("P_win_recompete", 0.27) * p["V_contract_per_seat"] * p.get("profit_margin", 0.10)
    if incumbent:
        value += stay_days * p.get("incumbent_daily_margin", 5000)
    if sustained:
        legal = 0.0  # GAO recommends reimbursement of protest costs
    return value - legal - p.get("relationship_cost", 40000)


def agency_payoff(p: dict, filed: bool, took_ca: bool, ca_turn: int | None, sustained: bool) -> float:
    if not filed:
        return 0.0
    if took_ca:
        days = 5 + 30 if ca_turn == 2 else 70 + 30  # early CA vs late CA (+30 days re-evaluation)
        late_penalty = 0 if ca_turn == 2 else p.get("cost_reimbursement", 250000) * 0.5
        return -(p["agency_delay_cost_per_day"] * days + p["corrective_action_cost"] + late_penalty)
    days = p.get("stay_days_expected", 100) - 30 + (30 if sustained else 0)
    loss = p["agency_delay_cost_per_day"] * days
    if sustained:
        loss += p["agency_public_loss"] + p["cost_reimbursement"] + p["corrective_action_cost"]
    return -loss
