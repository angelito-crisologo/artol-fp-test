"""Main entry point for the prototype.

Runs both scenarios and writes a gallery per template plus a top-level index:
  - DEEP template on a 10x15 m (narrow/deep) lot   -> output/deep/
  - WIDE template on a 15x12 m (wide-frontage) lot  -> output/wide/

Run:  python3 generate.py
Pure standard library (SVG written directly; no external deps).
"""
import os
from model import Lot, shell_category
from rules import Rules
from engine import DEFAULTS
from optimizer import generate_candidates
from validator import is_compliant
from render import layout_to_svg, gallery_html

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# (template, lot width, lot depth, label, variants)
# Each variant is a dict of discrete overrides explored as a distinct candidate.
DEEP_VARIANTS = [
    {"master_position": "rear"},
    {"master_position": "front"},
]
WIDE_VARIANTS = [
    {"master_position": "rear", "ensuite_position": "alongside_master"},
    {"master_position": "rear", "ensuite_position": "twin_mid"},
    {"master_position": "rear", "ensuite_position": "twin_side"},
    {"master_position": "front", "ensuite_position": "twin_side"},
]
SINGLE_VARIANT = [{}]   # for reproduction templates that use their fixed defaults

SCENARIOS = [
    # (template_key, lot_w, lot_d, label, variants)
    ("narrow_stacked",         10.0, 15.0, "Narrow — narrow_stacked on 10x15 m lot",                                   DEEP_VARIANTS),
    ("squarish_two_bedroom",   13.0, 12.0, "Squarish — squarish_two_bedroom on 13x12 m lot",                            SINGLE_VARIANT),
    ("wide_hall_notch",        16.0, 11.0, "Wide — wide_hall_notch (notch + bath middle) on 16x11 m lot",               WIDE_VARIANTS),
    ("wide_central_hall",      16.0, 11.0, "Wide — wide_central_hall (faithful bungalow_wide) on 16x11 m lot",          SINGLE_VARIANT),
    ("wide_open_plan",         18.0, 11.0, "Wide — wide_open_plan (open great-room L-shape) on 18x11 m lot",            SINGLE_VARIANT),
]


def make_lot(rules: Rules, carport_side: str, width: float, depth: float) -> Lot:
    """That side's setback widens to 3 m; the opposite side and front/rear stay at 2 m."""
    sb = rules.v1["setbacks_applied_m"]
    wide, narrow = sb["carport_side"], sb["other_side"]
    return Lot(
        width=width, depth=depth, front=sb["front"], rear=sb["rear"],
        left=wide if carport_side == "left" else narrow,
        right=wide if carport_side == "right" else narrow,
        street_side="front",
    )


def run_scenario(rules: Rules, template: str, width: float, depth: float,
                 label: str, variants):
    outdir = os.path.join(OUT, template)
    os.makedirs(outdir, exist_ok=True)
    sample = make_lot(rules, "right", width, depth)
    env = sample.envelope()
    cat = shell_category(sample)
    print(f"\n=== {label} ===")
    print(f"buildable {env.w:.1f}x{env.h:.1f} m ({env.area:.0f} sqm) — shell category: {cat}")

    # enforce supported_shells: refuse mismatches with a clean message
    supported = DEFAULTS[template].get("supported_shells", [])
    if supported and cat not in supported:
        print(f"  SKIPPED — {template} supports {supported}, lot is {cat}")
        return []

    # faithful reproduction templates use their fixed intended proportions
    # (no SA exploration); generative templates optimize the cut ratios.
    optimize = template not in ("wide_open_plan", "wide_central_hall",
                                "squarish_two_bedroom")
    layouts = generate_candidates(
        lambda cs: make_lot(rules, cs, width, depth),
        rules, template=template, variants=variants, seeds_per_combo=6, iters=4000,
        optimize=optimize,
    )

    report = []
    for idx, L in enumerate(layouts, 1):
        with open(os.path.join(outdir, f"candidate_{idx}.svg"), "w", encoding="utf-8") as f:
            f.write(layout_to_svg(L))
        ok = is_compliant(L)
        sugg = sum(1 for i in L.issues if i.severity == "suggestion")
        ens = L.genome.get("ensuite_position", "-")
        line = (f"Candidate {idx}: {'COMPLIANT' if ok else 'NON-COMPLIANT'} | "
                f"master={L.genome.get('master_position')} | ensuite={ens} | "
                f"fitness={L.score:.2f} | footprint={L.footprint_area:.1f} sqm | "
                f"occupancy={L.occupancy_pct:.1f}% | {sugg} size-suggestions")
        print("  " + line)
        report.append(line)

    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(gallery_html(layouts, f"PH 2BR Floor Plan Generator — {label}"))
    with open(os.path.join(outdir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(label + "\n" + "\n".join(report) + "\n")
    return layouts


def write_top_index():
    links = "".join(
        f'<li><a href="{t}/index.html">{lbl}</a></li>'
        for t, _, _, lbl, _ in SCENARIOS
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>PH Floor Plan Generator — galleries</title>
<style>body{{font-family:Arial;margin:32px}} h1{{font-size:22px}} li{{margin:8px 0;font-size:16px}}</style>
</head><body><h1>PH 2BR Floor Plan Generator — candidate galleries</h1>
<ul>{links}</ul></body></html>"""
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    os.makedirs(OUT, exist_ok=True)
    rules = Rules()
    for template, w, d, label, variants in SCENARIOS:
        run_scenario(rules, template, w, d, label, variants)
    write_top_index()
    print(f"\nDone. Open {os.path.join(OUT, 'index.html')}")


if __name__ == "__main__":
    main()
