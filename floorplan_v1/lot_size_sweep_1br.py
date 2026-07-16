"""Lot-size sweep for the 1BR topology catalog (one topology per shape).

For each of the three 1BR topologies (squarish, wide, narrow), finds the
smallest lot that solves + validates cleanly and scans up through a range to
see (a) whether the solver goes infeasible again at the high end and (b) at
what lot/floor size the program would make more sense as a 2BR instead.

Unlike the squarish-2BR sweep (6 sibling topologies, one shape), this one
covers 3 shapes with only one topology each — so it's pinning down a single
min/max per shape, not a "safe across N topologies" number. Each shape gets
its own ratio range matching its target shell_category bucket(s):
  - squarish: ratio ~1.00 (bucket [0.80, 1.30))
  - wide:     ratio ~1.3-1.8 (bucket [1.30, 1.85))
  - narrow:   ratio ~0.3-0.75 (buckets 'deep' [0.55,0.80) + 'super_deep' (<0.55) --
              no literal "narrow" shell_category bucket exists; the topology's
              own target_shell label doesn't correspond 1:1 to shell_category's
              output, so this sweep calls _run_hand_authored directly instead
              of going through ai/match.py's shell filter)

No carport (ncp), symmetric 2 m setbacks on all sides.

Run from floorplan_v1/:  python3 lot_size_sweep_1br.py
Writes floorplan_v1/output/lot_size_sweep_1br_report.md and .json
(regenerated each run, gitignored like the rest of output/).
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)   # so `import run` triggers run.py's own core/solver/ai path setup

from run import _run_hand_authored, Brief, _make_default_lot, shell_category  # noqa: E402

OUT_DIR = os.path.join(_HERE, "output")

# (topology filename, list of (ratio, depth_range, step))
SHAPES = {
    "squarish": {
        "topology": "1s/1br/squarish/1s_1br_sq_side_split_bath_gr.json",
        "ratios": [(1.00, 6.0, 14.0, 0.5), (0.85, 8.0, 16.0, 1.0), (1.15, 6.0, 14.0, 1.0)],
    },
    "wide": {
        "topology": "1s/1br/wide/1s_1br_wd_side_split_bath_hall_gr.json",
        "ratios": [(1.40, 5.0, 12.0, 0.5), (1.60, 5.0, 12.0, 0.5), (1.30, 5.0, 12.0, 0.5)],
    },
    "narrow": {
        "topology": "1s/1br/narrow/1s_1br_nw_side_corridor_bath_hall.json",
        "ratios": [(0.45, 12.0, 22.0, 0.5), (0.35, 12.0, 22.0, 0.5), (0.55, 12.0, 22.0, 0.5)],
    },
}

# Candidate 1BR floor-area band (NOT yet locked in project memory -- each
# topology's own notes independently estimate 20-42 m2 buildable; this
# sweep is partly meant to pin down a real, empirically-verified number).
BAND_1BR_ESTIMATE = (20.0, 42.0)
BAND_2BR_KNEE = 45.0   # below the locked 2BR/1bath floor -- rough top-of-1BR marker


def make_brief(width, depth):
    return Brief(
        intent=f"1BR lot-size sweep {width}x{depth}",
        lot_width=width, lot_depth=depth, bedroom_count=1,
        carport_side=None, carport_type=None,
        setbacks={"front": 2.0, "rear": 2.0, "left": 2.0, "right": 2.0},
    )


def band_flag(floor_area):
    if floor_area < BAND_1BR_ESTIMATE[0]:
        return "below 1BR estimate band"
    if floor_area <= BAND_1BR_ESTIMATE[1]:
        return "1BR estimate band"
    if floor_area <= BAND_2BR_KNEE:
        return "above 1BR estimate, below 2BR/1bath floor"
    return "past 2BR/1bath floor (45m2) -- lot big enough for 2BR"


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
        fell_back="(fallback)" in str(reason),
    )
    return result


def _sizes(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [round(lo + step * i, 2) for i in range(n + 1)]


def sweep_shape(shape_name, spec):
    print(f"=== {shape_name}: {spec['topology']} ===", flush=True)
    runs = []
    for ratio, lo, hi, step in spec["ratios"]:
        for depth in _sizes(lo, hi, step):
            width = round(depth * ratio, 2)
            r = try_one(spec["topology"], width, depth)
            r["ratio"] = ratio
            runs.append(r)
            tag = "PASS" if r.get("ok") else "FAIL"
            extra = (f"score={r.get('score', 0):.2f} warn={r.get('warnings', 0)}"
                     + (" FALLBACK" if r.get("fell_back") else "")
                     if r.get("ok") else r.get("error", ""))
            print(f"  [{tag}] {width}x{depth} (r={ratio})  env={r['env_w']}x{r['env_h']}"
                  f"  shell={r['shell']}  floor={r['floor_area']}m2  {extra}", flush=True)
    return runs


def summarize(shape_name, runs):
    primary_ratio = SHAPES[shape_name]["ratios"][0][0]
    primary = [r for r in runs if r["ratio"] == primary_ratio]
    passes = [r for r in primary if r.get("ok")]
    min_pass = min(passes, key=lambda r: r["depth"]) if passes else None
    max_pass = max(passes, key=lambda r: r["depth"]) if passes else None
    fails_above_min = None
    if min_pass:
        larger_fails = [r for r in primary
                         if not r.get("ok") and r["depth"] > min_pass["depth"]]
        fails_above_min = min(larger_fails, key=lambda r: r["depth"]) if larger_fails else None
    clean = [r for r in passes if r.get("warnings", 1) == 0 and not r.get("fell_back")]
    return {
        "shape": shape_name,
        "topology": SHAPES[shape_name]["topology"],
        "primary_ratio": primary_ratio,
        "min_feasible": {"width": min_pass["width"], "depth": min_pass["depth"],
                          "floor_area": min_pass["floor_area"]} if min_pass else None,
        "max_feasible_tested": {"width": max_pass["width"], "depth": max_pass["depth"],
                                 "floor_area": max_pass["floor_area"]} if max_pass else None,
        "first_infeasible_above_min": {"width": fails_above_min["width"], "depth": fails_above_min["depth"]}
                                        if fails_above_min else None,
        "clean_range": {"min_depth": min(r["depth"] for r in clean),
                         "max_depth": max(r["depth"] for r in clean)} if clean else None,
    }


def render_report(all_runs, all_summaries):
    lines = ["# Lot-size sweep -- 1BR topology catalog (one topology per shape)", "",
             "ncp (no carport), symmetric 2 m setbacks. One topology per shape "
             "(no siblings yet), so this pins a single min/max per shape.", ""]
    for s in all_summaries:
        lines.append(f"## {s['shape']} -- {s['topology']}")
        lines.append("")
        if s["min_feasible"]:
            mf = s["min_feasible"]
            lines.append(f"- **Smallest feasible lot (ratio {s['primary_ratio']}):** "
                         f"{mf['width']}x{mf['depth']} m (floor area {mf['floor_area']} m2)")
        else:
            lines.append(f"- **No feasible lot found in tested range at ratio {s['primary_ratio']}.**")
        if s["first_infeasible_above_min"]:
            fi = s["first_infeasible_above_min"]
            lines.append(f"- **Goes infeasible again above:** {fi['width']}x{fi['depth']} m")
        else:
            lines.append("- Stays feasible throughout the tested range above the minimum.")
        if s["clean_range"]:
            cr = s["clean_range"]
            lines.append(f"- **Clean (0-warning, no-fallback) depth range:** "
                         f"{cr['min_depth']}-{cr['max_depth']} m")
        else:
            lines.append("- Never solves clean (0 warnings, no fallback) in tested range.")
        if s["max_feasible_tested"]:
            mx = s["max_feasible_tested"]
            lines.append(f"- Largest lot tested that still solves: "
                         f"{mx['width']}x{mx['depth']} m (floor {mx['floor_area']} m2)")
        lines.append("")
        lines.append("| lot (WxD) | ratio | envelope | shell | floor m2 | band | result | score | warn | fallback |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in [x for x in all_runs if x["shape"] == s["shape"]]:
            if r.get("ok"):
                res = "PASS"
                score = f"{r['score']:.2f}"
                warn = str(r["warnings"])
                fb = "yes" if r.get("fell_back") else "-"
            else:
                res = "FAIL"
                score = warn = fb = "-"
            lines.append(f"| {r['width']}x{r['depth']} | {r['ratio']} | "
                         f"{r['env_w']}x{r['env_h']} | {r['shell']} | {r['floor_area']} | {r['band']} | "
                         f"{res} | {score} | {warn} | {fb} |")
        lines.append("")
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_runs = []
    all_summaries = []
    t_start = time.time()
    for shape_name, spec in SHAPES.items():
        runs = sweep_shape(shape_name, spec)
        for r in runs:
            r["shape"] = shape_name
        all_runs.extend(runs)
        all_summaries.append(summarize(shape_name, runs))
    with open(os.path.join(OUT_DIR, "lot_size_sweep_1br_raw.json"), "w") as f:
        json.dump({"runs": all_runs, "summaries": all_summaries}, f, indent=2)
    report = render_report(all_runs, all_summaries)
    report_path = os.path.join(OUT_DIR, "lot_size_sweep_1br_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\ndone in {time.time() - t_start:.0f}s -- wrote {report_path}", flush=True)


if __name__ == "__main__":
    main()
