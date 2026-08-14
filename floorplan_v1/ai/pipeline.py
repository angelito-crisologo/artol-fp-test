"""End-to-end pipeline: brief -> LLM -> topology -> solver -> Layout.

Includes the infeasibility-repair loop: if the solver can't realize the
LLM's topology, the failure is fed back to the LLM for a revised attempt
(up to MAX_REPAIR rounds). With the stub LLM this loop is a no-op (stub
returns the same thing); it'll become useful once Claude is wired in.
"""
import json
import os
import sys
from typing import Dict, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "core"))    # core modules
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "solver"))  # solver modules
sys.path.insert(0, _HERE)                                  # ai siblings (brief, llm)

from model import Lot, shell_category                        # noqa: E402  (core)
from rules import Rules                                      # noqa: E402  (core)
from validator import (                                      # noqa: E402  (core)
    validate, is_compliant, SETBACK_MIN_BY_OCCUPANCY,
)

from topology import (                                       # noqa: E402  (solver)
    Topology, RoomSpec, Adjacency, SetbackElement,
    SoftProximity, ZoneSplit, validate_topology,
)
from solver import solve                                     # noqa: E402  (solver)

from brief import Brief                                      # noqa: E402  (ai)
from llm import get_client                                   # noqa: E402  (ai)

MAX_REPAIR = 2          # repair rounds when the solver returns infeasible


def _topology_from_dict(d: dict) -> Topology:
    rooms = [RoomSpec(**{k: r[k] for k in r if k in RoomSpec.__annotations__})
             for r in d["rooms"]]
    adjs = [Adjacency(**{k: e[k] for k in e if k in Adjacency.__annotations__})
            for e in d["adjacencies"]]
    elems = [SetbackElement(**{k: x[k] for k in x if k in SetbackElement.__annotations__})
             for x in d.get("setback_elements", [])]
    sprox = [SoftProximity(**{k: x[k] for k in x if k in SoftProximity.__annotations__})
             for x in d.get("soft_proximities", [])]
    zs_raw = d.get("zone_split")
    zs = ZoneSplit(**{k: zs_raw[k] for k in zs_raw if k in ZoneSplit.__annotations__}) \
         if zs_raw else None
    return Topology(
        id=d["id"], label=d["label"], target_shell=d["target_shell"],
        rooms=rooms, adjacencies=adjs, entry_point=d["entry_point"],
        setback_elements=elems, soft_proximities=sprox, zone_split=zs,
        notes=d.get("notes", []),
    )


def _legal_min_setbacks(occupancy: str) -> Dict[str, float]:
    """Per-side legal minimum setbacks for a residential occupancy class.

    Sourced from core/validator.py's SETBACK_MIN_BY_OCCUPANCY so the solver
    and the validator cannot disagree about the same rule — before 2026-08-05
    lot construction hardcoded 2.0 m on every side while the validator
    measured against this table, which is why every run emitted a
    `setback_below_irr_baseline` suggestion for the front yard.

    Front is the side that actually varies: R-1 (low-density single-detached)
    requires 4.5 m, R-2/R-3/R-4 require 3.0 m. The 2.0 m figure that used to
    be hardcoded here is the PD 1096 Sec. 708(a) minimum for SIDE and REAR
    yards (or BP 220 economic housing) — it was never a legal front yard."""
    mins = SETBACK_MIN_BY_OCCUPANCY.get(occupancy) or {}
    return {"front": float(mins.get("front", 3.0)),
            "rear":  float(mins.get("rear", 2.0)),
            "left":  float(mins.get("side", 2.0)),
            "right": float(mins.get("side", 2.0))}


def _clamp_setback(specified: float, minimum: float) -> float:
    """Raise a setback to its legal minimum, but never touch a deliberate 0.

    A 0 means a firewall (party wall) on that side. Whether that is legal for
    the occupancy class is the validator's call (W-H10) — silently inflating
    it to 2 m here would hide an illegal firewall instead of reporting it."""
    if specified == 0:
        return 0.0
    return max(float(specified), minimum)


