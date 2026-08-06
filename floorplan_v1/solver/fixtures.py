"""Phase E.2 — place real furniture/fixture RECTANGLES in each room.

Phase E.1 (`fixture_orientation.py`) assigns each room's walls a function —
which wall the bed head sits against, which carries the kitchen sink run,
which are a bath's wet and shower walls — and deliberately stops short of
placing anything. This module finishes the job.

Why real rectangles rather than a generative image (see
NANO_BANANA_RENDER_DESIGN.md): furniture placed here is QUERYABLE. "Does a
queen bed plus 600 mm of circulation actually fit in this bedroom?" is a
question a plan should be able to answer, and it is also a genuine test of
whether a topology's room sizes are usable rather than merely code-compliant.
An image model can only draw something plausible; it cannot tell you the bed
does not fit.

Placement is deterministic and post-solve. It never feeds back into the
solver and never affects validation — a room whose furniture does not fit is
reported, not rejected.

Dimensions are PH mid-market practice in metres.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from model import Rect, Room

# --- standard sizes (width across the wall it backs onto, depth out from it) --
BED = {                     # mattress footprint
    "single": (0.91, 1.90),
    "double": (1.37, 1.90),
    "queen":  (1.52, 2.03),
    "king":   (1.83, 2.03),
}
NIGHTSTAND = (0.45, 0.40)
WARDROBE_DEPTH = 0.60
TOILET = (0.40, 0.70)
LAVATORY = (0.55, 0.45)
SHOWER = (0.90, 0.90)
COUNTER_DEPTH = 0.60
SINK = (0.80, 0.55)
RANGE = (0.60, 0.60)
FRIDGE = (0.70, 0.70)
SOFA3 = (2.10, 0.85)
COFFEE_TABLE = (1.10, 0.60)
TV_CONSOLE = (1.40, 0.40)
DINING = {4: (1.40, 0.85), 6: (1.80, 0.95)}
CAR = (1.80, 4.50)

CLEARANCE = 0.60            # circulation a person needs alongside furniture

_SIDES = ("N", "S", "E", "W")
_OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


@dataclass
class Fixture:
    """One piece of furniture or sanitary ware, as a real rectangle."""
    room: str
    kind: str                     # "bed_queen", "toilet", "counter", "car", ...
    rect: Rect
    against: str = ""             # wall it backs onto: N/S/E/W
    cell_idx: int = 0             # which cell of an L-shaped room
    note: str = ""


@dataclass
class FixtureReport:
    """What could and could not be placed — the queryable output."""
    fixtures: List[Fixture] = field(default_factory=list)
    unfit: List[str] = field(default_factory=list)   # human-readable failures

    def add(self, f: Optional[Fixture]):
        if f is not None:
            self.fixtures.append(f)


def _against(cell: Rect, wall: str, width: float, depth: float,
             offset: float = 0.0) -> Optional[Rect]:
    """A `width` x `depth` rectangle backed onto `wall` of `cell`, its near
    edge `offset` along that wall from the west (N/S) or south (E/W) end.
    Returns None when it will not fit inside the cell."""
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    if wall in ("N", "S"):
        if width > w + 1e-9 or depth > h + 1e-9:
            return None
        x0 = min(max(cell.x0 + offset, cell.x0), cell.x1 - width)
        y0 = cell.y1 - depth if wall == "N" else cell.y0
        return Rect(x0, y0, x0 + width, y0 + depth)
    if depth > w + 1e-9 or width > h + 1e-9:
        return None
    y0 = min(max(cell.y0 + offset, cell.y0), cell.y1 - width)
    x0 = cell.x1 - depth if wall == "E" else cell.x0
    return Rect(x0, y0, x0 + depth, y0 + width)


def _centred(cell: Rect, wall: str, width: float, depth: float) -> Optional[Rect]:
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    span = w if wall in ("N", "S") else h
    return _against(cell, wall, width, depth, max(0.0, (span - width) / 2.0))



def _span_depth(cell: Rect, wall: str):
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    return (w, h) if wall in ("N", "S") else (h, w)


def _fit_on_wall(cell: Rect, wall: str, width: float, depth: float,
                 blockers: List[Rect], prefer: Optional[float] = None):
    """Search along `wall` for a clear `width` x `depth` position.

    Returns (rect, None) on success or (None, reason). Every placement goes
    through this: a first pass placed each fixture at ONE fixed offset and, if
    that collided, reported a dimensional failure — which produced 48 bogus
    "no 0.90 m shower fits" reports against baths that had 1.3 m of shower
    wall and 2.0 m of depth. A fixture must exhaust its wall before failing,
    and the reason must name the real cause.
    """
    span, avail = _span_depth(cell, wall)
    if width > span + 1e-9:
        return None, (f"needs {width:.2f} m along the {wall} wall, "
                      f"only {span:.2f} m there")
    if depth > avail + 1e-9:
        return None, (f"needs {depth:.2f} m of depth off the {wall} wall, "
                      f"only {avail:.2f} m there")
    lo, hi = 0.0, span - width
    target = (span - width) / 2.0 if prefer is None else prefer
    step = 0.05
    n = int(max(0.0, hi - lo) / step) + 1
    for off in sorted((lo + k * step for k in range(n)),
                      key=lambda v: abs(v - target)):
        cand = _against(cell, wall, width, depth, off)
        if cand is not None and not any(_overlaps(cand, b) for b in blockers):
            return cand, None
    return None, (f"no clear {width:.2f} x {depth:.2f} m spot on the {wall} "
                  f"wall — blocked by other fixtures")


def _fit_anywhere(cell: Rect, walls, width: float, depth: float,
                  blockers: List[Rect]):
    """Try each wall in order. On total failure, say so honestly: name every
    wall tried and whether the obstacle was SIZE or other fixtures. Reporting
    the last wall's reason alone reads as if only that wall was attempted."""
    reasons = []
    for wall in walls:
        r, why = _fit_on_wall(cell, wall, width, depth, blockers)
        if r is not None:
            return r, wall, None
        reasons.append((wall, why))
    tried = ",".join(w for w, _ in reasons)
    if all("blocked by other fixtures" in why for _, why in reasons):
        detail = "every wall is blocked by other fixtures"
    elif all("only" in why for _, why in reasons):
        detail = "no wall is large enough"
    else:
        detail = "; ".join(f"{w}: {why}" for w, why in reasons)
    return None, None, (f"no clear {width:.2f} x {depth:.2f} m spot on any wall "
                        f"(tried {tried}) — {detail}")


