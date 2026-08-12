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
# v4 (2026-08-06): the ask changes from GENERATE to RESTYLE for every room we
# can now furnish ourselves. Phase E.2 (solver/fixtures.py) places real
# rectangles for bedrooms, baths and kitchens, and polish.py now sends an
# image with that furniture already drawn — so for those rooms the instruction
# is "reproduce what is drawn", not "decide what to put there".
#
# This is a deliberate test, not an incremental tweak. v1-v3 all failed the
# same way: the model regenerates the whole diagram and invents ROOMS (v3
# added a phantom T&B and a closet, and dropped the kitchen's exterior door).
# More prescriptive prose made it worse, not better. If the model also cannot
# hold a plan it does not have to think about, it cannot do this job, and the
# styling should move into core/render.py where we control the geometry.
#
# Living/dining/great rooms, carports and planting are still GENERATED —
# fixtures.py does not place them yet. That split is stated explicitly per
# room, because a blanket "preserve everything" would suppress them entirely.
# v5 (2026-08-06): user review picked v2 as the best IMAGE, with exactly two
# defects — the kitchen's exterior service door missing (absent in ALL FOUR
# renders) and the T&B door relocated. Both are doors, so v5 attacks doors and
# changes nothing else.
#
# Two hypotheses, both acted on:
#   1. The model follows the IMAGE far more than the prose (the one consistent
#      finding across v1-v4). Both problem doors are 0.7-0.8 m wide, tucked
#      0.15 m into a corner, drawn as thin grey arcs — one of them next to a
#      window on the same wall. So polish.py now sends a raster with every
#      door OVERDRAWN in colour (core/render.py door_emphasis) and the prompt
#      explains the marking. That is a new lever; more forceful wording is not.
#   2. The T&B door opens into the KITCHEN, which our own validator flags as
#      unusual (bath_door_into_kitchen). The model is very likely "correcting"
#      it toward its priors, so v5 states it is deliberate rather than just
#      repeating the coordinates louder.
# v6 (2026-08-06): STOP ASKING THE MODEL FOR TEXT.
#
# v5 delivered what was asked of it — all 5 doors including the kitchen's
# exterior service door, missing from every render before it — which confirmed
# that marking the doors in the IMAGE works where four rounds of prose failed.
# But it also invented every dimension figure again (LIVING "3.7x2.6 m .
# 14.8 sqm" where the plan says "33.1 sqm (L-shaped)"), doubled the scale bar,
# and kept the magenta marker colour it was told was only a marker.
#
# Invented numbers are the one defect present in ALL FIVE renders regardless
# of wording, and they are the most dangerous one: a customer reads them as
# fact. So v6 removes the opportunity rather than the temptation — the model
# returns a picture with NO text anywhere, and render.py composites our own
# labels back on at our coordinates with our numbers. Deterministic, free, and
# it cannot drift.
#
# Same reasoning retires the scale bar and the ruler from the ask: both are
# text, both were wrong every time, and both are already correct in our own
# drawing, which the composite keeps.
PROMPT_VERSION = "6"

# Room types Phase E.2 furnishes. Everything else still needs generating.
_FURNISHED_BY_US = {
    "master_bedroom", "bedroom_standard", "maids_room",
    "common_bath", "ensuite_bath", "bath_toilet", "maids_bath", "powder_room",
    "kitchen",
}

# Keyed on the fixture-library id, which is what Fixture.kind now carries.
# The fallback at the call site is `kind.replace("_", " ")`, so a stale key
# degrades quietly into worse prose ("range electric") rather than an error —
# which is exactly why these are worth keeping current on a path whose whole
# difficulty is wording.
_FIXTURE_PROSE = {
    "bed_single": "single bed", "bed_double": "double bed",
    "bed_queen": "queen bed", "bed_king": "king bed",
    "nightstand": "bedside table", "wardrobe": "wardrobe",
    "toilet": "toilet", "lavatory": "lavatory basin",
    "shower_stall": "shower tray",
    "kitchen_counter": "kitchen counter run", "kitchen_sink": "kitchen sink",
    "range_electric": "cooking range", "fridge": "refrigerator",
}

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



def _drawn_fixtures_for(room: Dict[str, Any]) -> List[str]:
    """Prose for furniture ALREADY PRESENT in the supplied image (v4).

    Stated in words for the same reason openings are: the model follows prose
    and largely ignores the appended JSON. Each item carries its real size and
    the wall it backs onto, so "reproduce it" is checkable rather than vague.
    """
    out = []
    for f in room.get("fixtures_already_drawn", []):
        name = _FIXTURE_PROSE.get(f["kind"], f["kind"].replace("_", " "))
        w, h = f.get("size_m", [0, 0])
        where = ""
        if f.get("against_wall"):
            where = f", against the {_SIDE.get(f['against_wall'], f['against_wall'])} wall"
        out.append(f"{name} ({_fmt(w)} x {_fmt(h)} m){where}")
    return out


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


