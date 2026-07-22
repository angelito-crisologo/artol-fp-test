#!/usr/bin/env python3
"""Regenerates artol-topologies/ (the published HTML catalog) from the
current floorplan_v1/ checkout.

For every topology under floorplan_v1/topologies/, picks its canonical
test brief (smallest no-carport lot, excluding swap/kdoor/lanai/dk_svc
variants and fallback-mechanism proof briefs), solves it through the real
CP-SAT pipeline, and writes:

  artol-topologies/data/topologies/<id>.json   raw topology doc (all topologies)
  artol-topologies/data/briefs/<id>.json       raw canonical brief (verified only)
  artol-topologies/plans/<id>.svg              solved floor plan (verified only)
  artol-topologies/index.html                  gallery + one page per topology
  artol-topologies/assets/{styles.css,app.js}  copied from this directory

A topology with no test brief (or where every referencing brief falls back
to a different topology before solving) is listed as "not regression-tested"
with a structural-only check — nothing about its output is fabricated.

Usage:
    python3 tools/topology_catalog/build_catalog.py

Run from anywhere; every path is resolved relative to this file and to the
repo root two levels up. Takes a few minutes — one real CP-SAT solve per
verified topology. See TOPOLOGY_CHANGES.md at the repo root for what a
run is expected to pick up.
"""
import glob
import html as htmllib
import json
import os
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_FP = os.path.join(_REPO, "floorplan_v1")
_SITE = os.path.join(_REPO, "artol-topologies")
_TOPOLOGIES_DIR = os.path.join(_FP, "topologies")
_PLANS_DIR = os.path.join(_SITE, "plans")
_DATA_TOPOLOGIES_DIR = os.path.join(_SITE, "data", "topologies")
_DATA_BRIEFS_DIR = os.path.join(_SITE, "data", "briefs")
_ASSETS_SRC = os.path.join(_HERE, "assets")
_ASSETS_DST = os.path.join(_SITE, "assets")

sys.path.insert(0, _FP)
import run  # noqa: E402  floorplan_v1/run.py — wires up its own core/solver/ai sys.path

BATH_TYPES = ("common_bath", "ensuite_bath", "bath_toilet", "powder_room")
BEDROOM_TYPES = ("master_bedroom", "bedroom_standard")
SHAPE_ORDER = {"squarish": 0, "narrow": 1, "wide": 2, "extra_wide": 3}
SHAPE_LABEL = {"squarish": "Squarish", "narrow": "Narrow", "wide": "Wide",
               "extra_wide": "Extra wide"}
ZONE_FILL = {"public": "#cfe2f3", "private": "#d9ead3", "service": "#fce5cd",
             "circulation": "#efefef"}

PRETTY_ROOM = {
    "master_bedroom": "Master bedroom",
    "bedroom_standard": "Standard bedroom",
    "common_bath": "Common bath",
    "ensuite_bath": "Ensuite bath",
    "bath_toilet": "Bath & toilet",
    "powder_room": "Powder room",
    "great_room": "Great room",
    "living_room": "Living room",
    "dining_room": "Dining room",
    "kitchen": "Kitchen",
    "hallway": "Hallway",
    "stairs": "Stairs",
    "carport": "Carport",
    "dirty_kitchen": "Dirty kitchen",
    "service_area": "Service area",
    "lanai": "Lanai",
    "porch": "Porch",
}


def pretty_room(t):
    return PRETTY_ROOM.get(t, t.replace("_", " ").capitalize())


def esc(s):
    return htmllib.escape(str(s), quote=False)


def fmt_num(x):
    x = float(x)
    if x.is_integer():
        return str(int(x))
    return f"{x:g}"


# ---------- discovery ----------

def discover_topologies():
    out = []
    for abs_path in sorted(glob.glob(os.path.join(_TOPOLOGIES_DIR, "**", "*.json"),
                                      recursive=True)):
        rel = os.path.relpath(abs_path, _TOPOLOGIES_DIR).replace(os.sep, "/")
        with open(abs_path, encoding="utf-8") as f:
            raw = json.load(f)
        out.append((rel, abs_path, raw))
    return out


