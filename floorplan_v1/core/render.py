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
    "common_bath": "T&B",
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
    "porch": "PORCH",
}

# Compact fallbacks for room types whose preferred label may not fit a small
# room. The full label is tried first; the fallback is used only if the
# label can't be made to fit even at the minimum font size, with wrapping.
LABEL_FALLBACKS = {
    "ensuite_bath": "T&B",
}

# Adaptive labeling thresholds. Labels are scaled and / or wrapped to fit
# the cell they're drawn in; rooms below the area threshold drop the
# dimensions sub-text entirely (the rule of thumb being that <3 sqm rooms
# are typically baths or closets where the exact dimensions are recoverable
# from the lot ruler and aren't load-bearing on the plan).
LABEL_FONT_MAX = 12
LABEL_FONT_MIN = 8
SUB_FONT_FIXED = 10          # consistent dimensions size across all rooms
SMALL_ROOM_THRESHOLD_SQM = 3.0
LABEL_USE_RATIO = 0.85       # fraction of cell width usable for the text


def _estimate_text_width_px(text: str, font_size: float, bold: bool) -> float:
    """Rough Arial text width estimate (good enough for fit decisions)."""
    avg_char = font_size * (0.62 if bold else 0.56)
    return len(text) * avg_char


def _fit_label_lines(text, max_w_px, max_font, min_font, *,
                      fallback=None, bold=True):
    """Try to fit `text` inside `max_w_px`. Strategy:
      1. Single line at decreasing font sizes (max → min).
      2. If still too wide and there's a space, split into two lines at
         the most-balanced word boundary, retry single → min font.
      3. If a fallback shorter label is supplied, try it single-line.
      4. Last resort: return the text at min font (slight overflow ok)."""
    # Strategy 1
    for f in range(max_font, min_font - 1, -1):
        if _estimate_text_width_px(text, f, bold) <= max_w_px:
            return [text], f
    # Strategy 2a — split on a "·" separator if present (used in the
    # dimensions sub like "1.5×2.0 m · 3.0 sqm"). The bullet is purely a
    # visual separator on the single-line form, so drop it when wrapping.
    if " · " in text:
        l1, l2 = text.split(" · ", 1)
        for f in range(max_font, min_font - 1, -1):
            if (_estimate_text_width_px(l1, f, bold) <= max_w_px and
                    _estimate_text_width_px(l2, f, bold) <= max_w_px):
                return [l1, l2], f
    # Strategy 2b — generic space split (most-balanced word boundary)
    if " " in text:
        words = text.split()
        best = None
        best_max_len = float("inf")
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            l2 = " ".join(words[i:])
            m = max(len(l1), len(l2))
            if m < best_max_len:
                best_max_len = m
                best = (l1, l2)
        if best:
            l1, l2 = best
            for f in range(max_font, min_font - 1, -1):
                if (_estimate_text_width_px(l1, f, bold) <= max_w_px and
                        _estimate_text_width_px(l2, f, bold) <= max_w_px):
                    return [l1, l2], f
    # Strategy 3
    if fallback is not None:
        for f in range(max_font, min_font - 1, -1):
            if _estimate_text_width_px(fallback, f, bold) <= max_w_px:
                return [fallback], f
    # Strategy 4
    return [fallback if fallback else text], min_font


def _fit_sub_fixed(text, max_w_px, font_size, bold=False, fallbacks=None):
    """Fit a dimensions sub at a FIXED font size. Returns a list of lines:
    1 line if the full text fits as-is, 2 lines if a " · " split fits,
    otherwise the first fallback that fits. As a last resort returns the
    shortest fallback (the bare area) even if it slightly overflows — every
    room must show its size, so a small label overflow is better than no
    label at all."""
    if _estimate_text_width_px(text, font_size, bold) <= max_w_px:
        return [text]
    if " · " in text:
        l1, l2 = text.split(" · ", 1)
        if (_estimate_text_width_px(l1, font_size, bold) <= max_w_px and
                _estimate_text_width_px(l2, font_size, bold) <= max_w_px):
            return [l1, l2]
    fbs = list(fallbacks or [])
    for f in fbs:
        if _estimate_text_width_px(f, font_size, bold) <= max_w_px:
            return [f]
    # None fit — force the shortest fallback (last in list, typically just
    # the bare area). Better to slightly overflow than to drop the size.
    if fbs:
        return [fbs[-1]]
    return []


def _emit_centered_text_block(cx, cy, label_lines, label_font,
                              sub_lines, sub_font):
    """Emit SVG <text> elements for a label block (bold, dark) and an
    optional dimensions sub block (smaller, gray) stacked vertically and
    centered on (cx, cy)."""
    n_label = len(label_lines)
    n_sub = len(sub_lines) if sub_lines else 0
    label_lh = label_font * 1.15
    sub_lh = sub_font * 1.15 if n_sub else 0
    gap = 4 if n_sub else 0
    total_h = n_label * label_lh + gap + n_sub * sub_lh
    # Top edge of the whole text block in SVG coords
    top = cy - total_h / 2
    parts = []
    # Label lines (baseline ~ font_size below the line's top)
    y = top + label_font
    for line in label_lines:
        parts.append(
            f'<text x="{cx:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'font-family="Arial" font-size="{label_font}" '
            f'font-weight="bold" fill="#222">{html.escape(line)}</text>')
        y += label_lh
    # Sub lines (no bold, gray)
    if n_sub:
        y = top + n_label * label_lh + gap + sub_font
        for line in sub_lines:
            parts.append(
                f'<text x="{cx:.1f}" y="{y:.1f}" text-anchor="middle" '
                f'font-family="Arial" font-size="{sub_font}" '
                f'fill="#555">{html.escape(line)}</text>')
            y += sub_lh
    return "".join(parts)


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