def _doors_block(manifest: Dict[str, Any]) -> List[str]:
    """Every door in the plan, in one place, at the top (v5).

    Previously each door was mentioned only under its own room, halfway down a
    long prompt. The kitchen's exterior service door was dropped in all four
    renders. Collecting them into a single numbered checklist gives the model
    something it can COUNT, and pairing it with the coloured marks in the image
    gives it something it can SEE.
    """
    rows = []
    for st in manifest["storeys"]:
        names = {x["id"]: x["description"] for x in st["rooms"]}
        for r in st["rooms"]:
            for d in r.get("doors", []):
                if "wall" not in d:
                    continue
                lead = d.get("leads_to")
                to = "the OUTSIDE" if lead == "outside" else names.get(lead, lead)
                note = ""
                if d.get("kind") == "service_door":
                    note = ("  <- EXTERIOR SERVICE DOOR. This is a real door to "
                            "the outside, NOT a window. It has been missing from "
                            "every previous attempt. Draw it.")
                elif d.get("kind") == "bath_door" and lead in ("kitchen",):
                    note = ("  <- DELIBERATE: this bathroom's only door opens "
                            "onto the kitchen. That is intentional in this "
                            "design. Do not move it to another wall or another "
                            "room, and do not add a second bathroom door.")
                rows.append(
                    f"  {len(rows) + 1}. {names.get(r['id'], r['id']).upper()}: "
                    f"{_fmt(d.get('clear_width_m', 0.8))} m door on its "
                    f"{_SIDE.get(d['wall'], d['wall'])} wall, "
                    f"{_place(d.get('position_m', 0.0), d['wall'])}, "
                    f"connecting to {to}, swinging into "
                    f"{names.get(d.get('swings_into'), d.get('swings_into'))}."
                    + note)
    if not rows:
        return []
    out = ["", f"=== DOORS — ALL {len(rows)} MUST APPEAR, AND NO OTHERS ===",
           "In the supplied image every door is OVERDRAWN IN MAGENTA/PINK so "
           "you cannot miss it: the opening across the wall, the door leaf and "
           "its swing arc. That colour is a MARKER, not part of the design — "
           "draw these doors in your normal architectural style, in exactly "
           "the positions marked.",
           f"There are {len(rows)} magenta marks. Your drawing must have "
           f"{len(rows)} doors, in those same places:"]
    out.extend(rows)
    out.append("Any opening NOT marked in magenta is a WINDOW. Do not convert "
               "a window into a door or a door into a window.")
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
    n_drawn = sum(len(r.get("fixtures_already_drawn", []))
                  for st in manifest["storeys"] for r in st["rooms"])
    lines.append(
        "RESTYLE the supplied floor plan into a polished, presentation-quality "
        "2D architectural drawing for a Philippine single-detached mid-market "
        "house. This is a redrawing task, NOT a design task: the layout and "
        "most of the furniture are already correct in the supplied image. Your "
        "job is line weight, palette, texture and finish."
    )
    n_rooms = sum(len(st["rooms"]) for st in manifest["storeys"])
    n_doors = sum(1 for st in manifest["storeys"] for r in st["rooms"]
                  for d in r.get("doors", []) if "wall" in d)
    n_wins = sum(len(r.get("windows", [])) for st in manifest["storeys"]
                 for r in st["rooms"])
    lines.append("")
    lines.append("=== OUTPUT FORMAT — ABSOLUTE, OVERRIDES EVERYTHING ELSE ===")
    lines.append(
        "1. YOUR IMAGE MUST CONTAIN NO TEXT WHATSOEVER. No room names, no "
        "dimensions, no areas, no scale bar, no numbers, no ruler, no title, "
        "no legend, no north letter, no watermark. Not one character. Room "
        "labels are added afterwards by the software; anything you write will "
        "be covered up or will conflict with the real figures."
    )
    lines.append(
        "2. YOUR IMAGE MUST CONTAIN NO MAGENTA OR PINK LINES. The bright "
        "magenta marks in the supplied image are a temporary marker showing "
        "you where the doors are. Draw those doors in normal architectural "
        "line work — thin dark leaf and a light swing arc. No magenta, no "
        "pink, anywhere in your output."
    )
    lines.append(
        "3. Fill the ENTIRE canvas with the lot, edge to edge — the boundary "
        "of your image IS the boundary of the lot. No white margin, no frame, "
        "no border, no drop shadow, no page. The composite depends on this "
        "alignment being exact."
    )
    lines.append("")
    lines.append("=== FIDELITY CONTRACT — OVERRIDES EVERYTHING BELOW ===")
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
        f"- The supplied image ALREADY CONTAINS {n_drawn} pieces of furniture "
        "and sanitary ware, drawn to scale in the correct positions. Reproduce "
        "every one of them where it already is. Do NOT move, resize, rotate, "
        "duplicate, remove or substitute any of them. They were placed by "
        "measurement and their positions are already verified to clear every "
        "door swing."
    )
    lines.append(
        "- Only the rooms explicitly marked 'FURNISH THIS ROOM' below are "
        "yours to fill. Every other room is already furnished — restyle it, "
        "do not redesign it."
    )
    lines.append(
        "- NO furniture, fixture, planting or rug may overlap a doorway, its "
        "swing arc, or the clear path through it."
    )
    lines.extend(_doors_block(manifest))
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
    lines.append("ROOM BY ROOM:")

    for st in manifest["storeys"]:
        names = {x["id"]: x["description"] for x in st["rooms"]}
        if composite:
            lines.append("")
            lines.append(f"  [{st['label'].upper()}]")
        for r in st["rooms"]:
            drawn = _drawn_fixtures_for(r)
            # A room we furnish ourselves is never handed generation prose —
            # offering both would invite the model to "improve" on measured
            # placement, which is the one thing v4 exists to prevent.
            items = [] if (drawn or r["type"] in _FURNISHED_BY_US) \
                else _furniture_for(r, st["rooms"])
            openings = _openings_for(r, names)
            if not (drawn or items or openings):
                continue
            lbl = r.get("label_text") or r["description"].upper()
            sub = r.get("label_sub_text") or f"{_fmt(r['area_sqm'])} sqm"
            # v6: no "LABEL THIS ROOM" instruction — the model writes nothing.
            # The label strings still go in the JSON so it knows what the room
            # IS, but they are ours to draw, not its.
            # Use the SHORT label, not the description. v6 headed each room
            # with `description` ("COMMON TOILET & BATH") and the model — which
            # writes text no matter what it is told — copied that string, which
            # is wider than the room and so overflows any mask we can put over
            # it. Headed "T&B" (v5's wording) its stray label stays inside the
            # room and the chip covers it.
            lines.append(f"  - {lbl} ({r['description']}, "
                         f"{sub} — the software writes this text, not you):")
            if drawn:
                lines.append("      * ALREADY DRAWN — reproduce exactly where "
                             "shown, add nothing: " + "; ".join(drawn) + ".")
            elif r["type"] in _FURNISHED_BY_US:
                # Phase E.2 ran and placed nothing here: the room is genuinely
                # too small for standard fixtures. Saying "furnish it" would
                # have the model draw furniture we have MEASURED will not fit.
                lines.append("      * leave this room UNFURNISHED — nothing "
                             "standard fits; draw the empty floor.")
            if items:
                lines.append("      * FURNISH THIS ROOM with "
                             + "; ".join(items) + ".")
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
    lines.append("PLACEMENT RULES (for the rooms marked FURNISH THIS ROOM only):")
    lines.append("  - Never block a door swing, a window, or a circulation path.")
    lines.append("  - Furniture must fit the stated room area; do not oversize it.")
    lines.append("  - Respect the wall functions given above — they come from the "
                 "plumbing and daylight layout and are not suggestions.")
    lines.append("  - Do not spill furniture from these rooms into a "
                 "neighbouring one that is already furnished.")

    lines.append("")
    lines.append("STYLE:")
    lines.append("  - Straight top-down orthographic plan view. No perspective, "
                 "no 3D, no isometric.")
    lines.append("  - Clean architectural line work: heavy exterior walls, lighter "
                 "interior partitions, doors shown with swing arcs.")
    lines.append("  - Muted, professional palette; subtle floor textures "
                 "distinguishing tile, timber and outdoor paving.")
    # v6: no north arrow, no scale bar, no ruler, no captions — all of these
    # are text or carry text, all were wrong in every previous render, and all
    # are already correct in our own drawing, which the composite retains.
    lines.append("  - NO scale bar, NO north arrow, NO ruler, NO caption, NO "
                 "labels. The software adds these. Draw only the building, "
                 "its contents, and the grounds.")
    lines.append("  - Leave the middle of each room visually calm — a label "
                 "will be composited over the centre of every room, so avoid "
                 "putting busy detail or strong pattern there.")

    lines.append("")
    lines.append("AUTHORITATIVE GEOMETRY (metres; use this over your reading of the "
                 "image if they ever disagree):")
    lines.append("```json")
    lines.append(json.dumps(manifest, indent=1, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convert-framed prompt (PROMPT_VERSION "C1")
# ---------------------------------------------------------------------------
#
# Six versions of build_prompt() above said "RESTYLE" / "redraw", and every one
# of them invented dimension figures. A user-written prompt opening "CONVERT
# the provided floor plan image into a 2D architectural render" got every
# figure right first try, having been told nothing about numbers — see
# NANO_BANANA_RENDER_DESIGN.md §9. That wording is preserved here verbatim.
#
# What this adds over the hand-written file kept at ai/prompts/convert_render.txt
# is that the COUNTS are derived from the manifest instead of typed in. That
# file is specific to the plan it was written for: reused on another brief it
# asserts "exactly 1 toilet/bath" and names LIVING and DINING rooms that do not
# exist, and the model duly dropped a bathroom and relocated the kitchen. The
# design doc already noted counts are derivable and therefore generalise; this
# is that, built.

CONVERT_PROMPT_VERSION = "C1"

_BATH_TYPES_P = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room",
                 "maids_bath"}
_BED_TYPES_P = {"master_bedroom", "bedroom_standard", "maids_room"}


def _all_rooms(manifest):
    return [r for st in manifest["storeys"] for r in st["rooms"]]


def _label_of(room):
    return room.get("label_text") or room.get("description", "").upper()


def _unique_doors(manifest):
    """Every doorway once. A door is listed on BOTH rooms it connects, but the
    second copy carries no `wall` — that is the existing dedupe key."""
    out = []
    for st in manifest["storeys"]:
        by_id = {r["id"]: r for r in st["rooms"]}
        for r in st["rooms"]:
            for d in r.get("doors", []):
                if "wall" not in d:
                    continue
                to = d.get("leads_to", "outside")
                other = ("outside" if to == "outside"
                         else _label_of(by_id.get(to, {"description": to})))
                out.append((_label_of(r), other, d.get("kind", "door")))
    return out


def build_convert_prompt(manifest: Dict[str, Any]) -> str:
    rooms = _all_rooms(manifest)
    labels = [_label_of(r) for r in rooms]
    els = [e for e in (manifest.get("setback_elements") or [])]
    el_labels = [(e.get("type") or "").upper() for e in els if e.get("type")]
    baths = [r for r in rooms if r.get("type") in _BATH_TYPES_P]
    beds = [r for r in rooms if r.get("type") in _BED_TYPES_P]
    doors = _unique_doors(manifest)
    n_wins = sum(len(r.get("windows", [])) for r in rooms)
    n_st = manifest.get("storey_count", len(manifest["storeys"]))
    has_carport = any((e.get("type") or "").lower() in ("carport", "garage")
                      for e in els)
    has_stairs = any(r.get("type") == "stairs" for r in rooms)
    great = [r for r in rooms if r.get("type") in ("great_room", "living_room",
                                                   "dining_room")]

    L: List[str] = []
    a = L.append
    a("Task: Convert the provided floor plan image into a 2D architectural render.")
    a("")
    a("Strict Constraints:")
    a("    * Maintain zero structural deviation from the provided image.")
    a("    * Do not add or remove any walls, rooms, doors, windows, or bathrooms.")
    a("    * Preserve the exact placement of all original doors and windows.")
    a("    * Keep the floor plan dimensions exactly as they are without expanding or shortening walls.")
    a("    * Do not add any room, alcove, closet, or fixture nook that is not in the provided image.")
    a("")
    a("What this plan contains — match these counts exactly:")
    a(f"    * EXACTLY {len(rooms)} interior rooms: {', '.join(labels)}."
      + (f" Plus outdoor: {', '.join(el_labels)}." if el_labels else "")
      + f" {len(labels) + len(el_labels)} labels in total.")
    if beds:
        dup = [x for x in {l for l in labels if labels.count(l) > 1}]
        a(f"    * EXACTLY {len(beds)} bedrooms."
          + (f" More than one is labelled {' and '.join(sorted(dup))} — that is"
             " correct and not a duplication." if dup else ""))
    a(f"    * EXACTLY {len(baths)} toilet/bath"
      f"{'s' if len(baths) != 1 else ''}: {', '.join(_label_of(b) for b in baths)}."
      " Do not add another bathroom or a powder room, and do not merge or drop"
      " any of these.")
    a(f"    * EXACTLY {len(doors)} doors:")
    for i, (frm, to, kind) in enumerate(doors, 1):
        via = "outside" if to == "outside" else to
        a(f"        {i}. {frm} to {via}"
          + (f"  ({kind.replace('_', ' ')})" if kind else ""))
    a(f"    * EXACTLY {n_wins} windows.")
    a(f"    * This plan is {n_st}-storey."
      + ("" if has_stairs else " There are no stairs — do not draw any."))
    if not has_carport:
        a("    * There is NO carport and NO garage — do not draw one, and do not draw a car.")
    a("")
    a("Setback Rules:")
    a("    * Render the outdoor setbacks for the first floor only. Render the setbacks as neutral ground.")
    if el_labels:
        a(f"    * The only outdoor areas are: {', '.join(el_labels)}. Do not add any other.")
    a("")
    a("Furniture & Visual Aids:")
    a("    * Every fixture and piece of furniture must sit ENTIRELY INSIDE the room it")
    a("      belongs to. Nothing may cross a wall into a neighbouring room, and no room")
    a("      may borrow floor area from another to fit its furniture.")
    a(f"    * EVERY bathroom holds, at minimum, THREE fixtures: a toilet (water closet),")
    a("      a lavatory (wash basin) and a shower. This plan has "
      f"{len(baths)} bathroom{'s' if len(baths) != 1 else ''}, so draw "
      f"{len(baths)} toilet{'s' if len(baths) != 1 else ''}, "
      f"{len(baths)} lavator{'ies' if len(baths) != 1 else 'y'} and "
      f"{len(baths)} shower{'s' if len(baths) != 1 else ''} in total"
      + (f" — one set in each of {', '.join(_label_of(b) for b in baths)}."
         if len(baths) > 1 else "."))
    a("      No bathroom may be left with only cabinets or an empty floor.")
    a("    * A bathtub is OPTIONAL. Include one only where the bathroom is large enough")
    a("      to hold it IN ADDITION to the toilet, lavatory and shower, without shrinking")
    a("      any of those three and without crossing a wall. If it does not fit that way,")
    a("      leave it out.")
    for g in great:
        lbl = _label_of(g)
        if g.get("type") == "great_room":
            a(f"    * {lbl} is a single combined living and dining space, so it holds BOTH")
            a("      the seating group and the dining set. It must contain ALL FOUR of these:")
            a("      (1) a sofa, (2) a centre/coffee table in front of it, (3) a TV, and")
            a("      (4) a dining table with its chairs. Armchairs are optional extras, not")
            a("      a substitute for any of the four. Do not split it into separate rooms")
            a("      and do not label any part of it LIVING or DINING.")
        elif g.get("type") == "living_room":
            a(f"    * {lbl} must contain a sofa, a centre/coffee table in front of it, and a TV.")
        else:
            a(f"    * {lbl} must contain a dining table with its chairs.")
    for r in rooms:
        if r.get("type") == "kitchen":
            a(f"    * {_label_of(r)} holds the counter run, sink, range and refrigerator.")
            a("      The counter must stop at the kitchen's own walls.")
        if r.get("type") == "hallway":
            a(f"    * {_label_of(r)} is circulation. Keep it EMPTY — no furniture of any kind.")
    if beds:
        a("    * Each bedroom holds one bed, a bedside table and a wardrobe."
          + (f" {_label_of(max(beds, key=lambda b: b.get('area_sqm', 0)))} is the"
             " largest and must read as the primary bedroom." if len(beds) > 1 else ""))
    for e in els:
        a(f"    * {(e.get('type') or '').upper()} is outdoor. Keep it free of indoor furniture.")
    a("    * Scale all fixtures accurately to the room size. If a fixture does not fit")
    a("      inside its own room, draw a smaller one — never spill it into the next room.")
    a("    * Ensure no furniture fully or partially blocks any door.")
    a("    * The bright magenta marks in the supplied image are a TEMPORARY MARKER showing")
    a("      you where the doors are. Draw those doors in normal architectural line work —")
    a("      a thin dark leaf and a light swing arc. No magenta or pink anywhere in your output.")
    a("    * Make sure all room names and dimension text remain clearly readable.")
    a("    * Every room label in the provided image must appear in your output with the")
    a("      same text, and every dimension figure must be copied exactly as written.")
    a("      Do not invent, round or alter any number.")
    return "\n".join(L)
