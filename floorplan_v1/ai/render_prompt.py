"""Prompt construction for the polished-render call (Nano Banana).

See NANO_BANANA_RENDER_DESIGN.md §2.2. Pure text assembly — no network, no
key, no cost — so it can be iterated on and diffed offline before any billed
call is made.

Design note: we do NOT simply dump the manifest JSON and hope. An image model
follows concrete, per-room instructions far better than it infers intent from
a data structure. So this module TRANSLATES the manifest into explicit
furniture instructions per room, grounded in that room's actual area and its
derived wall functions (bed head / sink run / wet wall / shower wall). The
JSON is still appended as the authoritative geometry reference, but the prose
is what does the work.
"""
import json
from typing import Any, Dict, List

# Bump to invalidate the render cache deliberately (design §5). Any change to
# the wording below should bump this, or stale images will be served.
#
# v3 (2026-08-06): v2 fixed what was MISSING (windows, swing arcs) but degraded
# what was already right — labels lost/merged their area figures, the kitchen's
# exterior door vanished, and dimensions were invented. Lengthening the prompt
# by ~40% pushed the "reproduce exactly" rule down the page and diluted it. So
# v3 does the opposite of v2: the fidelity contract moves to the TOP and is
# stated as a countable checklist, openings carry their exact POSITION along
# the wall rather than just naming the wall, and the L-shape instruction is
# dropped (two attempts, no effect, pure prompt budget).
#
# v2 (2026-08-06), after reviewing the first real render: the model follows the
# PROSE and largely ignores the appended JSON. Facts that must survive have to
# be stated in words. v1 left doors, windows and L-shaped rooms to the JSON
# and got: no windows on several exterior walls, inconsistent door swings, and
# an L-shaped living room drawn as a plain rectangle. v2 also pins the scale
# bar (v1 produced two overlapping, mutually inconsistent ones) and forbids
# labels overlapping furniture or crossing walls.
PROMPT_VERSION = "3"

_SIDE = {"N": "north", "S": "south", "E": "east", "W": "west"}


def _fmt(v: float) -> str:
    return f"{v:g}"


def _bed_size(area: float) -> str:
    if area >= 13.0:
        return "a king bed"
    if area >= 10.0:
        return "a queen bed"
    if area >= 7.5:
        return "a double bed"
    return "a single bed"


def _dining_seats(area: float) -> str:
    if area >= 12.0:
        return "a six-seat dining table"
    if area >= 8.0:
        return "a four-seat dining table"
    return "a compact four-seat dining table"


_BED_LADDER = ["a single bed", "a double bed", "a queen bed", "a king bed"]


def _bed_for(room: Dict[str, Any], peers) -> str:
    """Bed size by area, but RANKED so the master always reads as primary.

    Area alone is not enough: since the dead-strip claimer stopped enforcing
    master-supremacy (2026-08-06), a standard bedroom can end up physically
    larger than the master. Giving both a king would invert the hierarchy the
    drawing exists to communicate, so a standard is capped one rung below
    whatever the master gets.
    """
    if room["type"] == "maids_room":
        return "a single bed"
    mine = _BED_LADDER.index(_bed_size(room["area_sqm"]))
    if room["type"] == "bedroom_standard":
        master = next((p for p in (peers or ())
                       if p["type"] == "master_bedroom"), None)
        if master is not None:
            cap = _BED_LADDER.index(_bed_size(master["area_sqm"])) - 1
            mine = max(0, min(mine, cap))
    return _BED_LADDER[mine]


