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
# ratio = shell width / shell depth (front-to-rear). Five bands across the
# spectrum, matching the topology directory structure:
#   super_deep  ratio  < 0.55          very deep narrow lots
#   deep        0.55 <= ratio < 0.80   deep but not extreme
#   squarish    0.80 <= ratio < 1.30   near-square
#   wide        1.30 <= ratio < 1.85   wide but not extreme
#   extra_wide  ratio >= 1.85          very wide / shallow
SHELL_SUPER_DEEP_MAX = 0.55
SHELL_DEEP_MAX       = 0.80
SHELL_WIDE_MIN       = 1.30
SHELL_EXTRA_WIDE_MIN = 1.85


def shell_category(lot: "Lot") -> str:
    env = lot.envelope()
    if env.h <= 0:
        return "super_deep"
    ratio = env.w / env.h
    if ratio < SHELL_SUPER_DEEP_MAX:
        return "super_deep"
    if ratio < SHELL_DEEP_MAX:
        return "deep"
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
