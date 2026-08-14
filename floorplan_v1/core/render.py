"""SVG renderer + HTML gallery for generated layouts.

Front (street) is drawn at the BOTTOM. Rooms are coloured by zone; uncovered
setback elements are drawn dashed. Dimensions and areas are labelled.

Two top-level entry points:
  - layout_to_svg(layout)         — raw layout (filled rooms + ruler only)
  - archplan_to_svg(plan)         — adds doors + windows from an ArchPlan
"""
import html
import bisect
import math
import re
from typing import List, Optional
from model import Layout, Rect, make_outside_probe

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
    "lanai": "LANAI",
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


# Bath-type rooms that can be a solver-pinned notch room (see
# Room.notch_pin_of) — these get FULL partition walls against the stair's
# legs (Pass D in _compute_walls), unlike a non-bath room absorbing the
# same notch as an open alcove via claim_stair_notch (thin rail instead —
# see _notch_alcove_rail_svg).
_NOTCH_BATH_TYPES = ("common_bath", "ensuite_bath", "bath_toilet", "powder_room")


def _fill(room) -> str:
    if room.type in _NOTCH_BATH_TYPES:
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

    # footprint rooms (may be composite / L-shaped -> draw each cell, label once).
    # A notch-pinned room's rect deliberately overlaps its stair's own rect
    # (see Room.notch_pin_of / Topology.notch_powder_room_id and
    # solver/snap_gaps.py::claim_stair_notch) — draw it LAST (stable sort)
    # so its fill/label/stroke sit on top of the stair's, instead of the
    # stair's own fill silently painting over it.
    rooms_ordered = sorted(
        layout.rooms, key=lambda r: 1 if getattr(r, "notch_pin_of", None) else 0)
    for r in rooms_ordered:
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
        # Stairs: draw the tread lines + UP/DN travel arrow instead of the
        # generic centered label (the arrow direction comes from the solver's
        # ascent decision, stored on room.stair_up). Non-straight stair
        # types (l_landing, etc.) get their own turn glyph instead, keyed
        # off room.stair_type — see solver/topology.py RoomSpec.stair_type.
        if r.type == "stairs" and getattr(r, "stair_type", "straight") == "l_landing":
            s.append(_l_landing_glyph(lot, r))
            continue
        if r.type == "stairs" and getattr(r, "stair_up", None):
            s.append(_stair_glyph(lot, r))
            continue
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


def _stair_glyph(lot, room) -> str:
    """Stair symbol for a type=='stairs' room: light tread lines across the
    run plus a bold travel-direction arrow — 'UP' on the ground floor,
    'DN' on upper floors (there you step off the opening and descend). The
    ascent vector room.stair_up points from the flight's bottom to its top;
    the arrow uses it directly on the ground floor and reversed above."""
    up = getattr(room, "stair_up", None)
    if not up:
        return ""
    dx, dy = up
    rect = room.rect
    vertical = abs(dy) > abs(dx)
    out = []
    # Tread lines perpendicular to the run, ~0.28 m apart (tread depth).
    TREAD_M = 0.28
    n = max(2, int(round((rect.h if vertical else rect.w) / TREAD_M)))
    for i in range(1, n):
        if vertical:
            yy = rect.y0 + i * rect.h / n
            xa, ya = _to_svg_xy(lot, rect.x0, yy)
            xb, _ = _to_svg_xy(lot, rect.x1, yy)
            out.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" '
                       f'y2="{ya:.1f}" stroke="#9a9a9a" stroke-width="0.6"/>')
        else:
            xx = rect.x0 + i * rect.w / n
            xa, ya = _to_svg_xy(lot, xx, rect.y0)
            _, yb = _to_svg_xy(lot, xx, rect.y1)
            out.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xa:.1f}" '
                       f'y2="{yb:.1f}" stroke="#9a9a9a" stroke-width="0.6"/>')
    # Travel direction: ascend on the ground floor, descend on upper floors.
    descend = room.storey > 1
    ddx, ddy = (-dx, -dy) if descend else (dx, dy)
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    half = (rect.h if vertical else rect.w) / 2
    L = half - min(0.45, half * 0.30)          # inset the arrow from both ends
    tx, ty = _to_svg_xy(lot, cx - ddx * L, cy - ddy * L)   # tail
    hx, hy = _to_svg_xy(lot, cx + ddx * L, cy + ddy * L)   # head
    out.append(f'<line x1="{tx:.1f}" y1="{ty:.1f}" x2="{hx:.1f}" y2="{hy:.1f}" '
               f'stroke="#333" stroke-width="2" stroke-linecap="round"/>')
    ang = math.atan2(hy - ty, hx - tx)          # arrowhead barbs at the head
    for da in (math.radians(148), math.radians(-148)):
        bx, by = hx + 7.0 * math.cos(ang + da), hy + 7.0 * math.sin(ang + da)
        out.append(f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{bx:.1f}" '
                   f'y2="{by:.1f}" stroke="#333" stroke-width="2" '
                   f'stroke-linecap="round"/>')
    # UP / DN label just past the tail (halo so it reads over the treads).
    seg = math.hypot(hx - tx, hy - ty) or 1.0
    ux, uy = (hx - tx) / seg, (hy - ty) / seg   # unit vector tail -> head
    lx, ly = tx - ux * 9.0, ty - uy * 9.0       # 9 px beyond the tail
    out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
               f'dominant-baseline="middle" font-family="Arial" font-size="9" '
               f'font-weight="bold" fill="#333" stroke="white" '
               f'stroke-width="2.5" paint-order="stroke">{("DN" if descend else "UP")}</text>')
    return "".join(out)


