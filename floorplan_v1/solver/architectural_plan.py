"""Phase D.1 — turn a snapped Layout + Topology into an ArchitecturalPlan.

The Layout produced by the CP-SAT solver (and polished by snap_gaps) is a set
of room rectangles. An ArchitecturalPlan enriches it with the architectural
elements that turn it from a room-diagram into a real floor plan:

  - Door     : where each adjacency in the topology becomes a physical door,
               including its swing direction and clear width.
  - Window   : where each habitable room's exterior walls get window openings.
  - OpenPlanEdge: where two rooms with kind="open_plan" adjacency share a wall
                  that should NOT be drawn (great↔kitchen, living↔dining, etc.).

This module does NOT touch the solver or validator — it's purely a projection
of an already-validated layout. See render.py for how the plan is drawn.

Coordinate convention (matches model.py):
  - x increases EAST  (right)
  - y increases NORTH (rear / away from street)
  - Front of lot = SOUTH = smaller y
"""
from dataclasses import dataclass, field, replace as dc_replace
from typing import List, Optional, Tuple

from model import Layout, Rect, Room
from topology import Topology
from fixture_orientation import derive_orientations, RoomOrientation


# Door clear-width defaults by adjacency kind. Defaults match PD 1096 minima
# for the National Building Code of the Philippines:
#   main entrance / habitable exit: 0.90 m
#   bedroom / interior:             0.80 m
#   toilet & bath:                  0.70 m
DOOR_CLEAR_WIDTH_M = {
    "main_door":          0.90,
    "bedroom_door":       0.80,
    "bedroom_to_public":  0.80,
    "bath_door":          0.70,
    "ensuite_door":       0.70,
    "service_door":       0.80,    # kitchen-to-dirty-kitchen back door
}

# Corner-offset rule (PH practice): an interior door near a perpendicular
# wall should have its near edge at least 100–150 mm from the room corner
# (so there's space for the jamb, casing, and a light switch). Centered
# doors are only used for the main entrance and formal double doors.
CORNER_OFFSET_M = 0.15

# Adjacency kinds that DON'T get a door:
#   open_plan:               emit an OpenPlanEdge (wall removed when rendered)
#   wet_core:                solid plumbing wall, no door
#   bath_to_bedroom_wall:    bath shares a wall with a bedroom but no door
#                            (the bath is accessed from the LDK / hall, not
#                            directly from the bedroom — common in PH practice
#                            for shared common T&Bs that aren't ensuites)
#   bedroom_to_bedroom_wall: two bedrooms share a wall (stacked layout) but
#                            never connect through a door — each bedroom
#                            accesses circulation from the public side
_NO_DOOR_KINDS = {"open_plan", "wet_core", "bath_to_bedroom_wall",
                  "bedroom_to_bedroom_wall",
                  # wall_only — generic solid-wall adjacency. Used by the
                  # door-host machinery for group members not selected to
                  # host the door; usable directly in topologies too.
                  "wall_only",
                  # bedroom_to_public_wall — shared wall between a bedroom
                  # and a public room (great_room / living_room / dining_room)
                  # used to pin the public room's boundary to the bedroom's
                  # boundary WITHOUT emitting a door. The bedroom accesses
                  # public space via a different adjacency (e.g. through a
                  # hall). Geometry-only constraint.
                  "bedroom_to_public_wall"}

# Bedroom + common-bath pairs are ALWAYS wall-only regardless of the kind
# declared in the topology. Common T&B is shared/public; access is from the
# LDK or a hall, never directly from a private bedroom. (Ensuite baths are
# different — they DO open directly into their bedroom.)
_BEDROOM_TYPES = {"master_bedroom", "bedroom_standard", "maids_room"}
_COMMON_BATH_TYPES = {"common_bath", "bath_toilet", "powder_room"}

# Room-type pairs that are open-plan BY DEFAULT, regardless of the topology's
# declared adjacency kind. Reflects PH practice: the kitchen flows into the
# living / dining / great room without a wall between them unless the topology
# explicitly opts out (e.g., by declaring kind="wet_core" or kind="bath_door").
# An adjacency between these types gets treated as kind="open_plan" even if
# the JSON says kind="door" or kind="main_door".
_OPEN_PLAN_TYPE_PAIRS = {
    frozenset({"kitchen", "living_room"}),
    frozenset({"kitchen", "dining_room"}),
    frozenset({"kitchen", "great_room"}),
    frozenset({"living_room", "dining_room"}),
    frozenset({"dining_room", "great_room"}),
    frozenset({"living_room", "great_room"}),
    # Hallway is always open to the public LDK area — there's no door
    # between a hall and a great_room / living / dining / kitchen. The
    # hall connects bedrooms and baths to the LDK through an open mouth.
    frozenset({"hallway", "great_room"}),
    frozenset({"hallway", "living_room"}),
    frozenset({"hallway", "dining_room"}),
    frozenset({"hallway", "kitchen"}),
}


def _effective_kind(adj, room_a_type: str, room_b_type: str) -> str:
    """Override the topology's declared adjacency kind when the two room types
    form an LDK pair — those rooms have no wall between them by default."""
    if frozenset({room_a_type, room_b_type}) in _OPEN_PLAN_TYPE_PAIRS:
        return "open_plan"
    return adj.kind

# Zone privacy ranking for swing direction. Door swings into the more-private
# room (the room with the larger value here).
_ZONE_PRIVACY = {
    "circulation": 0,
    "public":      1,
    "service":     2,
    "private":     3,
}

HABITABLE = {"bedroom_standard", "master_bedroom", "living_room",
             "dining_room", "great_room", "maids_room"}
BATH_TYPES = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room"}

# Rooms that get an exterior window. Habitable rooms NEED a window for
# Sec. 808 compliance; baths and kitchens get one for ventilation per PH
# practice (kitchen window typically over the sink). Hallways, dirty
# kitchens, carports, etc. don't qualify.
WINDOWED_TYPES = HABITABLE | BATH_TYPES | {"kitchen"}

# Rooms whose window should use the small vent-style sizing (vs. the
# larger habitable-style window). Kitchens take the habitable style — the
# window over the sink is typically larger than a bath vent.
BATH_STYLE_WINDOW = set(BATH_TYPES)

# PH-practice sill height (m, from finished floor level) and typical glazed
# height (m). Pulled from developer plan packs (Camella, Avida) and UAP
# teaching notes. Sill heights:
#   bedroom        0.9 m — clears a typical bed headboard.
#   kitchen        1.1 m — sits above the 0.85 m counter + backsplash.
#   bath / WC      1.6 m — clerestory: above standing eye-level for privacy.
#   living/dining  0.7 m — low sill for view to street/yard.
# Glazed height is the window height itself; sill + height = head height.
# (Project default head ≈ 2.1 m to align with door head.)
PER_ROOM_WINDOW_DEFAULTS = {
    "master_bedroom":   {"sill": 0.90, "height": 1.20},
    "bedroom_standard": {"sill": 0.90, "height": 1.20},
    "maids_room":       {"sill": 0.90, "height": 1.00},
    "kitchen":          {"sill": 1.05, "height": 0.80},
    "common_bath":      {"sill": 1.60, "height": 0.50},
    "ensuite_bath":     {"sill": 1.60, "height": 0.50},
    "bath_toilet":      {"sill": 1.60, "height": 0.50},
    "powder_room":      {"sill": 1.70, "height": 0.40},
    "living_room":      {"sill": 0.70, "height": 1.40},
    "dining_room":      {"sill": 0.70, "height": 1.40},
    "great_room":       {"sill": 0.70, "height": 1.40},
}