def _make_default_lot(brief: Brief) -> Lot:
    """Lot built from the brief's dims, with setbacks at their legal minimum
    for the brief's occupancy class (see `_legal_min_setbacks`) and a 3 m
    carport setback on the side named by brief.carport_side. When
    carport_side is None the brief has no carport (ncp).

    A brief can override the four setbacks directly via its `setbacks` dict
    (e.g., `setbacks: {front: 2, rear: 2, left: 2, right: 0}` for a firewall
    on the right). When `setbacks` is given, carport_side/carport_type are
    ignored — the brief is fully in control of envelope geometry, EXCEPT that
    each side is still floored at its legal minimum (a firewall 0 excepted).
    Without that floor the override could put a plan below code, and every
    brief in this repo declares `front: 2.0`, which no occupancy class
    permits."""
    occupancy = getattr(brief, "occupancy_class", "R-2")
    legal = _legal_min_setbacks(occupancy)
    explicit = getattr(brief, "setbacks", None)
    if explicit:
        return Lot(
            width=brief.lot_width, depth=brief.lot_depth,
            front=_clamp_setback(explicit.get("front", legal["front"]), legal["front"]),
            rear=_clamp_setback(explicit.get("rear", legal["rear"]), legal["rear"]),
            left=_clamp_setback(explicit.get("left", legal["left"]), legal["left"]),
            right=_clamp_setback(explicit.get("right", legal["right"]), legal["right"]),
            street_side="front",
            occupancy_class=occupancy,
        )
    front, rear = legal["front"], legal["rear"]
    left, right = legal["left"], legal["right"]
    side  = (brief.carport_side  or "").lower()
    ctype = (brief.carport_type  or "").lower()
    # Only fcp widens the setback — 3 m for the full side depth.
    # ccp keeps all setbacks at 2 m; the L-notch is a building_void in the
    # topology, not a wider lot setback.
    if ctype == "fcp":
        # A carport needs 3 m of clearance on its side. Take the larger of
        # that and the class's legal minimum — for a FRONT carport under R-1
        # the legal 4.5 m already exceeds it.
        if side == "left":
            left = max(left, 3.0)
        elif side == "front":
            front = max(front, 3.0)
        elif side == "right":
            right = max(right, 3.0)
    # ncp and ccp: every side stays at its legal minimum for the class
    return Lot(
        width=brief.lot_width, depth=brief.lot_depth,
        front=front, rear=rear, left=left, right=right,
        street_side="front",
        occupancy_class=occupancy,
    )


# ---------- buildable-shell capping (SHELL_CAPPING_DESIGN.md §2) ----------

SHELL_SLACK = 1.10           # rectangles don't tile perfectly; target = sum * this
SHELL_INFLATE_THRESHOLD = 1.05   # deadband: don't inflate for a trivial surplus
FRONT_INFLATE_CAP_M = 4.5    # IRR Rule VIII R-1 baseline; never inflate past it
GRID_M = 0.05                # solver grid, so setbacks land on it


def topology_target_area(topo, rules) -> float:
    """Floor area a topology wants at its preferred-high, i.e. the largest
    shell that is not simply oversized for the program.

    Two-storey uses the LARGEST STOREY, not the sum — the shell is a footprint.
    Multiplied by SHELL_SLACK because a solver cannot tile rectangles into
    exactly their combined area."""
    per_storey: Dict[int, float] = {}
    for r in topo.rooms:
        pref = rules.preferred_area_range(r.type)
        hi = pref[1] if pref else (rules.hard_min_area(r.type) or 0.0) * 4.0
        per_storey[getattr(r, "storey", 1)] = per_storey.get(getattr(r, "storey", 1), 0.0) + hi
    return (max(per_storey.values()) if per_storey else 0.0) * SHELL_SLACK


def _snap(v: float) -> float:
    return round(round(v / GRID_M) * GRID_M, 4)


