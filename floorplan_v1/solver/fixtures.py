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

Dimensions are PH mid-market practice in metres, and since Layer A they come
from `fixture_library` (the `fixtures/` drawing library) rather than from
constants written here. The swap was exact — every constant this module used
to define already matched the library to the centimetre — so it changed no
geometry. What it bought is the data a bare `(w, d)` tuple cannot carry:
per-side clearance with a stated reason, anchoring, handedness and stretch
bounds. See `fixture_library.py`.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fixture_library import load_library
from model import Rect, Room, make_outside_probe, probe_point

LIB = load_library()

# --- standard sizes (width across the wall it backs onto, depth out from it) --
# Named lookups, not copied numbers: the library file is the source of truth
# and a size change there reaches placement without an edit here.
BED = {                     # mattress footprint
    "single": LIB.size("bed_single"),
    "double": LIB.size("bed_double"),
    "queen":  LIB.size("bed_queen"),
    "king":   LIB.size("bed_king"),
}
NIGHTSTAND = LIB.size("nightstand")
WARDROBE_DEPTH = LIB.get("wardrobe").d
TOILET = LIB.size("toilet")
LAVATORY = LIB.size("lavatory")
SHOWER = LIB.size("shower_stall")
COUNTER_DEPTH = LIB.get("kitchen_counter").d
SINK = LIB.size("kitchen_sink")
RANGE = LIB.size("range_electric")
FRIDGE = LIB.size("fridge")
SOFA3 = LIB.size("sofa_3seat")
COFFEE_TABLE = LIB.size("coffee_table")
TV_CONSOLE = LIB.size("tv_console")
DINING = {4: LIB.size("dining_4"), 6: LIB.size("dining_6")}
CAR = LIB.size("car")

_SIDES = ("N", "S", "E", "W")
_OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


# --- clear floor: furniture goes against the wall FACE ----------------------
#
# A Room's rect is the wall CENTRELINE, not the inside face. Adjacent rooms
# share an edge exactly — `br2` ends at x=4.60 and `br3` begins at x=4.60 —
# and the renderer draws the wall band STRADDLING that line, 0.05 m into each
# room for an interior partition.
#
# Placing furniture flush to the rect therefore buries it in the wall, and
# where two rooms share a party wall their furniture meets at the centreline:
# in the lobby-hub plan the two beds' headboards touched at a gap of exactly
# 0.000 m, reading as two beds shoved against each other with no wall between.
#
# So placement runs on the CLEAR FLOOR — the rect pulled in by half the wall
# thickness on every side that has a wall. Exterior walls are thicker, and
# which sides are exterior comes from `make_outside_probe`, the one shared
# definition the renderer also uses, so the furniture and the drawn wall can
# never disagree. A side that opens into the room's own alcove has no wall and
# is not inset.
from render import (WALL_THICKNESS_EXTERIOR,          # noqa: E402
                    WALL_THICKNESS_INTERIOR)


def _clear_cell(cell: Rect, siblings: List[Rect], faces_outside) -> Rect:
    """`cell` pulled in to the inside face of whatever wall bounds each side."""
    edge = {}
    for side in _SIDES:
        if any(_overlaps(_strip_behind(cell, side, 0.02), s) for s in siblings):
            edge[side] = 0.0                     # alcove mouth: no wall here
            continue
        outside = False
        if faces_outside is not None:
            try:
                outside = faces_outside(*probe_point(cell, side))
            except Exception:
                outside = False
        edge[side] = (WALL_THICKNESS_EXTERIOR if outside
                      else WALL_THICKNESS_INTERIOR) / 2.0
    out = Rect(cell.x0 + edge["W"], cell.y0 + edge["S"],
               cell.x1 - edge["E"], cell.y1 - edge["N"])
    # Degenerate guard: a cell thinner than its own walls would invert.
    if out.x1 - out.x0 < 0.20 or out.y1 - out.y0 < 0.20:
        return cell
    return out


class _RoomFloor:
    """A Room seen as its clear floor: same identity and true area, but `rect`
    and `cells` are inset to the wall faces. Placement, door clearance and the
    clearance check all run on this so they agree with the drawing."""

    __slots__ = ("_r", "rect", "cells")

    def __init__(self, room: Room, faces_outside):
        self._r = room
        raw = room.cells
        self.cells = [_clear_cell(c, [o for o in raw if o is not c],
                                  faces_outside) for c in raw]
        self.rect = self.cells[0]

    def __getattr__(self, name):     # id, type, area, storey, ... stay truthful
        return getattr(self._r, name)


def _floor_probe(layout):
    """`faces_outside` for the storey this layout describes, or None.

    Scoped to ONE storey: a multi-storey layout carries both floors' rooms and
    the upper footprint would mask the lower one's perimeter gaps.
    """
    try:
        env = layout.lot.envelope()
        storeys = {getattr(r, "storey", 1) for r in layout.rooms}
        one = min(storeys) if len(storeys) == 1 else None
        obstacles = [c for r in layout.rooms
                     if one is None or getattr(r, "storey", 1) == one
                     for c in r.cells]
        return make_outside_probe(env, obstacles)
    except Exception:
        return None


@dataclass
class Fixture:
    """One piece of furniture or sanitary ware, as a real rectangle.

    `kind` IS the library id — `LIB.get(f.kind)` always resolves. It used to be
    a private vocabulary that mostly-but-not-quite matched ("counter" for
    `kitchen_counter`, "sink" for `kitchen_sink`), and carrying two names for
    one thing is how a renderer ends up guessing which it was handed.
    """
    room: str
    kind: str                     # library id: "bed_queen", "kitchen_sink", ...
    rect: Rect
    against: str = ""             # wall it backs onto: N/S/E/W
    cell_idx: int = 0             # which cell of an L-shaped room
    note: str = ""


