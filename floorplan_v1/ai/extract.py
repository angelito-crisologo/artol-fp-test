"""Free-text intent -> structured Brief-field dict.

This is a separate, narrower Claude call from ai/pipeline.py's topology
generation call. Its only job is turning a buyer's natural-language
description into the structured fields on `Brief`, so the front end (app.py)
can show them as editable form fields *before* anything gets solved.

Same pluggable-client pattern as ai/llm.py: a deterministic StubExtractor
(regex/keyword based) for local testing without burning API credits, and a
ClaudeExtractor that activates automatically when ANTHROPIC_API_KEY is set.
"""
import os
import re
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------- #
# Fields we ask for — a subset of ai/brief.py::Brief that's meaningful for
# a buyer to describe in free text. intent itself is stored verbatim by the
# caller; it isn't part of this schema.
# ---------------------------------------------------------------------- #

REQUIREMENTS_SCHEMA = {
    "name": "submit_requirements",
    "description": (
        "Structured house requirements extracted from a buyer's free-text "
        "description."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lot_width": {
                "type": "number",
                "description": "Street frontage in metres. If not mentioned, "
                               "guess a sensible mid-market default (e.g. 10).",
            },
            "lot_depth": {
                "type": "number",
                "description": "Front-to-rear lot depth in metres. If not "
                               "mentioned, guess a sensible mid-market default "
                               "(e.g. 12).",
            },
            "bedroom_count": {
                "type": "integer",
                "description": "Number of bedrooms. Default 2 if not mentioned.",
            },
            "must_haves": {
                "type": "array", "items": {"type": "string"},
                "description": "Short phrases for explicitly requested features, "
                               "e.g. 'open plan', 'dirty kitchen'.",
            },
            "avoid": {
                "type": "array", "items": {"type": "string"},
                "description": "Short phrases for explicitly unwanted features.",
            },
            "carport_side": {
                "type": "string", "enum": ["left", "right", "front", "none"],
                "description": "Side of the carport if one is wanted. 'none' if "
                               "no carport is mentioned.",
            },
            "carport_type": {
                "type": "string", "enum": ["fcp", "ccp", "none"],
                "description": "'fcp' (full carport, whole side setback) or "
                               "'ccp' (claimed carport, partial L-notch). "
                               "Default 'ccp' if a carport is wanted but the "
                               "type isn't specified. 'none' if no carport.",
            },
            "occupancy_class": {
                "type": "string", "enum": ["R-1", "R-2", "R-3"],
                "description": "PD 1096 occupancy class. Default 'R-1' "
                               "(single-detached) unless a firewall / party "
                               "wall / duplex is mentioned.",
            },
            "swap_master_standard": {
                "type": "boolean",
                "description": "True if the buyer wants the master bedroom at "
                               "the rear (quieter) instead of the default "
                               "front position.",
            },
            "no_master": {
                "type": "boolean",
                "description": "True only if the buyer explicitly wants "
                               "all-equal bedrooms with no distinguished "
                               "master.",
            },
            "num_baths": {
                "type": "integer",
                "description": "Number of full bathrooms required. Set to 2 "
                               "when the buyer requests a private/ensuite bath "
                               "for the master bedroom (phrases like 'own t&b', "
                               "'private bathroom', 'ensuite', 'master bath', "
                               "'sariling CR'). Set to 0 to use the size-based "
                               "default instead.",
            },
            "powder_room": {
                "type": "boolean",
                "description": "True if a powder room / half-bath / guest "
                               "toilet is requested.",
            },
            "dirty_kitchen": {
                "type": "boolean",
                "description": "True if a dirty kitchen is requested.",
            },
            "service_area": {
                "type": "boolean",
                "description": "True if a laundry / service area is requested.",
            },
            "lanai": {"type": "boolean", "description": "True if a lanai is requested."},
            "patio": {"type": "boolean", "description": "True if a patio is requested."},
            "kitchen_back_door": {
                "type": "boolean",
                "description": "Default true; false only if the buyer "
                               "explicitly wants the kitchen's rear wall "
                               "sealed (no back door).",
            },
        },
        "required": ["lot_width", "lot_depth", "bedroom_count"],
    },
}

SYSTEM_PROMPT = """\
You turn a home buyer's free-text description into structured requirements \
for a Philippine mid-market single-detached house. You are NOT designing the \
house — a separate system does that. You are only extracting/inferring the \
structured fields defined by the submit_requirements tool.

Rules:
- If a field isn't mentioned or implied, use the documented default. Never \
leave a required field out.
- lot_width/lot_depth: look for explicit dimensions ("10x12", "10 by 12 \
meters", "lot is 300 sqm on a 15m frontage"). If only an area is given, pick \
a plausible width/depth pair for a mid-market lot. If nothing is given, \
default to 10 x 12.
- must_haves/avoid: short phrases, not full sentences, e.g. "open plan", \
"dirty kitchen", not "I want an open plan kitchen".
- Call submit_requirements exactly once with your best extraction."""