def capped_setbacks(brief: Brief, topo, rules):
    """Setbacks after absorbing surplus lot area, per SHELL_CAPPING_DESIGN.md §2.

    Returns (setbacks_dict, info) where info explains what happened — `info`
    is None when nothing was inflated, which is the common case.

    The shell shrinks toward `target_area` preserving its ASPECT RATIO (so it
    stays the same *kind* of shell that `shell_category` matched the topology
    against), then the surplus goes: front up to a 4.5 m cap, rear takes the
    rest of the depth, sides split the width equally.

    An explicit `Brief.setbacks` disables inflation outright. A partial
    `Brief.shell_inflation` pins named sides and lets the rest absorb."""
    base = _make_default_lot(brief)
    if getattr(brief, "setbacks", None):
        return None, None                       # brief is fully in control

    target = topology_target_area(topo, rules)
    env = base.envelope()
    raw_area = env.w * env.h
    if target <= 0 or raw_area <= target * SHELL_INFLATE_THRESHOLD:
        return None, None                       # inside the deadband

    f = (target / raw_area) ** 0.5              # aspect-preserving
    d_depth, d_width = env.h * (1 - f), env.w * (1 - f)

    front, rear = base.front, base.rear
    left, right = base.left, base.right
    add_front = min(d_depth, max(0.0, FRONT_INFLATE_CAP_M - front))
    front += add_front
    rear  += d_depth - add_front
    left  += d_width / 2.0
    right += d_width / 2.0

    # A carport must keep its 3 m; inflation only ever grows a side, so this
    # can only bind if the pinned overrides below take it back.
    out = {"front": _snap(front), "rear": _snap(rear),
           "left": _snap(left), "right": _snap(right)}
    pins = getattr(brief, "shell_inflation", None) or {}
    for k, v in pins.items():
        if k in out and v is not None:
            out[k] = _snap(float(v))
    side = (brief.carport_side or "").lower()
    if side in ("left", "right", "front"):
        out[side] = max(out[side], 3.0)
    info = (f"shell capped {env.w:.2f}x{env.h:.2f} -> {env.w*f:.2f}x{env.h*f:.2f} m "
            f"(target {target:.1f} m2); setbacks front {base.front:.2f}->{out['front']:.2f}, "
            f"rear {base.rear:.2f}->{out['rear']:.2f}, "
            f"sides {base.left:.2f}->{out['left']:.2f}/{out['right']:.2f}")
    return out, info


def make_capped_lot(brief: Brief, topo, rules) -> Tuple[Lot, object]:
    """Lot for SOLVING, with the shell capped to the topology's program.

    Deliberately separate from `_make_default_lot`, which stays topology-free:
    `ai/match.py` calls that one to compute `shell_category` when PICKING a
    topology, so making it topology-dependent would be circular."""
    sb, info = capped_setbacks(brief, topo, rules)
    if not sb:
        return _make_default_lot(brief), None
    return Lot(width=brief.lot_width, depth=brief.lot_depth,
               front=sb["front"], rear=sb["rear"],
               left=sb["left"], right=sb["right"],
               street_side="front",
               occupancy_class=getattr(brief, "occupancy_class", "R-2")), info


def run(brief: Brief, verbose: bool = True):
    """Execute the C.2 pipeline. Returns (Layout, Topology, reasoning) on
    success, or raises RuntimeError if no feasible layout can be produced
    after MAX_REPAIR rounds."""
    rules = Rules()
    lot = _make_default_lot(brief)
    shell = shell_category(lot)

    if verbose:
        print(brief.summary())
        print(f"shell category: {shell}  |  buildable {lot.envelope().w:.1f}x{lot.envelope().h:.1f} m")

    client = get_client()
    error_feedback: Optional[str] = None

    for attempt in range(1 + MAX_REPAIR):
        if verbose:
            tag = "first attempt" if attempt == 0 else f"repair attempt {attempt}"
            print(f"\n[{tag}]  LLM client: {type(client).__name__}")

        topo_dict, reason = client.generate(brief, error_feedback=error_feedback)
        if verbose:
            print(f"  reasoning: {reason}")

        # schema-validate
        try:
            topo = _topology_from_dict(topo_dict)
        except Exception as e:
            error_feedback = f"topology JSON didn't fit our schema: {e}"
            if verbose:
                print(f"  schema error: {e}")
            continue

        # structural validate (orphans, missing entry, etc.)
        topo_errs = validate_topology(topo)
        if topo_errs:
            error_feedback = "structural topology errors: " + "; ".join(topo_errs)
            if verbose:
                print(f"  structural errors: {topo_errs}")
            continue

        # try to realize geometry
        try:
            layout = solve(topo, lot, rules, time_limit_s=10.0, verbose=False)
        except RuntimeError as e:
            error_feedback = f"solver couldn't realize the topology geometrically: {e}"
            if verbose:
                print(f"  solver failed: {e}")
            continue

        # final compliance check (defensive — the solver should guarantee this)
        issues, score = validate(layout, rules)
        errs = [i for i in issues if i.severity == "error"]
        if errs:
            error_feedback = f"validator caught {len(errs)} hard violation(s): " + \
                             "; ".join(str(i) for i in errs[:3])
            if verbose:
                print(f"  validator caught errors: {error_feedback}")
            continue

        # success
        if verbose:
            warns = [i for i in issues if i.severity == "warning"]
            sugg = [i for i in issues if i.severity == "suggestion"]
            print(f"  COMPLIANT  score={score:.2f}  {len(warns)} warn  {len(sugg)} sugg")
        return layout, topo, reason

    raise RuntimeError(
        f"could not produce a feasible layout after {1 + MAX_REPAIR} attempts. "
        f"last feedback: {error_feedback}"
    )