def load_test_brief_candidates():
    """topology_fname (as declared in brief JSON) -> list of candidate dicts."""
    by_topo = {}
    for name, brief_obj, topology_fname, adjustments, rel_dir in run.load_test_briefs():
        path = (os.path.join(run.TEST_BRIEFS_DIR, rel_dir, name + ".json") if rel_dir
                else os.path.join(run.TEST_BRIEFS_DIR, name + ".json"))
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        by_topo.setdefault(topology_fname, []).append(dict(
            path=path, raw=raw, brief=brief_obj, topology_fname=topology_fname,
            adjustments=adjustments, name=name))
    return by_topo


def _excluded_candidate(entry):
    base = os.path.basename(entry["path"])
    if "test_mins" in entry["path"].replace(os.sep, "/"):
        return True
    if any(bad in base for bad in ("_swap", "_kdoor", "_lanai", "_dk_svc")):
        return True
    intent = (entry["raw"].get("intent") or "").upper()
    if "AUTO-SWITCH PROOF:" in intent:
        return True
    return False


def pick_canonical_brief(candidates):
    """Prefer: not a variant/fallback-proof brief, no carport, smallest lot."""
    if not candidates:
        return None
    filtered = [c for c in candidates if not _excluded_candidate(c)] or candidates

    def is_ncp(c):
        return c["raw"].get("carport_type") in (None, "ncp") and not c["raw"].get("carport_side")

    pool = [c for c in filtered if is_ncp(c)] or filtered
    pool.sort(key=lambda c: c["raw"]["lot_width"] * c["raw"]["lot_depth"])
    return pool[0]


# ---------- per-topology derived content ----------

def derive_legend(rooms):
    zones, bath = set(), False
    for r in rooms:
        if r.get("type") in BATH_TYPES:
            bath = True
        else:
            zones.add(r.get("zone"))
    items = []
    if "private" in zones:
        items.append(("#d9ead3", "Bedroom"))
    if bath:
        items.append(("#ead1dc", "Bath (any zone)"))
    if "public" in zones:
        items.append(("#cfe2f3", "Public / LDK"))
    if "circulation" in zones:
        items.append(("#efefef", "Circulation"))
    if "service" in zones:
        items.append(("#fce5cd", "Service"))
    return items


