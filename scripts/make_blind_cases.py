#!/usr/bin/env python3
"""
Turn full decisions into "blind" cases for backtesting.

GAO decisions state the outcome (and GAO's reasoning) in the text, so we keep
only the factual background and the protester's arguments, and hold the
outcome back as the label. This is a first-pass heuristic: it truncates at the
start of GAO's analysis ("DISCUSSION") and strips outcome sentences.

Usage:
  python scripts/make_blind_cases.py
Output:
  data/processed/blind_cases.jsonl   {id, title, facts, label}
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "processed" / "decisions.jsonl"
DST = ROOT / "data" / "processed" / "blind_cases.jsonl"

CUT_MARKERS = re.compile(r"\n(DISCUSSION|Discussion|ANALYSIS)\n")
LEAK = re.compile(r"[^.]*\b(sustain|deny|denied|dismiss|dismissed)\b[^.]*\.", re.I)


def blind(text: str) -> str:
    m = CUT_MARKERS.search(text)
    facts = text[: m.start()] if m else text[: len(text) // 2]
    # Drop the "DECISION" header block's summary lines that state the result.
    facts = LEAK.sub("", facts)
    return facts.strip()


def main():
    n = 0
    with SRC.open() as fin, DST.open("w") as fout:
        for line in fin:
            rec = json.loads(line)
            if rec["outcome"] == "unknown" or rec["is_reconsideration"]:
                continue
            fout.write(json.dumps({
                "id": rec["b_numbers"][0] if rec["b_numbers"] else rec["url"],
                "title": rec["title"],
                "decision_date": rec["decision_date"],
                "facts": blind(rec["text"]),
                "label": rec["outcome"],
            }) + "\n")
            n += 1
    print(f"wrote {n} blind cases -> {DST}")


if __name__ == "__main__":
    main()
