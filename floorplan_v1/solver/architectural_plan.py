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
from dataclasses import dataclass, field
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
                  "bedroom_to_bedroom_wall"}

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


def _door_for_adjacency(adj, layout: Layout) -> Optional[Door]:
    """Emit a Door (or None) for a single topology adjacency."""
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
    # Find the shared edge between cell A of each room. (Composite cells
    # ignored for D.1 — they're not present in current topologies.)
    edge = _shared_edge(room_a.rect, room_b.rect)
    if edge is None:
        return None
    side_a, coord, start, end = edge
    shared_len = end - start
    clear = DOOR_CLEAR_WIDTH_M.get(adj.kind, 0.80)
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
    wall_origin = _wall_origin(room_a.rect, side_a)
    wall_end = wall_origin + _wall_length(room_a.rect, side_a)
    dist_low_to_corner  = start - wall_origin       # how far the shared edge's
    dist_high_to_corner = wall_end - end            # ends are from room_a's
                                                    # perpendicular walls
    low_real, high_real = _perpendicular_walls_real(
        room_a, side_a, env, layout.rooms)
    # Hinge selection priority:
    #   1. Exactly one corner has a real perpendicular wall — use that one.
    #   2. Both real (or both fake) — fall back to nearer corner; ties LOW.
    if low_real and not high_real:
        prefer = "low"
    elif high_real and not low_real:
        prefer = "high"
    else:
        prefer = "low" if dist_low_to_corner <= dist_high_to_corner else "high"
    if prefer == "low":
        hinge_at = "low"
        if dist_low_to_corner < 0.01:
            # Shared edge starts AT room_a's wall corner: push the door
            # 150 mm in from that corner.
            position_m = CORNER_OFFSET_M
        else:
            # Shared edge starts mid-wall — hinge at the LOW end of the edge.
            position_m = start - wall_origin
    else:
        hinge_at = "high"
        if dist_high_to_corner < 0.01:
            # Shared edge ends AT room_a's wall corner: push door 150 mm
            # back from that corner.
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
    return Door(
        room_a=adj.a, room_b=adj.b, wall=side_a,
        position_m=round(position_m, 3),
        clear_width_m=round(clear, 3),
        swing_into=_swing_into(room_a, room_b, adj.kind),
        kind=adj.kind,
        hinge_at=hinge_at,
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
                        env: Rect) -> Optional[Door]:
    """If the topology declares a dirty_kitchen setback element, emit a door
    from the room it sits behind (typically the kitchen) to the exterior on
    that room's rear wall. PH practice always has a kitchen-to-dirty-kitchen
    pass-through; this generates it automatically rather than requiring every
    topology to declare it as an adjacency."""
    dk = next((sb for sb in topology.setback_elements
               if sb.type == "dirty_kitchen"), None)
    if dk is None:
        return None
    # Which room sits in front of the dirty kitchen? Default to 'kitchen'
    # since that's the only room a dirty kitchen ever sits behind in PH
    # practice.
    behind_id = dk.behind or "kitchen"
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


def _front_door(topology: Topology, layout: Layout, env: Rect) -> Optional[Door]:
    """The entry-host room gets a front door on whichever exterior wall faces
    the street (south by convention, falling back to any exterior wall)."""
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
    # Front-door placement: centered ONLY when there's enough room for the
    # door PLUS a centered window on either side (i.e., wall_len wide enough
    # that a habitable-style 0.9 m window fits after subtracting door +
    # clearances). On narrower facades (e.g., 2.4–2.6 m great_room in a
    # firewall-compact layout), shove the front door into a corner so the
    # other half of the wall is free for the room's 10% window.
    space_for_centered = clear + 2 * (0.9 + 0.30) + 0.20  # door + window each side
    if wall_len >= space_for_centered:
        pos = (wall_len - clear) / 2.0
        hinge_at = "low"
    else:
        pos = CORNER_OFFSET_M
        hinge_at = "low"
    return Door(
        room_a="exterior", room_b=entry_id, wall=chosen,
        position_m=round(pos, 3),
        clear_width_m=round(clear, 3),
        swing_into=entry_id,
        kind="main_door",
        hinge_at=hinge_at,
    )


# ----------------------------------------------------------------------------
# Public entrypoint
# ----------------------------------------------------------------------------

def architecturalize(layout: Layout, topology: Topology) -> ArchPlan:
    """Project the topology onto the (snapped) layout to produce doors,
    windows, and open-plan-edge metadata."""
    plan = ArchPlan(layout=layout, topology=topology)
    env = layout.lot.envelope()

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

    # Pass 1: doors and open-plan edges from topology adjacencies
    for adj in topology.adjacencies:
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
        door = _door_for_adjacency(adj, layout)
        if door:
            plan.doors.append(door)
            _record_interior_door(door)

    # Pass 2: front door — only one side is a real room.
    fd = _front_door(topology, layout, env)
    if fd:
        plan.doors.append(fd)
        _record_door(fd.room_b, fd.wall,
                     fd.position_m, fd.position_m + fd.clear_width_m)

    # Pass 2b: kitchen-to-dirty-kitchen back door (also exterior on the room side).
    dk_door = _dirty_kitchen_door(topology, layout, env)
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