def _furniture_for(room: Dict[str, Any], peers=()) -> List[str]:
    """Concrete furniture for one room, scaled to its real area and obeying
    its derived wall functions. PH mid-market conventions.

    `peers` are the other rooms on the same storey — needed so bedroom
    hierarchy is ranked rather than taken from raw area."""
    t = room["type"]
    a = room["area_sqm"]
    o = room.get("orientation") or {}

    def side_of(field):
        raw = o.get(field)
        return raw.split(" ")[0] if raw else None       # "north — ..." -> "north"

    if t in ("master_bedroom", "bedroom_standard", "maids_room"):
        head = side_of("head_wall")
        bed = _bed_for(room, peers)
        items = [f"{bed} with its headboard against the "
                 f"{head or 'longest interior'} wall",
                 "a bedside table on each accessible side of the bed"
                 if a >= 9.0 else "one bedside table",
                 "a wardrobe against a wall that has no window"]
        if a >= 13.0:
            items.append("a small study desk and chair")
        return items

    if t == "kitchen":
        sink = side_of("sink_wall")
        work = side_of("work_wall")
        items = [f"a continuous counter along the {sink or 'exterior'} wall "
                 f"with an undermount sink centred on it",
                 "a four-burner range with overhead extractor",
                 "a full-height refrigerator at one end of the counter run",
                 "upper wall cabinets drawn as a lighter dashed band above the counter"]
        if work:
            items.append(f"a secondary counter run along the {work} wall")
        if a >= 11.0:
            items.append("a small island or peninsula if it does not block circulation")
        return items

    if t in ("common_bath", "ensuite_bath", "bath_toilet", "maids_bath"):
        wet = side_of("wet_wall")
        shower = side_of("shower_wall")
        return [f"a toilet and a lavatory/basin against the {wet or 'plumbing'} wall",
                f"a shower enclosure against the {shower or 'opposite'} wall, "
                f"drawn with a floor drain",
                "a mirror over the basin"]

    if t == "powder_room":
        wet = side_of("wet_wall")
        return [f"a toilet and a compact corner basin against the "
                f"{wet or 'plumbing'} wall",
                "NO shower — this is a half bath"]

    if t == "living_room":
        return ["a three-seat sofa facing the TV wall",
                "an armchair and a coffee table",
                "a low TV console against the wall opposite the sofa",
                "a rug under the seating group"]

    if t == "great_room":
        return ["a sofa set and coffee table forming the living zone",
                f"{_dining_seats(a * 0.4)} in the dining zone",
                "a low TV console facing the sofa",
                "a rug defining the living zone"]

    if t == "dining_room":
        return [_dining_seats(a) + " with chairs drawn around it",
                "a slim sideboard against a wall if space allows"]

    if t == "hallway":
        return ["keep clear — circulation only; at most a narrow console or runner"]

    if t == "foyer":
        return ["a shoe cabinet or console against one wall", "a doormat at the entry"]

    if t == "stairs":
        return ["treads drawn with an UP/DOWN direction arrow and a handrail line"]

    if t == "laundry":
        return ["a washing machine and dryer side by side", "a utility sink"]

    return []



def _place(pos: float, wall: str) -> str:
    """Where along the wall an opening starts.

    Naming only the wall (v2) was not enough — the model put openings wherever
    it liked and silently dropped the kitchen's exterior door. Door.position_m
    is measured from the WEST end on N/S walls and from the SOUTH end on E/W
    walls (see solver/architectural_plan.py::Door)."""
    frm = "west" if wall in ("N", "S") else "south"
    return f"starting {_fmt(pos)} m from its {frm} end"


def _openings_for(room: Dict[str, Any], names: Dict[str, str] = None) -> List[str]:
    """Doors and windows as PROSE.

    v1 left these to the JSON and the model ignored them — several exterior
    walls came back blank and door swings were inconsistent. Stated in words
    they survive."""
    names = names or {}

    def nm(rid):
        # Room IDs like "standard" / "br2" are internal; the model should read
        # human names or it will echo the id into the drawing.
        return names.get(rid, rid)

    out = []
    for d in room.get("doors", []):
        if "wall" not in d:
            continue                      # the far side of an opening listed elsewhere
        side = _SIDE.get(d["wall"], d["wall"])
        swing = d.get("swings_into")
        lead = d.get("leads_to")
        where = f"to the {nm(lead)}" if lead and lead != "outside" else (
            "to the outside" if lead == "outside" else "")
        out.append(
            f"a {_fmt(d.get('clear_width_m', 0.8))} m doorway on the {side} wall, "
            f"{_place(d.get('position_m', 0.0), d['wall'])} {where}".strip()
            + (f", drawn with a swing arc opening into the {nm(swing)}"
               if swing else "")
        )
    for w in room.get("windows", []):
        side = _SIDE.get(w["wall"], w["wall"])
        out.append(f"a {_fmt(w['width_m'])} m window on the {side} wall, "
                   f"{_place(w['position_m'], w['wall'])}")
    return out


