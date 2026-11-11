"""RL decision layer (Option 3): Claude supplies beliefs; small tabular
Q-learners choose the strategic moves and learn from simulated payoffs.

Multi-agent setup: the protester company and the agency are independent
learners, each maximizing its own scorecard. Both learn at the same time, so
each one's environment includes the other's evolving strategy.

Training needs NO LLM calls: one LLM-played game (or a few) provides each
case's belief profile; training samples thousands of episodes around it with
randomized parameters (incumbency, delay cost, legal cost) and noisy beliefs.
"""
import json
import random
from collections import defaultdict

from .game import MOVES
from .payoffs import agency_payoff, protester_payoff

P_BINS = [0.1, 0.2, 0.3, 0.45, 0.6, 1.01]
DELAY_BINS = [2500, 7500, 15000, 30000, 1e12]


def bucket(x, bins):
    for i, b in enumerate(bins):
        if x < b:
            return i
    return len(bins) - 1


def state_key(tag: str, s: dict) -> str:
    if tag == "AGENCY_T2":
        return f"ps{bucket(s['p_sustain_any'], P_BINS)}|d{bucket(s['delay_cost'], DELAY_BINS)}"
    return f"pr{bucket(s['p_relief'], P_BINS)}|inc{s.get('incumbent', 0)}"


class Policy:
    def __init__(self, alpha=0.05, epsilon=0.15):
        self.q = {tag: defaultdict(lambda: defaultdict(float)) for tag in MOVES}
        self.n = {tag: defaultdict(lambda: defaultdict(int)) for tag in MOVES}
        self.alpha, self.epsilon = alpha, epsilon

    def act(self, tag, state, explore=True):
        k = state_key(tag, state)
        if explore and random.random() < self.epsilon:
            return random.choice(MOVES[tag])
        qs = self.q[tag][k]
        return max(MOVES[tag], key=lambda a: qs[a]) if qs else MOVES[tag][0]

    def update(self, tag, state, action, reward):
        k = state_key(tag, state)
        self.n[tag][k][action] += 1
        self.q[tag][k][action] += self.alpha * (reward - self.q[tag][k][action])

    def table(self):
        return {tag: {k: {"best": max(v, key=v.get), "q": {a: round(x, 3) for a, x in v.items()},
                          "n": dict(self.n[tag][k])}
                      for k, v in sorted(self.q[tag].items())} for tag in self.q}

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.table(), f, indent=2)

    @classmethod
    def load(cls, path):
        pol = cls(epsilon=0.0)
        for tag, rows in json.load(open(path)).items():
            for k, row in rows.items():
                for a, x in row["q"].items():
                    pol.q[tag][k][a] = x
        return pol


def clip(x):
    return min(0.95, max(0.01, x))


class ProtestEnv:
    """Cheap simulator of one case's strategic layer.

    profile: beliefs from an LLM-played game:
      counsel_p_relief_t1, agency_p_sustain_any, counsel_p_relief_t3, true_p_sustain
    true_p_sustain is the environment's chance GAO sustains if the case is decided
    (default: the agency's own estimate, since it is best informed about the record).
    """

    def __init__(self, params: dict, profile: dict, randomize=True, noise=0.08):
        self.base, self.profile, self.randomize, self.noise = params, profile, randomize, noise

    def sample_params(self):
        p = dict(self.base)
        if self.randomize:
            p["incumbent"] = random.choice([0, 1])
            p["agency_delay_cost_per_day"] = random.choice([1000, 5000, 10000, 20000, 40000])
            p["protester_legal_cost"] = random.choice([150000, 250000, 400000])
        return p

    def episode(self, pol: Policy, explore=True):
        p = self.sample_params()
        n = lambda x: clip(x + random.gauss(0, self.noise))
        true_p = n(self.profile["true_p_sustain"])
        s1 = {"p_relief": n(self.profile["counsel_p_relief_t1"]), "incumbent": p.get("incumbent", 0)}
        a1 = pol.act("COMPANY_T1", s1, explore)
        if a1 == "do_not_file":
            pol.update("COMPANY_T1", s1, a1, 0.0)
            return {"outcome": "not_filed", "p": p}
        s2 = {"p_sustain_any": n(self.profile["agency_p_sustain_any"]), "delay_cost": p["agency_delay_cost_per_day"]}
        a2 = pol.act("AGENCY_T2", s2, explore)
        if a2 == "corrective_action":
            rp = protester_payoff(p, True, "early", True, False) / 1e5
            ra = agency_payoff(p, True, True, 2, False) / 1e5
            pol.update("COMPANY_T1", s1, a1, rp)
            pol.update("AGENCY_T2", s2, a2, ra)
            return {"outcome": "corrective_action", "p": p, "rp": rp, "ra": ra}
        s3 = {"p_relief": n(self.profile["counsel_p_relief_t3"]), "incumbent": p.get("incumbent", 0)}
        a3 = pol.act("COMPANY_T3", s3, explore)
        if a3 == "withdraw":
            rp = protester_payoff(p, True, "early", False, False) / 1e5
            ra = agency_payoff(p, True, False, None, False) / 1e5 * 0.5  # protest ends ~halfway
            outcome = "withdrawn"
        else:
            sustained = random.random() < true_p
            rp = protester_payoff(p, True, "full", sustained, sustained) / 1e5
            ra = agency_payoff(p, True, False, None, sustained) / 1e5
            outcome = "sustained" if sustained else "denied"
        pol.update("COMPANY_T1", s1, a1, rp)
        pol.update("COMPANY_T3", s3, a3, rp)
        pol.update("AGENCY_T2", s2, a2, ra)
        return {"outcome": outcome, "p": p, "rp": rp, "ra": ra}


def train(envs: list, episodes=50000, seed=0, window=5000):
    """Train one shared policy across cases. Returns policy + learning curve
    (outcome mix per window) to check whether play converges."""
    random.seed(seed)
    pol = Policy()
    curve, counts = [], defaultdict(int)
    for i in range(1, episodes + 1):
        env = random.choice(envs)
        counts[env.episode(pol)["outcome"]] += 1
        if i % window == 0:
            total = sum(counts.values())
            curve.append({"episode": i, **{k: round(v / total, 3) for k, v in sorted(counts.items())}})
            counts = defaultdict(int)
        pol.epsilon = max(0.02, 0.15 * (1 - i / episodes))
    return pol, curve