def _tread_lines_svg(lot, x0, y0, x1, y1, vertical) -> str:
    """Light tread lines across a rectangular stair leg, perpendicular to
    the direction of travel (vertical=True means treads stack top-to-bottom
    i.e. travel is along y; False means travel is along x). Shared helper
    for both the straight-stair glyph and the turning-stair leg strips."""
    out = []
    TREAD_M = 0.28
    n = max(2, int(round((y1 - y0 if vertical else x1 - x0) / TREAD_M)))
    for i in range(1, n):
        if vertical:
            yy = y0 + i * (y1 - y0) / n
            xa, ya = _to_svg_xy(lot, x0, yy)
            xb, _ = _to_svg_xy(lot, x1, yy)
            out.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" '
                       f'y2="{ya:.1f}" stroke="#9a9a9a" stroke-width="0.6"/>')
        else:
            xx = x0 + i * (x1 - x0) / n
            xa, ya = _to_svg_xy(lot, xx, y0)
            _, yb = _to_svg_xy(lot, xx, y1)
            out.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xa:.1f}" '
                       f'y2="{yb:.1f}" stroke="#9a9a9a" stroke-width="0.6"/>')
    return "".join(out)


def _l_landing_glyph(lot, room) -> str:
    """L-shaped stair with a quarter landing: leg 1 runs from the boarding
    wall to a square landing in the corner, leg 2 continues perpendicular
    from the landing to the arrival wall. Unlike the straight stair's
    solver-chosen stair_up, a turning stair's entry/exit walls are author-
    declared (room.stair_board_wall / stair_arrive_wall — see
    Adjacency.stair_wall) since they aren't a single solver-chosen ascent
    axis. Falls back to the plain straight glyph if either wall is unset
    (shouldn't happen for a properly-authored l_landing stair). Geometry
    (leg1/leg2/landing/notch) comes from the shared core.model.l_landing_cells
    helper — also used by the solver's notch-derivation/claim logic, so the
    render always matches what was actually reserved or reclaimed."""
    from model import l_landing_cells
    board = getattr(room, "stair_board_wall", None)
    arrive = getattr(room, "stair_arrive_wall", None)
    cells = l_landing_cells(room.rect, board, arrive)
    if cells is None:
        return _stair_glyph(lot, room)
    leg1, leg2, landing = cells["leg1"], cells["leg2"], cells["landing"]
    board_travels_y = board in ("N", "S")
    out = [
        _tread_lines_svg(lot, leg1.x0, leg1.y0, leg1.x1, leg1.y1, board_travels_y),
        _tread_lines_svg(lot, leg2.x0, leg2.y0, leg2.x1, leg2.y1, not board_travels_y),
    ]
    arrow_from = ((leg1.x0 + leg1.x1) / 2, (leg1.y0 + leg1.y1) / 2)
    arrow_bend = ((landing.x0 + landing.x1) / 2, (landing.y0 + landing.y1) / 2)
    arrow_to = ((leg2.x0 + leg2.x1) / 2, (leg2.y0 + leg2.y1) / 2)
    # Landing outline — a plain square, no tread lines (it's a flat platform).
    p0 = _to_svg_xy(lot, landing.x0, landing.y0)
    p1 = _to_svg_xy(lot, landing.x1, landing.y1)
    lxs0, lxs1 = sorted((p0[0], p1[0]))
    lys0, lys1 = sorted((p0[1], p1[1]))
    out.append(f'<rect x="{lxs0:.1f}" y="{lys0:.1f}" width="{lxs1-lxs0:.1f}" '
               f'height="{lys1-lys0:.1f}" fill="none" stroke="#9a9a9a" '
               f'stroke-width="0.8"/>')
    # Travel arrow: leg1 midpoint -> landing -> leg2 midpoint, bent through
    # the landing (an L-shaped path following the actual walking line)
    # instead of a single diagonal cutting across the turn. Reversed on
    # upper floors (descending) same as the straight glyph.
    descend = room.storey > 1
    pts = [arrow_from, arrow_bend, arrow_to]
    if descend:
        pts = list(reversed(pts))
    svg_pts = [_to_svg_xy(lot, *p) for p in pts]
    path_d = " ".join(
        f'{"M" if i == 0 else "L"} {x:.1f} {y:.1f}'
        for i, (x, y) in enumerate(svg_pts))
    out.append(f'<path d="{path_d}" fill="none" stroke="#333" '
               f'stroke-width="2" stroke-linecap="round" '
               f'stroke-linejoin="round"/>')
    (ax, ay), (bx, by) = svg_pts[-2], svg_pts[-1]
    ang = math.atan2(by - ay, bx - ax)
    for da in (math.radians(148), math.radians(-148)):
        hx, hy = bx + 7.0 * math.cos(ang + da), by + 7.0 * math.sin(ang + da)
        out.append(f'<line x1="{bx:.1f}" y1="{by:.1f}" x2="{hx:.1f}" '
                   f'y2="{hy:.1f}" stroke="#333" stroke-width="2" '
                   f'stroke-linecap="round"/>')
    label = "DN" if descend else "UP"
    (tx, ty) = svg_pts[0]
    (nx, ny) = svg_pts[1]
    seg = math.hypot(nx - tx, ny - ty) or 1.0
    ux, uy = (nx - tx) / seg, (ny - ty) / seg
    lx_, ly_ = tx - ux * 9.0, ty - uy * 9.0
    out.append(f'<text x="{lx_:.1f}" y="{ly_:.1f}" text-anchor="middle" '
               f'dominant-baseline="middle" font-family="Arial" font-size="9" '
               f'font-weight="bold" fill="#333" stroke="white" '
               f'stroke-width="2.5" paint-order="stroke">{label}</text>')
    return "".join(out)


def _opp_side(side: str) -> str:
    return {"N": "S", "S": "N", "E": "W", "W": "E"}[side]


