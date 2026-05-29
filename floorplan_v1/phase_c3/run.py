"""C.3 entry point — hybrid pipeline with caching for the AI path.

Two routes:

1. **Hand-authored anchors.** Each brief maps to a topology JSON. We load it,
   run the solver, render. Deterministic, zero API calls.

2. **AI-generated briefs.** Each brief is hashed into a cache key (intent +
   structured fields). If the cache has a topology for that key, we replay it
   through the solver — no API call. If not, we call Claude (temperature 0
   for repeatability), validate that the topology actually realises, cache
   the JSON, and render.

Edit the brief text or any requirement field and the cache key changes, so a
fresh Claude call is triggered automatically. Anything else (prompt updates,
solver tweaks, exemplar changes) doesn't invalidate the cache — runs against
the cached topology pick up those improvements without spending a token.

Outputs land in phase_c3/output/; cached topologies in phase_c3/cache/.
"""
import argparse
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))                               # shared modules
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "phase_c"))      # phase_c (solver, topology)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "phase_c2"))     # phase_c2 (brief, llm, pipeline)

try:
    import cairosvg                            # noqa: F401
    _HAS_CAIROSVG = True
except (ImportError, OSError) as _e:
    _HAS_CAIROSVG = False
    print(f"note: cairosvg unavailable ({_e.__class__.__name__}); "
          f"will write SVGs only. Install with `brew install cairo libffi pango` "
          f"then `pip3 install cairosvg --break-system-packages`.")

from model import shell_category                                 # noqa: E402
from rules import Rules                                          # noqa: E402
from validator import validate                                   # noqa: E402
from render import layout_to_svg                                 # noqa: E402

from topology import load_topology, validate_topology            # noqa: E402  (phase_c)
from solver import solve, AdjustmentError                        # noqa: E402  (phase_c)

from brief import Brief                                          # noqa: E402  (phase_c2)
from llm import ClaudeLLM, StubLLM                               # noqa: E402  (phase_c2)
from pipeline import (                                           # noqa: E402  (phase_c2)
    _topology_from_dict, _make_default_lot, MAX_REPAIR,
)