def _rect_svg(lot, rect: Rect, fill, dashed=False, label="", sub="",
              no_stroke=False):
    px = MARGIN + rect.x0 * SCALE
    py = _y(lot, rect.y1)            # top edge = larger y
    w = rect.w * SCALE
    h = rect.h * SCALE
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    if no_stroke:
        stroke = ' stroke="none"'
    else:
        stroke = ' stroke="#333" stroke-width="1.5"'
    parts = [f'<rect x="{px:.1f}" y="{py:.1f}" width="{w:.1f}" height="{h:.1f}" '
             f'fill="{fill}"{stroke}{dash}/>']
    cx = px + w / 2
    cy = py + h / 2
    if label or sub:
        max_w = w * LABEL_USE_RATIO
        label_lines, label_font = ([], 0)
        sub_lines = []
        if label:
            label_lines, label_font = _fit_label_lines(
                label, max_w, LABEL_FONT_MAX, LABEL_FONT_MIN, bold=True)
        if sub:
            # Fixed-size dimensions for consistency across the plan; wraps
            # to 2 lines on " · " when needed, drops otherwise.
            sub_lines = _fit_sub_fixed(sub, max_w, SUB_FONT_FIXED, bold=False)
        parts.append(_emit_centered_text_block(
            cx, cy, label_lines, label_font, sub_lines, SUB_FONT_FIXED))
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

    # setback elements (uncovered, dashed). Inset by SETBACK_STROKE_INSET so
    # the dashed stroke's half-thickness overhang doesn't poke past the
    # rect's footprint (e.g., into the inside corner of an L-shape building
    # when the setback element sits flush against a building wall).
    from model import Rect as _Rect
    for e in layout.elements:
        r = e.rect
        inset = SETBACK_STROKE_INSET
        inset_rect = _Rect(r.x0 + inset, r.y0 + inset, r.x1 - inset, r.y1 - inset)
        s.append(_rect_svg(lot, inset_rect, _fill(e), dashed=True,
                           label=LABELS.get(e.type, e.type),
                           sub=f"{e.rect.w:.1f}×{e.rect.h:.1f} m"))

    # footprint rooms (may be composite / L-shaped -> draw each cell, label once)
    for r in layout.rooms:
        fill = _fill(r)
        cells = r.cells
        composite = len(cells) > 1
        for c in cells:
            # Suppress per-cell stroke on composite rooms — the cell-to-cell
            # boundaries shouldn't show as thin dark lines inside the room.
            # The composite's actual outline still appears: walls (Pass A/B/C)
            # cover all exterior edges, and at open-plan boundaries the
            # _open_plan_svg overdraw already kills the seam.
            s.append(_rect_svg(lot, c, fill, no_stroke=composite))
        big = max(cells, key=lambda c: c.area)  # label on the largest cell
        cx = MARGIN + (big.x0 + big.w / 2) * SCALE
        cy = _y(lot, big.y0 + big.h / 2)
        label_raw = LABELS.get(r.type, r.type)
        fallback = LABEL_FALLBACKS.get(r.type)
        if len(cells) > 1:
            sub_raw = f"{r.area:.1f} sqm (L-shaped)"
            sub_fallbacks = [
                f"{r.area:.1f} sqm L",
                f"{r.area:.1f} sqm",
            ]
        else:
            sub_raw = f"{r.rect.w:.1f}×{r.rect.h:.1f} m · {r.rect.area:.1f} sqm"
            sub_fallbacks = [
                f"{r.rect.area:.1f} sqm",
            ]
        # Available text width = label cell width × usable ratio.
        max_w = big.w * SCALE * LABEL_USE_RATIO
        label_lines, label_font = _fit_label_lines(
            label_raw, max_w, LABEL_FONT_MAX, LABEL_FONT_MIN,
            fallback=fallback, bold=True)
        # Every room shows a sub-line — never leave a room un-sized. The fit
        # function tries the full "dims · area" string first; if it won't fit
        # at the fixed sub-font size, the fallbacks ("area sqm" alone, or the
        # L-shaped composite's variants) are tried in order until one fits.
        # Tiny rooms typically end up with just the area; that's intentional —
        # the floor ruler still shows the exact rect, but the user can read
        # the area off the label without hunting on the ruler.
        sub_lines = _fit_sub_fixed(
            sub_raw, max_w, SUB_FONT_FIXED, bold=False,
            fallbacks=sub_fallbacks)
        s.append(_emit_centered_text_block(
            cx, cy, label_lines, label_font, sub_lines, SUB_FONT_FIXED))

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


# Lot/exterior fill — matches the lot rectangle drawn by layout_to_svg, used
# whenever an opening's "other side" is outside the building.
LOT_FILL = "#fbfbf7"

# Half-thickness of the colored erase strip used to clear the wall + room
# strokes at an opening. 5 svg-px covers the worst-case 0.20 m exterior wall
# (8.4 px) and the room stroke (1.5 px) when applied on each side of the wall.
ERASE_HALF_PX = 5