@dataclass
class ClearanceIssue:
    """A fixture that FITS but has too little floor kept clear around it.

    Deliberately a separate category from `unfit`. "No shower fits in this
    bath" and "the shower fits but you cannot open the door past it" are
    different findings about a room, and collapsing both into one list of
    strings loses the distinction that makes either actionable.

    Structured rather than pre-formatted because the whole point of Phase E.2
    is that furniture is QUERYABLE: `actual` and `required` let a caller rank
    by how badly a room misses, which a sentence cannot.
    """
    room: str
    fixture: str                  # library id
    side: str                     # local side: front | back | left | right
    required: float               # metres the library asks for
    actual: float                 # metres actually free
    blocked_by: str               # "wall" or the library id of the obstruction
    reason: str                   # the library's own words for why it is needed

    @property
    def shortfall(self) -> float:
        return self.required - self.actual

    def describe(self) -> str:
        by = ("the wall" if self.blocked_by == "wall"
              else f"the {self.blocked_by}")
        return (f"{self.room}: {self.fixture} has {self.actual:.2f} m clear to "
                f"its {self.side}, needs {self.required:.2f} m ({self.reason}) "
                f"— {by} is in the way")


@dataclass
class FixtureReport:
    """What could and could not be placed — the queryable output."""
    fixtures: List[Fixture] = field(default_factory=list)
    unfit: List[str] = field(default_factory=list)   # human-readable failures
    clearance: List[ClearanceIssue] = field(default_factory=list)

    def add(self, f: Optional[Fixture]):
        if f is not None:
            self.fixtures.append(f)

    def tight(self, min_shortfall: float = 0.0) -> List[ClearanceIssue]:
        """Clearance issues worst-first. `min_shortfall` filters out the
        near-misses — a 50 mm gap beside a WC is real but is not the finding
        you lead with when a kitchen is 400 mm short of a working aisle."""
        return sorted((c for c in self.clearance
                       if c.shortfall >= min_shortfall - 1e-9),
                      key=lambda c: -c.shortfall)


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
                 blockers: List[Rect], prefer: Optional[float] = None,
                 siblings: Optional[List[Rect]] = None):
    """Search along `wall` for a clear `width` x `depth` position.

    Returns (rect, None) on success or (None, reason). Every placement goes
    through this: a first pass placed each fixture at ONE fixed offset and, if
    that collided, reported a dimensional failure — which produced 48 bogus
    "no 0.90 m shower fits" reports against baths that had 1.3 m of shower
    wall and 2.0 m of depth. A fixture must exhaust its wall before failing,
    and the reason must name the real cause.

    `siblings` are the room's OTHER cells. Where they are given, a position
    whose back lands on the mouth of an alcove is rejected: that edge of the
    cell is an opening, not a wall, and a bed with its head there has no
    headboard wall at all. 12 fixtures in the suite were placed that way.
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
    blocked = False
    for off in sorted((lo + k * step for k in range(n)),
                      key=lambda v: abs(v - target)):
        cand = _against(cell, wall, width, depth, off)
        if cand is None or any(_overlaps(cand, b) for b in blockers):
            continue
        if siblings and not _backed_by_wall(cand, wall, siblings):
            blocked = True
            continue
        return cand, None
    if blocked:
        return None, (f"the {wall} side of this cell is the mouth of the "
                      f"room's alcove, not a wall")
    return None, (f"no clear {width:.2f} x {depth:.2f} m spot on the {wall} "
                  f"wall — blocked by other fixtures")


def _fit_anywhere(cell: Rect, walls, width: float, depth: float,
                  blockers: List[Rect], siblings: Optional[List[Rect]] = None):
    """Try each wall in order. On total failure, say so honestly: name every
    wall tried and whether the obstacle was SIZE or other fixtures. Reporting
    the last wall's reason alone reads as if only that wall was attempted."""
    reasons = []
    for wall in walls:
        r, why = _fit_on_wall(cell, wall, width, depth, blockers,
                              siblings=siblings)
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
    sibs = room.cells[1:]
    bed = _centred(cell, head, bw, bd)
    if bed is not None and sibs and not _backed_by_wall(bed, head, sibs):
        bed = None                    # centred position has no wall behind it
    if bed is None:
        bed, _why = _fit_on_wall(cell, head, bw, bd, [], siblings=sibs)
    if bed is None and sibs:
        # The chosen head wall is (partly) the alcove mouth. Another wall with
        # real masonry behind it beats a headboard against thin air.
        bed, alt, _why = _fit_anywhere(
            cell, [x for x in _SIDES if x != head], bw, bd, [], siblings=sibs)
        if bed is not None:
            head = alt
    if bed is None:
        rep.unfit.append(f"{room.id}: {kind} bed ({bw:.2f} x {bd:.2f} m) does "
                         f"not fit on the {head} wall of a "
                         f"{cell.w:.2f} x {cell.h:.2f} m room")
        return
    rep.add(Fixture(room.id, f"bed_{kind}", bed, against=head))

    # The bed's side-circulation check used to live here as a hand-rolled
    # `span - bw < CLEARANCE` test. It is now `check_clearances`, which reads
    # the same requirement off the bed's own manifest (right: 0.60,
    # "circulation down one long side") and applies the equivalent test to
    # every other fixture too.
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    span = w if head in ("N", "S") else h

    # Nightstand in the gap beside the bed, if there is one.
    if span - bw >= NIGHTSTAND[0]:
        off = (span - bw) / 2.0 - NIGHTSTAND[0]
        ns = _against(cell, head, NIGHTSTAND[0], NIGHTSTAND[1], max(0.0, off))
        if ns is not None and sibs and not _backed_by_wall(ns, head, sibs):
            ns = None
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
            wd, why = _fit_on_wall(cell, wall, ww, WARDROBE_DEPTH, mine,
                                   siblings=sibs)
            if wd is not None:
                rep.add(Fixture(room.id, "wardrobe", wd, against=wall))
                placed = True
                break
        if placed:
            break
    if not placed and len(room.cells) > 1:
        # A wardrobe is the natural tenant of an alcove: 0.60 m deep, and most
        # of the suite's alcoves are shallow limbs that suit nothing else.
        for ww in (1.80, 1.20, 0.90):
            wd, wall, idx = _fit_in_room(room, ww, WARDROBE_DEPTH, mine,
                                         must_wall=True, skip=0)
            if wd is not None:
                rep.add(Fixture(room.id, "wardrobe", wd, against=wall,
                                cell_idx=idx, note="in the room's alcove"))
                placed = True
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
    sibs = room.cells[1:]
    mine: List[Rect] = []

    # Tuck the WC toward the end of the wet wall, but not tighter than its own
    # manifest allows: 0.05 m was an invented number that put the pan 50 mm
    # from the return wall while the library asks 0.10 m of elbow room, and it
    # was the single largest source of clearance findings in the suite.
    # `_fit_on_wall` treats this as a preference, so a wall with no room to
    # honour it still places the WC rather than failing.
    _wc_elbow = LIB.get("toilet").clearance_for("left")
    t, why = _fit_on_wall(cell, wet, TOILET[0], TOILET[1], mine,
                          prefer=_wc_elbow.depth if _wc_elbow else 0.05,
                          siblings=sibs)
    if t is None:
        # The wet wall can turn out to be the mouth of the room's alcove, which
        # is no wall at all. Plumbing prefers the wet wall; it does not prefer
        # having no WC. Fall back the way the lavatory already does.
        t, wet2, why = _fit_anywhere(
            cell, [x for x in _SIDES if x != wet], TOILET[0], TOILET[1], mine,
            siblings=sibs)
        if t is not None:
            wet = wet2
    if t is None:
        rep.unfit.append(f"{room.id}: toilet — {why}")
    else:
        rep.add(Fixture(room.id, "toilet", t, against=wet)); mine.append(t)

    lav, why = _fit_on_wall(cell, wet, LAVATORY[0], LAVATORY[1], mine,
                            siblings=sibs)
    if lav is None:
        lav, w2, why = _fit_anywhere(
            cell, [s for s in _SIDES if s != wet], LAVATORY[0], LAVATORY[1],
            mine, siblings=sibs)
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
    sh, wall, why = _fit_anywhere(cell, order, SHOWER[0], SHOWER[1], mine,
                                  siblings=sibs)
    if sh is None and len(room.cells) > 1:
        sh, wall, idx = _fit_in_room(room, SHOWER[0], SHOWER[1], mine,
                                     must_wall=True, walls=order, skip=0)
        if sh is not None:
            rep.add(Fixture(room.id, "shower_stall", sh, against=wall,
                            cell_idx=idx, note="in the bath's alcove"))
            mine.append(sh)
            return
    if sh is None:
        rep.unfit.append(f"{room.id}: shower — {why}; room is "
                         f"{cell.w:.2f} x {cell.h:.2f} m = {room.area:.2f} sqm")
    else:
        rep.add(Fixture(room.id, "shower_stall", sh, against=wall)); mine.append(sh)


