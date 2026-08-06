"""Polished 2D render of a solved floor plan, via Gemini "Nano Banana".

DELIBERATELY A SEPARATE COMMAND. See NANO_BANANA_RENDER_DESIGN.md §4.

    python3 run.py --brief=X       # solve + render. No polish flag exists.
    python3 polish.py --brief=X    # this tool, on an explicitly named plan

`run.py` does not import this module and has no polish option, so there is no
code path — enabled or disabled — from generating a floor plan to calling a
paid image API. Run `python3 polish.py --self-check` to verify that guarantee
still holds after any refactor.

Outputs, all beside the technical drawing in output/:
    <brief>_render.png      the polished image      (ILLUSTRATIVE ONLY)
    <brief>_source.svg      the drawing that was sent, as vectors
    <brief>_source.png      the exact raster that was sent
    <brief>_manifest.json   what we told the model was true
    <brief>_prompt.txt      what we asked for

The manifest and prompt are written every run so a bad image is auditable —
there is no automated fidelity check for this feature (design §6), so being
able to see exactly what was requested is the fallback.

THE POLISHED IMAGE IS NEVER THE PLAN OF RECORD. The dimensioned SVG is.
"""
import argparse
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _sub in ("core", "solver", "ai"):
    _p = os.path.join(_HERE, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ---------------------------------------------------------------------------
# Model + cost. Pinned HERE and nowhere else (design §3): image-model ids move
# faster than this repo does, so there is exactly one line to correct.
# ---------------------------------------------------------------------------
MODEL = os.environ.get("ARTOL_GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
EST_COST_USD = 0.04          # rough per-image; for the confirmation prompt only

_SECRETS = os.path.join(os.path.dirname(_HERE), ".streamlit", "secrets.toml")


def _api_key():
    """GEMINI_API_KEY from the environment, else .streamlit/secrets.toml."""
    k = os.environ.get("GEMINI_API_KEY")
    if k:
        return k
    try:
        import tomllib
        with open(_SECRETS, "rb") as f:
            return tomllib.load(f).get("GEMINI_API_KEY")
    except Exception:
        return None


def _render_png(layout, topo, brief_name, plain=False):
    """Rasterise the plan to PNG bytes — the composite for a 2-storey house
    (design decision #2), which is exactly what core/render.py already emits.

    Since PROMPT_VERSION 4 the drawing we send is FURNISHED: Phase E.2
    (`solver/fixtures.py`) places measured rectangles for bedrooms, baths and
    kitchens, and the prompt asks the model to reproduce them rather than
    invent its own. That narrows the model's job from designing to styling —
    the whole point of design §7 option C.

    `plain=True` sends the solver's drawing exactly as run.py writes it — no
    Phase E.2 furniture, no door marking — for testing a prompt against the
    unmodified output.

    Returns (png_bytes, svg_text, fixtures).
    """
    import cairosvg
    from render import (archplan_to_svg, compose_floor_svgs,
                        fixtures_overlay_svg, inject_overlay)
    from fixtures import place_fixtures

    fixtures = []

    def _one(plan, sub_layout):
        if plain:
            return archplan_to_svg(plan)
        rep = place_fixtures(sub_layout, plan)
        fixtures.extend(rep.fixtures)
        return inject_overlay(archplan_to_svg(plan, door_emphasis=True),
                              fixtures_overlay_svg(rep.fixtures, sub_layout))

    if getattr(layout, "archplan", None) is not None:
        svg = _one(layout.archplan, layout)
    else:
        # Each floor's ArchPlan carries its own per-floor sub-layout; using the
        # multi-storey parent here would place furniture against both storeys'
        # rooms at once (the trap recorded in CLAUDE.md).
        titled = [(title, _one(plan, plan.layout))
                  for title, plan in layout.archplans]
        svg = compose_floor_svgs(titled)
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=2.0), svg, fixtures


def _solve(brief_name):
    import run as R
    hits = [t for t in R.load_test_briefs() if t[0] == brief_name]
    if not hits:
        hits = [t for t in R.load_ai_briefs() if t[0] == brief_name]
        if hits:
            raise SystemExit(f"'{brief_name}' is an AI brief; polish.py currently "
                             f"expects a hand-authored brief with a topology.")
    if not hits:
        raise SystemExit(f"no brief named '{brief_name}'. "
                         f"Use the filename stem, e.g. "
                         f"1s_2br_15x15_sq_side_split_bath_ld_ncp")
    name, brief, topo_fn, adj, rel = hits[0]
    layout, topo, _ = R._run_hand_authored(brief, topo_fn, adjustments=adj,
                                           verbose=False, deterministic=True)
    return layout, topo, brief, R.OUT


def self_check() -> int:
    """Verify the isolation guarantee (design §4.1): nothing in the generation
    or publishing path may import this module or the prompt builder."""
    targets = ["run.py", "app.py",
               os.path.join("..", "tools", "topology_catalog", "build_catalog.py")]
    banned = ("polish", "render_prompt", "google.genai", "from google import genai")
    bad = []
    for t in targets:
        p = os.path.join(_HERE, t)
        if not os.path.exists(p):
            continue
        src = open(p, encoding="utf-8").read()
        for token in banned:
            for i, line in enumerate(src.splitlines(), 1):
                ls = line.strip()
                if token in ls and (ls.startswith("import ") or ls.startswith("from ")):
                    bad.append(f"{os.path.basename(p)}:{i}: {ls}")
    if bad:
        print("FAIL — the generation path imports the polish stack:")
        for b in bad:
            print("   ", b)
        return 1
    print("OK — run.py / app.py / build_catalog.py import neither polish.py, "
          "render_prompt, nor the Gemini SDK.")
    print("     No code path leads from generating a floor plan to a paid API call.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="floorplan_v1/polish.py",
        description="Polished 2D render of ONE explicitly named floor plan. "
                    "Never runs automatically; never part of run.py --test.")
    ap.add_argument("--brief", metavar="NAME",
                    help="REQUIRED. Brief filename stem. No sweep/glob mode — "
                         "this tool renders one named plan at a time.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the cost confirmation prompt.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write the manifest and prompt, make NO API call.")
    ap.add_argument("--self-check", action="store_true",
                    help="Verify nothing in the generation path imports this tool.")
    ap.add_argument("--prompt-file", metavar="PATH",
                    help="Send this file's text VERBATIM instead of the built "
                         "prompt. The manifest is still written for audit, but "
                         "nothing from it is appended.")
    ap.add_argument("--plain", action="store_true",
                    help="Send the solver's drawing unmodified — no Phase E.2 "
                         "furniture, no door marking.")
    ap.add_argument("--raw-output", action="store_true",
                    help="Write the model's image as-is; skip the crop/mask/"
                         "label composite.")
    args = ap.parse_args(argv)

    if args.self_check:
        return self_check()
    if not args.brief:
        ap.error("--brief is required (there is deliberately no 'polish everything' mode)")

    from render_manifest import build_manifest_for_layout
    from render_prompt import build_prompt, PROMPT_VERSION

    layout, topo, brief, out_dir = _solve(args.brief)
    # The raster is built FIRST: it is what places the furniture, and the
    # manifest must describe the image we actually send, not a different one.
    png, svg, fixtures = _render_png(layout, topo, args.brief, plain=args.plain)
    manifest = build_manifest_for_layout(layout, brief, fixtures)
    if args.prompt_file:
        # Verbatim. A hand-written prompt is a controlled experiment; silently
        # appending our manifest JSON or fidelity clauses would change what is
        # being tested and make the result unattributable.
        with open(args.prompt_file, encoding="utf-8") as f:
            prompt = f.read()
    else:
        prompt = build_prompt(manifest)

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, args.brief)
    with open(base + "_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    with open(base + "_prompt.txt", "w", encoding="utf-8") as f:
        f.write(prompt)
    # The SOURCE drawing this run actually sent. Written because polish.py
    # re-solves the brief rather than reading test_baselines/, so the two can
    # legitimately differ (baselines lag a solver change until refreshed) —
    # when a render looks wrong, the first question is whether the input was
    # what you expected. _source.png is the exact raster transmitted;
    # _source.svg is the same drawing as vectors, for close inspection.
    with open(base + "_source.svg", "w", encoding="utf-8") as f:
        f.write(svg)
    with open(base + "_source.png", "wb") as f:
        f.write(png)
    print(f"  wrote {base}_manifest.json")
    print(f"  wrote {base}_prompt.txt")
    print(f"  wrote {base}_source.svg   (the drawing sent to the model)")
    print(f"  wrote {base}_source.png   ({len(png)/1024:.0f} KB — the exact raster sent)")

    sig = hashlib.sha256(
        (PROMPT_VERSION + prompt).encode("utf-8") + png).hexdigest()[:16]
    out_png = base + "_render.png"
    stamp = base + "_render.sig"
    if os.path.exists(out_png) and os.path.exists(stamp):
        if open(stamp).read().strip() == sig:
            print(f"  up to date (cache {sig}) — nothing to do: {out_png}")
            return 0

    if args.dry_run:
        print("  --dry-run: no API call made.")
        return 0

    key = _api_key()
    if not key:
        raise SystemExit("no GEMINI_API_KEY (env or .streamlit/secrets.toml)")

    print(f"\n  brief : {args.brief}")
    print(f"  model : {MODEL}")
    print(f"  output: {out_png}")
    print(f"  cost  : ~${EST_COST_USD:.2f} for 1 image")
    if not args.yes:
        if input("  proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  aborted.")
            return 1

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=MODEL,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    data = None
    for cand in (resp.candidates or []):
        for part in (getattr(cand.content, "parts", None) or []):
            blob = getattr(part, "inline_data", None)
            if blob is not None and getattr(blob, "data", None):
                data = blob.data
                break
        if data:
            break
    if not data:
        txt = getattr(resp, "text", None)
        raise SystemExit(f"no image in the response. Model said: {txt!r}")

    with open(base + "_raw.png", "wb") as f:
        f.write(data)                       # exactly what came back, untouched
    print(f"  wrote {base}_raw.png  ({len(data)/1024:.0f} KB — model output as returned)")

    # PROMPT_VERSION 6: the model returns a text-free picture of the lot and
    # WE draw the words. Invented dimension figures were the one defect in
    # every render regardless of wording, so the opportunity is removed rather
    # than argued with. inject_overlay lays the returned image over our plan
    # and then lifts our own labels back on top of it — our coordinates, our
    # numbers — while the metre ruler survives because it sits outside the lot
    # rectangle the image covers.
    if args.raw_output:
        with open(out_png, "wb") as f:
            f.write(data)
        open(stamp, "w").write(sig)
        print(f"  wrote {out_png}  (raw, no composite)")
        print("  NOTE: illustrative only — the dimensioned SVG remains the "
              "plan of record.")
        return 0

    import cairosvg
    from render import (polished_image_overlay, inject_overlay,
                        room_label_masks)
    composed = inject_overlay(
        svg, polished_image_overlay(layout, data) + room_label_masks(layout))
    with open(base + "_render.svg", "w", encoding="utf-8") as f:
        f.write(composed)
    cairosvg.svg2png(bytestring=composed.encode("utf-8"), write_to=out_png,
                     scale=2.0)
    open(stamp, "w").write(sig)
    print(f"  wrote {base}_render.svg  (composite: model image + our labels)")
    print(f"  wrote {out_png}")
    print("  NOTE: illustrative only — the dimensioned SVG remains the plan of record.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