# Lot/exterior fill — matches the lot rectangle drawn by layout_to_svg, used
# whenever an opening's "other side" is outside the building.
LOT_FILL = "#fbfbf7"

# Half-thickness of the colored erase strip used to clear the wall + room
# strokes at an opening. 5 svg-px covers the worst-case 0.20 m exterior wall
# (8.4 px) and the room stroke (1.5 px) when applied on each side of the wall.
ERASE_HALF_PX = 5


# Door-emphasis colour, used ONLY when archplan_to_svg(door_emphasis=True).
# See that function's docstring for why this exists and why it is opt-in.
#
# This was a saturated magenta, on the reasoning that the marking had to be
# unmissable. It was — and the image model copied it straight into its output,
# so every render came back with bright pink doors. Telling it not to did not
# work: the generated prompt said "No magenta or pink anywhere in your output"
# and it produced pink doors anyway, which is the standing finding that this
# model follows the picture and ignores prohibitions.
#
# The emphasis never needed colour. It also triples the line WEIGHT (2.2-3.4 px
# against thin grey arcs), and that is what actually makes a 0.7 m door tucked
# into a corner findable at raster scale. So the marker is now near-black: still
# unmissable in the source, and indistinguishable from correct architectural
# linework if the model copies it, which it will.
_DOOR_HL = "#1a1a1a"


def _door_svg(door, layout, emphasis: bool = False) -> str:
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
    if emphasis:
        # A 0.7 m door tucked 0.15 m into a corner, drawn as a thin grey arc
        # beside a window, is genuinely hard to SEE at the raster scale the
        # image model receives — and across four runs the model followed the
        # image far more reliably than the prose. So make the opening
        # unmissable rather than describing it harder.
        parts.append(
            f'<path d="M {txs:.1f} {tys:.1f} A {radius:.1f} {radius:.1f} 0 0 '
            f'{sweep} {lxs:.1f} {lys:.1f}" fill="none" stroke="{_DOOR_HL}" '
            f'stroke-width="2.2" opacity="0.9"/>')
        parts.append(
            f'<line x1="{hxs:.1f}" y1="{hys:.1f}" x2="{txs:.1f}" y2="{tys:.1f}" '
            f'stroke="{_DOOR_HL}" stroke-width="3.0"/>')
        # The opening itself, marked across the wall line.
        parts.append(
            f'<line x1="{nxs:.1f}" y1="{nys:.1f}" x2="{fxs:.1f}" y2="{fys:.1f}" '
            f'stroke="{_DOOR_HL}" stroke-width="3.4" opacity="0.85"/>')
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
    # An L-shaped room's window may sit on its alcove cell, not its main
    # rect — position_m is measured along THAT cell's wall.
    cells = room.cells
    idx = min(getattr(window, "cell_index", 0), len(cells) - 1)
    rect, wall, pos, w = cells[idx], window.wall, window.position_m, window.width_m

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

# Stair rail: the boarding/arrival open-plan edge (stairs <-> its GF/2F
# circulation neighbor) is otherwise fully invisible like an LDK seam. A
# thin rail line marks the run's flanking side, with a gap this wide left
# at the correct end so the actual entrance (where you step on/off the
# flight) reads clearly. See _stair_rail_svg.
STAIR_OPENING_M = 0.9

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
    # An uncovered side is EXTERIOR when the empty space it faces REACHES
    # THE OUTSIDE — either because the wall sits on the envelope boundary,
    # or because the unowned region beyond it connects to that boundary.
    #
    # The second case matters because the building footprint is the union of
    # room cells, NOT the envelope rectangle (Layout.footprint_area already
    # sums room areas, so occupancy math has always agreed). A perimeter
    # strip that no room claims is therefore OUTSIDE the building, and the
    # wall facing it is a real exterior wall — the footprint is simply not
    # rectangular there. Before 2026-08-05 this was tested as "does the wall
    # coordinate lie on the envelope edge", which drew such walls at
    # interior thickness and made the outline read as a missing wall (seen
    # on a 20x20 solve of 1s_2br_sq_side_split_bath_ld, where the bedroom's
    # south face sat 0.52 m inside the envelope behind an unclaimed strip).
    #
    # A gap fully ENCLOSED by rooms is a different thing — a courtyard or
    # light well — and keeps INTERIOR thickness, so walls bounding a small
    # inter-room gap still look consistent with their neighbours (e.g. T&B
    # south wall east of hall when rear-band rooms differ slightly in depth).
    void_rects_only = [vr for _vid, vr, _c in voids]

    # Same probe the architectural plan uses, so wall weight, windows and
    # exterior doors cannot disagree about which walls face the lot.
    _occ = [oc for (_or, oc) in all_cells] + void_rects_only
    _probe = make_outside_probe(env, _occ)

    def _faces_outside(side, coord, s_, e_):
        """True when the empty space just beyond this wall segment reaches
        the lot exterior (so the segment is part of the building outline)."""
        mid = (s_ + e_) / 2.0
        step = env_eps * 10
        if side == "N":   px, py = mid, coord + step
        elif side == "S": px, py = mid, coord - step
        elif side == "E": px, py = coord + step, mid
        else:             px, py = coord - step, mid
        return _probe(px, py)

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
                for s_, e_ in uncovered:
                    thickness = (WALL_THICKNESS_EXTERIOR
                                 if _faces_outside(side, coord, s_, e_)
                                 else WALL_THICKNESS_INTERIOR)
                    walls.append(_wall_rect(side, coord, s_, e_, thickness))

    # Pass D — notch-pinned BATH rooms: partition walls against the stair's
    # own leg1/leg2 (see core.model.l_landing_cells). The room and its stair
    # are exempted from Passes A/B's shared-edge detection since their rects
    # deliberately overlap (Room.notch_pin_of), so no wall is ever
    # synthesized between them there. A bath needs real privacy walls here
    # (unlike a non-bath room absorbing the same notch as an open alcove via
    # claim_stair_notch, which gets a thin balustrade rail instead — see
    # _notch_alcove_rail_svg).
    from model import l_landing_cells
    rooms_by_id = {r.id: r for r in rooms}
    for r in rooms:
        if r.type not in _NOTCH_BATH_TYPES:
            continue
        stair = rooms_by_id.get(getattr(r, "notch_pin_of", None))
        if stair is None:
            continue
        cells_ll = l_landing_cells(stair.rect, stair.stair_board_wall,
                                   stair.stair_arrive_wall)
        if cells_ll is None:
            continue
        for leg in (cells_ll["leg1"], cells_ll["leg2"]):
            edge = _wall_shared_edge(r.rect, leg)
            if edge is None:
                continue
            side, coord, start, end = edge
            walls.append(_wall_rect(side, coord, start, end,
                                    WALL_THICKNESS_INTERIOR))

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