def _longest_free_wall(cell: Rect, avoid: set) -> str:
    """The longest wall not in `avoid` (typically the door walls)."""
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    order = sorted(_SIDES, key=lambda s: -(w if s in ("N", "S") else h))
    for s in order:
        if s not in avoid:
            return s
    return order[0]


def _bed_kind(room: Room, master_area: Optional[float]) -> str:
    """Ranked, not purely area-derived — the master must read as primary even
    when a standard bedroom has ended up physically larger (possible since the
    dead-strip claimer stopped enforcing master-supremacy)."""
    ladder = ["single", "double", "queen", "king"]
    a = room.area
    nat = 3 if a >= 13.0 else 2 if a >= 10.0 else 1 if a >= 7.5 else 0
    if room.type == "maids_room":
        return "single"
    if room.type == "bedroom_standard" and master_area is not None:
        m = 3 if master_area >= 13.0 else 2 if master_area >= 10.0 else \
            1 if master_area >= 7.5 else 0
        nat = max(0, min(nat, m - 1))
    return ladder[nat]


def _place_bedroom(room: Room, orient, door_walls: set,
                   master_area: Optional[float], rep: FixtureReport):
    cell = room.rect
    head = (orient.head_wall if orient and orient.head_wall
            else _longest_free_wall(cell, door_walls))
    kind = _bed_kind(room, master_area)
    bw, bd = BED[kind]
    bed = _centred(cell, head, bw, bd)
    if bed is None:
        rep.unfit.append(f"{room.id}: {kind} bed ({bw:.2f} x {bd:.2f} m) does "
                         f"not fit on the {head} wall of a "
                         f"{cell.w:.2f} x {cell.h:.2f} m room")
        return
    rep.add(Fixture(room.id, f"bed_{kind}", bed, against=head))

    # Circulation: a bed needs CLEARANCE on at least one long side.
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    span = w if head in ("N", "S") else h
    if span - bw < CLEARANCE - 1e-9:
        rep.unfit.append(f"{room.id}: {kind} bed leaves {span - bw:.2f} m beside it, "
                         f"under the {CLEARANCE:.2f} m circulation minimum")

    # Nightstand in the gap beside the bed, if there is one.
    if span - bw >= NIGHTSTAND[0]:
        off = (span - bw) / 2.0 - NIGHTSTAND[0]
        ns = _against(cell, head, NIGHTSTAND[0], NIGHTSTAND[1], max(0.0, off))
        if ns is not None and not _overlaps(ns, bed):
            rep.add(Fixture(room.id, "nightstand", ns, against=head))

    # Wardrobe: prefer a wall that is neither the head wall nor a door wall,
    # but try every wall before giving up.
    mine = [f.rect for f in rep.fixtures if f.room == room.id]
    preferred = [s for s in _SIDES if s not in (set(door_walls) | {head})]
    order = preferred + [s for s in _SIDES if s not in preferred]
    placed = False
    for wall in order:
        run = w if wall in ("N", "S") else h
        for ww in (min(1.80, run), 1.20, 0.90):
            if ww > run + 1e-9:
                continue
            wd, why = _fit_on_wall(cell, wall, ww, WARDROBE_DEPTH, mine)
            if wd is not None:
                rep.add(Fixture(room.id, "wardrobe", wd, against=wall))
                placed = True
                break
        if placed:
            break
    if not placed:
        rep.unfit.append(f"{room.id}: wardrobe — no clear 0.90 x "
                         f"{WARDROBE_DEPTH:.2f} m run on any wall "
                         f"(room is {w:.2f} x {h:.2f} m)")


