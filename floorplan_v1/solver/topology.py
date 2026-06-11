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
    # --- door-host groups (Phase 1 of door-host selection) -----------------
    # Adjacencies sharing a door_host_group name are ALTERNATE door hosts for
    # the same room: exactly one member of the group emits a door, the rest
    # render as solid walls. The member authored with a door kind (bath_door,
    # bedroom_door, ...) is the group's default; a brief-level door_host
    # override can pick a different member. See architectural_plan.py Pass 1a.
    door_host_group: Optional[str] = None
    # For no-door-kind members (e.g. wet_core): True means a door MAY be
    # placed on this edge when the group selection picks it. Without it, an
    # override pointing at this member is rejected (falls back to default).
    door_allowed: bool = False
    # The door kind to use when this member is chosen but its declared kind
    # is a no-door kind (e.g. wet_core edge hosting a bath door). Defaults
    # to "bath_door" when omitted.
    door_kind: Optional[str] = None
    # Minimum CONTINUOUS solid wall (m) that must remain on the shared edge
    # after the door + frames are placed — the plumbing-band guard for doors
    # on wet_core walls. 0.0 disables the guard. If the realized geometry
    # can't honor it, no door is emitted on this edge and the group falls
    # back to its default host.
    min_solid_wall_m: float = 0.0


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
    # Optional per-topology dimension overrides. When None, _setback_elements
    # falls back to its built-in default (e.g., side carport 2.6 m wide x 5.0 m
    # deep). Set these on a topology when its building_void was sized for a
    # non-default carport, so the carport's rear edge aligns with the void's
    # rear edge in the rendered floor plan.
    width_m:  Optional[float] = None
    depth_m:  Optional[float] = None


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

    # When True the solver constrains width(ensuite_bath) == width(common_bath).
    # Use this on clustered-bath topologies where the bath block sits in the
    # middle band: matching widths forces a symmetric split of that band so
    # the bath layout stays invariant to changes in the public-side area
    # (e.g., between a with-carport L-shape and a no-carport rectangle, the
    # private wing reads identically — only the L-cut at front-right differs).
    match_bath_widths: bool = False

    # When True the solver constrains the rooms in the bedroom-band (the
    # middle band between master and standard — typically ensuite + common,
    # plus any hallway in a [master, X, standard] stack) to tile the bedroom
    # width exactly. Without this, the middle band can overhang the bedroom
    # column (bath block wider than bedrooms), leaving an interior gap east
    # of master that the snap-gaps post-process then fills asymmetrically —
    # master grows east, standard stays narrow because kitchen blocks, and
    # the matched bedroom widths invariant breaks. Pair this flag with
    # match_bedroom_widths + match_bath_widths for a fully symmetric private
    # wing.
    bedroom_band_fills_width: bool = False

    # When True the topology caps the ensuite at preferred-high area
    # (4.5 m²) and lets the strip east of ensuite within the bedroom column
    # join master as an L-extension. Use this on distributed-bath topologies
    # where the bedroom column is wider than the ensuite needs to be: rather
    # than letting the snap-gaps post-process extend ensuite to bedroom
    # width (giving an oversized ensuite at 5-6 m²), the strip becomes
    # additional master area. The post-process `claim_ensuite_alcove`
    # handles the actual L-shape assignment.
    ensuite_alcove_joins_master: bool = False

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
    # See floorplan_v1/run.py::_apply_lot_profile for the matching logic.
    lot_adjustment_profiles: list = field(default_factory=list)

    # Optional list of BuildingVoid — rectangles inside the buildable envelope
    # reserved away from rooms (typically because a setback element like a
    # carport "cuts" into the building from a side or front edge).
    building_voids: List[BuildingVoid] = field(default_factory=list)

    # Optional path (relative to topologies/) to a fallback topology that the
    # runner should attempt when this topology is infeasible on the given lot.
    # Use case: a hall-variant declares its no-hall sibling as fallback so the
    # runner can downgrade gracefully on a too-small shell rather than erroring
    # out. When the fallback is used, the runner emits a "warning" issue noting
    # that the primary topology didn't fit.
    fallback_topology: Optional[str] = None

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
        match_bath_widths=bool(d.get("match_bath_widths", False)),
        bedroom_band_fills_width=bool(d.get("bedroom_band_fills_width", False)),
        ensuite_alcove_joins_master=bool(d.get("ensuite_alcove_joins_master", False)),
        front_to_rear_stacks=list(d.get("front_to_rear_stacks", []) or []),
        rear_anchored=list(d.get("rear_anchored", []) or []),
        left_anchored=list(d.get("left_anchored", []) or []),
        right_anchored=list(d.get("right_anchored", []) or []),
        lot_adjustment_profiles=list(d.get("lot_adjustment_profiles", []) or []),
        building_voids=voids,
        fallback_topology=d.get("fallback_topology"),
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


# Map for mirroring x-axis-specific location strings on BuildingVoid.
# y-axis-only strings (front_only, rear_only) would be unchanged; only
# the four corner strings used today are listed here.
_X_MIRROR_LOCATION = {
    "front_left":  "front_right",
    "front_right": "front_left",
    "rear_left":   "rear_right",
    "rear_right":  "rear_left",
}