def _place_kitchen(room: Room, orient, rep: FixtureReport):
    cell = room.rect
    sink_wall = orient.sink_wall if orient and orient.sink_wall else "N"
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    run = w if sink_wall in ("N", "S") else h

    counter = _against(cell, sink_wall, run, COUNTER_DEPTH)
    if counter is None:
        rep.unfit.append(f"{room.id}: no {COUNTER_DEPTH:.2f} m counter run fits")
        return
    rep.add(Fixture(room.id, "kitchen_counter", counter, against=sink_wall,
                    note="main counter run"))

    # Appliances go in from the ENDS first, then the sink takes what is left in
    # the middle. The old order placed the sink dead-centre and the range at a
    # fixed 0.05 m from the end, each ignoring the other: the guard below
    # checks the TOTAL width fits, but two independently chosen offsets can
    # still collide, and on a 1.50 m run they did — sink 0.35–1.15 against
    # range 0.05–0.65. That was 9 hobs sitting inside a sink.
    #
    # `appliances` deliberately does NOT include the counter: the sink, range
    # and fridge are set INTO the run, and overlapping it is correct.
    appliances: List[Rect] = []
    if run >= SINK[0] + RANGE[0] + 0.10:
        rg = _against(cell, sink_wall, RANGE[0], RANGE[1], 0.05)
        if rg is not None:
            rep.add(Fixture(room.id, "range_electric", rg, against=sink_wall))
            appliances.append(rg)
    else:
        rep.unfit.append(f"{room.id}: counter run {run:.2f} m too short for "
                         f"sink + range side by side")
    if run >= SINK[0] + RANGE[0] + FRIDGE[0] + 0.20:
        fr = _against(cell, sink_wall, FRIDGE[0], FRIDGE[1], run - FRIDGE[0] - 0.05)
        if fr is not None:
            rep.add(Fixture(room.id, "fridge", fr, against=sink_wall))
            appliances.append(fr)

    sink, _why = _fit_on_wall(cell, sink_wall, SINK[0], SINK[1], appliances)
    if sink is not None:
        rep.add(Fixture(room.id, "kitchen_sink", sink, against=sink_wall))
    else:
        rep.unfit.append(f"{room.id}: kitchen sink — no clear {SINK[0]:.2f} m "
                         f"of counter left between the range and the fridge "
                         f"on a {run:.2f} m run")