def _door_svg(door, layout) -> str:
    """Render a door symbol: an opening erased into the wall, a perpendicular
    door panel line, and a quarter-arc swing. The wall side stored on the
    Door is relative to room_a (or room_b if room_a == 'exterior')."""
    if door.room_a == "exterior":
        owner = next((r for r in layout.rooms if r.id == door.room_b), None)
        owner_is_a = False
        other = None
    elif door.room_b == "exterior":
        owner = next((r for r in layout.rooms if r.id == door.room_a), None)
        owner_is_a = True
        other = None
    else:
        owner = next((r for r in layout.rooms if r.id == door.room_a), None)
        owner_is_a = True
        other = next((r for r in layout.rooms if r.id == door.room_b), None)
    if owner is None:
        return ""
    # Pick the cell the door was placed on. For L-shape composites, the door
    # may live on rect2 rather than the primary rect (e.g., master.rect2 ↔
    # dining when ensuite_alcove_joins_master triggers). `cell_idx` is set
    # by _interior_door when generating the Door.
    cell_idx = getattr(door, "cell_idx", 0)
    cells = owner.cells
    if 0 <= cell_idx < len(cells):
        rect = cells[cell_idx]
    else:
        rect = owner.rect
    wall, pos, cw = door.wall, door.position_m, door.clear_width_m

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

    # Hinge selection: door.hinge_at picks which end of the opening is the
    # hinge. The other end becomes the latch. With "low" (default), the
    # hinge is at the position_m end; with "high", at the far end. This
    # lets the door swing open against the nearest perpendicular wall.
    if getattr(door, "hinge_at", "low") == "high":
        hinge_m = far
        latch_m = near
    else:
        hinge_m = near
        latch_m = far
    hx, hy = hinge_m
    if perp == "N":   tip = (hx, hy + cw)
    elif perp == "S": tip = (hx, hy - cw)
    elif perp == "E": tip = (hx + cw, hy)
    else:             tip = (hx - cw, hy)  # W

    # SVG-space conversions. The wall-erase needs the OPENING endpoints
    # (near & far). The door PANEL is drawn from the hinge perpendicular
    # into the room (so it hugs the perpendicular wall). The swing ARC
    # sweeps from the tip back to the latch end of the opening.
    lot = layout.lot
    hxs, hys = _to_svg_xy(lot, *hinge_m)   # hinge end of opening
    lxs, lys = _to_svg_xy(lot, *latch_m)   # latch end of opening
    txs, tys = _to_svg_xy(lot, *tip)
    nxs, nys = _to_svg_xy(lot, *near)      # opening start (for wall erase)
    fxs, fys = _to_svg_xy(lot, *far)       # opening end   (for wall erase)

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
    # Erase the wall + room strokes at the opening using the ACTUAL room
    # fill on each side of the wall (not white) — keeps the colour blocks
    # continuous so the opening doesn't read as a hole in the floor plan.
    owner_fill = _fill(owner)
    other_fill = _fill(other) if other is not None else LOT_FILL
    erase = _two_color_opening_erase(
        nxs, nys, fxs, fys, wall, owner_fill, other_fill)
    parts = [
        erase,
        # Door panel (perpendicular line from hinge to tip) — hugs the
        # perpendicular wall the door rests against when fully open.
        f'<line x1="{hxs:.1f}" y1="{hys:.1f}" x2="{txs:.1f}" y2="{tys:.1f}" '
        f'stroke="#444" stroke-width="1.4"/>',
        # Swing arc (quarter circle from tip to latch) — the far end of the
        # swing, bulging away from the perpendicular wall.
        f'<path d="M {txs:.1f} {tys:.1f} A {radius:.1f} {radius:.1f} 0 0 '
        f'{sweep} {lxs:.1f} {lys:.1f}" fill="none" stroke="#999" '
        f'stroke-width="0.7" stroke-dasharray="2 2"/>',
    ]
    return "".join(parts)


def _two_color_opening_erase(nxs, nys, fxs, fys, wall, owner_fill, other_fill):
    """Emit two filled rects covering the wall at an opening, one per side
    of the wall, each painted with the room fill on that side. `wall` is the
    Door/Window's `wall` attribute (N/S/E/W) relative to the owner room.

    For wall = N: owner is SOUTH of the wall (larger svg y), other is NORTH.
    For wall = S: owner is NORTH (smaller svg y),                 other is SOUTH.
    For wall = E: owner is WEST  (smaller svg x), other is EAST.
    For wall = W: owner is EAST                    , other is WEST."""
    h = ERASE_HALF_PX
    if wall in ("N", "S"):
        # horizontal wall — nys == fys (same svg y). Strip extends ±h in svg y.
        x_min = min(nxs, fxs)
        x_max = max(nxs, fxs)
        y_wall = nys
        if wall == "N":
            owner_y0, owner_y1 = y_wall, y_wall + h   # south (down)
            other_y0, other_y1 = y_wall - h, y_wall   # north (up)
        else:  # wall == "S"
            owner_y0, owner_y1 = y_wall - h, y_wall   # north of S wall
            other_y0, other_y1 = y_wall, y_wall + h   # south of S wall
        return (
            f'<rect x="{x_min:.1f}" y="{owner_y0:.1f}" '
            f'width="{x_max - x_min:.1f}" height="{owner_y1 - owner_y0:.1f}" '
            f'fill="{owner_fill}" stroke="none"/>'
            f'<rect x="{x_min:.1f}" y="{other_y0:.1f}" '
            f'width="{x_max - x_min:.1f}" height="{other_y1 - other_y0:.1f}" '
            f'fill="{other_fill}" stroke="none"/>'
        )
    else:
        # vertical wall — nxs == fxs (same svg x). Strip extends ±h in svg x.
        y_min = min(nys, fys)
        y_max = max(nys, fys)
        x_wall = nxs
        if wall == "E":
            owner_x0, owner_x1 = x_wall - h, x_wall   # west of E wall
            other_x0, other_x1 = x_wall, x_wall + h   # east of E wall
        else:  # wall == "W"
            owner_x0, owner_x1 = x_wall, x_wall + h   # east of W wall
            other_x0, other_x1 = x_wall - h, x_wall   # west of W wall
        return (
            f'<rect x="{owner_x0:.1f}" y="{y_min:.1f}" '
            f'width="{owner_x1 - owner_x0:.1f}" height="{y_max - y_min:.1f}" '
            f'fill="{owner_fill}" stroke="none"/>'
            f'<rect x="{other_x0:.1f}" y="{y_min:.1f}" '
            f'width="{other_x1 - other_x0:.1f}" height="{y_max - y_min:.1f}" '
            f'fill="{other_fill}" stroke="none"/>'
        )


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
    # Erase the wall on each side of the opening using the room's fill on
    # the interior side and the lot fill on the exterior side, then draw
    # three parallel black lines (architectural convention: outer frame /
    # glass centerline / inner frame).
    erase = _two_color_opening_erase(
        axs, ays, bxs, bys, wall, _fill(room), LOT_FILL)
    win_offset = 3                 # px — perpendicular spread of the 3 lines
    win_color = "#222"             # near-black; matches wall darks
    win_stroke = 1.0
    if wall in ("N", "S"):
        # horizontal wall — three lines stacked vertically along the opening
        x1, x2 = axs, bxs
        y_c = ays                  # ays == bys
        offsets = (-win_offset, 0, win_offset)
        lines = [
            f'<line x1="{x1:.1f}" y1="{y_c + dy:.1f}" '
            f'x2="{x2:.1f}" y2="{y_c + dy:.1f}" '
            f'stroke="{win_color}" stroke-width="{win_stroke}"/>'
            for dy in offsets
        ]
    else:
        # vertical wall — three lines side by side along the opening
        y1, y2 = ays, bys
        x_c = axs                  # axs == bxs
        offsets = (-win_offset, 0, win_offset)
        lines = [
            f'<line x1="{x_c + dx:.1f}" y1="{y1:.1f}" '
            f'x2="{x_c + dx:.1f}" y2="{y2:.1f}" '
            f'stroke="{win_color}" stroke-width="{win_stroke}"/>'
            for dx in offsets
        ]
    return erase + "".join(lines)