_BALUSTRADE_STYLE = 'stroke="#666" stroke-width="1.2"'


def _notch_alcove_rail_svg(room, layout) -> str:
    """Balustrade for a non-bath room that absorbed an L-landing stair's
    notch as an open alcove (claim_stair_notch, solver/snap_gaps.py) —
    marks the two edges where the new alcove floor meets the stair's
    remaining void (leg1 and leg2) with a thin rail, same as a real
    stairwell guard-rail. The alcove's other two sides need nothing: one is
    internal to the claiming room (rect + rect2, no seam drawn at all) and
    the other already gets a normal wall from Pass A against whatever room
    is on its far side."""
    from model import l_landing_cells
    stair = next((r for r in layout.rooms if r.id == room.notch_pin_of), None)
    if stair is None or room.rect2 is None:
        return ""
    cells = l_landing_cells(stair.rect, stair.stair_board_wall,
                            stair.stair_arrive_wall)
    if cells is None:
        return ""
    out = []
    for leg in (cells["leg1"], cells["leg2"]):
        edge = _wall_shared_edge(room.rect2, leg)
        if edge is None:
            continue
        side, coord, start, end = edge
        if side in ("N", "S"):
            p1, p2 = (start, coord), (end, coord)
        else:
            p1, p2 = (coord, start), (coord, end)
        p1s = _to_svg_xy(layout.lot, *p1)
        p2s = _to_svg_xy(layout.lot, *p2)
        out.append(f'<line x1="{p1s[0]:.1f}" y1="{p1s[1]:.1f}" x2="{p2s[0]:.1f}" '
                   f'y2="{p2s[1]:.1f}" {_BALUSTRADE_STYLE} stroke-linecap="butt"/>')
    return "".join(out)


def _stair_rail_svg(edge, layout) -> str:
    """For a stair boarding/arrival open-plan edge, draw a thin rail line
    along the shared boundary instead of leaving it fully invisible, with
    a gap at the correct end of the run marking the actual entrance —
    where a person steps on/off the flight.

    Ground floor (the stairs room's storey == 1, boarding): the gap sits
    at the LOW end of the run (opposite room.stair_up) — you step onto the
    first tread there and ascend away from it. Upper floor (storey > 1,
    arrival): the gap sits at the HIGH end (in the stair_up direction) —
    ascent finishes there and you step off onto the upper circulation.

    No-ops (returns "") when neither room is a stairs room, or when this
    particular edge runs PERPENDICULAR to the flight (an end-cap boundary
    at the run's short end) — that edge already IS the entrance in full,
    same as today's fully-open rendering."""
    rooms_by_id = {r.id: r for r in layout.rooms}
    a = rooms_by_id.get(edge.room_a)
    b = rooms_by_id.get(edge.room_b)
    if a is None or b is None:
        return ""
    stair_room = a if a.type == "stairs" else (b if b.type == "stairs" else None)
    if stair_room is None:
        return ""
    if getattr(stair_room, "stair_type", "straight") != "straight":
        # Turning stairs (l_landing, etc.) have no single "run axis" this
        # straight-only heuristic applies to, and their board/arrival walls
        # ARE the true walk-through entrance in full (unlike a straight run,
        # where only PART of the shared wall is the entrance) — leave fully
        # open, same as any other open-plan edge. The notch portion of this
        # same wall (if any) gets its own treatment separately: a solver-
        # pinned bath gets a real wall (Pass D, _compute_walls), and a
        # claimed alcove gets its own balustrade (_notch_alcove_rail_svg).
        return ""
    up = getattr(stair_room, "stair_up", None)
    if not up:
        return ""
    dx, dy = up
    vertical_run = abs(dy) > abs(dx)
    ra = getattr(edge, "cell_a", None) or a.rect
    rb = getattr(edge, "cell_b", None) or b.rect
    eps = 1e-3

    if abs(ra.x1 - rb.x0) <= eps or abs(ra.x0 - rb.x1) <= eps:
        edge_vertical = True
        x = ra.x1 if abs(ra.x1 - rb.x0) <= eps else ra.x0
        lo, hi = max(ra.y0, rb.y0), min(ra.y1, rb.y1)
    elif abs(ra.y1 - rb.y0) <= eps or abs(ra.y0 - rb.y1) <= eps:
        edge_vertical = False
        y = ra.y1 if abs(ra.y1 - rb.y0) <= eps else ra.y0
        lo, hi = max(ra.x0, rb.x0), min(ra.x1, rb.x1)
    else:
        return ""
    if hi - lo <= eps or edge_vertical != vertical_run:
        return ""   # degenerate, or a perpendicular end-cap — leave fully open

    boarding = stair_room.storey == 1
    rect = stair_room.rect
    if vertical_run:
        entrance = rect.y0 if (dy > 0) == boarding else rect.y1
    else:
        entrance = rect.x0 if (dx > 0) == boarding else rect.x1
    # Anchor the gap at whichever end of the ACTUAL overlap [lo, hi] is
    # nearer the true entrance coordinate (the flanking neighbor may not
    # reach all the way to the stair room's own end — the solver only
    # requires it come within STAIR_END_ZONE_U of it).
    near_lo = abs(entrance - lo) <= abs(entrance - hi)
    if near_lo:
        rail_lo, rail_hi = min(hi, lo + STAIR_OPENING_M), hi
    else:
        rail_lo, rail_hi = lo, max(lo, hi - STAIR_OPENING_M)
    if rail_hi - rail_lo <= eps:
        return ""   # the gap covers the whole overlap — nothing to rail
    # Inset the far end (a true perpendicular-wall corner) by the same
    # amount _open_plan_svg uses, so the rail doesn't poke into that wall.
    inset = WALL_THICKNESS_INTERIOR / 2.0
    if near_lo:
        rail_hi -= inset
    else:
        rail_lo += inset
    if rail_hi - rail_lo <= eps:
        return ""
    if edge_vertical:
        p1, p2 = (x, rail_lo), (x, rail_hi)
    else:
        p1, p2 = (rail_lo, y), (rail_hi, y)
    p1s = _to_svg_xy(layout.lot, *p1)
    p2s = _to_svg_xy(layout.lot, *p2)
    return (f'<line x1="{p1s[0]:.1f}" y1="{p1s[1]:.1f}" x2="{p2s[0]:.1f}" '
            f'y2="{p2s[1]:.1f}" stroke="{WALL_FILL}" stroke-width="2" '
            f'stroke-linecap="butt"/>')


