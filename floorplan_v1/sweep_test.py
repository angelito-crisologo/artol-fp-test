"""Solves every brief fixture under briefs/test_sweep/ and reports PASS/FAIL.

This is a separate, manually-run counterpart to `run.py --test`: it does
not touch briefs/test/, test_output/, or test_baselines/. It just solves
whatever brief-JSON fixtures already exist under briefs/test_sweep/
(written by `sweep_discover.py`) and renders them to sweep_output/
(gitignored scratch, mirrors test_output/'s role).

A PASS here means "still feasible" -- for a _min/_max fixture that's the
whole point (it's pinned at a discovered feasibility boundary), so a FAIL
after a solver or topology change is a real signal the boundary moved,
not necessarily a bug. Re-run sweep_discover.py to refresh the fixture
once you've confirmed the new boundary is expected.

Usage:
    python3 sweep_test.py                  # every fixture
    python3 sweep_test.py --topology=<id>  # only fixtures under that topology's folder
    python3 sweep_test.py --png            # also write PNGs (needs cairosvg)
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from run import _run_hand_authored, Brief, _write, _BRIEF_FIELDS  # noqa: E402

BRIEFS_SWEEP_DIR = os.path.join(_HERE, "briefs", "test_sweep")
SWEEP_OUT_DIR = os.path.join(_HERE, "sweep_output")


def _load_fixtures(topology_filter=None):
    out = []
    for root, _dirs, files in os.walk(BRIEFS_SWEEP_DIR):
        for fname in sorted(files):
            if not fname.endswith(".json"):
                continue
            full = os.path.join(root, fname)
            rel_dir = os.path.relpath(root, BRIEFS_SWEEP_DIR)
            if topology_filter and topology_filter not in rel_dir.replace(os.sep, "/"):
                continue
            with open(full, encoding="utf-8") as f:
                data = json.load(f)
            if "topology" not in data:
                continue
            name = os.path.splitext(fname)[0]
            kwargs = {k: data[k] for k in _BRIEF_FIELDS if k in data}
            brief = Brief(**kwargs)
            out.append((name, brief, data["topology"], rel_dir))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topology", metavar="ID",
                   help="Only run fixtures whose folder path contains this topology id")
    p.add_argument("--png", action="store_true", help="Also write PNGs (needs cairosvg)")
    args = p.parse_args()

    fixtures = _load_fixtures(args.topology)
    if not fixtures:
        print("no sweep fixtures found -- run sweep_discover.py first"
             + (f" for --topology={args.topology}" if args.topology else ""))
        return 1

    print(f"running {len(fixtures)} sweep fixture(s); writing to "
         f"{os.path.relpath(SWEEP_OUT_DIR, _HERE)}/\n")
    n_pass = n_fail = 0
    for name, brief, topology_fname, rel_dir in fixtures:
        print(f"--- {rel_dir}/{name}")
        try:
            layout, topo, reason = _run_hand_authored(
                brief, topology_fname, verbose=False, deterministic=True)
        except RuntimeError as e:
            print(f"  FAIL  {e}")
            n_fail += 1
            continue
        warns = sum(1 for i in layout.issues if i.severity == "warning")
        sugg = sum(1 for i in layout.issues if i.severity == "suggestion")
        _write(name, layout, topo, reason, rel_dir=rel_dir, out_root=SWEEP_OUT_DIR,
              write_png=args.png)
        print(f"  PASS  ({warns} warn, {sugg} sugg)")
        n_pass += 1

    print(f"\nsummary: {n_pass} pass, {n_fail} fail")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