def swap_master_standard_in_topology(t: Topology) -> Topology:
    """Return a copy of `t` with the placements of the master_bedroom and
    bedroom_standard rooms swapped.

    Used to support master-at-rear (vs. master-at-front) as a brief-level
    knob. Topology files are authored in the canonical "master at front of
    private column" form; when the brief sets swap_master_standard=true,
    the runner applies this transform before passing the topology to the
    solver. Net effect: master physically moves to where standard was
    (typically the rear of the private column), and standard moves to
    master's old position (typically the front).

    What CHANGES:
      - front_to_rear_stacks: each stack containing BOTH master_id and
        standard_id is reversed. This puts master at the rear end of the
        stack and standard at the front end. Stacks not containing both
        (e.g., the public LDK stack) are unchanged.
      - {rear,left,right}_anchored: master_id and standard_id tokens swap
        simultaneously. If standard was rear-anchored, master becomes
        rear-anchored instead (and vice versa).

    What does NOT change:
      - rooms (master is still master, standard is still standard — same
        sizes, same priority, same type)
      - adjacencies (keyed by room id; master ↔ ensuite still holds, etc.)
      - soft_proximities, zone_split, setback_elements, building_voids
      - match_bedroom_widths, match_bath_widths, bedroom_band_fills_width,
        ensuite_alcove_joins_master (all position-independent)
      - lot_adjustment_profiles (keyed by room TYPE)

    No-op if the topology lacks a master_bedroom or a bedroom_standard.
    """
    master_id = next((r.id for r in t.rooms if r.type == "master_bedroom"), None)
    std_id = next((r.id for r in t.rooms if r.type == "bedroom_standard"), None)
    if master_id is None or std_id is None:
        return t  # nothing to swap

    def _swap_token(x: str) -> str:
        if x == master_id:
            return std_id
        if x == std_id:
            return master_id
        return x

    new_stacks = []
    for stack in t.front_to_rear_stacks or []:
        if master_id in stack and std_id in stack:
            new_stacks.append(list(reversed(stack)))
        else:
            new_stacks.append(list(stack))

    return Topology(
        id=t.id, label=t.label, target_shell=t.target_shell,
        rooms=list(t.rooms), adjacencies=list(t.adjacencies),
        entry_point=t.entry_point,
        setback_elements=list(t.setback_elements),
        soft_proximities=list(t.soft_proximities),
        zone_split=t.zone_split,
        notes=list(t.notes),
        match_bedroom_widths=t.match_bedroom_widths,
        match_bath_widths=t.match_bath_widths,
        bedroom_band_fills_width=t.bedroom_band_fills_width,
        ensuite_alcove_joins_master=t.ensuite_alcove_joins_master,
        front_to_rear_stacks=new_stacks,
        rear_anchored=[_swap_token(x) for x in t.rear_anchored],
        left_anchored=[_swap_token(x) for x in t.left_anchored],
        right_anchored=[_swap_token(x) for x in t.right_anchored],
        lot_adjustment_profiles=list(t.lot_adjustment_profiles),
        building_voids=list(t.building_voids),
        fallback_topology=t.fallback_topology,
    )


def mirror_topology_x(t: Topology) -> Topology:
    """Return a copy of `t` with all x-axis (left/right) fields flipped.

    Used to support carport-side as a brief-level input: topology files are
    authored in the canonical "carport on the right" form, and when the brief
    says carport_side='left' the runner mirrors the topology before passing it
    to the solver. Mirrored fields:

      - left_anchored ↔ right_anchored (list swap)
      - building_voids[].location: front_left ↔ front_right, rear_left ↔ rear_right

    y-axis fields (rear_anchored, front_to_rear_stacks) are NOT touched.
    Identity-preserving on rooms, adjacencies, soft_proximities, setback_elements
    (the renderer flips the carport's side from the SetbackElement separately).
    """
    mirrored_voids = []
    for v in t.building_voids or []:
        new_loc = _X_MIRROR_LOCATION.get((v.location or "").lower(), v.location)
        mirrored_voids.append(BuildingVoid(
            id=v.id, location=new_loc, width_m=v.width_m, depth_m=v.depth_m,
            consumed_by=v.consumed_by,
        ))
    return Topology(
        id=t.id, label=t.label, target_shell=t.target_shell,
        rooms=list(t.rooms), adjacencies=list(t.adjacencies),
        entry_point=t.entry_point,
        setback_elements=list(t.setback_elements),
        soft_proximities=list(t.soft_proximities),
        zone_split=t.zone_split,
        notes=list(t.notes),
        match_bedroom_widths=t.match_bedroom_widths,
        match_bath_widths=t.match_bath_widths,
        bedroom_band_fills_width=t.bedroom_band_fills_width,
        ensuite_alcove_joins_master=t.ensuite_alcove_joins_master,
        front_to_rear_stacks=list(t.front_to_rear_stacks),
        rear_anchored=list(t.rear_anchored),
        # x-axis fields swap:
        left_anchored=list(t.right_anchored),
        right_anchored=list(t.left_anchored),
        lot_adjustment_profiles=list(t.lot_adjustment_profiles),
        building_voids=mirrored_voids,
        fallback_topology=t.fallback_topology,
    )
