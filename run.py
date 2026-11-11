#!/usr/bin/env python3
"""
GAO protest simulator CLI.

  # Play one case with Claude agents (or --mock for an offline test)
  python run.py play data/cases/b-424641_packet.yaml [--mock] [--scenario realistic]
        [--agency defend|corrective_action|llm|policy|benchmark] [--repeats 5] [--lessons]

  # Train the RL decision layer from belief profiles (no LLM calls)
  python run.py train [--episodes 50000]

  # Show what LLM, RL policy, and rational benchmark choose for each profile
  python run.py compare
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import yaml

from sim.benchmark import benchmark_choice
from sim.case import Case
from sim.game import Game, p_any, save, score
from sim.llm import make_llm
from sim.rl import Policy, ProtestEnv, state_key, train

ROOT = Path(__file__).parent
RUNS, PROFILES = ROOT / "runs", ROOT / "data" / "profiles"
POLICY = ROOT / "runs" / "rl_policy.json"


def profile_from_log(log):
    """Extract the belief profile the RL environment needs from a played game."""
    out = {}
    for t in log["turns"]:
        j = t.get("json", {})
        if t.get("task") == "COUNSEL_T1":
            out["counsel_p_relief_t1"] = j["p_relief"]
        elif t.get("task") == "AGENCY_T2":
            out["agency_p_sustain_any"] = round(p_any(j["p_sustain"]), 3)
        elif t.get("task") == "COUNSEL_T3":
            out["counsel_p_relief_t3"] = j["p_relief"]
    out.setdefault("counsel_p_relief_t3", out.get("counsel_p_relief_t1", 0.2))
    out["true_p_sustain"] = out.get("agency_p_sustain_any", 0.3)
    return out


def cmd_play(a):
    case = Case.load(a.case)
    llm = make_llm(a.mock)
    deciders = {"AGENCY_T2": a.agency, "COMPANY_T1": a.company, "COMPANY_T3": a.company}
    policy = Policy.load(POLICY) if "policy" in deciders.values() and POLICY.exists() else None
    memory = {}
    RUNS.mkdir(exist_ok=True)
    PROFILES.mkdir(parents=True, exist_ok=True)
    for r in range(a.repeats):
        log = Game(case, llm, a.scenario, deciders, policy, a.temperature, memory).run()
        log["score"] = score(log, case)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = RUNS / f"{case.case_id}_{a.scenario}_ag-{a.agency}_{stamp}_r{r}{'_mock' if a.mock else ''}.json"
        save(log, out)
        if not a.mock:  # mock beliefs are fake; don't let them train the policy
            prof = profile_from_log(log)
            (PROFILES / f"{case.case_id}.json").write_text(json.dumps(prof, indent=2))
        res = log["result"]
        print(f"[run {r}] outcome={res['outcome']}  payoffs={ {k: round(v) for k, v in res['payoffs'].items()} }")
        print(f"         score={log['score']}  calls={log['usage']['calls']}  -> {out.name}")
        if a.lessons:  # agents write notes for the next repeat (in-context learning)
            for actor in ("protester_counsel", "agency"):
                from sim.agents import TASKS, prompt
                summary = f"Outcome: {res['outcome']}. Your payoff: {res['payoffs'].get('agency' if actor == 'agency' else 'protester_co'):,.0f}"
                s, u = prompt(actor, "LESSONS", summary, case.params, TASKS["LESSONS"], memory.get(actor, ""))
                from sim.llm import extract_json
                notes = extract_json(llm(s, u, 0.3)).get("lessons", [])
                memory[actor] = (memory.get(actor, "") + "\n" + "\n".join(f"- {n}" for n in notes)).strip()


def load_envs():
    envs = []
    for f in sorted(PROFILES.glob("*.json")):
        prof = json.loads(f.read_text())
        stem = prof.get("params_from", f.stem).lower()
        case_file = ROOT / "data" / "cases" / f"{stem}_packet.yaml"
        params = yaml.safe_load(case_file.read_text())["parameters"]
        envs.append((f.stem, params, prof))
    if not envs:
        raise SystemExit("No profiles in data/profiles/. Run `play` first.")
    return envs


def cmd_train(a):
    envs = load_envs()
    pol, curve = train([ProtestEnv(p, prof) for _, p, prof in envs], episodes=a.episodes)
    pol.save(POLICY)
    print("Learning curve (outcome mix per window):")
    for row in curve:
        print("  ", row)
    print(f"\nLearned policy -> {POLICY}")
    for tag, rows in pol.table().items():
        print(f"\n{tag}")
        for k, row in rows.items():
            print(f"   {k:<12} best={row['best']:<18} q={row['q']}")


def cmd_compare(a):
    pol = Policy.load(POLICY) if POLICY.exists() else None
    for cid, p, prof in load_envs():
        print(f"\n== {cid} ==")
        for inc in (0, 1):
            for delay in (1000, 10000, 40000):
                states = {
                    "COMPANY_T1": {"p_relief": prof["counsel_p_relief_t1"], "incumbent": inc},
                    "AGENCY_T2": {"p_sustain_any": prof["agency_p_sustain_any"], "delay_cost": delay},
                    "COMPANY_T3": {"p_relief": prof["counsel_p_relief_t3"], "incumbent": inc},
                }
                pp = {**p, "incumbent": inc, "agency_delay_cost_per_day": delay}
                row = []
                for tag, s in states.items():
                    bench = benchmark_choice(tag, s, pp)
                    rl = pol.act(tag, s, explore=False) if pol else "-"
                    row.append(f"{tag}: bench={bench} rl={rl}")
                print(f" incumbent={inc} delay=${delay:>6}/day | " + " | ".join(row))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("play")
    pl.add_argument("case")
    pl.add_argument("--mock", action="store_true")
    pl.add_argument("--scenario", default="realistic", choices=["realistic", "full_transparency", "no_apo_access"])
    pl.add_argument("--agency", default="llm")
    pl.add_argument("--company", default="llm")
    pl.add_argument("--repeats", type=int, default=1)
    pl.add_argument("--temperature", type=float, default=0.7)
    pl.add_argument("--lessons", action="store_true", help="agents write lessons between repeats")
    tr = sub.add_parser("train")
    tr.add_argument("--episodes", type=int, default=50000)
    sub.add_parser("compare")
    a = ap.parse_args()
    {"play": cmd_play, "train": cmd_train, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
