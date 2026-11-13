#!/usr/bin/env python3
"""Turn the frozen merits test set into playable case packets, using Haiku 5.5
through Claude Code (`claude -p --model haiku`, your subscription).

Two separate calls per case, so the case file can never see the outcome:
  1. FACTS call   - reads ONLY data/test_facts/<case>.txt (intro minus outcome sentences
                    + background) and writes the packet: who could see what, and the
                    grounds actually filed (g1, g2, ...).
  2. ANSWER call  - reads the grounds from call 1 plus data/test_answers/<case>.json
                    (GAO's digest and discussion) and maps GAO's ruling onto each id.
                    Output goes ONLY to <case>_observer_only.yaml.
Then every packet is scanned for outcome language; flagged ones are listed for a human.

Usage (from the project folder, with Claude Code installed and logged in):
  python scripts/build_test_packets.py               # all cases, 3 at a time, resumes
  python scripts/build_test_packets.py --limit 3     # try a few first
  python scripts/build_test_packets.py --mock        # offline plumbing test
Env: BUILD_MODEL (default haiku), JOBS (default 3).
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sim.game import normalize_ruling, overall_from_rulings  # noqa: E402
from sim.llm import ClaudeCLI, extract_json  # noqa: E402

FACTS, ANSWERS, OUT = ROOT / "data" / "test_facts", ROOT / "data" / "test_answers", ROOT / "data" / "cases_test"
DEFAULTS = {"profit_margin": 0.10, "incumbent_daily_margin": 5000, "stay_days_expected": 100,
            "relationship_cost": 40000, "agency_delay_cost_per_day": 10000, "agency_public_loss": 300000,
            "cost_reimbursement": 250000, "corrective_action_cost": 250000, "corrective_action_days": 90}
LEAK = re.compile(r"\b(we (find|conclude|agree|disagree|deny|sustain|dismiss)|gao (found|held|sustained|denied|"
                  r"dismissed)|protest (is|was) (denied|sustained|dismissed)|our (decision|office) (found|held))\b", re.I)

SYS_FACTS = ("You convert a GAO bid-protest record into a case file for a simulation. Use ONLY facts stated in the "
             "text. Never say or hint whether any argument is right, whether GAO agreed, or how the protest ended; "
             "drop any sentence that does. Write in neutral, factual language. START with a ```json``` block.")
TASK_FACTS = """From the text below, produce JSON with these keys:
- protester, awardee (or null), agency, solicitation, protest_type ("pre-award"|"post-award"|"other"),
  est_value_usd (number or null), n_offerors (number or null), protester_is_incumbent (true|false|null)
- public: what any bidder knew from the solicitation and the award notice (requirements, evaluation scheme, award).
- debrief: what the protester itself learned about its own and the awardee's evaluation (ratings, weaknesses, prices)
  before protesting. Empty string if not stated.
- protester_private: facts only the protester knew (its own situation, incumbency). Empty string if none.
- agency_internal: facts in the agency's own files that bidders did not see (evaluator notes, internal reasoning,
  documents in the record). Facts only, no judgement of whether they were proper.
- protected_record: further details of the evaluation record that would be released under a protective order.
- grounds: the protester's distinct arguments as filed, [{id: "g1", name: "The protester contends ..."}, ...].
  One entry per distinct argument, in the order the text gives them; keep each under 40 words.
TEXT:
"""
SYS_ANS = ("You read a GAO decision and record how GAO ruled on each listed ground. Be exact. "
           "START with a ```json``` block.")
TASK_ANS = """Grounds (use exactly these ids):
{grounds}

