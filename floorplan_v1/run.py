"""artol-ai entry point — hybrid pipeline.

Two routes:

1. **Hand-authored anchors.** Each brief maps to a topology JSON. We load it,
   run the solver, render. Deterministic, zero API calls.

2. **AI-generated briefs.** Claude composes a topology from scratch, validates
   it realises on the given lot, and renders. Retries up to MAX_REPAIR times
   on infeasibility. Every run calls the API — no caching.

Outputs land in floorplan_v1/output/.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Project is laid out as three sibling sub-packages of bare-import modules:
#   core/   — model, rules, render, validator, setback_elements
#   solver/ — topology, solver, snap_gaps, architectural_plan, fixture_orientation
#   ai/     — brief, prompt, llm, pipeline
# Adding each subdir to sys.path lets us keep simple bare imports below.
sys.path.insert(0, os.path.join(_HERE, "core"))
sys.path.insert(0, os.path.join(_HERE, "solver"))
sys.path.insert(0, os.path.join(_HERE, "ai"))

try:
    import cairosvg                            # noqa: F401
    _HAS_CAIROSVG = True
except (ImportError, OSError) as _e:
    _HAS_CAIROSVG = False
    print(f"note: cairosvg unavailable ({_e.__class__.__name__}); "
          f"will write SVGs only. Install with `brew install cairo libffi pango` "
          f"then `pip3 install cairosvg --break-system-packages`.")

from model import shell_category                                 # noqa: E402  (core)
from rules import Rules                                          # noqa: E402  (core)
from validator import validate                                   # noqa: E402  (core)
from render import layout_to_svg, archplan_to_svg                # noqa: E402  (core)

from topology import load_topology, validate_topology, mirror_topology_x, swap_master_standard_in_topology, apply_no_master_transform  # noqa: E402  (solver)
from solver import solve, AdjustmentError                        # noqa: E402  (solver)
from snap_gaps import snap_gaps, claim_void_alcoves              # noqa: E402  (solver)
from architectural_plan import architecturalize                  # noqa: E402  (solver)

from brief import Brief                                          # noqa: E402  (ai)
from llm import ClaudeLLM, StubLLM                               # noqa: E402  (ai)
from pipeline import (                                           # noqa: E402  (ai)
    _topology_from_dict, _make_default_lot, MAX_REPAIR,
)


_TOPOLOGIES_DIR = os.path.join(_HERE, "topologies")
OUT = os.path.join(_HERE, "output")
BRIEFS_DIR = os.path.join(_HERE, "briefs")
HAND_AUTHORED_DIR = os.path.join(BRIEFS_DIR, "hand_authored")
AI_DIR = os.path.join(BRIEFS_DIR, "ai")
# Topology regression test mode: each test brief in briefs/test/ exercises
# one topology end-to-end. Outputs land in test_output/ (gitignored
# scratch); test_baselines/ holds the checked-in "known-good" SVGs that
# regressions are diffed against. Update baselines deliberately with
# --update-baselines after an intentional renderer / solver change.
TEST_BRIEFS_DIR    = os.path.join(BRIEFS_DIR, "test")
TEST_OUT_DIR       = os.path.join(_HERE, "test_output")
TEST_BASELINES_DIR = os.path.join(_HERE, "test_baselines")
os.makedirs(OUT, exist_ok=True)
os.makedirs(HAND_AUTHORED_DIR, exist_ok=True)
os.makedirs(AI_DIR, exist_ok=True)
os.makedirs(TEST_BRIEFS_DIR, exist_ok=True)
os.makedirs(TEST_OUT_DIR, exist_ok=True)
os.makedirs(TEST_BASELINES_DIR, exist_ok=True)

AI_TEMPERATURE = 0.0   # set to None to use the API default (1.0)


# ---------- brief loading ----------
#
# Briefs live in floorplan_v1/briefs/ as one JSON file each:
#   briefs/hand_authored/<name>.json  →  pinned to a topology file (no AI call)
#   briefs/ai/<name>.json             →  Claude composes the topology
#
# Each file is a flat JSON object with the Brief fields (intent, lot_width,
# lot_depth, bedroom_count, must_haves, avoid, carport_side, carport_type). Hand-
# authored briefs additionally include a "topology" field naming a JSON in
# floorplan_v1/topologies/. The brief name comes from the filename (without .json).
# Add, edit, or remove briefs by editing the JSON — no Python changes.

_BRIEF_FIELDS = ("intent", "lot_width", "lot_depth", "bedroom_count",
                 "must_haves", "avoid", "carport_side", "carport_type", "setbacks",
                 "occupancy_class", "swap_master_standard", "door_host",
                 # Tier 1 additions (2026-06-25)
                 "no_master", "dirty_kitchen", "service_area", "lanai", "patio",
                 "num_baths", "powder_room",
                 # Tier 2 additions (2026-06-25)
                 "kitchen_back_door")

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
    """Recursively scan a brief subdir (now nested by storey / br / shell),
    sort by relative path, return a list of tuples.

    For hand_authored: (name, brief, topology_filename, adjustments, rel_dir).
    For ai:           (name, brief, adjustments, rel_dir).

    `rel_dir` is the brief's location relative to `subdir` (e.g., "1s/2br/wide")
    used by the writer to mirror the same hierarchy in the output folder.

    `adjustments` is an optional per-room-type override dict from the brief JSON
    (key: room type name, value: {min_area_sqm, max_area_sqm, min_least_dim_m}).
    Routed to the solver as a soft overlay; deliberately NOT part of the cache
    key so editing adjustments re-solves geometry without re-calling Claude.
    """
    if not os.path.isdir(subdir):
        return []
    out = []
    # Walk recursively so nested 1s/2br/<shell>/anchor_*.json briefs are picked
    # up. Sort by relative path for deterministic ordering.
    matches = []
    for root, _, files in os.walk(subdir):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, subdir)
            matches.append((rel, full))
    matches.sort()
    for rel, p in matches:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = _name_from_path(p)
        rel_dir = os.path.dirname(rel)         # "" for top-level briefs
        brief = _brief_from_json(data, p)
        adjustments = data.get("adjustments", {}) or {}
        _validate_adjustments(adjustments, p)
        if expect_topology:
            if "topology" not in data:
                raise ValueError(f"{p}: hand-authored brief must include a "
                                 f"'topology' field naming a file in "
                                 f"floorplan_v1/topologies/")
            out.append((name, brief, data["topology"], adjustments, rel_dir))
        else:
            out.append((name, brief, adjustments, rel_dir))
    return out


def load_hand_authored_anchors():
    return _load_briefs_from(HAND_AUTHORED_DIR, expect_topology=True)


def load_ai_briefs():
    return _load_briefs_from(AI_DIR, expect_topology=False)


def load_test_briefs():
    """Test briefs live FLAT in briefs/test/ (no shell-config nesting) —
    one minimal brief per topology, used for end-to-end regression. Each
    must reference an existing topology JSON via the `topology` field, same
    schema as the hand-authored anchors."""
    return _load_briefs_from(TEST_BRIEFS_DIR, expect_topology=True)


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

def _match_lot_profile(profiles, env_w: float, env_h: float):
    """Return the first matching profile's (name, auto_apply, preferred_apply)
    triple, or (None, {}, {}). Predicate keys understood:
      buildable_depth_lt_m / buildable_depth_gte_m
      buildable_width_lt_m / buildable_width_gte_m
      buildable_area_lt_sqm / buildable_area_gte_sqm

    `auto_apply` adjustments are applied unconditionally to every solve.
    `preferred_apply` adjustments are tried FIRST (added on top of auto_apply);
    if that solve is infeasible, the runner retries with only `auto_apply` and
    emits a 'tiered_preferred_dropped' warning. Use preferred_apply for soft
    floors (e.g., baths at 3.0 m² preferred-low) that should hold on roomy
    lots but yield to space pressure on tight ones.
    """
    area = env_w * env_h
    for prof in profiles or []:
        when = prof.get("when") or {}
        ok = True
        for k, v in when.items():
            v = float(v)
            if   k == "buildable_depth_lt_m":   ok = ok and env_h <  v
            elif k == "buildable_depth_gte_m":  ok = ok and env_h >= v
            elif k == "buildable_width_lt_m":   ok = ok and env_w <  v
            elif k == "buildable_width_gte_m":  ok = ok and env_w >= v
            elif k == "buildable_area_lt_sqm":  ok = ok and area  <  v
            elif k == "buildable_area_gte_sqm": ok = ok and area  >= v
            else:
                ok = False  # unknown predicate -> profile doesn't match
                break
        if ok:
            return (prof.get("name", "(unnamed)"),
                    prof.get("auto_apply") or {},
                    prof.get("preferred_apply") or {})
    return None, {}, {}


def _strip_carport_from_topology(topo):
    """Return a copy of `topo` with the carport setback element removed AND
    any building_void that was carved for the carport (`consumed_by="carport"`)
    removed too. Used when brief.carport_side/carport_type == 'none' — the building
    footprint becomes a clean rectangle (no L-cut) and no carport is rendered
    in the side setback."""
    from topology import Topology as _Topology  # type: ignore
    new_setbacks = [sb for sb in topo.setback_elements
                    if (sb.type or "").lower() != "carport"]
    new_voids = [v for v in (topo.building_voids or [])
                 if (v.consumed_by or "").lower() != "carport"]
    return _Topology(
        id=topo.id, label=topo.label, target_shell=topo.target_shell,
        rooms=list(topo.rooms), adjacencies=list(topo.adjacencies),
        entry_point=topo.entry_point,
        setback_elements=new_setbacks,
        soft_proximities=list(topo.soft_proximities),
        zone_split=topo.zone_split,
        notes=list(topo.notes),
        match_bedroom_widths=topo.match_bedroom_widths,
        match_bath_widths=topo.match_bath_widths,
        bedroom_band_fills_width=topo.bedroom_band_fills_width,
        ensuite_alcove_joins_master=topo.ensuite_alcove_joins_master,
        front_to_rear_stacks=list(topo.front_to_rear_stacks),
        rear_anchored=list(topo.rear_anchored),
        left_anchored=list(topo.left_anchored),
        right_anchored=list(topo.right_anchored),
        lot_adjustment_profiles=list(topo.lot_adjustment_profiles),
        building_voids=new_voids,
        fallback_topology=topo.fallback_topology,
    )


def _strip_carport_void_only(topo):
    """Return a copy of `topo` with the carport building_void removed but the
    carport setback element kept. Used when brief.carport_side/carport_type == 'front'
    — the front-parallel carport doesn't carve the building envelope (it sits
    entirely in the front setback area), so the L-cut void must go, but the
    carport itself stays so the setback-element placer still renders it."""
    from topology import Topology as _Topology  # type: ignore
    new_voids = [v for v in (topo.building_voids or [])
                 if (v.consumed_by or "").lower() != "carport"]
    return _Topology(
        id=topo.id, label=topo.label, target_shell=topo.target_shell,
        rooms=list(topo.rooms), adjacencies=list(topo.adjacencies),
        entry_point=topo.entry_point,
        setback_elements=list(topo.setback_elements),
        soft_proximities=list(topo.soft_proximities),
        zone_split=topo.zone_split,
        notes=list(topo.notes),
        match_bedroom_widths=topo.match_bedroom_widths,
        match_bath_widths=topo.match_bath_widths,
        bedroom_band_fills_width=topo.bedroom_band_fills_width,
        ensuite_alcove_joins_master=topo.ensuite_alcove_joins_master,
        front_to_rear_stacks=list(topo.front_to_rear_stacks),
        rear_anchored=list(topo.rear_anchored),
        left_anchored=list(topo.left_anchored),
        right_anchored=list(topo.right_anchored),
        lot_adjustment_profiles=list(topo.lot_adjustment_profiles),
        building_voids=new_voids,
        fallback_topology=topo.fallback_topology,
    )


def _strip_setback_element(topo, element_type: str):
    """Return a copy of `topo` with all setback elements of the given type
    removed. Used for optional external spaces (dirty_kitchen, service_area,
    lanai, patio) that are off by default and only included when the brief
    explicitly enables them.

    Unlike the carport strip, these rear/side elements have no building_void,
    so only setback_elements needs filtering."""
    from topology import Topology as _Topology  # type: ignore
    etype = element_type.lower()
    new_setbacks = [sb for sb in topo.setback_elements
                    if (sb.type or "").lower() != etype]
    return _Topology(
        id=topo.id, label=topo.label, target_shell=topo.target_shell,
        rooms=list(topo.rooms), adjacencies=list(topo.adjacencies),
        entry_point=topo.entry_point,
        setback_elements=new_setbacks,
        soft_proximities=list(topo.soft_proximities),
        zone_split=topo.zone_split,
        notes=list(topo.notes),
        match_bedroom_widths=topo.match_bedroom_widths,
        match_bath_widths=topo.match_bath_widths,
        bedroom_band_fills_width=topo.bedroom_band_fills_width,
        ensuite_alcove_joins_master=topo.ensuite_alcove_joins_master,
        front_to_rear_stacks=list(topo.front_to_rear_stacks),
        rear_anchored=list(topo.rear_anchored),
        left_anchored=list(topo.left_anchored),
        right_anchored=list(topo.right_anchored),
        lot_adjustment_profiles=list(topo.lot_adjustment_profiles),
        building_voids=list(topo.building_voids or []),
        fallback_topology=topo.fallback_topology,
    )


def _bump_lot_front(lot, min_front: float):
    """Return a Lot with `front` setback bumped to at least `min_front` (keeps
    other dims unchanged). Used by front-carport handling — the front-parallel
    carport (2.6 m deep) needs ≥ 3.0 m front setback so it clears the building
    face cleanly."""
    from model import Lot as _Lot
    if lot.front >= min_front:
        return lot
    return _Lot(width=lot.width, depth=lot.depth,
                front=min_front, rear=lot.rear, left=lot.left, right=lot.right,
                street_side=getattr(lot, "street_side", "front"),
                occupancy_class=getattr(lot, "occupancy_class", "R-1"))


def _topology_void_rects(topo, lot):
    """Convert each topology BuildingVoid (anchored at an envelope corner)
    into a Rect in model coordinates for downstream consumers (snap_gaps,
    renderer)."""
    from model import Rect as _Rect
    env = lot.envelope()
    out = []
    for v in (getattr(topo, "building_voids", None) or []):
        loc = (v.location or "").lower()
        if loc == "front_left":
            r = _Rect(env.x0, env.y0, env.x0 + v.width_m, env.y0 + v.depth_m)
        elif loc == "front_right":
            r = _Rect(env.x1 - v.width_m, env.y0, env.x1, env.y0 + v.depth_m)
        elif loc == "rear_left":
            r = _Rect(env.x0, env.y1 - v.depth_m, env.x0 + v.width_m, env.y1)
        elif loc == "rear_right":
            r = _Rect(env.x1 - v.width_m, env.y1 - v.depth_m, env.x1, env.y1)
        else:
            continue
        out.append(r)
    return out


def _merge_lot_profile(topo, env_w: float, env_h: float, brief_adj: dict,
                       verbose: bool):
    """If the topology defines lot_adjustment_profiles, find the first match
    based on the envelope dims and merge its `auto_apply` (and optionally
    `preferred_apply`) into brief_adj. Brief always wins on conflicting
    (room_type, knob) pairs.

    Returns (base_adj, preferred_adj) — two dicts.
      base_adj      = auto_apply ∪ brief — applied to every solve attempt
      preferred_adj = preferred_apply layered ON TOP of base_adj — tried
                      first; the caller drops it on infeasibility.
    When the profile has no preferred_apply, preferred_adj is None and the
    caller skips the tiered-retry path.
    """
    profiles = getattr(topo, "lot_adjustment_profiles", None) or []
    if not profiles:
        return (brief_adj or {}), None
    name, auto, preferred = _match_lot_profile(profiles, env_w, env_h)
    if not auto and not preferred:
        return (brief_adj or {}), None
    base = {rt: dict(knobs) for rt, knobs in auto.items()}
    for rt, knobs in (brief_adj or {}).items():
        base.setdefault(rt, {}).update(knobs)
    if verbose:
        print(f"  lot profile auto-applied: '{name}' -> {auto}")
    if preferred:
        merged_pref = {rt: dict(knobs) for rt, knobs in base.items()}
        for rt, knobs in preferred.items():
            merged_pref.setdefault(rt, {}).update(knobs)
        if verbose:
            print(f"  lot profile preferred-tier: '{name}' -> {preferred}")
        return base, merged_pref
    return base, None


def _run_hand_authored(brief: Brief, topology_filename: str,
                       adjustments: dict = None, verbose: bool = True,
                       deterministic: bool = False,
                       _fallback_warning: str = None):
    """Load named topology, solve, validate. No API call. `deterministic`
    pins the solver to single-threaded + fixed random seed so test mode
    can byte-diff the SVG against a baseline.

    Fallback behavior: when the primary topology declares a
    `fallback_topology` and the solver reports infeasibility on the brief's
    lot, recursively retry with the fallback. A "topology_fallback" warning
    is attached to layout.issues so the test summary surfaces the downgrade
    (e.g., hall-variant → no-hall variant when the shell can't fit a hall).
    `_fallback_warning` is the private propagation channel — callers
    shouldn't pass it directly.
    """
    rules = Rules()
    lot = _make_default_lot(brief)
    shell = shell_category(lot)
    env = lot.envelope()
    if verbose:
        print(brief.summary())
        print(f"shell category: {shell}  |  buildable {env.w:.1f}x{env.h:.1f} m")
        print(f"\n[hand-authored]  topology: {topology_filename}")
        if adjustments:
            print(f"  adjustments (brief): {adjustments}")
    topo = load_topology(os.path.join(_TOPOLOGIES_DIR, topology_filename))
    # Master/standard swap: when the brief asks for master-at-rear, flip the
    # placements of master_bedroom and bedroom_standard before any other
    # transform. This is a position-only swap (the rooms keep their types,
    # sizes, and adjacencies; only stack ordering and anchor-list tokens
    # change). Applied first so subsequent carport mirroring/stripping
    # operates on the post-swap topology.
    if getattr(brief, "swap_master_standard", False):
        topo = swap_master_standard_in_topology(topo)
        if verbose:
            print(f"  swap_master_standard=true → master moves to standard's "
                  f"position (and vice versa)")
    if getattr(brief, "no_master", False):
        if getattr(brief, "swap_master_standard", False) and verbose:
            print(f"  warning: swap_master_standard is ignored when no_master=true")
        topo = apply_no_master_transform(topo)
        if verbose:
            print(f"  no_master=true → master_bedroom retyped to bedroom_standard, "
                  f"ensuite_bath removed")
    # Carport-side mirroring: topology files are authored in the canonical
    # "carport on the right" form. When the brief asks for the carport on
    # the LEFT, mirror the topology's x-axis fields (anchored lists and
    # building-void corner locations) and flip the solver's kitchen_side
    # symmetry break so the kitchen tracks the carport on the same side
    # rather than getting pinned opposite. When the brief asks for NO
    # carport (ncp), strip the carport's setback element and the
    # building_void that pairs with it so the building footprint becomes
    # a clean rectangle (no L-cut).
    side  = (brief.carport_side or "").lower()
    ctype = (brief.carport_type  or "").lower()
    if side == "left":
        topo = mirror_topology_x(topo)
        if ctype == "fcp":
            # fcp: full side setback (3 m throughout) — strip the L-void so
            # the envelope stays a clean rectangle (narrower than ccp).
            topo = _strip_carport_void_only(topo)
        kitchen_side = "left"
    elif not side:                  # ncp — no carport
        topo = _strip_carport_from_topology(topo)
        kitchen_side = "right"
    elif side == "front":
        # Front-parallel fcp carport across the full front setback. Bump the
        # front setback to 3.0 m and strip the side void (front carport
        # doesn't carve the side envelope). The solver auto-detects "front".
        topo = _strip_carport_void_only(topo)
        if lot.front < 3.0:
            lot = _bump_lot_front(lot, 3.0)
            env = lot.envelope()
        kitchen_side = "right"
    elif ctype == "fcp":
        # fcp right: full side setback (3 m throughout) — strip the L-void.
        topo = _strip_carport_void_only(topo)
        kitchen_side = "right"
    else:                           # ccp right (default)
        kitchen_side = "right"
    # Optional external spaces: strip setback elements not requested in brief.
    # Default is off for all except porch (porch has no setback element yet —
    # it is always rendered as a front-entry landing by the renderer).
    for _ext_type, _enabled in (
        ("dirty_kitchen", getattr(brief, "dirty_kitchen", False)),
        ("service_area",  getattr(brief, "service_area",  False)),
        ("lanai",         getattr(brief, "lanai",         False)),
        ("patio",         getattr(brief, "patio",         False)),
    ):
        if not _enabled:
            _had = any((sb.type or "").lower() == _ext_type
                       for sb in topo.setback_elements)
            topo = _strip_setback_element(topo, _ext_type)
            if verbose and _had:
                print(f"  {_ext_type} not in brief → stripped from topology")
    # Bath-count check: resolve the required bath count (from brief or
    # size-based default) and warn if the topology doesn't match.
    # "Baths" here = common_bath + ensuite_bath rooms in the topology.
    # Default rule: buildable floor area >= 65 m² → 2 baths, else 1.
    _topo_bath_count = sum(
        1 for r in topo.rooms if r.type in ("common_bath", "ensuite_bath"))
    _required_baths = getattr(brief, "num_baths", None)
    if _required_baths is None:
        _floor_area = env.w * env.h
        _required_baths = 2 if _floor_area >= 65.0 else 1
    if _topo_bath_count != _required_baths and verbose:
        print(f"  warning: brief requires {_required_baths} bath(s) "
              f"(floor area {env.w * env.h:.1f} m²) but topology has "
              f"{_topo_bath_count} — topology mismatch")
    base_adj, preferred_adj = _merge_lot_profile(
        topo, env.w, env.h, adjustments, verbose)
    # Tiered solve attempt: try with preferred_apply layered on top first
    # (e.g., baths floored at 3.0 m² preferred-low). On infeasibility,
    # quietly drop preferred and retry with just base_adj — emit a warning
    # so the user knows the soft floor was relaxed.
    tiered_dropped = False
    if preferred_adj is not None:
        try:
            layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False,
                           adjustments=preferred_adj, deterministic=deterministic,
                           kitchen_side=kitchen_side)
        except RuntimeError as e:
            if "no feasible" not in str(e).lower():
                raise   # not an infeasibility — re-raise as-is
            if verbose:
                print(f"  preferred tier infeasible; relaxing preferred_apply "
                      f"and retrying with base adjustments")
            tiered_dropped = True
            layout = None  # solver retry below
    else:
        layout = None
    if layout is None:
        merged_adj = base_adj
    else:
        merged_adj = preferred_adj
    try:
        if layout is None:
            layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False,
                           adjustments=merged_adj, deterministic=deterministic,
                           kitchen_side=kitchen_side)
    except RuntimeError as e:
        # Solver couldn't find a feasible layout. If the topology declares a
        # fallback (typically a hall-variant falling back to its no-hall
        # sibling), retry with the fallback and propagate a warning that the
        # primary topology didn't fit the shell.
        msg = str(e).lower()
        if topo.fallback_topology and "no feasible" in msg:
            fb_warning = (
                f"primary topology '{topology_filename}' does not fit the "
                f"given shell — falling back to '{topo.fallback_topology}'"
            )
            if verbose:
                print(f"  primary infeasible ({e}); fallback -> "
                      f"{topo.fallback_topology}")
            return _run_hand_authored(
                brief, topo.fallback_topology, adjustments=adjustments,
                verbose=verbose, deterministic=deterministic,
                _fallback_warning=fb_warning,
            )
        raise
    # Attach the topology's building voids to the layout so the validator
    # can see them and suppress the "element in envelope" false positive
    # (a setback element overlapping a void is intentional).
    void_rects = _topology_void_rects(topo, lot)
    layout.building_void_rects = void_rects
    issues, score = validate(layout, rules)
    errs = [i for i in issues if i.severity == "error"]
    if errs:
        raise RuntimeError(
            f"hand-authored topology {topology_filename} failed validation: "
            + "; ".join(str(e) for e in errs[:3]))
    # Build per-room max_area_sqm caps from the merged adjustments so the
    # post-solve passes (claim_ensuite_alcove + snap_gaps) honor the cap
    # the solver was given. Solver-time max_area_sqm is enforced as
    # area[r.id] <= cap, but snap_gaps and the alcove claim run after solve
    # and would otherwise overrun the cap.
    area_caps = {}
    for room in topo.rooms:
        knobs = merged_adj.get(room.type) if merged_adj else None
        if knobs and "max_area_sqm" in knobs:
            area_caps[room.id] = float(knobs["max_area_sqm"])
    # Pre-snap-gaps: claim the strip east of ensuite for master (L-shape)
    # if the topology opted in via ensuite_alcove_joins_master. Doing this
    # BEFORE snap_gaps means ensuite can't drift east into the strip — the
    # strip is already master's rect2 when snap_gaps starts its scan.
    from snap_gaps import claim_ensuite_alcove
    claim_ensuite_alcove(layout, topo, verbose=verbose, max_area_caps=area_caps)
    # Post-solve, post-validate gap snapper: extend room walls into any unused
    # envelope strips. Building voids are treated as obstacles so rooms don't
    # snap into them. Pass matched_x_pairs so snap_gaps preserves any
    # match_*_widths invariants the solver enforced (without this, an
    # asymmetric east-side gap can drift the matched widths apart).
    matched_x_pairs = []
    if topo.match_bedroom_widths:
        m_id = next((r.id for r in topo.rooms if r.type == "master_bedroom"), None)
        s_id = next((r.id for r in topo.rooms if r.type == "bedroom_standard"), None)
        if m_id and s_id:
            matched_x_pairs.append((m_id, s_id))
    if topo.match_bath_widths:
        e_id = next((r.id for r in topo.rooms if r.type == "ensuite_bath"), None)
        c_id = next((r.id for r in topo.rooms if r.type == "common_bath"), None)
        if e_id and c_id:
            matched_x_pairs.append((e_id, c_id))
    layout, n_snaps = snap_gaps(layout, verbose=verbose, void_rects=void_rects,
                                matched_x_pairs=matched_x_pairs,
                                max_area_caps=area_caps)
    # Post-snap alcove claim: rectangular dead space next to a void's INTERIOR
    # face (e.g., the strip past a front_right carport_cut's north edge) gets
    # assigned to the adjacent room as a second cell — that room becomes
    # L-shaped. Without this, the wall along the void's north edge doesn't
    # sit flush with the void (a small alcove of unowned interior remains).
    n_alcoves = claim_void_alcoves(layout, void_rects=void_rects, verbose=verbose)
    # Build the architectural plan now (post-snap) so the validator's
    # window-area checks (W-H1, W-H2) can see the windows. Attach the plan
    # to the layout — downstream rendering reuses it instead of rebuilding.
    plan = architecturalize(layout, topo,
                            door_host=getattr(brief, "door_host", None),
                            kitchen_back_door=getattr(brief, "kitchen_back_door", True))
    layout.archplan = plan
    if n_snaps:
        # Re-validate to refresh the score with the now-larger room areas.
        issues, score = validate(layout, rules)
    else:
        # Validate again so window-area checks run against the attached plan.
        issues, score = validate(layout, rules)
    errs = [i for i in issues if i.severity == "error"]
    if errs:
        raise RuntimeError(
            f"hand-authored topology {topology_filename} failed validation: "
            + "; ".join(str(e) for e in errs[:3]))
    # If we got here via fallback, surface that as a top-level warning so the
    # test summary and CLI both see it (validator owns layout.issues now).
    if _fallback_warning is not None:
        from validator import Issue as _Issue
        layout.issues.insert(0, _Issue(
            "warning", "topology_fallback", _fallback_warning))
    if tiered_dropped:
        from validator import Issue as _Issue
        layout.issues.insert(0, _Issue(
            "warning", "tiered_preferred_dropped",
            f"preferred_apply adjustments did not fit '{topology_filename}' "
            f"on this shell — relaxed to base auto_apply (e.g., baths held to "
            f"hard minimum instead of preferred-low)"))
    if verbose:
        warns = [i for i in layout.issues if i.severity == "warning"]
        sugg = [i for i in layout.issues if i.severity == "suggestion"]
        snap_note = f" ({n_snaps} snap(s))" if n_snaps else ""
        print(f"  COMPLIANT  score={score:.2f}  {len(warns)} warn  {len(sugg)} sugg{snap_note}")
        for w in warns:
            print(f"    [WARN] {w.msg}")
    reason = f"[hand-authored] using {topology_filename} (no API call)"
    if _fallback_warning is not None:
        reason += " (fallback)"
    return layout, topo, reason


def _try_realize(topo_dict: dict, brief: Brief, rules: Rules,
                 adjustments: dict = None, deterministic: bool = False):
    """Run a topology dict through solve+validate. Returns (layout, topology,
    score) on success or raises with a human-readable reason."""
    topo = _topology_from_dict(topo_dict)
    errs = validate_topology(topo)
    if errs:
        raise RuntimeError("structural topology errors: " + "; ".join(errs))
    lot = _make_default_lot(brief)
    env = lot.envelope()
    # AI-generated topologies are authored for the exact carport side in the
    # brief — no mirroring. Only strip/adjust for ncp, fcp, and front carports.
    side  = (brief.carport_side or "").lower()
    ctype = (brief.carport_type  or "").lower()
    if side == "left":
        if ctype == "fcp":
            topo = _strip_carport_void_only(topo)
        kitchen_side = "left"
    elif not side:                  # ncp
        topo = _strip_carport_from_topology(topo)
        kitchen_side = "right"
    elif side == "front":
        topo = _strip_carport_void_only(topo)
        if lot.front < 3.0:
            lot = _bump_lot_front(lot, 3.0)
            env = lot.envelope()
        kitchen_side = "right"
    elif ctype == "fcp":            # fcp right
        topo = _strip_carport_void_only(topo)
        kitchen_side = "right"
    else:                           # ccp right (default)
        kitchen_side = "right"
    base_adj, preferred_adj = _merge_lot_profile(
        topo, env.w, env.h, adjustments, verbose=False)
    # AI pipeline mirror of the hand-authored tiered-retry: try preferred
    # first, fall back to base on infeasibility (warning isn't surfaced here
    # because AI-pipeline runs use a different reporting path).
    try_adj = preferred_adj if preferred_adj is not None else base_adj
    try:
        layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False,
                       adjustments=try_adj, kitchen_side=kitchen_side,
                       deterministic=deterministic)
    except RuntimeError as e:
        if preferred_adj is None or "no feasible" not in str(e).lower():
            raise
        layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False,
                       adjustments=base_adj, kitchen_side=kitchen_side,
                       deterministic=deterministic)
    void_rects = _topology_void_rects(topo, lot)
    layout.building_void_rects = void_rects
    issues, score = validate(layout, rules)
    hard = [i for i in issues if i.severity == "error"]
    if hard:
        raise RuntimeError("validator caught hard violation(s): "
                           + "; ".join(str(i) for i in hard[:3]))
    # Snap unused envelope strips after the AI-realized layout has cleared
    # the validator. Build the archplan post-snap and re-validate so the
    # final score reflects window-area compliance (W-H1, W-H2).
    layout, n_snaps = snap_gaps(layout, verbose=False, void_rects=void_rects)
    plan = architecturalize(layout, topo,
                            door_host=getattr(brief, "door_host", None),
                            kitchen_back_door=getattr(brief, "kitchen_back_door", True))
    layout.archplan = plan
    issues, score = validate(layout, rules)
    hard = [i for i in issues if i.severity == "error"]
    if hard:
        raise RuntimeError("validator caught hard violation(s) post-archplan: "
                           + "; ".join(str(i) for i in hard[:3]))
    return layout, topo, score, issues


def _run_ai(brief: Brief, adjustments: dict = None, verbose: bool = True,
            deterministic: bool = False):
    """Call Claude to compose a topology and run it through the solver.
    Retries up to MAX_REPAIR times on infeasibility. Every call hits the API."""
    rules = Rules()
    lot = _make_default_lot(brief)
    env = lot.envelope()
    if verbose:
        print(brief.summary())
        print(f"shell category: {shell_category(lot)}  |  buildable {env.w:.1f}x{env.h:.1f} m")
        if adjustments:
            print(f"adjustments: {adjustments}")

    client = _make_ai_client()
    error_feedback = None
    for attempt in range(1 + MAX_REPAIR):
        if verbose:
            tag = "first attempt" if attempt == 0 else f"repair attempt {attempt}"
            print(f"\n[{tag}]  LLM client: {type(client).__name__}")
        topo_dict, reason = client.generate(brief, error_feedback=error_feedback)
        if verbose:
            print(f"  reasoning: {reason}")
        try:
            layout, topo, score, issues = _try_realize(topo_dict, brief, rules, adjustments, deterministic=deterministic)
        except AdjustmentError as e:
            raise RuntimeError(
                f"adjustments don't match Claude's composed topology: {e}\n"
                f"  fix the adjustments and re-run."
            )
        except RuntimeError as e:
            error_feedback = str(e)
            if verbose:
                print(f"  failed: {e}")
            continue
        warns = [i for i in issues if i.severity == "warning"]
        sugg = [i for i in issues if i.severity == "suggestion"]
        if verbose:
            print(f"  COMPLIANT  score={score:.2f}  {len(warns)} warn  {len(sugg)} sugg")
        return layout, topo, reason

    raise RuntimeError(
        f"could not produce a feasible layout after {1 + MAX_REPAIR} attempts. "
        f"last feedback: {error_feedback}"
    )


def _write(name, layout, topo, reason, rel_dir="", out_root=None):
    """Write the architectural plan SVG + PNG. Mirrors the brief's relative
    path under `out_root` (defaults to the canonical OUT dir). Test runs
    point this at TEST_OUT_DIR or TEST_BASELINES_DIR instead. Overwrites
    any existing file."""
    base = out_root if out_root is not None else OUT
    out_dir = os.path.join(base, rel_dir) if rel_dir else base
    os.makedirs(out_dir, exist_ok=True)

    # Reuse the plan that the run/realize step attached after snap_gaps;
    # rebuild only if it wasn't cached (defensive).
    plan = getattr(layout, "archplan", None) or architecturalize(layout, topo)
    svg_path = os.path.join(out_dir, f"{name}.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(archplan_to_svg(plan))
    print(f"  wrote {svg_path}")
    if _HAS_CAIROSVG:
        png_path = os.path.join(out_dir, f"{name}.png")
        try:
            cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=560)
            print(f"  wrote {png_path}")
        except Exception as e:
            print(f"  PNG conversion skipped: {e.__class__.__name__}: {e}")
    print(f"  reasoning: {reason}")
    print(f"  topology id: {topo.id}")


def _run_tests(update_baselines: bool = False, brief_filter: str = None) -> int:
    """Run every brief in briefs/test/ through the hand-authored solver +
    architectural-plan pipeline. Renders go to test_output/ (or
    test_baselines/ when --update-baselines is set).

    PASS / FAIL is based on validator compliance — a brief passes when the
    solver returns a layout and the validator emits zero hard errors. The
    CP-SAT solver is non-deterministic across runs even with a fixed seed
    (the 10-second wallclock cutoff lands on different optima on different
    runs), so we don't byte-diff SVGs. test_baselines/ remains a *visual*
    reference folder — humans inspect it manually when a topology change
    needs a sanity check that the rendering still reads correctly.

    Returns the number of FAILing tests (0 = clean)."""
    briefs = load_test_briefs()
    if brief_filter:
        briefs = [t for t in briefs if t[0] == brief_filter]
        if not briefs:
            print(f"no test brief matches --brief={brief_filter!r}")
            return 1
    out_root = TEST_BASELINES_DIR if update_baselines else TEST_OUT_DIR
    mode = "updating baselines in" if update_baselines else "writing to"
    print(f"running {len(briefs)} test brief(s); {mode} "
          f"{os.path.relpath(out_root, _HERE)}/\n")

    n_pass = n_fail = n_err = 0
    for name, brief, topology_fname, adjustments, rel_dir in briefs:
        print(f"--- {name}")
        try:
            layout, topo, reason = _run_hand_authored(
                brief, topology_fname, adjustments=adjustments,
                verbose=False, deterministic=True)
        except RuntimeError as e:
            print(f"  ERROR  (solver/validator): {e}")
            n_err += 1
            continue
        # The layout already passed _run_hand_authored's validator gate
        # (it raises on hard errors). Confirm explicitly and surface
        # warning / suggestion counts for human inspection.
        warns = sum(1 for i in layout.issues if i.severity == "warning")
        sugg  = sum(1 for i in layout.issues if i.severity == "suggestion")
        _write(name, layout, topo, reason, rel_dir=rel_dir, out_root=out_root)
        print(f"  PASS  ({warns} warn, {sugg} sugg)")
        n_pass += 1

    print(f"\nsummary: {n_pass} pass, {n_fail} fail, {n_err} error")
    if update_baselines:
        print(f"baselines updated at {os.path.relpath(out_root, _HERE)}/")
    return n_fail + n_err


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="floorplan_v1/run.py",
        description="Hybrid hand-authored + AI floor-plan pipeline. "
                    "By default runs every brief in floorplan_v1/briefs/.",
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
    p.add_argument("--test", action="store_true",
                   help="Run topology regression: every brief in briefs/test/ "
                        "is solved + validated + rendered to test_output/. "
                        "A test PASSes when the validator emits zero hard "
                        "errors. Skips the hand_authored/ + ai/ paths.")
    p.add_argument("--update-baselines", action="store_true",
                   help="With --test: write the just-rendered test SVGs/PNGs "
                        "over test_baselines/ (the visual-reference folder "
                        "checked into git) instead of test_output/. Use after "
                        "an intentional renderer or topology change to refresh "
                        "the human-eye baseline.")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    if args.test:
        sys.exit(_run_tests(update_baselines=args.update_baselines,
                            brief_filter=args.brief))
    if args.update_baselines:
        print("note: --update-baselines only does anything with --test; ignoring.")

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
    for name, brief, topology_fname, adjustments, rel_dir in hand_authored:
        print(f"\n{'=' * 70}\n=== {os.path.join(rel_dir, name) if rel_dir else name}   (hand-authored)\n{'=' * 70}")
        try:
            layout, topo, reason = _run_hand_authored(
                brief, topology_fname, adjustments=adjustments)
        except RuntimeError as e:
            print(f"FAILED: {e}")
            continue
        _write(name, layout, topo, reason, rel_dir=rel_dir)

    # Section 2 — AI briefs.
    for name, brief, adjustments, rel_dir in ai_briefs:
        print(f"\n{'=' * 70}\n=== {os.path.join(rel_dir, name) if rel_dir else name}   (AI-generated)\n{'=' * 70}")
        try:
            layout, topo, reason = _run_ai(brief, adjustments=adjustments, verbose=True)
        except RuntimeError as e:
            print(f"FAILED: {e}")
            continue
        _write(name, layout, topo, reason, rel_dir=rel_dir)


if __name__ == "__main__":
    main()