# ---------------------------------------------------------------------------
# Wall thickness (Phase D.2)
# ---------------------------------------------------------------------------

WALL_THICKNESS_INTERIOR = 0.10   # m — interior partition (drywall or thin CHB)
WALL_THICKNESS_EXTERIOR = 0.20   # m — exterior CHB + finish
WALL_FILL = "#555"               # gray fill for walls

# Setback elements (carport, dirty kitchen, etc.) are drawn with a dashed
# 1.5 px stroke; the stroke is centred on the rect perimeter and overhangs
# half its width past the rect bounds. When the element sits flush against
# a building wall (e.g., 3 m carport flush at the L-cut), that overhang
# pokes past the building's corner into the room interior. Insetting the
# rendered rect by ~3 cm keeps the dashed line clear of the building corner
# without visibly changing the dimensions.
SETBACK_STROKE_INSET = 0.03      # m — half-stroke overhang clearance
EPS = 1e-3


def _void_rects(plan):
    """Build a list of (id, rect, consumed_by) tuples for the topology's
    building voids in lot/model coordinates. Voids participate in the wall
    graph like phantom rooms: walls between a real room and a void are
    treated as EXTERIOR walls (building's outer face), but the void's
    OTHER edges (where they meet the buildable envelope edge) get no
    walls — those faces are open to the outside (e.g., to the carport)."""
    out = []
    env = plan.layout.lot.envelope()
    for v in (plan.topology.building_voids or []):
        loc = (v.location or "").lower()
        if loc == "front_left":
            r = Rect(env.x0, env.y0, env.x0 + v.width_m, env.y0 + v.depth_m)
        elif loc == "front_right":
            r = Rect(env.x1 - v.width_m, env.y0, env.x1, env.y0 + v.depth_m)
        elif loc == "rear_left":
            r = Rect(env.x0, env.y1 - v.depth_m, env.x0 + v.width_m, env.y1)
        elif loc == "rear_right":
            r = Rect(env.x1 - v.width_m, env.y1 - v.depth_m, env.x1, env.y1)
        else:
            continue
        out.append((v.id, r, v.consumed_by))
    return out


def _compute_walls(plan):
    """Walk the layout and emit wall geometry (axis-aligned rectangles).

    Strategy (operates on CELLS, so L-shaped composite rooms are handled
    correctly — the wall between a room's own primary rect and its rect2
    alcove is not drawn, the alcove's exterior walls are drawn, and the
    alcove's edges shared with adjacent rooms become proper interior walls):
      Pass A — interior walls: for every PAIR of cells from DIFFERENT rooms
               that share a non-zero edge, emit one wall rectangle. Skip
               room pairs flagged as open_plan.
      Pass B — exterior walls: for every cell edge, subtract all the segments
               covered by OTHER cells (including other cells of the same
               room — those are interior to the composite, not exterior)
               AND any building voids. What's left faces the lot exterior.
      Pass C — cell↔void walls: walls between a cell and a building void
               are EXTERIOR-grade (the building's outer face meeting the
               void). The void itself contributes NO walls along its
               lot-edge sides (those are open).

    Walls are CENTRED on the cell boundary, so each wall extends half its
    thickness into the cell interior AND half into the adjacent space."""
    rooms = plan.layout.rooms
    open_set = {frozenset((e.room_a, e.room_b)) for e in plan.open_plan_edges}
    voids = _void_rects(plan)               # list of (id, Rect, consumed_by)
    walls = []
    # Envelope edges — used by Pass B to decide whether an uncovered cell
    # side faces the LOT EXTERIOR (truly outside the building → exterior
    # thickness) or an INTERIOR GAP inside the envelope between rooms
    # (visually still an interior wall → interior thickness).
    env = plan.layout.lot.envelope()
    env_eps = 1e-3

    # All (owning_room, cell) pairs. Iterating cells (not rooms) is what
    # makes L-shape composites render correctly.
    all_cells = [(r, c) for r in rooms for c in r.cells]

    # Pass A — interior walls, one per non-open-plan CELL pair from
    # DIFFERENT rooms. Cells of the same room never get a wall between them
    # (they form an L-shaped composite, internally connected).
    for i, (r1, c1) in enumerate(all_cells):
        for r2, c2 in all_cells[i + 1:]:
            if r1.id == r2.id:
                continue
            if frozenset((r1.id, r2.id)) in open_set:
                continue
            edge = _wall_shared_edge(c1, c2)
            if edge is None:
                continue
            side, coord, start, end = edge
            walls.append(_wall_rect(side, coord, start, end,
                                    WALL_THICKNESS_INTERIOR))

    # Pass C — cell ↔ void walls (the building's exterior face meeting the
    # void). Use EXTERIOR thickness because this IS the outer wall.
    for r in rooms:
        for c in r.cells:
            for _vid, vrect, _consumed in voids:
                edge = _wall_shared_edge(c, vrect)
                if edge is None:
                    continue
                side, coord, start, end = edge
                walls.append(_wall_rect(side, coord, start, end,
                                        WALL_THICKNESS_EXTERIOR))

    # Pass B — exterior walls, uncovered portions of each side per cell.
    # Treat voids and ALL other cells (including same-room cells) as
    # coverage. This way the boundary between great's rect and great's
    # rect2 isn't drawn as an exterior wall.
    #
    # An uncovered side is EXTERIOR ONLY when it sits ON the envelope
    # boundary (the cell wall is part of the building outline meeting the
    # lot setback). When the uncovered side is INSIDE the envelope — i.e.,
    # an interior gap between rooms that no room happens to cover — it
    # should be drawn at INTERIOR thickness, because visually it's still
    # an interior partition between two parts of the building interior,
    # not a wall facing the lot exterior. Without this distinction, walls
    # bounding a small gap between rooms render at exterior thickness and
    # look inconsistent with the surrounding interior walls (e.g., T&B
    # south wall east of hall when the rear band rooms have slightly
    # different depths).
    void_rects_only = [vr for _vid, vr, _c in voids]
    for r in rooms:
        for c in r.cells:
            other_cells = [oc for (_or, oc) in all_cells if oc is not c]
            for side in ("N", "S", "E", "W"):
                uncovered = _uncovered_segments_for_cell(
                    c, side, other_cells, void_rects_only)
                if side == "N":   coord = c.y1
                elif side == "S": coord = c.y0
                elif side == "E": coord = c.x1
                else:             coord = c.x0
                # Determine whether this wall edge sits on the envelope
                # boundary (true exterior) or is inside (interior gap).
                if side == "N":
                    on_env = abs(coord - env.y1) <= env_eps
                elif side == "S":
                    on_env = abs(coord - env.y0) <= env_eps
                elif side == "E":
                    on_env = abs(coord - env.x1) <= env_eps
                else:   # "W"
                    on_env = abs(coord - env.x0) <= env_eps
                thickness = WALL_THICKNESS_EXTERIOR if on_env else WALL_THICKNESS_INTERIOR
                for s_, e_ in uncovered:
                    walls.append(_wall_rect(side, coord, s_, e_, thickness))

    return walls


