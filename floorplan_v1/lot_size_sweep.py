"""Lot-size sweep for the squarish 2BR topology catalog.

For each squarish 2BR topology, finds the smallest lot that solves +
validates cleanly (no hard errors), and scans up through a range well past
the 2BR floor-area band so we can see (a) whether the solver ever goes
infeasible again at the high end and (b) at what lot/floor size the program
crosses into "big enough for 3BR" territory per the locked floor-area
bands (see memory: floor-area-per-br).

No carport (ncp), symmetric 2 m setbacks on all sides — the baseline case
most existing squarish test briefs use. Two lot-shape sweeps:
  - ratio 1.00 (square), fine step (0.5 m), 8-20 m
  - ratio 0.85 and 1.15 (near-square rectangles), coarser step (1.0 m)
Combos whose buildable envelope falls outside the "squarish" shell
category (aspect 0.80-1.30) are skipped — off-topic for this catalog.

Run from floorplan_v1/:  python3 lot_size_sweep.py
Writes floorplan_v1/output/lot_size_sweep_report.md and .json (regenerated
each run, gitignored like the rest of output/).
"""
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)   # so `import run` triggers run.py's own core/solver/ai path setup

from run import _run_hand_authored, Brief, _make_default_lot, shell_category  # noqa: E402

OUT_DIR = os.path.join(_HERE, "output")

TOPOLOGIES = [
    "1s/2br/squarish/1s_2br_sq_side_split_bath_ld.json",
    "1s/2br/squarish/1s_2br_sq_side_split_bath_pwd_gr.json",
    "1s/2br/squarish/1s_2br_sq_side_split_baths_cl_ld.json",
    "1s/2br/squarish/1s_2br_sq_side_split_baths_cl_hall_ld.json",
    "1s/2br/squarish/1s_2br_sq_side_split_baths_ds_ld.json",
]

# PH floor-area-per-bedroom-count bands (locked convention, single-storey,
# see memory: floor-area-per-br). Used here only to flag when a lot's floor
# area has grown past what a 2BR program should occupy.
BAND_2BR_1BATH = (45.0, 65.0)
BAND_2BR_2BATH = (65.0, 80.0)
BAND_3BR_KNEE = 80.0   # above this floor area, PH market practice swaps to 3BR

RATIO_SWEEPS = [
    (1.00, 0.5),   # (width/depth ratio, size step in m)
    (0.85, 1.0),
    (1.15, 1.0),
]
SIZE_MIN, SIZE_MAX = 8.0, 20.0   # depth range, m


def _sizes(step):
    n = int(round((SIZE_MAX - SIZE_MIN) / step))
    return [round(SIZE_MIN + step * i, 2) for i in range(n + 1)]


def make_brief(width, depth):
    return Brief(
        intent=f"lot-size sweep {width}x{depth}",
        lot_width=width, lot_depth=depth, bedroom_count=2,
        carport_side=None, carport_type=None,
        setbacks={"front": 2.0, "rear": 2.0, "left": 2.0, "right": 2.0},
    )


def band_flag(floor_area):
    if floor_area < BAND_2BR_1BATH[0]:
        return "below 2BR/1bath band"
    if floor_area <= BAND_2BR_1BATH[1]:
        return "2BR/1bath band"
    if floor_area <= BAND_2BR_2BATH[1]:
        return "2BR/2bath band"
    return "past 3BR knee (~80m2) -- lot big enough for 3BR"


def try_one(topology_filename, width, depth):
    brief = make_brief(width, depth)
    lot = _make_default_lot(brief)
    env = lot.envelope()
    shell = shell_category(lot)
    floor_area = round(env.w * env.h, 2)
    result = {
        "width": width, "depth": depth,
        "env_w": round(env.w, 2), "env_h": round(env.h, 2),
        "floor_area": floor_area, "shell": shell,
        "band": band_flag(floor_area),
    }
    if shell != "squarish":
        result.update(skipped="not squarish shell")
        return result
    t0 = time.time()
    try:
        layout, topo, reason = _run_hand_authored(
            brief, topology_filename, verbose=False, deterministic=True)
    except RuntimeError as e:
        result.update(ok=False, error=str(e)[:200], elapsed=round(time.time() - t0, 2))
        return result
    warns = [i for i in layout.issues if i.severity == "warning"]
    sugg = [i for i in layout.issues if i.severity == "suggestion"]
    result.update(
        ok=True, score=layout.score, warnings=len(warns), suggestions=len(sugg),
        warning_codes=[w.code for w in warns],
        elapsed=round(time.time() - t0, 2),
    )
    return result


def sweep_topology(topology_filename):
    print(f"=== {topology_filename} ===", flush=True)
    runs = []
    for ratio, step in RATIO_SWEEPS:
        for depth in _sizes(step):
            width = round(depth * ratio, 2)
            r = try_one(topology_filename, width, depth)
            r["ratio"] = ratio
            runs.append(r)
            tag = ("SKIP" if "skipped" in r else "PASS" if r.get("ok") else "FAIL")
            extra = (f"score={r.get('score', 0):.2f} warn={r.get('warnings', 0)}"
                     if r.get("ok") else r.get("error", r.get("skipped", "")))
            print(f"  [{tag}] {width}x{depth} (r={ratio})  env={r['env_w']}x{r['env_h']}"
                  f"  floor={r['floor_area']}m2  {extra}", flush=True)
    return runs