def _counter_svg(ctr, layout) -> str:
    """Dining counter (breakfast bar) on an open-plan kitchen edge: a 0.6 m
    millwork band inside the kitchen along the shared boundary, plus stool
    circles on the living side. Drawn fixture-weight (thin stroke, light
    fill) so it reads as cabinetry, not a wall — the open-plan erase
    underneath stays visible at the walk-through gap."""
    lot = layout.lot
    d = ctr.depth_m
    s0, s1 = ctr.start_m, ctr.start_m + ctr.length_m
    mid = (s0 + s1) / 2.0
    # `inward` = unit direction from the shared edge INTO the band-host room
    # (the wall letter is the side of the host room the edge sits on).
    inward = {"S": +1, "N": -1, "W": +1, "E": -1}[ctr.wall]
    # Stools sit across the seam in the facing room (default), or inside the
    # host room beyond the band (stools_with_band — living room hosts both).
    if getattr(ctr, "stools_with_band", False):
        stool_off = ctr.coord + (d + 0.25) * inward
    else:
        stool_off = ctr.coord - 0.25 * inward
    if ctr.wall in ("N", "S"):
        x0, x1 = s0, s1
        y0, y1 = sorted((ctr.coord, ctr.coord + d * inward))
        stool_pts = [(mid - 0.35, stool_off), (mid + 0.35, stool_off)]
    else:
        y0, y1 = s0, s1
        x0, x1 = sorted((ctr.coord, ctr.coord + d * inward))
        stool_pts = [(stool_off, mid - 0.35), (stool_off, mid + 0.35)]
    px = MARGIN + x0 * SCALE
    py = _y(lot, y1)
    w = (x1 - x0) * SCALE
    h = (y1 - y0) * SCALE
    parts = [f'<rect x="{px:.1f}" y="{py:.1f}" width="{w:.1f}" height="{h:.1f}" '
             f'fill="#e9e2d4" stroke="#7a6a52" stroke-width="1"/>']
    r_px = 0.175 * SCALE
    for sx, sy in stool_pts[:ctr.stools]:
        cx = MARGIN + sx * SCALE
        cy = _y(lot, sy)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r_px:.1f}" '
                     f'fill="#ffffff" stroke="#7a6a52" stroke-width="1"/>')
    return "".join(parts)


def archplan_to_svg(plan, door_emphasis: bool = False) -> str:
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

    `door_emphasis` overdraws every door in heavy near-black line work (see
    _DOOR_HL — it was a saturated magenta until the model started reproducing
    the magenta). It exists for
    ONE consumer — polish.py, which hands the drawing to an image model that
    kept dropping the kitchen's exterior service door and relocating the T&B
    door across four attempts. Default False, so the technical drawing and all
    52 baselines are untouched; this is a communication aid, never the plan of
    record.
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
        overlays.append(_stair_rail_svg(ope, plan.layout))
    # Balustrade for a non-bath room that absorbed an L-landing stair's
    # notch as an open alcove (claim_stair_notch) — the bath case gets real
    # walls instead, from Pass D in _compute_walls.
    for r in plan.layout.rooms:
        if getattr(r, "notch_pin_of", None) and r.type not in _NOTCH_BATH_TYPES:
            overlays.append(_notch_alcove_rail_svg(r, plan.layout))
    # Doors and windows punch openings through walls.
    for d in plan.doors:
        overlays.append(_door_svg(d, plan.layout, emphasis=door_emphasis))
    for w in plan.windows:
        overlays.append(_window_svg(w, plan.layout))
    # Dining counters (counter_divider adjacencies) — drawn last so the
    # millwork band and stools sit on top of the open-plan erase.
    for c in getattr(plan, "counters", []):
        overlays.append(_counter_svg(c, plan.layout))
    inject = "".join(overlays)
    return base.replace("</svg>", inject + "</svg>")