def _overlaps(a: Rect, b: Rect, tol: float = 1e-6) -> bool:
    return (a.x0 < b.x1 - tol and a.x1 > b.x0 + tol and
            a.y0 < b.y1 - tol and a.y1 > b.y0 + tol)


# --- L-shaped rooms: the alcove is floor, not a hole -------------------------
#
# A room's `cells` are `rect` plus an optional `rect2` alcove, and since
# dead-strip claiming became always-on those alcoves are routine: 31 rooms in
# the suite hold 72.9 m² of them. Everything here used to look at `rect` only,
# so that floor may as well not have existed — furniture was deleted for want
# of somewhere to stand while an empty limb of the same room sat unused.
#
# The subtlety is that a cell's boundary is NOT all wall. Where two cells meet
# there is an OPENING, and a wardrobe backed onto an opening is furniture
# floating in mid-room. So a candidate position is checked against the real
# thing: is the sliver directly behind it inside a sibling cell?

def _strip_behind(r: Rect, wall: str, t: float) -> Rect:
    """The band of floor `t` deep immediately outside `wall` of `r`."""
    if wall == "N":
        return Rect(r.x0, r.y1, r.x1, r.y1 + t)
    if wall == "S":
        return Rect(r.x0, r.y0 - t, r.x1, r.y0)
    if wall == "E":
        return Rect(r.x1, r.y0, r.x1 + t, r.y1)
    return Rect(r.x0 - t, r.y0, r.x0, r.y1)


def _backed_by_wall(r: Rect, wall: str, siblings: List[Rect]) -> bool:
    """True when `r`'s `wall` side really is a wall, not the way into the
    room's other cell. Tested on the actual footprint rather than on the
    cell's whole side, because an alcove commonly meets only PART of a side —
    treating the entire side as open would refuse good positions."""
    strip = _strip_behind(r, wall, 0.02)
    return not any(_overlaps(strip, s) for s in siblings)


def _fixture_wd(f: "Fixture"):
    """(width along its backing wall, depth off it) — the fixture's own
    dimensions, independent of which wall it currently sits on."""
    w, h = f.rect.x1 - f.rect.x0, f.rect.y1 - f.rect.y0
    return (w, h) if f.against in ("N", "S") else (h, w)


def _fit_in_cell(room: Room, idx: int, width: float, depth: float,
                 blockers: List[Rect], must_wall: bool, walls=None):
    """Try to seat a `width` x `depth` fixture in cell `idx` of `room`.

    Returns (rect, wall) or (None, None). When `must_wall`, a position whose
    back is an opening into another cell is rejected.
    """
    cells = room.cells
    cell = cells[idx]
    sibs = [c for i, c in enumerate(cells) if i != idx]
    for wall in (walls or _SIDES):
        cand, _ = _fit_on_wall(cell, wall, width, depth, blockers)
        if cand is None:
            continue
        if must_wall and not _backed_by_wall(cand, wall, sibs):
            continue
        return cand, wall
    return None, None


def _fit_in_room(room: Room, width: float, depth: float, blockers: List[Rect],
                 must_wall: bool, walls=None, skip: int = -1):
    """Same, but sweeping every cell — primary first, then the alcoves.

    Primary first is deliberate and not just ordering convenience: an alcove
    is a NOOK. A bed or a counter run belongs in the body of the room, and
    only what spills over should end up in the limb.
    """
    for idx in range(len(room.cells)):
        if idx == skip:
            continue
        cand, wall = _fit_in_cell(room, idx, width, depth, blockers,
                                  must_wall, walls)
        if cand is not None:
            return cand, wall, idx
    return None, None, -1


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


_RUN_KINDS = {"kitchen_counter"}  # fixtures that may be SHORTENED rather than moved

# Which fixtures may be banished to the room's alcove when a doorway leaves
# them nowhere else to go. Only pieces that mean the same thing wherever they
# stand.
#
# The excluded ones are excluded on meaning, not geometry — they placed
# perfectly well in the alcove when this was unrestricted. A nightstand IS its
# adjacency to the bed, and a sink IS part of the counter run; three metres
# away in a nook, each becomes a drawing that quietly says something false. A
# plan honestly missing its sink is a finding the reader can act on. A plan
# showing the sink in the wrong place is one they cannot.
_ALCOVE_EXILE_OK = {"wardrobe", "fridge", "shower_stall"}

# Pieces free to sit on a DIFFERENT WALL of the same room. Wider than the
# exile set, because moving a lavatory or WC to another wall of its own bath
# keeps it in the wet room and reads correctly, where banishing it to a nook
# would not. Still excludes the position-defined pieces: a nightstand belongs
# beside the bed and a sink belongs in the counter run, wherever those are.
# Pairs that are SUPPOSED to overlap. A sink, range or fridge is set INTO the
# counter run, so the counter is not an obstruction to them — it is what they
# sit in. Treating it as one is not cosmetic: `check_door_clearance` passed the
# counter in the blocker list, so EVERY position along the counter wall read as
# occupied and the appliance was deleted instead of slid along the run. That
# accounted for 48 of the suite's 140 "did not fit" reports — the single
# largest category — in kitchens that had room all along.
_SET_INTO_COUNTER = {"kitchen_sink", "range_electric", "fridge"}


def _may_overlap(a_kind: str, b_kind: str) -> bool:
    return ((a_kind in _SET_INTO_COUNTER and b_kind == "kitchen_counter")
            or (b_kind in _SET_INTO_COUNTER and a_kind == "kitchen_counter"))


