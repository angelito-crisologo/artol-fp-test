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

_(empty — a full regen was run 2026-07-22, see Applied history)_

## Applied history

**2026-07-22 — Full regen (46 topologies, 33 verified, 13 not yet tested) — quadrant gr→ld + door fix + claim_dead_strips thickness guard**
Ran `tools/topology_catalog/build_catalog.py` to fold in the quadrant
(`1s_2br_wd_quadrant_split_baths_ds_ld`) changes + the shared-code guard
(net topology count unchanged, in-place modification):
- **Quadrant great_room split into separate living + dining** (matches its
  `_ld` name at last); solved via its new 12×10 canonical brief. Verified
  the plan now labels LIVING + DINING (no GREAT ROOM).
- **Master door moved hall → living, hinged at the SE corner**
  (`door_placement: high_corner`) so it corner-swings against the east wall.
- **SHARED CODE `claim_dead_strips` min-thickness guard** (`MIN_ALCOVE_THICKNESS_M
  = 0.15`) — rejects degenerate <0.15 m slivers (fixes the quadrant 13×10
  "missing wall"). Only affects `claim_dead_strips` topologies with such a
  sliver; among current baselines that's the quadrant only.
Verified: HTML well-formed (div balance 1770/1770), quadrant card + plan
render (Verified), no orphans. Careful NOT to fold in ~9 pre-existing
stale/nondeterministic baselines a blanket `--update-baselines` surfaced —
see [[claim-dead-strips-thickness-and-baseline-gotcha]]. 48/48 regression +
52/52 sweep pass.

**2026-07-21 — Full regen (46 topologies, 33 verified, 13 not yet tested) — new front-back hall_ld + l_wrap deletion**
Ran `tools/topology_catalog/build_catalog.py` to fold in two changes since
the previous same-day regen (net topology count unchanged: 46 → 46, −1
`l_wrap` +1 front-back):
- **New `1s_2br_wd_front_back_split_bath_hall_ld`** — wide 1-storey, single
  T&B, full LDK across the front (living|dining|kitchen side by side),
  bedrooms across the rear, central HALL notch (master/standard/T&B all
  door into it, hall opens into dining). The hall is what makes a full-LDK
  front-back split feasible — without it the right bedroom sits above only
  the kitchen, failing the hard bedroom-access validator rule (kitchen ∉
  `ACCESS_FROM`). Solver reqs: `zone_split` horizontal, `ldk_horizontal`,
  `kitchen_rear_pin: false`, end-only anchors, `match_widths` hall=T&B,
  `claim_dead_strips: true`. 0-warning band ~11×10/12×9 to 17×12; canonical
  min 12×10, fallback → `hall_gr`. Sweep set min 12×9 / med 12×10 / max
  13×9. See [[wide-2br-front-back-hall-ld]].
- **Deleted `1s_2br_wd_l_wrap_bath_hall_gr`** — near-duplicate of
  `hall_gr` (differed only in a `master↔great` wall + dropped `zone_split`);
  distinction was patchy (fell back to `hall_gr` byte-identical at many
  sizes). Nothing fell back TO it. See [[wide-2br-l-wrap-deleted]].
Verified: HTML well-formed (div balance 1768/1768), the new front-back
topology renders with card + plan (Verified). Manually pruned 3 orphaned
`l_wrap` build artifacts the regen left behind (`data/topologies/`,
`data/briefs/`, `plans/` — 0 index references, source deleted). 49/49
regression + 49/49 sweep pass.

**2026-07-21 — Full regen (46 topologies, 33 verified, 13 not yet tested) — wide-cl saga + claim_dead_strips flag + new hall_ld**
Ran `tools/topology_catalog/build_catalog.py` to fold in everything since
the 2026-07-20 ds_gr regen. Net topology count 44 → 46 (+`cl_gr` restored,
+`hall_ld` new). Changes captured:
- **New `1s_2br_wd_side_split_bath_hall_ld`** — LDK conversion of the wide
  single-bath hall topology, built as a depth-gated SIBLING (`hall_gr`
  kept: fallback target for 3 topologies + reaches shallower depth-5 lots).
  Broad clean 0-warning band (buildable width 7–12, depth ≥6, ~11×10 to
  16×12) — much better than narrow-band `cl_ld` (single-bath = fewer
  private-side width constraints). Published min 12×10; `fallback_topology`
  → `hall_gr` for sub-depth-6 lots; `claim_dead_strips: true`. New briefs:
  LD canonical 12×10, plus 11×9 for `hall_gr` (had only 14×10). Sweep set:
  gr min 11×9, ld med 12×10, ld max 13×11. See [[wide-2br-hall-gr-ld-pair]].
