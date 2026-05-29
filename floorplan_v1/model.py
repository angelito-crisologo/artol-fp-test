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

    @property
    def cells(self) -> List[Rect]:
        return [self.rect] + ([self.rect2] if self.rect2 else [])

    @property
    def area(self) -> float:
        return round(sum(c.area for c in self.cells), 4)

    @property
    def least(self) -> float:
        """Narrowest arm (each cell must independently clear minimums)."""
        return min(c.least for c in self.cells)

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

    @property
    def area(self) -> float:
        return round(self.width * self.depth, 4)

    def envelope(self) -> Rect:
        """Buildable footprint after setbacks."""
        return Rect(self.left, self.front, self.width - self.right, self.depth - self.rear)


# --- Shell category thresholds (based on the buildable shell, not the raw lot) ---
# ratio = shell width / shell depth (front-to-rear).  These are the bands every
# template registers against, so a template like wide_open_plan only runs on a
# wide buildable shell and is refused (with a clear message) on a narrow one.
SHELL_NARROW_MAX = 0.80   # ratio < 0.80  -> narrow (deep > 1.25 x width)
SHELL_WIDE_MIN = 1.30     # ratio >= 1.30 -> wide; in between -> squarish


def shell_category(lot: "Lot") -> str:
    env = lot.envelope()
    if env.h <= 0:
        return "narrow"
    ratio = env.w / env.h
    if ratio < SHELL_NARROW_MAX:
        return "narrow"
    if ratio >= SHELL_WIDE_MIN:
        return "wide"
    return "squarish"


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
