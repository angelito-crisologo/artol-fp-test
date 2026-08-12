"""Layer A — the fixture library (`fixtures/`) as typed data.

`fixtures/` is a standalone drawing library: 55 SVG symbols drawn in metres,
each with a `.json` manifest describing how it may be placed and what floor it
needs kept clear. `fixtures/index.json` is every manifest in one file, which is
what this module reads.

This replaces the hardcoded dimension constants that used to sit at the top of
`fixtures.py`. That is not a re-measurement: every one of those constants
already matched the library to the centimetre. What the library adds is the
part the constants could not carry —

  - per-SIDE, per-REASON clearance, instead of one 0.60 m number for
    everything. A kitchen counter needs 0.90 m in front of it, not 0.60;
  - `anchor` — whether a piece needs one wall behind it, two walls meeting at
    a corner, no wall at all, or is positioned by its centre;
  - `footprint.shape` — an L-sofa's inner corner and a round table's corners
    are free floor, not obstruction;
  - `stretch` bounds for wall runs, so shortening a counter has a floor;
  - `handed`, for the pieces that mirror into a different valid piece.

Nothing here places anything or knows what a room needs. The library says what
a fixture IS; `fixtures.py` decides what goes where. Keeping that seam means a
new symbol is a data change, not a code change.
"""
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
# solver/ → floorplan_v1/ → fixtures/index.json
LIBRARY_DIR = os.path.normpath(os.path.join(_HERE, "..", "fixtures"))
_INDEX_PATH = os.path.join(LIBRARY_DIR, "index.json")

# Clearance sides are given in the symbol's LOCAL space: front is +y (into the
# room), back is -y, left is -x, right is +x. They rotate with the symbol.
SIDES_LOCAL = ("front", "back", "left", "right")


@dataclass(frozen=True)
class Cell:
    """One rectangle of a non-rectangular footprint, in local metres."""
    x: float
    y: float
    w: float
    d: float


@dataclass(frozen=True)
class Footprint:
    """The floor the fixture actually occupies, in metres.

    For `shape == "circle"`, w == d is the diameter and the corners of that
    square are free floor. For `shape == "L"`, `w`/`d` are only the bounding
    box and `cells` gives what is really occupied. Check `shape` before
    treating `w x d` as solid.
    """
    w: float
    d: float
    shape: str                      # "rect" | "circle" | "L"
    cells: Optional[Tuple[Cell, ...]] = None

    @property
    def is_rect(self) -> bool:
        return self.shape == "rect"


@dataclass(frozen=True)
class Clearance:
    """Floor that must stay clear on one side, and why.

    The `reason` is carried through deliberately: a clearance that cannot be
    explained in plain words is usually a number someone copied, and it is
    what makes a tight-fit report readable rather than a list of deltas.
    """
    side: str                       # front | back | left | right (local)
    depth: float
    reason: str


@dataclass(frozen=True)
class Stretch:
    """How far a wall run may be extended or shortened."""
    axis: str                       # "width" | "depth"
    min: float
    max: float
    repeat_unit: float
    how: str


@dataclass(frozen=True)
class FixtureSpec:
    """One symbol: its footprint, its placement rules, and its drawing."""
    id: str
    label: str
    tier: int                       # 1 = plan reads as finished, 2 = PH set, 3 = extra
    category: str
    svg: str                        # filename, relative to LIBRARY_DIR
    footprint: Footprint
    viewbox_w: float
    viewbox_h: float
    origin_x: float                 # where the footprint's back-left corner
    origin_y: float                 # sits inside the viewBox
    anchor: str                     # wall_back | corner | free | center
    must_back_wall: bool
    needs_plumbing_wall: bool
    handed: bool
    stretch: Optional[Stretch]
    clearance: Tuple[Clearance, ...]
    rooms: Tuple[str, ...]
    notes: str = ""

    @property
    def w(self) -> float:
        return self.footprint.w

    @property
    def d(self) -> float:
        return self.footprint.d

    @property
    def size(self) -> Tuple[float, float]:
        """(width across the wall it backs onto, depth out from it)."""
        return self.footprint.w, self.footprint.d

    @property
    def has_overhang(self) -> bool:
        """Whether the drawing extends outside its own footprint.

        True for the dining tables, whose chairs are drawn where they
        physically are — which is inside the clearance zone. That overlap is
        not a bug to clip away; seeing it is how you notice a dining room is
        too tight.
        """
        return (self.origin_x != 0.0 or self.origin_y != 0.0
                or self.viewbox_w != self.footprint.w
                or self.viewbox_h != self.footprint.d)

    @property
    def svg_path(self) -> str:
        return os.path.join(LIBRARY_DIR, self.svg)

    def clearance_for(self, side: str) -> Optional[Clearance]:
        return next((c for c in self.clearance if c.side == side), None)