_RELOCATABLE = _ALCOVE_EXILE_OK | {"lavatory", "toilet"}


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
    # Door zones come from the TRUE room geometry, never the clear floor: a
    # door's `position_m` is measured along the wall from the ORIGINAL rect's
    # origin, so deriving the zone from an inset cell slides every zone off
    # its own doorway — which reads downstream as furniture blocking doors
    # that it is nowhere near.
    true_rooms = {r.id: r for r in layout.rooms}
    zones: Dict[str, List[Rect]] = {}
    for d in getattr(plan, "doors", []):
        for rid in (d.room_a, d.room_b):
            r = true_rooms.get(rid)
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
        # EVERY other fixture in the room, not just the ones already processed.
        # `keep` holds only what this loop has reached, so building the blocker
        # list from it made everything later in `rep.fixtures` invisible — and
        # a piece shifted out of a doorway would come to rest on top of it.
        # That accounted for 35 of the suite's 44 fixture-on-fixture overlaps
        # (a lavatory inside a WC, a nightstand inside a bed). Pieces already
        # processed are at their final position; the rest are at their placed
        # one, which is the best information available at this point.
        others = [o.rect for o in rep.fixtures
                  if o.room == f.room and o is not f
                  and not _may_overlap(f.kind, o.kind)]

        if f.kind in _RUN_KINDS:
            # No `others` check here on purpose: a counter run is SUPPOSED to
            # overlap its own sink, range and fridge — they are set into it.
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
        # Last resort before deleting: ANOTHER WALL. `_shift_along` only slides
        # along the wall the fixture already sits on, so a piece boxed in on
        # that one wall was thrown away while three other walls stood empty.
        # Removals were by far the largest category of "unfit" in the suite.
        # Restricted to pieces whose meaning does not depend on where they are:
        # a lavatory is a lavatory on any wall of its bath, a nightstand is
        # only a nightstand beside the bed.
        if room is not None and f.kind in _RELOCATABLE:
            fw, fd = _fixture_wd(f)
            spec = LIB.get(f.kind) if f.kind in LIB else None
            must = bool(spec and spec.must_back_wall)
            # A wet fixture prefers a wall that is already wet. Without this
            # the search takes walls in N/S/E/W order and cheerfully puts the
            # WC on the north wall and the basin on the south, which is two
            # plumbing walls in a 1.5 m bath — legal, drawn correctly, and
            # something no one would build.
            order = None
            if spec and spec.needs_plumbing_wall:
                wet = {o.against for o in rep.fixtures
                       if o.room == f.room and o is not f and o.against
                       and o.kind in LIB and LIB.get(o.kind).needs_plumbing_wall}
                order = ([s for s in _SIDES if s in wet]
                         + [s for s in _SIDES if s not in wet])
            cand, wall = _fit_in_cell(room, f.cell_idx, fw, fd,
                                      zs + others, must, walls=order)
            idx = f.cell_idx
            where = "on another wall"
            if cand is None and f.kind in _ALCOVE_EXILE_OK:
                cand, wall, idx = _fit_in_room(room, fw, fd, zs + others, must,
                                               skip=f.cell_idx)
                where = "to the room's alcove"
            if cand is not None:
                f.rect, f.against = cand, wall
                f.cell_idx = idx if idx >= 0 else f.cell_idx
                f.note = (f.note + f"; moved {where} "
                          "to clear a doorway").strip("; ")
                keep.append(f)
                continue
        rep.unfit.append(f"{f.room}: {f.kind} removed — no clear position "
                         f"that avoids a doorway")
    rep.fixtures = keep


# --- Layer B: clearance checking ------------------------------------------
#
# The library gives clearance per SIDE, in the symbol's own local space:
# front is +y (into the room), back is -y, left is -x, right is +x. Those
# sides rotate with the symbol, so they have to be resolved against the wall
# the fixture actually backs onto before they mean anything in room space.
#
# The library's local frame has +x right and +y front, and the placement
# transform is `scale(S, -S) rotate(θ)`, so at θ=0 local +y points NORTH and
# local +x points EAST — i.e. θ=0 is a fixture backed onto its SOUTH wall.
# Each 90° step rotates the whole frame from there.
_LOCAL_TO_GLOBAL = {
    "S": {"front": "N", "back": "S", "right": "E", "left": "W"},
    "E": {"front": "W", "back": "E", "right": "N", "left": "S"},
    "N": {"front": "S", "back": "N", "right": "W", "left": "E"},
    "W": {"front": "E", "back": "W", "right": "S", "left": "N"},
}


# How much of an approach a neighbour must cover before it counts as blocking
# it. A fixture that clips the CORNER of another's approach has not taken it
# away: in an 8x11 narrow bath the shower overlaps the WC's 0.40 m approach by
# 0.05 m, leaving seven eighths of it open and the whole room beyond, and
# counting that as "0.00 m clear in front of the toilet" was the checker's
# single worst false positive — it produced the largest shortfall in the suite
# for a bath that is genuinely usable.
_BLOCK_FRAC = 0.5