def _place_bath(room: Room, orient, rep: FixtureReport):
    cell = room.rect
    wet = orient.wet_wall if orient and orient.wet_wall else "N"
    shower_wall = (orient.shower_wall if orient and orient.shower_wall
                   else _OPPOSITE.get(wet, "S"))
    powder = room.type == "powder_room"
    mine: List[Rect] = []

    t, why = _fit_on_wall(cell, wet, TOILET[0], TOILET[1], mine, prefer=0.05)
    if t is None:
        rep.unfit.append(f"{room.id}: toilet — {why}")
    else:
        rep.add(Fixture(room.id, "toilet", t, against=wet)); mine.append(t)

    lav, why = _fit_on_wall(cell, wet, LAVATORY[0], LAVATORY[1], mine)
    if lav is None:
        lav, w2, why = _fit_anywhere(
            cell, [s for s in _SIDES if s != wet], LAVATORY[0], LAVATORY[1], mine)
        if lav is not None:
            rep.add(Fixture(room.id, "lavatory", lav, against=w2)); mine.append(lav)
        else:
            rep.unfit.append(f"{room.id}: lavatory — {why}")
    else:
        rep.add(Fixture(room.id, "lavatory", lav, against=wet)); mine.append(lav)

    if powder:
        return
    # Shower: preferred wall first, then ANY wall. Only then is it a real
    # statement that the room cannot take one.
    order = [shower_wall] + [s for s in _SIDES if s != shower_wall]
    sh, wall, why = _fit_anywhere(cell, order, SHOWER[0], SHOWER[1], mine)
    if sh is None:
        rep.unfit.append(f"{room.id}: shower — {why}; room is "
                         f"{cell.w:.2f} x {cell.h:.2f} m = {room.area:.2f} sqm")
    else:
        rep.add(Fixture(room.id, "shower", sh, against=wall)); mine.append(sh)


