"""LLM backends. Each call is stateless text-in/text-out: no tools, no files,
no shared conversation. Agent "memory" is only what the orchestrator passes in.

Backends:
  AnthropicLLM  - real calls (needs ANTHROPIC_API_KEY)
  MockLLM       - deterministic canned answers for offline testing
"""
import json
import os
import re


def extract_json(text: str) -> dict:
    """Return the last JSON object in a model response."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    candidates = blocks or re.findall(r"(\{.*\})", text, re.S)
    for cand in reversed(candidates):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in response:\n" + text[-500:])


class AnthropicLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 2000):
        import anthropic  # imported lazily so mock mode needs no package
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("SIM_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def __call__(self, system: str, user: str, temperature: float = 0.7) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        self.usage["input_tokens"] += resp.usage.input_tokens
        self.usage["output_tokens"] += resp.usage.output_tokens
        self.usage["calls"] += 1
        return "".join(b.text for b in resp.content if b.type == "text")


class MockLLM:
    """Canned responses keyed by the TASK tag in the prompt. For plumbing tests only."""

    CANNED = {
        "COUNSEL_T1": {"grounds": [
            {"id": "g1", "name": "Unstated criterion: DBB delivery method", "p_sustain": 0.15},
            {"id": "g2", "name": "Unstated criterion: historic preservation", "p_sustain": 0.12},
            {"id": "g3", "name": "Prof. quals scored from SF330 Section G", "p_sustain": 0.10}],
            "p_relief": 0.22, "recommend_filing": True,
            "client_advice": "Narrow protest, ~1 in 5 chance of relief."},
        "COMPANY_T1": {"decision": "file", "budget_cap_usd": 150000, "my_p_relief": 0.2},
        "AGENCY_T2": {"decision": "defend", "p_sustain": {"g1": 0.5, "g2": 0.15, "g3": 0.2},
                      "p_prejudice": 0.5, "report_summary": "Criteria logically encompassed."},
        "COUNSEL_T3": {"keep": ["g1", "g2"], "drop": ["g3"], "supplemental": [],
                       "p_sustain": {"g1": 0.25, "g2": 0.12, "g3": 0.05}, "p_relief": 0.25,
                       "comments_summary": "Synopsis disclaims delivery-method preference.",
                       "client_message": "Continue on strongest issue."},
        "COMPANY_T3": {"decision": "continue"},
        "GAO_T5": {"rulings": {"g1": "sustained", "g2": "denied"},
                   "overall": "sustained_in_part", "costs_recommended": True,
                   "confidence": {"g1": 0.65, "g2": 0.55}},
        "LESSONS": {"lessons": ["Unstated-criteria grounds are strongest when the solicitation is silent."]},
    }

    def __init__(self):
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def __call__(self, system: str, user: str, temperature: float = 0.7) -> str:
        self.usage["calls"] += 1
        m = re.search(r"TASK_TAG:\s*(\w+)", user)
        tag = m.group(1) if m else "LESSONS"
        return "```json\n" + json.dumps(self.CANNED[tag]) + "\n```"


def make_llm(mock: bool):
    if mock:
        return MockLLM()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY or use --mock")
    return AnthropicLLM()