def summarize(topology_filename, runs):
    square = [r for r in runs if r["ratio"] == 1.00 and "skipped" not in r]
    passes = [r for r in square if r.get("ok")]
    fails_above_min = None
    min_pass = min(passes, key=lambda r: r["depth"]) if passes else None
    max_pass = max(passes, key=lambda r: r["depth"]) if passes else None
    # first infeasibility at a size larger than min_pass, if any (upper bound)
    if min_pass:
        larger_fails = [r for r in square
                         if not r.get("ok") and r["depth"] > min_pass["depth"]]
        fails_above_min = min(larger_fails, key=lambda r: r["depth"]) if larger_fails else None
    knee = next((r for r in square if r.get("ok") and r["floor_area"] > BAND_3BR_KNEE), None)
    return {
        "topology": topology_filename,
        "min_feasible": {"width": min_pass["width"], "depth": min_pass["depth"],
                          "floor_area": min_pass["floor_area"]} if min_pass else None,
        "max_feasible_tested": {"width": max_pass["width"], "depth": max_pass["depth"],
                                 "floor_area": max_pass["floor_area"]} if max_pass else None,
        "first_infeasible_above_min": {"width": fails_above_min["width"], "depth": fails_above_min["depth"]}
                                        if fails_above_min else None,
        "floor_area_crosses_3br_knee_at": {"width": knee["width"], "depth": knee["depth"],
                                            "floor_area": knee["floor_area"]} if knee else None,
    }


def render_report(all_runs, all_summaries):
    lines = ["# Lot-size sweep -- squarish 2BR topologies", "",
             f"ncp (no carport), symmetric 2 m setbacks, ratios "
             f"{', '.join(str(r) for r, _ in RATIO_SWEEPS)}, "
             f"depth range {SIZE_MIN}-{SIZE_MAX} m.", ""]
    for s in all_summaries:
        lines.append(f"## {s['topology']}")
        lines.append("")
        if s["min_feasible"]:
            mf = s["min_feasible"]
            lines.append(f"- **Smallest feasible square lot:** {mf['width']}x{mf['depth']} m "
                         f"(floor area {mf['floor_area']} m2)")
        else:
            lines.append("- **No feasible square lot found in tested range (8-20 m).**")
        if s["first_infeasible_above_min"]:
            fi = s["first_infeasible_above_min"]
            lines.append(f"- **Goes infeasible again above:** {fi['width']}x{fi['depth']} m")
        else:
            lines.append("- Stays feasible throughout the tested range above the minimum "
                         "(no upper infeasibility found up to 20x20 m).")
        if s["floor_area_crosses_3br_knee_at"]:
            k = s["floor_area_crosses_3br_knee_at"]
            lines.append(f"- **Floor area passes the ~80 m2 3BR knee at:** {k['width']}x{k['depth']} m "
                         f"(floor {k['floor_area']} m2) -- lots at/above this size are better suited "
                         f"to a 3BR program than a bigger 2BR.")
        if s["max_feasible_tested"]:
            mx = s["max_feasible_tested"]
            lines.append(f"- Largest square lot tested that still solves cleanly: "
                         f"{mx['width']}x{mx['depth']} m (floor {mx['floor_area']} m2)")
        lines.append("")
        lines.append("| lot (WxD) | ratio | envelope | floor m2 | band | result | score | warn |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in [x for x in all_runs if x["topology"] == s["topology"]]:
            if "skipped" in r:
                res = f"skip ({r['skipped']})"
                score = warn = "-"
            elif r.get("ok"):
                res = "PASS"
                score = f"{r['score']:.2f}"
                warn = str(r["warnings"])
            else:
                res = "FAIL"
                score = warn = "-"
            lines.append(f"| {r['width']}x{r['depth']} | {r['ratio']} | "
                         f"{r['env_w']}x{r['env_h']} | {r['floor_area']} | {r['band']} | "
                         f"{res} | {score} | {warn} |")
        lines.append("")
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_runs = []
    all_summaries = []
    t_start = time.time()
    for topo_fn in TOPOLOGIES:
        runs = sweep_topology(topo_fn)
        for r in runs:
            r["topology"] = topo_fn
        all_runs.extend(runs)
        all_summaries.append(summarize(topo_fn, runs))
    with open(os.path.join(OUT_DIR, "lot_size_sweep_raw.json"), "w") as f:
        json.dump({"runs": all_runs, "summaries": all_summaries}, f, indent=2)
    report = render_report(all_runs, all_summaries)
    report_path = os.path.join(OUT_DIR, "lot_size_sweep_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\ndone in {time.time() - t_start:.0f}s -- wrote {report_path}", flush=True)


if __name__ == "__main__":
    main()