# Side names use compass directions. N = rear, S = front (street), E = right,
# W = left. Each room has up to four walls keyed by these.
SIDES = ("N", "S", "E", "W")


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------

@dataclass
class Door:
    """A door opening between room_a and room_b. For the front door, room_a is
    the string 'exterior' and room_b is the entry-host room."""
    room_a: str
    room_b: str
    wall: str               # 'N'/'S'/'E'/'W' relative to room_a (or to room_b
                            # if room_a is 'exterior')
    position_m: float       # distance from the wall's NW endpoint to the door's
                            # near edge — depends on wall orientation:
                            #   N/S walls: distance from the west endpoint (x increases)
                            #   E/W walls: distance from the south endpoint (y increases)
    clear_width_m: float
    swing_into: str         # room_a or room_b — which room the door swings into
    kind: str               # main_door / bedroom_door / bath_door / etc.
    hinge_at: str = "low"   # "low" = hinge at the position_m end (W/S);
                            # "high" = hinge at the far end (E/N).
                            # Picked so the door swings open against the
                            # nearest perpendicular wall.
    cell_idx: int = 0       # which cell of room_a (or room_b for exterior
                            # doors) the door lives on — 0 = primary rect,
                            # 1 = rect2 (L-shape alcove). position_m is
                            # measured along THIS cell's wall, not the
                            # room's primary rect.


@dataclass
class Window:
    """A window opening in a room's exterior wall."""
    room: str               # room id
    wall: str               # 'N'/'S'/'E'/'W' — which side of the room
    position_m: float       # along the wall (same convention as Door)
    width_m: float
    height_m: float = 1.2   # typical PH window head height
    sill_height_m: float = 0.9


@dataclass
class OpenPlanEdge:
    """A shared wall that should NOT be drawn — the two rooms are open-plan.

    When the open-plan adjacency happens at one of the rooms' secondary
    cells (rect2 / alcove), cell_a / cell_b carry the specific cells the
    edge sits on. The renderer uses these to overdraw the right boundary;
    when None, the renderer falls back to the rooms' primary rects."""
    room_a: str
    room_b: str
    wall: str               # which side of cell_a (or room_a.rect) is open
    cell_a: Optional["Rect"] = None
    cell_b: Optional["Rect"] = None


@dataclass
class ArchPlan:
    """Architectural projection of a Layout + Topology pair. The Layout owns the
    room rectangles; this object adds the architectural elements on top."""
    layout: Layout
    topology: Topology
    doors: List[Door]                       = field(default_factory=list)
    windows: List[Window]                   = field(default_factory=list)
    open_plan_edges: List[OpenPlanEdge]     = field(default_factory=list)


# ----------------------------------------------------------------------------
# Geometric helpers
# ----------------------------------------------------------------------------

def _best_shared_edge_for_rooms(room_a, room_b, eps: float = 1e-3
                                ) -> Optional[Tuple[str, float, float, float, "Rect", "Rect"]]:
    """Scan every cell pair (room_a.cells × room_b.cells) for shared edges and
    return the LONGEST one as (side_of_cell_a, coord, start, end, cell_a,
    cell_b). For composite rooms (L-shape with rect2), this picks the right
    cell to place the door against — e.g., master.rect2 ↔ dining.rect when
    master is L-shaped and rect2 is what actually touches dining."""
    best = None
    best_len = 0.0
    for ca in room_a.cells:
        for cb in room_b.cells:
            edge = _shared_edge(ca, cb, eps=eps)
            if edge is None:
                continue
            side, coord, start, end = edge
            length = end - start
            if length > best_len:
                best_len = length
                best = (side, coord, start, end, ca, cb)
    return best


def _shared_edge(a: Rect, b: Rect, eps: float = 1e-3
                 ) -> Optional[Tuple[str, float, float, float]]:
    """If a and b share a wall, return (side_of_a, coord, start, end) where:
        side_of_a is one of N/S/E/W
        coord is the constant coordinate of the wall (x for E/W, y for N/S)
        start, end are the perpendicular range of the SHARED segment.
    Returns None if a and b don't share a wall.
    """
    # Vertical walls (x = constant)
    if abs(a.x1 - b.x0) <= eps:                    # a is west of b
        s = max(a.y0, b.y0)
        e = min(a.y1, b.y1)
        if e - s > eps:
            return ("E", a.x1, s, e)
    if abs(a.x0 - b.x1) <= eps:                    # a is east of b
        s = max(a.y0, b.y0)
        e = min(a.y1, b.y1)
        if e - s > eps:
            return ("W", a.x0, s, e)
    # Horizontal walls (y = constant)
    if abs(a.y1 - b.y0) <= eps:                    # a is south (front of) b
        s = max(a.x0, b.x0)
        e = min(a.x1, b.x1)
        if e - s > eps:
            return ("N", a.y1, s, e)
    if abs(a.y0 - b.y1) <= eps:                    # a is north (rear of) b
        s = max(a.x0, b.x0)
        e = min(a.x1, b.x1)
        if e - s > eps:
            return ("S", a.y0, s, e)
    return None


def _touches_exterior(rect: Rect, env: Rect, side: str, eps: float = 1e-3) -> bool:
    if side == "N": return abs(rect.y1 - env.y1) <= eps
    if side == "S": return abs(rect.y0 - env.y0) <= eps
    if side == "E": return abs(rect.x1 - env.x1) <= eps
    if side == "W": return abs(rect.x0 - env.x0) <= eps
    return False


def _wall_length(rect: Rect, side: str) -> float:
    if side in ("N", "S"): return rect.x1 - rect.x0   # horizontal wall
    return rect.y1 - rect.y0                          # vertical wall


def _wall_origin(rect: Rect, side: str) -> float:
    """The lower coordinate of the wall in its perpendicular axis.
    For N/S walls (horizontal): returns x0 (the west endpoint).
    For E/W walls (vertical):   returns y0 (the south endpoint).
    `position_m` on Door / Window is measured from this origin."""
    if side in ("N", "S"): return rect.x0
    return rect.y0


def _opposite(side: str) -> str:
    return {"N": "S", "S": "N", "E": "W", "W": "E"}[side]