def _free_depth(r: Rect, cell: Rect, side: str, blockers: List["Fixture"],
                siblings: Optional[List[Rect]] = None):
    """How much clear floor there really is off `side` of `r`, and what ends
    it — the room boundary, or the nearest fixture in the way.

    An obstruction counts only when it covers more than half the width of the
    approach (`_BLOCK_FRAC`): a wardrobe two metres down the wall does not
    shorten the floor in front of a bed, and neither does a shower tray
    catching one corner of it. Doorways deliberately do NOT count — a doorway
    IS circulation, and `check_door_clearance` has already guaranteed nothing
    solid is standing in one.

    Returns (depth, blocker, side) — blocker is a Fixture, or None for the
    wall; side is echoed back so callers can tell which way was measured.
    """
    if side == "N":
        limit, along = cell.y1 - r.y1, (r.x0, r.x1)
    elif side == "S":
        limit, along = r.y0 - cell.y0, (r.x0, r.x1)
    elif side == "E":
        limit, along = cell.x1 - r.x1, (r.y0, r.y1)
    else:
        limit, along = r.x0 - cell.x0, (r.y0, r.y1)

    width = max(along[1] - along[0], 1e-9)
    limit = max(0.0, limit)
    # Where the cell's edge is an OPENING into the room's other cell, the floor
    # carries on and so does the clearance. Measuring to the cell edge treats
    # an alcove mouth as a wall and reports a fixture as boxed in by nothing.
    for s in (siblings or ()):
        probe = _strip_behind(_strip_behind(r, side, limit), side, 0.02)
        if not _overlaps(probe, s):
            continue
        limit += (s.y1 - s.y0 if side in ("N", "S") else s.x1 - s.x0)
        break

    best, who = limit, None
    for b in blockers:
        o = b.rect
        if side in ("N", "S"):
            cross, near = (o.x0, o.x1), (o.y0 - r.y1 if side == "N"
                                         else r.y0 - o.y1)
        else:
            cross, near = (o.y0, o.y1), (o.x0 - r.x1 if side == "E"
                                         else r.x0 - o.x1)
        overlap = min(cross[1], along[1]) - max(cross[0], along[0])
        if overlap / width <= _BLOCK_FRAC:
            continue                      # clips the approach; does not take it
        if -1e-9 <= near < best:
            best, who = max(0.0, near), b
    return best, who, side


def _sides_to_test(spec, c) -> List[str]:
    """Which local side(s) actually have to satisfy clearance `c`.

    Usually just the one named. The exception is a side-circulation clearance
    on a piece that is NOT handed and names only one of left/right — a bed's
    `right: 0.60, "circulation down one long side"`. That piece mirrors freely,
    so which side the library happened to draw it on carries no meaning, and
    demanding the gap on that specific side reports a bedroom as cramped when
    the aisle is simply on the other side of the bed. Either side satisfies it.

    When a manifest names BOTH left and right (the WC's 0.10 elbow room) each
    is required on its own, and this returns them separately.
    """
    if c.side not in ("left", "right") or spec.handed:
        return [c.side]
    named = {x.side for x in spec.clearance}
    if "left" in named and "right" in named:
        return [c.side]
    return ["left", "right"]


def check_clearances(rep: "FixtureReport", layout, floors=None) -> None:
    """Measure the floor kept clear around every placed fixture.

    This replaces a single `CLEARANCE = 0.60` applied to one fixture (the bed)
    with the library's per-side, per-reason numbers applied to all of them.
    The numbers are not cosmetic: every wet fixture asks 0.90 m in front, not
    0.60, so the old check was optimistic by 300 mm across every kitchen in
    the catalog. (The check it replaces was also inert — it never fired once
    across the 61 floors in the suite.)

    Reports only. Nothing is moved or dropped — a tight room is a finding
    about the topology, and silently shuffling furniture to make the finding
    go away is how a plan comes to look better than the house would be.
    """
    rooms = floors or {r.id: r for r in layout.rooms}
    found = []                            # (fixture, blocker, issue)
    for f in rep.fixtures:
        try:
            spec = LIB.get(f.kind)
        except KeyError:
            continue                      # not a library piece; nothing to check
        room = rooms.get(f.room)
        if room is None or not spec.clearance:
            continue
        cells = room.cells
        ci = min(f.cell_idx, len(cells) - 1)
        cell = cells[ci]
        sibs = [c for i, c in enumerate(cells) if i != ci]
        sides = _LOCAL_TO_GLOBAL.get(f.against)
        if sides is None:
            continue                      # free-standing; no back wall to rotate from
        others = [o for o in rep.fixtures if o.room == f.room and o is not f]
        for c in spec.clearance:
            if c.side == "back" and spec.must_back_wall:
                continue                  # the back IS the wall, on purpose
            local = _sides_to_test(spec, c)
            best = None
            for ls in local:
                g = sides.get(ls)
                if g is None:
                    continue
                actual, who, gdir = _free_depth(f.rect, cell, g, others, sibs)
                if best is None or actual > best[0]:
                    best = (actual, who, gdir)
            if best is None or best[0] >= c.depth - 1e-9:
                continue
            found.append((f, best[1], best[2], ClearanceIssue(
                room=f.room, fixture=f.kind, side="|".join(local),
                required=c.depth, actual=best[0],
                blocked_by=best[1].kind if best[1] else "wall",
                reason=c.reason)))
    rep.clearance.extend(_dedupe_facing(found))


def _dedupe_facing(found) -> List[ClearanceIssue]:
    """Collapse the two halves of a shared gap into one finding.

    A bed whose foot faces a wardrobe 0.35 m away breaks both pieces' front
    clearance, but there is ONE problem there and one thing to do about it.
    Reporting it from both sides doubles the count and makes a tight bedroom
    look like two tight bedrooms. The surviving record is the one asking for
    more room, since satisfying it satisfies the other.

    Keyed on the DIRECTION as well as the pair. Keying on the pair alone
    silently kept only one issue per neighbour, so a piece whose front and
    side were both blocked by the same wrap-around neighbour — two distinct
    gaps — would have had one of them escape collapse entirely.
    """
    by_edge = {}
    for f, blocker, side, issue in found:
        if blocker is not None:
            by_edge[(id(f), id(blocker), side)] = issue
    drop = set()
    for (a, b, side), issue in by_edge.items():
        other = by_edge.get((b, a, _OPPOSITE[side]))
        if other is None or id(issue) in drop or id(other) in drop:
            continue
        loser = (other if (issue.required, issue.shortfall, issue.fixture) >=
                 (other.required, other.shortfall, other.fixture) else issue)
        drop.add(id(loser))
    return [i for _, _, _, i in found if id(i) not in drop]


