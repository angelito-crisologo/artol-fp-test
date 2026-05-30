"""SVG renderer + HTML gallery for generated layouts.

Front (street) is drawn at the BOTTOM. Rooms are coloured by zone; uncovered
setback elements are drawn dashed. Dimensions and areas are labelled.
"""
import html
from typing import List
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