def _perpendicular_walls_real(room: Room, wall: str, env: Rect,
                              all_rooms) -> Tuple[bool, bool]:
    """For `room`'s `wall`, classify each end of the wall by whether the
    perpendicular wall at that corner is ACTUALLY DRAWN.

    Returns (low_real, high_real) where:
      * "low"  end of the wall = west endpoint (N/S walls) or south endpoint
              (E/W walls). The perpendicular wall is the room's W or S side.
      * "high" end = east / north endpoint. The perpendicular wall is the
              room's E or N side.

    A perpendicular wall is "real" if it's either exterior (touches the
    buildable envelope edge) OR shared with a neighbor whose room-type pair
    with `room` is NOT in _OPEN_PLAN_TYPE_PAIRS. Open-plan boundaries get
    erased at render time, so a door hinged there has nothing to swing
    against — the corner is invisible."""
    if wall in ("N", "S"):
        low_perp_side, high_perp_side = "W", "E"
    else:
        low_perp_side, high_perp_side = "S", "N"

    def _real(perp_side: str) -> bool:
        if _touches_exterior(room.rect, env, perp_side):
            return True
        for other in all_rooms:
            if other.id == room.id:
                continue
            edge = _shared_edge(room.rect, other.rect)
            if edge is None or edge[0] != perp_side:
                continue
            if frozenset({room.type, other.type}) in _OPEN_PLAN_TYPE_PAIRS:
                return False
            return True
        # No neighbor on that perpendicular side and not exterior — could be a
        # building-void boundary. Treat as not-real so we avoid pinning a door
        # to a corner that has no perpendicular wall to swing against.
        return False

    return (_real(low_perp_side), _real(high_perp_side))


# ----------------------------------------------------------------------------
# Door / window logic
# ----------------------------------------------------------------------------

def _swing_into(room_a: Room, room_b: Room, kind: str) -> str:
    """Return the id of the room the door should swing into.
      - Bath doors swing into the BATH (so the bath door, if accidentally left
        open mid-swing, doesn't collide with bedroom furniture).
      - Front / main_door swings into room_b (the entry-host) by convention.
      - All other interior doors swing into the more-PRIVATE room
        (private > service > public > circulation). Tie goes to room_a."""
    # Bath rule first — it overrides the zone heuristic for ensuite/common.
    if room_a.type in BATH_TYPES and room_b.type not in BATH_TYPES:
        return room_a.id
    if room_b.type in BATH_TYPES and room_a.type not in BATH_TYPES:
        return room_b.id
    if kind == "main_door":
        return room_b.id
    pa = _ZONE_PRIVACY.get(room_a.zone, 1)
    pb = _ZONE_PRIVACY.get(room_b.zone, 1)
    return room_a.id if pa >= pb else room_b.id


def _door_for_adjacency(adj, layout: Layout,
                        topology: Optional[Topology] = None) -> Optional[Door]:
    """Emit a Door (or None) for a single topology adjacency.

    When `topology` is provided, the hinge selection also considers
    front_to_rear_stacks: a bedroom stacked with another bedroom prefers
    to hinge TOWARD the stack neighbor (so the two bedroom doors converge
    at the shared horizontal boundary, creating a clear 'bedroom-wing
    entry' rather than spreading doors along the great-room wall)."""
    room_a = next((r for r in layout.rooms if r.id == adj.a), None)
    room_b = next((r for r in layout.rooms if r.id == adj.b), None)
    if room_a is None or room_b is None:
        return None
    kind = _effective_kind(adj, room_a.type, room_b.type)
    if kind in _NO_DOOR_KINDS:
        return None
    # Generic rule: bedroom <-> common bath / WC / powder room is always a
    # wall, not a door. The common bath is shared and accessed from the LDK
    # or a hall, never directly from a private bedroom. Topologies that
    # declare such an adjacency (typically as a 'bath_to_bedroom_wall' kind,
    # but we don't trust them to do that consistently) get filtered here.
    types = {room_a.type, room_b.type}
    if types & _BEDROOM_TYPES and types & _COMMON_BATH_TYPES:
        return None
    # Scan all (cell_a, cell_b) pairs and pick the LONGEST shared edge.
    # This is what handles L-shape composites correctly: e.g., when master
    # has a rect2 alcove that touches dining, the door goes on rect2's
    # east wall (the long shared edge) rather than master.rect's east wall
    # (which might have a tiny or zero overlap with dining).
    best = _best_shared_edge_for_rooms(room_a, room_b)
    if best is None:
        return None
    side_a, coord, start, end, cell_a, cell_b = best
    shared_len = end - start
    clear = DOOR_CLEAR_WIDTH_M.get(adj.kind, 0.80)
    # Plumbing-band guard (door-host edges on wet walls): the shared edge
    # must keep `min_solid_wall_m` of continuous solid wall AFTER the door
    # (clear width + 2x 0.10 m frame) is placed. If it can't, this edge
    # refuses the door — the door-host group falls back to its default.
    min_solid = getattr(adj, "min_solid_wall_m", 0.0) or 0.0
    if min_solid > 0 and shared_len < clear + 0.20 + min_solid:
        return None
    # If the shared wall isn't long enough for the door + 0.1 m frame, skip.
    if shared_len < clear + 0.10:
        # Best we can do: shrink the door to fit, but never below the min spec.
        clear = max(0.60, shared_len - 0.10)
    # Door position & hinge orientation: PH "swing-against-nearest-wall" rule.
    # We pick whichever end of the SHARED EDGE has a REAL perpendicular wall
    # (exterior or non-open-plan neighbor) — open-plan boundaries get erased
    # at render time, so hinging against them is wrong. The hinge sits at
    # that corner so the panel swings open against that perpendicular wall
    # at 180°. If both corners are real (or both fake), fall back to the
    # nearer-corner rule; ties go LOW for consistency.
    env = layout.lot.envelope()
    # wall geometry uses the CELL that's actually sharing the edge with room_b
    # (not room_a.rect) — important for L-shape composites where the door
    # lives on rect2's wall, not rect's wall.
    wall_origin = _wall_origin(cell_a, side_a)
    wall_end = wall_origin + _wall_length(cell_a, side_a)
    dist_low_to_corner  = start - wall_origin       # how far the shared edge's
    dist_high_to_corner = wall_end - end            # ends are from cell_a's
                                                    # perpendicular walls
    low_real, high_real = _perpendicular_walls_real(
        room_a, side_a, env, layout.rooms)
    # Stack-bias for bedroom doors: if this is a bedroom-to-public door AND
    # the bedroom is in a front_to_rear_stack with another bedroom, prefer
    # to hinge TOWARD the stack neighbor so the two bedroom doors cluster
    # at the shared horizontal boundary (a clean 'bedroom-wing entry').
    stack_bias = None
    if topology is not None and side_a in ("E", "W"):
        # The "bedroom" side of this adjacency is room_a iff it's a bedroom
        # type. Same for room_b; in practice only one is a bedroom.
        bedroom_for_stack = None
        if room_a.type in _BEDROOM_TYPES:
            bedroom_for_stack = room_a
        elif room_b.type in _BEDROOM_TYPES:
            bedroom_for_stack = room_b
        if bedroom_for_stack is not None:
            for stack in topology.front_to_rear_stacks or []:
                if bedroom_for_stack.id not in stack:
                    continue
                idx = stack.index(bedroom_for_stack.id)
                # bedroom-type ids in this stack other than this one
                bedroom_ids_in_stack = {
                    rid for rid in stack
                    if rid != bedroom_for_stack.id and
                    next((r for r in layout.rooms if r.id == rid), None) and
                    next(r for r in layout.rooms if r.id == rid).type in _BEDROOM_TYPES
                }
                if not bedroom_ids_in_stack:
                    break
                front_of = set(stack[:idx])
                rear_of  = set(stack[idx + 1:])
                has_front_bedroom = bool(front_of & bedroom_ids_in_stack)
                has_rear_bedroom  = bool(rear_of  & bedroom_ids_in_stack)
                # On E/W walls: HIGH end of wall = rear (high y), LOW = front.
                if has_rear_bedroom and not has_front_bedroom:
                    stack_bias = "high"
                elif has_front_bedroom and not has_rear_bedroom:
                    stack_bias = "low"
                break

    # Hinge selection priority:
    #   0. Stack-bias (bedroom in a bedroom-stack — hinge toward stack neighbor).
    #   1. Exactly one corner has a real perpendicular wall — use that one.
    #   2. Both real (or both fake) — fall back to nearer corner; ties LOW.
    if stack_bias:
        prefer = stack_bias
    elif low_real and not high_real:
        prefer = "low"
    elif high_real and not low_real:
        prefer = "high"
    else:
        prefer = "low" if dist_low_to_corner <= dist_high_to_corner else "high"
    # main_door (front entry) always snaps to a room corner — it should
    # never float mid-wall. Other doors use the corner snap only when the
    # shared edge already starts/ends at the wall corner.
    force_corner = (kind == "main_door")
    if prefer == "low":
        hinge_at = "low"
        if dist_low_to_corner < 0.01 or force_corner:
            # Shared edge starts AT room_a's wall corner (or front door):
            # push the door 150 mm in from that corner.
            position_m = CORNER_OFFSET_M
        else:
            # Shared edge starts mid-wall — hinge at the LOW end of the edge.
            position_m = start - wall_origin
    else:
        hinge_at = "high"
        if dist_high_to_corner < 0.01 or force_corner:
            # Shared edge ends AT room_a's wall corner (or front door):
            # push door 150 mm back from that corner.
            position_m = (end - wall_origin) - CORNER_OFFSET_M - clear
        else:
            # Shared edge ends mid-wall — anchor the door's HIGH end at the
            # edge end.
            position_m = (end - wall_origin) - clear
    # Clamp: the door must fit inside the shared edge.
    min_pos = start - wall_origin
    max_pos = (end - wall_origin) - clear
    if position_m < min_pos: position_m = min_pos
    if position_m > max_pos: position_m = max_pos
    # Index of cell_a in room_a.cells — needed by the renderer so it can pick
    # the right cell when the room is an L-shape composite.
    cell_idx = 0
    for i, c in enumerate(room_a.cells):
        if c is cell_a:
            cell_idx = i
            break
    return Door(
        room_a=adj.a, room_b=adj.b, wall=side_a,
        position_m=round(position_m, 3),
        clear_width_m=round(clear, 3),
        swing_into=_swing_into(room_a, room_b, adj.kind),
        kind=adj.kind,
        hinge_at=hinge_at,
        cell_idx=cell_idx,
    )