def _uncovered_segments_for_cell(cell, side, other_cells, void_rects):
    """Like _uncovered_segments_excluding_voids, but cell-based. `other_cells`
    is the list of all cells from every room EXCEPT this one (it may include
    other cells of the same room — those are part of the composite and so
    count as coverage too, preventing a wall between them)."""
    if side == "N":
        edge_start, edge_end = cell.x0, cell.x1
        match_coord = cell.y1
        is_neighbor = lambda o: abs(o.y0 - match_coord) <= EPS
        proj = lambda o: (o.x0, o.x1)
    elif side == "S":
        edge_start, edge_end = cell.x0, cell.x1
        match_coord = cell.y0
        is_neighbor = lambda o: abs(o.y1 - match_coord) <= EPS
        proj = lambda o: (o.x0, o.x1)
    elif side == "E":
        edge_start, edge_end = cell.y0, cell.y1
        match_coord = cell.x1
        is_neighbor = lambda o: abs(o.x0 - match_coord) <= EPS
        proj = lambda o: (o.y0, o.y1)
    else:  # W
        edge_start, edge_end = cell.y0, cell.y1
        match_coord = cell.x0
        is_neighbor = lambda o: abs(o.x1 - match_coord) <= EPS
        proj = lambda o: (o.y0, o.y1)
    covered = []
    for o in other_cells:
        if not is_neighbor(o):
            continue
        a, b = proj(o)
        s, e = max(a, edge_start), min(b, edge_end)
        if e - s > EPS:
            covered.append((s, e))
    for v in void_rects:
        if not is_neighbor(v):
            continue
        a, b = proj(v)
        s, e = max(a, edge_start), min(b, edge_end)
        if e - s > EPS:
            covered.append((s, e))
    return _subtract_segments(edge_start, edge_end, covered)


def _uncovered_segments_excluding_voids(room, side, all_rooms, void_rects):
    """Like _uncovered_segments, but also subtracts the segments covered by
    building voids. We don't want to emit a Pass B (exterior) wall on a
    side where a void abuts, because Pass C already emitted that wall."""
    base = _uncovered_segments(room, side, all_rooms)
    if not void_rects:
        return base
    # For each void touching this room's edge, mark its perpendicular range
    # as "covered" and subtract from the base segments.
    if side == "N":
        match_coord = room.rect.y1
        is_neighbor = lambda v: abs(v.y0 - match_coord) <= EPS
        proj = lambda v: (v.x0, v.x1)
    elif side == "S":
        match_coord = room.rect.y0
        is_neighbor = lambda v: abs(v.y1 - match_coord) <= EPS
        proj = lambda v: (v.x0, v.x1)
    elif side == "E":
        match_coord = room.rect.x1
        is_neighbor = lambda v: abs(v.x0 - match_coord) <= EPS
        proj = lambda v: (v.y0, v.y1)
    else:  # W
        match_coord = room.rect.x0
        is_neighbor = lambda v: abs(v.x1 - match_coord) <= EPS
        proj = lambda v: (v.y0, v.y1)
    covered = []
    for v in void_rects:
        if not is_neighbor(v):
            continue
        a, b = proj(v)
        covered.append((a, b))
    # Subtract void-covered intervals from each base segment.
    out = []
    for seg_s, seg_e in base:
        out.extend(_subtract_segments(seg_s, seg_e, covered))
    return out


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


