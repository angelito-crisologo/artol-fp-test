"""End-to-end pipeline: brief -> LLM -> topology -> solver -> Layout.

Includes the infeasibility-repair loop: if the solver can't realize the
LLM's topology, the failure is fed back to the LLM for a revised attempt
(up to MAX_REPAIR rounds). With the stub LLM this loop is a no-op (stub
returns the same thing); it'll become useful once Claude is wired in.
"""
import json
import os
import sys
from typing import Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "core"))    # core modules
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "solver"))  # solver modules
sys.path.insert(0, _HERE)                                  # ai siblings (brief, llm)

from model import Lot, shell_category                        # noqa: E402  (core)
from rules import Rules                                      # noqa: E402  (core)
from validator import validate, is_compliant                 # noqa: E402  (core)

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


def _make_default_lot(brief: Brief) -> Lot:
    """Lot built from the brief's dims with default 2 m setbacks and a 3 m
    carport setback on the side named by brief.carport_side. When
    carport_side is None the brief has no carport (ncp) and all setbacks
    are 2 m.

    A brief can override the four setbacks directly via its `setbacks` dict
    (e.g., `setbacks: {front: 2, rear: 2, left: 2, right: 0}` for a firewall
    on the right). When `setbacks` is given, carport_side/carport_type are
    ignored — the brief is fully in control of envelope geometry."""
    occupancy = getattr(brief, "occupancy_class", "R-1")
    explicit = getattr(brief, "setbacks", None)
    if explicit:
        return Lot(
            width=brief.lot_width, depth=brief.lot_depth,
            front=float(explicit.get("front", 2.0)),
            rear=float(explicit.get("rear", 2.0)),
            left=float(explicit.get("left", 2.0)),
            right=float(explicit.get("right", 2.0)),
            street_side="front",
            occupancy_class=occupancy,
        )
    front, rear, left, right = 2.0, 2.0, 2.0, 2.0
    side  = (brief.carport_side  or "").lower()
    ctype = (brief.carport_type  or "").lower()
    # Only fcp widens the setback — 3 m for the full side depth.
    # ccp keeps all setbacks at 2 m; the L-notch is a building_void in the
    # topology, not a wider lot setback.
    if ctype == "fcp":
        if side == "left":
            left = 3.0
        elif side == "front":
            front = 3.0
        elif side == "right":
            right = 3.0
    # ncp and ccp: all setbacks stay at 2.0
    return Lot(
        width=brief.lot_width, depth=brief.lot_depth,
        front=front, rear=rear, left=left, right=right,
        street_side="front",
        occupancy_class=occupancy,
    )


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
