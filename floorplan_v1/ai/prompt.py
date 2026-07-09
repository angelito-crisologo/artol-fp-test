"""System prompt + few-shot examples + tool schema for the Claude call.

The prompt teaches Claude:
  - the role (PH residential architect)
  - our rule vocabulary (adjacency, soft_proximities, zone_split, etc.)
  - the hard PD 1096 constraints rooms must satisfy
  - PH-specific design conventions
  - the tool-use schema for the topology output
  - few-shot exemplars: brief -> topology pairs derived from our hand-authored files

The exemplars are the single most important part of the prompt — they're how
Claude learns what a good topology looks like in our system's vocabulary.
"""
import json
import os
from typing import Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOPOLOGIES_DIR = os.path.join(os.path.dirname(_HERE), "topologies")


# ---------- the system prompt itself ----------

SYSTEM_PROMPT = """\
You are an experienced Filipino mid-market residential architect. Your job
is to author a *topology* (an adjacency graph + rules) for a 2-bedroom
single-storey single-detached home, based on the buyer's brief and the lot.

You DO NOT decide the geometry. A separate deterministic solver (CP-SAT)
takes your topology and places the rectangles to satisfy all hard PD 1096
constraints automatically. Your job is to encode the DESIGN INTENT — which
rooms exist, how they connect, what soft preferences shape the layout.

# Rule vocabulary

You have five kinds of rules you can put in a topology:

1. **rooms** — the room program. Each room has an id (unique), type
   (matches our rules catalog: master_bedroom, ensuite_bath,
   bedroom_standard, common_bath, living_room, dining_room, kitchen,
   great_room, lanai, foyer, maids_room), zone (public/private/service),
   and size_priority (public_LDK / master_bedroom / other_bedrooms /
   service_and_baths — higher priority rooms get bigger).

2. **adjacencies** — hard rules requiring two rooms to share a wall of at
   least min_shared_wall_m. Use this for required door connections
   (ensuite door to master, kitchen-to-dining open plan, etc.) and shared
   walls (wet-core plumbing between common bath and kitchen).

3. **soft_proximities** — soft preferences pulling two rooms closer
   together via a Manhattan-distance penalty in the solver objective.
   Use this when you WANT two rooms near each other but don't strictly
   require a shared wall.

4. **zone_split** — an optional hard partition of the envelope into a
   private half and a public half (axis: vertical or horizontal,
   private_side: left/right/front/rear). Use this only when the brief
   calls for strict separation; otherwise omit it.

5. **entry_point** — the room that hosts the main door from the street.
   Almost always the living room.

6. **building_voids** — rectangular cutouts carved from the buildable
   envelope BEFORE the solver places rooms. Rooms cannot overlap them.
   Each void has: id (string), location (front_right / front_left /
   rear_right / rear_left — corner of the envelope where the cut starts),
   width_m (how deep the cut bites into the envelope measured across the
   lot width), depth_m (how far the cut extends front-to-rear within the
   envelope), consumed_by ("carport" for the CCP L-notch).
   Only use building_voids for the CCP carport pattern (see below).

# Hard PD 1096 rules (the solver enforces these automatically — you don't
# repeat them, but your topology must be CONSISTENT with them)

- Habitable rooms (bedrooms, living, dining, great_room): min 6 sqm with
  least dimension >= 2.0 m, must touch an exterior wall (window access).
- Kitchen: min 3 sqm, least dim >= 1.5 m, MUST touch the rear exterior
  wall (so the dirty kitchen behind it in the rear setback is adjacent).
- Living room: MUST touch the front exterior wall (street-side entry).
- Baths: min 1.2 sqm, least dim >= 0.9 m. We aim for >= 1.5 m least dim
  for comfort; the solver handles this automatically.
- Ensuite must be adjacent to master.
- Bedrooms must be reachable from a living/dining/great_room/hallway.

# PH design conventions

- Front door always opens into the living room.
- Kitchen sits at the rear; dirty kitchen + service area live in the rear
  setback behind it.
- Carport: the brief tells you `carport_type` (ccp / fcp / ncp) and
  `carport_side` (left / right / front). Encode it as follows.

  Generate the topology for the ACTUAL carport side in the brief — do not
  use a canonical side. If the brief says carport_side=left, put the carport
  on the left; if carport_side=right, put it on the right.

  **ncp** (no carport): omit the carport setback_element and building_void.

  **ccp** (claimed carport — default when carport_type is omitted):
  The carport occupies 3 m of the specified side setback for the first 6 m
  from the street, then the setback narrows back to 2 m, creating an L-notch
  in the building footprint. Include BOTH:
    setback_elements entry:
      { "type": "carport", "location": "side_setback", "covered": false,
        "width_m": 3.0, "depth_m": 6.0 }
    building_voids entry — location depends on carport_side:
      carport_side=left  → "location": "front_left"
      carport_side=right → "location": "front_right"
      { "id": "carport_cut", "location": "front_left",
        "width_m": 1.0, "depth_m": 4.0, "consumed_by": "carport" }
    (width_m 1.0 = extra 1 m beyond the 2 m base setback;
     depth_m 4.0 = 6 m carport depth − 2 m front setback)

  **fcp** (full carport): full 3 m setback entire depth — no L-notch.
  Include only the setback_element, NO building_void:
    { "type": "carport", "location": "side_setback", "covered": false,
      "width_m": 3.0, "depth_m": 6.0 }

  Room placement relative to the carport side:
  - Public column (great_room / kitchen) goes on the SAME side as the carport.
    Kitchen anchors to the rear of the carport side.
  - Private column (bedrooms + baths) goes on the OPPOSITE side.
  - zone_split.private_side = the side OPPOSITE the carport.
  Example: carport_side=left → public column left, private column right,
    zone_split private_side="right", building_void location="front_left".
- Master bedroom usually larger than the standard bedroom.
- Common T&B is typically publicly accessible (door off dining).
- Prefer placing common T&B against an exterior wall (rear or side boundary)
  so it can have a window for natural ventilation rather than an interior
  vent shaft (Sec. 809 is legal but a window is cheaper and standard in PH
  mid-market). Author the topology so common's adjacencies are compatible
  with exterior placement: don't trap it between rooms that fully enclose it.
  If the design genuinely needs an interior common (rare on squarish lots),
  it's still allowed — the solver will accept it.
- "Clustered baths / wet core" means the ensuite and common T&B share a
  hard plumbing wall (`ensuite <-> common`, kind: `wet_core`, min_shared_wall_m
  >= 1.2 m). The bath block sits BETWEEN the bedrooms — ensuite on the master
  side (private door), common on the standard-bedroom side (shared wall +
  door off the public LDK). The two baths form the acoustic + privacy buffer
  separating sleeping spaces. Do NOT put the wet core against the kitchen for
  this pattern; kitchen plumbing is independent.
- "Open plan" means living-dining-kitchen flow without walls between them
  (encode as adjacencies with min_shared_wall_m >= 1.5 m).

# Maid's room (helper's room) — conditional

Only include a maid's room when the brief asks for it (e.g., the user lists
"maid's room" in must_haves, or the intent text explicitly mentions a helper
or live-in maid). PH mid-market houses sometimes include one; if the brief is
silent, do not add it.

When the brief does ask for one:
- type: `maids_room`, zone: `service`, size_priority: `service_and_baths`
- It is a HABITABLE room (PD 1096 Sec. 806(1)) — it must touch an exterior
  wall for a window. The solver enforces this; your job is to NOT bury it.
- Legal minimum 6 sqm with 2.0 m least dimension. Aim for the legal minimum
  unless the brief says otherwise (mid-market houses keep this room small).
- Hard adjacency: `maids_room <-> kitchen` (min_shared_wall_m >= 0.7 m).
  The helper accesses the kitchen directly; no walking through public spaces.
- Place it inside the buildable shell, adjacent to the kitchen — typically
  on the kitchen's far side from the dining room, hugging the rear or service
  side of the house. It is NOT a setback element.
- It does not need (and should not have) a soft proximity to bedrooms, public
  rooms, or the master suite.

# Your task

Given a Brief, produce a topology JSON via the `submit_topology` tool. Use
the example briefs and their authored topologies below as guidance.
"""


