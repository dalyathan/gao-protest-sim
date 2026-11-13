#!/usr/bin/env python3
"""Aggregate real (non-mock) game logs in runs/ and score them against actual outcomes."""
import glob, json, collections, sys
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sim.game import p_any

ROOT = Path(__file__).resolve().parent.parent
WIN = {"sustained", "sustained_in_part", "corrective_action"}
rows = []
for f in sorted(glob.glob(str(ROOT / "runs" / "B-*.json"))):
    if "_mock" in f:
        continue
    L = json.load(open(f))
    cid = L["case_id"]
    obs = ROOT / "data" / "cases" / f"{cid.lower()}_observer_only.yaml"
    actual = yaml.safe_load(obs.read_text())["actual"] if obs.exists() else {}
    t = {x.get("task"): x.get("json", {}) for x in L["turns"] if "task" in x}
    dec = {x["decision"]: x["choice"] for x in L["turns"] if "decision" in x}
    a_ps = t.get("AGENCY_T2", {}).get("p_sustain", {})
    rows.append({
        "case": cid, "file": Path(f).name, "sim": L["result"]["outcome"], "actual": actual.get("outcome"),
        "actual_won": actual.get("outcome") in WIN or bool(actual.get("corrective_action")),
        "sim_won": L["result"]["outcome"] in WIN,
        "filed": dec.get("COMPANY_T1"), "agency": dec.get("AGENCY_T2"),
        "counsel_p1": t.get("COUNSEL_T1", {}).get("p_relief"),
        "agency_p": round(p_any(a_ps), 2) if a_ps else None,
        "rulings": L["result"].get("rulings", {}), "actual_rulings": actual.get("grounds", {}),
        "per_ground": (L.get("score") or {}).get("per_ground"),
        "tokens": L["usage"]["input_tokens"] + L["usage"]["output_tokens"],
        "agency_reason": next((x.get("raw", "") for x in L["turns"] if x.get("task") == "AGENCY_T2"), ""),
    })

print(f"{len(rows)} real games\n")
by = collections.defaultdict(list)
for r in rows: by[r["case"]].append(r)
print(f"{'case':<13}{'actual':<34}{'sim outcomes':<55}{'counsel p':<11}{'agency p'}")
for c, rs in sorted(by.items()):
    print(f"{c:<13}{str(rs[0]['actual']):<34}{', '.join(r['sim'] for r in rs):<55}"
          f"{','.join(str(r['counsel_p1']) for r in rs):<11}{','.join(str(r['agency_p']) for r in rs)}")

n = len(rows)
filed = [r for r in rows if r["filed"] == "file"]
ca = [r for r in filed if r["agency"] == "corrective_action"]
decided = [r for r in rows if r["rulings"]]
won_match = sum(r["sim_won"] == r["actual_won"] for r in rows)
print(f"\nProtester filed:            {len(filed)}/{n}  (real: {n}/{n} filed)")
print(f"Agency backed down (CA):    {len(ca)}/{len(filed)} filed games  (real published cases: agency defended in all but partial CA in B-424708)")
print(f"'Protester won anything':   {won_match}/{n} match reality")
# Per-ground agreement is only meaningful for games played with the real filed grounds
# (--fixed-grounds / --real-path); free-play grounds are counsel's own and are not compared.
pg = [g for r in rows if isinstance(r["per_ground"], list) for g in r["per_ground"] if g["match"] is not None]
print(f"Games reaching GAO ruling:  {len(decided)}/{n}")
if pg:
    print(f"Per-ground (fixed grounds): exact {sum(g['match'] for g in pg)}/{len(pg)};  "
          f"sustain-vs-not {sum(g['sustain_match'] for g in pg)}/{len(pg)};  "
          f"real sustains caught {sum(g['sim']=='sustained' for g in pg if g['actual']=='sustained')}/"
          f"{sum(g['actual']=='sustained' for g in pg)}")
else:
    print("Per-ground: no fixed-grounds games yet (free-play grounds are not comparable)")
print(f"Tokens: {sum(r['tokens'] for r in rows):,} total, ~{sum(r['tokens'] for r in rows)//max(n,1):,}/game")

print("\nWhy agencies backed down (first 2 examples):")
for r in ca[:2]:
    txt = r["agency_reason"]; i = txt.find("```", txt.find("```") + 3)
    print(f"--- {r['case']}: {txt[i+3:i+600].strip()}\n")