def _open_plan_edges_for_adjacency(adj, layout: Layout) -> List[OpenPlanEdge]:
    """Build OpenPlanEdges for `adj` across ALL cell-pair combinations of
    the two rooms (so composite L-shaped rooms get one edge per shared
    boundary, not just one for the primary rects). Caller is responsible
    for deciding whether the adjacency is actually open-plan."""
    room_a = next((r for r in layout.rooms if r.id == adj.a), None)
    room_b = next((r for r in layout.rooms if r.id == adj.b), None)
    if room_a is None or room_b is None:
        return []
    out = []
    for ca in room_a.cells:
        for cb in room_b.cells:
            edge = _shared_edge(ca, cb)
            if edge is None:
                continue
            out.append(OpenPlanEdge(room_a=adj.a, room_b=adj.b,
                                    wall=edge[0],
                                    cell_a=ca, cell_b=cb))
    return out


def _free_segments(wall_len: float, blockers: List[Tuple[float, float]],
                    clearance: float = 0.30) -> List[Tuple[float, float]]:
    """Subtract a list of `blocker` intervals (in wall-local coords, each
    expanded by `clearance` on each side for jamb/casing) from [0, wall_len].
    Returns the remaining FREE intervals sorted by descending length."""
    if not blockers:
        return [(0.0, wall_len)]
    expanded = [(max(0.0, s - clearance), min(wall_len, e + clearance))
                for s, e in blockers]
    expanded.sort()
    merged = [expanded[0]]
    for s, e in expanded[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    free: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in merged:
        if s > cursor + 1e-6:
            free.append((cursor, s))
        cursor = max(cursor, e)
    if wall_len > cursor + 1e-6:
        free.append((cursor, wall_len))
    free.sort(key=lambda iv: iv[1] - iv[0], reverse=True)
    return free


def _windows_for_room(room: Room, env: Rect, bath: bool,
                      door_segments: dict, firewall_sides: set,
                      orientation: Optional[RoomOrientation] = None) -> List[Window]:
    """Place windows on the exterior walls of `room`.

    `door_segments` maps side → list of (start, end) door footprints in
    wall-local coordinates. A wall may carry BOTH a door and a window (e.g.,
    the front door + a living-room picture window on the same south wall) as
    long as there's a wall segment of sufficient length, separated from the
    door by ~0.30 m of jamb/casing clearance.

    `firewall_sides` (lot setback = 0) get no openings at all (PD 1096 §704;
    RA 9514 firewall rule)."""
    out: List[Window] = []
    # Score each candidate side; orientation hints add or subtract priority
    # so window placement matches PH practice (kitchen window over the sink
    # wall; bedroom window NOT on the head wall; bath window NOT on the
    # wet/shower wall). Hints are SOFT — if the only available exterior wall
    # is the "wrong" one, we still place a window there for §808 compliance.
    candidates: List[tuple] = []      # (priority, side)
    for side in SIDES:
        if side in firewall_sides:
            continue
        if not _touches_exterior(room.rect, env, side):
            continue
        priority = 0.0
        if orientation is not None:
            if orientation.sink_wall == side:    priority += 5.0   # kitchen
            if orientation.head_wall == side:    priority -= 3.0   # bedroom
            if orientation.wet_wall == side:     priority -= 4.0   # bath
            if orientation.shower_wall == side:  priority -= 2.0   # bath
        # Mild tie-breaker by wall length — prefer the longer wall.
        priority += _wall_length(room.rect, side) * 0.01
        candidates.append((priority, side))
    candidates.sort(reverse=True)
    for _, side in candidates:
        wall_len = _wall_length(room.rect, side)
        free = _free_segments(wall_len, door_segments.get(side, []))
        if not free:
            continue
        # Use the largest free segment.
        seg_start, seg_end = free[0]
        seg_len = seg_end - seg_start
        if bath:
            w = max(0.6, min(0.9, seg_len * 0.5))
        else:
            w = max(0.9, min(2.4, seg_len * 0.55))
        # Centering inside the free segment already gives a corner offset;
        # we only need a tiny extra slack to keep the jamb off the wall
        # corner / door jamb (which the 0.30 m clearance already includes).
        if seg_len < w + 0.05:
            # Try shrinking to a minimum-size window for ventilation.
            min_w = 0.6 if bath else 0.9
            if seg_len < min_w + 0.05:
                continue
            w = min_w
        pos = seg_start + (seg_len - w) / 2.0          # center in free segment
        defaults = PER_ROOM_WINDOW_DEFAULTS.get(room.type, {})
        out.append(Window(
            room=room.id, wall=side,
            position_m=round(pos, 3),
            width_m=round(w, 3),
            height_m=defaults.get("height", 1.2),
            sill_height_m=defaults.get("sill", 0.9),
        ))
    return out


def _dirty_kitchen_door(topology: Topology, layout: Layout,
                        env: Rect, force: bool = False) -> Optional[Door]:
    """Emit a service door from the kitchen to the exterior on its rear wall.

    When `force` is True (brief.kitchen_back_door = True, the default), the
    door is generated unconditionally — PH practice always has a kitchen back
    door, regardless of whether a dirty kitchen is present in the setback.
    When `force` is False (legacy / explicit opt-out), the door is generated
    only when the topology declares a dirty_kitchen setback element."""
    dk = next((sb for sb in topology.setback_elements
               if sb.type == "dirty_kitchen"), None)
    if dk is None and not force:
        return None
    # Which room sits in front of the dirty kitchen (or just the kitchen when
    # no dirty kitchen is declared)? Default to 'kitchen'.
    behind_id = (dk.behind if dk else None) or "kitchen"
    room = next((r for r in layout.rooms if r.id == behind_id), None)
    if room is None:
        return None
    # The dirty kitchen sits at the REAR setback (per the topology field
    # location='rear_setback'), so the door is on the room's NORTH wall —
    # which is also the wall that touches the buildable envelope rear edge.
    if not _touches_exterior(room.rect, env, "N"):
        return None
    wall_len = _wall_length(room.rect, "N")
    clear = 0.80   # standard service door clear opening
    if wall_len < clear + 0.20:
        clear = max(0.60, wall_len - 0.20)
    # PH practice: doors from the kitchen always sit at a CORNER, against a
    # REAL perpendicular wall. The kitchen's west and east sides may include
    # open-plan boundaries (e.g., kitchen↔great_room) that don't get drawn —
    # hinging the door at such a "corner" leaves it swinging against nothing.
    # Pick the side with a real perpendicular wall (exterior or non-open-plan
    # neighbor). If both qualify, default to LOW (west).
    low_real, high_real = _perpendicular_walls_real(
        room, "N", env, layout.rooms)
    if high_real and not low_real:
        pos = wall_len - CORNER_OFFSET_M - clear
        hinge_at = "high"
    else:
        pos = CORNER_OFFSET_M
        hinge_at = "low"
    if pos + clear + 0.10 > wall_len:
        # Wall too short — fall back to whatever fits.
        pos = max(0.0, wall_len - clear - 0.10)
    if pos < 0.0:
        pos = 0.0
    return Door(
        room_a="exterior", room_b=behind_id, wall="N",
        position_m=round(pos, 3),
        clear_width_m=round(clear, 3),
        swing_into=behind_id,
        kind="service_door",
        hinge_at=hinge_at,
    )


def _front_door(topology: Topology, layout: Layout, env: Rect,
                existing_doors: Optional[List["Door"]] = None) -> Optional[Door]:
    """The entry-host room gets a front door on whichever exterior wall faces
    the street (south by convention, falling back to any exterior wall).

    `existing_doors`: interior doors already placed in this layout. When the
    front door's natural centered position would land near an interior door
    on a perpendicular wall (the entry door would open into another door —
    e.g., the main entry directly facing the master-bedroom door across the
    threshold), shift the front door to the OPPOSITE corner of the entry
    wall so the two doors no longer face each other.
    """
    entry_id = topology.entry_point
    entry_room = next((r for r in layout.rooms if r.id == entry_id), None)
    if entry_room is None:
        return None
    # Prefer south (street side); else any exterior side.
    chosen = None
    for side in ("S", "E", "W", "N"):
        if _touches_exterior(entry_room.rect, env, side):
            chosen = side
            break
    if chosen is None:
        return None
    wall_len = _wall_length(entry_room.rect, chosen)
    clear = DOOR_CLEAR_WIDTH_M["main_door"]
    if wall_len < clear + 0.30:
        clear = max(0.80, wall_len - 0.30)
    # Front-door placement: always at the low corner (PH practice — entry
    # door sits at one side of the living/great room facade, not centred).
    # The corner-threat check below will push to high corner or, as a last
    # resort, to centre if both corners are already occupied by interior doors.
    pos = CORNER_OFFSET_M
    hinge_at = "low"

    # Avoid placing the front door near a corner that's already occupied by
    # an interior door on a perpendicular wall of the entry-host room.
    threatened = _entry_wall_threatened_corners(
        entry_room, chosen, existing_doors or [])
    low_pos = CORNER_OFFSET_M
    high_pos = wall_len - CORNER_OFFSET_M - clear
    if threatened == {"low"}:
        pos, hinge_at = high_pos, "high"
    elif threatened == {"high"}:
        pos, hinge_at = low_pos, "low"
    elif threatened == {"low", "high"}:
        # Both corners taken — centered is the best of the bad options.
        pos = (wall_len - clear) / 2.0
        hinge_at = "low"

    return Door(
        room_a="exterior", room_b=entry_id, wall=chosen,
        position_m=round(pos, 3),
        clear_width_m=round(clear, 3),
        swing_into=entry_id,
        kind="main_door",
        hinge_at=hinge_at,
    )


def _entry_wall_threatened_corners(entry_room, entry_side, doors):
    """Return the set of {'low', 'high'} for entry-wall corners that already
    have an interior door on the abutting perpendicular wall of the entry-
    host room. Front door placed at such a corner would open into the other
    door's threshold."""
    threatened = set()
    # Each entry side has a low and high corner; map the perpendicular walls
    # of the entry room that hit each corner.
    threat_map = {
        "S": ("W", "E"),     # S wall: low corner at W, high at E
        "N": ("W", "E"),
        "W": ("S", "N"),     # W wall: low corner at S, high at N
        "E": ("S", "N"),
    }
    if entry_side not in threat_map:
        return threatened
    low_perp, high_perp = threat_map[entry_side]
    # Threshold: distance from corner along the perp-wall axis under which
    # an interior door 'threatens' the corner. CORNER_OFFSET_M is where
    # interior doors typically anchor; +0.5 m buffer covers the swing arc.
    threshold = CORNER_OFFSET_M + 0.5
    for door in doors:
        if door.room_a == entry_room.id:
            door_side_from_entry = door.wall
        elif door.room_b == entry_room.id:
            door_side_from_entry = _opposite(door.wall)
        else:
            continue
        if door_side_from_entry not in (low_perp, high_perp):
            continue
        # door.position_m is local from the perp wall's wall_origin (the
        # "low" end of the perp wall, which is the corner closest to the
        # entry wall when entry_side is S or W; for N or E entry sides the
        # corner closer to the entry wall is at the perp wall's HIGH end).
        if entry_side in ("S", "W"):
            close_to_corner = door.position_m <= threshold
            far_from_corner = (door.position_m + door.clear_width_m) >= \
                (_wall_length_for_perp(entry_room, door_side_from_entry) - threshold)
        else:
            close_to_corner = (door.position_m + door.clear_width_m) >= \
                (_wall_length_for_perp(entry_room, door_side_from_entry) - threshold)
            far_from_corner = door.position_m <= threshold
        # 'close_to_corner' relative to entry wall side
        if close_to_corner:
            if door_side_from_entry == low_perp:
                threatened.add("low")
            else:
                threatened.add("high")
    return threatened


def _wall_length_for_perp(room, side):
    if side in ("N", "S"):
        return room.rect.x1 - room.rect.x0
    return room.rect.y1 - room.rect.y0


# ----------------------------------------------------------------------------
# Door-host scoring (Phase 2 of door-host selection)
# ----------------------------------------------------------------------------
# When a door_host_group offers more than one eligible host wall and the
# brief doesn't pick one explicitly, the host is chosen by scoring. The
# principle: a door sterilizes the floor in front of it (approach clearance)
# and breaks a wall that could otherwise hold furniture — but that cost is
# ~zero when the approach zone lands on floor that is ALREADY circulation
# (e.g. the kitchen aisle serving the dirty-kitchen back door). Components:
#
#   + circulation overlap : fraction of the door's approach zone overlapping
#                           a circulation corridor (front-door spine, the
#                           dirty-kitchen door's aisle, hallway rooms)
#   + freed wall          : furnishable wall length (>= 1.5 m) the LOSING
#                           candidates keep solid in public rooms
#   - sanitary penalty    : bath door opening into a kitchen (soft rule —
#                           the validator additionally flags it)
#   - wet-wall penalty    : door cut into a wet_core plumbing wall
#
# Ties (and everything short of a strict improvement) keep the topology's
# authored default host, so renders only change when the gain is real.
DOOR_HOST_W_CIRCULATION    = 4.0   # x overlap fraction (0..1)
DOOR_HOST_W_FREED_WALL     = 1.0   # x meters of freed furnishable public wall
DOOR_HOST_P_SANITARY       = 0.5   # bath door into kitchen (soft rule — validator already flags; was 2.0)
DOOR_HOST_P_WET_WALL       = 0.5   # door on a wet_core plumbing wall (was 1.0)
DOOR_HOST_APPROACH_DEPTH_M = 1.2   # approach clearance in front of a door
DOOR_HOST_FURNISHABLE_MIN_M = 1.0  # min solid run that counts as furnishable (was 1.5)

# Freed-wall credit only counts walls returned to PUBLIC rooms (where solid
# wall = furniture placement); service rooms keep their walls busy anyway.
_PUBLIC_FREED_TYPES = {"great_room", "living_room", "dining_room"}


def _rect_intersection(a, b):
    """Intersection of two (x0, y0, x1, y1) tuples, or None."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _rect_area(r) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _door_segment_abs(door: "Door", rooms_by_id: dict):
    """Absolute geometry of a door's wall footprint as (side, wall_coord,
    lo, hi). Interior doors are positioned in room_a's cell frame; exterior
    doors (room_a not a room, e.g. 'exterior') in room_b's primary cell."""
    if door.room_a in rooms_by_id:
        room = rooms_by_id[door.room_a]
        cells = room.cells
        cell = cells[min(door.cell_idx, len(cells) - 1)]
    else:
        cell = rooms_by_id[door.room_b].cells[0]
    s = door.wall
    if s in ("N", "S"):
        lo = cell.x0 + door.position_m
        hi = lo + door.clear_width_m
        coord = cell.y1 if s == "N" else cell.y0
    else:
        lo = cell.y0 + door.position_m
        hi = lo + door.clear_width_m
        coord = cell.x1 if s == "E" else cell.x0
    return s, coord, lo, hi


