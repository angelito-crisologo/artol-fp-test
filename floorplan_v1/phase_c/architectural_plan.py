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


# Door clear-width defaults by adjacency kind. Door panel width (not the wall
# slot — wall slot has frame on each side, ~10 cm total).
DOOR_CLEAR_WIDTH_M = {
    "main_door":          0.85,   # front door, 90 mm clear behind a 95 mm leaf
    "bedroom_door":       0.80,
    "bedroom_to_public":  0.80,
    "bath_door":          0.70,
    "ensuite_door":       0.70,
}

# Adjacency kinds that DON'T get a door:
#   open_plan: emit an OpenPlanEdge (wall removed when rendered)
#   wet_core:  solid plumbing wall, no door
_NO_DOOR_KINDS = {"open_plan", "wet_core"}

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
    """A shared wall that should NOT be drawn — the two rooms are open-plan."""
    room_a: str
    room_b: str
    wall: str               # which side of room_a is open to room_b


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
    # Center the door on the shared segment. position_m is from the wall's NW
    # origin (room_a's x0 for N/S, y0 for E/W) to the near edge of the door.
    mid = (start + end) / 2.0
    near = mid - clear / 2.0
    position_m = near - _wall_origin(room_a.rect, side_a)
    return Door(
        room_a=adj.a, room_b=adj.b, wall=side_a,
        position_m=round(position_m, 3),
        clear_width_m=round(clear, 3),
        swing_into=_swing_into(room_a, room_b, adj.kind),
        kind=adj.kind,
    )


def _open_plan_edge_for_adjacency(adj, layout: Layout) -> Optional[OpenPlanEdge]:
    """Build an OpenPlanEdge for `adj`. Caller is responsible for deciding
    whether this adjacency is actually open-plan (see _effective_kind)."""
    room_a = next((r for r in layout.rooms if r.id == adj.a), None)
    room_b = next((r for r in layout.rooms if r.id == adj.b), None)
    if room_a is None or room_b is None:
        return None
    edge = _shared_edge(room_a.rect, room_b.rect)
    if edge is None:
        return None
    return OpenPlanEdge(room_a=adj.a, room_b=adj.b, wall=edge[0])


def _windows_for_room(room: Room, env: Rect, bath: bool, exclude_walls: set) -> List[Window]:
    """One window on every exterior wall of `room` (skipping any side already
    consumed by a door — that's `exclude_walls`)."""
    out: List[Window] = []
    for side in SIDES:
        if side in exclude_walls:
            continue
        if not _touches_exterior(room.rect, env, side):
            continue
        wall_len = _wall_length(room.rect, side)
        if bath:
            w = max(0.6, min(0.9, wall_len * 0.4))
        else:
            w = max(0.9, min(2.4, wall_len * 0.55))
        if wall_len < w + 0.20:                      # not enough room — skip
            continue
        pos = (wall_len - w) / 2.0                   # centered
        out.append(Window(
            room=room.id, wall=side,
            position_m=round(pos, 3),
            width_m=round(w, 3),
        ))
    return out


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
    # For the front door, position toward the corner closer to the carport-
    # neutral side. Simplest: centered.
    pos = (wall_len - clear) / 2.0
    return Door(
        room_a="exterior", room_b=entry_id, wall=chosen,
        position_m=round(pos, 3),
        clear_width_m=round(clear, 3),
        swing_into=entry_id,
        kind="main_door",
    )


# ----------------------------------------------------------------------------
# Public entrypoint
# ----------------------------------------------------------------------------

def architecturalize(layout: Layout, topology: Topology) -> ArchPlan:
    """Project the topology onto the (snapped) layout to produce doors,
    windows, and open-plan-edge metadata."""
    plan = ArchPlan(layout=layout, topology=topology)
    env = layout.lot.envelope()

    # Track which walls of each room have a door — windows on those same walls
    # are suppressed (we don't want a door and window stacked).
    door_walls_by_room: dict = {}

    # Pass 1: doors and open-plan edges from topology adjacencies
    rooms_by_id = {r.id: r for r in layout.rooms}
    for adj in topology.adjacencies:
        ra, rb = rooms_by_id.get(adj.a), rooms_by_id.get(adj.b)
        if ra is None or rb is None:
            continue
        kind = _effective_kind(adj, ra.type, rb.type)
        if kind == "open_plan":
            ope = _open_plan_edge_for_adjacency(adj, layout)
            if ope:
                plan.open_plan_edges.append(ope)
            continue
        if kind == "wet_core":
            continue
        door = _door_for_adjacency(adj, layout)
        if door:
            plan.doors.append(door)
            door_walls_by_room.setdefault(door.room_a, set()).add(door.wall)
            # Record on room_b too — adjacency is symmetric, but the wall key
            # is relative to room_a so on room_b's side it's the opposite side.
            door_walls_by_room.setdefault(door.room_b, set()).add(_opposite(door.wall))

    # Pass 2: front door
    fd = _front_door(topology, layout, env)
    if fd:
        plan.doors.append(fd)
        # The entry room's exterior wall is now consumed by the front door.
        door_walls_by_room.setdefault(fd.room_b, set()).add(fd.wall)

    # Pass 3: windows for habitable + bath rooms on remaining exterior walls
    for r in layout.rooms:
        if r.type not in HABITABLE and r.type not in BATH_TYPES:
            continue
        bath = r.type in BATH_TYPES
        used = door_walls_by_room.get(r.id, set())
        plan.windows.extend(_windows_for_room(r, env, bath, used))

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
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from model import Lot
    from rules import Rules
    from topology import load_topology
    from solver import solve
    from snap_gaps import snap_gaps
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "phase_c3"))
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