def _place_kitchen(room: Room, orient, rep: FixtureReport):
    cell = room.rect
    sink_wall = orient.sink_wall if orient and orient.sink_wall else "N"
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    run = w if sink_wall in ("N", "S") else h

    counter = _against(cell, sink_wall, run, COUNTER_DEPTH)
    if counter is None:
        rep.unfit.append(f"{room.id}: no {COUNTER_DEPTH:.2f} m counter run fits")
        return
    rep.add(Fixture(room.id, "counter", counter, against=sink_wall,
                    note="main counter run"))
    rep.add(_centred(cell, sink_wall, SINK[0], SINK[1]) and
            Fixture(room.id, "sink", _centred(cell, sink_wall, SINK[0], SINK[1]),
                    against=sink_wall))
    if run >= SINK[0] + RANGE[0] + 0.10:
        rg = _against(cell, sink_wall, RANGE[0], RANGE[1], 0.05)
        rep.add(rg and Fixture(room.id, "range", rg, against=sink_wall))
    else:
        rep.unfit.append(f"{room.id}: counter run {run:.2f} m too short for "
                         f"sink + range side by side")
    if run >= SINK[0] + RANGE[0] + FRIDGE[0] + 0.20:
        fr = _against(cell, sink_wall, FRIDGE[0], FRIDGE[1], run - FRIDGE[0] - 0.05)
        rep.add(fr and Fixture(room.id, "fridge", fr, against=sink_wall))


def _overlaps(a: Rect, b: Rect, tol: float = 1e-6) -> bool:
    return (a.x0 < b.x1 - tol and a.x1 > b.x0 + tol and
            a.y0 < b.y1 - tol and a.y1 > b.y0 + tol)


def _door_zone(door, room: Room) -> Optional[Rect]:
    """The clear floor a doorway needs: its width along the wall, extended
    one door-width into the room. Nothing may sit here."""
    cells = room.cells
    c = cells[min(getattr(door, "cell_idx", 0), len(cells) - 1)]
    w = max(getattr(door, "clear_width_m", 0.8), 0.6)
    p = getattr(door, "position_m", 0.0)
    if door.wall in ("N", "S"):
        x0 = min(max(c.x0 + p, c.x0), c.x1 - w)
        return (Rect(x0, c.y1 - w, x0 + w, c.y1) if door.wall == "N"
                else Rect(x0, c.y0, x0 + w, c.y0 + w))
    y0 = min(max(c.y0 + p, c.y0), c.y1 - w)
    return (Rect(c.x1 - w, y0, c.x1, y0 + w) if door.wall == "E"
            else Rect(c.x0, y0, c.x0 + w, y0 + w))


_RUN_KINDS = {"counter"}          # fixtures that may be SHORTENED rather than moved


def _trim_run(f: "Fixture", zone: Rect) -> Optional[Rect]:
    """Shorten a wall run so it stops clear of `zone`, keeping the longer of
    the two remaining segments. A counter meeting a door on its own wall
    should end at the doorway, not vanish."""
    r = f.rect
    if f.against in ("N", "S"):
        left, right = zone.x0 - r.x0, r.x1 - zone.x1
        if max(left, right) < 0.60:
            return None                          # nothing usable survives
        return (Rect(r.x0, r.y0, zone.x0, r.y1) if left >= right
                else Rect(zone.x1, r.y0, r.x1, r.y1))
    down, up = zone.y0 - r.y0, r.y1 - zone.y1
    if max(down, up) < 0.60:
        return None
    return (Rect(r.x0, r.y0, r.x1, zone.y0) if down >= up
            else Rect(r.x0, zone.y1, r.x1, r.y1))