def _door_band(door: "Door", rooms_by_id: dict, depth: float):
    """Band of `depth` to BOTH sides of the door's wall segment. Intersect
    with a room's cells to get the approach zone on that room's side."""
    s, coord, lo, hi = _door_segment_abs(door, rooms_by_id)
    if s in ("N", "S"):
        return (lo, coord - depth, hi, coord + depth)
    return (coord - depth, lo, coord + depth, hi)


def _door_corridor_zone(door: "Door", rooms_by_id: dict):
    """Approach corridor of an exterior door: the door's wall footprint
    extruded DOOR_HOST_APPROACH_DEPTH_M into the host room.

    Previously used full room depth, which caused false circulation-overlap
    credit: a bath door at the rear of a large room scored as if it shared
    the same circulation path as the front door at the opposite end, because
    the front-door corridor spanned the entire room. Capping at approach depth
    means overlap is only awarded when the two door zones genuinely share floor.
    """
    cell = rooms_by_id[door.room_b].cells[0]
    s, coord, lo, hi = _door_segment_abs(door, rooms_by_id)
    D = DOOR_HOST_APPROACH_DEPTH_M
    if s == "S":   # front door faces north into room
        return (lo, coord, hi, min(coord + D, cell.y1))
    elif s == "N": # rear door faces south into room
        return (lo, max(coord - D, cell.y0), hi, coord)
    elif s == "E": # east door faces west into room
        return (max(coord - D, cell.x0), lo, coord, hi)
    else:          # "W" — west door faces east into room
        return (coord, lo, min(coord + D, cell.x1), hi)