def _shape_note(room: Dict[str, Any]) -> str:
    """Describe an L-shaped room in words.

    The manifest carries `l_shaped` and the alcove rectangle, but v1's render
    drew the living room as a plain rectangle and absorbed its alcove into
    circulation — the flag alone did not survive."""
    if not room.get("l_shaped"):
        return ""
    main = room["rect_m"]
    parts = []
    for cell in room.get("extra_cells_m", []):
        w, h = abs(cell[2] - cell[0]), abs(cell[3] - cell[1])
        if cell[3] <= main[1] + 1e-6:   rel = "south"
        elif cell[1] >= main[3] - 1e-6: rel = "north"
        elif cell[2] <= main[0] + 1e-6: rel = "west"
        else:                           rel = "east"
        parts.append(f"a {_fmt(w)} x {_fmt(h)} m alcove on its {rel} side")
    return ("THIS ROOM IS L-SHAPED: its main body plus "
            + " and ".join(parts)
            + ". Draw it as ONE room with an L outline — the alcove is part of "
              "this room, not a corridor or a separate space")


def _setback_furniture(el: Dict[str, Any]) -> List[str]:
    t = el["type"]
    rc = el.get("rect_m") or [0, 0, 0, 0]
    width = abs(rc[2] - rc[0])
    if t == "carport":
        n = 2 if width >= 5.2 else 1
        return [f"{n} car{'s' if n > 1 else ''} drawn in plan view, "
                f"parked nose-in toward the house"]
    if t == "porch":
        return ["a doormat and a potted plant beside the entry door"]
    if t == "lanai":
        return ["outdoor lounge seating and a low table", "potted plants"]
    if t == "dirty_kitchen":
        return ["an outdoor cooking range, a utility sink and open shelving"]
    if t == "service_area":
        return ["a washing machine, a laundry sink and a drying rack"]
    return []


