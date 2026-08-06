"""Structured description of a solved plan, for grounding an image model.

See NANO_BANANA_RENDER_DESIGN.md §2. The polished-render feature sends a
rendered PNG *plus* this manifest, because the model regenerates the whole
diagram rather than annotating ours — so the only grounding available is what
we state in the prompt.

Deliberately a pure function of an ArchPlan: no network, no API key, no cost.
It can be exercised against the whole brief suite offline, which is the point
— if the manifest is wrong, everything downstream is wrong.

The `orientation` block is the valuable part. `solver/fixture_orientation.py`
derives, per room, which wall the bed head sits against, which wall carries
the kitchen sink/counter run, and which are a bath's wet and shower walls —
and stops deliberately short of placing furniture. Handing those hints to the
image model is what stops it putting a bed across a window or a toilet on the
wall it shares with the kitchen.
"""
from typing import Any, Dict, List, Optional

# Human-facing names; the model reads these, so prefer plain words over the
# catalog's internal type ids.
_ROOM_PROSE = {
    "master_bedroom": "master bedroom",
    "bedroom_standard": "bedroom",
    "living_room": "living room",
    "great_room": "combined living/dining great room",
    "dining_room": "dining room",
    "kitchen": "kitchen",
    "common_bath": "common toilet & bath",
    "ensuite_bath": "ensuite toilet & bath",
    "bath_toilet": "toilet & bath",
    "powder_room": "powder room (half bath)",
    "hallway": "hallway",
    "foyer": "foyer",
    "stairs": "staircase",
    "maids_room": "maid's room",
    "maids_bath": "maid's toilet & bath",
    "laundry": "laundry",
    "lanai": "lanai",
    "porch": "porch",
    "carport": "carport",
    "dirty_kitchen": "dirty kitchen (outdoor cooking)",
    "service_area": "service / laundry area",
}

_SIDE_PROSE = {"N": "north", "S": "south", "E": "east", "W": "west"}


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _rect(rc) -> List[float]:
    """[x0, y0, x1, y1] in metres, lot coordinates, origin at the lot's
    south-west corner and +y running toward the rear."""
    return [_r(rc.x0), _r(rc.y0), _r(rc.x1), _r(rc.y1)]


def _orientation_block(orient) -> Dict[str, str]:
    if orient is None:
        return {}
    out = {}
    for field, meaning in (
        ("head_wall", "bed headboard against this wall"),
        ("sink_wall", "kitchen sink and main counter run along this wall"),
        ("work_wall", "secondary counter run along this wall"),
        ("wet_wall", "toilet and lavatory against this wall"),
        ("shower_wall", "shower against this wall"),
    ):
        side = getattr(orient, field, None)
        if side:
            out[field] = f"{_SIDE_PROSE.get(side, side)} — {meaning}"
    return out


