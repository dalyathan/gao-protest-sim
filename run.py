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


def load_dotenv(path=Path(__file__).parent / ".env"):
    """Load KEY=VALUE lines from .env (git-ignored) into the environment."""
    import os
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_dotenv()

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
        if t.get("task") == "COUNSEL_T1" and j.get("p_relief") is not None:
            out["counsel_p_relief_t1"] = float(j["p_relief"])
        elif t.get("task") == "AGENCY_T2" and isinstance(j.get("p_sustain"), dict):
            out["agency_p_sustain_any"] = round(p_any(j["p_sustain"]), 3)
        elif t.get("task") == "COUNSEL_T3" and j.get("p_relief") is not None:
            out["counsel_p_relief_t3"] = float(j["p_relief"])
    out.setdefault("counsel_p_relief_t3", out.get("counsel_p_relief_t1", 0.2))
    if "agency_p_sustain_any" in out:  # absent when the company never filed
        out["true_p_sustain"] = out["agency_p_sustain_any"]
    return out


def model_tag():
    import os
    if os.environ.get("SIM_BACKEND", "").lower() == "cli":
        return "cli-" + os.environ.get("SIM_CLI_MODEL", "sonnet")
    return os.environ.get("SIM_MODEL", "claude-sonnet-5-5")


def cmd_play(a):
    case = Case.load(a.case)
    llm = make_llm(a.mock)
    deciders = {"AGENCY_T2": a.agency, "COMPANY_T1": a.company, "COMPANY_T3": a.company}
    if a.real_path:  # condition on the path published cases actually took, to test the merits
        deciders = {"COMPANY_T1": "file", "AGENCY_T2": "defend", "COMPANY_T3": "continue"}
    fixed = a.fixed_grounds or (a.real_path and bool(case.extra.get("filed_grounds")))
    policy = Policy.load(POLICY) if "policy" in deciders.values() and POLICY.exists() else None
    memory = {}
    RUNS.mkdir(exist_ok=True)
    PROFILES.mkdir(parents=True, exist_ok=True)
    # Everything that changes the game goes into the name, so --resume never mixes conditions.
    dec = "realpath" if a.real_path else f"ag-{a.agency}_co-{a.company}"
    mt = "mock" if a.mock else model_tag()
    tag = f"{case.case_id}_{a.scenario}_{dec}{'_fixed' if fixed else ''}_{mt}_t{a.temperature}"
    if a.mock:
        print("NOTE: mock agents give canned answers; their scores are NOT meaningful.")
    for r in range(a.repeats):
        if a.resume and not a.lessons and list(RUNS.glob(f"{tag}_*_r{r}.json")):
            print(f"[run {r}] already done, skipping (use --no-resume to redo)")
            continue
        log = Game(case, llm, a.scenario, deciders, policy, a.temperature, memory, fixed_grounds=fixed).run()
        log["model"] = mt
        log["score"] = score(log, case)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = RUNS / f"{tag}_{stamp}_r{r}.json"
        save(log, out)
        # RL profiles: only realistic, unforced LLM games, averaged over all such games of the case.
        if not a.mock and a.scenario == "realistic" and set(deciders.values()) == {"llm"}:
            update_profile(case.case_id, profile_from_log(log))
        res = log["result"]
        sc = log["score"]
        g = f"  grounds {sc.get('grounds_exact_match')}/{sc.get('grounds_ruled')}" if "grounds_ruled" in sc else ""
        print(f"[run {r}] outcome={res['outcome']} (real: {sc.get('actual_outcome')})  "
              f"payoffs={ {k: round(v) for k, v in res['payoffs'].items()} }{g}")
        print(f"         calls={log['usage'].get('calls')}  -> {out.name}")
        if a.lessons:  # agents write notes for the next repeat (in-context learning)
            for actor in ("protester_counsel", "agency"):
                from sim.agents import TASKS, prompt
                summary = f"Outcome: {res['outcome']}. Your payoff: {res['payoffs'].get('agency' if actor == 'agency' else 'protester_co'):,.0f}"
                s, u = prompt(actor, "LESSONS", summary, case.params, TASKS["LESSONS"], memory.get(actor, ""))
                from sim.llm import extract_json
                notes = extract_json(llm(s, u, 0.3)).get("lessons", [])
                memory[actor] = (memory.get(actor, "") + "\n" + "\n".join(f"- {n}" for n in notes)).strip()


def update_profile(case_id, prof):
    """Running mean of belief profiles across games of one case (missing keys skipped)."""
    path = PROFILES / f"{case_id}.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    n = old.get("n_games", 0)
    merged = {"n_games": n + 1}
    for k in set(old) | set(prof):
        if k == "n_games":
            continue
        a, b = old.get(k), prof.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            merged[k] = round((a * n + b) / (n + 1), 4)
        else:
            merged[k] = b if b is not None else a
    path.write_text(json.dumps(merged, indent=2))


def load_envs():
    envs = []
    for f in sorted(PROFILES.glob("*.json")):
        prof = json.loads(f.read_text())
        stem = prof.get("params_from", f.stem).lower()
        case_file = ROOT / "data" / "cases" / f"{stem}_packet.yaml"
        need = ("counsel_p_relief_t1", "agency_p_sustain_any", "counsel_p_relief_t3", "true_p_sustain")
        if not case_file.exists() or any(k not in prof for k in need):
            print(f"skipping profile {f.name}: incomplete (no filed game yet) or no packet")
            continue
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
    pl.add_argument("--no-resume", dest="resume", action="store_false",
                    help="re-run repeats that already have a log in runs/ (default: skip them)")
    pl.add_argument("--real-path", action="store_true",
                    help="force file/defend/continue (the path every published decision took) to test merits; "
                         "uses the packet's filed_grounds when present")
    pl.add_argument("--fixed-grounds", action="store_true",
                    help="counsel argues exactly the packet's filed_grounds (needed for per-ground scoring)")
    tr = sub.add_parser("train")
    tr.add_argument("--episodes", type=int, default=50000)
    sub.add_parser("compare")
    a = ap.parse_args()
    {"play": cmd_play, "train": cmd_train, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