- **SHARED CODE: new per-topology flag `claim_dead_strips`** (`solver/topology.py`
  + `run.py`, threaded through all 8 construction sites; default False =
  zero effect anywhere it isn't set). Wires the multi-storey dead-strip
  claimer into the single-storey realize path. Enabled on `cl_ld` (claims
  ~0.86 m² at 12×10 → 0 dead space) and the new `hall_ld`.
- **Wide `cl_gr`/`cl_ld` pair** — `cl_gr` deleted then restored same-session
  as `cl_ld`'s depth-gated compact sibling (retuned its profile: kitchen
  1.8→1.6, hall greatest-dim 2.8→2.2-2.8 range); `cl_ld` narrow-band LDK
  (12×10–15×11.5), `claim_dead_strips` added. Fixed a month-old dangling
  `fallback_topology` (both had pointed at the 2026-06-25-deleted
  `wd_side_split_bath_gr`); `cl_ld` now → `cl_gr`, `cl_gr` → `hall_gr`.
  See [[wide-2br-cl-gr-to-ld]].
Verified: HTML well-formed (div balance 1768/1768), all 4 wide-cl/hall
topologies render with cards + plans, `hall_ld` shows Verified. Also pruned
2 long-stale orphaned build artifacts left from the 2026-07-20 1BR-hall
removals (`1s_1br_nw_side_corridor_bath_hall`, `1s_1br_wd_side_split_bath_hall_gr`
— 0 index references, source long gone). 49/49 regression + 46/46 sweep pass.

**2026-07-20 — Full regen (44 topologies, 31 verified, 13 not yet tested) — ds_gr removed (no replacement)**
Ran `tools/topology_catalog/build_catalog.py` to pick up the deletion of
`1s_2br_sq_side_split_baths_ds_gr` — topology count actually DROPPED this
time (45→44, verified 32→31), unlike the three prior gr→ld conversions
which were net-zero swaps: `1s_2br_sq_side_split_baths_ds_ld` already
existed as an independent topology beforehand, so no replacement was
built. Deleted the topology file + 3 `briefs/test/test_mins/`
fixtures/baselines. Removed the now-redundant `ds_gr` few-shot entry in
`ai/prompt.py` and the `ds_gr` line in `lot_size_sweep.py`'s topology
list. Also fixed 6 stale comparative-prose mentions of "squarish ds_gr"
inside the unrelated wide topology `1s_2br_wd_side_split_baths_ds_gr`'s
own label/notes (its id and its own compact-shell profile name are
unrelated and were left alone) — repointed to "ds_ld", verified the
"omits fallback_topology" claim still holds for `ds_ld`. Verified: HTML
well-formed (div tag balance 1669/1669), zero remaining
`1s_2br_sq_side_split_baths_ds_gr` mentions anywhere in the built site,
manually deleted 3 leftover `ds_gr` build artifacts (`data/topologies/`,
`data/briefs/`, `plans/`). 47/47 regression + 40/40 sweep fixtures pass.
See [[squarish-2br-ds-gr-removed]].

