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
# Tolerance for the threshold comparison. The CP-SAT solver outputs grid-
# quantized coords (5 cm grid), but converting back to floats can introduce
# sub-millimeter drift — e.g., (7.0 - 6.95) evaluates to 0.04999...982 in
# IEEE-754, failing `< 0.05` and preventing legitimate 5 cm gaps from being
# snapped (leaving them as visible "doubled walls" in the render).
# Subtracting this epsilon from the threshold makes gaps at exactly 5 cm
# reliably qualify for snapping.
_THRESHOLD_EPS = 1e-6


def snap_gaps(layout: Layout, max_iter: int = 50,
              verbose: bool = False,
              void_rects: Optional[List[Rect]] = None,
              matched_x_pairs: Optional[List[Tuple[str, str]]] = None,
              max_area_caps: Optional[dict] = None,
              frozen_ids: Optional[set] = None
              ) -> Tuple[Layout, int]:
    """Iteratively snap rooms to fill rectangular gaps. Modifies layout's room
    rects in place; returns (layout, snap_count) for inspection.

    `void_rects` are extra obstacles (e.g., topology building voids) that
    rooms must not extend INTO. They behave like other room cells for gap-
    computation purposes.

    `matched_x_pairs` is a list of (room_id_a, room_id_b) tuples whose widths
    must stay equal. When extending one of the matched rooms east or west,
    the snap distance is capped at min(self_gap, twin_gap) and the snap is
    applied to BOTH rooms together — so the post-snap layout preserves the
    solver's match_bedroom_widths / match_bath_widths invariants. Match is
    enforced ONLY on the x-axis (width); depth (y-axis) is unconstrained.

    `max_area_caps` is a dict {room_id: max_area_sqm} for rooms that should
    not grow past a target area post-snap. The solver enforces these at
    solve time but doesn't carry the constraint into snap_gaps; this
    parameter restores the invariant. When set, the snap distance for a
    capped room is shrunk so the resulting total area (rect + rect2) stays
    under the cap. If the room is already at or over its cap, it doesn't
    grow at all on this iteration.

    `frozen_ids` are room ids that must NOT be extended at all. Multi-storey
    v2 uses this for stair rooms: the GF flight and the 2F stairwell are
    snapped per-floor in separate passes, so growing one would silently
    break the solver's cross-floor rect-equality — and a stair's run is
    riser math, not leftover space (design decision D6).
    """
    env = layout.lot.envelope()
    voids = void_rects or []
    frozen = frozen_ids or set()
    # Build a twin lookup: room_id -> twin_room_id (x-axis only).
    twin_of: dict = {}
    for a, b in (matched_x_pairs or []):
        twin_of[a] = b
        twin_of[b] = a
    room_by_id = {r.id: r for r in layout.rooms}
    caps = max_area_caps or {}
    snap_count = 0
    for _ in range(max_iter):
        best_dist = 0.0
        best_target: Optional[Tuple[Room, int, str]] = None
        for room in layout.rooms:
            if room.id in frozen:
                continue
            cells = room.cells
            for cell_idx, cell in enumerate(cells):
                # Obstacles: every cell in the layout except the one we're
                # snapping. This includes the same room's OTHER cells (e.g.,
                # master.rect when we're snapping master.rect2) so an L-shape
                # composite can't have one of its cells grow over the other.
                obstacles = ([c for o in layout.rooms for c in o.cells
                              if c is not cell] + voids)
                for side in ("west", "east", "south", "north"):
                    d = _gap_distance(cell, side, env, obstacles)
                    # Max-area cap: shrink d so the room's TOTAL area (across
                    # all cells) stays under the cap after this extension.
                    if room.id in caps:
                        d = _shrink_for_area_cap(d, room, cell, side, caps[room.id])
                    # Master-supremacy guard: the solver enforces the PH hard
                    # rule master > standard (1 m² margin) at solve time, but
                    # unequal snap growth can erode it (observed live: br3
                    # +90 cm vs master +35 cm ended in exact equality). Cap a
                    # standard bedroom's growth at its storey's master's
                    # CURRENT area minus half the margin — master only ever
                    # grows during snapping, so the invariant survives the
                    # whole loop regardless of extension order.
                    if room.type == "bedroom_standard":
                        m = next((r for r in layout.rooms
                                  if r.type == "master_bedroom"
                                  and r.storey == room.storey), None)
                        if m is not None:
                            d = _shrink_for_area_cap(d, room, cell, side,
                                                     m.area - 0.5)
                    # If this room has a matched twin and the snap is on the
                    # x-axis (east/west), cap d to what the twin can also do.
                    if side in ("east", "west") and room.id in twin_of:
                        twin = room_by_id.get(twin_of[room.id])
                        if twin is not None:
                            twin_obs = ([c for o in layout.rooms for c in o.cells
                                         if c is not twin.rect] + voids)
                            td = _gap_distance(twin.rect, side, env, twin_obs)
                            # Twin also subject to its own area cap.
                            if twin.id in caps:
                                td = _shrink_for_area_cap(td, twin, twin.rect, side, caps[twin.id])
                            d = min(d, td)
                    if d > best_dist:
                        best_dist = d
                        best_target = (room, cell_idx, side)
        if best_dist < THRESHOLD_M - _THRESHOLD_EPS or best_target is None:
            break
        room, cell_idx, side = best_target
        _extend_cell(room, cell_idx, side, best_dist)
        snap_count += 1
        if verbose:
            print(f'  snap: {room.id} +{best_dist*100:.0f} cm {side}')
        # If matched, snap the twin by the same amount in lockstep.
        if side in ("east", "west") and room.id in twin_of:
            twin = room_by_id.get(twin_of[room.id])
            if twin is not None:
                _extend_cell(twin, 0, side, best_dist)
                snap_count += 1
                if verbose:
                    print(f'  snap: {twin.id} +{best_dist*100:.0f} cm {side} '
                          f'(matched-twin lockstep)')
    return layout, snap_count