def _normalize(raw: Dict) -> Dict:
    """Map the schema's 'none' sentinels to the None the rest of the pipeline
    expects, and num_baths=0 to None."""
    out = dict(raw)
    if out.get("carport_side") in ("none", None, ""):
        out["carport_side"] = None
    if out.get("carport_type") in ("none", None, ""):
        out["carport_type"] = None
    if not out.get("num_baths"):
        out["num_baths"] = None
    out.setdefault("must_haves", [])
    out.setdefault("avoid", [])
    out.setdefault("occupancy_class", "R-1")
    out.setdefault("bedroom_count", 2)
    out.setdefault("swap_master_standard", False)
    out.setdefault("no_master", False)
    out.setdefault("powder_room", False)
    out.setdefault("dirty_kitchen", False)
    out.setdefault("service_area", False)
    out.setdefault("lanai", False)
    out.setdefault("patio", False)
    out.setdefault("kitchen_back_door", True)
    return out


class StubExtractor:
    """Deterministic regex/keyword extractor. Good enough to exercise the
    front end end-to-end without an API key; obviously cruder than Claude."""

    def extract(self, intent: str) -> Tuple[Dict, str]:
        text = intent.lower()

        dims = re.search(r"(\d+(?:\.\d+)?)\s*(?:m)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:m)?", text)
        lot_width = float(dims.group(1)) if dims else 10.0
        lot_depth = float(dims.group(2)) if dims else 12.0

        br = re.search(r"(\d+)\s*[- ]?\s*(?:bed|bedroom|br)\b", text)
        bedroom_count = int(br.group(1)) if br else 2

        baths = re.search(r"(\d+)\s*[- ]?\s*(?:full )?bath", text)
        num_baths = int(baths.group(1)) if baths else None
        if num_baths is None and any(k in text for k in (
                "own t&b", "own tb", "private bath", "ensuite", "sariling cr",
                "master bath", "master bedroom.*bath", "own bathroom")):
            num_baths = 2

        want_carport = any(k in text for k in ("carport", "garage"))
        carport_side = None
        if want_carport:
            if "left" in text:
                carport_side = "left"
            elif "front" in text:
                carport_side = "front"
            else:
                carport_side = "right"
        carport_type = None
        if want_carport:
            carport_type = "fcp" if any(k in text for k in ("full carport", "fcp", "whole setback")) else "ccp"

        occupancy_class = "R-1"
        if any(k in text for k in ("firewall", "party wall", "duplex")):
            occupancy_class = "R-2"
        elif any(k in text for k in ("apartment", "multi-family", "multi family")):
            occupancy_class = "R-3"

        flag_map = {
            "powder_room": ("powder room", "half bath", "half-bath", "guest toilet"),
            "dirty_kitchen": ("dirty kitchen",),
            "service_area": ("laundry", "service area"),
            "lanai": ("lanai",),
            "patio": ("patio",),
            "swap_master_standard": ("master at rear", "master at the back", "master bedroom at back", "master rear"),
            "no_master": ("no master", "equal bedrooms", "no distinguished master"),
        }
        flags = {k: any(kw in text for kw in kws) for k, kws in flag_map.items()}

        must_haves = [label.replace("_", " ") for label, hit in
                      (("open plan", "open plan" in text),
                       ("dirty kitchen", flags["dirty_kitchen"]),
                       ("powder room", flags["powder_room"]),
                       ("lanai", flags["lanai"]),
                       ("patio", flags["patio"]))
                      if hit]

        avoid = []
        if "no carport" in text:
            avoid.append("carport")
            carport_side = None
            carport_type = None

        raw = {
            "lot_width": lot_width, "lot_depth": lot_depth,
            "bedroom_count": bedroom_count, "must_haves": must_haves,
            "avoid": avoid, "carport_side": carport_side or "none",
            "carport_type": carport_type or "none",
            "occupancy_class": occupancy_class, "num_baths": num_baths or 0,
            "kitchen_back_door": True,
            **flags,
        }
        return _normalize(raw), "[stub] regex/keyword extraction — no API call"


class ClaudeExtractor:
    """Calls Claude with a narrow tool-use schema to extract structured
    requirements from free text. `temperature=0` for repeatability."""

    DEFAULT_MODEL = "claude-sonnet-4-5"
    MAX_TOKENS = 1024

    def __init__(self, api_key: str, model: Optional[str] = None):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL

    def extract(self, intent: str) -> Tuple[Dict, str]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            tools=[REQUIREMENTS_SCHEMA],
            tool_choice={"type": "tool", "name": "submit_requirements"},
            messages=[{"role": "user", "content": intent}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_requirements":
                reason = (f"[claude/{self.model}] {resp.stop_reason}; "
                          f"tokens: in={resp.usage.input_tokens} "
                          f"out={resp.usage.output_tokens}")
                return _normalize(block.input), reason
        raise RuntimeError(f"Claude response had no submit_requirements tool_use; "
                           f"stop_reason={resp.stop_reason}")


def get_extractor():
    """Same fallback rule as ai/llm.py::get_client(): Claude if a key + the
    anthropic library are both available, otherwise the stub."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            return ClaudeExtractor(key)
        except ImportError:
            pass
    return StubExtractor()


def extract_requirements(intent: str) -> Tuple[Dict, str]:
    """Top-level convenience: intent text -> (fields dict, reasoning string)."""
    return get_extractor().extract(intent)
