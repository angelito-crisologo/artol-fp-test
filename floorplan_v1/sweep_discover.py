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
    # 1s_1br_sq_side_split_bath_gr is deliberately NOT in SPECS (2026-07-20,
    # same pattern as the narrow gr/ld siblings below). Its
    # briefs/test_sweep/ fixtures were pruned back to compact-only
    # (ratio-1.00 and near-square-1.15 "_compact" points; med/max removed)
    # now that 1s_1br_sq_side_split_bath_ld covers larger sizes instead.
    # Re-running `sweep_discover.py --topology=1s_1br_sq_side_split_bath_gr`
    # would need a SPECS entry re-added first -- not doing that accidentally
    # regenerates the med/max fixtures this restriction removed.
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
    # 1s_1br_nw_front_back_split_bath_gr and 1s_1br_nw_front_rear_bath_gr are
    # deliberately NOT in SPECS (2026-07-20). Their briefs/test_sweep/
    # fixtures were hand-curated instead of tool-discovered:
    #   - front_back_split_bath_gr: user-specified round-number progression
    #     8x10/9x11/10x12 (all verified feasible directly), not the tool's
    #     empirically-discovered 8x10/9.6x12/11.2x14.
    #   - front_rear_bath_gr: deliberately restricted to a single compact
    #     8x10 fixture, no _med/_max. Its bedroom is anchored to BOTH side
    #     walls (full-width by construction), which pins feasibility to a
    #     narrow ~7.5-8.0 m width corridor regardless of depth -- the
    #     fixed_widths sweep mode below (still useful as a pattern for
    #     similar topologies) found it stays feasible out to 8x19/60 m2,
    #     but that's well past this catalog's ~24-36 m2 working range for
    #     1BR, so larger sizes are being left unexplored/infeasible on
    #     purpose rather than characterized.
    # Re-running `sweep_discover.py --topology=<either id>` would need a
    # SPECS entry re-added first -- not doing that accidentally overwrites
    # these intentional choices with auto-discovered ones.
    # 1s_1br_wd_split_wing_bath_gr and 1s_1br_wd_side_split_bath_gr are
    # deliberately NOT in SPECS (2026-07-20, same pattern as the narrow
    # gr/ld siblings above). Both were originally ratio-shaped (canonical
    # ratio 1.25 / 10x8, empirically feasible 10x8 up to 15x12/88 m2 --
    # neither has a double-anchored room the way narrow front_rear_bath_gr
    # does, confirmed via left/right_anchored inspection before sweeping).
    # Their briefs/test_sweep/ fixtures are now hand-picked round numbers
    # (10x8/11x8/12x9) instead: 88 m2 was judged too big for a 1BR program
    # (past the 2BR/1bath 45 m2 floor-area knee) and tagged infeasible-by-
    # policy, so max was pulled back to 12x9/40 m2 -- still comfortably
    # inside the catalog's ~24-40 m2 working range for 1BR, all 3 points
    # verified feasible directly. Re-running `sweep_discover.py
    # --topology=<either id>` would need a SPECS entry re-added first --
    # not doing that accidentally regenerates the 88 m2 max these hand-
    # picked numbers replaced.
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


def _qualify_and_pick(runs, require_shell, want_median):
    qualifying = [r for r in runs if r["ok"] and r["shell"] == require_shell]
    if not qualifying:
        return None
    qualifying.sort(key=lambda r: r["depth"])
    points = {"min": qualifying[0], "max": qualifying[-1]}
    if want_median and len(qualifying) >= 3:
        points["med"] = _pick_median(qualifying)
    return points


def discover_ratio_class(topology_path, bedroom_count, ratio, depth_lo, depth_hi,
                         step, require_shell, want_median):
    """Width scales with depth (width = depth * ratio) -- for topologies whose
    feasibility tracks a fixed aspect ratio."""
    runs = []
    for depth in _sizes(depth_lo, depth_hi, step):
        width = round(depth * ratio, 2)
        runs.append(_try_one(topology_path, width, depth, bedroom_count))
    return _qualify_and_pick(runs, require_shell, want_median)


def discover_fixed_width_class(topology_path, bedroom_count, width, depth_lo, depth_hi,
                               step, require_shell, want_median):
    """Width held constant, only depth varies -- for topologies whose
    feasibility is bounded by an absolute width window (not a ratio) and
    where depth is otherwise free to grow, e.g. a shotgun/railroad narrow
    plan where every room's width is pinned by the shell but rooms can
    just get deeper. A ratio sweep can't find these: as depth grows at a
    fixed ratio, width drifts away from the narrow tolerance window and
    every point past the first misses."""
    runs = []
    for depth in _sizes(depth_lo, depth_hi, step):
        runs.append(_try_one(topology_path, width, depth, bedroom_count))
    return _qualify_and_pick(runs, require_shell, want_median)


def _brief_json(topology_id, topology_path, bedroom_count, point, label, ratio, tag):
    w, d = point["width"], point["depth"]
    if ratio is None:
        ratio_note = f" at a fixed width of {_fmt_num(point['width'])} m"
    elif ratio == 1.00:
        ratio_note = ""
    else:
        ratio_note = f" at a near-square ratio of {ratio}"
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

    classes = []
    for tag, ratio, lo, hi, step, require_shell, want_median in spec.get("ratios", []):
        classes.append(dict(tag=tag, kind="ratio", param=ratio, lo=lo, hi=hi, step=step,
                            require_shell=require_shell, want_median=want_median,
                            desc=f"ratio {ratio}"))
    for tag, width, lo, hi, step, require_shell, want_median in spec.get("fixed_widths", []):
        classes.append(dict(tag=tag, kind="width", param=width, lo=lo, hi=hi, step=step,
                            require_shell=require_shell, want_median=want_median,
                            desc=f"fixed width {width}"))

    for c in classes:
        if c["kind"] == "ratio":
            points = discover_ratio_class(
                spec["topology_path"], spec["bedroom_count"], c["param"], c["lo"], c["hi"],
                c["step"], c["require_shell"], c["want_median"])
            ratio_for_brief = c["param"]
        else:
            points = discover_fixed_width_class(
                spec["topology_path"], spec["bedroom_count"], c["param"], c["lo"], c["hi"],
                c["step"], c["require_shell"], c["want_median"])
            ratio_for_brief = None
        if points is None:
            print(f"  {c['desc']}: no feasible point classified as "
                 f"'{c['require_shell']}' in the swept range -- skipping, no files written")
            continue
        os.makedirs(out_dir, exist_ok=True)
        for label, point in points.items():
            suffix = "_".join(p for p in (c["tag"], label) if p)
            fname = f"{_brief_stem(topology_id, point)}_ncp_{suffix}.json"
            fpath = os.path.join(out_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(_brief_json(topology_id, spec["topology_path"],
                                      spec["bedroom_count"], point, label, ratio_for_brief,
                                      c["tag"]),
                         f, indent=2)
                f.write("\n")
            written.append(fpath)
            print(f"  {c['desc']} {label}{(' ' + c['tag']) if c['tag'] else ''}: "
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