def derive_notes_paragraphs(notes_list):
    paragraphs, current = [], []
    for line in notes_list or []:
        if line.strip() == "":
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def derive_overrides(raw):
    items = []
    if raw.get("lot_adjustment_profiles"):
        names = ", ".join(p.get("name", "?") for p in raw["lot_adjustment_profiles"])
        items.append(f"lot_adjustment_profiles — size-conditional room-size overrides "
                     f"({esc(names)}).")
    if any("door_host_group" in a for a in raw.get("adjacencies", [])):
        items.append('door_host_group — at least one door\'s host wall is chosen by the '
                     'solver\'s auto-scorer (or overridden per-brief via '
                     '<code class="mono">door_host</code>), not fixed in the topology.')
    if raw.get("match_bedroom_widths"):
        items.append("match_bedroom_widths — solver forces master.width == standard.width.")
    if raw.get("match_bath_widths"):
        items.append("match_bath_widths — solver forces the bath rooms' widths to match.")
    if raw.get("match_widths"):
        groups = "; ".join(", ".join(g) for g in raw["match_widths"])
        items.append(f"match_widths — solver forces matching widths within each group: "
                     f"{esc(groups)}.")
    if raw.get("private_area_floor") is False:
        items.append("private_area_floor: false — the hard private-area-must-exceed-public "
                     "rule is disabled (a single bedroom can't outweigh a full LDK).")
    if raw.get("zone_balance_rooms"):
        zbr = raw["zone_balance_rooms"]
        if isinstance(zbr, dict):
            desc = "; ".join(f"{esc(zone)}: {esc(', '.join(ids))}" for zone, ids in zbr.items())
        else:
            desc = esc(", ".join(zbr))
        items.append(f"zone_balance_rooms — custom room grouping overrides the default "
                     f"public/private area split ({desc}).")
    if raw.get("aspect_overrides"):
        desc = ", ".join(f"{esc(room)} ({ratio}:1)" for room, ratio in raw["aspect_overrides"].items())
        items.append(f"aspect_overrides — per-room aspect-ratio (w:h) floor for {desc}.")
    if raw.get("kitchen_rear_pin") is not None:
        items.append(f"kitchen_rear_pin: {str(raw['kitchen_rear_pin']).lower()} — overrides "
                     f"the solver's default kitchen-rear-wall placement rule.")
    if raw.get("kitchen_side_pin") is False:
        items.append("kitchen_side_pin: false — the default mirror-symmetry kitchen-side pin "
                     "is disabled (kitchen legitimately sits on the non-carport side).")
    if raw.get("ldk_horizontal"):
        items.append("ldk_horizontal: true — disables the solver's default vertical "
                     "LDK-stacking rules so great_room/kitchen can sit side-by-side.")
    if raw.get("ensuite_alcove_joins_master"):
        items.append("ensuite_alcove_joins_master — the strip beside a narrower ensuite is "
                     "folded into master as an L-shaped alcove.")
    if raw.get("bedroom_band_fills_width"):
        items.append("bedroom_band_fills_width — the bedroom band is forced to fill the full "
                     "envelope width.")
    if raw.get("fallback_topology"):
        target = os.path.splitext(os.path.basename(raw["fallback_topology"]))[0]
        if raw.get("fallback_below_buildable_sqm"):
            items.append(f"fallback_below_buildable_sqm / fallback_topology — below "
                         f"{esc(raw['fallback_below_buildable_sqm'])} m²/floor buildable area, "
                         f"the runner auto-routes to <code class=\"mono\">{esc(target)}</code> "
                         f"before attempting a solve.")
        else:
            items.append(f"fallback_topology — if the solver reports infeasibility on the "
                         f"brief's lot, retries with <code class=\"mono\">{esc(target)}</code>.")
    if raw.get("storeys"):
        kinds = {a.get("kind") for a in raw.get("adjacencies", [])}
        bits = []
        if "stair_vertical" in kinds:
            bits.append('GF flight and 2F stairwell pinned to the identical rectangle '
                       '(<code class="mono">stair_vertical</code>)')
        if "stair_boarding" in kinds or "stair_arrival" in kinds:
            bits.append('ascent direction forced via <code class="mono">stair_boarding</code>/'
                       '<code class="mono">stair_arrival</code> so the flight can\'t top out '
                       'against a wall')
        if bits:
            items.append("Two-storey: " + "; ".join(bits) + ".")
    return items


def room_fill_color(rr, room):
    if rr.get("type") in BATH_TYPES:
        return "#ead1dc"
    if room.zone == "circulation":
        return ZONE_FILL["circulation"]
    return ZONE_FILL.get(room.zone, "#eeeeee")


# ---------- record building ----------

def build_record(rel_path, abs_path, raw, brief_candidates):
    rooms = raw.get("rooms", [])
    rec = dict(
        id=raw["id"],
        rel_path=rel_path,
        abs_path=abs_path,
        raw=raw,
        shape=raw.get("target_shell", "squarish"),
        is_multi="storeys" in raw,
        bedroom_count=sum(1 for r in rooms if r.get("type") in BEDROOM_TYPES),
        bath_count=sum(1 for r in rooms if r.get("type") in BATH_TYPES),
        legend=derive_legend(rooms),
        notes_paragraphs=derive_notes_paragraphs(raw.get("notes")),
        overrides=derive_overrides(raw),
        verified=False,
    )
    rec["shape_label"] = SHAPE_LABEL.get(rec["shape"], rec["shape"].capitalize())
    rec["storey_label"] = "2-storey" if rec["is_multi"] else "single-storey"

    try:
        run.load_topology(abs_path)
        rec["structural_ok"] = True
        rec["structural_msg"] = None
    except Exception as e:  # noqa: BLE001 — surfaced verbatim in the notice block
        rec["structural_ok"] = False
        rec["structural_msg"] = f"{e.__class__.__name__}: {e}"

    chosen = pick_canonical_brief(brief_candidates)
    if chosen is None:
        return rec

    try:
        layout, topo_obj, reason = run._run_hand_authored(
            chosen["brief"], chosen["topology_fname"], adjustments=chosen["adjustments"],
            verbose=False, deterministic=True)
    except RuntimeError as e:
        print(f"  ! WARNING: canonical brief for {rec['id']} failed to solve: {e}")
        return rec

    rec["verified"] = True
    rec["brief_path"] = chosen["path"]
    rec["brief_raw"] = chosen["raw"]
    rec["brief_rel"] = os.path.relpath(chosen["path"], run.BRIEFS_DIR).replace(os.sep, "/")
    rec["topology_fname"] = chosen["topology_fname"]
    rec["layout"] = layout
    rec["topo_obj"] = topo_obj
    rec["reason"] = reason
    return rec


