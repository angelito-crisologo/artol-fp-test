"""SVG renderer + HTML gallery for generated layouts.

Front (street) is drawn at the BOTTOM. Rooms are coloured by zone; uncovered
setback elements are drawn dashed. Dimensions and areas are labelled.

Two top-level entry points:
  - layout_to_svg(layout)         — raw layout (filled rooms + ruler only)
  - archplan_to_svg(plan)         — adds doors + windows from an ArchPlan
"""
import html
import math
from typing import List, Optional
from model import Layout, Rect

SCALE = 42          # px per metre
MARGIN = 46         # px

ZONE_FILL = {
    "public": "#cfe2f3",
    "private": "#d9ead3",
    "service": "#fce5cd",
    "circulation": "#efefef",
}
LABELS = {
    "bedroom_standard": "BEDROOM",
    "master_bedroom": "MASTER BR",
    "ensuite_bath": "ENSUITE",
    "common_bath": "COMMON T&B",
    "bath_toilet": "WC",
    "powder_room": "WC",
    "living_room": "LIVING",
    "dining_room": "DINING",
    "kitchen": "KITCHEN",
    "great_room": "GREAT ROOM",
    "hallway": "HALL",
    "carport": "CARPORT",
    "dirty_kitchen": "DIRTY KITCHEN",
    "service_area": "SERVICE",
}


def _fill(room) -> str:
    if room.type in ("common_bath", "ensuite_bath", "bath_toilet", "powder_room"):
        return "#ead1dc"
    if room.zone == "circulation":
        return ZONE_FILL["circulation"]
    if not room.covered:
        return "#f2f2f2"
    return ZONE_FILL.get(room.zone, "#eeeeee")


def _y(lot, my):
    """model y (front=0) -> svg y, front at bottom."""
    return MARGIN + (lot.depth - my) * SCALE


def _rect_svg(lot, rect: Rect, fill, dashed=False, label="", sub=""):
    px = MARGIN + rect.x0 * SCALE
    py = _y(lot, rect.y1)            # top edge = larger y
    w = rect.w * SCALE
    h = rect.h * SCALE
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts = [f'<rect x="{px:.1f}" y="{py:.1f}" width="{w:.1f}" height="{h:.1f}" '
             f'fill="{fill}" stroke="#333" stroke-width="1.5"{dash}/>']
    cx = px + w / 2
    cy = py + h / 2
    if label:
        parts.append(f'<text x="{cx:.1f}" y="{cy-6:.1f}" text-anchor="middle" '
                     f'font-family="Arial" font-size="12" font-weight="bold" fill="#222">{html.escape(label)}</text>')
    if sub:
        parts.append(f'<text x="{cx:.1f}" y="{cy+10:.1f}" text-anchor="middle" '
                     f'font-family="Arial" font-size="10" fill="#555">{html.escape(sub)}</text>')
    return "".join(parts)