def build_manifest(plan, brief=None) -> Dict[str, Any]:
    """Ground-truth description of `plan` (an ArchPlan) for the image model.

    Coordinates are metres in lot space. The street is at the SOUTH edge —
    stated explicitly because a floor plan's orientation is otherwise
    ambiguous to a model, and the entry/porch/carport must land street-side.
    """
    layout = plan.layout
    lot = layout.lot
    env = lot.envelope()

    # A Door's `wall` is relative to room_a (or to room_b when room_a is the
    # literal string "exterior") — NOT to both rooms. Recording the same wall
    # letter against both sides would tell the model to cut a north-wall
    # opening in a room whose shared wall is its south. So the wall-bearing
    # side gets the geometry; the other side just gets a "connects to" note.
    doors_by_room: Dict[str, List[Dict]] = {}
    for d in plan.doors:
        a, b = d.room_a, d.room_b
        owner, other = (b, None) if a == "exterior" else (a, b)
        doors_by_room.setdefault(owner, []).append({
            "wall": d.wall,
            "position_m": _r(d.position_m),
            "clear_width_m": _r(d.clear_width_m),
            "kind": d.kind,
            "swings_into": d.swing_into,
            "hinge_at": getattr(d, "hinge_at", "low"),
            "on_cell": getattr(d, "cell_idx", 0),
            "leads_to": "outside" if a == "exterior" else other,
        })
        if other:
            doors_by_room.setdefault(other, []).append({
                "connects_to": owner,
                "kind": d.kind,
                "clear_width_m": _r(d.clear_width_m),
                "note": "same opening as the one listed on " + owner,
            })
    windows_by_room: Dict[str, List[Dict]] = {}
    for w in plan.windows:
        windows_by_room.setdefault(w.room, []).append({
            "wall": w.wall,
            "position_m": _r(w.position_m),
            "width_m": _r(w.width_m),
        })

    by_storey: Dict[int, List] = {}
    for r in layout.rooms:
        by_storey.setdefault(getattr(r, "storey", 1), []).append(r)

    storeys = []
    for st in sorted(by_storey):
        rooms = []
        for r in sorted(by_storey[st], key=lambda x: (x.rect.y0, x.rect.x0)):
            cells = [_rect(c) for c in r.cells]
            # The EXACT strings the technical drawing prints. Critical: the
            # prompt previously stated its own wording and its own numbers
            # ("MASTER BEDROOM (19.98 sqm)") while the supplied image showed
            # the renderer's ("MASTER BR" / "5.4x3.7 m . 20.0 sqm"). Handing
            # the model two different sets of numbers is what produced
            # invented dimensions. Sourced from core/render.py so they cannot
            # drift apart.
            try:
                from render import LABELS as _RL
                label = _RL.get(r.type, r.type.replace("_", " ").upper())
            except Exception:
                label = r.type.replace("_", " ").upper()
            if len(r.cells) > 1:
                sub = f"{r.area:.1f} sqm (L-shaped)"
            else:
                sub = (f"{r.rect.w:.1f}\u00d7{r.rect.h:.1f} m \u00b7 "
                       f"{r.rect.area:.1f} sqm")
            rooms.append({
                "id": r.id,
                "type": r.type,
                "description": _ROOM_PROSE.get(r.type, r.type.replace("_", " ")),
                "label_text": label,
                "label_sub_text": sub,
                "area_sqm": _r(r.area),
                "rect_m": cells[0],
                # An L-shaped room (a claimed dead strip) has a second cell.
                # Stated separately so the model draws one room, not two.
                "extra_cells_m": cells[1:],
                "l_shaped": len(cells) > 1,
                "orientation": _orientation_block(plan.orientations.get(r.id)),
                "doors": doors_by_room.get(r.id, []),
                "windows": windows_by_room.get(r.id, []),
            })
        storeys.append({
            "storey": st,
            "label": "ground floor" if st == 1 else f"floor {st}",
            "envelope_m": _rect(env),
            "floor_area_sqm": _r(sum(x["area_sqm"] for x in rooms)),
            "rooms": rooms,
        })

    # Setback elements (carport, dirty kitchen, service area, lanai, porch)
    # are Room objects on layout.elements — outside the building envelope but
    # inside the lot, and they must appear in the render (decision #5: cars
    # in carports, planting, dirty-kitchen equipment, lanai furniture).
    setbacks = []
    for el in getattr(layout, "elements", []) or []:
        setbacks.append({
            "type": el.type,
            "description": _ROOM_PROSE.get(el.type, el.type.replace("_", " ")),
            "rect_m": _rect(el.rect),
            "covered": bool(getattr(el, "covered", False)),
        })

    return {
        "street_side": "south",
        "note": ("Coordinates are metres in lot space; origin at the lot's "
                 "south-west corner, +x east, +y toward the rear. The street "
                 "is at the SOUTH edge."),
        "lot": {"width_m": _r(lot.width), "depth_m": _r(lot.depth),
                "setbacks_m": {"front": _r(lot.front), "rear": _r(lot.rear),
                               "left": _r(lot.left), "right": _r(lot.right)}},
        "buildable_envelope_m": _rect(env),
        "occupancy_class": getattr(lot, "occupancy_class", None),
        "storeys": storeys,
        "setback_elements": setbacks,
        "topology": {"id": plan.topology.id, "label": plan.topology.label},
        "brief_intent": (getattr(brief, "intent", None) or "")[:600] or None,
    }


def build_manifest_for_layout(layout, brief=None) -> Dict[str, Any]:
    """Manifest for a solved layout, single- OR multi-storey.

    Single-storey results carry one `layout.archplan`; multi-storey results
    carry `layout.archplans = [(floor_title, ArchPlan), ...]` — one plan per
    floor over its own per-floor sub-layout, with `archplan` left None.
    Decision #2 sends the COMPOSITE, so every floor is merged into a single
    manifest with one entry per storey.
    """
    if getattr(layout, "archplan", None) is not None:
        plans = [(None, layout.archplan)]
    else:
        plans = list(getattr(layout, "archplans", None) or [])
    if not plans:
        raise ValueError("layout has neither .archplan nor .archplans")

    base = None
    storeys: List[Dict[str, Any]] = []
    for title, plan in plans:
        m = build_manifest(plan, brief)
        if base is None:
            base = m
        else:
            # Later floors contribute only their storey block; lot, topology
            # and setback elements are shared (elements hang off the
            # ground-floor sub-layout only).
            for el in m["setback_elements"]:
                if el not in base["setback_elements"]:
                    base["setback_elements"].append(el)
        for st in m["storeys"]:
            if title:
                st["label"] = title.strip().lower()
            storeys.append(st)

    storeys.sort(key=lambda x: x["storey"])
    for i, st in enumerate(storeys, start=1):
        st["storey"] = i          # a 2-storey composite reads 1,2 — not 1,1
    base["storeys"] = storeys
    base["storey_count"] = len(storeys)
    base["composite"] = len(storeys) > 1
    return base
