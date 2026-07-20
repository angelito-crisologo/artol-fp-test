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

- `1s_2br_wd_side_split_bath_hall_gr` — single bath, hall in private column
- `1s_2br_wd_side_split_baths_cl_gr` — clustered baths at rear band
- `1s_2br_wd_l_wrap_bath_hall_gr` — L-wrap great room with mid-band hall
- `1s_2br_wd_side_split_baths_ds_gr` — distributed baths, no hall, both
  bedrooms direct-to-great (renamed 2026-07-13 from `..._ds_hall_gr` after
  removing the hall)
- `1s_2br_wd_front_back_split_baths_ds_gr` — front-back split (not vertical
  column split like everything else); great_room + kitchen side-by-side at
  front, master|ensuite|common|standard in one row at rear. See
  [[front-back-split-topology-solver-bug]] for how it was made to work —
  uses the new `ldk_horizontal` topology flag.
- `1s_2br_wd_quadrant_split_baths_ds_ld` — private/public in diagonal
  quadrants; great_room+standard up front, master+ensuite | hall/common
  (stacked) | kitchen at rear. hall is the circulation hinge.

**Square 2BR topologies** (`floorplan_v1/topologies/1s/2br/squarish/`):

- `1s_2br_sq_side_split_bath_gr` — single bath, private column left
- `1s_2br_sq_side_split_bath_pwd_gr` — single bath + powder room, 4-room rear band; buildable width ≤ ~11 m
- `1s_2br_sq_side_split_baths_cl_gr` — clustered baths (ensuite + common), private column
- `1s_2br_sq_side_split_baths_cl_hall_gr` — clustered baths with hall
- `1s_2br_sq_side_split_baths_ds_gr` — distributed baths, great room
- `1s_2br_sq_side_split_baths_ds_ld` — distributed baths, living/dining

**1BR topologies** (`floorplan_v1/topologies/1s/1br/{squarish,narrow,wide}/`,
added 2026-07-16 — full detail in [[br1-topology-catalog]]):

- `sq_side_split_bath_gr` — squarish, 9×9 lot, straight-cut 2×2 grid
- `nw_front_back_split_bath_gr` — narrow, 8×10, bedroom door via kitchen side
- `nw_front_rear_bath_gr` — narrow, 8×10, full-width rear bedroom
- `wd_split_wing_bath_gr` — wide, 10×8, wet end-column
- `wd_side_split_bath_gr` — wide, 10×8, wet rear band, least override-hungry

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

**Test suite status:** 71 pass, 0 fail, 0 error (includes 17 minimum-boundary
briefs under `briefs/test/test_mins/`, see [[squarish-2br-lot-size-sweep]],
6 1BR test briefs (down from 8 — `wd_side_split_bath_hall_gr` and
`nw_side_corridor_bath_hall` both removed 2026-07-20, no-hall-in-1BR rule),
and — added 2026-07-19/20 — 4 3BR-squarish-fix briefs +
8 multi-storey briefs).

## Recently completed

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
