"""Single-agent baseline: ONE call per case, no game.

The agent is given exactly what GAO sees at decision time (public documents, the
protected record, and the grounds actually filed) and predicts the ruling on each
ground. It answers the question "does the multi-agent game add anything over one
good prompt?" Logs use the same shape as Game logs so score() works unchanged.
"""
import time

from .agents import RULES
from .case import Case
from .game import IllegalMove, normalize_ruling, overall_from_rulings
from .llm import extract_json

ROLE = ("An experienced GAO bid-protest attorney predicting how GAO's Procurement Law Division will "
        "rule. Apply GAO's actual standards of review and give calibrated probabilities.")
TASK = ("For EACH ground listed, predict GAO's ruling (sustained|denied|dismissed) and the probability "
        "it is sustained, with a one-sentence reason. JSON keys: rulings{ground_id:ruling}, "
        "p_sustain{ground_id:p}")


def run_single(case: Case, llm, temperature=0.7) -> dict:
    grounds = case.extra.get("filed_grounds")
    if not grounds:
        raise SystemExit(f"{case.case_id}: single-agent mode needs `filed_grounds` in the packet")
    ids = [g["id"] for g in grounds]
    ctx = case.context_for("gao", 5, "realistic")
    user = (f"INFORMATION YOU CAN SEE:\n{ctx}\n\nGROUNDS FILED:\n"
            + "\n".join(f"{g['id']}: {g['name']}" for g in grounds) + f"\n\nTASK_TAG: SINGLE\n{TASK}")
    system = RULES + "\n\nROLE: " + ROLE
    u0 = dict(llm.usage)
    t0 = time.time()
    text = llm(system, user, temperature)

    def check(out):
        r = out.get("rulings") if isinstance(out.get("rulings"), dict) else {}
        bad = [g for g in ids if normalize_ruling(r.get(g)) is None]
        return f"give a ruling (sustained|denied|dismissed) for every id in {ids}; problem with {bad}" if bad else None
    try:
        out = extract_json(text)
        err = check(out)
    except ValueError:
        out, err = None, "no JSON block"
    if err:
        text += "\n\n[repair]\n" + llm(system, user + f"\n\nPROBLEM WITH YOUR ANSWER: {err}\n"
                                       "Reply with ONLY the corrected ```json``` block.", 0.0)
        out = extract_json(text)
        if check(out):
            raise IllegalMove(f"{case.case_id} single: {check(out)}")
    rulings = {g: normalize_ruling(out["rulings"][g]) for g in ids}
    ps = out.get("p_sustain") if isinstance(out.get("p_sustain"), dict) else {}
    overall = overall_from_rulings(rulings)
    return {"case_id": case.case_id, "mode": "single", "scenario": "single", "fixed_grounds": True,
            "turns": [{"turn": 5, "actor": "single", "task": "SINGLE", "json": out, "raw": text,
                       "secs": round(time.time() - t0, 1)}],
            "result": {"outcome": overall, "rulings": rulings, "payoffs": {}},
            "beliefs": {"single_p_sustain": ps},
            "usage": {k: llm.usage.get(k, 0) - u0.get(k, 0) for k in llm.usage}}
