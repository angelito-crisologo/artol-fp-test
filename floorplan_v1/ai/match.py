"""Match structured requirements against the hand-authored topology catalog.

Two things are structurally fixed per topology (can't be changed by brief
parameters at solve time): its room program (bedroom count) and its
target_shell (squarish/wide/deep/...). Everything else on Brief (carport
type, bath preferences, swap_master_standard, ...) is a parameter applied
WHEN a topology is run, not a filter on which topologies are candidates.

So matching here is a hard filter on (bedroom_count, shell) — no scoring,
no near-misses. Empty results are expected and correct when nothing in the
catalog fits (e.g. a 3BR ask today, before the wide-shell catalog's Phase 2
topologies exist).
"""
import json
import os
import sys
from dataclasses import dataclass
from typing import List

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_TOPOLOGIES_DIR = os.path.join(_PROJECT_ROOT, "topologies")
for _sub in ("core", "solver"):
    _p = os.path.join(_PROJECT_ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model import shell_category  # noqa: E402

_BEDROOM_TYPES = {"master_bedroom", "bedroom_standard"}


@dataclass
class Candidate:
    id: str
    label: str
    filename: str          # relative to topologies/, e.g. "1s/2br/squarish/x.json"
    target_shell: str
    bedroom_count: int
    notes: List[str]


def _iter_topology_files():
    for root, _dirs, files in os.walk(_TOPOLOGIES_DIR):
        for fn in files:
            if fn.endswith(".json"):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, _TOPOLOGIES_DIR)
                yield rel, full


def _load_candidate(rel_path: str, full_path: str) -> Candidate:
    with open(full_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    bedroom_count = sum(1 for r in d.get("rooms", []) if r.get("type") in _BEDROOM_TYPES)
    return Candidate(
        id=d["id"], label=d["label"], filename=rel_path,
        target_shell=d["target_shell"], bedroom_count=bedroom_count,
        notes=d.get("notes", []),
    )


def all_topologies() -> List[Candidate]:
    """Every topology in the catalog, unfiltered. Useful for debugging/tests."""
    return [_load_candidate(rel, full) for rel, full in _iter_topology_files()]


def match_topologies(brief) -> List[Candidate]:
    """Hard-filter the catalog by (brief.bedroom_count, shell-from-lot-dims).

    `brief` needs lot_width, lot_depth, bedroom_count, carport_side,
    occupancy_class, and (optionally) setbacks — i.e. anything
    ai/pipeline.py::_make_default_lot reads. Imported lazily to avoid a hard
    circular-import dependency at module load time.
    """
    from pipeline import _make_default_lot  # noqa: E402 (ai sibling)

    lot = _make_default_lot(brief)
    shell = shell_category(lot)
    out = [c for c in all_topologies()
           if c.target_shell == shell and c.bedroom_count == brief.bedroom_count]
    out.sort(key=lambda c: c.id)
    return out, shell