def _clip_to_clear_floor(rep: "FixtureReport", floors) -> None:
    """Pull every fixture inside the wall FACES.

    Applied to the RESULT rather than to the search space, and that ordering is
    the whole point. Insetting before placement shrinks the room the placer is
    reasoning about, and fixtures start falling out of rooms that can hold them
    perfectly well — tried it, and both bedrooms of the lobby-hub plan lost
    their beds, which is a worse drawing than the one being fixed.

    Clipping afterwards costs nothing: a bed backed onto a party wall loses
    50 mm of its nominal length and gains a 0.10 m gap from the bed on the
    other side, which is exactly the wall now drawn between them.
    """
    for f in rep.fixtures:
        fl = floors.get(f.room)
        if fl is None:
            continue
        cell = fl.cells[min(f.cell_idx, len(fl.cells) - 1)]
        r = f.rect
        clipped = Rect(max(r.x0, cell.x0), max(r.y0, cell.y0),
                       min(r.x1, cell.x1), min(r.y1, cell.y1))
        if clipped.x1 - clipped.x0 > 0.05 and clipped.y1 - clipped.y0 > 0.05:
            f.rect = clipped


# --- Layer D: the public rooms -----------------------------------------------
#
# Until now living, dining and great rooms were placed by nothing, so the
# public half of every furnished plan came out empty while the bedrooms and
# baths were fully fitted. That reads as an unfinished drawing rather than a
# sparse one, which is why this matters more than prettier symbols did.
#
# The library's public-room pieces need anchors the bedroom/bath placers never
# used: dining tables are `center` (positioned by their middle, in open floor),
# coffee tables and armchairs are `free`. Both are handled here. `corner`
# (sofa_l) is deliberately NOT — it needs two walls meeting at the footprint
# origin and an L footprint on Fixture, and a 3-seat sofa against one wall is
# the honest fallback until that exists.

_PUBLIC = {"great_room", "living_room", "dining_room", "family_room"}
_CARPORT = {"carport", "garage"}


def _centred_rect(cell: Rect, w: float, d: float) -> Optional[Rect]:
    """A w x d rectangle on the centre of `cell`. None if it does not fit."""
    if w > (cell.x1 - cell.x0) + 1e-9 or d > (cell.y1 - cell.y0) + 1e-9:
        return None
    cx, cy = (cell.x0 + cell.x1) / 2.0, (cell.y0 + cell.y1) / 2.0
    return Rect(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)


def _halves(cell: Rect):
    """Split a cell across its LONGER axis. A great_room holds both a seating
    group and a dining set, and they need separate floor or the dining table
    lands in the middle of the sofa."""
    w, h = cell.x1 - cell.x0, cell.y1 - cell.y0
    if w >= h:
        mid = (cell.x0 + cell.x1) / 2.0
        return Rect(cell.x0, cell.y0, mid, cell.y1), Rect(mid, cell.y0, cell.x1, cell.y1)
    mid = (cell.y0 + cell.y1) / 2.0
    return Rect(cell.x0, cell.y0, cell.x1, mid), Rect(cell.x0, mid, cell.x1, cell.y1)


def _dining_for(area: float):
    """Table by the floor actually available, largest first. Sized off the ZONE
    rather than the whole room: in a great_room the dining set only gets half."""
    for fid, need in (("dining_6", 11.0), ("dining_4", 7.5),
                      ("dining_compact_4", 5.0)):
        if area >= need:
            return fid
    return None


def _place_seating(room, zone: Rect, siblings, door_walls: set,
                   blockers: List[Rect], rep: "FixtureReport") -> None:
    """Sofa against the best wall of `zone`, coffee table in front of it, TV
    console opposite. The coffee table is the library's `free` anchor: it is
    positioned RELATIVE to the sofa, not to a wall."""
    wall = _longest_free_wall(zone, set(door_walls))
    sibs = list(siblings)
    sofa = None
    for fid in ("sofa_3seat", "sofa_2seat"):
        w, d = LIB.size(fid)
        cand, _ = _fit_on_wall(zone, wall, w, d, blockers, siblings=sibs)
        if cand is not None:
            rep.add(Fixture(room.id, fid, cand, against=wall))
            blockers.append(cand)
            sofa = (cand, fid)
            break
    if sofa is None:
        rep.unfit.append(f"{room.id}: no sofa fits on the {wall} side "
                         f"({zone.x1 - zone.x0:.2f} x {zone.y1 - zone.y0:.2f} m zone)")
        return

    srect, _fid = sofa
    cw, cd = LIB.size("coffee_table")
    gap = 0.45                      # the library's own front clearance
    if wall in ("N", "S"):
        cx = (srect.x0 + srect.x1) / 2.0
        y0 = srect.y0 - gap - cd if wall == "N" else srect.y1 + gap
        coffee = Rect(cx - cw / 2, y0, cx + cw / 2, y0 + cd)
    else:
        cy = (srect.y0 + srect.y1) / 2.0
        x0 = srect.x0 - gap - cw if wall == "E" else srect.x1 + gap
        coffee = Rect(x0, cy - cd / 2, x0 + cw, cy + cd / 2)
    inside = (zone.x0 - 1e-6 <= coffee.x0 and coffee.x1 <= zone.x1 + 1e-6
              and zone.y0 - 1e-6 <= coffee.y0 and coffee.y1 <= zone.y1 + 1e-6)
    if inside and not any(_overlaps(coffee, b) for b in blockers):
        rep.add(Fixture(room.id, "coffee_table", coffee, against=wall,
                        note="in front of the sofa"))
        blockers.append(coffee)

    tw, td = LIB.size("tv_console")
    opp = _OPPOSITE[wall]
    tv, _ = _fit_on_wall(zone, opp, tw, td, blockers, siblings=sibs)
    if tv is not None:
        rep.add(Fixture(room.id, "tv_console", tv, against=opp,
                        note="facing the sofa"))
        blockers.append(tv)