_FLOOR_TITLE_BAND_PX = 34    # vertical space above each floor plan for its title
_FLOOR_GAP_PX = 24           # horizontal gap between floor plans


def compose_floor_svgs(titled_svgs) -> str:
    """Composite per-floor plan SVGs side-by-side into ONE SVG document —
    the multi-storey output format (MULTISTOREY_V2_DESIGN.md, D4). Keeps
    the 1-brief-1-SVG contract intact for test baselines, the output
    folder, and the Streamlit app.

    `titled_svgs`: list of (title, svg_doc) left-to-right — ground floor
    first. Each svg_doc is a complete document as produced by
    layout_to_svg / archplan_to_svg; it is embedded unmodified as a nested
    <svg> element (valid SVG) with an x/y offset, under a centered title.
    """
    import re
    entries = []
    for title, doc in titled_svgs:
        m = re.search(r'<svg[^>]*\bwidth="([\d.]+)"[^>]*\bheight="([\d.]+)"',
                      doc)
        w, h = (float(m.group(1)), float(m.group(2))) if m else (600.0, 600.0)
        entries.append((title, doc, w, h))
    total_w = sum(w for _, _, w, _ in entries) \
        + _FLOOR_GAP_PX * (len(entries) - 1)
    total_h = _FLOOR_TITLE_BAND_PX + max(h for _, _, _, h in entries)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'width="{total_w:.0f}" height="{total_h:.0f}" '
             f'viewBox="0 0 {total_w:.0f} {total_h:.0f}">',
             f'<rect x="0" y="0" width="{total_w:.0f}" '
             f'height="{total_h:.0f}" fill="white"/>']
    x = 0.0
    for title, doc, w, h in entries:
        parts.append(
            f'<text x="{x + w / 2:.0f}" y="{_FLOOR_TITLE_BAND_PX - 12:.0f}" '
            f'text-anchor="middle" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="15" font-weight="bold" letter-spacing="2">'
            f'{title}</text>')
        # Nest the complete per-floor document at (x, band). A nested <svg>
        # element ignores any xml declaration-less doc's own x/y (none set)
        # and scopes its viewBox locally, so the inner drawing is unchanged.
        parts.append(doc.replace(
            "<svg ", f'<svg x="{x:.0f}" y="{_FLOOR_TITLE_BAND_PX}" ', 1))
        x += w + _FLOOR_GAP_PX
    parts.append("</svg>")
    return "".join(parts)


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

# ---------------------------------------------------------------------------
# Furniture / fixture overlay (Phase E.2)
# ---------------------------------------------------------------------------

# ONE fill for every fixture family, deliberately.
#
# The first cut coloured fixtures by family (sanitary ware pale blue, timber
# warm) and it was a mistake: a pale-blue shower inside a bath reads as a
# separate ROOM against the public zone's #cfe2f3, and the drawing's whole
# job is to make room boundaries unambiguous. Room fill means zone; fixture
# fill must mean "contents", one value, distinct from every zone colour.
#
# Kinds are told apart by LINEWORK instead — pillow band, basin ellipse,
# burner circles — which also survives greyscale printing, which colour
# coding does not.
_FIXTURE_FILL = "#e3ded4"
_FIXTURE_PILLOW = "#cbc4b4"
_FIXTURE_STROKE = "#8a8378"

# Which glyph a fixture id gets. Explicit, because the first version derived
# it as `kind.split("_")[0]` and that only worked while the ids were a private
# vocabulary: against the real library ids it reads `kitchen_sink` as family
# "kitchen" and silently drops the basin ellipse. An id with no entry here
# draws as a plain body, which is the correct default for most of the library.
_FIXTURE_GLYPH = {
    "bed_single": "bed", "bed_double": "bed",
    "bed_queen": "bed", "bed_king": "bed",
    "kitchen_sink": "basin", "lavatory": "basin",
    "lavatory_pedestal": "basin", "laundry_sink": "basin", "toilet": "basin",
    "range_electric": "burners", "stove_gas_2burner": "burners",
}


def _fixture_family(kind: str) -> str:
    return _FIXTURE_GLYPH.get(kind, "")


# --- Layer C: draw the library's real symbols -------------------------------
#
# Every symbol in fixtures/ is drawn in METRES in its own local space: the wall
# it backs onto is at y = 0, it faces +y into the room, and the footprint's
# back-left corner sits at `origin` inside the viewBox. One transform carries
# the metre-to-pixel conversion and the y-flip together:
#
#     translate(px, py) scale(S, -S) rotate(theta) translate(-ox, -oy)
#
# S is SCALE, which the library was authored against. The trailing translate
# puts the footprint's back-left corner on the anchor point — not always (0,0),
# since the dining tables draw their chairs outside their own footprint.
#
# A welcome side effect: the symbol draws its TRUE shape, so an L-sofa and a
# round table read correctly even though Fixture.rect is only their bounding
# box. The placer still reasons about the rectangle; only the drawing improves.

# theta=0 is a fixture backed onto its SOUTH wall: after the y-flip, local +y
# (into the room) points north.
_SYMBOL_THETA = {"S": 0, "E": 90, "N": 180, "W": 270}

# Which corner of the fixture's rect is the footprint's back-left. "Left" is
# defined facing INTO the room, so it rotates with the symbol.
_SYMBOL_ANCHOR = {
    "S": lambda r: (r.x0, r.y0),
    "N": lambda r: (r.x1, r.y1),
    "E": lambda r: (r.x1, r.y0),
    "W": lambda r: (r.x0, r.y1),
}