# ---------- HTML fragments ----------

def code_panel_html(panel_id, filename, obj, download_href):
    text = json.dumps(obj, indent=2, ensure_ascii=True) + "\n"
    n_lines = text.count("\n")
    n_bytes = len(text.encode("utf-8"))
    size = f"{n_bytes / 1024:.1f} KB" if n_bytes >= 1024 else f"{n_bytes} B"
    return (
        '<details class="code-panel" open>\n'
        '  <summary class="code-panel-summary">\n'
        '    <span class="disclosure-tri" aria-hidden="true"></span>\n'
        f'    <span class="code-panel-file"><b>{esc(filename)}</b></span>\n'
        f'    <span class="code-panel-meta">{n_lines} lines · {size}</span>\n'
        '  </summary>\n'
        f'  <div class="code-panel-toolbar"><a class="download-link" href="{esc(download_href)}" '
        f'download>Download</a><button class="copy-btn" data-copy-target="{esc(panel_id)}" '
        f'type="button">Copy</button></div>\n'
        f'  <pre class="code-scroll"><code id="{esc(panel_id)}" class="lang-json">{esc(text)}</code></pre>\n'
        '</details>'
    )


def render_definition_subsheet(rec):
    legend_html = "".join(
        f'<div class="legend-item"><span class="swatch" style="background:{c}"></span>{esc(l)}</div>'
        for c, l in rec["legend"])
    notes_html = "".join(f"<p>{esc(p)}</p>" for p in rec["notes_paragraphs"])
    adj_html = "".join(
        f'<li><b>{esc(a["a"])} ↔ {esc(a["b"])}</b> — {esc(a.get("note", ""))}'
        f'<span class="kind">{esc(a.get("kind", ""))}</span></li>'
        for a in rec["raw"].get("adjacencies", []))
    overrides_html = ""
    if rec["overrides"]:
        overrides_html = ('<h3>Notable overrides</h3><ul class="override-list">'
                          + "".join(f"<li>{o}</li>" for o in rec["overrides"]) + "</ul>")
    panel = code_panel_html(f"topo-{rec['id']}", f"{rec['id']}.json", rec["raw"],
                            f"data/topologies/{rec['id']}.json")
    return (
        '<div class="subsheet">\n'
        f'  <div class="subsheet-head"><h3>Definition</h3><span class="subsheet-file">'
        f'{esc(rec["rel_path"])}</span></div>\n'
        '  <div class="sheet-body">\n'
        '    <div class="prose">\n'
        '      <h4>Room program</h4>\n'
        f'      <div class="legend">{legend_html}</div>\n'
        '      <h4>Design notes</h4>\n'
        f'      {notes_html}\n'
        '      <h4>Key adjacencies</h4>\n'
        f'      <ul class="adj-list">{adj_html}</ul>\n'
        f'      {overrides_html}\n'
        '    </div>\n'
        f'    {panel}\n'
        '  </div>\n'
        '</div>'
    )