# ---------- few-shot exemplars ----------

# Each tuple is (reverse-engineered example brief, exemplar filename). The
# brief is what a user might have written to elicit that topology — when
# Claude sees a new brief, it picks the closest exemplar feeling.
EXEMPLARS = [
    ("Standard mid-market 2-bedroom open-plan home. Comfortable living and "
     "dining, bathrooms convenient to the bedrooms, nothing exotic. "
     "Ensuite near master, common bath off the great room — distributed baths "
     "(no shared plumbing wall between the two bathrooms). Open-plan great "
     "room combines living, dining, and kitchen.",
     "1s/2br/squarish/1s_2br_sq_side_split_baths_ds_gr.json"),
    ("2-bedroom where the two bathrooms cluster together between the bedrooms "
     "and share a plumbing wall — the bath block sits BETWEEN master and the "
     "standard bedroom, acting as the acoustic buffer between sleeping spaces. "
     "Ensuite is on the master side, common on the standard-bedroom side with "
     "a public door off the great room.",
     "1s/2br/squarish/1s_2br_sq_side_split_baths_cl_gr.json"),
    ("2-bedroom with strict separation between the public side and the private "
     "side (bedrooms+baths). Traditional sala-comedor-kusina: separate living, "
     "dining, and kitchen rooms rather than a combined great room. Distributed "
     "baths — ensuite off master, common bath accessible from the living/dining "
     "area. Use when the brief calls for a formal or traditional layout.",
     "1s/2br/squarish/1s_2br_sq_side_split_baths_ds_ld.json"),
]


def _load(fname: str) -> Dict:
    with open(os.path.join(_TOPOLOGIES_DIR, fname), "r", encoding="utf-8") as f:
        return json.load(f)


_LAST_EXAMPLE_TOOL_USE_ID = None   # tracked across builds so llm.py can pair it


