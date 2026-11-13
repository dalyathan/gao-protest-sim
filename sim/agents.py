"""Prompt templates. Every prompt is built only from (a) the actor's role and
scorecard, (b) documents its visibility allows, and (c) messages the rules let
it receive. The orchestrator never adds anything else.
"""

RULES = ("You are playing ONE role in a simulation of a GAO bid protest. Reason only from the "
         "information given. Do not invent facts or case citations; you may rely on general GAO "
         "principles you are confident about, labelled as such. START your answer with a ```json``` "
         "block exactly matching the requested keys, then give your reasoning in under 250 words.")

ROLES = {
    "protester_counsel": "Outside counsel for the protester, an experienced GAO protest lawyer. "
        "Scorecard: client's payoff + 0.3 x your credibility with GAO (penalized for weak or "
        "unsupported grounds). You may not reveal protected (apo) record details to the client.",
    "protester_co": "Business leadership of the protester. You decide whether to authorize and fund "
        "the protest. You never see the protected record; you rely on counsel's non-specific advice.",
    "agency": "Contracting officer and agency counsel for the procuring agency. You decide whether to "
        "defend the evaluation or take corrective action.",
    "gao": "GAO Office of General Counsel attorney deciding the protest. You are not self-interested; "
        "your job is a correct, precedent-consistent decision on each ground.",
}


def scorecard_text(actor: str, p: dict) -> str:
    if actor == "protester_co":
        inc = "You ARE the incumbent: you keep earning ~${:,}/day while the automatic stay lasts.".format(
            p.get("incumbent_daily_margin", 5000)) if p.get("incumbent") else \
            "You are NOT the incumbent; delay earns you nothing."
        return (f"SCORECARD: U = P(relief) x P(win after re-evaluation, ~{p.get('P_win_recompete', 0.27)}) x "
                f"${p['V_contract_per_seat']:,} x profit margin {p.get('profit_margin', 0.10)} "
                f"- legal cost (~${p.get('legal_cost_early', 60000):,} if it ends early, "
                f"~${p.get('protester_legal_cost', 250000):,} to a decision; reimbursed if sustained) "
                f"- relationship cost (~${p.get('relationship_cost', 40000):,}). {inc}")
    if actor == "agency":
        return (f"SCORECARD (minimize loss): -${p['agency_delay_cost_per_day']:,}/day of delay "
                f"- P(sustain) x (${p['agency_public_loss']:,} reputational + ${p['cost_reimbursement']:,} "
                f"protester costs) - ${p['corrective_action_cost']:,} if you take corrective action. "
                f"Defending holds the procurement until GAO decides (~{p.get('stay_days_expected', 100)} days from filing); "
                f"if GAO sustains, you must ALSO re-evaluate (~{p.get('corrective_action_days', 90)} days). "
                f"Corrective action now ends the protest but the re-evaluation (~{p.get('corrective_action_days', 90)} "
                f"days) still delays the award. "
                "Late corrective action risks cost reimbursement for undue delay.")
    if actor == "protester_counsel":
        return "SCORECARD: your client's payoff, plus credibility with GAO (weight 0.3)."
    return ""


def prompt(actor: str, task_tag: str, context: str, p: dict, task: str, memory: str = "") -> tuple[str, str]:
    system = RULES + "\n\nROLE: " + ROLES[actor]
    user = (f"{scorecard_text(actor, p)}\n\n"
            + (f"YOUR NOTES FROM PAST CASES:\n{memory}\n\n" if memory else "")
            + f"INFORMATION YOU CAN SEE:\n{context}\n\nTASK_TAG: {task_tag}\n{task}")
    return system, user


TASKS = {
    "COUNSEL_T1": "Draft the protest grounds you would file. For each give id (g1, g2, ...), name, "
        "a 2-sentence argument, and p_sustain. Give overall p_relief (incl. corrective action) and advice to "
        "the client. JSON keys: grounds[{id,name,p_sustain}], p_relief, recommend_filing, client_advice",
    "COUNSEL_T1_FIXED": "For each filed ground give id (as listed), a 2-sentence assessment, and p_sustain. "
        "Give overall p_relief (incl. corrective action) and advice to the client. "
        "JSON keys: grounds[{id,p_sustain}], p_relief, recommend_filing, client_advice",
    "COMPANY_T1": "Decide FILE or DO_NOT_FILE and a budget cap. Show expected-value reasoning. "
        "JSON keys: decision ('file'|'do_not_file'), budget_cap_usd, my_p_relief",
    "AGENCY_T2": "Estimate p_sustain per ground and p_prejudice; compare expected loss of DEFEND vs "
        "CORRECTIVE_ACTION; decide. If defending, summarize your agency report arguments. "
        "JSON keys: decision ('defend'|'corrective_action'), p_sustain{ground_id:p}, p_prejudice, report_summary",
    "COUNSEL_T3": "You now see the protected record. Update p_sustain per ground; decide which grounds to "
        "keep or drop (keep/drop list ground ids) and any supplemental grounds the record supports; summarize comments "
        "to GAO; write a NON-SPECIFIC message to the client. JSON keys: keep[ids], drop[ids], "
        "supplemental[{id:'s1',name}], p_sustain{id:p}, p_relief, comments_summary, client_message",
    "COUNSEL_T3_NO_APO": "You were NOT admitted to the protective order: you have only the agency's public "
        "summary, not the protected record. Update p_sustain per ground; decide which grounds to keep or drop "
        "(list ids) and any supplemental grounds; summarize comments to GAO; write a message to the client. "
        "JSON keys: keep[ids], drop[ids], supplemental[{id:'s1',name}], p_sustain{id:p}, p_relief, "
        "comments_summary, client_message",
    "COMPANY_T3": "Decide CONTINUE or WITHDRAW. JSON keys: decision ('continue'|'withdraw')",
    "GAO_T5": "Rule on each remaining ground (sustained|denied|dismissed) with a short rationale and "
        "confidence; analyze prejudice; give overall outcome and whether costs are recommended. JSON keys: "
        "rulings{ground_id:ruling}, overall ('denied'|'sustained'|'sustained_in_part'|'dismissed'), "
        "costs_recommended, confidence{ground_id:p}",
    "LESSONS": "Given this case and your payoff, write up to 3 short, general lessons for future cases "
        "(no case-specific names). JSON keys: lessons[]",
}
