"""Discovers empirical min/med/max feasible lot sizes for a topology (per
ratio class) and writes them as brief-JSON fixtures under
briefs/test_sweep/, mirroring the topologies/ directory hierarchy with one
folder per topology.

This is a discovery tool. Run it manually, only when a topology or solver
change might plausibly shift feasibility boundaries -- it is NOT part of
the regular `run.py --test` regression suite and does not touch
briefs/test/ or test_output/. Re-run it to refresh a topology's sweep
fixtures; the companion `sweep_test.py` then just solves whatever briefs
already exist here (fast -- no re-sweeping).

Each ratio class in a topology's spec can require a specific shell
category ("squarish"/"narrow"/"wide"/"extra_wide"). A lot can solve
geometrically but land in the "wrong" shell bucket due to fixed-setback
distortion (see LOT_SIZE_SWEEP_FINDINGS.md) -- those points don't count
for that ratio class's real-world matcher coverage and are excluded, not
just deprioritized. If NO point in the swept range is both feasible and
correctly classified, no files are written for that ratio class and the
run prints why.

"med" (median) is only written when the ratio class asks for one AND at
least 3 qualifying points exist -- it's the qualifying point closest to
the midpoint of the observed min/max, tie-breaking toward the smaller
size, never an interpolated/untested size.

Usage:
    python3 sweep_discover.py                  # every topology in SPECS
    python3 sweep_discover.py --topology=<id>   # just one
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)  # so `import run` triggers run.py's own core/solver/ai path setup

from run import _run_hand_authored, Brief, _make_default_lot, shell_category  # noqa: E402

BRIEFS_SWEEP_DIR = os.path.join(_HERE, "briefs", "test_sweep")

# One entry per topology. `ratios` is a list of ratio-class specs:
#   (tag, ratio, depth_lo, depth_hi, step, require_shell, want_median)
# `tag` is appended to filenames for non-primary ratio classes ("" for the
# topology's natural/primary ratio -- no tag needed there).
SPECS = {
    "1s_1br_sq_side_split_bath_gr": {
        "topology_path": "1s/1br/squarish/1s_1br_sq_side_split_bath_gr.json",
        "folder": "1s/1br/squarish/1s_1br_sq_side_split_bath_gr",
        "bedroom_count": 1,
        "ratios": [
            ("",     1.00, 6.0, 14.0, 0.5, "squarish", True),
            ("r115", 1.15, 6.0, 14.0, 0.5, "squarish", False),
            ("r085", 0.85, 8.0, 25.0, 0.5, "squarish", False),
        ],
    },
    "1s_1br_sq_side_split_bath_ld": {
        "topology_path": "1s/1br/squarish/1s_1br_sq_side_split_bath_ld.json",
        "folder": "1s/1br/squarish/1s_1br_sq_side_split_bath_ld",
        "bedroom_count": 1,
        "ratios": [
            ("",     1.00, 6.0, 14.0, 0.5, "squarish", True),
            ("r115", 1.15, 6.0, 14.0, 0.5, "squarish", False),
            ("r085", 0.85, 8.0, 25.0, 0.5, "squarish", False),
        ],
    },
}


def _fmt_num(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else f"{x:g}"


def _sizes(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [round(lo + step * i, 2) for i in range(n + 1)]


def _try_one(topology_path, width, depth, bedroom_count):
    brief = Brief(
        intent=f"sweep probe {width}x{depth}", lot_width=width, lot_depth=depth,
        bedroom_count=bedroom_count, carport_side=None, carport_type=None,
        setbacks={"front": 2.0, "rear": 2.0, "left": 2.0, "right": 2.0},
    )
    lot = _make_default_lot(brief)
    shell = shell_category(lot)
    env = lot.envelope()
    try:
        _run_hand_authored(brief, topology_path, verbose=False, deterministic=True)
        ok = True
    except RuntimeError:
        ok = False
    return dict(width=width, depth=depth, shell=shell, ok=ok,
               floor_area=round(env.w * env.h, 2))


def _pick_median(qualifying):
    """Qualifying point closest to the min/max midpoint; ties -> smaller."""
    depths = sorted(r["depth"] for r in qualifying)
    mid = (depths[0] + depths[-1]) / 2.0
    best = min(qualifying, key=lambda r: (abs(r["depth"] - mid), r["depth"]))
    return best


def discover_ratio_class(topology_path, bedroom_count, ratio, depth_lo, depth_hi,
                         step, require_shell, want_median):
    runs = []
    for depth in _sizes(depth_lo, depth_hi, step):
        width = round(depth * ratio, 2)
        runs.append(_try_one(topology_path, width, depth, bedroom_count))
    qualifying = [r for r in runs if r["ok"] and r["shell"] == require_shell]
    if not qualifying:
        return None
    qualifying.sort(key=lambda r: r["depth"])
    points = {"min": qualifying[0], "max": qualifying[-1]}
    if want_median and len(qualifying) >= 3:
        points["med"] = _pick_median(qualifying)
    return points


def _brief_json(topology_id, topology_path, bedroom_count, point, label, ratio, tag):
    w, d = point["width"], point["depth"]
    ratio_note = "" if ratio == 1.00 else f" at a near-square ratio of {ratio}"
    return {
        "intent": (
            f"Sweep fixture ({label.upper()}{(' ' + tag) if tag else ''}) for "
            f"{topology_id}{ratio_note} -- {_fmt_num(w)}x{_fmt_num(d)} m lot, "
            f"{point['floor_area']} m2 buildable floor. Discovered empirically by "
            f"sweep_discover.py; re-run that script to refresh if the solver or "
            f"this topology changes."
        ),
        "lot_width": w,
        "lot_depth": d,
        "bedroom_count": bedroom_count,
        "must_haves": [],
        "avoid": [],
        "occupancy_class": "R-1",
        "setbacks": {"front": 2.0, "rear": 2.0, "left": 2.0, "right": 2.0},
        "topology": topology_path,
    }


def discover_topology(topology_id, spec):
    print(f"=== {topology_id} ===")
    out_dir = os.path.join(BRIEFS_SWEEP_DIR, spec["folder"])
    written = []
    for tag, ratio, lo, hi, step, require_shell, want_median in spec["ratios"]:
        points = discover_ratio_class(
            spec["topology_path"], spec["bedroom_count"], ratio, lo, hi, step,
            require_shell, want_median)
        if points is None:
            print(f"  ratio {ratio}: no feasible point classified as "
                 f"'{require_shell}' in the swept range -- skipping, no files written")
            continue
        os.makedirs(out_dir, exist_ok=True)
        for label, point in points.items():
            suffix = "_".join(p for p in (tag, label) if p)
            fname = f"{_brief_stem(topology_id, point)}_ncp_{suffix}.json"
            fpath = os.path.join(out_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(_brief_json(topology_id, spec["topology_path"],
                                      spec["bedroom_count"], point, label, ratio, tag),
                         f, indent=2)
                f.write("\n")
            written.append(fpath)
            print(f"  ratio {ratio} {label}{(' ' + tag) if tag else ''}: "
                 f"{point['width']}x{point['depth']} ({point['floor_area']} m2) "
                 f"-> {os.path.relpath(fpath, _HERE)}")
    return written


def _brief_stem(topology_id, point):
    # Reuse the project's storey/nbr prefix from the topology id, swap in
    # the discovered lot dims: 1s_1br_sq_side_split_bath_gr -> 1s_1br_8.5x8.5_sq_side_split_bath_gr
    parts = topology_id.split("_")
    storey, nbr = parts[0], parts[1]
    rest = "_".join(parts[2:])
    return f"{storey}_{nbr}_{_fmt_num(point['width'])}x{_fmt_num(point['depth'])}_{rest}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topology", metavar="ID", help="Only discover this topology id")
    args = p.parse_args()

    targets = {args.topology: SPECS[args.topology]} if args.topology else SPECS
    if args.topology and args.topology not in SPECS:
        print(f"no SPECS entry for topology {args.topology!r} -- add one in sweep_discover.py")
        return 1

    all_written = []
    for topology_id, spec in targets.items():
        all_written.extend(discover_topology(topology_id, spec))
    print(f"\nwrote {len(all_written)} sweep brief(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