def render_notice(rec):
    if rec["structural_ok"]:
        return (
            '<div class="notice warn">\n'
            '  <b>Not yet regression-tested.</b> No test brief in <code class="mono">briefs/test/</code> '
            'currently exercises this topology through the solver (or every brief that references it '
            'falls back to a different topology before solving). Static structural check only — '
            '<code class="mono">load_topology()</code> loads cleanly — every room ID is unique, every '
            'adjacency references a real room, and every habitable room is reachable from the entry '
            'point. No test brief, rendered output, or solver-derived room sizing exists to show for '
            'this entry; nothing below is fabricated to fill the gap.\n'
            '</div>'
        )
    return (
        '<div class="notice warn">\n'
        '  <b>Not yet regression-tested — and fails to load.</b> '
        '<code class="mono">load_topology()</code> raised: '
        f'<span class="code-inline">{esc(rec["structural_msg"])}</span>. No test brief exercises '
        'this topology; the structural error needs fixing before one can be authored.\n'
        '</div>'
    )


def brief_facts(raw_brief):
    lw, ld = raw_brief["lot_width"], raw_brief["lot_depth"]
    sb = raw_brief.get("setbacks") or {"front": 2.0, "rear": 2.0, "left": 2.0, "right": 2.0}
    front, rear = sb.get("front", 2.0), sb.get("rear", 2.0)
    left, right = sb.get("left", 2.0), sb.get("right", 2.0)
    env_w, env_h = lw - left - right, ld - front - rear
    carport_side = raw_brief.get("carport_side")
    carport_type = raw_brief.get("carport_type")
    carport_desc = (f"{(carport_type or 'ncp').upper()} — {carport_side} side" if carport_side
                    else "None requested")
    computed = (f"Lot {fmt_num(lw)}×{fmt_num(ld)} m with {fmt_num(front)} m front / "
               f"{fmt_num(rear)} m rear / {fmt_num(left)} m side setbacks gives a "
               f"{fmt_num(env_w)}×{fmt_num(env_h)} m buildable envelope — "
               f"{fmt_num(env_w * env_h)} m² floor, "
               + (f"requesting a carport on the {carport_side} side."
                  if carport_side else "requesting no carport.") + " ")
    rows = [
        ("Lot", f"{fmt_num(lw)} × {fmt_num(ld)} m ({fmt_num(lw * ld)} m²)"),
        ("Buildable envelope", f"{fmt_num(env_w)} × {fmt_num(env_h)} m ({fmt_num(env_w * env_h)} m²)"),
        ("Setbacks", f"{fmt_num(front)} / {fmt_num(rear)} / {fmt_num(left)} / {fmt_num(right)} m "
                    f"(front/rear/left/right)"),
        ("Bedrooms requested", str(raw_brief.get("bedroom_count", "—"))),
        ("Carport", carport_desc),
        ("Occupancy class", raw_brief.get("occupancy_class", "R-1")),
    ]
    return computed, rows


def render_brief_subsheet(rec):
    raw_brief = rec["brief_raw"]
    computed, fact_rows = brief_facts(raw_brief)
    facts_html = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in fact_rows)
    must_haves = " · ".join(raw_brief.get("must_haves", [])) or "—"
    panel = code_panel_html(f"brief-{rec['id']}", os.path.basename(rec["brief_path"]),
                            raw_brief, f"data/briefs/{rec['id']}.json")
    return (
        '<div class="subsheet">\n'
        f'  <div class="subsheet-head"><h3>Test brief</h3><span class="subsheet-file">'
        f'{esc(rec["brief_rel"])}</span></div>\n'
        '  <div class="sheet-body">\n'
        '    <div class="prose">\n'
        f'      <p>{esc(raw_brief.get("intent", ""))}</p><p>{esc(computed)}</p>\n'
        f'      <table class="facts">{facts_html}</table>\n'
        f'      <h4>Must-haves</h4><p>{esc(must_haves)}</p>\n'
        '    </div>\n'
        f'    {panel}\n'
        '  </div>\n'
        '</div>'
    )


