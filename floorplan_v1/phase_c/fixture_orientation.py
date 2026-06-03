"""Phase E.1 — lightweight 'wall function' assignment per room.

The orientation module assigns each room's walls a function (head, sink,
wet, shower, etc.) WITHOUT placing actual furniture rectangles. This is
enough to refine door + window placement to match PH practice:

  - Kitchen window goes over the SINK WALL (developer-typical: window over
    the sink so dish-washing has natural light).
  - Bedroom window does NOT go on the HEAD WALL (the wall the bed sits
    against, so the bed isn't blocking the window).
  - Bath window does NOT go on the WET WALL (the toilet/lavatory side) or
    the SHOWER WALL (water + cold-bridge issues).

Derivation is heuristic — when there's no clear winner the field stays
None and downstream code falls back to its default rule.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from model import Rect, Room

SIDES = ("N", "S", "E", "W")
_OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
_PERPENDICULAR = {"N": ("E", "W"), "S": ("E", "W"),
                  "E": ("N", "S"), "W": ("N", "S")}


@dataclass
class RoomOrientation:
    """Per-room wall-function assignment. Each field names a compass side
    (N/S/E/W) of the room, or stays None when no preference is determined."""
    head_wall:   Optional[str] = None   # bedroom — wall the bed sits against
    sink_wall:   Optional[str] = None   # kitchen — wall behind the sink/counter
    work_wall:   Optional[str] = None   # kitchen — perpendicular counter run
    wet_wall:    Optional[str] = None   # bath — toilet + lavatory back wall
    shower_wall: Optional[str] = None   # bath — shower stall wall


_BEDROOM_TYPES = {"master_bedroom", "bedroom_standard", "maids_room"}
_BATH_TYPES = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room"}
_KITCHEN_TYPES = {"kitchen"}
_WET_NEIGHBOR_TYPES = _BATH_TYPES | _KITCHEN_TYPES   # plumbing-economy share


def _touches_exterior(rect: Rect, env: Rect, side: str, eps: float = 1e-3) -> bool:
    if side == "N": return abs(rect.y1 - env.y1) <= eps
    if side == "S": return abs(rect.y0 - env.y0) <= eps
    if side == "E": return abs(rect.x1 - env.x1) <= eps
    if side == "W": return abs(rect.x0 - env.x0) <= eps
    return False


def _wall_length(rect: Rect, side: str) -> float:
    if side in ("N", "S"):
        return rect.x1 - rect.x0
    return rect.y1 - rect.y0


def _shared_side(room_a: Room, room_b: Room, eps: float = 1e-3) -> Optional[str]:
    """If `room_a` and `room_b` share a wall, return the side of room_a that
    abuts room_b (N/S/E/W). Returns None if they don't share a wall."""
    a, b = room_a.rect, room_b.rect
    if abs(a.x1 - b.x0) <= eps and min(a.y1, b.y1) - max(a.y0, b.y0) > eps:
        return "E"
    if abs(a.x0 - b.x1) <= eps and min(a.y1, b.y1) - max(a.y0, b.y0) > eps:
        return "W"
    if abs(a.y1 - b.y0) <= eps and min(a.x1, b.x1) - max(a.x0, b.x0) > eps:
        return "N"
    if abs(a.y0 - b.y1) <= eps and min(a.x1, b.x1) - max(a.x0, b.x0) > eps:
        return "S"
    return None


def _derive_kitchen(room: Room, env: Rect, all_rooms: List[Room],
                     door_walls: set) -> RoomOrientation:
    """Kitchen orientation: sink_wall = longest free exterior wall (the
    over-sink window goes here per PH developer practice). work_wall is
    perpendicular to sink_wall and points toward the longest interior run
    where the stove + counter L can sit."""
    ori = RoomOrientation()
    # 1. Sink wall: prefer the longest exterior wall NOT consumed by a door.
    candidates: List[tuple] = []
    for side in SIDES:
        if not _touches_exterior(room.rect, env, side):
            continue
        wlen = _wall_length(room.rect, side)
        door_penalty = 1.5 if side in door_walls else 0.0
        candidates.append((wlen - door_penalty, side, wlen))
    if candidates:
        candidates.sort(reverse=True)
        ori.sink_wall = candidates[0][1]
    # 2. Work wall: perpendicular to sink, prefer the longer of the two
    # options. Doesn't have to be exterior.
    if ori.sink_wall:
        perp_sides = _PERPENDICULAR[ori.sink_wall]
        perp_lengths = [(_wall_length(room.rect, s), s) for s in perp_sides]
        perp_lengths.sort(reverse=True)
        ori.work_wall = perp_lengths[0][1]
    return ori


