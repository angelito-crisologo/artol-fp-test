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

**2026-07-20 — `dining_counter` auto-decide is now size-conditional for one topology (shared code)**
`floorplan_v1/ai/brief.py` (`Brief.dining_counter` changed from `bool = True`
to `Optional[bool] = None`) + `floorplan_v1/run.py` (new
`_effective_dining_counter()`, wired into all 3 `architecturalize()` call
sites). An explicit `True`/`False` on a brief still always wins. When
unset, every topology still defaults to counter-on **except**
`1s_1br_sq_side_split_bath_gr`, which now auto-decides from the lot's
smaller dimension: counter on at ≤9 m, off above 9 m. Verified: 73/73
regression pass, plus a direct boundary check (9×9→on, 10×10→off,
9.77×8.5→on, 12.07×10.5→off, explicit overrides still win either
direction). **No visible regen diff expected** — this topology's current
canonical brief (9×9) stays ≤9 m, so its Output subsheet renders
identically; logged for completeness/future-brief awareness, not because
the published site is stale.

**2026-07-20 — new proof-of-concept topology on disk, not yet a catalog entry**
`floorplan_v1/topologies/1s/1br/squarish/1s_1br_sq_side_split_bath_ld.json`
— an LD (separate living/dining/kitchen) sibling of
`1s_1br_sq_side_split_bath_gr`, built to answer a feasibility question.
Confirmed feasible (10×10–12×12 m primary range; swept via
`sweep_discover.py`/`sweep_test.py`, NOT `briefs/test/` or `run.py --test`).
Deliberately has no `briefs/test/` entry and isn't referenced anywhere in
docs/memory yet. **Heads up:** because `build_catalog.py` walks the whole
`topologies/` tree, a regen run right now would surface this as a new
*unverified* gallery card — expected but premature until there's a
decision on whether it graduates to a real catalog entry.

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