def _shrink_for_area_cap(d: float, room: Room, cell: Rect, side: str,
                          max_area: float) -> float:
    """Reduce extension distance `d` so the room's total area (across all
    cells) doesn't exceed `max_area`. Returns the (possibly shrunk) distance.
    Returns 0 if the room is already at or over its cap."""
    if d <= 0:
        return d
    current_total = sum((c.x1-c.x0)*(c.y1-c.y0)
                        for c in (room.rect, room.rect2) if c is not None)
    remaining = max_area - current_total
    if remaining <= 0:
        return 0.0
    # Area added by extending `cell` by distance d on `side` = d * perpendicular_extent.
    if side in ("west", "east"):
        perp = cell.y1 - cell.y0
    else:
        perp = cell.x1 - cell.x0
    if perp <= 0:
        return d
    max_d = remaining / perp
    return min(d, max_d)


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


def claim_ensuite_alcove(layout, topology, verbose: bool = False,
                          max_area_caps: Optional[dict] = None) -> int:
    """Post-solve, pre-snap-gaps pass that hands the strip east of ensuite
    (within the bedroom column) to master as a rect2 — making master
    L-shaped. Applies only when the topology declares
    `ensuite_alcove_joins_master: true`.

    Geometry:
      Ensuite is in the [master, ensuite, standard] front-to-rear stack so
      it sits in the middle band between master and standard. The bedroom
      column spans x=[env.x_start, bedroom_east]; ensuite is capped at
      width 3.0 m, leaving a strip x=[ensuite.x_end, bedroom_east] at
      y=[ensuite.y_start, ensuite.y_end]. Master claims this strip as its
      rect2 so the unclaimed area gets folded into the bedroom rather than
      eaten by snap_gaps extending ensuite.

    The L-extension also touches standard's south wall along its north edge
    — that's an intentional bedroom-to-bedroom wall (a closet against it is
    the typical acoustic mitigation).

    Returns the number of alcoves claimed (0 or 1 for current topologies;
    1 only when ensuite is genuinely narrower than the bedroom column).
    """
    if not getattr(topology, "ensuite_alcove_joins_master", False):
        return 0
    master = next((r for r in layout.rooms if r.type == "master_bedroom"), None)
    ensuite = next((r for r in layout.rooms if r.type == "ensuite_bath"), None)
    if master is None or ensuite is None:
        return 0
    if master.rect2 is not None:
        # Master already has a rect2 (from a void-alcove claim). Don't clobber.
        return 0
    eps = 1e-6
    # Bedroom column east edge — defined as master's rect east edge (since
    # master is left-anchored to env.x_start and its rect spans the full
    # bedroom width at the front band).
    bedroom_east = master.rect.x1
    ensuite_east = ensuite.rect.x1
    if ensuite_east >= bedroom_east - eps:
        # Ensuite already fills the bedroom column — no alcove to claim.
        return 0
    alcove = Rect(ensuite_east, ensuite.rect.y0, bedroom_east, ensuite.rect.y1)
    if alcove.area < THRESHOLD_M:
        return 0
    # Honor master's max_area_sqm cap: if the alcove would push master over
    # its cap, shrink the alcove width so master.rect + alcove stays at cap.
    caps = max_area_caps or {}
    if master.id in caps:
        master_rect_area = (master.rect.x1 - master.rect.x0) * (master.rect.y1 - master.rect.y0)
        remaining = caps[master.id] - master_rect_area
        if remaining <= 0:
            # master.rect is already at or over the cap — no room for an alcove
            return 0
        alcove_height = alcove.y1 - alcove.y0
        if alcove_height > 0:
            max_alcove_width = remaining / alcove_height
            current_alcove_width = alcove.x1 - alcove.x0
            if current_alcove_width > max_alcove_width:
                # Shrink alcove: anchor east edge at bedroom_east, pull west edge.
                new_x0 = bedroom_east - max_alcove_width
                alcove = Rect(new_x0, alcove.y0, bedroom_east, alcove.y1)
                if alcove.area < THRESHOLD_M:
                    return 0
    master.rect2 = alcove
    if verbose:
        print(f"  ensuite alcove: master +{alcove.area:.2f} sqm "
              f"(x={alcove.x0:.2f}-{alcove.x1:.2f} y={alcove.y0:.2f}-{alcove.y1:.2f})")
    return 1


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