def _derive_bath(room: Room, env: Rect, all_rooms: List[Room],
                  door_walls: set) -> RoomOrientation:
    """Bath orientation: wet_wall = wall shared with another wet room
    (plumbing economy). Falls back to the wall opposite the door. shower
    is perpendicular to wet, on a non-exterior wall when possible."""
    ori = RoomOrientation()
    # 1. Wet wall — share plumbing with another wet room.
    for other in all_rooms:
        if other.id == room.id or other.type not in _WET_NEIGHBOR_TYPES:
            continue
        shared = _shared_side(room, other)
        if shared:
            ori.wet_wall = shared
            break
    # 2. Fallback wet wall: wall opposite the bath door (developer default:
    # toilet faces the door).
    if not ori.wet_wall and door_walls:
        door_side = next(iter(door_walls))
        ori.wet_wall = _OPPOSITE.get(door_side)
    # 3. Shower wall: perpendicular to wet_wall, NOT exterior when possible.
    if ori.wet_wall:
        perp_sides = list(_PERPENDICULAR[ori.wet_wall])
        # Prefer interior perpendicular sides
        scored = []
        for s in perp_sides:
            is_ext = _touches_exterior(room.rect, env, s)
            wlen = _wall_length(room.rect, s)
            score = wlen + (-2.0 if is_ext else 0.0)
            scored.append((score, s))
        scored.sort(reverse=True)
        ori.shower_wall = scored[0][1]
    return ori


def _derive_bedroom(room: Room, env: Rect, all_rooms: List[Room],
                     door_walls: set) -> RoomOrientation:
    """Bedroom orientation: head_wall = an interior wall (so the bed isn't
    blocking a window) opposite the door when possible. Avoid exterior
    walls — those are for the window."""
    ori = RoomOrientation()
    # Score each side: prefer interior, then opposite-to-door, then longer.
    scored = []
    door_side = next(iter(door_walls)) if door_walls else None
    for side in SIDES:
        if _wall_length(room.rect, side) < 1.0:
            continue
        is_ext = _touches_exterior(room.rect, env, side)
        is_door = side in door_walls
        is_opposite_door = door_side and side == _OPPOSITE.get(door_side)
        score = 0.0
        if is_ext:        score -= 3.0   # prefer interior for headboard
        if is_door:       score -= 5.0   # never put head wall on door wall
        if is_opposite_door: score += 2.0
        score += _wall_length(room.rect, side) * 0.1
        scored.append((score, side))
    if scored:
        scored.sort(reverse=True)
        ori.head_wall = scored[0][1]
    return ori


def derive_orientations(layout, env, door_walls_by_room: Dict[str, set]
                         ) -> Dict[str, RoomOrientation]:
    """Compute RoomOrientation for every room in the layout. Uses door
    placement (door_walls_by_room) to inform which walls already have
    doors and which sides are 'opposite-the-door'. Topology-level overrides
    are not yet honored — to be added when topology JSON gains an
    `orientation` block per room."""
    out: Dict[str, RoomOrientation] = {}
    for r in layout.rooms:
        dw = door_walls_by_room.get(r.id, set())
        if r.type in _KITCHEN_TYPES:
            out[r.id] = _derive_kitchen(r, env, layout.rooms, dw)
        elif r.type in _BATH_TYPES:
            out[r.id] = _derive_bath(r, env, layout.rooms, dw)
        elif r.type in _BEDROOM_TYPES:
            out[r.id] = _derive_bedroom(r, env, layout.rooms, dw)
        else:
            out[r.id] = RoomOrientation()  # LDK rooms get no orientation hint
    return out