def _shift_along(f: "Fixture", cell: Rect, blockers: List[Rect]) -> Optional[Rect]:
    """Slide a discrete fixture along the wall it backs onto, looking for the
    nearest clear position. Beats deleting it outright."""
    r = f.rect
    w, h = r.x1 - r.x0, r.y1 - r.y0
    if f.against in ("N", "S"):
        lo, hi, cur = cell.x0, cell.x1 - w, r.x0
    else:
        lo, hi, cur = cell.y0, cell.y1 - h, r.y0
    if hi < lo:
        return None
    step = 0.05
    n = int((hi - lo) / step) + 1
    cands = sorted((lo + k * step for k in range(n)), key=lambda v: abs(v - cur))
    for v in cands:
        cand = (Rect(v, r.y0, v + w, r.y1) if f.against in ("N", "S")
                else Rect(r.x0, v, r.x1, v + h))
        if not any(_overlaps(cand, b) for b in blockers):
            return cand
    return None


def check_door_clearance(rep: "FixtureReport", layout, plan) -> None:
    """Guarantee nothing sits in a doorway's clear zone.

    This is what the generative render could not give: with real rectangles we
    can PROVE no furniture blocks a door instead of asking a model politely.

    Resolution order matters. A first pass simply deleted any offender, which
    produced 280 removals across the suite — nearly all of them artifacts: a
    kitchen counter running a full wall ALWAYS meets a door on that wall, and
    deleting it is absurd when shortening it is correct. So: trim runs, shift
    discrete pieces to the nearest clear spot, and only remove when neither
    works.
    """
    rooms = {r.id: r for r in layout.rooms}
    zones: Dict[str, List[Rect]] = {}
    for d in getattr(plan, "doors", []):
        for rid in (d.room_a, d.room_b):
            r = rooms.get(rid)
            if r is None:
                continue
            z = _door_zone(d, r)
            if z is not None:
                zones.setdefault(rid, []).append(z)

    keep: List[Fixture] = []
    for f in rep.fixtures:
        zs = zones.get(f.room, [])
        hit = next((z for z in zs if _overlaps(f.rect, z)), None)
        if hit is None:
            keep.append(f)
            continue
        room = rooms.get(f.room)
        cell = room.cells[min(f.cell_idx, len(room.cells) - 1)] if room else None
        others = [k.rect for k in keep if k.room == f.room]

        if f.kind in _RUN_KINDS:
            trimmed = _trim_run(f, hit)
            if trimmed is not None and not any(_overlaps(trimmed, z) for z in zs):
                f.rect = trimmed
                f.note = (f.note + "; trimmed clear of a doorway").strip("; ")
                keep.append(f)
                continue
        if cell is not None:
            moved = _shift_along(f, cell, zs + others)
            if moved is not None:
                f.rect = moved
                f.note = (f.note + "; shifted clear of a doorway").strip("; ")
                keep.append(f)
                continue
        rep.unfit.append(f"{f.room}: {f.kind} removed — no clear position "
                         f"that avoids a doorway")
    rep.fixtures = keep


_BEDROOMS = {"master_bedroom", "bedroom_standard", "maids_room"}
_BATHS = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room", "maids_bath"}


def place_fixtures(layout, plan) -> FixtureReport:
    """Place furniture for every room on `layout`, using `plan.orientations`.

    Returns both the fixtures and a list of things that did NOT fit — the
    latter is the point: it says which rooms are only nominally usable.
    """
    rep = FixtureReport()
    orientations = getattr(plan, "orientations", {}) or {}

    door_walls: Dict[str, set] = {}
    for d in getattr(plan, "doors", []):
        if d.room_a != "exterior":
            door_walls.setdefault(d.room_a, set()).add(d.wall)

    by_storey: Dict[int, List[Room]] = {}
    for r in layout.rooms:
        by_storey.setdefault(getattr(r, "storey", 1), []).append(r)

    for rooms in by_storey.values():
        master = next((r for r in rooms if r.type == "master_bedroom"), None)
        m_area = master.area if master else None
        for r in rooms:
            o = orientations.get(r.id)
            dw = door_walls.get(r.id, set())
            if r.type in _BEDROOMS:
                _place_bedroom(r, o, dw, m_area, rep)
            elif r.type in _BATHS:
                _place_bath(r, o, rep)
            elif r.type == "kitchen":
                _place_kitchen(r, o, rep)
    check_door_clearance(rep, layout, plan)
    return rep
