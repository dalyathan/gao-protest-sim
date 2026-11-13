"""LLM backends. Each call is stateless text-in/text-out: no tools, no files,
no shared conversation. Agent "memory" is only what the orchestrator passes in.

Backends:
  AnthropicLLM  - real calls (needs ANTHROPIC_API_KEY)
  ClaudeCLI     - real calls through the Claude Code CLI (`claude -p`), billed to your
                  Claude subscription instead of the API. Select with SIM_BACKEND=cli.
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
    def __init__(self, model: str | None = None, max_tokens: int = 4000):
        import anthropic  # imported lazily so mock mode needs no package
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("SIM_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def __call__(self, system: str, user: str, temperature: float = 0.7) -> str:
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, system=system,
                      messages=[{"role": "user", "content": user}])
        try:
            resp = self.client.messages.create(temperature=temperature, **kwargs)
        except Exception as e:  # some models/SDKs reject temperature (TypeError or a 400 BadRequestError)
            if "temperature" not in str(e).lower() and not isinstance(e, TypeError):
                raise
            resp = self.client.messages.create(**kwargs)
        self.usage["input_tokens"] += resp.usage.input_tokens
        self.usage["output_tokens"] += resp.usage.output_tokens
        self.usage["calls"] += 1
        return "".join(b.text for b in resp.content if b.type == "text")


class ClaudeCLI:
    """One fresh `claude -p` process per agent turn.

    Isolation rules (these protect the experiment):
      * runs in an empty temporary folder, with every tool disabled, so an agent
        cannot open the project (e.g. *_observer_only.yaml) or the web;
      * --safe-mode: no CLAUDE.md, skills, plugins, hooks, MCP servers or memory;
      * --no-session-persistence: nothing carries over between calls;
      * our own system prompt replaces Claude Code's default one.
    ANTHROPIC_API_KEY is removed from the child's environment so the call uses
    your logged-in subscription rather than the API key.
    Note: the CLI exposes no temperature setting.
    """

    def __init__(self, model: str | None = None, timeout: int = 600):
        import shutil
        if not shutil.which("claude"):
            raise SystemExit("`claude` not found. Install Claude Code and run `claude` once to log in.")
        self.model = model or os.environ.get("SIM_CLI_MODEL", "sonnet")
        self.timeout = timeout
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def __call__(self, system: str, user: str, temperature: float = 0.7) -> str:
        import subprocess, tempfile
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        with tempfile.TemporaryDirectory(prefix="gaosim_") as tmp:
            sp = os.path.join(tmp, "system.txt")
            with open(sp, "w") as f:
                f.write(system)
            cmd = ["claude", "-p", "--safe-mode", "--tools", "", "--no-session-persistence",
                   "--max-turns", "1", "--model", self.model, "--output-format", "json",
                   "--system-prompt-file", sp]
            import time
            waits = [30, 120, 300, 900]  # back off on usage/rate limits or transient errors
            for attempt in range(len(waits) + 1):
                t0 = time.time()
                try:
                    r = subprocess.run(cmd, input=user, capture_output=True, text=True,
                                       cwd=tmp, env=env, timeout=self.timeout)
                    out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
                    err = r.returncode != 0 or out.get("is_error") or "result" not in out
                except subprocess.TimeoutExpired:
                    r, out, err = None, {}, True
                self.seconds = getattr(self, "seconds", 0) + time.time() - t0
                if not err:
                    break
                msg = (out.get("result") if out else None) or (r.stderr[-400:] if r else "timeout")
                if attempt == len(waits):
                    raise RuntimeError(f"claude -p failed after retries: {msg}")
                print(f"    claude -p error ({str(msg)[:120]!r}); retrying in {waits[attempt]}s", flush=True)
                time.sleep(waits[attempt])
        u = out.get("usage") or {}
        self.usage["input_tokens"] += int(u.get("input_tokens", 0))
        self.usage["output_tokens"] += int(u.get("output_tokens", 0))
        self.usage["calls"] += 1
        return out.get("result", "")


class MockLLM:
    """Canned responses keyed by the TASK tag in the prompt. For plumbing tests only:
    scores from mock games mean nothing (the canned answers happen to resemble one real case)."""

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
        out = json.loads(json.dumps(self.CANNED[tag]))
        # Use the ground ids the prompt actually offers, so fixed-grounds games run too.
        ids = re.findall(r"^(\S+?): ", user.split("Grounds remaining for decision:")[-1], re.M) \
            if "Grounds remaining for decision:" in user else []
        filed = re.findall(r"^(\S+?): ", user.split("filed on exactly these grounds")[-1].split("\n\n")[0], re.M) \
            if "filed on exactly these grounds" in user else []
        if tag == "COUNSEL_T1" and filed:
            out["grounds"] = [{"id": g, "p_sustain": 0.15} for g in filed]
        listed = re.findall(r"^(\S+?): ", user.split("PROTEST FILED. Grounds:")[-1].split("\n\n")[0], re.M) \
            if "PROTEST FILED. Grounds:" in user else []
        if tag == "AGENCY_T2" and listed:
            out["p_sustain"] = {g: 0.2 for g in listed}
        if tag == "COUNSEL_T3" and listed:
            out["keep"], out["drop"] = listed[:2], listed[2:]
            out["p_sustain"] = {g: 0.2 for g in listed}
        if tag == "GAO_T5" and ids:
            out["rulings"] = {g: ("sustained" if i == 0 else "denied") for i, g in enumerate(ids)}
            out["confidence"] = {g: 0.6 for g in ids}
        return "```json\n" + json.dumps(out) + "\n```"


def make_llm(mock: bool):
    if mock:
        return MockLLM()
    if os.environ.get("SIM_BACKEND", "").lower() == "cli":
        return ClaudeCLI()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY or use --mock")
    return AnthropicLLM()
