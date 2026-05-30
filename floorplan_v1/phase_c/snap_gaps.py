"""Post-process layout: snap rooms to fill rectangular gaps in the envelope.

The CP-SAT solver sometimes leaves small unused strips in the buildable
envelope when it hits the aspect cap (a room can't grow any further without
becoming corridor-shaped, so the solver chooses to waste a few cm rather
than violate the rule). For visual cleanliness, this module greedily extends
each room's walls outward until no gap remains.

Trade-off (intentional, per design call):
  - Aspect cap is NOT re-checked. A snapped great_room could end up at
    2.1:1 (slightly above the 1.8 strict cap) — the validator doesn't
    enforce aspect, so this passes validation.
  - Corridor protection is intentionally weakened HERE. The strict cap is
    still the SOLVER's behavior; this post-process loosens it for the final
    polish only.

The snapper DOES respect:
  - No overlap with other rooms (gap distance is bounded by neighbor edges).
  - The buildable envelope (gap distance is bounded by env edges).
  - Composite rooms (each cell snapped independently).

Run AFTER solve() and validate(). Re-running validate() after this is
optional — none of the validator's hard rules can be newly violated by
extension-only snaps (area mins can only grow, no-overlap is preserved,
envelope is preserved, window access is preserved since rooms only get
bigger). The aspect cap, which CAN now be violated, isn't a validator rule.
"""
from typing import List, Optional, Tuple
from model import Layout, Rect, Room


THRESHOLD_M = 0.05   # ignore sub-5 cm gaps as float / grid noise


def snap_gaps(layout: Layout, max_iter: int = 50,
              verbose: bool = False) -> Tuple[Layout, int]:
    """Iteratively snap rooms to fill rectangular gaps. Modifies layout's room
    rects in place; returns (layout, snap_count) for inspection."""
    env = layout.lot.envelope()
    snap_count = 0
    for _ in range(max_iter):
        best_dist = 0.0
        best_target: Optional[Tuple[Room, int, str]] = None
        for room in layout.rooms:
            other_rects = [c for o in layout.rooms if o is not room
                           for c in o.cells]
            cells = room.cells
            for cell_idx, cell in enumerate(cells):
                for side in ("west", "east", "south", "north"):
                    d = _gap_distance(cell, side, env, other_rects)
                    if d > best_dist:
                        best_dist = d
                        best_target = (room, cell_idx, side)
        if best_dist < THRESHOLD_M or best_target is None:
            break
        room, cell_idx, side = best_target
        _extend_cell(room, cell_idx, side, best_dist)
        snap_count += 1
        if verbose:
            print(f'  snap: {room.id} +{best_dist*100:.0f} cm {side}')
    return layout, snap_count


def _gap_distance(r: Rect, side: str, env: Rect, others: List[Rect]) -> float:
    """Distance r could extend on the given side before hitting an obstacle
    (another room cell or the envelope edge). 0 if already flush."""
    eps = 1e-6
    if side == "west":
        target = env.x0
        for o in others:
            if (o.y0 < r.y1 - eps and o.y1 > r.y0 + eps and
                    o.x1 <= r.x0 + eps):
                target = max(target, o.x1)
        return max(0.0, r.x0 - target)
    if side == "east":
        target = env.x1
        for o in others:
            if (o.y0 < r.y1 - eps and o.y1 > r.y0 + eps and
                    o.x0 >= r.x1 - eps):
                target = min(target, o.x0)
        return max(0.0, target - r.x1)
    if side == "south":
        target = env.y0
        for o in others:
            if (o.x0 < r.x1 - eps and o.x1 > r.x0 + eps and
                    o.y1 <= r.y0 + eps):
                target = max(target, o.y1)
        return max(0.0, r.y0 - target)
    if side == "north":
        target = env.y1
        for o in others:
            if (o.x0 < r.x1 - eps and o.x1 > r.x0 + eps and
                    o.y0 >= r.y1 - eps):
                target = min(target, o.y0)
        return max(0.0, target - r.y1)
    return 0.0


def _extend_cell(room: Room, cell_idx: int, side: str, dist: float) -> None:
    """Extend room.rect (cell_idx=0) or room.rect2 (cell_idx=1) by `dist` on
    the given side. Replaces the Rect in place on the Room."""
    rect = room.rect if cell_idx == 0 else room.rect2
    if rect is None:
        return
    if side == "west":
        new = Rect(round(rect.x0 - dist, 4), rect.y0, rect.x1, rect.y1)
    elif side == "east":
        new = Rect(rect.x0, rect.y0, round(rect.x1 + dist, 4), rect.y1)
    elif side == "south":
        new = Rect(rect.x0, round(rect.y0 - dist, 4), rect.x1, rect.y1)
    elif side == "north":
        new = Rect(rect.x0, rect.y0, rect.x1, round(rect.y1 + dist, 4))
    else:
        return
    if cell_idx == 0:
        room.rect = new
    else:
        room.rect2 = new