def _circulation_zones(topology: Topology, layout: Layout, env: Rect,
                       kitchen_back_door: bool = True) -> list:
    """Prospective circulation corridors used as scoring anchors: the
    front-door spine, the dirty-kitchen door's aisle, and hallway rooms.
    The exterior doors are computed prospectively (Pass 2/2b will recompute
    them with full door context; positions are deterministic and match in
    practice)."""
    zones = []
    rooms_by_id = {r.id: r for r in layout.rooms}
    fd = _front_door(topology, layout, env)
    if fd and fd.room_b in rooms_by_id:
        zones.append(_door_corridor_zone(fd, rooms_by_id))
    dk = _dirty_kitchen_door(topology, layout, env, force=kitchen_back_door)
    if dk and dk.room_b in rooms_by_id:
        zones.append(_door_corridor_zone(dk, rooms_by_id))
    for r in layout.rooms:
        if r.type == "hallway":
            for c in r.cells:
                zones.append((c.x0, c.y0, c.x1, c.y1))
    return zones


def _score_door_host(member, door: "Door", group_room: Room, host_room: Room,
                     members: list, zones: list, rooms_by_id: dict) -> float:
    """Score one door-host candidate. Higher = better host wall."""
    score = 0.0
    # --- circulation overlap: approach zone ∩ circulation corridors -------
    band = _door_band(door, rooms_by_id, DOOR_HOST_APPROACH_DEPTH_M)
    approach = []
    for c in host_room.cells:
        r = _rect_intersection(band, (c.x0, c.y0, c.x1, c.y1))
        if r:
            approach.append(r)
    a_area = sum(_rect_area(r) for r in approach)
    if a_area > 1e-9:
        overlap = 0.0
        for ar in approach:
            for z in zones:
                hit = _rect_intersection(ar, z)
                if hit:
                    overlap += _rect_area(hit)
        score += DOOR_HOST_W_CIRCULATION * min(overlap / a_area, 1.0)
    # --- freed furnishable wall in public rooms ---------------------------
    for m in members:
        if m is member:
            continue
        other_id = m.b if m.a == group_room.id else m.a
        other = rooms_by_id.get(other_id)
        if other is None or other.type not in _PUBLIC_FREED_TYPES:
            continue
        best = _best_shared_edge_for_rooms(group_room, other)
        if best:
            length = best[3] - best[2]
            if length >= DOOR_HOST_FURNISHABLE_MIN_M - 1e-9:
                score += DOOR_HOST_W_FREED_WALL * length
    # --- penalties ---------------------------------------------------------
    if group_room.type in BATH_TYPES and host_room.type == "kitchen":
        score -= DOOR_HOST_P_SANITARY
    if member.kind == "wet_core":
        score -= DOOR_HOST_P_WET_WALL
    return score