# ---------------------------------------------------------------------------
# Dead-strip claimer (multi-storey v2)
# ---------------------------------------------------------------------------

# Which room types make the best owner for an unowned interior strip, best
# first. Habitable public rooms benefit most (they're usually below their
# preferred area); halls are natural circulation spill; kitchens turn the
# strip into a pantry nook (the reference spec's under-stair storage).
_STRIP_CLAIM_PRIORITY = {
    "living_room": 0, "great_room": 0,
    "hallway": 1,
    "dining_room": 2,
    "master_bedroom": 3, "bedroom_standard": 3,
    "kitchen": 4,
}


def claim_dead_strips(layout, void_rects: Optional[List[Rect]] = None,
                      verbose: bool = False) -> int:
    """Post-snap pass that finds UNOWNED rectangular interior strips and
    hands each to an adjacent room as its rect2 cell (making that room
    L-shaped). Complements snap_gaps, which can only extend a room's FULL
    edge: a strip flanking part of a stair column (shorter than every
    neighbor's edge) is unreachable by edge-extension but perfectly
    claimable as an alcove.

    Built for the multi-storey pipeline (dead slivers beside the stair
    column — see MULTISTOREY_V2_DESIGN.md known gaps); deliberately NOT
    wired into the single-storey path, whose 60+ test baselines are stable
    without it.

    Only strictly rectangular uncovered regions are claimed (an L-shaped
    hole is left alone); the claimant's cell must fully contain one side of
    the strip so the union is a clean L. Rooms typed 'stairs' never claim
    (the flight is riser math); rooms that already have a rect2 are skipped
    (one alcove per room). Returns the number of strips claimed.
    """
    env = layout.lot.envelope()
    eps = 1e-6
    obstacles = [c for r in layout.rooms for c in r.cells] + list(void_rects or [])
    xs = sorted({env.x0, env.x1} | {v for c in obstacles for v in (c.x0, c.x1)
                                    if env.x0 - eps < v < env.x1 + eps})
    ys = sorted({env.y0, env.y1} | {v for c in obstacles for v in (c.y0, c.y1)
                                    if env.y0 - eps < v < env.y1 + eps})
    nx, ny = len(xs) - 1, len(ys) - 1

    def covered(i, j):
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        return any(c.x0 - eps < cx < c.x1 + eps and
                   c.y0 - eps < cy < c.y1 + eps for c in obstacles)

    free = [[not covered(i, j) for j in range(ny)] for i in range(nx)]
    seen = [[False] * ny for _ in range(nx)]
    claimed = 0
    for i0 in range(nx):
        for j0 in range(ny):
            if not free[i0][j0] or seen[i0][j0]:
                continue
            # Flood-fill the uncovered component.
            comp, stack = [], [(i0, j0)]
            seen[i0][j0] = True
            while stack:
                i, j = stack.pop()
                comp.append((i, j))
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a, b = i + di, j + dj
                    if 0 <= a < nx and 0 <= b < ny and free[a][b] \
                            and not seen[a][b]:
                        seen[a][b] = True
                        stack.append((a, b))
            # Decompose the component into rectangles. A rectangular hole
            # yields itself in one piece; an L/T-shaped one (e.g. the region
            # wrapping a stair column's corner) is split greedily: take the
            # topmost-leftmost remaining cell, extend right along its row,
            # then extend that column-span downward while every column stays
            # present. Pieces are claimed largest-first so the most valuable
            # strip gets the best-ranked neighbor (a room can hold only one
            # alcove — rect2 — so order matters).
            remaining = set(comp)
            pieces = []
            while remaining:
                i, j = min(remaining, key=lambda c: (ys[c[1]], xs[c[0]]))
                i_hi = i
                while (i_hi + 1, j) in remaining:
                    i_hi += 1
                j_hi = j
                while all((k, j_hi + 1) in remaining for k in range(i, i_hi + 1)):
                    j_hi += 1
                for k in range(i, i_hi + 1):
                    for l in range(j, j_hi + 1):
                        remaining.discard((k, l))
                pieces.append(Rect(xs[i], ys[j], xs[i_hi + 1], ys[j_hi + 1]))
            pieces.sort(key=lambda r: -r.area)
            for strip in pieces:
                if strip.area < THRESHOLD_M:
                    continue
                x0, y0, x1, y1 = strip.x0, strip.y0, strip.x1, strip.y1
                # Candidate claimants: a room cell that abuts one full side
                # of the strip (edge coincident and spanning the strip's side).
                best, best_rank = None, None
                for room in layout.rooms:
                    if room.type == "stairs" or room.rect2 is not None:
                        continue
                    rank = _STRIP_CLAIM_PRIORITY.get(room.type)
                    if rank is None:
                        continue
                    # Master-supremacy guard: the solver enforces the PH hard
                    # rule master > standard at solve time; a post-solve claim
                    # must not silently break it. A standard bedroom may only
                    # take a strip if its resulting total stays below its
                    # storey's master (observed live: an 11x11 squarish 3BR
                    # solve handed br3 a 5.2 m2 alcove, outgrowing master).
                    if room.type == "bedroom_standard":
                        m = next((r for r in layout.rooms
                                  if r.type == "master_bedroom"
                                  and r.storey == room.storey), None)
                        if m is not None and room.area + strip.area >= m.area:
                            continue
                    c = room.rect
                    abuts = (
                        (abs(c.x1 - x0) < eps or abs(c.x0 - x1) < eps)
                        and c.y0 < y0 + eps and c.y1 > y1 - eps
                    ) or (
                        (abs(c.y1 - y0) < eps or abs(c.y0 - y1) < eps)
                        and c.x0 < x0 + eps and c.x1 > x1 - eps
                    )
                    if abuts and (best_rank is None or rank < best_rank):
                        best, best_rank = room, rank
                if best is None:
                    continue
                best.rect2 = strip
                obstacles.append(strip)
                claimed += 1
                if verbose:
                    print(f"  alcove: {best.id} +{strip.area:.2f} sqm "
                          f"(dead strip x={x0:.2f}-{x1:.2f} y={y0:.2f}-{y1:.2f})")
    return claimed