_TOPOLOGIES_DIR = os.path.join(os.path.dirname(_HERE), "phase_c", "topologies")
OUT = os.path.join(_HERE, "output")
VERSIONS_DIR = os.path.join(OUT, "versions")
CACHE_DIR = os.path.join(_HERE, "cache")
BRIEFS_DIR = os.path.join(_HERE, "briefs")
HAND_AUTHORED_DIR = os.path.join(BRIEFS_DIR, "hand_authored")
AI_DIR = os.path.join(BRIEFS_DIR, "ai")
os.makedirs(OUT, exist_ok=True)
os.makedirs(VERSIONS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(HAND_AUTHORED_DIR, exist_ok=True)
os.makedirs(AI_DIR, exist_ok=True)

AI_TEMPERATURE = 0.0   # set to None to use the API default (1.0)


# ---------- brief loading ----------
#
# Briefs live in phase_c3/briefs/ as one JSON file each:
#   briefs/hand_authored/<name>.json  →  pinned to a topology file (no AI call)
#   briefs/ai/<name>.json             →  Claude composes the topology
#
# Each file is a flat JSON object with the Brief fields (intent, lot_width,
# lot_depth, bedroom_count, must_haves, avoid, carport_preference). Hand-
# authored briefs additionally include a "topology" field naming a JSON in
# phase_c/topologies/. The brief name comes from the filename (without .json).
# Add, edit, or remove briefs by editing the JSON — no Python changes.

_BRIEF_FIELDS = ("intent", "lot_width", "lot_depth", "bedroom_count",
                 "must_haves", "avoid", "carport_preference")

_VALID_ADJUSTMENT_KEYS = {"min_area_sqm", "max_area_sqm",
                          "min_least_dim_m", "max_least_dim_m",
                          "min_greatest_dim_m", "max_greatest_dim_m"}


def _validate_adjustments(adjustments: dict, source_path: str):
    """Fail fast at brief-load time on typos and bad shapes. Catches:
      - unknown room type names (matched against ph_floorplan_rules.json)
      - unknown adjustment knob names
    The narrower 'type not in *this* topology' check still happens in the
    solver — it can't run here because for AI briefs the topology is composed
    by Claude after load. This is the cheap-fail tier."""
    if not adjustments:
        return
    valid_types = Rules().valid_room_types()
    bad_types = [k for k in adjustments if k not in valid_types]
    if bad_types:
        raise ValueError(
            f"{source_path}: adjustments references unknown room type(s) "
            f"{bad_types}. Valid types are: {sorted(valid_types)}")
    for room_type, knobs in adjustments.items():
        if not isinstance(knobs, dict):
            raise ValueError(
                f"{source_path}: adjustments[{room_type!r}] must be an object "
                f"(got {type(knobs).__name__})")
        bad_knobs = [k for k in knobs if k not in _VALID_ADJUSTMENT_KEYS]
        if bad_knobs:
            raise ValueError(
                f"{source_path}: adjustments[{room_type!r}] has unknown knob(s) "
                f"{bad_knobs}. Valid knobs: {sorted(_VALID_ADJUSTMENT_KEYS)}")


def _name_from_path(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _brief_from_json(data: dict, source_path: str) -> Brief:
    """Build a Brief from a JSON dict; raise if required fields missing."""
    missing = [f for f in ("intent", "lot_width", "lot_depth")
               if f not in data]
    if missing:
        raise ValueError(f"{source_path}: missing required field(s) {missing}")
    kwargs = {f: data[f] for f in _BRIEF_FIELDS if f in data}
    return Brief(**kwargs)


def _load_briefs_from(subdir: str, expect_topology: bool):
    """Scan a brief subdir, sort by filename, return a list of tuples.

    For hand_authored: (name, brief, topology_filename, adjustments).
    For ai:           (name, brief, use_cache, adjustments).

    `adjustments` is an optional per-room-type override dict from the brief JSON
    (key: room type name, value: {min_area_sqm, max_area_sqm, min_least_dim_m}).
    Routed to the solver as a soft overlay; deliberately NOT part of the cache
    key so editing adjustments re-solves geometry without re-calling Claude.
    """
    if not os.path.isdir(subdir):
        return []
    out = []
    for fname in sorted(os.listdir(subdir)):
        if not fname.endswith(".json"):
            continue
        p = os.path.join(subdir, fname)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = _name_from_path(p)
        brief = _brief_from_json(data, p)
        adjustments = data.get("adjustments", {}) or {}
        _validate_adjustments(adjustments, p)
        if expect_topology:
            if "topology" not in data:
                raise ValueError(f"{p}: hand-authored brief must include a "
                                 f"'topology' field naming a file in "
                                 f"phase_c/topologies/")
            out.append((name, brief, data["topology"], adjustments))
        else:
            # AI briefs accept an optional "use_cache" flag. Default true.
            # Set false to force a fresh Claude call (cache read is skipped;
            # the new result is still written so future cache-on runs pick it up).
            use_cache = bool(data.get("use_cache", True))
            out.append((name, brief, use_cache, adjustments))
    return out


def load_hand_authored_anchors():
    return _load_briefs_from(HAND_AUTHORED_DIR, expect_topology=True)


def load_ai_briefs():
    return _load_briefs_from(AI_DIR, expect_topology=False)


# ---------- caching ----------

def _brief_cache_key(brief: Brief) -> str:
    """Stable hash over the requirement fields the user controls. Any change
    to text or structured fields produces a different key and forces a fresh
    Claude call; prompt/solver/exemplar changes do not."""
    payload = {
        "intent": brief.intent.strip(),
        "lot_width": brief.lot_width,
        "lot_depth": brief.lot_depth,
        "bedroom_count": brief.bedroom_count,
        "must_haves": list(brief.must_haves),
        "avoid": list(brief.avoid),
        "carport_preference": brief.carport_preference,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_path(brief: Brief) -> str:
    return os.path.join(CACHE_DIR, f"{_brief_cache_key(brief)}.json")


def _load_cached(brief: Brief):
    p = _cache_path(brief)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["topology"], data.get("reason", "[cache] (no reason)")


def _save_cache(brief: Brief, topology_dict: dict, reason: str):
    with open(_cache_path(brief), "w", encoding="utf-8") as f:
        json.dump({
            "brief_summary": brief.summary(),
            "reason": reason,
            "topology": topology_dict,
        }, f, indent=2)


def _invalidate(brief: Brief):
    p = _cache_path(brief)
    if os.path.exists(p):
        os.unlink(p)


# ---------- AI client ----------

def _make_ai_client():
    """Build a deterministic Claude client when a key is available; otherwise
    fall back to the StubLLM picker. Same interface either way."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            return ClaudeLLM(api_key=key, temperature=AI_TEMPERATURE)
        except ImportError:
            print("note: ANTHROPIC_API_KEY set but anthropic library missing — "
                  "run: pip install anthropic --break-system-packages")
            print("falling back to StubLLM for now.")
    return StubLLM()


# ---------- runners ----------

def _run_hand_authored(brief: Brief, topology_filename: str,
                       adjustments: dict = None, verbose: bool = True):
    """Load named topology, solve, validate. No API call."""
    rules = Rules()
    lot = _make_default_lot(brief)
    shell = shell_category(lot)
    env = lot.envelope()
    if verbose:
        print(brief.summary())
        print(f"shell category: {shell}  |  buildable {env.w:.1f}x{env.h:.1f} m")
        print(f"\n[hand-authored]  topology: {topology_filename}")
        if adjustments:
            print(f"  adjustments: {adjustments}")
    topo = load_topology(os.path.join(_TOPOLOGIES_DIR, topology_filename))
    layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False,
                   adjustments=adjustments)
    issues, score = validate(layout, rules)
    errs = [i for i in issues if i.severity == "error"]
    if errs:
        raise RuntimeError(
            f"hand-authored topology {topology_filename} failed validation: "
            + "; ".join(str(e) for e in errs[:3]))
    if verbose:
        warns = [i for i in issues if i.severity == "warning"]
        sugg = [i for i in issues if i.severity == "suggestion"]
        print(f"  COMPLIANT  score={score:.2f}  {len(warns)} warn  {len(sugg)} sugg")
    reason = f"[hand-authored] using {topology_filename} (no API call)"
    return layout, topo, reason


def _try_realize(topo_dict: dict, brief: Brief, rules: Rules,
                 adjustments: dict = None):
    """Run a topology dict through solve+validate. Returns (layout, topology,
    score) on success or raises with a human-readable reason."""
    topo = _topology_from_dict(topo_dict)
    errs = validate_topology(topo)
    if errs:
        raise RuntimeError("structural topology errors: " + "; ".join(errs))
    lot = _make_default_lot(brief)
    layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False,
                   adjustments=adjustments)
    issues, score = validate(layout, rules)
    hard = [i for i in issues if i.severity == "error"]
    if hard:
        raise RuntimeError("validator caught hard violation(s): "
                           + "; ".join(str(i) for i in hard[:3]))
    return layout, topo, score, issues


def _run_ai_with_cache(brief: Brief, use_cache: bool = True,
                       adjustments: dict = None, verbose: bool = True):
    """Cache → solver path. On cache miss (or `use_cache=False`), call Claude
    with the repair loop. Successful topologies are always written to the
    cache, even when use_cache=False — the flag only controls whether we
    READ from the cache.

    `adjustments` is forwarded to the solver but NOT part of the cache key,
    so re-running with new adjustments resolves geometry without re-calling
    Claude."""
    rules = Rules()
    lot = _make_default_lot(brief)
    env = lot.envelope()
    if verbose:
        print(brief.summary())
        print(f"shell category: {shell_category(lot)}  |  buildable {env.w:.1f}x{env.h:.1f} m")
        print(f"cache key: {_brief_cache_key(brief)}  (use_cache={use_cache})")
        if adjustments:
            print(f"adjustments: {adjustments}")

    # ----- cache hit attempt (only when use_cache=True) -----
    cached = _load_cached(brief) if use_cache else None
    if cached is not None:
        topo_dict, cached_reason = cached
        try:
            layout, topo, score, issues = _try_realize(topo_dict, brief, rules, adjustments)
            warns = [i for i in issues if i.severity == "warning"]
            sugg = [i for i in issues if i.severity == "suggestion"]
            reason = f"[cache] {cached_reason}"
            if verbose:
                print(f"\n[cache hit]  no API call")
                print(f"  cached reason: {cached_reason}")
                print(f"  COMPLIANT  score={score:.2f}  {len(warns)} warn  {len(sugg)} sugg")
            return layout, topo, reason
        except AdjustmentError as e:
            # User-side mismatch between adjustments and the cached topology
            # (e.g., adjusting `great_room` when the cached topology has no
            # great_room). Preserve the cache, fail loud.
            raise RuntimeError(
                f"adjustments don't match the cached topology: {e}\n"
                f"  the cached topology is preserved at {_cache_path(brief)}\n"
                f"  options: (1) relax/edit the adjustments to use a room type "
                f"that the cached topology contains; (2) set use_cache=false "
                f"in the brief to let Claude compose a new topology."
            )
        except RuntimeError as e:
            # use_cache=True is strict: NEVER silently invalidate the cache
            # and regenerate. Most common cause when this hits is an over-
            # constrained adjustment (solver returns INFEASIBLE). The user
            # asked to preserve the topology — preserving means refusing to
            # let it be silently replaced. They can either relax constraints
            # or set use_cache=false to opt into regeneration.
            raise RuntimeError(
                f"cached topology can't realize the current constraints: {e}\n"
                f"  the cached topology is preserved at {_cache_path(brief)}\n"
                f"  options:\n"
                f"    (1) relax the adjustments so the cached topology can fit them,\n"
                f"    (2) set use_cache=false in the brief to let Claude compose "
                f"a new topology,\n"
                f"    (3) delete the cache file manually if you believe it is "
                f"actually corrupted."
            )

    # ----- fresh call (cache miss, or use_cache=False forcing regeneration) -----
    if verbose and not use_cache:
        cached_exists = os.path.exists(_cache_path(brief))
        msg = ("overriding existing cache entry" if cached_exists
               else "no cache entry exists for this brief")
        print(f"\n[use_cache=False]  {msg} — calling Claude fresh")
    client = _make_ai_client()
    error_feedback = None
    last_topo_dict = None
    last_reason = None
    for attempt in range(1 + MAX_REPAIR):
        if verbose:
            tag = "first attempt" if attempt == 0 else f"repair attempt {attempt}"
            print(f"\n[{tag}]  LLM client: {type(client).__name__}")
        topo_dict, reason = client.generate(brief, error_feedback=error_feedback)
        if verbose:
            print(f"  reasoning: {reason}")
        try:
            layout, topo, score, issues = _try_realize(topo_dict, brief, rules, adjustments)
        except AdjustmentError as e:
            # User-side error — Claude can't fix it by composing a new
            # topology. Bubble up immediately instead of burning repair attempts.
            raise RuntimeError(
                f"adjustments don't match Claude's composed topology: {e}\n"
                f"  fix the adjustments and re-run."
            )
        except RuntimeError as e:
            error_feedback = str(e)
            if verbose:
                print(f"  failed: {e}")
            continue
        # success
        _save_cache(brief, topo_dict, reason)
        warns = [i for i in issues if i.severity == "warning"]
        sugg = [i for i in issues if i.severity == "suggestion"]
        if verbose:
            print(f"  COMPLIANT  score={score:.2f}  {len(warns)} warn  {len(sugg)} sugg")
            print(f"  cached to {_cache_path(brief)}")
        return layout, topo, reason

    raise RuntimeError(
        f"could not produce a feasible layout after {1 + MAX_REPAIR} attempts. "
        f"last feedback: {error_feedback}"
    )


import re                                                       # noqa: E402


def _next_version_for(name: str) -> int:
    """Find the next available v<N> archive number for this brief."""
    pat = re.compile(rf"^{re.escape(name)}_v(\d+)\.svg$")
    highest = 0
    if os.path.isdir(VERSIONS_DIR):
        for fname in os.listdir(VERSIONS_DIR):
            m = pat.match(fname)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def _archive_existing(name: str) -> int:
    """If <name>.svg already exists in OUT, move it (and its .png companion)
    into VERSIONS_DIR as <name>_v<N>.svg. Returns the N used, or 0 if nothing
    was archived."""
    svg_path = os.path.join(OUT, f"{name}.svg")
    png_path = os.path.join(OUT, f"{name}.png")
    if not os.path.exists(svg_path):
        return 0
    n = _next_version_for(name)
    os.rename(svg_path, os.path.join(VERSIONS_DIR, f"{name}_v{n}.svg"))
    if os.path.exists(png_path):
        os.rename(png_path, os.path.join(VERSIONS_DIR, f"{name}_v{n}.png"))
    return n


def _write(name, layout, topo, reason, no_version=False):
    # Preserve the previous latest (if any) under versions/<name>_v<N>.svg
    # before overwriting. Skipped when --no-version is passed.
    if not no_version:
        archived = _archive_existing(name)
        if archived:
            print(f"  archived previous as versions/{name}_v{archived}.svg")

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
    print(f"  reasoning: {reason}")
    print(f"  topology id: {topo.id}")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="phase_c3/run.py",
        description="Hybrid hand-authored + AI floor-plan pipeline. "
                    "By default runs every brief in phase_c3/briefs/.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--brief", metavar="NAME",
                   help="Only run the brief with this filename stem "
                        "(e.g. 'novel_wfh_couple' or 'anchor_open'). "
                        "Combine with --mode to disambiguate if the same "
                        "name exists in both subfolders.")
    p.add_argument("--mode", choices=("hand_authored", "ai", "all"),
                   default="all",
                   help="Restrict to one section. 'hand_authored' skips all "
                        "Claude calls; 'ai' skips deterministic anchors.")
    p.add_argument("--no-version", action="store_true",
                   help="Overwrite existing output files instead of archiving "
                        "the previous version into output/versions/. By default "
                        "each re-run preserves the prior layout under "
                        "<name>_v<N>.svg so you can compare iterations.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    hand_authored = load_hand_authored_anchors()
    ai_briefs = load_ai_briefs()

    if args.mode == "hand_authored":
        ai_briefs = []
    elif args.mode == "ai":
        hand_authored = []

    if args.brief:
        hand_authored = [t for t in hand_authored if t[0] == args.brief]
        ai_briefs    = [t for t in ai_briefs    if t[0] == args.brief]
        if not hand_authored and not ai_briefs:
            print(f"no brief matches --brief={args.brief!r}"
                  f"{f' under --mode={args.mode}' if args.mode != 'all' else ''}")
            print(f"  available in hand_authored/: "
                  f"{[t[0] for t in load_hand_authored_anchors()]}")
            print(f"  available in ai/:            "
                  f"{[t[0] for t in load_ai_briefs()]}")
            sys.exit(1)

    print(f"loaded {len(hand_authored)} hand-authored brief(s) from "
          f"{os.path.relpath(HAND_AUTHORED_DIR, _HERE)}/")
    print(f"loaded {len(ai_briefs)} AI brief(s) from "
          f"{os.path.relpath(AI_DIR, _HERE)}/")

    # Section 1 — hand-authored anchors.
    for name, brief, topology_fname, adjustments in hand_authored:
        print(f"\n{'=' * 70}\n=== {name}   (hand-authored)\n{'=' * 70}")
        try:
            layout, topo, reason = _run_hand_authored(
                brief, topology_fname, adjustments=adjustments)
        except RuntimeError as e:
            print(f"FAILED: {e}")
            continue
        _write(name, layout, topo, reason, no_version=args.no_version)

    # Section 2 — AI briefs (cache controlled per-brief by use_cache flag).
    for name, brief, use_cache, adjustments in ai_briefs:
        tag = "AI-generated, cached" if use_cache else "AI-generated, FRESH (cache disabled)"
        print(f"\n{'=' * 70}\n=== {name}   ({tag})\n{'=' * 70}")
        try:
            layout, topo, reason = _run_ai_with_cache(
                brief, use_cache=use_cache, adjustments=adjustments, verbose=True)
        except RuntimeError as e:
            print(f"FAILED: {e}")
            continue
        _write(name, layout, topo, reason, no_version=args.no_version)


if __name__ == "__main__":
    main()
