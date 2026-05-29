"""LLM client — pluggable between a deterministic stub and the real Claude API.

The stub picks one of the hand-authored topologies based on keywords in the
brief, simulating what a working Claude integration would return. This lets
us validate the full pipeline (brief → topology → solver → render) and the
infeasibility-repair loop without burning API credits.

When ANTHROPIC_API_KEY is present in the environment, the client switches to
the real Claude call automatically.
"""
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOPOLOGIES_DIR = os.path.join(os.path.dirname(_HERE), "phase_c", "topologies")


def _load_topology_json(filename: str) -> Dict:
    with open(os.path.join(_TOPOLOGIES_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


class StubLLM:
    """Deterministic stand-in for the Claude call.

    Picks a topology from our hand-authored exemplars based on simple keyword
    matching on the brief. Good enough to exercise the pipeline; obviously
    not a real LLM."""

    def __init__(self):
        # the order matters: more specific rules first
        self._rules = [
            (["split", "private wing", "separation", "noise"], ["clustered", "wet core", "share plumbing"],
             "squarish_two_bedroom_split_clustered_baths.json"),
            (["split", "private wing", "separation", "noise"], [],
             "squarish_two_bedroom_split.json"),
            (["clustered", "wet core", "share plumbing", "plumbing wall"], [],
             "squarish_two_bedroom_clustered_baths.json"),
            ([], [],   # fallback
             "squarish_two_bedroom.json"),
        ]

    def generate(self, brief, error_feedback: Optional[str] = None) -> Tuple[Dict, str]:
        """Return (topology_dict, reasoning_text)."""
        text = (brief.intent + " " + " ".join(brief.must_haves)).lower()
        for primary, secondary, fname in self._rules:
            if any(k in text for k in primary):
                if not secondary or any(k in text for k in secondary):
                    topo = _load_topology_json(fname)
                    reason = self._reason(brief, fname, primary, secondary)
                    return topo, reason
            elif not primary:   # fallback rule
                topo = _load_topology_json(fname)
                reason = self._reason(brief, fname, ["(fallback)"], [])
                return topo, reason
        # shouldn't reach here, but safety net
        return _load_topology_json("squarish_two_bedroom.json"), "fallback"

    @staticmethod
    def _reason(brief, fname, primary, secondary) -> str:
        return (f"[stub] picked {fname} based on keywords {primary}"
                + (f" + {secondary}" if secondary else "")
                + f" in brief")


class ClaudeLLM:
    """Calls Claude (Anthropic API) with our system prompt, few-shot exemplars
    and tool-use schema. Activated automatically when ANTHROPIC_API_KEY is in
    the environment AND the anthropic library is installed.

    `temperature` is optional. When None we let the API default apply (1.0).
    Pass 0.0 for the most-reproducible behaviour (still not byte-for-byte
    deterministic, but close enough that the same brief usually yields the
    same topology)."""

    DEFAULT_MODEL = "claude-sonnet-4-5"
    MAX_TOKENS = 4096

    def __init__(self, api_key: str, model: Optional[str] = None,
                 temperature: Optional[float] = None):
        from anthropic import Anthropic   # raises ImportError if not installed
        self.client = Anthropic(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL
        self.temperature = temperature

    def generate(self, brief, error_feedback: Optional[str] = None) -> Tuple[Dict, str]:
        from prompt import (SYSTEM_PROMPT, TOOL_SCHEMA,
                            build_few_shot_messages, build_brief_message,
                            last_example_tool_use_id)

        messages = list(build_few_shot_messages())          # exemplars first
        # the live brief becomes the final user turn — but the previous turn
        # was an assistant tool_use (the last exemplar), so we must pair it
        # with a tool_result block before the brief text.
        messages.append({"role": "user", "content": [
            {"type": "tool_result",
             "tool_use_id": last_example_tool_use_id(),
             "content": "Accepted."},
            {"type": "text", "text": build_brief_message(brief, error_feedback)},
        ]})

        kwargs = {}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "submit_topology"},
            messages=messages,
            **kwargs,
        )

        # extract the tool-use block (the topology JSON)
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_topology":
                topo_dict = block.input
                t_tag = f"/T={self.temperature}" if self.temperature is not None else ""
                reason = (f"[claude/{self.model}{t_tag}] {resp.stop_reason}; "
                          f"tokens: in={resp.usage.input_tokens} "
                          f"out={resp.usage.output_tokens}")
                return topo_dict, reason
        raise RuntimeError(f"Claude response had no submit_topology tool_use; "
                           f"stop_reason={resp.stop_reason}")


def get_client():
    """Return a Claude client if a key + the anthropic library are both
    available; otherwise fall back to the stub. The pipeline doesn't care
    which one it gets — same interface."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            return ClaudeLLM(key)
        except ImportError:
            print("note: ANTHROPIC_API_KEY set but anthropic library missing — "
                  "run: pip install anthropic --break-system-packages")
            print("falling back to stub LLM for now.")
    return StubLLM()
