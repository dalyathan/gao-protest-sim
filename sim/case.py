"""Case packets and visibility filtering.

Each document in a packet has a `tag`. An actor sees a document only if the
tag is in its allowed set for the current turn. The observer-only outcome file
is never loaded here.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Which tags each actor may see, and from which turn.
VISIBILITY = {
    "protester_co":      {"public": 0, "debrief": 0, "private_protester": 0},
    "protester_counsel": {"public": 0, "debrief": 0, "private_protester": 0, "apo": 3},
    "agency":            {"public": 0, "debrief": 0, "agency_internal": 0, "apo": 2},
    "intervenor":        {"public": 0, "apo": 3},
    "gao":               {"public": 0, "apo": 3},
}

# Info scenarios (GAME_DESIGN.md 7.3) override visibility.
def visibility_for(scenario: str) -> dict:
    vis = {a: dict(t) for a, t in VISIBILITY.items()}
    if scenario == "full_transparency":
        all_tags = {"public", "debrief", "private_protester", "agency_internal", "apo"}
        vis = {a: {t: 0 for t in all_tags} for a in vis}
    elif scenario == "no_apo_access":
        vis["protester_counsel"].pop("apo", None)
    return vis


@dataclass
class Case:
    case_id: str
    documents: list
    params: dict
    path: Path
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "Case":
        p = Path(path)
        if "observer_only" in p.name:
            raise ValueError("refusing to load an observer-only file as a case")
        d = yaml.safe_load(p.read_text())
        return cls(case_id=d["case_id"], documents=d["documents"],
                   params=d.get("parameters", {}), path=p,
                   extra={k: v for k, v in d.items() if k not in ("case_id", "documents", "parameters")})

    def context_for(self, actor: str, turn: int, scenario: str = "realistic") -> str:
        allowed = visibility_for(scenario)[actor]
        parts = []
        for doc in self.documents:
            tag = doc["tag"]
            start = max(allowed.get(tag, 99), doc.get("available_from_turn", 0))
            if tag in allowed and turn >= start:
                parts.append(f"[{doc['id']} | {tag}]\n{doc['text'].strip()}")
        return "\n\n".join(parts)


def load_outcome(case: Case) -> dict:
    """Observer only: load the real outcome for scoring."""
    p = case.path.with_name(case.path.name.replace("_packet", "_observer_only"))
    return yaml.safe_load(p.read_text())["actual"] if p.exists() else {}