def build_few_shot_messages() -> List[Dict]:
    """Return a list of (user, assistant) message pairs for few-shot in-context
    learning. Each pair shows: example brief -> example topology submission.

    The API requires every assistant tool_use to be paired with a user
    tool_result on the next turn. We weave a synthetic 'Accepted.' tool_result
    into each subsequent user turn. The very last tool_use's pair is added by
    llm.py when it appends the live brief."""
    global _LAST_EXAMPLE_TOOL_USE_ID
    msgs = []
    prev_id = None
    for brief_text, fname in EXEMPLARS:
        topo = _load(fname)
        # tool_use.id must match ^[a-zA-Z0-9_-]+$ — strip the .json extension
        # and replace any other punctuation to keep the regex happy.
        slug = os.path.splitext(os.path.basename(fname))[0]
        tool_use_id = f"toolu_example_{slug}"
        brief_block = {"type": "text",
                       "text": f"Brief: {brief_text}\n"
                               f"Lot: 13.0 x 12.0 m (squarish shell, 156 sqm)"}
        if prev_id is None:
            msgs.append({"role": "user", "content": [brief_block]})
        else:
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": prev_id, "content": "Accepted."},
                brief_block,
            ]})
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id,
             "name": "submit_topology", "input": topo}
        ]})
        prev_id = tool_use_id
    _LAST_EXAMPLE_TOOL_USE_ID = prev_id
    return msgs


def last_example_tool_use_id() -> str:
    """The tool_use id of the final exemplar — llm.py wraps the live brief in
    a tool_result for this id so the conversation is structurally valid."""
    if _LAST_EXAMPLE_TOOL_USE_ID is None:
        # ensure the build has run at least once
        build_few_shot_messages()
    return _LAST_EXAMPLE_TOOL_USE_ID


# ---------- tool schema (Anthropic tool-use input_schema) ----------

# Forces Claude's output to a structured topology JSON our pipeline can parse
# without ambiguity. The solver validates further once the topology is built.
TOOL_SCHEMA = {
    "name": "submit_topology",
    "description": "Submit the final topology (adjacency graph + rules) for "
                   "the floor-plan solver to realize.",
    "input_schema": {
        "type": "object",
        "required": ["id", "label", "target_shell", "rooms", "adjacencies", "entry_point"],
        "properties": {
            "id": {"type": "string", "description": "snake_case identifier"},
            "label": {"type": "string", "description": "human-readable summary"},
            "target_shell": {"type": "string", "enum": ["narrow", "squarish", "wide"]},
            "rooms": {
                "type": "array", "minItems": 4,
                "items": {
                    "type": "object",
                    "required": ["id", "type", "zone", "size_priority"],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "zone": {"type": "string",
                                 "enum": ["public", "private", "service", "circulation"]},
                        "size_priority": {"type": "string",
                                          "enum": ["public_LDK", "master_bedroom",
                                                   "other_bedrooms", "service_and_baths"]},
                        "hosts_entry": {"type": "boolean"},
                    },
                },
            },
            "adjacencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["a", "b", "min_shared_wall_m"],
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                        "min_shared_wall_m": {"type": "number", "minimum": 0.1},
                        "kind": {"type": "string"},
                        "note": {"type": "string"},
                    },
                },
            },
            "soft_proximities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["a", "b", "weight"],
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                        "weight": {"type": "number"},
                        "note": {"type": "string"},
                    },
                },
            },
            "zone_split": {
                "type": "object",
                "properties": {
                    "axis": {"type": "string", "enum": ["vertical", "horizontal"]},
                    "private_side": {"type": "string",
                                     "enum": ["left", "right", "front", "rear"]},
                    "private_rooms": {"type": "array", "items": {"type": "string"}},
                    "public_rooms":  {"type": "array", "items": {"type": "string"}},
                },
            },
            "entry_point": {"type": "string", "description": "id of the room hosting the main entry"},
            "setback_elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "location": {"type": "string"},
                        "covered": {"type": "boolean"},
                        "behind": {"type": "string"},
                        "width_m": {"type": "number"},
                        "depth_m": {"type": "number"},
                    },
                },
            },
            "building_voids": {
                "type": "array",
                "description": "Rectangular cutouts from the buildable envelope. "
                               "Use only for the CCP claimed-carport L-notch.",
                "items": {
                    "type": "object",
                    "required": ["id", "location", "width_m", "depth_m", "consumed_by"],
                    "properties": {
                        "id": {"type": "string"},
                        "location": {"type": "string",
                                     "enum": ["front_right", "front_left",
                                              "rear_right", "rear_left"]},
                        "width_m": {"type": "number"},
                        "depth_m": {"type": "number"},
                        "consumed_by": {"type": "string"},
                    },
                },
            },
            "notes": {"type": "array", "items": {"type": "string"}},
        },
    },
}


def build_brief_message(brief, error_feedback=None) -> str:
    """Format a brief as the user-turn message for Claude."""
    s = brief.summary()
    s += f"\nshell: {brief.lot_area:.0f} sqm lot"
    if error_feedback:
        s += (f"\n\nYour previous topology attempt failed: {error_feedback}\n"
              f"Please revise the topology to address this and submit again.")
    return s