For each id give GAO's ruling: "sustained", "denied", or "dismissed" (use "dismissed" also for grounds GAO found
untimely, academic, abandoned or withdrawn). If several ids were decided together, give each the same ruling.
Also give: corrective_action_during_protest (true if the agency took corrective action on any ground during the
protest), costs_recommended (true|false).
JSON keys: rulings{{id: ruling}}, corrective_action_during_protest, costs_recommended
GAO DECISION (digest, outcome sentences, discussion, recommendation):
{answer}"""


class MockBuild:
    usage = {"calls": 0}

    def __call__(self, system, user, temperature=0):
        if user.startswith("Grounds (use"):
            ids = re.findall(r"^(g\d+):", user, re.M)
            return "```json\n" + json.dumps({"rulings": {g: "denied" for g in ids},
                                             "corrective_action_during_protest": False,
                                             "costs_recommended": False}) + "\n```"
        return "```json\n" + json.dumps({
            "protester": "P", "awardee": "A", "agency": "X", "solicitation": "S", "protest_type": "post-award",
            "est_value_usd": 1e7, "n_offerors": 3, "protester_is_incumbent": False, "public": "pub",
            "debrief": "deb", "protester_private": "", "agency_internal": "int", "protected_record": "rec",
            "grounds": [{"id": "g1", "name": "The protester contends A."}, {"id": "g2", "name": "The protester contends B."}]}) + "\n```"


def ask(llm, system, user, check):
    text = llm(system, user, 0.0)
    try:
        out = extract_json(text)
        err = check(out)
    except ValueError:
        out, err = None, "no JSON block"
    if err:
        out = extract_json(llm(system, user + f"\n\nPROBLEM: {err}. Reply with ONLY the corrected ```json``` block.", 0.0))
        err = check(out)
        if err:
            raise ValueError(err)
    return out


def build(stem, llm):
    pk, ob = OUT / f"{stem}_packet.yaml", OUT / f"{stem}_observer_only.yaml"
    if pk.exists() and ob.exists():
        return stem, "exists", []
    facts = (FACTS / f"{stem}.txt").read_text()

    def chk_facts(o):
        g = o.get("grounds")
        if not isinstance(g, list) or not g or not all(isinstance(x, dict) and x.get("id") and x.get("name") for x in g):
            return "'grounds' must be a non-empty list of {id, name}"
    f = ask(llm, SYS_FACTS, TASK_FACTS + facts, chk_facts)
    grounds = [{"id": f"g{i}", "name": str(g["name"]).strip()} for i, g in enumerate(f["grounds"], 1)]
    ids = [g["id"] for g in grounds]
    val = f.get("est_value_usd") or 20_000_000
    try:
        val = float(val)
    except (TypeError, ValueError):
        val = 20_000_000
    n_off = f.get("n_offerors") if isinstance(f.get("n_offerors"), (int, float)) and f.get("n_offerors") else 4
    head = (f"Agency: {f.get('agency')}\nSolicitation: {f.get('solicitation')}\nProtester: {f.get('protester')}\n"
            f"Awardee: {f.get('awardee')}\nProtest type: {f.get('protest_type')}\n\n")
    docs = [{"id": "solicitation_and_award", "tag": "public", "text": head + str(f.get("public", ""))}]
    for key, tag, turn in (("debrief", "debrief", None), ("protester_private", "private_protester", None),
                           ("agency_internal", "agency_internal", None), ("protected_record", "apo", 2)):
        txt = str(f.get(key) or "").strip()
        if txt:
            d = {"id": key, "tag": tag, "text": txt}
            if turn:
                d["available_from_turn"] = turn
            docs.append(d)
    packet = {"case_id": "B-" + re.match(r"b_([\d.]+)", stem).group(1).rstrip("."), "documents": docs, "filed_grounds": grounds,
              "parameters": {**DEFAULTS, "V_contract_per_seat": val,
                             "protester_legal_cost": int(min(250000, max(25000, 0.005 * val))),
                             "legal_cost_early": int(min(60000, max(10000, 0.0015 * val))),
                             "incumbent": 1 if f.get("protester_is_incumbent") else 0,
                             "P_win_recompete": round(min(0.6, 1 / max(2, n_off - 1)), 2)},
              "meta": {"source": "GAO decision PDF, facts-only split, built by " + os.environ.get("BUILD_MODEL", "haiku"),
                       "test_set": "merits_test_set v1", "stem": stem}}
    leaks = sorted({m.group(0) for d in docs for m in LEAK.finditer(d["text"])}
                   | {m.group(0) for g in grounds for m in LEAK.finditer(g["name"])})

    ans = json.loads((ANSWERS / f"{stem}.json").read_text())
    ans_txt = "\n\n".join(x for x in [ans.get("digest", ""), " ".join(ans.get("outcome_sentences", [])),
                                      ans.get("discussion", ""), ans.get("recommendation", "")] if x)[:60000]

    def chk_ans(o):
        r = o.get("rulings") if isinstance(o.get("rulings"), dict) else {}
        bad = [i for i in ids if normalize_ruling(r.get(i)) is None]
        return f"give sustained|denied|dismissed for every id in {ids}; problem with {bad}" if bad else None
    a = ask(llm, SYS_ANS, TASK_ANS.format(grounds="\n".join(f"{g['id']}: {g['name']}" for g in grounds),
                                          answer=ans_txt), chk_ans)
    rulings = {i: normalize_ruling(a["rulings"][i]) for i in ids}
    observer = {"case_id": packet["case_id"], "actual": {
        "decision_date": ans.get("date"), "outcome": overall_from_rulings(rulings), "grounds": rulings,
        "corrective_action": bool(a.get("corrective_action_during_protest")),
        "costs_recommended": bool(a.get("costs_recommended"))}}
    OUT.mkdir(parents=True, exist_ok=True)
    pk.write_text(yaml.safe_dump(packet, sort_keys=False, width=110, allow_unicode=True))
    ob.write_text("# OBSERVER ONLY - never shown to agents.\n" + yaml.safe_dump(observer, sort_keys=False))
    return stem, "built", leaks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    ts = json.loads((ROOT / "data" / "test_set_v1.json").read_text())
    stems = [re.sub(r"[^a-z0-9.]+", "_", b.lower()).strip("_") for b in ts["merits_test_set"]["cases"]]
    stems = stems[: a.limit] if a.limit else stems
    llm = MockBuild() if a.mock else ClaudeCLI(model=os.environ.get("BUILD_MODEL", "haiku"))
    if a.mock:
        global OUT
        OUT = Path("/tmp/cases_test_mock")
    flagged, failed = [], []
    with ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", 3))) as ex:
        futs = {ex.submit(build, s, llm): s for s in stems}
        for fu in futs:
            s = futs[fu]
            try:
                stem, status, leaks = fu.result()
                print(f"{status:<7} {stem}" + (f"   CHECK: {leaks}" if leaks else ""), flush=True)
                if leaks:
                    flagged.append(stem)
            except Exception as e:
                failed.append(s)
                print(f"FAILED  {s}: {str(e)[:160]}", flush=True)
    print(f"\nDone: {len(stems) - len(failed)} ok, {len(failed)} failed (re-run to retry), "
          f"{len(flagged)} flagged for a human look: {flagged}")
    print(f"Packets in {OUT}/  (dev cases stay in data/cases/)")


if __name__ == "__main__":
    main()