def _ruler_svg(lot) -> str:
    """Tick marks at 0.5 m intervals on all four sides of the lot, with metre
    labels at every 1 m. Minor (half-metre) ticks are short, major (metre)
    ticks are longer and carry the number. Ticks sit OUTSIDE the lot rectangle
    so they don't visually overlap rooms."""
    parts = []
    TICK_MINOR = 4      # px — half-metre ticks
    TICK_MAJOR = 8      # px — metre ticks
    LABEL_OFF  = 10     # px — label distance from lot edge
    STROKE = "#888"
    LABEL_FILL = "#666"
    FONT = 'font-family="Arial" font-size="9"'

    # Compute lot edges in svg coordinates
    L = MARGIN                                  # left edge x
    R = MARGIN + lot.width  * SCALE             # right edge x
    T = MARGIN                                  # top edge y (rear of lot)
    B = MARGIN + lot.depth * SCALE              # bottom edge y (front of lot)

    # Number of 0.5 m steps along each axis (round to handle float lots).
    n_x = int(round(lot.width  * 2))            # half-metre steps wide
    n_y = int(round(lot.depth * 2))             # half-metre steps deep

    for i in range(n_x + 1):
        x = L + (i * 0.5) * SCALE
        major = (i % 2 == 0)
        tlen = TICK_MAJOR if major else TICK_MINOR
        # top edge ticks (pointing up)
        parts.append(f'<line x1="{x:.1f}" y1="{T:.1f}" x2="{x:.1f}" y2="{T-tlen:.1f}" '
                     f'stroke="{STROKE}" stroke-width="1"/>')
        # bottom edge ticks (pointing down)
        parts.append(f'<line x1="{x:.1f}" y1="{B:.1f}" x2="{x:.1f}" y2="{B+tlen:.1f}" '
                     f'stroke="{STROKE}" stroke-width="1"/>')
        if major:
            label = str(i // 2)
            # top label
            parts.append(f'<text x="{x:.1f}" y="{T - LABEL_OFF:.1f}" text-anchor="middle" '
                         f'{FONT} fill="{LABEL_FILL}">{label}</text>')
            # bottom label
            parts.append(f'<text x="{x:.1f}" y="{B + LABEL_OFF + 6:.1f}" text-anchor="middle" '
                         f'{FONT} fill="{LABEL_FILL}">{label}</text>')

    for j in range(n_y + 1):
        y = B - (j * 0.5) * SCALE               # j=0 is the FRONT (bottom of svg)
        major = (j % 2 == 0)
        tlen = TICK_MAJOR if major else TICK_MINOR
        # left edge ticks (pointing left)
        parts.append(f'<line x1="{L:.1f}" y1="{y:.1f}" x2="{L-tlen:.1f}" y2="{y:.1f}" '
                     f'stroke="{STROKE}" stroke-width="1"/>')
        # right edge ticks (pointing right)
        parts.append(f'<line x1="{R:.1f}" y1="{y:.1f}" x2="{R+tlen:.1f}" y2="{y:.1f}" '
                     f'stroke="{STROKE}" stroke-width="1"/>')
        if major:
            label = str(j // 2)
            # left label
            parts.append(f'<text x="{L - LABEL_OFF:.1f}" y="{y+3:.1f}" text-anchor="end" '
                         f'{FONT} fill="{LABEL_FILL}">{label}</text>')
            # right label
            parts.append(f'<text x="{R + LABEL_OFF:.1f}" y="{y+3:.1f}" text-anchor="start" '
                         f'{FONT} fill="{LABEL_FILL}">{label}</text>')
    return "".join(parts)


def layout_to_svg(layout: Layout) -> str:
    lot = layout.lot
    W = lot.width * SCALE + 2 * MARGIN
    H = lot.depth * SCALE + 2 * MARGIN
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="0 0 {W:.0f} {H:.0f}">']
    s.append(f'<rect x="0" y="0" width="{W:.0f}" height="{H:.0f}" fill="white"/>')

    # lot boundary
    s.append(_rect_svg(lot, Rect(0, 0, lot.width, lot.depth), "#fbfbf7"))
    # metre ruler on all sides (0.5 m ticks, labels every 1 m)
    s.append(_ruler_svg(lot))
    # buildable envelope (dotted)
    env = lot.envelope()
    ex = MARGIN + env.x0 * SCALE
    ey = _y(lot, env.y1)
    s.append(f'<rect x="{ex:.1f}" y="{ey:.1f}" width="{env.w*SCALE:.1f}" height="{env.h*SCALE:.1f}" '
             f'fill="none" stroke="#9aa" stroke-width="1" stroke-dasharray="3 3"/>')

    # setback elements (uncovered, dashed)
    for e in layout.elements:
        s.append(_rect_svg(lot, e.rect, _fill(e), dashed=True,
                           label=LABELS.get(e.type, e.type),
                           sub=f"{e.rect.w:.1f}×{e.rect.h:.1f} m"))

    # footprint rooms (may be composite / L-shaped -> draw each cell, label once)
    for r in layout.rooms:
        fill = _fill(r)
        cells = r.cells
        for c in cells:
            s.append(_rect_svg(lot, c, fill))   # fill cells, no per-cell label
        big = max(cells, key=lambda c: c.area)  # label on the largest cell
        cx = MARGIN + (big.x0 + big.w / 2) * SCALE
        cy = _y(lot, big.y0 + big.h / 2)
        label = LABELS.get(r.type, r.type)
        if len(cells) > 1:
            sub = f"{r.area:.1f} sqm (L-shaped)"
        else:
            sub = f"{r.rect.w:.1f}×{r.rect.h:.1f} m · {r.rect.area:.1f} sqm"
        s.append(f'<text x="{cx:.1f}" y="{cy-6:.1f}" text-anchor="middle" '
                 f'font-family="Arial" font-size="12" font-weight="bold" fill="#222">{html.escape(label)}</text>')
        s.append(f'<text x="{cx:.1f}" y="{cy+10:.1f}" text-anchor="middle" '
                 f'font-family="Arial" font-size="10" fill="#555">{html.escape(sub)}</text>')

    # FRONT marker
    s.append(f'<text x="{MARGIN + lot.width*SCALE/2:.1f}" y="{H-12:.1f}" text-anchor="middle" '
             f'font-family="Arial" font-size="12" font-weight="bold" fill="#888">FRONT (street)</text>')
    s.append("</svg>")
    return "".join(s)


# ---------------------------------------------------------------------------
# Architectural overlay: doors and windows (Phase D.1, commit 2)
# ---------------------------------------------------------------------------

def _to_svg_xy(lot, mx, my):
    return MARGIN + mx * SCALE, MARGIN + (lot.depth - my) * SCALE


def _opp_side(side: str) -> str:
    return {"N": "S", "S": "N", "E": "W", "W": "E"}[side]


def _door_svg(door, layout) -> str:
    """Render a door symbol: an opening erased into the wall, a perpendicular
    door panel line, and a quarter-arc swing. The wall side stored on the
    Door is relative to room_a (or room_b if room_a == 'exterior')."""
    if door.room_a == "exterior":
        owner = next((r for r in layout.rooms if r.id == door.room_b), None)
        owner_is_a = False
    else:
        owner = next((r for r in layout.rooms if r.id == door.room_a), None)
        owner_is_a = True
    if owner is None:
        return ""
    rect, wall, pos, cw = owner.rect, door.wall, door.position_m, door.clear_width_m

    # Two endpoints of the door opening, in MODEL coords. The "near" end is
    # where position_m sits; the "far" end is `cw` further along the wall.
    if wall == "N":
        near = (rect.x0 + pos, rect.y1)
        far  = (rect.x0 + pos + cw, rect.y1)
        perp_into_owner = "S"
    elif wall == "S":
        near = (rect.x0 + pos, rect.y0)
        far  = (rect.x0 + pos + cw, rect.y0)
        perp_into_owner = "N"
    elif wall == "E":
        near = (rect.x1, rect.y0 + pos)
        far  = (rect.x1, rect.y0 + pos + cw)
        perp_into_owner = "W"
    elif wall == "W":
        near = (rect.x0, rect.y0 + pos)
        far  = (rect.x0, rect.y0 + pos + cw)
        perp_into_owner = "E"
    else:
        return ""

    # Does the door swing into the owner room? swing_into is a room id.
    swing_owner = (door.swing_into == door.room_a) if owner_is_a \
                  else (door.swing_into == door.room_b)
    perp = perp_into_owner if swing_owner else _opp_side(perp_into_owner)

    # Hinge defaults to the "near" endpoint; latch is the "far" endpoint.
    # Door panel extends from hinge perpendicular by `cw` into the swing side.
    hx, hy = near
    lx, ly = far
    if perp == "N":   tip = (hx, hy + cw)
    elif perp == "S": tip = (hx, hy - cw)
    elif perp == "E": tip = (hx + cw, hy)
    else:             tip = (hx - cw, hy)  # W

    # SVG-space conversions
    lot = layout.lot
    hxs, hys = _to_svg_xy(lot, *near)
    lxs, lys = _to_svg_xy(lot, *far)
    txs, tys = _to_svg_xy(lot, *tip)

    # SVG arc sweep flag. The arc must bulge OUTWARD — away from the hinge
    # (the centre of the swing) — toward the chord-midpoint side. With the
    # arc's centre at the hinge, the sweep flag selects which of the two
    # possible 90° arcs to draw. Cross product of (hinge→tip) × (hinge→latch)
    # in SVG y-down coords picks the right one: the arc that bulges "away"
    # from the hinge, i.e., the outer/balloon-out arc that traces the actual
    # swing path of the door's tip.
    cross = (txs - hxs) * (lys - hys) - (tys - hys) * (lxs - hxs)
    sweep = 1 if cross > 0 else 0

    radius = cw * SCALE
    # Erase the wall AND room stroke under the door opening with a wide white
    # line (10 px > the 8.4 px exterior wall, so the opening is clean).
    parts = [
        f'<line x1="{hxs:.1f}" y1="{hys:.1f}" x2="{lxs:.1f}" y2="{lys:.1f}" '
        f'stroke="white" stroke-width="10"/>',
        # Door panel (perpendicular line from hinge to tip)
        f'<line x1="{hxs:.1f}" y1="{hys:.1f}" x2="{txs:.1f}" y2="{tys:.1f}" '
        f'stroke="#444" stroke-width="1.4"/>',
        # Swing arc (quarter circle from tip to latch)
        f'<path d="M {txs:.1f} {tys:.1f} A {radius:.1f} {radius:.1f} 0 0 '
        f'{sweep} {lxs:.1f} {lys:.1f}" fill="none" stroke="#999" '
        f'stroke-width="0.7" stroke-dasharray="2 2"/>',
    ]
    return "".join(parts)


def _window_svg(window, layout) -> str:
    """Render a window: erase the wall stroke at the opening, then draw a
    thin blue band representing the window glass."""
    room = next((r for r in layout.rooms if r.id == window.room), None)
    if room is None:
        return ""
    rect, wall, pos, w = room.rect, window.wall, window.position_m, window.width_m

    if wall == "N":
        a = (rect.x0 + pos, rect.y1)
        b = (rect.x0 + pos + w, rect.y1)
    elif wall == "S":
        a = (rect.x0 + pos, rect.y0)
        b = (rect.x0 + pos + w, rect.y0)
    elif wall == "E":
        a = (rect.x1, rect.y0 + pos)
        b = (rect.x1, rect.y0 + pos + w)
    elif wall == "W":
        a = (rect.x0, rect.y0 + pos)
        b = (rect.x0, rect.y0 + pos + w)
    else:
        return ""

    lot = layout.lot
    axs, ays = _to_svg_xy(lot, *a)
    bxs, bys = _to_svg_xy(lot, *b)
    # Wide white erase (10 px > exterior wall thickness so the wall is cut
    # cleanly), then a blue glass strip on top.
    return (
        f'<line x1="{axs:.1f}" y1="{ays:.1f}" x2="{bxs:.1f}" y2="{bys:.1f}" '
        f'stroke="white" stroke-width="10"/>'
        f'<line x1="{axs:.1f}" y1="{ays:.1f}" x2="{bxs:.1f}" y2="{bys:.1f}" '
        f'stroke="#7aaad1" stroke-width="2.5"/>'
    )


# ---------------------------------------------------------------------------
# Wall thickness (Phase D.2)
# ---------------------------------------------------------------------------

WALL_THICKNESS_INTERIOR = 0.10   # m — interior partition (drywall or thin CHB)
WALL_THICKNESS_EXTERIOR = 0.20   # m — exterior CHB + finish
WALL_FILL = "#555"               # gray fill for walls
EPS = 1e-3


def _compute_walls(plan):
    """Walk the layout and emit wall geometry (axis-aligned rectangles).

    Strategy:
      Pass A — interior walls: for every PAIR of rooms that shares a non-zero
               edge, emit one wall rectangle centred on that edge. Skip pairs
               flagged as open_plan (no wall between L/D/K rooms etc.).
      Pass B — exterior walls: for every room edge, subtract all the segments
               covered by other rooms — what's left is exterior. Emit one
               wall rectangle per exterior segment, centred on the edge.

    Walls are CENTRED on the room boundary, so each wall extends half its
    thickness into the room interior AND half into the adjacent space
    (another room for interior walls, the buildable envelope void / setback
    for exterior walls)."""
    rooms = plan.layout.rooms
    open_set = {frozenset((e.room_a, e.room_b)) for e in plan.open_plan_edges}
    walls = []

    # Pass A — interior walls, one per non-open-plan pair
    for i, r1 in enumerate(rooms):
        for r2 in rooms[i + 1:]:
            if frozenset((r1.id, r2.id)) in open_set:
                continue
            edge = _wall_shared_edge(r1.rect, r2.rect)
            if edge is None:
                continue
            side, coord, start, end = edge
            walls.append(_wall_rect(side, coord, start, end,
                                    WALL_THICKNESS_INTERIOR))

    # Pass B — exterior walls, uncovered portions of each side per room
    for r in rooms:
        for side in ("N", "S", "E", "W"):
            uncovered = _uncovered_segments(r, side, rooms)
            if side == "N":   coord = r.rect.y1
            elif side == "S": coord = r.rect.y0
            elif side == "E": coord = r.rect.x1
            else:             coord = r.rect.x0
            for s_, e_ in uncovered:
                walls.append(_wall_rect(side, coord, s_, e_,
                                        WALL_THICKNESS_EXTERIOR))

    return walls


def _wall_shared_edge(a, b):
    """If a and b share a wall, return (side_of_a, coord, start, end) where
    side_of_a is 'N'/'S'/'E'/'W'. coord is the constant axis value; start /
    end are the perpendicular range of the SHARED segment. Returns None if
    a and b don't share a wall."""
    if abs(a.x1 - b.x0) <= EPS:                     # a is west of b
        s, e = max(a.y0, b.y0), min(a.y1, b.y1)
        return ("E", a.x1, s, e) if e - s > EPS else None
    if abs(a.x0 - b.x1) <= EPS:                     # a is east of b
        s, e = max(a.y0, b.y0), min(a.y1, b.y1)
        return ("W", a.x0, s, e) if e - s > EPS else None
    if abs(a.y1 - b.y0) <= EPS:                     # a is south (front of) b
        s, e = max(a.x0, b.x0), min(a.x1, b.x1)
        return ("N", a.y1, s, e) if e - s > EPS else None
    if abs(a.y0 - b.y1) <= EPS:                     # a is north (rear of) b
        s, e = max(a.x0, b.x0), min(a.x1, b.x1)
        return ("S", a.y0, s, e) if e - s > EPS else None
    return None


def _uncovered_segments(room, side, all_rooms):
    """Return the segments along `room`'s `side` edge that are NOT shared
    with any other room — these face the buildable envelope void or the
    setback / exterior."""
    if side == "N":
        edge_start, edge_end = room.rect.x0, room.rect.x1
        match_coord = room.rect.y1
        is_neighbor = lambda o: abs(o.rect.y0 - match_coord) <= EPS
        proj = lambda o: (o.rect.x0, o.rect.x1)
    elif side == "S":
        edge_start, edge_end = room.rect.x0, room.rect.x1
        match_coord = room.rect.y0
        is_neighbor = lambda o: abs(o.rect.y1 - match_coord) <= EPS
        proj = lambda o: (o.rect.x0, o.rect.x1)
    elif side == "E":
        edge_start, edge_end = room.rect.y0, room.rect.y1
        match_coord = room.rect.x1
        is_neighbor = lambda o: abs(o.rect.x0 - match_coord) <= EPS
        proj = lambda o: (o.rect.y0, o.rect.y1)
    else:  # W
        edge_start, edge_end = room.rect.y0, room.rect.y1
        match_coord = room.rect.x0
        is_neighbor = lambda o: abs(o.rect.x1 - match_coord) <= EPS
        proj = lambda o: (o.rect.y0, o.rect.y1)

    covered = []
    for o in all_rooms:
        if o is room:
            continue
        if not is_neighbor(o):
            continue
        a, b = proj(o)
        s, e = max(a, edge_start), min(b, edge_end)
        if e - s > EPS:
            covered.append((s, e))

    return _subtract_segments(edge_start, edge_end, covered)


def _subtract_segments(start, end, covered):
    """Subtract a list of covered (s, e) intervals from [start, end].
    Returns the uncovered intervals as a list of (s, e) tuples."""
    if not covered:
        return [(start, end)]
    covered = sorted(covered)
    out = []
    cursor = start
    for s, e in covered:
        if s > cursor + EPS:
            out.append((cursor, s))
        cursor = max(cursor, e)
    if end > cursor + EPS:
        out.append((cursor, end))
    return out


def _wall_rect(side, coord, start, end, thickness):
    """Build a Rect representing a wall sitting on a room edge, centred on
    `coord` (so half the thickness sits on either side of the edge)."""
    from model import Rect as _Rect
    half = thickness / 2
    if side in ("N", "S"):
        return _Rect(start, coord - half, end, coord + half)
    return _Rect(coord - half, start, coord + half, end)


def _wall_svg(wall, layout) -> str:
    """Render a wall as a filled gray rect."""
    lot = layout.lot
    x0, y0 = _to_svg_xy(lot, wall.x0, wall.y1)   # svg y is flipped, top edge = larger model y
    return (f'<rect x="{x0:.2f}" y="{y0:.2f}" '
            f'width="{wall.w * SCALE:.2f}" height="{wall.h * SCALE:.2f}" '
            f'fill="{WALL_FILL}" stroke="none"/>')


def _open_plan_svg(edge, layout) -> str:
    """Erase the shared wall stroke between two open-plan rooms — the entire
    shared segment is overdrawn in white."""
    rooms_by_id = {r.id: r for r in layout.rooms}
    a = rooms_by_id.get(edge.room_a)
    b = rooms_by_id.get(edge.room_b)
    if a is None or b is None:
        return ""
    ra, rb = a.rect, b.rect
    eps = 1e-3
    if abs(ra.x1 - rb.x0) <= eps:           # vertical wall (a west of b)
        x = ra.x1
        y0 = max(ra.y0, rb.y0); y1 = min(ra.y1, rb.y1)
        p1, p2 = (x, y0), (x, y1)
    elif abs(ra.x0 - rb.x1) <= eps:         # vertical wall (a east of b)
        x = ra.x0
        y0 = max(ra.y0, rb.y0); y1 = min(ra.y1, rb.y1)
        p1, p2 = (x, y0), (x, y1)
    elif abs(ra.y1 - rb.y0) <= eps:         # horizontal wall (a south of b)
        y = ra.y1
        x0 = max(ra.x0, rb.x0); x1 = min(ra.x1, rb.x1)
        p1, p2 = (x0, y), (x1, y)
    elif abs(ra.y0 - rb.y1) <= eps:         # horizontal wall (a north of b)
        y = ra.y0
        x0 = max(ra.x0, rb.x0); x1 = min(ra.x1, rb.x1)
        p1, p2 = (x0, y), (x1, y)
    else:
        return ""
    lot = layout.lot
    p1s = _to_svg_xy(lot, *p1)
    p2s = _to_svg_xy(lot, *p2)
    # Use a SLIGHTLY wider erase than the rendered stroke so two overlapping
    # 1.5 px room strokes are fully covered. 5 px gives ~1.75 px clearance
    # each side which is enough at the typical 42 px/m scale.
    return (f'<line x1="{p1s[0]:.1f}" y1="{p1s[1]:.1f}" '
            f'x2="{p2s[0]:.1f}" y2="{p2s[1]:.1f}" '
            f'stroke="white" stroke-width="5"/>')


def archplan_to_svg(plan) -> str:
    """Render the full architectural plan: room fills, walls of finite
    thickness (exterior 0.20 m, interior 0.10 m), open-plan transitions
    (where the wall has been suppressed), and doors / windows as openings
    through walls.

    SVG layer order (back to front):
      1. lot fill, ruler, envelope outline, setback elements   (layout_to_svg)
      2. room fills with labels                                (layout_to_svg)
      3. walls (gray bars on top of room boundaries)           NEW
      4. open-plan erases (clear room strokes where no wall)
      5. door erases + door panels + swing arcs
      6. window erases + window glass strips
    """
    base = layout_to_svg(plan.layout)
    overlays = []
    # Walls first — they cover room strokes for every non-open-plan boundary.
    for wall in _compute_walls(plan):
        overlays.append(_wall_svg(wall, plan.layout))
    # Open-plan: erase room strokes where there's no wall.
    for ope in plan.open_plan_edges:
        overlays.append(_open_plan_svg(ope, plan.layout))
    # Doors and windows punch openings through walls.
    for d in plan.doors:
        overlays.append(_door_svg(d, plan.layout))
    for w in plan.windows:
        overlays.append(_window_svg(w, plan.layout))
    inject = "".join(overlays)
    return base.replace("</svg>", inject + "</svg>")


def gallery_html(layouts: List[Layout], title: str) -> str:
    cards = []
    for idx, L in enumerate(layouts, 1):
        svg = layout_to_svg(L)
        errs = [i for i in L.issues if i.severity == "error"]
        warns = [i for i in L.issues if i.severity == "warning"]
        sugg = [i for i in L.issues if i.severity == "suggestion"]
        status = ("<span style='color:#137333;font-weight:bold'>&#10003; COMPLIANT</span>"
                  if not errs else
                  f"<span style='color:#b00020;font-weight:bold'>&#10007; {len(errs)} hard violation(s)</span>")
        notes = "".join(f"<li>{html.escape(str(i))}</li>" for i in (warns + sugg)[:8])
        mpos = L.genome.get("master_position", "-")
        epos = L.genome.get("ensuite_position")
        ens_label = {
            "alongside_master": "ensuite alongside master",
            "twin_mid": "twin baths (stacked)",
            "twin_side": "twin baths (side-by-side)",
        }
        variant = f"master {mpos}"
        if epos:
            variant += f" &middot; {ens_label.get(epos, epos)}"
        cards.append(f"""
        <div class="card">
          <h3>Candidate {idx} &mdash; {variant}</h3>
          <div class="status">fitness {L.score:.2f} &middot; carport {L.carport_side}</div>
          <div class="status">{status} &middot; footprint {L.footprint_area:.1f} sqm &middot; occupancy {L.occupancy_pct:.1f}%</div>
          <div class="svg">{svg}</div>
          <details><summary>{len(warns)} warning(s), {len(sugg)} suggestion(s)</summary>
            <ul>{notes or '<li>none</li>'}</ul></details>
        </div>""")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;margin:24px;background:#f7f8fa;color:#222}}
 h1{{font-size:22px}} .sub{{color:#666;margin-bottom:18px}}
 .grid{{display:flex;flex-wrap:wrap;gap:20px}}
 .card{{background:#fff;border:1px solid #e2e5ea;border-radius:10px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 .card h3{{font-size:15px;margin:0 0 4px}} .status{{font-size:13px;margin-bottom:8px;color:#444}}
 .svg{{border:1px solid #eee;border-radius:6px;overflow:hidden}}
 details{{margin-top:8px;font-size:12px;color:#555}} li{{margin:2px 0}}
 .legend span{{display:inline-block;padding:2px 8px;margin:2px;border-radius:4px;font-size:12px;border:1px solid #ccc}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="sub">PH single-detached 2BR &middot; 10&times;15 m lot &middot; single-storey &middot; generated by subdivision + simulated annealing, validated against PD 1096.</div>
<div class="legend">
 <span style="background:#cfe2f3">Public (living/dining)</span>
 <span style="background:#d9ead3">Private (bedrooms)</span>
 <span style="background:#fce5cd">Service (kitchen)</span>
 <span style="background:#ead1dc">Bath</span>
 <span style="background:#f2f2f2">Uncovered setback element (dashed)</span>
</div>
<div class="grid">{''.join(cards)}</div>
</body></html>"""
