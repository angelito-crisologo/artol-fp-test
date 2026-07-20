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

**2026-07-20 — Full regen (45 topologies, 32 verified, 13 not yet tested)**
Ran `tools/topology_catalog/build_catalog.py` to pick up the four 1BR LDK
siblings' new canonical `briefs/test/` entries (previously only had
`briefs/test_sweep/` fixtures, which the catalog build doesn't read).
Verified: HTML well-formed, header stats match (45/32/13), all four
(`1s_1br_sq_side_split_bath_ld`, `1s_1br_nw_front_back_split_bath_ld`,
`1s_1br_wd_side_split_bath_ld`, `1s_1br_wd_split_wing_bath_ld`) now show
"Verified" with rendered plans (spot-checked
`1s_1br_wd_side_split_bath_ld`). Verified-count 28→32, unverified 17→13.

**2026-07-20 — Full regen (45 topologies, 28 verified, 17 not yet tested)**
Ran `tools/topology_catalog/build_catalog.py`. Verified: HTML well-formed
(tag-balance check), header stats match (45/28/17), gallery card + detail
page counts both 45, the two removed hall topologies confirmed absent
(only a historical prose mention survives in a sibling's notes), a new
unverified LD card spot-checked and rendering correctly. Picked up
everything queued below plus the whole 1BR gr/ld restructuring this
session:

- `dining_counter` auto-decide made size-conditional for
  `1s_1br_sq_side_split_bath_gr` (`ai/brief.py`, `run.py`) — counter on at
  ≤9 m, off above. No visible diff on the canonical 9×9 brief (stays ≤9 m).
- **No-hall-in-1BR rule locked**: `1s_1br_wd_side_split_bath_hall_gr` and
  `1s_1br_nw_side_corridor_bath_hall` removed entirely (topology JSON,
  `briefs/test/` fixture, `test_baselines/` SVG). Both gallery cards +
  detail pages gone; topology count 43→41 from this alone before the LD
  additions below.
- **Min-is-gr / med+max-is-ld pattern established across all three 1BR
  shells** — four new LDK sibling topologies added, all currently
  *unverified* in the catalog (proof-of-concept, deliberately no
  `briefs/test/` entry yet, tested instead via the new
  `sweep_discover.py`/`sweep_test.py` pair against `briefs/test_sweep/`,
  which the catalog build does NOT read):
  - `1s_1br_sq_side_split_bath_ld` (squarish) — feasible 10×10–12×12.
  - `1s_1br_nw_front_back_split_bath_ld` (narrow) — feasible 9×11–10×12;
    its `gr` sibling restricted to a single compact 8×10 fixture.
  - `1s_1br_wd_side_split_bath_ld` (wide) — feasible 11×8/12×9 only (10×8
    infeasible); needed `ldk_horizontal: true` after diagnosing a hardcoded
    solver-rule conflict (living beside dining, not in front of it) and
    `mechanical_vent: true` on `living` (0 m² window at one size).
  - `1s_1br_wd_split_wing_bath_ld` (wide, second wide GR sibling) — same
    med/max-only split, same `mechanical_vent` fix on `living`.
  - All four *_gr siblings (`sq_side_split_bath_gr`, narrow
    `front_back_split_bath_gr`, both wide GR topologies) now restricted to
    a single compact fixture each — min is always their job.
- **Door-hinge fix**: `1s_1br_wd_split_wing_bath_gr` and its new `_ld`
  sibling both got `door_placement: "high_corner"` on the bedroom's door
  adjacency, moving it from clustering next to the front entry door to the
  rear end near the kitchen/counter. Both topologies' Output subsheets
  reflect the new hinge position.
- Header stats, accordion counts, and shape-filter pill counts all
  recomputed for the new 45/28/17 split.

---

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