def build_prompt(manifest: Dict[str, Any]) -> str:
    """Assemble the full instruction text for one polished render."""
    composite = manifest.get("composite", False)
    n_st = manifest.get("storey_count", len(manifest["storeys"]))

    lines: List[str] = []
    lines.append(
        "Redraw the supplied floor plan as a polished, presentation-quality 2D "
        "architectural floor plan for a Philippine single-detached mid-market "
        "house, fully furnished."
    )
    n_rooms = sum(len(st["rooms"]) for st in manifest["storeys"])
    n_doors = sum(1 for st in manifest["storeys"] for r in st["rooms"]
                  for d in r.get("doors", []) if "wall" in d)
    n_wins = sum(len(r.get("windows", [])) for st in manifest["storeys"]
                 for r in st["rooms"])
    lines.append("")
    lines.append("=== FIDELITY CONTRACT — READ FIRST, OVERRIDES EVERYTHING BELOW ===")
    lines.append(
        f"This plan has EXACTLY {n_rooms} rooms, {n_doors} doorways and "
        f"{n_wins} windows. Your drawing must contain exactly that many — no "
        "more, no fewer. Count them before you finish."
    )
    lines.append(
        "- Do NOT add, remove, merge, split, move, resize or rename any room, "
        "wall, doorway or window."
    )
    lines.append(
        "- Every doorway and window listed below MUST appear, on the wall "
        "stated and at the position stated along that wall. An exterior/service "
        "door is as important as an interior one — do not drop it."
    )
    lines.append(
        "- Room labels and their dimension/area figures must be copied "
        "VERBATIM from the list below. Never invent, merge, round or omit a "
        "number. If a label will not fit, shrink the text — do not edit it."
    )
    lines.append(
        "- NO furniture, fixture, planting or rug may overlap a doorway, its "
        "swing arc, or the clear path through it. Move the furniture."
    )
    lines.append("")
    lines.append("Other layout rules:")
    lines.append(
        "- Reproduce every room in the same relative position, proportion and "
        "adjacency as the supplied image and the JSON below. Do not add, remove, "
        "merge, split, move or rename any room."
    )
    lines.append(
        "- Keep every room name and its area figure exactly as given. Do not "
        "invent dimensions and do not alter the numbers."
    )
    lines.append(
        "- Keep every door and window on the wall stated below. Do not add "
        "openings that are not listed, and do not seal one that is."
    )
    lines.append(
        "- The street is at the SOUTH (bottom) edge. The main entry, porch and "
        "carport must stay on that side."
    )
    if composite:
        lines.append(
            f"- This is a {n_st}-storey house shown as ONE image with the floors "
            "side by side, ground floor on the LEFT. Keep that arrangement and "
            "title each floor."
        )
    lines.append("")
    lines.append("FURNISH every space as follows (plan view, drawn to scale):")

    for st in manifest["storeys"]:
        names = {x["id"]: x["description"] for x in st["rooms"]}
        if composite:
            lines.append("")
            lines.append(f"  [{st['label'].upper()}]")
        for r in st["rooms"]:
            items = _furniture_for(r, st["rooms"])
            openings = _openings_for(r, names)
            shape = ""   # L-shape prose dropped in v3 — see PROMPT_VERSION notes
            if not (items or openings or shape):
                continue
            lbl = r.get("label_text") or r["description"].upper()
            sub = r.get("label_sub_text") or f"{_fmt(r['area_sqm'])} sqm"
            lines.append(f"  - {r['description'].upper()}:")
            lines.append(f"      * LABEL THIS ROOM EXACTLY: \"{lbl}\" on the "
                         f"first line and \"{sub}\" beneath it. Copy both "
                         f"strings character for character.")
            if shape:
                lines.append(f"      * {shape}.")
            if items:
                lines.append("      * furnish with " + "; ".join(items) + ".")
            if openings:
                lines.append("      * openings — " + "; ".join(openings)
                             + ". Draw EVERY one of these and no others.")

    setbacks = [e for e in manifest.get("setback_elements", []) if _setback_furniture(e)]
    if setbacks:
        lines.append("")
        lines.append("OUTDOOR / SETBACK areas (outside the house walls, inside the lot):")
        for el in setbacks:
            lines.append(f"  - {el['description'].upper()}: "
                         + "; ".join(_setback_furniture(el)) + ".")
    lines.append("  - Plant lawn, shrubs or small trees in the remaining open lot area.")

    lines.append("")
    lines.append("PLACEMENT RULES:")
    lines.append("  - Never block a door swing, a window, or a circulation path.")
    lines.append("  - Furniture must fit the stated room area; do not oversize it.")
    lines.append("  - Respect the wall functions given above — they come from the "
                 "plumbing and daylight layout and are not suggestions.")

    lines.append("")
    lines.append("STYLE:")
    lines.append("  - Straight top-down orthographic plan view. No perspective, "
                 "no 3D, no isometric.")
    lines.append("  - Clean architectural line work: heavy exterior walls, lighter "
                 "interior partitions, doors shown with swing arcs.")
    lines.append("  - Muted, professional palette; subtle floor textures "
                 "distinguishing tile, timber and outdoor paving.")
    lines.append("  - Include a north arrow, and EXACTLY ONE scale bar. The "
                 "scale bar must have evenly spaced ticks with correct, "
                 "non-repeating labels. Do not draw two scale bars.")
    lines.append("  - Legible room labels with the area figure beneath, as in "
                 "the source image. Draw each label on a small opaque "
                 "rectangular background panel so the text stays legible over "
                 "flooring and furniture. Every label must sit INSIDE its own room, "
                 "must not cross a wall into a neighbouring room, and must not "
                 "be covered by furniture or planting. Move furniture before "
                 "you obscure a label.")
    lines.append("  - Keep the lot ruler along all four edges and the "
                 "'FRONT (street)' caption, as in the source image.")

    lines.append("")
    lines.append("AUTHORITATIVE GEOMETRY (metres; use this over your reading of the "
                 "image if they ever disagree):")
    lines.append("```json")
    lines.append(json.dumps(manifest, indent=1, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)
