"""C.2 entry point — runs the pipeline on a few sample briefs and renders."""
import os
import sys

# cairosvg is optional — used to also write PNGs alongside SVGs. If the system
# cairo lib isn't installed, the pipeline still runs and SVGs are still written;
# you just won't get the PNG companions.
try:
    import cairosvg                            # noqa: F401
    _HAS_CAIROSVG = True
except (ImportError, OSError) as _e:
    _HAS_CAIROSVG = False
    print(f"note: cairosvg unavailable ({_e.__class__.__name__}); "
          f"will write SVGs only. Install with `brew install cairo libffi pango` "
          f"then `pip3 install cairosvg --break-system-packages`.")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "phase_c"))

from render import layout_to_svg               # noqa: E402

from brief import Brief                        # noqa: E402
from pipeline import run                       # noqa: E402

OUT = os.path.join(_HERE, "output")
os.makedirs(OUT, exist_ok=True)


# Anchor briefs covering the design philosophies our exemplar topologies
# represent. The pipeline should round-trip each into a compliant layout.
#
# Note: the public/private split topology is intentionally absent from the
# squarish anchors. On a 13x12 lot the buildable envelope is only 8x8 m and
# a vertical zone-split halves it again — bedrooms get squeezed to the 2.0 m
# hard minimum and the result is technically compliant but design-poor. The
# split variants (squarish_two_bedroom_split[_clustered_baths].json) remain
# in the topology catalog for later use on wider lots.
BRIEFS = [
    ("anchor_open",
     Brief(intent="A standard mid-market 2-bedroom open-plan home for a "
                  "young couple. Nothing fancy — comfortable living/dining, "
                  "bathrooms convenient to the bedrooms.",
           lot_width=13.0, lot_depth=12.0, bedroom_count=2)),
    ("anchor_clustered",
     Brief(intent="2-bedroom with a clustered wet core — we want the two "
                  "bathrooms to share a plumbing wall to keep maintenance simple.",
           lot_width=13.0, lot_depth=12.0, bedroom_count=2,
           must_haves=["clustered baths", "shared plumbing wall"])),
    # Novel brief — not directly covered by any exemplar. Tests whether Claude
    # can reason about noise without falling back on the hard zone-split.
    ("novel_wfh_couple",
     Brief(intent="2-bedroom for a couple who both work from home. The second "
                  "bedroom will double as a shared home office and needs to be "
                  "quiet — away from kitchen noise and the LDK chatter. Open "
                  "plan LDK is fine.",
           lot_width=13.0, lot_depth=12.0, bedroom_count=2,
           must_haves=["quiet second bedroom for home office", "open plan LDK"],
           avoid=["second bedroom next to kitchen"])),
]


def main():
    for name, brief in BRIEFS:
        print(f"\n{'=' * 70}\n=== {name} ===\n{'=' * 70}")
        try:
            layout, topo, reason = run(brief, verbose=True)
        except RuntimeError as e:
            print(f"\nFAILED: {e}")
            continue

        svg_path = os.path.join(OUT, f"{name}.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(layout_to_svg(layout))
        print(f"  wrote {svg_path}")
        if _HAS_CAIROSVG:
            png_path = os.path.join(OUT, f"{name}.png")
            try:
                cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=560)
                print(f"  wrote {png_path}")
            except Exception as e:
                print(f"  PNG conversion skipped: {e.__class__.__name__}: {e}")
        print(f"  topology chosen: {topo.id}")


if __name__ == "__main__":
    main()