def render_output_subsheet(rec):
    layout = rec["layout"]
    issues = layout.issues
    if issues:
        chip_rows = []
        for issue in issues:
            sev = issue.severity
            label = {"warning": "Warning", "suggestion": "Suggestion",
                    "error": "Error"}.get(sev, sev.title())
            cls = {"warning": "warn", "suggestion": "warn", "error": "err"}.get(sev, "warn")
            chip_rows.append(
                f'<div class="chip-row"><span class="chip {cls}">{label}</span>'
                f'<span class="chip-text">{esc(issue.msg)} '
                f'<span class="code-inline">({esc(issue.code)})</span></span></div>')
        chips_html = "".join(chip_rows)
    else:
        chips_html = ('<div class="chip-row"><span class="chip pass">Clean</span>'
                     '<span class="chip-text">No warnings or suggestions.</span></div>')

    by_id = {r.id: r for r in layout.rooms}
    raw_rooms = rec["raw"].get("rooms", [])
    multi = rec["is_multi"]
    dim_rows, cur_storey = [], None
    for rr in raw_rooms:
        room = by_id.get(rr["id"])
        if room is None:
            continue
        if multi:
            st = rr.get("storey", 1)
            if st != cur_storey:
                cur_storey = st
                label = "GROUND FLOOR" if st == 1 else ("SECOND FLOOR" if st == 2 else f"FLOOR {st}")
                dim_rows.append(f'<tr class="storey-row"><td colspan="3">{esc(label)}</td></tr>')
        color = room_fill_color(rr, room)
        dim_rows.append(
            f'<tr><td><span class="room-tag" style="background:{color}"></span>'
            f'{esc(pretty_room(rr.get("type", "")))}</td>'
            f'<td class="num">{room.rect.w:.2f} × {room.rect.h:.2f} m</td>'
            f'<td class="num">{room.area:.2f} m²</td></tr>')
    dims_html = "".join(dim_rows)

    env = layout.lot.envelope()
    stat_html = (
        '<div class="stat-strip">\n'
        f'  <div class="stat"><div class="stat-label">Envelope</div>'
        f'<div class="stat-value">{env.area:.1f}<small>m²</small></div></div>\n'
        f'  <div class="stat"><div class="stat-label">Footprint</div>'
        f'<div class="stat-value">{layout.footprint_area:.1f}<small>m²</small></div></div>\n'
        f'  <div class="stat"><div class="stat-label">Occupancy</div>'
        f'<div class="stat-value">{layout.occupancy_pct:.1f}<small>%</small></div></div>\n'
        f'  <div class="stat"><div class="stat-label">Objective score</div>'
        f'<div class="stat-value">{layout.score:.1f}</div></div>\n'
        '</div>'
    )

    return (
        '<div class="subsheet">\n'
        f'  <div class="subsheet-head"><h3>Rendered output</h3><span class="subsheet-file">'
        f'[hand-authored] using {esc(rec["topology_fname"])} (no API call)</span></div>\n'
        '  <div class="sheet-body">\n'
        '    <div class="plan-sheet">\n'
        '      <div class="plan-sheet-head"><span>Floor plan · metres</span>\n'
        f'        <span><a class="download-link" href="plans/{rec["id"]}.svg" download>Download SVG</a> '
        '· Front (street) at bottom</span></div>\n'
        f'      <div class="plan-sheet-body"><img src="plans/{rec["id"]}.svg" '
        f'alt="Floor plan: {esc(rec["id"])}"></div>\n'
        '    </div>\n'
        '    <div class="prose">\n'
        '      <h4>Validator result</h4>\n'
        f'      <div class="chips">{chips_html}</div>\n'
        '      <h4>Room dimensions</h4>\n'
        f'      <table class="dims"><tr><th>Room</th><th class="num">W × D</th>'
        f'<th class="num">Area</th></tr>\n{dims_html}</table>\n'
        f'      {stat_html}\n'
        '    </div>\n'
        '  </div>\n'
        '</div>'
    )


