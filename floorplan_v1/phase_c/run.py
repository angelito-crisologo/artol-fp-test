"""End-to-end Phase C.1: topology + lot -> solve -> validate -> render.

Multi-shot over carport placement: tries the 3 m widened setback on the right,
left, and front of the same lot, runs the solver for each, and picks the
highest-scoring compliant layout. This is how "carport on the strategic side"
is realised without hard-coding which side.
"""
import os
import sys
import cairosvg

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from model import Lot                          # noqa: E402
from rules import Rules                        # noqa: E402
from validator import validate, is_compliant   # noqa: E402
from render import layout_to_svg               # noqa: E402

from topology import load_topology, validate_topology  # noqa: E402
from solver import solve                       # noqa: E402

OUT = os.path.join(_HERE, "output")
os.makedirs(OUT, exist_ok=True)


def make_lots(width: float, depth: float):
    """Return (label, Lot) candidates for the multi-shot."""
    return [
        ("right",
         Lot(width=width, depth=depth, front=2.0, rear=2.0, left=2.0, right=3.0,
             street_side="front")),
        ("left",
         Lot(width=width, depth=depth, front=2.0, rear=2.0, left=3.0, right=2.0,
             street_side="front")),
        ("front",
         Lot(width=width, depth=depth, front=3.0, rear=2.0, left=2.0, right=2.0,
             street_side="front")),
    ]


TOPOLOGIES = [
    "squarish_two_bedroom_distributed_baths.json",
    "squarish_two_bedroom_clustered_baths.json",
    "squarish_two_bedroom_split_stacked.json",
    "squarish_two_bedroom_split_openplan.json",
    "squarish_two_bedroom_rear_master.json",
    "squarish_two_bedroom_twin_ensuite.json",
]


def carport_to_living_distance(layout) -> float:
    """Manhattan distance between the carport's centre and the living room's
    centre. Used as a tie-break preference: when validator scores are tied,
    rank the candidate with the carport nearer to the living room first."""
    living = next((r for r in layout.rooms if r.type == "living_room"), None)
    carport = next((e for e in layout.elements if e.type == "carport"), None)
    if living is None or carport is None:
        return float("inf")
    lx = (living.rect.x0 + living.rect.x1) / 2
    ly = (living.rect.y0 + living.rect.y1) / 2
    cx = (carport.rect.x0 + carport.rect.x1) / 2
    cy = (carport.rect.y0 + carport.rect.y1) / 2
    return abs(lx - cx) + abs(ly - cy)


def main():
    rules = Rules()
    W, D = 13.0, 12.0
    print(f"lot {W}x{D} m ({W*D:.0f} sqm) | multi-variant catalog: "
          f"{len(TOPOLOGIES)} topology variant(s) x 3 carport positions\n")

    all_candidates = []
    for tname in TOPOLOGIES:
        tpath = os.path.join(_HERE, "topologies", tname)
        topo = load_topology(tpath)
        terrs = validate_topology(topo)
        if terrs:
            print(f"!! topology errors in {tname}: {terrs}")
            continue
        print(f"\n=== topology: {topo.id} ===")
        print(f"    {topo.label}")
        for clabel, lot in make_lots(W, D):
            env = lot.envelope()
            print(f"  -- carport @ {clabel}: buildable "
                  f"{env.w:.1f}x{env.h:.1f} m ({env.area:.1f} sqm) --")
            try:
                layout = solve(topo, lot, rules, time_limit_s=5.0, verbose=False)
            except RuntimeError as e:
                print(f"     no feasible layout ({e})")
                continue
            issues, score = validate(layout, rules)
            e_ = sum(1 for i in issues if i.severity == "error")
            w_ = sum(1 for i in issues if i.severity == "warning")
            s_ = sum(1 for i in issues if i.severity == "suggestion")
            tag = "COMPLIANT" if e_ == 0 else "NON-COMPLIANT"
            dist = carport_to_living_distance(layout) if e_ == 0 else float("inf")
            print(f"     {tag}  score={score:.2f}  errs={e_} warns={w_} sugg={s_}  "
                  f"carport→living {dist:.1f} m")
            if e_ == 0:
                all_candidates.append((topo.id, clabel, layout, score, w_, s_, dist))

    if not all_candidates:
        print("\nno feasible compliant layout for any variant x carport position")
        return

    # write per-variant per-carport renders for side-by-side comparison
    for tid, clabel, layout, score, _, _, _ in all_candidates:
        base = f"{tid}_carport_{clabel}"
        svg_path = os.path.join(OUT, f"{base}.svg")
        png_path = os.path.join(OUT, f"{base}.png")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(layout_to_svg(layout))
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=560)

    # rank lexicographically: highest validator score first, then ties broken
    # by carport-to-living distance (smaller = better) — preserves all options
    # in the catalog but defaults to the carport-near-living variant.
    all_candidates.sort(key=lambda c: (-c[3], c[6]))
    tid, clabel, best_layout, best_score, _, _, best_dist = all_candidates[0]
    print(f"\n=== best overall: {tid} / carport @ {clabel}  "
          f"score={best_score:.2f}  carport→living {best_dist:.1f} m ===")
    for r in best_layout.rooms:
        print(f"  {r.type:18s} {r.area:5.1f} sqm  least={r.least:.2f}  "
              f"({r.rect.w:.2f}x{r.rect.h:.2f})")

    svg_path = os.path.join(OUT, "squarish_two_bedroom_c1.svg")
    png_path = os.path.join(OUT, "squarish_two_bedroom_c1.png")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(layout_to_svg(best_layout))
    cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=560)
    print(f"\nwrote {len(all_candidates)} candidate(s) to {OUT}/")


if __name__ == "__main__":
    main()
