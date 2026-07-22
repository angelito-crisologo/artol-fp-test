# artol-ai — Active project context

PH floor plan generator + validator. Single-detached mid-market houses. CP-SAT solver.

## Session handoff (2026-07-19) — read this first

**Not yet committed** — this session's work (and the prior 2026-07-16
session's) sits uncommitted in the working tree; user is doing a manual
folder backup before committing. Full regression: **68/68 pass**.

### Multi-storey v2 — built from scratch this session

The pipeline now supports 2-storey topologies end to end: one joint CP-SAT
solve (no-overlap grouped per storey), a `stair_vertical` adjacency kind
that pins the GF flight and 2F stairwell to the identical rectangle,
`stair_boarding`/`stair_arrival` kinds that force the ascent direction so a
flight can never top out against a bedroom wall, per-floor
validate/snap/archplan post-passes, a dead-strip claimer (L-alcoves for
partial-edge gaps a normal snap can't reach), a composite side-by-side SVG
(GROUND FLOOR | SECOND FLOOR titles), and a rendered stair glyph (tread
lines + UP/DN travel arrow driven by the solver's own ascent decision).
Full design + task-by-task log: **`MULTISTOREY_V2_DESIGN.md`** (repo root).
Authoring checklist for the next 2-storey topology: memory
[[multistorey-topology-authoring]].

First topologies: `2s/2br/narrow/2s_2br_nw_side_spine_stair_bath_hall.json`
(GF hall retained) and its compact sibling `..._bath.json` (hall-less —
the great room IS the GF circulation, which also unlocks a dining
counter). The size rule between them is a new general mechanism,
`fallback_below_buildable_sqm` (paired with `fallback_topology`): below
28 m²/floor the runner auto-routes to the hall-less sibling with a
`compact_fallback` suggestion, *before* attempting a solve — this is
intent, not an infeasibility fallback. 3 test briefs cover hall-retained
(8×12), hall-less direct (8×10), and the auto-switch (8×10 requesting the
hall variant). The hall-less sibling needed `zone_balance_rooms` (whole
2F minus stairwell counts as private) to be solvable at all — see the
memory for why.

Three other 2s reference specs (`front_stair_foyer`, `mid_core_ustair`,
`rear_stair_understair`) were copied in but never converted to real
topology JSON — relocated to `docs/reference/2s_unconverted_specs/` in
the repo cleanup below so they don't list as broken 0-bedroom matcher
candidates.

### 3BR squarish topology fixes

Two pre-existing-but-untested 3BR squarish topologies
(`1s_3br_sq_hall_core_baths_ds_hall_gr`, `..._front_back_split_baths_cl_hall_lk`)
were **infeasible at every lot size** (proved up to 20×20 m buildable —
not a sizing issue). Both traced to over-constrained `left_anchored`/
`right_anchored`/`rear_anchored` combinations fighting the topology's own
`front_to_rear_stacks` + adjacency graph — same failure signature both
times. Fixed by dropping the conflicting anchor list(s) (kept
`rear_anchored` where it matters for window/ventilation) and, for
hall_core, adding a new `kitchen_side_pin: false` flag (kitchen on the
non-carport side legitimately contradicts the default mirror-symmetry
pin). Both now verified COMPLIANT at their claimed minimum lot sizes plus
ccp/fcp variants. Full trail: memory
[[solver-topology-overrides]] (the "recurring 3BR-catalog trap" note).
**The other 10 topologies dropped into `1s/3br/{narrow,squarish,wide}/`
this session remain unvalidated** — no test brief, not run through the
solver — see Open/deferred.

### Repo cleanup + restructure (2026-07-19)

Root went from ~14 loose files to 5 + `docs/`. Moved:
`ph_floorplan_rules.json` → `floorplan_v1/data/` (was reaching `../..`
from `core/rules.py` — now self-contained; path constant updated).
Historical docs (Phase-1 docx, the pre-Mac-reset backup/memory-export
pair) → `docs/archive/`. Reference material (NBC full text,
`common-configs/`, the 3 unconverted 2s specs) → `docs/reference/`.
Deleted: regenerable caches/output, 14 orphaned test baselines from a
retired naming scheme, `debug_brief.py`, `LANAI_REQUIREMENTS.md` (shipped
feature, findings absorbed elsewhere). **Not yet deleted** (user doing it
manually): `floorplan_v1/ai-output.png`, a stray untracked debug PNG with
no code references.

---

## Session handoff (2026-07-16)

GitHub remote in sync, both commits pushed
(`github.com/angelito-crisologo/artol-fp-test`, `8c275de`, `780df73`).
Streamlit Cloud deployment at `https://artol-fp.streamlit.app/` picks up
pushes automatically (~1 min rebuild). Full regression at the time: **61/61
pass** (now 68/68 — see the 2026-07-19 handoff above).

This session built the entire **1-bedroom topology catalog** — 7 new
topologies across all three shells, each reverse-engineered from a
reference floor-plan image (now deleted from the repo root post-session)
and verified to a COMPLIANT solve at a canonical lot size. Full detail in
[[br1-topology-catalog]]; summary here:

1. **Squarish**: `1s_1br_sq_side_split_bath_gr` (9×9 lot, 5×5 shell) — a
   straight-cut 2×2 grid matching `square-topology.png` exactly (bedroom +
   bath left column, great room + kitchen right column, one straight
   vertical wall).
2. **Narrow** (3 topologies): the pre-existing `nw_side_corridor_bath_hall`
   (fixed a `left_anchored` bug, now solves 8.5×12 up — removed 2026-07-20,
   see the 1BR topologies list below), plus two new ones —
   `nw_front_back_split_bath_gr` (8×10, from `narrow-fp-01.png`) and
   `nw_front_rear_bath_gr` (8×10, from `narrow-fp-02.png`, full-width rear
   bedroom).
3. **Wide** (2 new, alongside the pre-existing `wd_side_split_bath_hall_gr`
   which needed ≥13.3×9.5 — removed 2026-07-20, see the 1BR topologies list
   below): `wd_split_wing_bath_gr` (10×8, from `wide-fp-01.png`, wet
   end-column) and `wd_side_split_bath_gr` (10×8, user-requested variant —
   bath+kitchen rear band instead of end column, bath doors into the
   kitchen per a later revision).
4. **New dining-counter feature** (`counter_divider` adjacency flag) — all
   7 topologies use it instead of a full dining room (furnishability math:
   a great_room at its 6 m² hard minimum only fits a couch + TV, no
   table). See [[counter-divider-dining-spec]] — LOCKED design, do not
   re-propose the rejected `kitchen_dining` nook type or `lkc` config.
5. **Six new per-topology solver overrides** needed to make these small
   programs solvable: `match_widths`, `private_area_floor`,
   `zone_balance_rooms`, `aspect_overrides`, `kitchen_rear_pin`,
   `set_max_area_sqm`. See [[solver-topology-overrides]] — same
   "thread through all 7 Topology-copy sites" trap as `ldk_horizontal`.
6. **Fixed a real pre-existing bug**: `shell_category()` never returned
   `"narrow"` (only `"deep"`/`"super_deep"`), so `ai/match.py` could never
   surface ANY narrow topology through the Streamlit app, 1BR or the 5
   pre-existing 2BR ones. Fixed by merging the buckets. See
   [[shell-category-narrow-fix]] — `extra_wide` has the same unfixed gap
   (`wide`-labeled topologies never match `extra_wide` lots), flagged not
   fixed, scoped out by explicit user instruction.
- Remember [[ask-before-coding]] — this project's standing convention.

## Current focus (as of 2026-06-25)

**Naming convention locked:** `{storey}_{nbr}_{WxD}_{shape}_{strategy}_{bath_token}[_hall][_gr|_ld]_{carport}[_swap]`
Shapes: `sq`, `wd`, `dp`, `swd`, `sdp` | Strategies: `side_split`, `front_rear`, `l_wrap`, `z_wrap`, `split_wing` | Bath: `bath`, `bath_pwd`, `baths_cl`, `baths_ds`, `baths_mix` | Carport: `ncp`, `fcp`, `ccp`

**Carport type semantics (locked):**
- `ncp` — no carport; building_void + carport setback element stripped; rectangular envelope.
- `fcp` — full carport; entire side setback is 3 m throughout; building_void stripped; rectangular envelope (narrower shell than ccp). Set `carport_side` + `carport_type: fcp` in brief; explicit `setbacks.right/left: 3.0`.
- `ccp` — claimed carport; 3 m for first 6 m of depth, 2 m beyond; L-notch via building_void. `setbacks` all 2.0, void creates cutout.

**Wide 2BR topologies** (`floorplan_v1/topologies/1s/2br/wide/`):

- `1s_2br_wd_side_split_bath_hall_ld` / `1s_2br_wd_side_split_bath_hall_gr` — single bath, mid-band
  hall serving both bedrooms + common bath. A **depth-gated sibling pair** (added `ld` 2026-07-21):
  - `hall_gr` (combined great room, 2-deep public stack) — reaches shallow lots down to buildable
    depth 5. Canonical 14×10; also has an 11×9 test brief. Fallback target for 2 other wide
    topologies (`front_back_split_baths_ds_gr`, `cl_gr`), so it stays.
  - `hall_ld` (living/dining/kitchen split) — public side splits into stacked living/dining/kitchen,
    hall opens into dining (mid-row). Needs buildable depth ≥ 6 (published min 12×10); routes
    sub-depth-6 lots to `hall_gr` via fallback. Notably **broad, clean 0-warning band** (buildable
    width 7–12, depth ≥6 → ~11×10 to 16×12) — much better-behaved than `cl_ld` because it's
    single-bath with no ensuite/clustered-block/`match_*width` constraints. Upper-width limit
    (~buildable 12) is a soft public-room aspect cap, past the 2BR band anyway. Uses
    `claim_dead_strips: true` (master's floating front-band width leaves pockets at larger sizes;
    living absorbs them). See [[wide-2br-hall-gr-ld-pair]].
- `1s_2br_wd_side_split_baths_cl_ld` / `1s_2br_wd_side_split_baths_cl_gr` — clustered baths at rear
  band, mid-band hall serves both bedrooms + common bath (matches the squarish `cl_hall_gr`/
  `cl_hall_ld` pattern). Now a **depth-gated sibling pair**, not a gr→ld replacement:
  - `cl_gr` (combined great_room, 2-deep public stack) — the one to use down to ~5 m buildable
    depth. Published minimum 11×9. Its own compact-shell profile needed retuning to reach that
    (kitchen `min_least_dim_m` 1.8→1.6, hall's `min_greatest_dim_m` loosened from a rigid fixed
    2.8 to a 2.2-2.8 range — bisected to confirm neither alone was sufficient, and bath caps
    turned out unnecessary).
  - `cl_ld` (separate living/dining/kitchen, 3-deep public stack) — needs ≥~5.5 m buildable depth
    for that stack to fit (confirmed by isolating the LDK column alone: solves at 5.5 m depth,
    fails at 5.0 m, even with unlimited width — width doesn't help, this is a depth-specific
    floor). Published minimum 12×10 (true floor ~11.9×10). Feasible band tops out around
    15×11.5 — infeasible for good above that (structural, isolated to the `hall↔dining`
    adjacency; `hall`'s width is effectively locked to the middle sub-column's width via
    `match_bedroom_widths`, which doesn't scale with the envelope).
  - `cl_ld.fallback_topology` now points to `cl_gr` (deliberately relying on the general
    infeasibility-triggered fallback, not an area-based `fallback_below_buildable_sqm` gate,
    because the binding constraint is DEPTH not AREA — a wide-but-shallow lot has plenty of area
    but still can't reach `cl_ld`). Along the way, fixed a month-old dangling reference: both
    topologies' `fallback_topology` had pointed at `1s_2br_wd_side_split_bath_gr.json`, deleted
    2026-06-25 and superseded by `1s_2br_wd_side_split_bath_hall_gr.json` — the field was never
    updated back then and sat silently broken until this investigation exercised it.
  - See [[wide-2br-cl-gr-to-ld]] for the full trail (title is dated — the topology went
    delete→restore→retune within the same session).
- `1s_2br_wd_side_split_baths_ds_gr` — distributed baths, no hall, both
  bedrooms direct-to-great (renamed 2026-07-13 from `..._ds_hall_gr` after
  removing the hall)
- `1s_2br_wd_front_back_split_baths_ds_gr` — front-back split (not vertical
  column split like everything else); great_room + kitchen side-by-side at
  front, master|ensuite|common|standard in one row at rear. See
  [[front-back-split-topology-solver-bug]] for how it was made to work —
  uses the new `ldk_horizontal` topology flag.
- `1s_2br_wd_front_back_split_bath_hall_ld` — front-back split, **1 bath**,
  **full LDK** (living|dining|kitchen side by side across the front) with a
  central **hall notch**. Rear band: master (left) | hall+T&B middle column
  (hall front / T&B behind) | standard (right); all 3 private rooms door into
  the hall, which opens into dining. Built 2026-07-21 to spec. The hall is
  what makes it feasible — with the LDK split, the right-side bedroom sits
  above only the kitchen, and a bedroom can't be accessed through a kitchen
  (validator `ACCESS_FROM` = living/dining/great/**hallway**). Same solver
  requirements as the `ds_gr` front-back sibling (`zone_split` horizontal,
  `ldk_horizontal`, `kitchen_rear_pin: false`, don't crowd anchors) plus
  `match_widths` hall=T&B and `claim_dead_strips: true`. Broad 0-warning band
  (~11×10/12×9 to 17×12), canonical min 12×10, fallback → `hall_gr`. Plumbing
  note: T&B is rear-middle, far from the front kitchen — independent plumbing,
  no shared wet-wall. See [[wide-2br-front-back-hall-ld]].
- `1s_2br_wd_quadrant_split_baths_ds_ld` — private/public in diagonal
  quadrants; living+dining+standard up front, master+ensuite | hall/common
  (stacked) | kitchen at rear. hall is the circulation hinge. Great room
  split into separate living+dining 2026-07-21 (now actually matches its
  `_ld` name — see [[quadrant-split-topology]]); uses `ldk_horizontal` +
  `claim_dead_strips`.

**Square 2BR topologies** (`floorplan_v1/topologies/1s/2br/squarish/`):

- `1s_2br_sq_side_split_bath_ld` — single bath, private column left (standard front / master rear,
  master repositioned to the rear 2026-07-20 same day as creation); public side is separate
  living/dining/kitchen (stacked, solver's default LDK arrangement), not a great room. Published
  canonical minimum 10×10 (kitchen's compact-shell profile tuned to 1.6 m least-dim, down from the
  gr sibling's 2.0 m, specifically to hit this floor) — the reposition actually tightened the
  solver's true floor further to ~9.65×9.65, but 10×10 stays the published minimum since nothing
  asked for a further re-tune. Replaced `1s_2br_sq_side_split_bath_gr` (deleted 2026-07-20 — NOT a
  clean-warning win like the cl_gr→cl_ld swap: `window_area_habitable` and `bath_door_into_kitchen`
  persist here at most sizes, same as gr). Deliberately public-heavy zone ratio (45% private /
  55% public, including the bath on the public side) via two new configurable `Topology` fields —
  see [[zone-ratio-configurable]]. See also [[squarish-2br-lot-size-sweep]].
- `1s_2br_sq_side_split_bath_pwd_gr` — single bath + powder room, 4-room rear band; buildable width ≤ ~11 m
- `1s_2br_sq_side_split_baths_cl_ld` — clustered baths (ensuite + common), private column;
  standard front / master rear; public side is separate living/dining/kitchen (stacked, solver's
  default LDK arrangement), not a great room. True min 10.5×10.5. Replaced
  `1s_2br_sq_side_split_baths_cl_gr` (deleted 2026-07-20 — the LD split proved strictly better:
  smaller true minimum than cl_gr's 11×11, 0-warning solves everywhere tested). See
  [[squarish-2br-lot-size-sweep]].
- `1s_2br_sq_side_split_baths_cl_hall_ld` — clustered baths with a mid-band hall (between master
  front / standard rear); public side is separate living/dining/kitchen (stacked), not a great
  room — the hall's open mouth connects to dining (the middle-row public room), not living. Published
  minimum 10×10 (true floor ~9.9×9.9) — WORSE than the gr sibling's 9.5×9.5 by design cost, not a
  tunable threshold (tried loosening the compact-shell profile, floor didn't move). Warning profile
  at 10×10/11×11/12×12 is otherwise identical to gr. Replaced `1s_2br_sq_side_split_baths_cl_hall_gr`
  (deleted 2026-07-20). `fallback_topology` (→ `cl_ld`) carried over unchanged.
- `1s_2br_sq_side_split_baths_ds_ld` — distributed baths, living/dining (its `_gr` sibling was
  deleted 2026-07-20 — unlike the other three gr→ld conversions this session, `ds_ld` already
  existed as a separate topology beforehand, so this was a straight removal, not a build-then-swap)

**1BR topologies** (`floorplan_v1/topologies/1s/1br/{squarish,narrow,wide}/`,
added 2026-07-16 — full detail in [[br1-topology-catalog]]):

- `sq_side_split_bath_gr` — squarish, 9×9 lot, straight-cut 2×2 grid
- `nw_front_back_split_bath_gr` — narrow, 8×10, bedroom door via kitchen side
- `nw_front_rear_bath_gr` — narrow, 8×10, full-width rear bedroom
- `wd_split_wing_bath_gr` — wide, 10×8, wet end-column
- `wd_side_split_bath_gr` — wide, 10×8, wet rear band, least override-hungry

**Min-is-gr / med+max-is-ld pattern (2026-07-20):** every `_gr` topology
above is now restricted to a single compact/min canonical brief — larger
lots use a new `_ld` sibling (separate living/dining/kitchen) instead:
- `sq_side_split_bath_ld` — squarish, 11×11 canonical, feasible 10×10–12×12
- `nw_front_back_split_bath_ld` — narrow, 9×11 canonical (tight — bedroom
  and dining both near hard floors, but COMPLIANT), feasible 9×11–10×12
- `wd_side_split_bath_ld` — wide, 11×8 canonical, feasible 11×8/12×9 only
  (10×8 infeasible); needed `ldk_horizontal: true` (living sits beside
  dining, not in front of it — conflicts with the solver's default LDK
  stacking rule) and `mechanical_vent: true` on living
- `wd_split_wing_bath_ld` — wide, 11×8 canonical, feasible at both med/max,
  same `mechanical_vent` fix on living

All four now have real `briefs/test/` canonical briefs + `test_baselines/`
entries (graduated from `briefs/test_sweep/`-only proof-of-concept).
`wd_split_wing_bath_gr` and its `_ld` sibling also got a door-hinge fix
(`door_placement: "high_corner"` on the bedroom's door) moving it from
next to the front entry to the rear near the kitchen/counter. Full trail
in [[br1-topology-catalog]].

**Locked rule (2026-07-20): no hall in any 1BR topology.** A hall earns its
keep by keeping cross-bedroom traffic out of each other's way — with only
one bedroom there's no cross-traffic to manage, so it's just circulation
overhead stealing floor area from habitable rooms. Two topologies removed
under this rule, both replaced in the catalog by their hall-less siblings
above:
- `wd_side_split_bath_hall_gr` (wide, 14×10) — true feasibility floor
  (~13.3×9.5, 51 m²) sat inside the locked 2BR/1bath floor band anyway, not
  a genuinely 1BR-scaled size.
- `nw_side_corridor_bath_hall` (narrow, 8.5×12) — hall alone was 4.4 m²
  (~12% of the 36 m² floor), directly correlating with great_room sitting
  at only 15% of its preferred size; its hall-less siblings solve the same
  shell at the same ~24–36 m² scale without that tax.

See [[br1-topology-catalog]] for the full removal trail.

All 1BR topologies use `private_area_floor: false` (a single bedroom can
never outweigh the LDK under the hard "private ≥ public" rule) and the new
`counter_divider` dining-counter render feature — see
[[solver-topology-overrides]] and [[counter-divider-dining-spec]].

**3BR squarish topologies** (`floorplan_v1/topologies/1s/3br/squarish/`) —
2 of 4 files are verified, the other 2 (`l_wrap_baths_ds_hall_gr`,
`side_split_baths_cl_hall_gr`) plus everything under `1s/3br/{narrow,wide}/`
are unvalidated, see Open/deferred:

- `sq_hall_core_baths_ds_hall_gr` — pinwheel, 9.0×9.5 buildable min
  (fixed 2026-07-19, was infeasible everywhere as authored)
- `sq_front_back_split_baths_cl_hall_lk` — full-width front/rear bands,
  single wet stack, 9.0×9.0 buildable min (fixed 2026-07-19, same
  over-constrained-anchors bug class)

**2-storey topologies** (`floorplan_v1/topologies/2s/{nbr}/{shape}/`,
added 2026-07-19 — the multi-storey v2 pipeline, see the session handoff
above and [[multistorey-topology-authoring]] for how to author more):

- `2s_2br_nw_side_spine_stair_bath_hall` — narrow, GF hall retained,
  ~8×11+ lots (28+ m²/floor)
- `2s_2br_nw_side_spine_stair_bath` — narrow, hall-less compact sibling
  (great room is the GF circulation), 8×10 lot, auto-selected below the
  threshold via `fallback_below_buildable_sqm`
- `2s_2br_sq_rear_stair_bath_gr` — squarish (added 2026-07-19), rear-corner
  stair, hall-less GF, BOTH bedrooms side-by-side street-facing upstairs
  (2F-only zone_split); canonical 10×10 (72 m² gross — inside the 65–80
  band the narrow pair undershoots); feasible 9×10 up through 12×12+
- `2s_2br_wd_rear_stair_bath_gr` — wide (added 2026-07-19), the catalog's
  first HORIZONTAL stair run (sideways along the rear band — a 5 m-deep
  shell can't afford a front-to-rear run), full-width front great room,
  bath2 stacked over bath1; canonical 11×9 (70 m² gross); binding
  constraint is WIDTH ≥ 7.0 m (stair 3.5 + kitchen 2.1 + bath 1.4 in one
  rear band) — 11×8.5 solves, 10.5×9 doesn't despite more area
- `2s_3br_wd_rear_stair_baths_ds_gr` — wide, FIRST 2-storey 3BR (added
  2026-07-19): all 3 bedrooms upstairs (master+br2 street-facing front,
  br3 rear), landing hall as a compact mid-band CORE with 5 doors
  radiating (three-across-front was rejected — it forces a ~6.5 m back
  corridor past the hall aspect cap); baths distributed one per floor;
  canonical 12×10 (96 m² gross, mid-band); verified 11.5×9.5 (82) up to
  14×10.5, technically solves to 11×9 (70 — below band; treat the 80 m²
  band as the practical floor when matching)
- `2s_3br_nw_side_spine_stair_baths_ds_gr` — narrow 3BR sibling (added
  2026-07-19): same program re-partied for a deep ~5 m-wide shell —
  master full-width front, stairwell+hall as a left/mid SPINE (vs the
  wide sibling's core), br2 mid-right, br3 rear; GF kitchen as a
  rear-right COLUMN touching the great room (keeps the counter seam on
  a deep hall-less floor — a wet band between great and kitchen would
  landlock the kitchen); canonical 9×13 (90 m² gross), band floor at
  9×12/8×14 (80, rooms at hard minimums), up through 10×13 (108).
  Building it extended `claim_dead_strips` with rectangle decomposition
  (L-shaped holes now split into claimable rects — improved GF fill on
  ALL 2s topologies; their 6 baselines refreshed).
- `2s_3br_sq_rear_stair_baths_ds_gr` — squarish 3BR (added 2026-07-19,
  completes the 2s {2BR,3BR}×{narrow,squarish,wide} matrix): same graph
  as the wide 3BR, shell does the differentiating; ORIENTATION-ADAPTIVE
  stair (sideways on 7 m-wide floors, vertical rear-corner at ≤6.5 m);
  canonical 10.5×10.5 (84 m² gross, 100% coverage). Its authoring
  surfaced a THREE-layer leak of the "master is always larger" rule —
  solver (only first standard constrained → now ALL), snap_gaps (unequal
  growth eroded the margin → standards now capped at master−0.5), and
  the dead-strip claimer (alcove could outgrow master → guarded). The
  all-standards rule raised the 1s hall-core ccp minimum: its brief
  re-tuned 13.5×14 → 13.5×14.5; 9 baselines refreshed deliberately.

**Test suite status:** 75 pass, 0 fail, 0 error (includes 17 minimum-boundary
briefs under `briefs/test/test_mins/`, see [[squarish-2br-lot-size-sweep]],
10 1BR test briefs (6 gr/compact + 4 new ld/med — the four new LDK
siblings graduated from `briefs/test_sweep/`-only to real `briefs/test/`
canonical briefs 2026-07-20, each with a fresh `test_baselines/` entry;
`wd_side_split_bath_hall_gr` and `nw_side_corridor_bath_hall` were removed
earlier the same day, no-hall-in-1BR rule), and — added 2026-07-19/20 — 4
3BR-squarish-fix briefs + 8 multi-storey briefs).

## Recently completed

**Quadrant-split topology: great room finally split into living+dining (2026-07-21):** `1s_2br_wd_quadrant_split_baths_ds_ld` was named `_ld` but had shipped a great_room since its 2026-07-14 revision — a name/implementation mismatch. That revision *merged* living+dining into a great_room precisely because the original living+dining version was infeasible even at 34×34. Reversed it in-place now: split the great_room back into separate living (front-left) + dining (front-middle), so the topology matches its own name. Two things made the split feasible where it wasn't before: (1) `ldk_horizontal: true` (added later the same day in 2026-07-14, didn't exist when the original failed) disables the solver's hardcoded LDK stacking rule (living in front of dining+kitchen) that contradicted the side-by-side quadrant arrangement; (2) keeping kitchen NON-adjacent to dining (reached only via hall, as the great_room version already did) avoids the 3-way mutual adjacency (hall/kitchen/dining) the notes cite as the original blocker. Verified 0-warning across ~13×10 to 16×12 (oversized 25×18+ now just the ordinary non-monotonic upper bound, not the old total infeasibility). Added `claim_dead_strips: true` for the larger-size pockets. In-place conversion — same topology id, no fallback/prompt dependencies. Test briefs re-based afterward (user request): the old 14×11/14×10 canonical briefs were replaced by a single 12×10 brief (the clean 0-warning minimum), plus a 3-fixture sweep set — min 12×9 (buildable 8×5, the shallowest native solve; carries a soft `tiered_preferred_dropped` since the preferred bath/kitchen sizes don't fit at depth 5), med 12×10, max 13×10. 48/48 regression + 52/52 sweep pass. See [[quadrant-split-topology]].

**New front-back-split topology `1s_2br_wd_front_back_split_bath_hall_ld` (2026-07-21):** Built to an explicit user spec — wide 1-storey, single T&B (no ensuite), master + standard; whole front half a full LDK (living|dining|kitchen side by side), whole rear half private (master | middle | standard). First draft (each bedroom dooring into the public room in front of it) failed a HARD validator rule: `bedroom_standard has no access from a hallway or public room` — because the LDK split puts the right-side bedroom above only the **kitchen**, and the validator's `ACCESS_FROM` set is {living/dining/great/**hallway**}, NOT kitchen (a bedroom can't be reachable only through a kitchen). Retargeting standard→dining didn't help (over-constrained, infeasible even at 25×18). The fix — per the user's own next instruction — was a central **hall notch** (same width as the T&B via `match_widths`): master, standard, and T&B all door into the hall, which opens into dining; hallway IS valid bedroom access, so it resolves cleanly. Essentially the `hall_gr` circulation idiom rotated into a front-back split. Same solver requirements as the existing `front_back_split_baths_ds_gr` (`zone_split` horizontal / `ldk_horizontal` / `kitchen_rear_pin: false` / don't crowd the anchors — living left-anchored, kitchen right-anchored, ends only), plus `claim_dead_strips: true` (ragged widths leave pockets at larger sizes; living/hall absorb them → 0 dead space across the band). Broad 0-warning band (~11×10/12×9 to 17×12); canonical min 12×10; fallback → `hall_gr` for sub-minimum lots. Diagnostic method throughout: bisected flags/adjacencies at an oversized 25×18 envelope to separate structural conflicts from sizing. 49/49 regression (was 48, +1 new brief) + 46/46 sweep pass. See [[wide-2br-front-back-hall-ld]].

**Deleted near-duplicate `1s_2br_wd_l_wrap_bath_hall_gr` (2026-07-21):** structurally 90% identical to `1s_2br_wd_side_split_bath_hall_gr` — same 6-room program and adjacency graph, differing only in one extra `master↔great` wall adjacency + a dropped `zone_split` (the "L-wrap" lets the great room step around the master's front corner). At its canonical 14×10 the wrap is real and distinctive (great 21.6 vs 15.6 m², master 13.8 vs 18.9), but a size sweep showed the distinction is **patchy, not robust**: `l_wrap`'s own feasibility is non-monotonic, and at every size where it can't solve (e.g. 11×9, 14×11, 15×10) it silently falls back to `hall_gr` and renders byte-identical. So it's one design plus a variant that only diverges when its geometry happens to solve — a weaker two-slot justification than the always-distinct gr/ld depth-gated pairs. Nothing fell back TO it (it was a fallback source only, → `hall_gr`), so the delete was clean: removed the topology + its one 14×10 test brief/baseline, and reworded two comparative prose mentions in `1s_2br_wd_quadrant_split_baths_ds_ld`'s notes (the `master↔great` geometry-only-wall idiom and the null-`zone_split` convention) to be self-contained. The `l_wrap` naming-convention token stays (it's still a valid strategy name); the unrelated 3BR-squarish `l_wrap_baths_ds_hall_gr` is untouched. 48/48 regression (was 49, −1 deleted brief) + 46/46 sweep pass.

**New wide single-bath LDK topology `1s_2br_wd_side_split_bath_hall_ld` (2026-07-21):** LDK conversion of `1s_2br_wd_side_split_bath_hall_gr`, built as a depth-gated **sibling** (gr kept — it's the fallback target for 2 other wide topologies AND reaches shallower lots). Split `great` → living (front) + dining (mid) + kitchen (rear); hall's open mouth retargets from `great` to `dining` (mid-row), same pattern as the squarish/wide clustered-bath conversions. This one converts *much* more cleanly than the wide `cl_ld` (which is narrow-band): single-bath with no ensuite/clustered-block/`match_bedroom_widths`/`match_bath_widths`, so the private side has far fewer competing width constraints and master's full-width front band absorbs slack → a broad 0-warning band (buildable width 7–12, depth ≥6 → ~11×10 to 16×12). Depth floor is buildable 6 m (the LDK-stack constraint from `cl_ld`/`ds_gr`): 12×10 published min, sub-depth-6 lots route to `hall_gr` via `fallback_topology` (general infeasibility-triggered, not area-gated — binding constraint is depth not area). Upper-width limit ~buildable 12 is a soft aspect cap, past the 2BR band. Enabled `claim_dead_strips: true` (master's floating front-band width leaves pockets up to ~2.8 m² at larger sizes; living absorbs them → 0 dead space across the band). Per an explicit user call, briefs are split across the pair: LD canonical at **12×10** (its true min), plus a NEW **11×9** brief for the existing `hall_gr` (which previously had only its 14×10 canonical). Diagnostic note: flagged before building that the user's initially-requested 11×9 is infeasible on LD (depth 5 < the depth-6 floor) and confirmed gr handles it. 49/49 regression (was 47, +2 new briefs) + 43/43 sweep pass. See [[wide-2br-hall-gr-ld-pair]].

**Dead-strip cleanup opt-in flag; enabled on wide cl_ld (2026-07-20, same-day follow-up):** The wide `cl_ld` at its 12×10 minimum left ~0.86 m² of unclaimed interior floor in two pockets (a genuine grid-scan-confirmed gap, not a render artifact), because its ragged mid-column private-room widths (standard 2.2 / hall 2.2–2.8 / common 2.5) don't share an edge at tight sizes; at generous widths (14×10+) the rooms tile evenly on their own and there's no gap. The existing `claim_dead_strips` post-process (built for the multi-storey pipeline, always-on there) does exactly this cleanup but was **deliberately not wired into the single-storey path** to keep the 60+ single-storey baselines frozen. Rather than wire it globally (catalog-wide baseline churn), added a per-topology opt-in flag `claim_dead_strips: bool = False` — threaded through all 8 `Topology`/`_Topology` construction sites (same pattern as `kitchen_rear_pin`/`zone_ratio_*`) and gated the new single-storey call site in `run.py` on it. Enabled only on wide `cl_ld`: 12×10 now claims both pockets (living absorbs the 0.78 m² one → L-shaped living; hall takes the 0.07 m² sliver) → 0 dead space, still 0 warnings; 13×11 dropped from 0.235 to 0.005 m² (float noise). Confirmed a real visual improvement (living now wraps the narrower bedroom cleanly). Purely realized-geometry cleanup — never touches solver feasibility. Default-off means zero effect on every other topology's baseline. The `cl_gr` sibling (~2.4 m² dead at 12×10) was left as-is — out of scope, only cl_ld's output was flagged. 47/47 regression + 43/43 sweep fixtures pass; refreshed the one cl_ld test baseline.

**Wide 2BR clustered-baths: restored cl_gr as cl_ld's depth-gated sibling (2026-07-20, same-day follow-up):** Testing `cl_ld` at progressively smaller lots (12×8, 11×9) surfaced that its 11×9 result was actually a silent *fallback* to the unrelated single-bath `wd_side_split_bath_hall_gr`, not a real `cl_ld` solve — and that `cl_ld`'s LDK stack genuinely can't reach shallow-depth lots at all. Isolated why: the living/dining/kitchen 3-room column needs ≥5.5 m buildable depth alone (tested in isolation, unlimited width available) — confirmed depth-specific, not area-specific (widening a shallow lot to 15×9 still doesn't unlock it). Restored `1s_2br_wd_side_split_baths_cl_gr` from git history (recoverable since nothing from today's deletion had been committed yet) as the deliberate compact/shallow-depth sibling, not a reversion — repointed `cl_ld.fallback_topology` to it (replacing the dangling-reference fix from the previous entry, which had pointed at the structurally-unrelated `hall_gr`). Discovered the restored `cl_gr` was ALSO infeasible at the user's requested 11×9 minimum under its own real compact-shell profile (a flawed bare-`solve()` probe without `run.py`'s profile-application layer had wrongly suggested otherwise) — bisected the true cause via the same one-flag-at-a-time method used elsewhere this session: neither kitchen's floor nor hall's caps alone were sufficient, but kitchen `min_least_dim_m` 1.8→1.6 (same value already used on `bath_ld`) combined with loosening hall's `min_greatest_dim_m` from a rigid fixed 2.8 to a 2.2-2.8 range unlocked 11×9 with 0 warnings; bath caps turned out unnecessary. Re-verified all previously-good sizes (12×10 through 15×11) still solve cleanly. Built the canonical 11×9 test brief + baseline, and a 3-fixture sweep set per an explicit user spec: 11×9 min (`cl_gr`), 12×10 med (`cl_ld`), 13×11 max (`cl_ld`) — deliberately split across both topologies' own sweep folders since they're a matched pair, not duplicates. 47/47 regression + 43/43 sweep fixtures pass.

**Fixed a month-old dangling `fallback_topology` reference on the wide 2BR cl topology (2026-07-20, same-day follow-up):** while checking `1s_2br_wd_side_split_baths_cl_ld`'s feasibility at 12×8 (an out-of-band `extra_wide` ratio, correctly infeasible on the primary topology), the fallback path itself crashed — `fallback_topology` pointed at `1s_2br_wd_side_split_bath_gr.json`, which was deleted 2026-06-25 and explicitly superseded by `1s_2br_wd_side_split_bath_hall_gr.json` per that commit's own message, but the fallback field was never updated. It had been silently dormant for nearly a month (this session's own earlier note calling it "carried over unchanged" didn't catch it, since nothing had exercised the fallback path until this specific out-of-ratio brief). Repointed to the real successor; re-verified the fallback chain now resolves and attempts its own solve (still correctly infeasible at 12×8 — genuinely too shallow at that ratio, not a crash). Grepped for any other topology with the same dangling reference — none found, this was the only one. 46/46 regression + 40/40 sweep fixtures unaffected.

**Wide 2BR clustered-baths topology: gr → ld swap, wide cl_gr deleted (2026-07-20):** `1s_2br_wd_side_split_baths_cl_gr` (clustered rear baths + mid-band hallway, the wide-shell structural twin of squarish `cl_hall_gr`) converted to LDK style and its `gr` predecessor deleted. Investigated this one specifically *because* the squarish `cl_hall_gr`→`cl_hall_ld` conversion had already established the pattern (hall is the sole gateway for master/standard/common; only hall's own open-mouth adjacency needs retargeting, from `great` to `dining`) — confirmed the same retarget works here too. But unlike the squarish sibling (worked at every size tested), this one is genuinely **narrow-band**: 0-warning solves from ~11.9×10 (true floor) through roughly 15×11.5, then infeasible for good at every larger size tested up to a wildly oversized 25×18 — the "oversized envelope still fails" signature of a structural conflict, not a sizing issue. Isolated the cause by stripping rooms/flags one at a time (same method used for the failed `ds_gr` LDK attempt): removing just the `hall↔dining` adjacency makes the topology solve at ANY size, so the narrow band comes from hall's own width being effectively locked to the middle sub-column's width (tied to `standard`'s bedroom width via `match_bedroom_widths`), which doesn't scale the way it would need to as the envelope grows. Ruled out the compact-shell profile as the cause (tested with it disabled entirely and forced to always apply — neither changed the upper bound). Published minimum: 12×10 (round number just above the true ~11.9×10 floor). `fallback_topology` (→ the simpler single-bath `wd_side_split_bath_gr`) carried over unchanged, but is NOT currently size-gated to route large-lot briefs away from the narrow band — flagged as a gap for a future session, not fixed. Deleted the old topology + 2 dependent `briefs/test/` fixtures/baselines (no `test_mins/` or sweep fixtures existed for it). 46/46 regression (was 47, −2 deleted +1 new brief) + 40/40 sweep fixtures unaffected.

**Squarish 2BR distributed-baths topology: ds_gr deleted, no conversion needed (2026-07-20):** `1s_2br_sq_side_split_baths_ds_gr` removed outright — unlike the other three gr→ld conversions this session (`cl_gr`, `bath_gr`, `cl_hall_gr`), its LD sibling `1s_2br_sq_side_split_baths_ds_ld` already existed as a separate topology, so this was a straight deletion rather than a build-then-swap. No `fallback_topology` dependency either direction. Removed the now-redundant few-shot entry in `ai/prompt.py` (a separate `ds_ld` entry already covered the program) and the `ds_gr` line in `lot_size_sweep.py`'s topology list (`ds_ld` was already present alongside it). Deleted the topology file + 3 `briefs/test/test_mins/` fixtures/baselines (no `briefs/test/` main fixtures existed for it, and no `briefs/test_sweep/` fixtures). 47/47 regression (was 50, −3 deleted) + 40/40 sweep fixtures unaffected.

**Squarish 2BR hall-variant topology: gr → ld swap, cl_hall_gr deleted (2026-07-20):** `1s_2br_sq_side_split_baths_cl_hall_gr` (clustered baths + mid-band hallway between master and standard) converted to LDK style, mirroring the `cl_gr`→`cl_ld` and `bath_gr`→`bath_ld` conversions but with a different structural twist: bedrooms/baths in this topology never connect to the public side directly — everything routes through the hall, and only the hall's own open-mouth adjacency needed retargeting. Diagnostic method (per [[ask-before-coding]]): tested both `hall→living` and `hall→dining` as throwaway drafts before committing — `hall→living` is infeasible even at 11×11 (the hall sits in the MIDDLE band between master and standard, so its wall has to align with whichever public room occupies that same middle row; living is front-most, so that connection is geometrically wrong), `hall→dining` solves cleanly. Unlike the other two conversions, this one is a modest **loss** at the low end: true floor moved from gr's 9.5×9.5 to ~9.9×9.9. Tried closing the gap by loosening the compact-shell profile's auto_apply floors (kitchen 1.8→1.6, hallway 0.95→0.9) — floor didn't move, confirming the ~0.4 m cost is structural (dining's width has to satisfy both the hall's mouth and its own living/kitchen stacking), not a tunable threshold; reverted the profile to gr's original values. Published minimum: 10×10 (round number, comfortably above the true 9.9×9.9 floor, matching the `bath_ld` precedent). At 10×10/11×11/12×12 the warning profile is otherwise identical to gr (1 warn `tiered_preferred_dropped` at 10×10, 0 warn at 11×11+). `fallback_topology` (→ `cl_ld`) carried over unchanged — confirmed no OTHER topology's `fallback_topology` pointed at `cl_hall_gr`, so nothing needed repointing there. Deleted the old topology + 7 dependent `briefs/test/`+`test_mins/` fixtures/baselines; `lot_size_sweep.py`'s topology list updated; added a 3-fixture sweep set (10×10/11×11/12×12). 50/50 regression (was 56, −7 deleted +1 new brief) + 32/32 sweep fixtures pass.

**Configurable zone ratio + 45/55 public-heavy split on bath_ld (2026-07-20):** User asked whether `1s_2br_sq_side_split_bath_ld` could run a 45% private (bedrooms) / 55% public (LDK + bath) split — the inverse of the solver's catalog-wide default (55/45 favoring private, with a hard floor of `private >= public` that outright forbids anything below 50% private). Generalized the previously-hardcoded constants in `solver.py`'s zone-ratio block into two new `Topology` fields, `zone_ratio_private_floor_pct` and `zone_ratio_private_target_pct` (both default 50.0/55.0, verified byte-for-byte identical behavior for every other topology via full regression before touching bath_ld's own values — threaded through all 8 `Topology`-construction sites, the same "thread through every copy site" trap as `ldk_horizontal`). Set bath_ld to floor=40.0/target=45.0, plus a `zone_balance_rooms` override folding `common` (normally `zone: "service"`, neutral/excluded) into the public side per the user's explicit request. Verified achieved ratio lands 44–46.5% private / 53.5–56% public across 9.7×9.7–13×13 (exactly 45/55 at 10×10 and 12×12). Side effects: true floor tightened slightly to ~9.6×9.6 (10×10 stays the published minimum); 11×11's warning count dropped back to 1 (the extra `window_area_habitable` warning introduced by the same-day master reposition resolved itself under the new ratio). 56/56 regression + 29/29 sweep fixtures pass; 10×10 baseline refreshed (counts unchanged, room proportions shifted).

**Squarish 2BR single-bath topology: gr → ld swap, bath_gr deleted (2026-07-20):** `1s_2br_sq_side_split_bath_gr` (the smallest squarish 2BR topology, 1 bath, no ensuite) converted to LDK style — public side splits into living (front) / dining (mid) / kitchen (rear) instead of a combined great room, mirroring the same-day `cl_gr`→`cl_ld` conversion but on a structurally different program (a single bath sitting directly in the rear band next to kitchen, not a full-depth two-bath middle band). Diagnostic method: built a throwaway draft topology outside the catalog, swept lot sizes to confirm feasibility before committing to a real file (per [[ask-before-coding]]). First pass (kitchen's compact-shell profile carried over unchanged at `min_least_dim_m: 2.0`) made the requested 10×10 minimum infeasible — true floor was 11×11 with that profile active. Bisected the profile's floor value directly: 1.7 m still blocks 10×10, 1.6 m is the highest value that clears it (9.9×9.9 confirmed infeasible at 1.6 m), so the new topology ships with `min_least_dim_m: 1.6`. Unlike `cl_gr`→`cl_ld`, this is **not** a clean-warning win — both `window_area_habitable` (kitchen, small sizes) and `bath_door_into_kitchen` (door-host auto-scorer overriding the group's declared default) persist in the LD version at the same sizes they did in the original gr version; the win is purely the smaller minimum lot (10×10 vs 10.5×10.5). Deleted `bath_gr`'s topology file + all 12 `briefs/test/`+`test_mins/` fixtures and baselines; `lot_size_sweep.py`'s topology list repointed. No live `fallback_topology` dependency existed on this one (unlike `cl_hall_gr`→`cl_gr` last time). 56/56 regression (was 67, −12 deleted +1 new brief). Also built a 3-fixture sweep set (10×10 min / 11×11 med / 12×12 max) under `briefs/test_sweep/`. Follow-up same day: repositioned master to the rear (mirroring the earlier cl_gr→cl_ld reposition — wall-width values stay attached to the bedroom id, only the target public room and position anchors change). Side effect: tightened the solver's true floor further to ~9.65×9.65 and added a second `window_area_habitable` warning at 11×11 that wasn't there before — 10×10 stays the published minimum regardless since re-tuning wasn't requested. 56/56 regression + 29/29 sweep fixtures still pass; 10×10 baseline refreshed (suggestion count changed 7→6).

**Squarish 2BR bath-cluster topology: gr → ld swap, cl_gr deleted (2026-07-20):** `1s_2br_sq_side_split_baths_cl_gr` had its master repositioned to the rear this session (kitchen's `min_least_dim_m: 1.8` auto_apply floor was the confirmed binding constraint making 11×11 infeasible in the old master-at-front orientation — diagnosed via one-at-a-time constraint relaxation, not guesswork). While investigating, confirmed a living/dining/kitchen-stacked (LDK) version of the same private-column program is not just feasible but strictly better — smaller true minimum (10.5×10.5 vs 11×11) and clean 0-warning solves at every tested size. Built as new topology `1s_2br_sq_side_split_baths_cl_ld`, then `cl_gr` was fully deleted (topology file, 9 `briefs/test/` fixtures + baselines, 3 sweep fixtures) now that `cl_ld` supersedes it. Repointed the one live runtime dependency — `1s_2br_sq_side_split_baths_cl_hall_gr`'s `fallback_topology` — from `cl_gr` to `cl_ld` (was dormant, never actually triggered by any existing brief, but would have silently 404'd on a future infeasible-hall-variant brief if left dangling). Also updated `ai/prompt.py`'s few-shot example and `lot_size_sweep.py`'s topology list. `cl_ld` fixtures: 9-file hand-curated sweep set (`_min`/`_med`/`_max` + 3 near-square mirror pairs at 10.5×10.5/11×11/12×12). 67/67 regression, 26/26 sweep fixtures pass.

**Door-swing hinge fix — room_a vs actual swing target (2026-07-20):** `architectural_plan.py::_door_for_adjacency` picked the hinge corner using `room_a`'s own geometry regardless of which room the door swings into — silently wrong whenever the swinger isn't flush-aligned with room_a (routine upstairs: a narrow `hall2` spine inset within wider bedrooms). Fixed to evaluate corner-reality against the actual swinger, requiring the hinge to coincide with the swinger's real wall bound (not just "the swinger has a corner somewhere"). Verified visually (installed `cairosvg` + `PIL` in `.venv` for this — a same-function data check can't catch this class of bug). Not 2s-specific; touched 5 single-storey topologies too (all user-confirmed fine). Full trail in [[multistorey-v2]]. 73/73 regression, 33 baselines refreshed.

**2BR wide catalog additions (2026-07-13/14):** `baths_ds_hall_gr` →
`baths_ds_gr` (hall removed, both bedrooms door direct to great room). New
topology `1s_2br_wd_quadrant_split_baths_ds_ld` — private/public in
diagonal quadrants, `hall` as the circulation hinge between great_room and
kitchen; confirmed the `right_anchored` edge-collision authoring pattern is
repeatable (see [[quadrant-split-topology]]). Verified 14×11 and 14×10,
committed and pushed. Also fixed a door-hinge bug for L-shaped
ensuite-alcove bedrooms (`stack_bias` heuristic) and added the squarish
2BR lot-size sweep (`lot_size_sweep.py`, [[squarish-2br-lot-size-sweep]]).

**Horizontal-LDK solver support + front-back-split topology working (2026-07-14):** Two general solver capabilities, plus a topology that now uses them. (1) `solver.py`'s hardcoded kitchen-rear-wall pin now skips itself when a topology's `zone_split` explicitly declares kitchen as a front/public room (mathematically necessary — the old unconditional pin was incompatible with `zone_split` by construction). (2) New topology-level flag `ldk_horizontal` (default `False`) disables the solver's hardcoded LDK vertical-stacking rules (kitchen+great_room must stack, kitchen+dining must stack without living_room, living-in-front-of-both) for topologies that want great_room/kitchen side-by-side instead of stacked — threaded through every `Topology`-copy-constructing function in both `solver/topology.py` and `run.py` (7 sites total; missing any of them silently resets the flag). `1s_2br_wd_front_back_split_baths_ds_gr` now solves cleanly using both — see [[front-back-split-topology-solver-bug]] for the full 5-fix diagnostic trail. 48/48 regression, zero drift on any pre-existing baseline.

**Streamlit tester + deployment (2026-07-09):** `floorplan_v1/app.py` — free text → Claude extraction (`ai/extract.py`, stub fallback when no API key) → editable requirements form → hard-filtered topology candidate checklist (`ai/match.py`, filters catalog by bedroom_count + shell category, reusing `shell_category`/`_make_default_lot`) → "Run selected" solves each checked topology via the existing `run.py::_run_hand_authored` and renders results (SVG + validator issues/score) in tabs. Root `requirements.txt` added (didn't exist before). `DEPLOY.md` covers pushing to GitHub + Streamlit Community Cloud + secrets (`ANTHROPIC_API_KEY`, `APP_PASSWORD`). Verified locally via `streamlit.testing.v1.AppTest` (parse → edit → match → run, plus the empty-match path) — no framework installed for automated UI testing yet beyond that.

**Door-host selection, Phases 1+2 (2026-06-11):** WHICH wall hosts a room's door (a tier above where-on-the-wall placement).

- `Adjacency` fields (`topology.py`): `door_host_group` (members = alternate hosts, exactly one emits a door), `door_allowed` (no-door-kind member may host), `door_kind` (kind when a wet_core edge hosts; default `bath_door`), `min_solid_wall_m` (plumbing-band guard — door refused unless shared wall ≥ clear + 0.20 + guard; falls back to default host).
- `Brief.door_host` `{room_id: neighbor_id}` override — wins outright; also forces the default back (e.g. `{"common": "great"}`).
- Auto scoring (`architectural_plan.py` Pass 1a, `_score_door_host`): + circulation-overlap (4.0 × approach-zone fraction vs front-door spine / dirty-kitchen aisle / halls) + freed furnishable public wall (1.0/m, ≥1.5 m, great/living/dining only) − sanitary bath→kitchen (2.0) − wet-wall (1.0). Non-default must STRICTLY beat default. Weights are module constants.
- Validator soft flag `bath_door_into_kitchen` (warning, never hard block).
- Wired: `1s_2br_sq_side_split_bath_gr` group `common_access` (great default, kitchen alternate, 1.2 m solid guard). Plain 12x12 ncp brief now auto-picks the kitchen wall; tighter shells keep great (guard refuses <2.1 m shared wall). Test brief: `..._12x12_..._ncp_kdoor` pins the override path.

**fcp carports (commit e8e2b7e):** `carport_side` + `carport_type` Brief fields; fcp wired through `run.py`; 5 fcp test briefs.

**bath_pwd topology + dead zone fix (commit 02ab14f):** `powder_room: bool` Brief field; new squarish topology `1s_2br_sq_side_split_bath_pwd_gr` (4-room rear band, lot width ≤ ~11 m buildable). Removed `master_bedroom: max_area_sqm: 14.0` from wide-hall compact profile — was blocking master from filling west on 14×10 lots.

**Lanai support (2026-07-09):** `lanai: bool` Brief field now places a semi-outdoor lanai in the setback. All 9 topologies now declare `{"type": "lanai", "location": "rear_setback"}` in `setback_elements` (opt-in via brief). `setback_elements.py` places it behind the great_room's x-range in the rear setback, or alongside the great_room's y-range in the non-carport side setback when `location == "side_setback"`. Rendered as a dashed `LANAI` element. Test brief: `1s_2br_12x12_sq_side_split_bath_gr_ncp_lanai`.

**App improvements (2026-07-09):** Removed caching from AI pipeline (`run.py::_run_ai` — every call hits the API). Patio checkbox removed from `app.py`. AI prompt (`ai/prompt.py`) now passes the computed bath program explicitly so Claude follows 1-bath vs 2-bath briefs correctly (no stray ensuite on 1-bath briefs).

## Open / deferred

- **10 of 12 3BR topologies unvalidated** (dropped into
  `topologies/1s/3br/{narrow,squarish,wide}/` 2026-07-18, no test brief,
  never run through the solver): `1s/3br/narrow/*` (4 files),
  `1s/3br/wide/*` (4 files), `1s/3br/squarish/l_wrap_baths_ds_hall_gr` and
  `side_split_baths_cl_hall_gr`. The 2 squarish ones that WERE tested
  turned out infeasible-as-authored and needed fixing (see the
  2026-07-19 handoff) — treat the other 10 as likely needing the same
  anchor-list debugging before trusting them, per the "recurring
  3BR-catalog trap" note in [[solver-topology-overrides]].
- **3 unconverted 2-storey reference specs** at
  `docs/reference/2s_unconverted_specs/` (`front_stair_foyer`,
  `mid_core_ustair`, `rear_stair_understair`) — fully-dimensioned
  reference drawings in the OLD fixed-coordinate schema, not yet
  converted to topology-v0.1 (same conversion the side-spine-stair
  variant went through). See [[multistorey-topology-authoring]] for the
  recipe.
- **Multi-storey v2 known gaps** (see `MULTISTOREY_V2_DESIGN.md` for
  full detail): cross-floor wet-stack alignment is soft-only (the
  bath2→stairwell soft-proximity nudge in `2s_2br_sq_rear_stair_bath_gr`
  is the working pattern); 2s catalog now covers the full
  {2BR,3BR}×{narrow,squarish,wide} matrix (remaining gaps: no
  squarish/wide `_hall` siblings, no 2s carport variants, no 2s 1BR or
  4BR); no 3-storey support; the under-stair storage/pantry is only
  implicit (whichever room claims the dead-strip alcove beside the
  flight).
- **`extra_wide` shell-matching gap (found 2026-07-16, not fixed):** same bug class as the `narrow` fix — `ai/match.py` does exact string equality, but no topology declares `target_shell: "extra_wide"`, so `wide`-labeled topologies never match an `extra_wide` lot through the app. Scoped out of the narrow fix by explicit user instruction; needs its own go-ahead. See [[shell-category-narrow-fix]].
- **Door placement / corner-preference (requested, not started):** `door_placement` override on adjacency: `"low_corner" | "high_corner" | "center"`. Entry point: `architectural_plan.py::_door_for_adjacency` — `low_real`/`high_real` logic exists, needs override field + center path. (Different tier from door-HOST selection, which is done.)
- **Task #13 (deferred at user request):** Remove obsolete single-bath wide topologies, briefs, outputs.
- Wide-shell catalog plan in memory ([[wide-shell-catalog-plan]]) calls for 3BR wide-only topologies as Phase 2 (`1s_3br_wd_side_split_bath_hall_ld`, `1s_3br_wd_side_split_baths_cl_ld`). Not started.
- 1BR catalog is squarish/narrow/wide only — no `dp`/`swd`/`sdp` 1BR shapes yet. Not requested; noting the gap for symmetry with the 2BR catalog's shape coverage.

## Key project conventions

- **Ask before coding.** Discuss approach, get explicit go-ahead, then write code. See [[ask-before-coding]].
- **Every bedroom needs hallway/public access** — never via a bathroom. See [[floorplan-quality]].
- **Don't present mirror-image variants** as distinct designs.
- **Floor area bands** per [[floor-area-per-br]]: 2BR/1bath 45–65, 2BR/2bath 65–80, 3BR/2bath 80–120, 4BR/3bath 100–150 m². No locked 1BR band yet — the 7 topologies built 2026-07-16 land around 24–36 m² each, treat as a working range not a locked convention.
- **Rear-linear topology (bedrooms across rear) is infeasible** with current solver — use side-split column-stack instead. See [[rear-linear-infeasibility]].
- **1BR topologies need `private_area_floor: false`** — the solver's hard "private ≥ public" area rule assumes a multi-bedroom private wing; a single bedroom can never satisfy it against a full LDK. See [[solver-topology-overrides]].
- **Zone ratio (private/public split) is now per-topology configurable, not just on/off.** `zone_ratio_private_floor_pct` / `zone_ratio_private_target_pct` (both default 50.0/55.0, reproducing the old fixed 55/45-favoring-private behavior byte-for-byte for every topology that doesn't set them) generalize what used to be hardcoded constants in `solver.py`'s zone-ratio block. Use for a deliberately public-heavy design (target < 50 — keep floor ≤ target on that side of 50 or the hard floor contradicts the soft target and the block goes infeasible). See [[zone-ratio-configurable]].
- **Dead interior pockets at a topology's tight sizes: opt into `claim_dead_strips: true` before hand-tuning widths.** When ragged room widths leave small unclaimed rectangular interior gaps at a topology's compact end (that tile away at generous sizes), the per-topology flag `claim_dead_strips: bool` (default False) runs the multi-storey pipeline's dead-strip claimer on the single-storey realize — each pocket becomes an L-alcove on an adjacent room. It's a realized-geometry cleanup only, never affects solver feasibility, and default-off keeps every other baseline frozen. Prefer this over `match_widths`/width-pinning, which ADD solver constraints and routinely break feasibility at exactly the tight sizes you're trying to fix (proven on wide `cl_ld`). First user: `1s_2br_wd_side_split_baths_cl_ld`. See [[wide-2br-cl-gr-to-ld]].
- **New 3BR topologies: check for the over-constrained-anchors trap before trusting feasibility.** Declaring `left_anchored`+`right_anchored`+`rear_anchored` together routinely fights a topology's own `front_to_rear_stacks`/adjacency graph and produces infeasibility at EVERY lot size (proven twice, 2026-07-19). Test at an oversized envelope first; if infeasible, bisect anchor lists before suspecting adjacencies. See [[solver-topology-overrides]].
- **Authoring a 2-storey topology:** follow [[multistorey-topology-authoring]] step by step (storey tags, the three stair adjacency kinds, the always-on stair-run override, `zone_balance_rooms` for public-heavy ground floors, hall/hall-less as siblings not a conditional room). Architecture background in `MULTISTOREY_V2_DESIGN.md`.
- **Prefer a fixed door over `door_host_group` when the desired host scores worse than the alternative** — Pass 1a's auto-scorer will silently flip a group's default to whichever host wins on circulation-overlap, so a group can't reliably hold a deliberately-suboptimal-scoring choice. See [[br1-topology-catalog]] (door-host-group finding on `wd_side_split_bath_gr`).
- **Log every topology/brief/shared-render-code change to `TOPOLOGY_CHANGES.md`** (repo root) as it happens — new/modified topology, new/modified test brief, or an edit to `solver/*.py`/`core/render.py`/`core/model.py`/`ai/brief.py`/`run.py`. `artol-topologies/` (the published HTML catalog) is a build artifact regenerated from a snapshot; the tracker is what lets a single regen pass fold in everything since the last build instead of re-deriving a diff from git history. Shared-code entries have catalog-wide reach — flag them as "regen the whole site," not "these N topologies."

## Useful paths

- Topologies: `floorplan_v1/topologies/{1s,2s}/{nbr}/{shape}/`
- Test briefs: `floorplan_v1/briefs/test/`
- Solver: `floorplan_v1/solver/architectural_plan.py` (geometric solve: `floorplan_v1/solver/solver.py`)
- Renderer: `floorplan_v1/core/render.py`
- Rules catalog: `floorplan_v1/data/ph_floorplan_rules.json` (moved from repo root 2026-07-19; loaded by `core/rules.py`)
- Run tests: `cd floorplan_v1 && python3 run.py --test` (PNGs off by default —
  add `--png` for one run or `ARTOL_WRITE_PNG=1` env var to make it the
  standing default; `--no-png` overrides the env var back off. `cairosvg`
  is now installed in `.venv`, added 2026-07-20 for door-render debugging.)
- Run single brief: `python3 run.py --test --brief=<name>`
- Interactive tester: `streamlit run floorplan_v1/app.py` (see `DEPLOY.md` for hosting it online)
- Lot-size sweeps: `lot_size_sweep.py` (squarish 2BR, multi-sibling), `lot_size_sweep_1br.py` (one topology per shape, 1BR); durable findings: `floorplan_v1/LOT_SIZE_SWEEP_FINDINGS.md`
- Multi-storey v2 design + task log: `MULTISTOREY_V2_DESIGN.md` (repo root)
- `docs/archive/` — superseded one-time docs (pre-Mac-reset backup/memory-export, Phase-1 reports); `docs/reference/` — NBC full text, `common-configs/`, unconverted 2s specs
- Topology HTML catalog: `artol-topologies/` (published site, build artifact — don't hand-edit). Regenerate with `source .venv/bin/activate && python3 tools/topology_catalog/build_catalog.py` (checked in 2026-07-20; solves every topology's canonical test brief through the real solver, ~seconds for the current catalog). Change log: `TOPOLOGY_CHANGES.md` (repo root).