# ----------------------------------------------------------------------------
# Public entrypoint
# ----------------------------------------------------------------------------

def architecturalize(layout: Layout, topology: Topology,
                     door_host: Optional[dict] = None,
                     kitchen_back_door: bool = True) -> ArchPlan:
    """Project the topology onto the (snapped) layout to produce doors,
    windows, and open-plan-edge metadata.

    `door_host` ({room_id: neighbor_id}, usually from the brief) overrides
    which member of a door_host_group hosts the room's door. Invalid or
    geometrically un-honorable overrides fall back to the group's default
    (the member authored with a door kind).

    `kitchen_back_door` (default True): when True, a service door is always
    generated on the kitchen's rear exterior wall — even when no dirty kitchen
    is present. Set False to seal the kitchen's rear wall entirely."""
    plan = ArchPlan(layout=layout, topology=topology)
    env = layout.lot.envelope()

    # ------------------------------------------------------------------
    # Porch — always-on uncovered landing in the front setback.
    # Generated HERE (post-snap) so the width matches the final snapped
    # entry-room position, not the pre-snap solver output.
    # EXCEPTION: suppressed when carport_side == "front" (the carport
    # occupies the front setback — no room for a porch landing).
    # ------------------------------------------------------------------
    if layout.carport_side != "front":
        _ep_id = topology.entry_point
        _entry_r = next((r for r in layout.rooms if r.id == _ep_id), None)
        if _entry_r is None:
            _entry_r = next(
                (r for r in layout.rooms
                 if r.type in ("living_room", "great_room")), None
            )
        if _entry_r is not None:
            # Clamp only to lot boundary; rooms are always within the buildable
            # envelope so this guard should never actually clip.
            _px0 = max(0.0, _entry_r.rect.x0)
            _px1 = min(layout.lot.width, _entry_r.rect.x1)
            _py0 = round(layout.lot.front - 1.5, 3)
            _py1 = layout.lot.front
            # Replace any existing porch element (idempotent if called twice).
            layout.elements = [e for e in layout.elements if e.type != "porch"]
            layout.elements.append(Room("porch", "porch",
                                        Rect(_px0, _py0, _px1, _py1),
                                        "public", covered=False))

    # Track per-(room, side) door footprints (start, end in wall-local m)
    # so windows can coexist on the same wall as a door when there's room.
    door_segments_by_room: dict = {}     # {(room_id, side): [(start, end), ...]}
    rooms_by_id = {r.id: r for r in layout.rooms}

    def _record_door(room_id: str, side: str, start_m: float, end_m: float):
        door_segments_by_room.setdefault((room_id, side), []).append(
            (start_m, end_m))

    def _record_interior_door(door: "Door"):
        """Record an interior door on BOTH rooms' walls, converting the
        position_m (which is local to room_a's wall_origin) into room_b's
        wall_origin frame on the opposite wall."""
        a_id, a_side = door.room_a, door.wall
        b_id, b_side = door.room_b, _opposite(door.wall)
        a_local_start = door.position_m
        a_local_end   = a_local_start + door.clear_width_m
        _record_door(a_id, a_side, a_local_start, a_local_end)
        r_a = rooms_by_id[a_id]
        r_b = rooms_by_id[b_id]
        if door.wall in ("N", "S"):
            abs_start = r_a.rect.x0 + a_local_start
            abs_end   = r_a.rect.x0 + a_local_end
            b_local_start = abs_start - r_b.rect.x0
            b_local_end   = abs_end   - r_b.rect.x0
        else:
            abs_start = r_a.rect.y0 + a_local_start
            abs_end   = r_a.rect.y0 + a_local_end
            b_local_start = abs_start - r_b.rect.y0
            b_local_end   = abs_end   - r_b.rect.y0
        _record_door(b_id, b_side, b_local_start, b_local_end)

    # Pass 1a: door-host groups. Adjacencies sharing a door_host_group are
    # alternate hosts for one room's door — exactly ONE member emits a door;
    # the others render solid. Selection: brief override (door_host) if it
    # names a valid member, else the member authored with a door kind. If
    # the chosen edge refuses the door (e.g. the plumbing-band guard on a
    # wet_core wall fails), fall back to the default member.
    host_groups: dict = {}     # group name -> [adj, ...]
    for adj in topology.adjacencies:
        g = getattr(adj, "door_host_group", None)
        if g:
            host_groups.setdefault(g, []).append(adj)
    grouped_ids = {id(a) for members in host_groups.values() for a in members}

    def _door_emit_adj(member):
        """The adjacency to actually emit a door for: members declared with
        a no-door kind (wet_core etc.) get their kind swapped to door_kind
        so _door_for_adjacency treats them as a door edge."""
        if member.kind in _NO_DOOR_KINDS:
            return dc_replace(member,
                              kind=getattr(member, "door_kind", None) or "bath_door")
        return member

    circ_zones = None    # lazily computed — only when a group needs scoring
    for gname, members in host_groups.items():
        # The group's room = the room id common to all members.
        common_ids = {members[0].a, members[0].b}
        for m in members[1:]:
            common_ids &= {m.a, m.b}
        group_room_id = next(iter(common_ids)) if len(common_ids) == 1 else None

        default = next((m for m in members if m.kind not in _NO_DOOR_KINDS),
                       None)
        # Eligible members + their prospective doors, default first so that
        # scoring ties (strict-improvement rule) keep the authored default.
        ordered = ([default] if default is not None else []) + \
                  [m for m in members if m is not default]
        cand = []   # [(member, prospective Door), ...]
        for m in ordered:
            if m.kind in _NO_DOOR_KINDS and not getattr(m, "door_allowed", False):
                continue
            emit_adj = _door_emit_adj(m)
            if emit_adj.a not in rooms_by_id or emit_adj.b not in rooms_by_id:
                continue
            d = _door_for_adjacency(emit_adj, layout, topology=topology)
            if d:
                cand.append((m, d))
        if not cand:
            continue

        chosen = None
        # 1. Brief override wins outright (if its door is realizable).
        if door_host:
            for room_id, neighbor_id in door_host.items():
                hit = next((c for c in cand
                            if {c[0].a, c[0].b} == {room_id, neighbor_id}),
                           None)
                if hit:
                    chosen = hit
                    break
        # 2. Auto selection: score every candidate; a non-default host must
        #    STRICTLY beat the incumbent to win.
        if chosen is None and len(cand) > 1 and group_room_id is not None:
            if circ_zones is None:
                circ_zones = _circulation_zones(topology, layout, env,
                                                kitchen_back_door=kitchen_back_door)
            group_room = rooms_by_id[group_room_id]
            best, best_score = None, None
            for m, d in cand:
                host_id = m.b if m.a == group_room_id else m.a
                host_room = rooms_by_id.get(host_id)
                if host_room is None:
                    continue
                s = _score_door_host(m, d, group_room, host_room, members,
                                     circ_zones, rooms_by_id)
                if best_score is None or s > best_score + 1e-9:
                    best, best_score = (m, d), s
            chosen = best
        # 3. Single candidate / no scoring possible: default-first order.
        if chosen is None:
            chosen = cand[0]
        plan.doors.append(chosen[1])
        _record_interior_door(chosen[1])

    # Pass 1: doors and open-plan edges from topology adjacencies
    for adj in topology.adjacencies:
        if id(adj) in grouped_ids:
            continue   # handled in Pass 1a
        ra, rb = rooms_by_id.get(adj.a), rooms_by_id.get(adj.b)
        if ra is None or rb is None:
            continue
        kind = _effective_kind(adj, ra.type, rb.type)
        if kind == "open_plan":
            for ope in _open_plan_edges_for_adjacency(adj, layout):
                plan.open_plan_edges.append(ope)
            continue
        if kind == "wet_core":
            continue
        door = _door_for_adjacency(adj, layout, topology=topology)
        if door:
            plan.doors.append(door)
            _record_interior_door(door)

    # Pass 2: front door — only one side is a real room. Pass already-
    # placed interior doors so _front_door can avoid threading the entry
    # straight into another door's swing.
    fd = _front_door(topology, layout, env, existing_doors=list(plan.doors))
    if fd:
        plan.doors.append(fd)
        _record_door(fd.room_b, fd.wall,
                     fd.position_m, fd.position_m + fd.clear_width_m)

    # Pass 2b: kitchen back door (service door to exterior / dirty kitchen).
    # Generated whenever kitchen_back_door=True (the default), even when no
    # dirty kitchen is present in the setback.
    dk_door = _dirty_kitchen_door(topology, layout, env, force=kitchen_back_door)
    if dk_door:
        plan.doors.append(dk_door)
        _record_door(dk_door.room_b, dk_door.wall,
                     dk_door.position_m,
                     dk_door.position_m + dk_door.clear_width_m)

    # Pass 2c: derive per-room wall-function hints (RoomOrientation) from
    # the door layout. Used by Pass 3 below to steer window placement to
    # the PH-practice wall (kitchen → sink wall, bath → away from wet/shower
    # walls, bedroom → away from head wall).
    door_walls_by_room: dict = {}
    for (room_id, side) in door_segments_by_room.keys():
        door_walls_by_room.setdefault(room_id, set()).add(side)
    orientations = derive_orientations(layout, env, door_walls_by_room)

    # Pass 3: windows for habitable + bath + kitchen on remaining exterior
    # walls, skipping any firewall sides (lot setback = 0).
    lot = layout.lot
    firewall_sides = set()
    if lot.left == 0:  firewall_sides.add("W")
    if lot.right == 0: firewall_sides.add("E")
    if lot.front == 0: firewall_sides.add("S")
    if lot.rear == 0:  firewall_sides.add("N")
    for r in layout.rooms:
        if r.type not in WINDOWED_TYPES:
            continue
        bath_style = r.type in BATH_STYLE_WINDOW
        # Build {side: [door segments]} for this room
        door_segments = {}
        for (room_id, side), segs in door_segments_by_room.items():
            if room_id == r.id:
                door_segments[side] = segs
        plan.windows.extend(_windows_for_room(
            r, env, bath_style, door_segments, firewall_sides,
            orientation=orientations.get(r.id)))

    return plan