def _corner_caps(walls, rooms=None, open_plan_endpoints=None):
    """Emit a small filled square at corners where two perpendicular walls
    meet and leave a small unfilled notch.

    Two cases need a cap:
      * Mixed-thickness joints (interior wall ending at an exterior wall).
        The thinner wall's face is set back from the thicker wall's face,
        and the corner has a small visible notch.
      * Same-thickness L joints at CONVEX exterior corners (e.g., the
        building's outside SE corner, or the outside corner of the L-cut).
        The notch is on the exterior side and reads as a stray gap if not
        capped.

    Skip:
      * Endpoints where no other wall actually meets.
      * Same-thickness L joints at CONCAVE corners (e.g., the inside corner
        of a void-cut L-shape). The wall rects already cover the joint
        cleanly; emitting a cap there paints a dark dot inside the room.
      * Same-thickness COLLINEAR joints (two segments of the same straight
        wall). No notch — the rects touch end-to-end.
      * Corners that sit ON an open-plan-edge endpoint. The notch quadrant
        in such a corner is in the open-plan continuation, and painting it
        produces a stray dark dot inside the LDK opening. Suppressing the
        cap leaves the small notch unfilled — it shows the underlying room
        fill (cyan / public color) and reads as part of the open zone.

    Convex vs concave is detected by sampling the 4 quadrants of the corner:
    a convex corner has exactly 1 quadrant inside a room (the building
    interior), a concave corner has 3 quadrants inside a room (the
    void-cut inside corner sits in the interior). The rooms list is
    required for this check; if not supplied, same-thickness corners are
    skipped (legacy behaviour).

    `open_plan_endpoints`: optional iterable of (x, y) tuples — every endpoint
    of every open-plan edge in the layout. When provided, caps are
    suppressed at any corner whose point matches one of these endpoints
    within `eps`. See the fourth Skip case above. If not supplied,
    behaviour is unchanged from before (caps drawn at all eligible corners).
    """
    if not walls:
        return []
    eps = 1e-3
    ope_points = list(open_plan_endpoints or [])
    # Collect candidate (point, wall, axis) tuples. axis tells us the
    # orientation of `w` so we can detect collinear joints.
    candidates = []
    for w in walls:
        if w.w >= w.h:                          # horizontal-oriented wall
            cy_mid = (w.y0 + w.y1) / 2.0
            thickness = w.h
            for cx in (w.x0, w.x1):
                candidates.append((cx, cy_mid, thickness, w, "H"))
        else:                                    # vertical-oriented wall
            cx_mid = (w.x0 + w.x1) / 2.0
            thickness = w.w
            for cy in (w.y0, w.y1):
                candidates.append((cx_mid, cy, thickness, w, "V"))

    def _other_walls_at(point, source_wall):
        out = []
        px, py = point
        for ow in walls:
            if ow is source_wall:
                continue
            if (ow.x0 - eps <= px <= ow.x1 + eps and
                ow.y0 - eps <= py <= ow.y1 + eps):
                out.append(ow)
        return out

    def _wall_axis(ow):
        return "H" if ow.w >= ow.h else "V"

    def _is_inside_any_room(point):
        if not rooms:
            return False
        px, py = point
        for r in rooms:
            for c in r.cells:
                if (c.x0 - eps <= px <= c.x1 + eps and
                    c.y0 - eps <= py <= c.y1 + eps):
                    return True
        return False

    from model import Rect as _Rect
    caps = []
    for px, py, my_thick, w, my_axis in candidates:
        meets = _other_walls_at((px, py), w)
        if not meets:
            continue                               # wall ends in open interior
        # If all other walls are COLLINEAR with this wall (same axis), skip:
        # this is a straight wall split into segments, not a corner.
        if all(_wall_axis(ow) == my_axis for ow in meets):
            continue
        # Skip when this corner sits on an open-plan-edge endpoint. At such
        # corners the cap's diagonal-notch quadrant extends INTO the open
        # zone (where there's no wall to back it), painting a stray dark
        # 0.05 m dot inside the LDK opening. Without the cap, that quadrant
        # falls back to the room's underlying fill color and blends in.
        if any(abs(ex - px) <= eps and abs(ey - py) <= eps for ex, ey in ope_points):
            continue
        # Cap size = max thickness of the walls meeting at this corner.
        thicknesses = {round(my_thick, 4)} | {
            round(min(ow.w, ow.h), 4) for ow in meets
        }
        cap_size = max(thicknesses)
        half = cap_size / 2.0
        mixed = len(thicknesses) > 1
        if not mixed:
            # Same-thickness corner: emit cap at L-corners AND + junctions.
            # The cap fills the one quadrant of the cap area that's not
            # covered by the abutting walls — at a convex L that's the
            # exterior notch, at a concave L it's the small interior notch,
            # and at a + junction (3+ rooms meeting) it's the diagonal
            # notch left where two perpendicular walls of the same thickness
            # share only a corner-of-corner rather than fully overlapping.
            # Skip only inside_count == 2 (straight-through wall at the
            # building boundary — no corner, nothing to cap).
            offset = max(half * 1.5, 0.05)
            quads = [
                (px - offset, py - offset),
                (px + offset, py - offset),
                (px - offset, py + offset),
                (px + offset, py + offset),
            ]
            inside_count = sum(1 for q in quads if _is_inside_any_room(q))
            if inside_count == 2 or inside_count == 0:
                continue
        caps.append(_Rect(px - half, py - half, px + half, py + half))
    return caps


