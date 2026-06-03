"""Topology data model + loader for Phase C.1.

A topology is an adjacency graph specifying the room program, the required
adjacencies between rooms, the entry point, and the setback elements. It does
NOT contain geometry -- the CP-SAT solver places rectangles to realize it.
"""
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


@dataclass
class RoomSpec:
    id: str                # unique instance id (e.g. "master")
    type: str              # rules room_catalog id (e.g. "master_bedroom")
    zone: str = "private"
    size_priority: str = "service_and_baths"
    hosts_entry: bool = False
    # Topology-level opt-out from PD 1096 §808 10% window rule when the room
    # geometry can't physically fit a compliant window (e.g. a tight kitchen
    # whose only exterior wall is the back-door wall). The intent is that
    # the room uses artificial ventilation instead.
    mechanical_vent: bool = False


@dataclass
class Adjacency:
    a: str                 # room id
    b: str                 # room id
    min_shared_wall_m: float  # minimum continuous shared-wall length (door-able)
    kind: str = "door"
    note: str = ""


@dataclass
class ZoneSplit:
    """Optional hard partition of the buildable envelope into two halves —
    one for private (bedrooms+baths), one for public (LDK). axis='vertical'
    splits left/right; axis='horizontal' splits front/rear. private_side names
    which side the private zone goes on. The room id lists make the binding
    explicit so service rooms (kitchen vs common bath) can be steered to
    whichever side they belong to."""
    axis: str                          # "vertical" or "horizontal"
    private_side: str                  # "left", "right", "front", "rear"
    private_rooms: List[str] = field(default_factory=list)
    public_rooms: List[str] = field(default_factory=list)


@dataclass
class SoftProximity:
    a: str                 # room id
    b: str                 # room id
    weight: float = 30.0   # higher = solver pulls the two rooms closer
    note: str = ""


@dataclass
class SetbackElement:
    type: str              # carport | dirty_kitchen | service_area
    location: str          # side_setback | rear_setback | front_setback
    covered: bool = False
    behind: Optional[str] = None  # room id this element sits behind (for dirty kitchen)


@dataclass
class BuildingVoid:
    """A rectangular area INSIDE the buildable envelope that's reserved away
    from rooms. The solver treats it like a fixed-position phantom room: no
    other room can overlap it. The renderer treats its lot-facing edges as
    'open' (no wall there) and its room-facing edges as exterior walls.
    Visually merges with a setback element whose `consumed_by` matches.

    Used for L-shaped buildings where a setback element (typically the
    carport) extends through the envelope edge into the building footprint.
    """
    id: str
    location: str         # 'front_left' | 'front_right' | 'rear_left' | 'rear_right'
    width_m: float        # extent along the x-axis (parallel to front/rear)
    depth_m: float        # extent along the y-axis (parallel to left/right)
    consumed_by: Optional[str] = None  # setback element type that visually
                                       # extends into this void (usually "carport")


@dataclass
class Topology:
    id: str
    label: str
    target_shell: str
    rooms: List[RoomSpec]
    adjacencies: List[Adjacency]
    entry_point: str
    setback_elements: List[SetbackElement] = field(default_factory=list)
    soft_proximities: List[SoftProximity] = field(default_factory=list)
    zone_split: Optional[ZoneSplit] = None
    notes: List[str] = field(default_factory=list)
    # When True the solver constrains master.width == standard.width. Use this
    # on topologies where the design intent calls for the two bedrooms to
    # visually align (e.g., bath-block-between-bedrooms looks intentional only
    # if the block spans the full shared width).
    match_bedroom_widths: bool = False

    # Optional ordering hints. Each entry is a list of room ids that must
    # stack front-to-rear (room[0] in front, room[-1] at rear). The solver
    # adds hard constraints: room[i].y_end <= room[i+1].y for each pair.
    # Use this when an open_plan adjacency between two rooms could be
    # satisfied side-by-side (vertical shared wall) but the design intent is
    # specifically a vertical stack (horizontal shared wall). Example: an
    # LDK column where living must be in front of dining must be in front
    # of kitchen.
    front_to_rear_stacks: List[List[str]] = field(default_factory=list)

    # Optional list of room ids that must touch the REAR exterior wall.
    # Kitchen is already rear-anchored by the solver's hard rule; adding
    # another room here (e.g. dining) makes it sit beside the kitchen at
    # the rear rather than stacked in front of it. Useful for forcing a
    # side-by-side open-plan LDK layout.
    rear_anchored: List[str] = field(default_factory=list)

    # Optional lists of room ids that must touch the LEFT or RIGHT
    # exterior walls (envelope's x_start / x_end). Use these to eliminate
    # "wasted space" gaps on a side when a wing is shorter than the
    # envelope: anchoring the wing's rooms to the corresponding exterior
    # forces the solver to fill that edge cleanly.
    left_anchored: List[str] = field(default_factory=list)
    right_anchored: List[str] = field(default_factory=list)

    # Optional lot-conditional adjustment profiles. Each profile is a dict
    # with `when` (predicate on the lot's buildable dims) and `auto_apply`
    # (adjustments dict in the same shape as the brief's adjustments). The
    # FIRST matching profile is applied; its adjustments are merged with the
    # brief's own (the brief always wins on conflicting room+key pairs).
    # See phase_c3/run.py::_apply_lot_profile for the matching logic.
    lot_adjustment_profiles: list = field(default_factory=list)

    # Optional list of BuildingVoid — rectangles inside the buildable envelope
    # reserved away from rooms (typically because a setback element like a
    # carport "cuts" into the building from a side or front edge).
    building_voids: List[BuildingVoid] = field(default_factory=list)

    def room(self, room_id: str) -> RoomSpec:
        for r in self.rooms:
            if r.id == room_id:
                return r
        raise KeyError(f"unknown room id: {room_id}")

    def neighbours(self, room_id: str) -> List[str]:
        out = []
        for e in self.adjacencies:
            if e.a == room_id:
                out.append(e.b)
            elif e.b == room_id:
                out.append(e.a)
        return out