_SYM_INNER = re.compile(r"<svg[^>]*>(.*)</svg>\s*$", re.S)
_SYM_STRIP = re.compile(r"<(title|desc)>.*?</\1>", re.S)
_SYM_STROKE = re.compile(r'stroke-width="([\d.]+)"')
_SYM_VECTOR = re.compile(r'\s*vector-effect="non-scaling-stroke"')

_SYMBOL_CACHE = {}


def _symbol_body(fixture_id: str) -> str:
    """The drawable content of a symbol file, ready to place.

    Two edits to what the library ships, and they go together:

    The library sets `vector-effect="non-scaling-stroke"` on every stroked
    element so a 0.9 px line stays 0.9 px however the symbol is scaled.
    Browsers and resvg honour it; **cairosvg does not implement it at all**,
    and cairosvg is what run.py --png and the whole of polish.py rasterise
    with. Left alone, scaling by 42 turns a 0.9 px outline into a 38 px slab
    and every symbol becomes a featureless blob.

    So stroke widths are divided by SCALE, which renders identically at 1:1.
    The attribute must then be REMOVED, or a renderer that does honour it
    would apply 0.9/42 px and draw nothing at all. Fixing one without the
    other is broken in one viewer or the other.

    Cached: this is immutable file content, no per-layout state.
    """
    if fixture_id in _SYMBOL_CACHE:
        return _SYMBOL_CACHE[fixture_id]
    from fixture_library import load_library
    with open(load_library().get(fixture_id).svg_path, encoding="utf-8") as fh:
        raw = fh.read()
    m = _SYM_INNER.search(raw)
    body = _SYM_STRIP.sub("", m.group(1)) if m else ""
    body = _SYM_VECTOR.sub("", body)
    body = _SYM_STROKE.sub(
        lambda s: f'stroke-width="{float(s.group(1)) / SCALE:.5f}"', body)
    _SYMBOL_CACHE[fixture_id] = body
    return body


def fixture_symbol_svg(kind: str, rect, against: str, layout) -> Optional[str]:
    """One placed library symbol, or None when there is nothing to draw."""
    if not against or against not in _SYMBOL_THETA:
        return None                      # free-standing; no wall to orient from
    try:
        from fixture_library import load_library
        spec = load_library().get(kind)
    except (KeyError, ImportError, OSError):
        return None
    body = _symbol_body(kind)
    if not body:
        return None
    mx, my = _SYMBOL_ANCHOR[against](rect)
    px, py = _to_svg_xy(layout.lot, mx, my)
    return (f'<g transform="translate({px:.3f},{py:.3f}) '
            f'scale({SCALE},{-SCALE}) rotate({_SYMBOL_THETA[against]}) '
            f'translate({-spec.origin_x:.4f},{-spec.origin_y:.4f})">'
            f'{body}</g>')


def fixtures_overlay_svg(fixtures, layout, symbols: bool = True) -> str:
    """SVG for a list of Fixture-like objects (.rect, .kind, .room).

    Takes plain data rather than importing solver.fixtures, so core/ keeps its
    layering: the caller places the furniture and hands the rectangles here.
    Drawn fixture-weight, matching the dining-counter convention.

    With `symbols` (the default) each piece is drawn as its real library
    symbol. Anything the library has no drawing for — or that is free-standing,
    with no wall to orient from — falls back to the neutral rectangle and
    linework glyph below, which is also all `symbols=False` emits.
    """
    out = []
    for f in fixtures:
        rc = f.rect
        if symbols:
            sym = fixture_symbol_svg(f.kind, rc, getattr(f, "against", ""),
                                     layout)
            if sym:
                out.append(sym)
                continue
        x0, y0 = _to_svg_xy(layout.lot, rc.x0, rc.y1)     # SVG y is flipped
        x1, y1 = _to_svg_xy(layout.lot, rc.x1, rc.y0)
        fam = _fixture_family(f.kind)
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" '
                   f'height="{y1 - y0:.1f}" fill="{_FIXTURE_FILL}" '
                   f'stroke="{_FIXTURE_STROKE}" stroke-width="0.8" '
                   f'rx="1.5" opacity="0.95"/>')
        # A pillow band marks the head end of a bed, so its orientation is
        # legible without a label.
        if fam == "bed" and getattr(f, "against", ""):
            t = 0.22 * (y1 - y0) if f.against in ("N", "S") else 0.22 * (x1 - x0)
            if f.against == "N":
                px0, py0, px1, py1 = x0, y0, x1, y0 + t
            elif f.against == "S":
                px0, py0, px1, py1 = x0, y1 - t, x1, y1
            elif f.against == "W":
                px0, py0, px1, py1 = x0, y0, x0 + t, y1
            else:
                px0, py0, px1, py1 = x1 - t, y0, x1, y1
            out.append(f'<rect x="{px0:.1f}" y="{py0:.1f}" '
                       f'width="{px1 - px0:.1f}" height="{py1 - py0:.1f}" '
                       f'fill="{_FIXTURE_PILLOW}" stroke="none" rx="1"/>')
        if fam == "basin":
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            r = max(1.5, min(x1 - x0, y1 - y0) * 0.28)
            out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{r:.1f}" '
                       f'ry="{r:.1f}" fill="none" stroke="{_FIXTURE_STROKE}" '
                       f'stroke-width="0.7"/>')
        if fam == "burners":
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            d = min(x1 - x0, y1 - y0) * 0.22
            for dx, dy in ((-d, -d), (d, -d), (-d, d), (d, d)):
                out.append(f'<circle cx="{cx + dx:.1f}" cy="{cy + dy:.1f}" '
                           f'r="{d * 0.55:.1f}" fill="none" '
                           f'stroke="{_FIXTURE_STROKE}" stroke-width="0.6"/>')
    return "".join(out)