def render_detail_page(rec, index, total):
    pill = ('<span class="pill pass">Verified</span>' if rec["verified"]
           else '<span class="pill warn">Not regression-tested</span>')
    body = [render_definition_subsheet(rec)]
    if rec["verified"]:
        body.append(render_brief_subsheet(rec))
        body.append(render_output_subsheet(rec))
    else:
        body.insert(0, render_notice(rec))
    return (
        f'<section class="route-detail" id="page-{rec["id"]}" data-topology="{rec["id"]}" hidden>'
        f'<a class="back-link" href="#/">← Back to catalog</a>\n'
        '<div class="entry-head">\n'
        f'  <span class="entry-num">No. {index:02d} / {total}</span>\n'
        f'  <h2>{esc(rec["id"])}</h2>\n'
        f'  {pill}\n'
        '</div>\n'
        f'<div class="doc-sub"><span class="mono">{esc(rec["id"])}</span> · {rec["storey_label"]} · '
        f'{rec["shape_label"]} · {rec["bedroom_count"]} bed · {rec["bath_count"]} bath</div>\n'
        f'<p class="doc-desc">{esc(rec["raw"].get("label", ""))}</p>'
        + "".join(body) +
        '</section>'
    )


def render_thumb_card(rec):
    if rec["verified"]:
        media = (f'<div class="thumb-media"><img src="plans/{rec["id"]}.svg" '
                f'alt="Floor plan: {esc(rec["id"])}" loading="lazy"></div>')
        pill = '<span class="pill pass sm">Verified</span>'
    else:
        media = ('<div class="thumb-media thumb-empty"><span class="thumb-empty-glyph" '
                 'aria-hidden="true">▢</span><span class="thumb-empty-text">No rendered '
                 'output yet</span></div>')
        pill = '<span class="pill warn sm">Not tested</span>'
    tag = '<span class="thumb-tag">2-storey</span>' if rec["is_multi"] else ""
    return (
        f'<a class="thumb-card" href="#/topology/{rec["id"]}" data-topology="{rec["id"]}" '
        f'data-shape="{rec["shape"]}">\n'
        f'  {media}\n'
        '  <div class="thumb-info">\n'
        f'    <div class="thumb-name">{esc(rec["id"])}</div>\n'
        f'    <div class="thumb-meta">{rec["shape_label"]}{tag}{pill}</div>\n'
        '  </div>\n'
        '</a>'
    )


def render_accordion(groups):
    out = []
    for i, (bedroom_count, recs) in enumerate(groups):
        n_verified = sum(1 for r in recs if r["verified"])
        shape_counts = {}
        for r in recs:
            shape_counts[r["shape"]] = shape_counts.get(r["shape"], 0) + 1
        pills = ['<button class="filter-pill is-active" type="button" data-shape="all">All</button>']
        for shape in sorted(shape_counts, key=lambda s: SHAPE_ORDER.get(s, 9)):
            pills.append(f'<button class="filter-pill" type="button" data-shape="{shape}">'
                        f'{SHAPE_LABEL.get(shape, shape.capitalize())} '
                        f'<span class="filter-pill-n">{shape_counts[shape]}</span></button>')
        cards = "".join(render_thumb_card(r) for r in recs)
        is_open = " is-open" if i == 0 else ""
        aria_open = "true" if i == 0 else "false"
        out.append(
            f'<div class="acc-group{is_open}">\n'
            '  <div class="acc-header-row">\n'
            f'    <button class="acc-toggle" type="button" aria-expanded="{aria_open}">\n'
            '      <span class="acc-chevron" aria-hidden="true"></span>\n'
            f'      <span class="acc-title">{bedroom_count} Bedroom</span>\n'
            '    </button>\n'
            f'    <div class="acc-filter" role="group" aria-label="Filter {bedroom_count} bedroom '
            f'topologies by shape">{"".join(pills)}</div>\n'
            f'    <span class="acc-count">{len(recs)} topologies · {n_verified} verified</span>\n'
            '  </div>\n'
            f'  <div class="acc-panel">\n    <div class="thumb-grid">{cards}</div>\n  </div>\n'
            '</div>'
        )
    return "".join(out)