def load_topology(path: str) -> Topology:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    rooms = [RoomSpec(**{k: r[k] for k in r if k in RoomSpec.__annotations__}) for r in d["rooms"]]
    adjs = [Adjacency(**{k: e[k] for k in e if k in Adjacency.__annotations__}) for e in d["adjacencies"]]
    elems = [SetbackElement(**{k: x[k] for k in x if k in SetbackElement.__annotations__})
             for x in d.get("setback_elements", [])]
    voids = [BuildingVoid(**{k: x[k] for k in x if k in BuildingVoid.__annotations__})
             for x in d.get("building_voids", [])]
    sprox = [SoftProximity(**{k: x[k] for k in x if k in SoftProximity.__annotations__})
             for x in d.get("soft_proximities", [])]
    zs_raw = d.get("zone_split")
    zs = ZoneSplit(**{k: zs_raw[k] for k in zs_raw if k in ZoneSplit.__annotations__}) \
         if zs_raw else None
    return Topology(
        id=d["id"], label=d["label"], target_shell=d["target_shell"],
        rooms=rooms, adjacencies=adjs, entry_point=d["entry_point"],
        setback_elements=elems, soft_proximities=sprox, zone_split=zs,
        notes=d.get("notes", []),
        match_bedroom_widths=bool(d.get("match_bedroom_widths", False)),
        front_to_rear_stacks=list(d.get("front_to_rear_stacks", []) or []),
        rear_anchored=list(d.get("rear_anchored", []) or []),
        left_anchored=list(d.get("left_anchored", []) or []),
        right_anchored=list(d.get("right_anchored", []) or []),
        lot_adjustment_profiles=list(d.get("lot_adjustment_profiles", []) or []),
        building_voids=voids,
    )


def validate_topology(t: Topology) -> List[str]:
    """Basic structural checks BEFORE the geometric solver runs. Returns a list
    of error messages (empty -> ok)."""
    errs = []
    ids = {r.id for r in t.rooms}
    if len(ids) != len(t.rooms):
        errs.append("duplicate room ids")
    for e in t.adjacencies:
        if e.a not in ids or e.b not in ids:
            errs.append(f"adjacency references unknown room: {e.a} <-> {e.b}")
        if e.a == e.b:
            errs.append(f"self-adjacency: {e.a}")
    if t.entry_point not in ids:
        errs.append(f"entry_point references unknown room: {t.entry_point}")
    # every habitable room should be reachable from the entry through the adjacency graph
    from collections import deque
    visited = set()
    q = deque([t.entry_point])
    while q:
        cur = q.popleft()
        if cur in visited:
            continue
        visited.add(cur)
        for nb in t.neighbours(cur):
            if nb not in visited:
                q.append(nb)
    HABITABLE = {"bedroom_standard", "master_bedroom", "living_room",
                 "dining_room", "great_room"}
    for r in t.rooms:
        if r.id not in visited and r.type in HABITABLE:
            errs.append(f"habitable room '{r.id}' is unreachable from entry")
    return errs