# ----------------------------------------------------------------------------
# CLI / interactive spot-check
# ----------------------------------------------------------------------------

def _print_plan(plan: ArchPlan) -> None:
    print(f"=== ArchPlan for topology '{plan.topology.id}' ===")
    print(f"  envelope: {plan.layout.lot.envelope()}")
    print(f"\n  Doors ({len(plan.doors)}):")
    for d in plan.doors:
        print(f"    {d.room_a:>9s} <-> {d.room_b:<10s}  wall={d.wall}  "
              f"pos={d.position_m:.2f} m  clear={d.clear_width_m:.2f} m  "
              f"swing→{d.swing_into}  kind={d.kind}")
    print(f"\n  Open-plan edges ({len(plan.open_plan_edges)}):")
    for o in plan.open_plan_edges:
        print(f"    {o.room_a:>9s} <-> {o.room_b:<10s}  wall={o.wall}")
    print(f"\n  Windows ({len(plan.windows)}):")
    for w in plan.windows:
        print(f"    {w.room:>9s}  wall={w.wall}  pos={w.position_m:.2f} m  "
              f"width={w.width_m:.2f} m")


if __name__ == "__main__":
    # Interactive spot-check: take a topology + lot, solve, snap, archplan, print.
    import argparse, os, sys
    _SOLVER_DIR = os.path.dirname(os.path.abspath(__file__))
    _PROJECT_ROOT = os.path.dirname(_SOLVER_DIR)
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "core"))
    sys.path.insert(0, _SOLVER_DIR)
    sys.path.insert(0, _PROJECT_ROOT)
    from model import Lot
    from rules import Rules
    from topology import load_topology
    from solver import solve
    from snap_gaps import snap_gaps
    from run import _merge_lot_profile

    p = argparse.ArgumentParser()
    p.add_argument("topology", help="path to a topology JSON")
    p.add_argument("--width", type=float, default=16.0)
    p.add_argument("--depth", type=float, default=11.0)
    args = p.parse_args()

    lot = Lot(width=args.width, depth=args.depth, front=2.0, rear=2.0,
              left=2.0, right=3.0)
    topo = load_topology(args.topology)
    rules = Rules()
    env = lot.envelope()
    merged = _merge_lot_profile(topo, env.w, env.h, {}, verbose=False)
    layout = solve(topo, lot, rules, time_limit_s=15.0, verbose=False, adjustments=merged)
    layout, _ = snap_gaps(layout)
    plan = architecturalize(layout, topo)
    _print_plan(plan)