def render_page(all_recs):
    total = len(all_recs)
    n_verified = sum(1 for r in all_recs if r["verified"])
    n_unverified = total - n_verified

    groups = []
    seen = []
    for r in all_recs:
        if not seen or seen[-1][0] != r["bedroom_count"]:
            seen.append((r["bedroom_count"], []))
        seen[-1][1].append(r)
    groups = seen

    gallery = (
        '<div id="route-gallery">\n'
        '  <header class="gallery-header">\n'
        '    <div class="gallery-header-inner">\n'
        '      <div class="eyebrow">artol-ai · PH floor plan generator</div>\n'
        '      <h1 class="doc-title">Topology catalog</h1>\n'
        "      <p class=\"gallery-header-desc\">Every hand-authored room topology in the CP-SAT "
        "solver's catalog. Click a floor plan to open its own page — full definition, test "
        "brief, and solved output.</p>\n"
        '      <div class="stat-row">\n'
        f'        <div><div class="stat-label">Topologies</div><div class="stat-value">{total}</div></div>\n'
        f'        <div><div class="stat-label">Verified</div><div class="stat-value">{n_verified}</div></div>\n'
        f'        <div><div class="stat-label">Not yet tested</div>'
        f'<div class="stat-value sv-warn">{n_unverified}</div></div>\n'
        '      </div>\n'
        '    </div>\n'
        '  </header>\n'
        f'  <div class="accordion">{render_accordion(groups)}</div>\n'
        '</div>'
    )

    detail_pages = []
    for idx, r in enumerate(all_recs, start=1):
        detail_pages.append(render_detail_page(r, idx, total))

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>Topology Catalog — artol-ai</title>\n'
        '<meta name="description" content="Every hand-authored room topology in the artol-ai '
        'CP-SAT floor plan generator — definition, test brief, and solved output for each.">\n'
        '<link rel="stylesheet" href="assets/styles.css">\n</head>\n<body>\n'
        + gallery + "".join(detail_pages) +
        '\n<script src="assets/app.js" defer></script>\n</body>\n</html>\n'
    )


# ---------- main ----------

def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=True)
        f.write("\n")


def main():
    t0 = time.time()
    os.makedirs(_PLANS_DIR, exist_ok=True)
    os.makedirs(_DATA_TOPOLOGIES_DIR, exist_ok=True)
    os.makedirs(_DATA_BRIEFS_DIR, exist_ok=True)

    topologies = discover_topologies()
    briefs_by_topo = load_test_brief_candidates()
    print(f"discovered {len(topologies)} topologies, "
         f"{sum(len(v) for v in briefs_by_topo.values())} test-brief candidates across "
         f"{len(briefs_by_topo)} referenced topologies\n")

    records = []
    for rel_path, abs_path, raw in topologies:
        candidates = briefs_by_topo.get(rel_path, [])
        print(f"--- {rel_path}  ({len(candidates)} candidate brief(s))")
        rec = build_record(rel_path, abs_path, raw, candidates)
        if rec["verified"]:
            print(f"    solved via {os.path.basename(rec['brief_path'])}")
            run._write(rec["id"], rec["layout"], rec["topo_obj"], rec["reason"],
                      rel_dir="", out_root=_PLANS_DIR, write_png=False)
            write_json(os.path.join(_DATA_BRIEFS_DIR, f"{rec['id']}.json"), rec["brief_raw"])
        else:
            print("    NOT VERIFIED (no usable canonical brief)")
        write_json(os.path.join(_DATA_TOPOLOGIES_DIR, f"{rec['id']}.json"), raw)
        records.append(rec)

    records.sort(key=lambda r: (r["bedroom_count"], SHAPE_ORDER.get(r["shape"], 9),
                                2 if r["is_multi"] else 1, r["id"]))

    html_doc = render_page(records)
    with open(os.path.join(_SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_doc)

    os.makedirs(_ASSETS_DST, exist_ok=True)
    shutil.copy(os.path.join(_ASSETS_SRC, "styles.css"), os.path.join(_ASSETS_DST, "styles.css"))
    shutil.copy(os.path.join(_ASSETS_SRC, "app.js"), os.path.join(_ASSETS_DST, "app.js"))

    n_verified = sum(1 for r in records if r["verified"])
    dt = time.time() - t0
    print(f"\ndone in {dt:.0f}s — {len(records)} topologies, {n_verified} verified, "
         f"{len(records) - n_verified} not yet tested")
    print(f"wrote {os.path.join(_SITE, 'index.html')}")


if __name__ == "__main__":
    main()