def _merge_open_plan_edges(edges):
    """Merge adjacent open-plan edges that share a room pair AND lie on the
    same straight line, so two consecutive cell-level erases (e.g., when one
    side of the boundary is a composite L-shape made of rect + rect2) become
    one continuous erase. Without merging, the 0.10 m inset at each end of
    each edge leaves a small unerased segment at the cell boundary that the
    room-stroke shows through.
    """
    eps = 1e-3
    intervals = []  # list of dicts with normalized geometry
    for e in edges:
        ca = getattr(e, "cell_a", None)
        cb = getattr(e, "cell_b", None)
        if ca is None or cb is None:
            intervals.append({"edge": e, "axis": None})
            continue
        # Determine the shared edge's axis and coordinate.
        if abs(ca.x1 - cb.x0) <= eps:                   # vertical wall, ca west
            axis = "V"; coord = ca.x1
            s, t = max(ca.y0, cb.y0), min(ca.y1, cb.y1)
        elif abs(ca.x0 - cb.x1) <= eps:                 # vertical wall, ca east
            axis = "V"; coord = ca.x0
            s, t = max(ca.y0, cb.y0), min(ca.y1, cb.y1)
        elif abs(ca.y1 - cb.y0) <= eps:                 # horizontal, ca south
            axis = "H"; coord = ca.y1
            s, t = max(ca.x0, cb.x0), min(ca.x1, cb.x1)
        elif abs(ca.y0 - cb.y1) <= eps:                 # horizontal, ca north
            axis = "H"; coord = ca.y0
            s, t = max(ca.x0, cb.x0), min(ca.x1, cb.x1)
        else:
            intervals.append({"edge": e, "axis": None})
            continue
        intervals.append({
            "edge": e, "axis": axis, "coord": round(coord, 4),
            "s": s, "t": t,
            "pair": frozenset((e.room_a, e.room_b)),
            "wall": e.wall,
        })
    # Group by (pair, axis, coord, wall) and merge touching intervals.
    groups = {}
    leftovers = []
    for it in intervals:
        if it["axis"] is None:
            leftovers.append(it["edge"])
            continue
        key = (it["pair"], it["axis"], it["coord"], it["wall"])
        groups.setdefault(key, []).append(it)
    out = leftovers[:]
    from model import Rect as _Rect
    for key, items in groups.items():
        items.sort(key=lambda x: x["s"])
        merged = [items[0]]
        for it in items[1:]:
            last = merged[-1]
            if it["s"] <= last["t"] + eps:                # touch or overlap
                last["t"] = max(last["t"], it["t"])
            else:
                merged.append(it)
        # For each merged interval, build a representative edge using the
        # original first item's edge as a template, but with cell rects
        # spanning the merged span.
        for m in merged:
            template = m["edge"]
            if m["axis"] == "V":
                # vertical wall at x=coord; cells flank it
                # If template's cell_a is west: ca.x1==coord; spans s..t in y
                ca, cb = template.cell_a, template.cell_b
                if abs(ca.x1 - m["coord"]) <= eps:        # ca west of boundary
                    new_a = _Rect(ca.x0, m["s"], ca.x1, m["t"])
                    new_b = _Rect(cb.x0, m["s"], cb.x1, m["t"])
                else:                                       # ca east of boundary
                    new_a = _Rect(ca.x0, m["s"], ca.x1, m["t"])
                    new_b = _Rect(cb.x0, m["s"], cb.x1, m["t"])
            else:                                            # horizontal
                ca, cb = template.cell_a, template.cell_b
                if abs(ca.y1 - m["coord"]) <= eps:        # ca south of boundary
                    new_a = _Rect(m["s"], ca.y0, m["t"], ca.y1)
                    new_b = _Rect(m["s"], cb.y0, m["t"], cb.y1)
                else:                                       # ca north
                    new_a = _Rect(m["s"], ca.y0, m["t"], ca.y1)
                    new_b = _Rect(m["s"], cb.y0, m["t"], cb.y1)
            from architectural_plan import OpenPlanEdge
            out.append(OpenPlanEdge(
                room_a=template.room_a, room_b=template.room_b,
                wall=template.wall, cell_a=new_a, cell_b=new_b))
    return out


def _open_plan_edge_endpoints(edge):
    """Return the (x, y) endpoints of an open-plan edge's shared line."""
    eps = 1e-3
    ca = getattr(edge, "cell_a", None)
    cb = getattr(edge, "cell_b", None)
    if ca is None or cb is None:
        return set()
    if abs(ca.x1 - cb.x0) <= eps:
        x = ca.x1
        lo_y = max(ca.y0, cb.y0); hi_y = min(ca.y1, cb.y1)
        return {(x, lo_y), (x, hi_y)}
    if abs(ca.x0 - cb.x1) <= eps:
        x = ca.x0
        lo_y = max(ca.y0, cb.y0); hi_y = min(ca.y1, cb.y1)
        return {(x, lo_y), (x, hi_y)}
    if abs(ca.y1 - cb.y0) <= eps:
        y = ca.y1
        lo_x = max(ca.x0, cb.x0); hi_x = min(ca.x1, cb.x1)
        return {(lo_x, y), (hi_x, y)}
    if abs(ca.y0 - cb.y1) <= eps:
        y = ca.y0
        lo_x = max(ca.x0, cb.x0); hi_x = min(ca.x1, cb.x1)
        return {(lo_x, y), (hi_x, y)}
    return set()


def _collect_open_plan_endpoints(edges):
    """Union of endpoints from every open-plan edge in the plan."""
    out = set()
    for e in edges:
        out |= _open_plan_edge_endpoints(e)
    return out


