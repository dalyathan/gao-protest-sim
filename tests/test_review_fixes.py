"""Regression tests for the 2026-11-12 blind code review (docs/CODE_REVIEW_2026-11-12.md).
Run: python tests/test_review_fixes.py   (no API key needed)"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.benchmark import benchmark_choice, ev_company_t1
from sim.case import Case
from sim.game import Game, IllegalMove, normalize_move, overall_from_rulings, score
from sim.llm import MockLLM
from sim.payoffs import agency_payoff
from sim.rl import Policy

CASES = sorted((ROOT / "data" / "cases").glob("*_packet.yaml"))
C641 = Case.load(ROOT / "data" / "cases" / "b-424641_packet.yaml")


class Scripted(MockLLM):
    """Mock agents with per-task overrides."""
    def __init__(self, overrides=None, seq=None):
        super().__init__()
        self.overrides, self.seq = overrides or {}, seq or {}

    def __call__(self, system, user, temperature=0.7):
        text = super().__call__(system, user, temperature)
        tag = re.search(r"TASK_TAG:\s*(\w+)", user).group(1)
        if tag in self.seq and self.seq[tag]:
            o = self.seq[tag].pop(0)
        else:
            o = self.overrides.get(tag)
        if o is None:
            return text
        out = json.loads(text.split("```json\n")[1].split("\n```")[0])
        out.update(o)
        return "```json\n" + json.dumps(out) + "\n```"


def t_uppercase_and_synonyms():  # review #4
    assert normalize_move("FILE", "COMPANY_T1") == "file"
    assert normalize_move("Do Not File", "COMPANY_T1") == "do_not_file"
    assert normalize_move("CORRECTIVE_ACTION", "AGENCY_T2") == "corrective_action"
    assert normalize_move("maybe", "COMPANY_T1") is None
    log = Game(C641, Scripted({"COMPANY_T1": {"decision": "FILE"}, "COMPANY_T3": {"decision": "CONTINUE"},
                                "AGENCY_T2": {"decision": "DEFEND"}})).run()
    assert log["result"]["outcome"] not in ("not_filed", None)


def t_invalid_move_repaired_or_raised():
    llm = Scripted(seq={"COMPANY_T1": [{"decision": "perhaps"}, {"decision": "file"}]})
    Game(C641, llm).run()  # first answer invalid, repair answer valid
    try:
        Game(C641, Scripted({"COMPANY_T1": {"decision": "perhaps"}})).run()
        raise AssertionError("should have raised")
    except IllegalMove:
        pass


def t_overall_derived_from_rulings():  # review #4 (GAO overall not validated)
    assert overall_from_rulings({"a": "sustained", "b": "denied"}) == "sustained_in_part"
    assert overall_from_rulings({"a": "denied", "b": "dismissed"}) == "denied_in_part_dismissed_in_part"
    log = Game(C641, Scripted({"GAO_T5": {"overall": "denied in part"}, "AGENCY_T2": {"decision": "defend"}})).run()
    assert log["result"]["outcome"] in ("sustained_in_part", "denied", "sustained", "dismissed",
                                        "denied_in_part_dismissed_in_part")


def t_supplemental_grounds():  # review #3
    llm = Scripted({"AGENCY_T2": {"decision": "defend"},
                    "COUNSEL_T3": {"keep": [], "supplemental": [{"id": "s1", "name": "Unequal discussions"}]}})
    log = Game(C641, llm).run()
    assert "s1" in log["result"]["rulings"], log["result"]
    gao_prompt_seen = [t for t in log["turns"] if t.get("task") == "GAO_T5"]
    assert gao_prompt_seen
    llm2 = Scripted({"AGENCY_T2": {"decision": "defend"}, "COUNSEL_T3": {"supplemental": ["late-raised issue"]}})
    Game(C641, llm2).run()


def t_benchmark_not_always_file():  # review #1
    p = C641.params
    assert benchmark_choice("COMPANY_T1", {"p_relief": 0.0, "incumbent": 0}, p) == "do_not_file"
    assert ev_company_t1({"p_relief": 0.0, "incumbent": 0}, p)["file"] < 0
    assert benchmark_choice("COMPANY_T1", {"p_relief": 0.5, "incumbent": 0}, p) == "file"


def t_delay_cost_pushes_toward_corrective_action():  # review #2
    p = dict(C641.params)
    chose = {}
    for d in (1000, 10000, 20000, 40000):
        chose[d] = benchmark_choice("AGENCY_T2", {"p_sustain_any": 0.3, "delay_cost": d}, p)
    order = ["defend", "corrective_action"]
    assert [order.index(chose[d]) for d in sorted(chose)] == sorted(order.index(chose[d]) for d in chose), chose
    # higher delay cost never makes defending relatively cheaper
    gap = lambda d: (agency_payoff({**p, "agency_delay_cost_per_day": d}, True, True, 2, False)
                     - agency_payoff({**p, "agency_delay_cost_per_day": d}, True, False, None, False))
    assert gap(40000) >= gap(1000)


def t_usage_is_per_game():  # review #7
    llm = MockLLM()
    calls = [Game(C641, llm).run()["usage"]["calls"] for _ in range(3)]
    assert len(set(calls)) == 1, calls


def t_fixed_grounds_scoring():  # review #10
    for f in CASES:
        c = Case.load(f)
        log = Game(c, MockLLM(), deciders={"COMPANY_T1": "file", "AGENCY_T2": "defend", "COMPANY_T3": "continue"},
                   fixed_grounds=True).run()
        sc = score(log, c)
        ids = [g["id"] for g in c.extra["filed_grounds"]]
        assert [r["id"] for r in sc["per_ground"]] == ids, (f.name, sc)
        assert sc["grounds_ruled"] >= 1
        assert set(log["result"]["rulings"]) <= set(ids)
    free = Game(C641, MockLLM()).run()
    assert isinstance(score(free, C641).get("per_ground"), str)  # not comparable in free play


def t_policy_without_training():  # review #5
    try:
        Game(C641, MockLLM(), deciders={"AGENCY_T2": "policy"})
        raise AssertionError("should exit")
    except SystemExit:
        pass


def t_rl_never_prefers_untried():  # review #8
    pol = Policy(epsilon=0.0)
    s = {"p_sustain_any": 0.2, "delay_cost": 1000}
    pol.update("AGENCY_T2", s, "defend", -5.0)
    assert pol.act("AGENCY_T2", s, explore=False) == "defend"


def t_all_cases_free_play():
    for f in CASES:
        Game(Case.load(f), MockLLM()).run()


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("t_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except Exception as e:
                fails += 1; print(f"FAIL {name}: {type(e).__name__}: {e}")
    print("all passed" if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
