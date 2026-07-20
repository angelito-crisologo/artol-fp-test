# Topology Changes Tracker

Source of truth for what has changed in `floorplan_v1/` (topologies, test
briefs, shared solver/render code) since `artol-topologies/` — the published
HTML catalog — was last regenerated. The catalog is a build artifact, not
hand-edited; instead of re-deriving a diff from git history every time,
log the change here as it happens, then clear the log in one regen pass.

## Workflow

1. Whenever you create or modify a topology JSON, its canonical test brief,
   or any shared code that affects solving/rendering (`solver/*.py`,
   `core/render.py`, `core/model.py`, `ai/brief.py`, `run.py`), add an entry
   under **Pending** below before you consider the change done.
2. Shared-code entries have catalog-wide blast radius. Don't try to
   cherry-pick which topologies "probably" changed — regenerate the whole
   site and eyeball the diff, the same way the door-swing fix's 25-file
   baseline diff was triaged this session.
3. After `artol-topologies/` is regenerated, move the entries from
   **Pending** into **Applied history** with the regen date, then blank
   the Pending section.

## HTML doc regions (reference)

What a regen actually touches, so entries below can point at it precisely:

- **Gallery card** — `plans/<id>.svg` thumbnail + meta chips, index page
- **Detail → Definition** subsheet — legend, notes, adjacencies, overrides, JSON panel
- **Detail → Test Brief** subsheet — facts, prose, JSON panel
- **Detail → Output** subsheet — rendered SVG, validator chips, dims table
- **Header stats** — total / verified / unverified counts
- **Accordion + filter counts** — per-bedroom-count group totals, shape filter pills

## Regenerating

```
source .venv/bin/activate   # needs ortools + cairosvg, see repo root .venv
python3 tools/topology_catalog/build_catalog.py
```

Solves every topology's canonical test brief through the real CP-SAT
pipeline and rewrites `artol-topologies/{index.html,plans/,data/,assets/}`
from scratch. Canonical-brief selection (smallest no-carport lot,
excluding swap/kdoor/lanai/dk_svc variants and fallback-proof briefs) is
in `pick_canonical_brief()`. The script and its `assets/` templates are
checked in under `tools/topology_catalog/` — see that directory's
`build_catalog.py` docstring for the full field-by-field derivation notes
(legend colors, "Notable overrides" key→description map, dims-table
grouping, etc.) if extending it for a new topology-JSON key.

## Pending (not yet reflected in `artol-topologies/`)

_(empty — a full regen was run 2026-07-20, see Applied history)_

## Applied history

**2026-07-20 — Full regen (43 topologies, 30 verified, 13 not yet tested)**
Ran `tools/topology_catalog/build_catalog.py` (recreated this session —
the original scratchpad build scripts were gone, see the superseded
"Known gap" note this replaces). Picked up everything queued below, plus
6 brand-new topologies the queue hadn't caught up to bringing the catalog
from 38→43 topologies:

- Door-swing hinge fix (`architectural_plan.py::_door_for_adjacency`) —
  catalog-wide re-render, all Output subsheets refreshed.
- Master-bedroom-supremacy rule extended to all standard bedrooms
  (`solver.py` + `snap_gaps.py`) — all 3BR Output/Test-Brief subsheets
  refreshed, including `1s_3br_sq_hall_core_baths_ds_hall_gr`'s re-tuned
  13.5×14.5 canonical brief.
- `dining_counter` Brief override (`ai/brief.py`, `run.py`,
  `architectural_plan.py`) — visible in the 8 2-storey briefs' Test Brief
  JSON panels; counter no longer renders in their Output subsheets.
- 2-storey matrix completion — new gallery cards + full detail pages for
  `2s_2br_sq_rear_stair_bath_gr`, `2s_2br_wd_rear_stair_bath_gr`,
  `2s_2br_nw_side_spine_stair_bath` (hall-less sibling),
  `2s_3br_wd_rear_stair_baths_ds_gr`,
  `2s_3br_nw_side_spine_stair_baths_ds_gr`,
  `2s_3br_sq_rear_stair_baths_ds_gr` — completes the
  {2BR,3BR}×{narrow,squarish,wide} 2-storey matrix.
- `1s_3br_sq_front_back_split_baths_cl_hall_lk` — over-constrained-anchor
  fix now reflected (was previously showing the old infeasible-everywhere
  topology's stale render).
- Header stats, accordion counts, and shape-filter pill counts all
  recomputed for the new 43/30/13 split.
