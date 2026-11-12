#!/usr/bin/env python3
"""Convert data/extracted/*.json (facts + outcome) into case packets and
observer-only outcome files. Outcomes go ONLY to *_observer_only.yaml."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC, DST = ROOT / "data" / "extracted", ROOT / "data" / "cases"
CUTOFF = "2026-07-01"  # decisions before this may be in model training data
DEFAULTS = {"profit_margin": 0.10, "P_win_recompete": 0.3, "incumbent_daily_margin": 5000,
            "stay_days_expected": 100, "protester_legal_cost": 250000, "legal_cost_early": 60000,
            "relationship_cost": 40000, "agency_delay_cost_per_day": 10000, "agency_public_loss": 300000,
            "cost_reimbursement": 250000, "corrective_action_cost": 100000}


def money(s):
    nums = [float(x.replace(",", "")) for x in re.findall(r"\$([\d,]{6,})", s or "")]
    return max(nums) if nums else 20_000_000


def main():
    DST.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(SRC.glob("*.json")):
        d = json.loads(f.read_text())
        fa, out = d["facts"], d["outcome"]
        if fa.get("is_reconsideration"):
            continue
        cid = fa["b_numbers"][0] if fa["b_numbers"] else f.stem.upper()
        grounds = "\n".join(f"{g['id']}: {g['claim']}" for g in fa["protester_grounds"])
        summary = (f"Agency: {fa['agency']}\nSolicitation: {fa['solicitation']}\nType: {fa['procurement_type']}\n"
                   f"Value: {fa.get('est_value')}\nEvaluation: {fa.get('evaluation_scheme')}\n"
                   f"Offerors: {fa.get('n_offerors')}\nProtest type: {fa.get('protest_type')}\n\n{fa['background']}")
        n_off = fa.get("n_offerors") or 4
        packet = {
            "case_id": cid,
            "documents": [
                {"id": "solicitation_and_background", "tag": "public", "text": summary},
                {"id": "protester_view", "tag": "debrief", "text":
                    f"Protester: {fa['protester']} (incumbent: {fa.get('protester_is_incumbent')}). "
                    f"Awardee: {fa.get('awardee')}. Issues the protester has identified:\n{grounds}"},
                {"id": "agency_internal", "tag": "agency_internal", "text":
                    f"Agency's view of its record: {fa['agency_position']}\n{fa['record_facts_protected']}"},
                {"id": "agency_report", "tag": "apo", "available_from_turn": 2, "text":
                    f"Agency report (protected record): {fa['record_facts_protected']}\n"
                    f"Agency arguments: {fa['agency_position']}"},
            ],
            "parameters": {**DEFAULTS, "V_contract_per_seat": money(fa.get("est_value")),
                           "incumbent": 1 if fa.get("protester_is_incumbent") else 0,
                           "P_win_recompete": round(min(0.6, 1 / max(2, n_off - 1)), 2)},
            "meta": {"title": fa["title"], "intervenor_present": fa.get("intervenor_present"),
                     "protest_type": fa.get("protest_type"), "source": "extracted via web-reading tool",
                     "pre_cutoff": (out.get("decision_date") or "9999") < CUTOFF},
        }
        stem = cid.lower()
        (DST / f"{stem}_packet.yaml").write_text(yaml.safe_dump(packet, sort_keys=False, width=110))
        (DST / f"{stem}_observer_only.yaml").write_text(yaml.safe_dump(
            {"case_id": cid, "actual": {**out, "outcome": out["overall"], "grounds": out.get("rulings", {}),
                                        "corrective_action": out.get("corrective_action_taken_during_protest")}},
            sort_keys=False))
        n += 1
        print(f"{cid:<14} {out['overall']:<34} pre_cutoff={packet['meta']['pre_cutoff']}  {fa['title'][:45]}")
    print(f"{n} packets -> {DST}")


if __name__ == "__main__":
    main()