def _open_plan_svg(edge, layout, other_endpoints=None) -> str:
    """Erase the shared wall stroke between two open-plan rooms — the entire
    shared segment is overdrawn in white.

    The erase is INSET at each end by half the exterior wall thickness so it
    stops at the inner face of whatever perpendicular wall meets the shared
    edge, instead of cutting into that wall's geometry. (Walls are centred
    on the room boundary, so a perpendicular wall extends thickness/2 past
    the shared-edge endpoint into the open-plan span; without the inset, the
    white erase line would chop a notch out of that wall.) The room stroke
    in the small un-erased segment at each corner is hidden under the
    perpendicular wall's fill, so the visible result is a clean opening
    between the rooms.

    Works on whatever specific cells are recorded on the edge (cell_a /
    cell_b) when present — that handles L-shape composite rooms whose
    alcove abuts an open-plan neighbour. Falls back to the rooms' primary
    rects when the edge predates cell tracking.

    `other_endpoints`: optional set of (x, y) tuples — endpoints of every
    OTHER open-plan edge in the plan. When this edge's endpoint matches one
    of those (i.e., two open-plan boundaries meet at a corner), the inset
    on that end is suppressed — there is no perpendicular wall to avoid,
    only another open-plan transition, so erasing all the way to the corner
    sweeps up any stray room-stroke fragments at the intersection."""
    rooms_by_id = {r.id: r for r in layout.rooms}
    a = rooms_by_id.get(edge.room_a)
    b = rooms_by_id.get(edge.room_b)
    if a is None or b is None:
        return ""
    ra = getattr(edge, "cell_a", None) or a.rect
    rb = getattr(edge, "cell_b", None) or b.rect
    eps = 1e-3
    # Inset matches half the INTERIOR wall thickness. Interior walls (0.10 m
    # thick, centered on the boundary) extend 0.05 m past the open-plan edge
    # endpoint into the open span, so a 0.05 m inset stops the erase exactly
    # at the wall's open-plan-side face — no chop. The previous 0.10 m inset
    # (half EXTERIOR thickness) over-reserved by 0.05 m and left visible
    # stroke fragments at corners where only one open-plan edge ends. Open-
    # plan boundaries touching exterior walls are rare in this catalog —
    # if a future topology needs that, switch back to per-wall thickness
    # detection.
    inset = WALL_THICKNESS_INTERIOR / 2.0       # 0.05 m
    others = other_endpoints or set()

    def _has_other_at(point):
        for ox, oy in others:
            if abs(ox - point[0]) <= eps and abs(oy - point[1]) <= eps:
                return True
        return False

    if abs(ra.x1 - rb.x0) <= eps:           # vertical wall (a west of b)
        x = ra.x1
        lo_y = max(ra.y0, rb.y0)
        hi_y = min(ra.y1, rb.y1)
        y0 = lo_y if _has_other_at((x, lo_y)) else lo_y + inset
        y1 = hi_y if _has_other_at((x, hi_y)) else hi_y - inset
        if y1 - y0 <= eps:
            return ""
        p1, p2 = (x, y0), (x, y1)
    elif abs(ra.x0 - rb.x1) <= eps:         # vertical wall (a east of b)
        x = ra.x0
        lo_y = max(ra.y0, rb.y0)
        hi_y = min(ra.y1, rb.y1)
        y0 = lo_y if _has_other_at((x, lo_y)) else lo_y + inset
        y1 = hi_y if _has_other_at((x, hi_y)) else hi_y - inset
        if y1 - y0 <= eps:
            return ""
        p1, p2 = (x, y0), (x, y1)
    elif abs(ra.y1 - rb.y0) <= eps:         # horizontal wall (a south of b)
        y = ra.y1
        lo_x = max(ra.x0, rb.x0)
        hi_x = min(ra.x1, rb.x1)
        x0 = lo_x if _has_other_at((lo_x, y)) else lo_x + inset
        x1 = hi_x if _has_other_at((hi_x, y)) else hi_x - inset
        if x1 - x0 <= eps:
            return ""
        p1, p2 = (x0, y), (x1, y)
    elif abs(ra.y0 - rb.y1) <= eps:         # horizontal wall (a north of b)
        y = ra.y0
        lo_x = max(ra.x0, rb.x0)
        hi_x = min(ra.x1, rb.x1)
        x0 = lo_x if _has_other_at((lo_x, y)) else lo_x + inset
        x1 = hi_x if _has_other_at((hi_x, y)) else hi_x - inset
        if x1 - x0 <= eps:
            return ""
        p1, p2 = (x0, y), (x1, y)
    else:
        return ""
    lot = layout.lot
    p1s = _to_svg_xy(lot, *p1)
    p2s = _to_svg_xy(lot, *p2)
    # Cover the overlapping 1.5 px room strokes at the boundary using each
    # ROOM's fill on its own side, so the open-plan transition reads as a
    # continuation of colour rather than a white slot. `_open_plan_svg`'s
    # `edge.wall` is relative to room_a, same convention as for doors.
    return _two_color_opening_erase(
        p1s[0], p1s[1], p2s[0], p2s[1], edge.wall, _fill(a), _fill(b))


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
    # Compute open-plan edges + endpoints up front so the corner-cap pass
    # can suppress caps at points that sit on the open-plan boundary
    # (otherwise the cap's notch quadrant paints a dark dot inside the LDK
    # opening). Endpoints are also used later by the open-plan erase pass
    # to drop the wall-clearance inset where two open-plan edges meet.
    merged_open_edges = _merge_open_plan_edges(plan.open_plan_edges)
    all_endpoints = _collect_open_plan_endpoints(merged_open_edges)
    # A point is "shared" if it appears as an endpoint of TWO OR MORE
    # open-plan edges. Set subtraction (all_endpoints - my_eps) can't tell
    # us this because sets dedupe; use a counter and pre-compute the set
    # of shared corners. At shared corners the erase inset is suppressed
    # so the two erases meet cleanly with no un-erased gap between them.
    from collections import Counter as _Counter
    _ep_counts = _Counter()
    for _e in merged_open_edges:
        for _ep in _open_plan_edge_endpoints(_e):
            _ep_counts[_ep] += 1
    shared_endpoints = {_ep for _ep, _c in _ep_counts.items() if _c >= 2}
    # Walls first — they cover room strokes for every non-open-plan boundary.
    walls = _compute_walls(plan)
    for wall in walls:
        overlays.append(_wall_svg(wall, plan.layout))
    # Corner caps: small filled squares at corners that leave a notch
    # (mixed-thickness joints, or convex same-thickness L-corners). Inside
    # corners of L-shape composites (concave) skip the cap to avoid painting
    # a dark dot inside the room. Also skip at any open-plan-edge endpoint
    # so the cap's notch quadrant doesn't paint a dark dot inside the open
    # LDK transition.
    for cap in _corner_caps(walls, plan.layout.rooms,
                            open_plan_endpoints=all_endpoints):
        overlays.append(_wall_svg(cap, plan.layout))
    # Open-plan: erase room strokes where there's no wall. Merge adjacent
    # cell-level edges of the same room pair first so that a composite L's
    # cell boundary doesn't leave a 0.2 m unerased gap at the inset seam.
    # Collect every endpoint across all open-plan edges so when two edges
    # meet at a corner, neither one insets — the erase sweeps fully through
    # the corner, removing the cell-stroke fragment at the L of the
    # boundary.
    for ope in merged_open_edges:
        # Suppress the inset at any of this edge's endpoints that is SHARED
        # with another open-plan edge (count >= 2). Set subtraction is wrong
        # here: it loses count info, so a genuinely shared endpoint (in 2+
        # edges including this one) gets removed by `all - my_eps` and looks
        # un-shared. Passing the pre-computed shared_endpoints set fixes that.
        overlays.append(_open_plan_svg(ope, plan.layout,
                                       other_endpoints=shared_endpoints))
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
