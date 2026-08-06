"""Core data model for the PH floor plan generator (v1 prototype).

Coordinate system (metres):
  origin (0,0) = front-left corner of the LOT
  x increases to the RIGHT (0 .. lot width)
  y increases toward the REAR (0 = front/street, lot depth = rear)

Pure standard library, axis-aligned rectangles only.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return round(self.x1 - self.x0, 4)

    @property
    def h(self) -> float:
        return round(self.y1 - self.y0, 4)

    @property
    def area(self) -> float:
        return round(self.w * self.h, 4)

    @property
    def least(self) -> float:
        return round(min(self.w, self.h), 4)

    def touches_boundary(self, env: "Rect", tol: float = 1e-6) -> bool:
        """True if this rect touches any edge of the given envelope rect."""
        return (
            abs(self.x0 - env.x0) <= tol or abs(self.x1 - env.x1) <= tol or
            abs(self.y0 - env.y0) <= tol or abs(self.y1 - env.y1) <= tol
        )

    def overlaps(self, other: "Rect", tol: float = 1e-6) -> bool:
        return (
            self.x0 < other.x1 - tol and self.x1 > other.x0 + tol and
            self.y0 < other.y1 - tol and self.y1 > other.y0 + tol
        )

    def adjacent_to(self, other: "Rect", tol: float = 1e-3) -> bool:
        """Share a wall segment (touching edges with overlap along it)."""
        # vertical shared edge
        if abs(self.x1 - other.x0) <= tol or abs(self.x0 - other.x1) <= tol:
            return min(self.y1, other.y1) - max(self.y0, other.y0) > tol
        # horizontal shared edge
        if abs(self.y1 - other.y0) <= tol or abs(self.y0 - other.y1) <= tol:
            return min(self.x1, other.x1) - max(self.x0, other.x0) > tol
        return False


_L_LANDING_WALL_OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def l_landing_cells(rect: "Rect", board_wall: Optional[str],
                    arrive_wall: Optional[str]) -> Optional[Dict[str, "Rect"]]:
    """Decompose an L-landing stair's bounding rect into its four
    sub-rectangles: leg1 (from the boarding wall), leg2 (to the arrival
    wall), landing (their corner overlap), and notch (the unused corner
    diagonally opposite the landing — currently reserved for the stair but
    not actually part of any tread/landing, reclaimable by whichever room
    borders it). leg_w = min(rect.w, rect.h) / 3.0. Shared by the render
    glyph (core/render.py) and the solver's notch-derivation / claim logic
    (solver/solver.py, solver/snap_gaps.py) so both agree on the exact
    same geometry. Returns None if board_wall/arrive_wall aren't set or
    aren't a valid perpendicular pair (the only configuration an L-landing
    turn can have)."""
    if not board_wall or not arrive_wall or board_wall == arrive_wall \
            or _L_LANDING_WALL_OPPOSITE.get(board_wall) == arrive_wall:
        return None
    leg_w = min(rect.w, rect.h) / 3.0
    board_travels_y = board_wall in ("N", "S")
    leg1_wall = _L_LANDING_WALL_OPPOSITE[arrive_wall]
    if board_travels_y:
        if leg1_wall == "W":
            lx0, lx1 = rect.x0, rect.x0 + leg_w
        else:
            lx0, lx1 = rect.x1 - leg_w, rect.x1
        if board_wall == "S":
            ly0, ly1 = rect.y0, rect.y1 - leg_w
            l2y0, l2y1 = rect.y1 - leg_w, rect.y1
        else:
            ly0, ly1 = rect.y0 + leg_w, rect.y1
            l2y0, l2y1 = rect.y0, rect.y0 + leg_w
        leg1 = Rect(lx0, ly0, lx1, ly1)
        l2x0, l2x1 = (lx1, rect.x1) if leg1_wall == "W" else (rect.x0, lx0)
        leg2 = Rect(l2x0, l2y0, l2x1, l2y1)
        landing = Rect(lx0, l2y0, lx1, l2y1)
        notch = Rect(l2x0, ly0, l2x1, ly1)
    else:
        if leg1_wall == "S":
            ly0, ly1 = rect.y0, rect.y0 + leg_w
        else:
            ly0, ly1 = rect.y1 - leg_w, rect.y1
        if board_wall == "W":
            lx0, lx1 = rect.x0, rect.x1 - leg_w
            l2x0, l2x1 = rect.x1 - leg_w, rect.x1
        else:
            lx0, lx1 = rect.x0 + leg_w, rect.x1
            l2x0, l2x1 = rect.x0, rect.x0 + leg_w
        leg1 = Rect(lx0, ly0, lx1, ly1)
        l2y0, l2y1 = (ly1, rect.y1) if leg1_wall == "S" else (rect.y0, ly0)
        leg2 = Rect(l2x0, l2y0, l2x1, l2y1)
        landing = Rect(l2x0, ly0, l2x1, ly1)
        notch = Rect(lx0, l2y0, lx1, l2y1)
    return {"leg1": leg1, "leg2": leg2, "landing": landing, "notch": notch}


@dataclass
class Room:
    id: str            # unique instance id, e.g. "bedroom_standard"
    type: str          # rules room_catalog id, e.g. "bedroom_standard"
    rect: Rect
    zone: str = "private"      # public | private | service | circulation
    covered: bool = True
    rect2: Optional[Rect] = None   # optional 2nd cell -> L-shaped (composite) room
    mechanical_vent: bool = False  # opt-out from PD 1096 §808 10% window rule
                                   # (substitute artificial ventilation per §805)
    storey: int = 1                # which floor this room is on (1 = ground);
                                   # rooms on different storeys share the x/y
                                   # plane but may overlap in plan
    stair_up: Optional[tuple] = None  # for type=="stairs": ascent direction as
                                      # a lot-space unit vector (dx, dy) pointing
                                      # from the flight's BOTTOM to its TOP.
                                      # Set by the solver from its ascent
                                      # decision; the renderer draws the UP/DN
                                      # travel arrow from it.
    stair_type: str = "straight"     # for type=="stairs": which of the 6
                                      # catalog stair plan-types (copied
                                      # straight through from RoomSpec).
    stair_board_wall: Optional[str] = None  # for type=="stairs" with
                                      # stair_type != "straight": which wall
                                      # (N/S/E/W) the boarding neighbor
                                      # reaches, resolved from the topology's
                                      # stair_boarding adjacency stair_wall.
    stair_arrive_wall: Optional[str] = None  # same, for stair_arrival.
    notch_pin_of: Optional[str] = None  # room id of the L-landing stair whose
                                      # leftover notch this room is pinned
                                      # into (Topology.notch_powder_room_id) —
                                      # a DELIBERATE overlap with that one
                                      # room only; the validator's overlap
                                      # check exempts this specific pair.

    @property
    def cells(self) -> List[Rect]:
        return [self.rect] + ([self.rect2] if self.rect2 else [])

    @property
    def area(self) -> float:
        return round(sum(c.area for c in self.cells), 4)

    @property
    def least(self) -> float:
        """Least dim of the PRIMARY cell (rect). Secondary cells (rect2) are
        treated as ALCOVES — small composite extensions that may legitimately
        be narrower than the room's hard minimum (e.g., a void alcove behind
        a carport L-cut). The primary cell still has to clear PD 1096 minimums;
        an alcove is an addition, not a replacement for usable room space."""
        return self.rect.least

    def touches_boundary(self, env: "Rect") -> bool:
        return any(c.touches_boundary(env) for c in self.cells)

    def within(self, env: "Rect", tol: float = 1e-6) -> bool:
        return all(
            c.x0 >= env.x0 - tol and c.x1 <= env.x1 + tol and
            c.y0 >= env.y0 - tol and c.y1 <= env.y1 + tol
            for c in self.cells
        )

    def overlaps_room(self, other: "Room") -> bool:
        return any(a.overlaps(b) for a in self.cells for b in other.cells)

    def adjacent_room(self, other: "Room", tol: float = 1e-3) -> bool:
        return any(a.adjacent_to(b, tol) for a in self.cells for b in other.cells)


@dataclass
class Lot:
    width: float
    depth: float
    front: float       # front setback (m)
    rear: float
    left: float
    right: float
    street_side: str = "front"
    # PD 1096 / IRR Rule VII residential occupancy class — drives setback
    # minimums (W-H11) and firewall legality (W-H10). Default "R-1" matches
    # the project's primary target (single-detached single-family).
    occupancy_class: str = "R-1"

    @property
    def area(self) -> float:
        return round(self.width * self.depth, 4)

    def envelope(self) -> Rect:
        """Buildable footprint after setbacks."""
        return Rect(self.left, self.front, self.width - self.right, self.depth - self.rear)


# --- Shell category thresholds (based on the buildable shell, not the raw lot) ---
# ratio = shell width / shell depth (front-to-rear). Four bands across the
# spectrum, matching the topology directory structure (squarish/narrow/wide):
#   narrow      ratio  < 0.80          deep-to-narrow lots (was split into
#                                      "super_deep"/"deep" until 2026-07-16;
#                                      merged to "narrow" so this matches
#                                      topology target_shell values exactly
#                                      -- the split was never consumed by any
#                                      other logic, only ever printed/compared)
#   squarish    0.80 <= ratio < 1.30   near-square
#   wide        1.30 <= ratio < 1.85   wide but not extreme
#   extra_wide  ratio >= 1.85          very wide / shallow
SHELL_NARROW_MAX     = 0.80
SHELL_WIDE_MIN       = 1.30
SHELL_EXTRA_WIDE_MIN = 1.85


def shell_category(lot: "Lot") -> str:
    env = lot.envelope()
    if env.h <= 0:
        return "narrow"
    ratio = env.w / env.h
    if ratio < SHELL_NARROW_MAX:
        return "narrow"
    if ratio < SHELL_WIDE_MIN:
        return "squarish"
    if ratio < SHELL_EXTRA_WIDE_MIN:
        return "wide"
    return "extra_wide"


@dataclass
class Layout:
    lot: Lot
    rooms: List[Room]                  # enclosed footprint rooms
    elements: List[Room]               # uncovered setback elements
    carport_side: str                  # "left" | "right"
    genome: Dict = field(default_factory=dict)
    score: float = 0.0
    issues: List = field(default_factory=list)

    @property
    def footprint_area(self) -> float:
        return round(sum(r.area for r in self.rooms), 4)

    @property
    def occupancy_pct(self) -> float:
        return round(100.0 * self.footprint_area / self.lot.area, 2)


def make_outside_probe(env: "Rect", obstacles, eps: float = 1e-6):
    """Build `faces_outside(x, y) -> bool` for one floor's geometry.

    THE single definition of "outside the building", shared by the renderer
    (which wall weights to draw) and the architectural plan (where windows
    and exterior doors may go). Before 2026-08-06 those two had separate
    answers: render used this connectivity rule while architectural_plan
    used strict envelope-edge equality, so a wall that was exterior only
    because it faced an unclaimed perimeter strip got drawn heavy but was
    given no window and could host no door.

    The building footprint is the union of ROOM CELLS, not the envelope
    rectangle — `Layout.footprint_area` has always summed room areas. A
    point is OUTSIDE when it lies beyond the envelope, or in unowned space
    that reaches the envelope boundary. Unowned space fully ENCLOSED by
    rooms is a courtyard / light well, and is deliberately NOT outside.

    `obstacles` are the occupied rects (room cells + building voids).
    """
    import bisect as _bisect
    xs = sorted({env.x0, env.x1} | {v for c in obstacles for v in (c.x0, c.x1)
                                    if env.x0 - eps < v < env.x1 + eps})
    ys = sorted({env.y0, env.y1} | {v for c in obstacles for v in (c.y0, c.y1)
                                    if env.y0 - eps < v < env.y1 + eps})
    nx, ny = len(xs) - 1, len(ys) - 1

    def _free(i, j):
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        return not any(c.x0 - eps < cx < c.x1 + eps and
                       c.y0 - eps < cy < c.y1 + eps for c in obstacles)

    out = [[False] * ny for _ in range(nx)]
    stack = [(i, j) for i in range(nx) for j in range(ny)
             if _free(i, j) and (i in (0, nx - 1) or j in (0, ny - 1))]
    for i, j in stack:
        out[i][j] = True
    while stack:
        i, j = stack.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < nx and 0 <= b < ny and not out[a][b] and _free(a, b):
                out[a][b] = True
                stack.append((a, b))

    def faces_outside(px: float, py: float) -> bool:
        if not (env.x0 <= px <= env.x1 and env.y0 <= py <= env.y1):
            return True
        i = max(0, min(nx - 1, _bisect.bisect_right(xs, px) - 1))
        j = max(0, min(ny - 1, _bisect.bisect_right(ys, py) - 1))
        return out[i][j]

    return faces_outside


def probe_point(rect: "Rect", side: str, step: float = 1e-5):
    """A point just OUTSIDE `rect` on the given side — what to hand to
    `faces_outside` to ask whether that wall is an exterior wall."""
    mx, my = (rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0
    if side == "N": return (mx, rect.y1 + step)
    if side == "S": return (mx, rect.y0 - step)
    if side == "E": return (rect.x1 + step, my)
    return (rect.x0 - step, my)                      # "W"
