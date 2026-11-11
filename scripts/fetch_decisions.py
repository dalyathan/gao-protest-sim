#!/usr/bin/env python3
"""
Fetch published GAO bid protest decisions (public domain, U.S. government works).

Steps:
  1. Walk the GAO search listing filtered to "Bid Protest Decision" and collect
     decision URLs (/products/b-XXXXXX).
  2. Download each decision page, extract the decision text, and save it raw.
  3. Parse basic metadata: B-number(s), protester, date, outcome.

Usage:
  python scripts/fetch_decisions.py --pages 5          # ~5 listing pages
  python scripts/fetch_decisions.py --pages 5 --since 2026-07-01

Output:
  data/raw/<b-number>.html        raw decision page
  data/processed/decisions.jsonl  one JSON record per decision

Be polite: a delay is applied between requests. Run from a machine that can
reach www.gao.gov (e.g., your own laptop).
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.gao.gov"
LISTING = BASE + "/search?f%5B0%5D=ctype_search%3ABid%20Protest%20Decision&page={page}"
HEADERS = {"User-Agent": "gao-protest-sim research (contact: your-email@example.com)"}
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "decisions.jsonl"

# Outcome is stated near the end of GAO decisions, e.g. "The protest is denied."
OUTCOME_PATTERNS = [
    ("sustained", re.compile(r"\b(protest|protests) (is|are) sustained\b", re.I)),
    ("sustained_in_part", re.compile(r"sustained in part", re.I)),
    ("denied", re.compile(r"\b(protest|protests) (is|are) denied\b", re.I)),
    ("dismissed", re.compile(r"\b(protest|protests) (is|are) dismissed\b", re.I)),
    ("denied_in_part_dismissed_in_part", re.compile(r"denied in part and dismissed in part", re.I)),
]


def get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def collect_decision_urls(pages: int, delay: float) -> list[str]:
    urls: list[str] = []
    for p in range(pages):
        html = get(LISTING.format(page=p))
        soup = BeautifulSoup(html, "html.parser")
        found = {a["href"] for a in soup.select("a[href^='/products/b-']")}
        print(f"listing page {p}: {len(found)} decisions")
        if not found:
            break
        urls.extend(sorted(found - set(urls)))
        time.sleep(delay)
    return [BASE + u for u in urls]


def classify_outcome(text: str) -> str:
    tail = text[-3000:]  # outcome language sits at the end
    hits = [label for label, pat in OUTCOME_PATTERNS if pat.search(tail)]
    if "sustained_in_part" in hits:
        return "sustained_in_part"
    if "denied_in_part_dismissed_in_part" in hits:
        return "denied_in_part_dismissed_in_part"
    return hits[0] if hits else "unknown"


def parse_decision(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
    # Main body: GAO pages keep decision text in the main content region.
    main = soup.find("main") or soup
    text = main.get_text("\n", strip=True)
    bnums = sorted(set(re.findall(r"B-\d{6}(?:\.\d+)?", text)))
    date = None
    m = re.search(r"(January|February|March|April|May|June|July|August|September|"
                  r"October|November|December) \d{1,2}, 20\d\d", text)
    if m:
        date = datetime.strptime(m.group(0), "%B %d, %Y").date().isoformat()
    pdf = soup.select_one("a[href$='.pdf']")
    return {
        "url": url,
        "title": title,
        "b_numbers": bnums,
        "decision_date": date,
        "outcome": classify_outcome(text),
        "pdf_url": (BASE + pdf["href"]) if pdf and pdf["href"].startswith("/") else (pdf["href"] if pdf else None),
        "is_reconsideration": "reconsideration" in title.lower(),
        "n_chars": len(text),
        "text": text,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--since", type=str, default=None, help="YYYY-MM-DD; keep decisions on/after")
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    urls = collect_decision_urls(args.pages, args.delay)
    print(f"{len(urls)} decision URLs")
    kept = 0
    with OUT.open("a") as f:
        for url in urls:
            slug = url.rsplit("/", 1)[-1]
            raw_path = RAW / f"{slug}.html"
            if raw_path.exists():
                html = raw_path.read_text()
            else:
                try:
                    html = get(url)
                except requests.HTTPError as e:
                    print(f"skip {url}: {e}")
                    continue
                raw_path.write_text(html)
                time.sleep(args.delay)
            rec = parse_decision(url, html)
            if args.since and rec["decision_date"] and rec["decision_date"] < args.since:
                continue
            f.write(json.dumps(rec) + "\n")
            kept += 1
            print(f"{rec['decision_date']}  {rec['outcome']:<12} {rec['title'][:70]}")
    print(f"saved {kept} records -> {OUT}")


if __name__ == "__main__":
    main()