**2026-07-20 — Full regen (45 topologies, 32 verified, 13 not yet tested) — cl_hall_gr → cl_hall_ld swap**
Ran `tools/topology_catalog/build_catalog.py` to pick up the third gr→ld
conversion in this family (after `cl_gr`→`cl_ld` and `bath_gr`→`bath_ld`):
`1s_2br_sq_side_split_baths_cl_hall_gr` deleted, replaced by
`1s_2br_sq_side_split_baths_cl_hall_ld` (net topology count unchanged: 45
in, 45 out). Identical private column + mid-band hallway structure;
public side now living/dining/kitchen stacked front-to-rear, with the
hall's open-mouth adjacency retargeted from `great` to `dining`
specifically (tested `hall→living` directly — infeasible even at 11×11,
since the hall's middle-band position has to align with the middle-row
public room). Unlike the other two conversions in this family, this one
is a net **loss**: true floor moved from gr's 9.5×9.5 to ~9.9×9.9, and
loosening the compact-shell profile did not recover it (confirmed
structural, not tunable). Published minimum 10×10 anyway. Verified: HTML
well-formed (div tag balance 1716/1716), `cl_hall_ld`'s gallery card +
detail page render with "Verified" status and its own SVG plan,
`cl_hall_gr` no longer appears as a topology entry. Manually deleted 3
leftover `cl_hall_gr` artifacts the regen script left behind
(`data/topologies/`, `data/briefs/`, `plans/` — one file each). 50/50
regression + 32/32 sweep fixtures pass (36/36 by the time near-square
fixtures were added for both `cl_hall_ld` and `bath_ld` afterward — those
sweep-only fixtures aren't part of the catalog build). Full narrative
detail: CLAUDE.md "Recently completed" + memory
[[squarish-2br-cl-hall-gr-to-ld]].

**2026-07-20 — Full regen (45 topologies, 32 verified, 13 not yet tested) — bath_gr → bath_ld swap + zone-ratio generalization**
Ran `tools/topology_catalog/build_catalog.py` to pick up three same-day
changes on the squarish 2BR single-bath topology (net topology count
unchanged: 45 in, 45 out):
1. **Deleted `1s_2br_sq_side_split_bath_gr`, replaced by
   `1s_2br_sq_side_split_bath_ld`** — great-room public side converted to
   living/dining/kitchen stacked front-to-rear. Published minimum 10×10
   (down from gr's 10.5×10.5); required re-tuning the kitchen
   compact-shell profile's `min_least_dim_m` from 2.0 to 1.6. Not a
   clean-warning win like `cl_gr`→`cl_ld` — `window_area_habitable` and
   `bath_door_into_kitchen` persist at the same sizes gr had them.
2. **Repositioned master to the rear** (standard now front, master rear) —
   mirrors the `cl_gr`→`cl_ld` reposition mechanism. Tightened the true
   floor to ~9.65×9.65 (10×10 stays published).
3. **SHARED CODE:** generalized `solver.py`'s hardcoded 55/45-favoring-
   private zone-ratio block into per-topology `zone_ratio_private_floor_pct`
   / `zone_ratio_private_target_pct` fields (default 50.0/55.0, verified
   byte-for-byte unchanged for every other topology). `bath_ld` is the
   first topology to use non-default values (40.0/45.0, a deliberate 45%
   private / 55% public split including the bath), paired with a
   `zone_balance_rooms` override. See [[zone-ratio-configurable]].

Verified: HTML well-formed (div tag balance 1708/1708), `bath_ld`'s
gallery card + detail page render with "Verified" status and its own SVG
plan, `bath_gr` no longer appears as a topology entry. Manually deleted 3
leftover `bath_gr` artifacts the regen script left behind (`data/topologies/`,
`data/briefs/`, `plans/` — one file each; confirmed they were the 2BR ones,
not the still-existing unrelated 1BR `1s_1br_sq_side_split_bath_gr`).
56/56 regression + 29/29 sweep fixtures pass. Full narrative detail for
all three changes: CLAUDE.md "Recently completed" + memory
[[squarish-2br-bath-gr-to-ld]] / [[zone-ratio-configurable]].

**2026-07-20 — Full regen (45 topologies, 32 verified, 13 not yet tested) — cl_gr → cl_ld swap**
Ran `tools/topology_catalog/build_catalog.py` to pick up the deletion of
`1s_2br_sq_side_split_baths_cl_gr` and its replacement,
`1s_2br_sq_side_split_baths_cl_ld` (net topology count unchanged: 45 in,
45 out). Verified: HTML well-formed (div tag balance 1706/1706), `cl_ld`'s
gallery card + detail page render with "Verified" status and its own SVG
plan, `cl_gr` no longer appears as a topology entry (only survives as a
historical mention inside `cl_ld`'s own prose notes, expected). The build
script doesn't prune orphaned per-topology files for deleted topologies —
manually deleted 3 leftover `cl_gr` artifacts it left behind
(`data/topologies/`, `data/briefs/`, `plans/` — one file each) that the
regen itself didn't touch.

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
