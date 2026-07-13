# artol-ai — Active project context

PH floor plan generator + validator. Single-detached mid-market houses. CP-SAT solver.

## Session handoff (2026-07-13) — read this first

Mac was reset since the last session; environment was rebuilt (`brew install
python@3.12`, fresh `.venv`, `pip install -r requirements.txt`) and verified
— 46/47+ tests passing, GitHub remote intact and pushed
(`github.com/angelito-crisologo/artol-fp-test`), Streamlit Cloud deployment
at `https://artol-fp.streamlit.app/` confirmed still live. See
[[deployment-status]] memory for details.

This session's work, in order:

1. **Door-hinge bug fix** (`solver/architectural_plan.py`) — L-shaped
   bedrooms (ensuite-alcove claim) combined with the `stack_bias` heuristic
   could hinge a door against a non-existent wall, or leave two stacked
   bedrooms' doors far apart instead of mirroring at their real shared
   corner. Fixed + regression-tested (46/46 pass, zero baseline drift).
   Also added a lot-size feasibility sweep (`lot_size_sweep.py`,
   `LOT_SIZE_SWEEP_FINDINGS.md`) and 17 minimum-boundary test briefs under
   `briefs/test/test_mins/`. **Committed and pushed** (`71fb163`).
2. **Wide topology `baths_ds_hall_gr` → `baths_ds_gr`** — removed the hall
   per request; both bedrooms now door directly into the great room,
   mirroring the squarish `baths_ds_gr` sibling. New test brief
   `1s_2br_14x11_wd_side_split_baths_ds_gr_ncp` passes cleanly. **Not yet
   committed** — do so along with everything below in one commit.
3. **New topology `1s_2br_sq_front_back_split_baths_ds_lk.json`** (added by
   Angelito, filed under `wide/` despite squarish `target_shell`) — a novel
   "front-back split" design (one wall divides an all-public front band from
   an all-private rear band, vs. every other topology's vertical column
   split). **STILL BROKEN — read [[front-back-split-topology-solver-bug]]
   before touching this file.** Two authoring contradictions were found and
   fixed (a room forced to touch the rear wall while another room was
   stacked behind it, twice over — once via `rear_anchored`, once via
   kitchen's hardcoded rear-pin in `solver.py`). Per Angelito's request, the
   private band was reworked into one row — `master | ensuite | common |
   standard` (baths clustered in the middle) — which eliminates both of
   those. **Still infeasible at every lot size tried (12x12 up to 34x34).**
   Isolated to `left_anchored=["living"]` alone being infeasible even on a
   huge lot with nothing else constraining anything — a genuine `solver.py`
   bug, not a topology-authoring issue, not yet root-caused. This is the
   next thing to pick up.
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
- `1s_2br_sq_front_back_split_baths_ds_lk` — **BROKEN, do not rely on this
  one yet.** Front-back split (not vertical column split like everything
  else); `target_shell` is actually `squarish` despite living in this
  folder. See [[front-back-split-topology-solver-bug]].

**Square 2BR topologies** (`floorplan_v1/topologies/1s/2br/squarish/`):

- `1s_2br_sq_side_split_bath_gr` — single bath, private column left
- `1s_2br_sq_side_split_bath_pwd_gr` — single bath + powder room, 4-room rear band; buildable width ≤ ~11 m
- `1s_2br_sq_side_split_baths_cl_gr` — clustered baths (ensuite + common), private column
- `1s_2br_sq_side_split_baths_cl_hall_gr` — clustered baths with hall
- `1s_2br_sq_side_split_baths_ds_gr` — distributed baths, great room
- `1s_2br_sq_side_split_baths_ds_ld` — distributed baths, living/dining

**Test suite status:** 47 pass, 0 fail, 0 error (includes 17 minimum-boundary
briefs under `briefs/test/test_mins/`, see [[squarish-2br-lot-size-sweep]]).

## Recently completed

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

- **`solver.py` bug blocking `1s_2br_sq_front_back_split_baths_ds_lk`
  (found 2026-07-13, not yet root-caused):** `left_anchored=["living"]`
  alone is infeasible even on a 34x34 m lot with every other constraint
  stripped away. Not a topology-authoring issue — needs a read-through of
  `solver.py`'s full constraint-building function. See
  [[front-back-split-topology-solver-bug]].
- **Door placement / corner-preference (requested, not started):** `door_placement` override on adjacency: `"low_corner" | "high_corner" | "center"`. Entry point: `architectural_plan.py::_door_for_adjacency` — `low_real`/`high_real` logic exists, needs override field + center path. (Different tier from door-HOST selection, which is done.)
- **Task #13 (deferred at user request):** Remove obsolete single-bath wide topologies, briefs, outputs.
- Wide-shell catalog plan in memory ([[wide-shell-catalog-plan]]) calls for 3BR wide-only topologies as Phase 2 (`1s_3br_wd_side_split_bath_hall_ld`, `1s_3br_wd_side_split_baths_cl_ld`). Not started.

## Key project conventions

- **Ask before coding.** Discuss approach, get explicit go-ahead, then write code. See [[ask-before-coding]].
- **Every bedroom needs hallway/public access** — never via a bathroom. See [[floorplan-quality]].
- **Don't present mirror-image variants** as distinct designs.
- **Floor area bands** per [[floor-area-per-br]]: 2BR/1bath 45–65, 2BR/2bath 65–80, 3BR/2bath 80–120, 4BR/3bath 100–150 m².
- **Rear-linear topology (bedrooms across rear) is infeasible** with current solver — use side-split column-stack instead. See [[rear-linear-infeasibility]].

## Useful paths

- Topologies: `floorplan_v1/topologies/{1s,2s}/{nbr}/{shape}/`
- Test briefs: `floorplan_v1/briefs/test/`
- Solver: `floorplan_v1/solver/architectural_plan.py`
- Renderer: `floorplan_v1/core/render.py`
- Run tests: `cd floorplan_v1 && python3 run.py --test`
- Run single brief: `python3 run.py --test --brief=<name>`
- Interactive tester: `streamlit run floorplan_v1/app.py` (see `DEPLOY.md` for hosting it online)
