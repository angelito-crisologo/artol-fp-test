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
              verbose: bool = False,
              void_rects: Optional[List[Rect]] = None) -> Tuple[Layout, int]:
    """Iteratively snap rooms to fill rectangular gaps. Modifies layout's room
    rects in place; returns (layout, snap_count) for inspection.

    `void_rects` are extra obstacles (e.g., topology building voids) that
    rooms must not extend INTO. They behave like other room cells for gap-
    computation purposes."""
    env = layout.lot.envelope()
    voids = void_rects or []
    snap_count = 0
    for _ in range(max_iter):
        best_dist = 0.0
        best_target: Optional[Tuple[Room, int, str]] = None
        for room in layout.rooms:
            other_rects = [c for o in layout.rooms if o is not room
                           for c in o.cells]
            obstacles = other_rects + voids
            cells = room.cells
            for cell_idx, cell in enumerate(cells):
                for side in ("west", "east", "south", "north"):
                    d = _gap_distance(cell, side, env, obstacles)
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


def claim_void_alcoves(layout, void_rects: Optional[List[Rect]] = None,
                       verbose: bool = False) -> int:
    """Post-snap pass that finds 'alcoves' — rectangular dead space adjacent
    to a building void's INTERIOR face — and assigns each to the room that
    shares the void's other interior face, as a second cell (rect2). Turns
    the room into an L-shaped composite.

    Background:
      A building_void (e.g. a carport_cut at front_right) carves a rectangle
      out of the buildable envelope. After rooms are placed and snapped, the
      strip just PAST the void's interior face often stays unclaimed — it's
      inside the envelope, outside any room, and outside any void. Without
      this step, that strip renders as exterior space INSIDE the building
      footprint (a wall not flush with the void's edge).

      For a front_right void:
        - The void's lot-facing edges are SOUTH (y=void.y0) and EAST (x=void.x1).
        - The void's interior-facing edges are NORTH (y=void.y1) and WEST (x=void.x0).
        - The "north alcove" is the rect at [void.x0, void.x1] x [void.y1, next_obstacle_y].
        - Whichever room owns the void's WEST interior face (the room with east
          edge at x=void.x0) claims the north alcove as its rect2.

    Returns the number of alcoves claimed (0 if none). Safe no-op when there
    are no voids or no rooms qualify.
    """
    if not void_rects:
        return 0
    env = layout.lot.envelope()
    claims = 0
    eps = 1e-6
    for vrect in void_rects:
        # Only handle voids that DON'T span the whole envelope on either axis.
        if vrect.x0 <= env.x0 + eps and vrect.x1 >= env.x1 - eps:
            continue
        if vrect.y0 <= env.y0 + eps and vrect.y1 >= env.y1 - eps:
            continue

        # Figure out which void faces are interior (face the building rooms)
        # vs lot-facing (touch the envelope boundary).
        west_interior  = vrect.x0 > env.x0 + eps
        east_interior  = vrect.x1 < env.x1 - eps
        south_interior = vrect.y0 > env.y0 + eps
        north_interior = vrect.y1 < env.y1 - eps

        # For each interior face, compute the alcove rectangle (the strip
        # past the void's interior face, bounded by the nearest obstacle).
        # Each alcove is assigned to the room whose own interior face shares
        # the OTHER interior axis of the void.
        candidates = []
        if north_interior:
            # alcove past the void's north face: between y=vrect.y1 and the
            # closest obstacle to the north, within the void's x range
            ay0 = vrect.y1
            ay1 = env.y1
            for r in layout.rooms:
                for c in r.cells:
                    if c.x1 > vrect.x0 + eps and c.x0 < vrect.x1 - eps \
                       and c.y0 >= vrect.y1 - eps:
                        ay1 = min(ay1, c.y0)
            alcove = Rect(vrect.x0, ay0, vrect.x1, ay1)
            if alcove.area > THRESHOLD_M:
                # The claimant: the room that owns the void's WEST face (if
                # interior) or EAST face. For a front_right void with west
                # interior, that's the room with east edge at x=vrect.x0.
                claimant = _room_with_edge(layout.rooms, "east", vrect.x0,
                                           vrect.y0, vrect.y1)
                if claimant is None and east_interior:
                    claimant = _room_with_edge(layout.rooms, "west", vrect.x1,
                                               vrect.y0, vrect.y1)
                if claimant is not None:
                    candidates.append((claimant, alcove, "north"))
        if south_interior:
            ay1 = vrect.y0
            ay0 = env.y0
            for r in layout.rooms:
                for c in r.cells:
                    if c.x1 > vrect.x0 + eps and c.x0 < vrect.x1 - eps \
                       and c.y1 <= vrect.y0 + eps:
                        ay0 = max(ay0, c.y1)
            alcove = Rect(vrect.x0, ay0, vrect.x1, ay1)
            if alcove.area > THRESHOLD_M:
                claimant = _room_with_edge(layout.rooms, "east", vrect.x0,
                                           vrect.y0, vrect.y1)
                if claimant is None and east_interior:
                    claimant = _room_with_edge(layout.rooms, "west", vrect.x1,
                                               vrect.y0, vrect.y1)
                if claimant is not None:
                    candidates.append((claimant, alcove, "south"))
        if west_interior:
            # alcove past the void's west face: between the nearest obstacle
            # to the west and x=vrect.x0, spanning the void's y range
            ax1 = vrect.x0
            ax0 = env.x0
            for r in layout.rooms:
                for c in r.cells:
                    if c.y1 > vrect.y0 + eps and c.y0 < vrect.y1 - eps \
                       and c.x1 <= vrect.x0 + eps:
                        ax0 = max(ax0, c.x1)
            alcove = Rect(ax0, vrect.y0, ax1, vrect.y1)
            if alcove.area > THRESHOLD_M:
                # The claimant: the room whose EAST edge sits at the alcove's
                # west edge (i.e., the room immediately west of the gap).
                claimant = _room_with_edge(layout.rooms, "east", ax0,
                                           vrect.y0, vrect.y1)
                if claimant is not None:
                    candidates.append((claimant, alcove, "west"))
        if east_interior:
            ax0 = vrect.x1
            ax1 = env.x1
            for r in layout.rooms:
                for c in r.cells:
                    if c.y1 > vrect.y0 + eps and c.y0 < vrect.y1 - eps \
                       and c.x0 >= vrect.x1 - eps:
                        ax1 = min(ax1, c.x0)
            alcove = Rect(ax0, vrect.y0, ax1, vrect.y1)
            if alcove.area > THRESHOLD_M:
                claimant = _room_with_edge(layout.rooms, "west", ax1,
                                           vrect.y0, vrect.y1)
                if claimant is not None:
                    candidates.append((claimant, alcove, "east"))

        for room, alcove, where in candidates:
            if room.rect2 is not None:
                continue  # don't clobber existing composite
            room.rect2 = alcove
            claims += 1
            if verbose:
                print(f"  alcove: {room.id} +{alcove.area:.2f} sqm "
                      f"({where} of void, x={alcove.x0:.2f}-{alcove.x1:.2f} "
                      f"y={alcove.y0:.2f}-{alcove.y1:.2f})")
    return claims


def _room_with_edge(rooms, side: str, x_or_y: float,
                    range_lo: float, range_hi: float):
    """Find the first room with a cell edge on the given side at the given
    coordinate, where the cell's perpendicular range covers [range_lo, range_hi]
    (or any nontrivial overlap). Returns the Room or None.
    """
    eps = 1e-6
    best = None
    best_overlap = 0.0
    for room in rooms:
        for c in room.cells:
            if side == "east" and abs(c.x1 - x_or_y) < eps:
                lo = max(c.y0, range_lo)
                hi = min(c.y1, range_hi)
            elif side == "west" and abs(c.x0 - x_or_y) < eps:
                lo = max(c.y0, range_lo)
                hi = min(c.y1, range_hi)
            elif side == "north" and abs(c.y1 - x_or_y) < eps:
                lo = max(c.x0, range_lo)
                hi = min(c.x1, range_hi)
            elif side == "south" and abs(c.y0 - x_or_y) < eps:
                lo = max(c.x0, range_lo)
                hi = min(c.x1, range_hi)
            else:
                continue
            overlap = hi - lo
            if overlap > best_overlap + eps:
                best_overlap = overlap
                best = room
    return best