# The room-name and dimension <text> elements emitted by
# _emit_centered_text_block. Matched on their fill, which is unique to them:
# ruler numerals use LABEL_FILL and the stair UP/DN glyph carries a
# paint-order halo, so neither is caught here.
_LABEL_TEXT_RE = re.compile(
    r'<text\b[^>]*\bfill="#(?:222|555)"[^>]*>.*?</text>', re.S)


def polished_image_overlay(layout, png_bytes: bytes) -> str:
    """An `<image>` element covering exactly the LOT rectangle.

    For polish.py. The image model is asked to return the lot edge-to-edge
    with NO text of any kind, because invented dimension figures were the one
    defect that survived every prompt version — `KITCHEN 3.2x2.3 m . 7.3 sqm`
    where the plan says `3.1x2.3 m . 7.1 sqm` is exactly the silent
    disagreement NANO_BANANA_RENDER_DESIGN.md §1 calls worse than useless.

    So the model draws the picture and we draw the words. Splicing this
    through `inject_overlay` puts the picture over our plan and then lifts our
    own label text back on top of it, at our coordinates, with our numbers.
    The metre ruler survives untouched because it lives OUTSIDE the lot
    rectangle this image covers.
    """
    import base64
    lot = layout.lot
    x0, y0 = _to_svg_xy(lot, 0.0, lot.depth)        # SVG y is flipped
    x1, y1 = _to_svg_xy(lot, lot.width, 0.0)
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return (f'<image x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" '
            f'height="{y1 - y0:.1f}" preserveAspectRatio="none" '
            f'href="data:image/png;base64,{b64}"/>')


_TEXT_ATTR_RE = re.compile(
    r'<text[^>]*\bx="([\d.-]+)"[^>]*\by="([\d.-]+)"[^>]*'
    r'\bfont-size="([\d.]+)"[^>]*>(.*?)</text>', re.S)


def room_label_masks(layout, height_m: float = 1.15, width_frac: float = 0.86) -> str:
    """Opaque chips over the label zone of every room, sized to the ROOM.

    For polish.py. The image model is told, as instruction #1 and in capitals,
    to write no text; it writes room names and invented dimensions anyway, and
    places them at the room centre — the same place ours go. Masking by our own
    text width failed whenever its label was longer than ours (it rendered
    "COMMON TOILET & BATH" over a chip sized for "KITCHEN").

    Keying the chip to the room instead makes the cover-up independent of what
    the model chose to write, which is the only version that is actually
    reliable. Uses the same largest-cell rule archplan_to_svg uses to position
    a label, so the chip and the real label always agree.
    """
    out = []
    # Setback elements (porch, carport, lanai) carry labels too, and the model
    # writes over them just as happily.
    for r in list(layout.rooms) + list(getattr(layout, "elements", []) or []):
        big = max(getattr(r, "cells", None) or [r.rect], key=lambda c: c.area)
        w = min(big.w * width_frac, big.w - 0.10)
        h = min(height_m, big.h - 0.10)
        if w <= 0 or h <= 0:
            continue
        cx, cy = (big.x0 + big.x1) / 2.0, (big.y0 + big.y1) / 2.0
        x0, y0 = _to_svg_xy(layout.lot, cx - w / 2, cy + h / 2)
        x1, y1 = _to_svg_xy(layout.lot, cx + w / 2, cy - h / 2)
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" '
                   f'height="{y1 - y0:.1f}" fill="#fbfbf8" opacity="0.93" '
                   f'rx="4"/>')
    return "".join(out)


def _label_masks(labels, pad_x=7.0, pad_y=3.0) -> str:
    """Opaque panels sized to each label line, emitted BEHIND the text.

    For polish.py only. The image model was told three times, in capitals and
    as instruction #1, to write no text — and wrote its own room names and its
    own (invented) dimensions anyway. Since it places them at the room centre,
    exactly where ours go, an opaque panel behind our label covers its label.
    We stop asking and start painting over.

    Width is estimated from the glyph count rather than measured — there is no
    font metric available here — so the panel is padded generously. It sits on
    an opaque near-white so it reads as a label chip, not a hole.
    """
    out = []
    for m in _TEXT_ATTR_RE.finditer(labels):
        cx, cy, fs = float(m.group(1)), float(m.group(2)), float(m.group(3))
        txt = re.sub(r"<[^>]+>", "", m.group(4))
        w = 0.62 * fs * max(len(txt), 1) + 2 * pad_x
        h = fs * 1.25 + 2 * pad_y
        out.append(f'<rect x="{cx - w / 2:.1f}" y="{cy - fs - pad_y:.1f}" '
                   f'width="{w:.1f}" height="{h:.1f}" fill="#fbfbf8" '
                   f'opacity="0.93" rx="3"/>')
    return "".join(out)


def inject_overlay(svg_doc: str, overlay: str, mask_behind_labels=False) -> str:
    """Splice an overlay in, keeping the room labels readable ON TOP of it.

    SVG has no z-index — paint order IS stacking order — so an overlay
    appended at the end covers the room labels, and a bed lands squarely
    across "MASTER BR / 5.4x3.7 m . 20.0 sqm".

    Rather than teach every drawing pass about a furniture layer (which would
    move text in all 52 baselines for a feature nothing in the pipeline calls
    yet), lift the label text out of the finished document and re-emit it
    after the overlay. Text has no fill or stroke interaction with what it
    passes over, so promoting it is purely a stacking change — and a document
    with no overlay is never touched.
    """
    if not overlay:
        return svg_doc
    labels = "".join(_LABEL_TEXT_RE.findall(svg_doc))
    body = _LABEL_TEXT_RE.sub("", svg_doc)
    masks = _label_masks(labels) if mask_behind_labels else ""
    return body.replace("</svg>", overlay + masks + labels + "</svg>")
