#!/usr/bin/env python3
"""Split GAO decision texts into an outcome-blind FACTS file (what agents may see)
and an ANSWER file (observer only).

FACTS  = the DECISION intro (who protests what, and the grounds) with every
         outcome sentence removed, plus the BACKGROUND section.
ANSWER = DIGEST, the removed outcome sentences, DISCUSSION, RECOMMENDATION.

Then a leak scan flags any facts file that still contains outcome language, so a
human can check it before it is used. This script never prints outcomes.
Usage: python scripts/split_gao_decision.py   (reads data/test_set_v1.json)
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TXT, OUT_F, OUT_A = ROOT / "data" / "gao_txt", ROOT / "data" / "test_facts", ROOT / "data" / "test_answers"
HEAD = re.compile(r"^\s*(DIGEST|DECISION|BACKGROUND|DISCUSSION|RECOMMENDATION|CONCLUSION)\s*$", re.M)
OUTCOME_SENT = re.compile(r"[^.]*\b(we|gao)\s+(deny|sustain|dismiss|denies|sustains|dismisses)\b[^.]*\.|"
                          r"[^.]*\bprotests? (is|are) (denied|sustained|dismissed)[^.]*\.", re.I)
LEAK = re.compile(r"\b(sustain\w*|deni\w*|deny|dismiss\w*|we (find|conclude|agree|disagree)|"
                  r"unobjectionable|reasonabl[ey] (concluded|found)|recommend\w*|prejudic\w*)\b", re.I)


def sections(text):
    marks = [(m.group(1), m.start(), m.end()) for m in HEAD.finditer(text)]
    out = {}
    for i, (name, s, e) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out.setdefault(name, text[e:end].strip())
    return out


def clean(s):
    s = re.sub(r"Page \d+\s+B-[\d.,\s;B-]+", " ", s)  # page footers
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def main():
    OUT_F.mkdir(parents=True, exist_ok=True)
    OUT_A.mkdir(parents=True, exist_ok=True)
    rows = json.load(open(ROOT / "data" / "test_set_v1.json"))["tier_A_post_cutoff"]
    report = []
    for r in rows:
        text = (TXT / r["file"]).read_text(errors="ignore")
        sec = sections(text)
        intro = clean(sec.get("DECISION", ""))
        removed = [m.group(0) for m in OUTCOME_SENT.finditer(intro)]
        intro_blind = OUTCOME_SENT.sub("", intro).strip()
        facts = "INTRODUCTION\n" + intro_blind + "\n\nBACKGROUND\n" + clean(sec.get("BACKGROUND", "(none)"))
        answer = {"b": r["b"], "date": r["date"], "digest": clean(sec.get("DIGEST", "")),
                  "outcome_sentences": removed, "discussion": clean(sec.get("DISCUSSION", "")),
                  "recommendation": clean(sec.get("RECOMMENDATION", ""))}
        stem = re.sub(r"[^a-z0-9.]+", "_", r["b"].lower()).strip("_")
        (OUT_F / f"{stem}.txt").write_text(facts)
        (OUT_A / f"{stem}.json").write_text(json.dumps(answer, indent=1))
        hits = sorted({m.group(0).lower() for m in LEAK.finditer(facts)})
        low = re.sub(r"\s+", " ", intro).lower()
        kind = ("costs_request" if re.search(r"request\w* (that )?(our office|gao) recommend", low) or "--costs" in low
                else "reconsideration" if "reconsider" in low[:600]
                else "protest")
        hard_leak = bool(re.search(r"\b(we find|we conclude|our office would likely|we agree with the agency)\b",
                                   re.sub(r"\s+", " ", facts), re.I))
        report.append({"case": stem, "facts_words": len(facts.split()), "has_background": "BACKGROUND" in sec,
                       "outcome_sentences_removed": len(removed), "leak_terms": hits,
                       "kind": kind, "hard_leak": hard_leak,
                       "usable": kind == "protest" and not hard_leak})
    (ROOT / "data" / "test_facts" / "_leak_report.json").write_text(json.dumps(report, indent=1))
    flagged = [x for x in report if x["leak_terms"]]
    print(f"{len(report)} cases split. facts words median "
          f"{sorted(x['facts_words'] for x in report)[len(report)//2]}. "
          f"No BACKGROUND: {sum(not x['has_background'] for x in report)}. "
          f"Intro outcome sentence removed: {sum(x['outcome_sentences_removed'] > 0 for x in report)}. "
          f"Flagged words: {len(flagged)}.")
    import collections
    print("Kinds:", dict(collections.Counter(x["kind"] for x in report)),
          "| GAO-voice leak in facts:", sum(x["hard_leak"] for x in report),
          "| USABLE merits test cases:", sum(x["usable"] for x in report))


if __name__ == "__main__":
    main()