def _place_dining(room, zone: Rect, blockers: List[Rect],
                  rep: "FixtureReport") -> None:
    """Dining table on the centre of `zone` — the library's `center` anchor,
    the first placement in this module not measured from a wall."""
    area = (zone.x1 - zone.x0) * (zone.y1 - zone.y0)
    fid = _dining_for(area)
    if fid is None:
        rep.unfit.append(f"{room.id}: no dining table fits — zone is "
                         f"{area:.1f} m², the smallest table needs 5.0")
        return
    w, d = LIB.size(fid)
    rect = _centred_rect(zone, w, d)
    if rect is None or any(_overlaps(rect, b) for b in blockers):
        rep.unfit.append(f"{room.id}: {fid} does not fit clear on the centre "
                         f"of its zone")
        return
    # `against` carries no meaning for a centre-anchored piece, but the
    # renderer needs an orientation to place the symbol; the zone's long axis
    # is the natural one.
    long_x = (zone.x1 - zone.x0) >= (zone.y1 - zone.y0)
    rep.add(Fixture(room.id, fid, rect, against="S" if long_x else "W",
                    note="centred in its zone"))
    blockers.append(rect)


def _has_dining_counter(room, plan) -> bool:
    """Does this room already eat at a counter rather than a table?

    A `counter_divider` adjacency puts a dining counter on the kitchen seam,
    and `architectural_plan.py` already builds it and `render.py` already draws
    it — it lives in `plan.counters`, not in this module. It is the catalog's
    deliberate answer for compact plans: a great_room near its hard minimum
    fits a couch and a TV but not a table, so the millwork does the table's job
    (see `counter_divider`, a LOCKED design). Layer D reported those rooms as
    "no dining table fits", which was a false defect — the dining function was
    already there, drawn by another subsystem.
    """
    # Counter.room is the kitchen-side room the band sits in; Counter.facing is
    # the room the stools serve. Either end means this room eats at the counter.
    for c in (getattr(plan, "counters", None) or ()):
        if room.id in (getattr(c, "room", None), getattr(c, "facing", None)):
            return True
    return False


def _place_public(room, orient, door_walls: set, rep: "FixtureReport",
                  plan=None) -> None:
    cell = room.rect
    sibs = room.cells[1:]
    blockers: List[Rect] = []
    counter = _has_dining_counter(room, plan)
    if room.type == "dining_room":
        if not counter:
            _place_dining(room, cell, blockers, rep)
    elif room.type in ("living_room", "family_room"):
        _place_seating(room, cell, sibs, door_walls, blockers, rep)
    elif counter:
        # Dining is handled by the counter, so the seating group gets the WHOLE
        # room rather than half of it — which is the point of the counter parti.
        _place_seating(room, cell, sibs, door_walls, blockers, rep)
    else:                                   # great_room — holds BOTH
        a, b = _halves(cell)
        _place_seating(room, a, sibs, door_walls, blockers, rep)
        _place_dining(room, b, blockers, rep)


def _place_carport(element, rep: "FixtureReport") -> None:
    """A car in the carport. Carports and lanais are SETBACK ELEMENTS in this
    project, not rooms — they never appear in layout.rooms — so this is driven
    off layout.elements instead of the room loop."""
    w, d = LIB.size("car")
    cell = element.rect
    ew, eh = cell.x1 - cell.x0, cell.y1 - cell.y0
    # park along whichever way the bay actually runs
    rect = _centred_rect(cell, w, d) if eh >= ew else _centred_rect(cell, d, w)
    if rect is None:
        rep.unfit.append(f"{element.id}: car ({w:.2f} x {d:.2f} m) does not fit "
                         f"in a {ew:.2f} x {eh:.2f} m carport")
        return
    rep.add(Fixture(element.id, "car", rect,
                    against="S" if eh >= ew else "W", note="parked"))


_BEDROOMS = {"master_bedroom", "bedroom_standard", "maids_room"}
_BATHS = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room", "maids_bath"}


def place_fixtures(layout, plan) -> FixtureReport:
    """Place furniture for every room on `layout`, using `plan.orientations`.

    Returns both the fixtures and a list of things that did NOT fit — the
    latter is the point: it says which rooms are only nominally usable.
    """
    rep = FixtureReport()
    orientations = getattr(plan, "orientations", {}) or {}
    # One clear-floor view of every room, built once. Everything downstream —
    # placement, door clearance, the clearance check — works on this so the
    # furniture sits against the wall FACE, matching what gets drawn.
    probe = _floor_probe(layout)
    floors = {r.id: _RoomFloor(r, probe) for r in layout.rooms}

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
            elif r.type in _PUBLIC:
                _place_public(r, o, dw, rep, plan)
    for el in (getattr(layout, "elements", None) or ()):
        if getattr(el, "type", "") in _CARPORT:
            _place_carport(el, rep)
    check_door_clearance(rep, layout, plan)
    _clip_to_clear_floor(rep, floors)
    check_clearances(rep, layout, floors)
    return rep