class FixtureLibrary:
    """Every symbol, indexed by id and by the rooms it belongs in."""

    def __init__(self, specs: List[FixtureSpec], meta: Dict):
        self._by_id = {s.id: s for s in specs}
        self._by_room: Dict[str, List[FixtureSpec]] = {}
        for s in specs:
            for r in s.rooms:
                self._by_room.setdefault(r, []).append(s)
        self.version = meta.get("version", "")
        self.units = meta.get("units", "m")
        self.convention = meta.get("convention", {})

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, fixture_id: str) -> bool:
        return fixture_id in self._by_id

    @property
    def ids(self) -> List[str]:
        return sorted(self._by_id)

    def get(self, fixture_id: str) -> FixtureSpec:
        """Look up by id. Raises rather than returning None: every call site
        names a symbol it expects to exist, so a miss is a typo or a deleted
        file, and failing at the lookup names it better than a None does three
        frames later."""
        try:
            return self._by_id[fixture_id]
        except KeyError:
            raise KeyError(
                f"no fixture {fixture_id!r} in the library at {LIBRARY_DIR} "
                f"({len(self._by_id)} symbols)") from None

    def size(self, fixture_id: str) -> Tuple[float, float]:
        return self.get(fixture_id).size

    def for_room(self, room_type: str, tier: Optional[int] = None
                 ) -> List[FixtureSpec]:
        """Symbols declared as belonging in `room_type`, lowest tier first.

        Note the library's room vocabulary is WIDER than the topology
        catalog's: it names dirty_kitchen, service_area, maids_room, wic,
        study and others that no topology declares yet, plus carport/lanai
        which exist here as setback elements rather than rooms. An unknown
        room type is not an error, it just has nothing to place.
        """
        out = self._by_room.get(room_type, [])
        if tier is not None:
            out = [s for s in out if s.tier <= tier]
        return sorted(out, key=lambda s: (s.tier, s.id))

    @property
    def room_types(self) -> List[str]:
        return sorted(self._by_room)


def _cells(raw) -> Optional[Tuple[Cell, ...]]:
    if not raw:
        return None
    return tuple(Cell(c["x"], c["y"], c["w"], c["d"]) for c in raw)


def _stretch(raw) -> Optional[Stretch]:
    if not raw:
        return None
    return Stretch(raw["axis"], raw["min"], raw["max"],
                   raw.get("repeat_unit", 0.0), raw.get("how", ""))


def _spec(raw: Dict) -> FixtureSpec:
    fp, vb, og = raw["footprint"], raw["viewbox"], raw["origin"]
    return FixtureSpec(
        id=raw["id"],
        label=raw["label"],
        tier=raw["tier"],
        category=raw["category"],
        svg=raw["svg"],
        footprint=Footprint(fp["w"], fp["d"], fp["shape"], _cells(fp.get("cells"))),
        viewbox_w=vb["w"],
        viewbox_h=vb["h"],
        origin_x=og["x"],
        origin_y=og["y"],
        anchor=raw["anchor"],
        must_back_wall=raw["must_back_wall"],
        needs_plumbing_wall=raw["needs_plumbing_wall"],
        handed=raw["handed"],
        stretch=_stretch(raw.get("stretch")),
        clearance=tuple(Clearance(c["side"], c["depth"], c["reason"])
                        for c in raw.get("clearance", [])),
        rooms=tuple(raw.get("rooms", [])),
        notes=raw.get("notes", ""),
    )


_CACHE: Optional[FixtureLibrary] = None


def load_library(path: Optional[str] = None, force: bool = False
                 ) -> FixtureLibrary:
    """Read `fixtures/index.json`. Cached — the library is immutable data.

    The cache is a module global, which this project has been bitten by
    before. It is safe here for the reason the earlier one was not: this holds
    no per-layout state. It is the same file parsed to the same frozen
    dataclasses on every call, so nothing from one brief can reach the next.
    `force=True` re-reads it anyway, for editing the library in a live session.
    """
    global _CACHE
    if path is None and _CACHE is not None and not force:
        return _CACHE
    with open(path or _INDEX_PATH, encoding="utf-8") as fh:
        raw = json.load(fh)
    lib = FixtureLibrary([_spec(f) for f in raw["fixtures"]], raw)
    if path is None:
        _CACHE = lib
    return lib
