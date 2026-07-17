# artol-ai — Active project context

PH floor plan generator + validator. Single-detached mid-market houses. CP-SAT solver.

## Session handoff (2026-07-16) — read this first

GitHub remote in sync, both commits pushed
(`github.com/angelito-crisologo/artol-fp-test`, `8c275de`, `780df73`).
Streamlit Cloud deployment at `https://artol-fp.streamlit.app/` picks up
pushes automatically (~1 min rebuild). Full regression: **61/61 pass**.

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
   (fixed a `left_anchored` bug, now solves 8.5×12 up), plus two new ones —
   `nw_front_back_split_bath_gr` (8×10, from `narrow-fp-01.png`) and
   `nw_front_rear_bath_gr` (8×10, from `narrow-fp-02.png`, full-width rear
   bedroom).
3. **Wide** (2 new, alongside the pre-existing `wd_side_split_bath_hall_gr`
   which needs ≥13.3×9.5): `wd_split_wing_bath_gr` (10×8, from
   `wide-fp-01.png`, wet end-column) and `wd_side_split_bath_gr` (10×8,
   user-requested variant — bath+kitchen rear band instead of end column,
   bath doors into the kitchen per a later revision).
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
- `nw_side_corridor_bath_hall` — narrow, 8.5×12, shotgun corridor sequence
- `nw_front_back_split_bath_gr` — narrow, 8×10, bedroom door via kitchen side
- `nw_front_rear_bath_gr` — narrow, 8×10, full-width rear bedroom
- `wd_side_split_bath_hall_gr` — wide, 14×10 (pre-existing, needs ≥13.3×9.5)
- `wd_split_wing_bath_gr` — wide, 10×8, wet end-column
- `wd_side_split_bath_gr` — wide, 10×8, wet rear band, least override-hungry

All 1BR topologies use `private_area_floor: false` (a single bedroom can
never outweigh the LDK under the hard "private ≥ public" rule) and the new
`counter_divider` dining-counter render feature — see
[[solver-topology-overrides]] and [[counter-divider-dining-spec]].

**Test suite status:** 61 pass, 0 fail, 0 error (includes 17 minimum-boundary
briefs under `briefs/test/test_mins/`, see [[squarish-2br-lot-size-sweep]],
plus 8 new 1BR test briefs added 2026-07-16).

## Recently completed

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
- **Prefer a fixed door over `door_host_group` when the desired host scores worse than the alternative** — Pass 1a's auto-scorer will silently flip a group's default to whichever host wins on circulation-overlap, so a group can't reliably hold a deliberately-suboptimal-scoring choice. See [[br1-topology-catalog]] (door-host-group finding on `wd_side_split_bath_gr`).

## Useful paths

- Topologies: `floorplan_v1/topologies/{1s,2s}/{nbr}/{shape}/`
- Test briefs: `floorplan_v1/briefs/test/`
- Solver: `floorplan_v1/solver/architectural_plan.py`
- Renderer: `floorplan_v1/core/render.py`
- Run tests: `cd floorplan_v1 && python3 run.py --test`
- Run single brief: `python3 run.py --test --brief=<name>`
- Interactive tester: `streamlit run floorplan_v1/app.py` (see `DEPLOY.md` for hosting it online)
- Lot-size sweeps: `lot_size_sweep.py` (squarish 2BR, multi-sibling), `lot_size_sweep_1br.py` (one topology per shape, 1BR)
