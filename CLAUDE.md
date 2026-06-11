# artol-ai — Active project context

PH floor plan generator + validator. Single-detached mid-market houses. CP-SAT solver.

## Current focus (as of 2026-06-11)

**Naming convention locked:** `{storey}_{nbr}_{WxD}_{shape}_{strategy}_{bath_token}[_hall][_gr|_ld]_{carport}[_swap]`
Shapes: `sq`, `wd`, `dp`, `swd`, `sdp` | Strategies: `side_split`, `front_rear`, `l_wrap`, `z_wrap`, `split_wing` | Bath: `bath`, `baths_cl`, `baths_ds`, `baths_mix` | Carport: `ncp`, `fcp`, `ccp`

**Wide 2BR topologies** (`floorplan_v1/topologies/1s/2br/wide/`):

- `1s_2br_wd_side_split_bath_gr` — single bath, private column left
- `1s_2br_wd_side_split_bath_hall_gr` — single bath, hall in private column
- `1s_2br_wd_side_split_baths_cl_gr` — clustered baths at rear band
- `1s_2br_wd_front_rear_bath_gr` — bedrooms at rear, great room front
- `1s_2br_wd_l_wrap_bath_hall_gr` — L-wrap great room with mid-band hall

**Square 2BR topologies** (`floorplan_v1/topologies/1s/2br/squarish/`):

- `1s_2br_sq_side_split_bath_gr` — single bath, private column left
- `1s_2br_sq_side_split_baths_cl_gr` — clustered baths (ensuite + common), private column
- `1s_2br_sq_side_split_baths_cl_hall_gr` — clustered baths with hall
- `1s_2br_sq_side_split_baths_ds_gr` — distributed baths, great room
- `1s_2br_sq_side_split_baths_ds_ld` — distributed baths, living/dining

All 25 test briefs pass. 1 known pre-existing error from an abandoned `rear_bedrooms_gr` brief.

## Recently completed (commit feb677a)

- New adjacency kind `bedroom_to_public_wall` added to solver's `_NO_DOOR_KINDS` — geometry-only no-door wall (used in `single_bath_hall_gr` to align master east = great west).
- Render fix in `_compute_walls` Pass B — wall thickness now classified by envelope membership (0.20 m exterior on env boundary, 0.10 m interior otherwise). Fixes T&B interior walls rendering as exterior thickness.
- `single_bath_hall_gr` lot_adjustment pins: kitchen depth 2.0, hallway depth 1.0, standard 3×3 exactly, master 4.6×3.0 exactly. Eliminates the parallel-wall artifact at T&B's southeast corner by aligning all rear-band rooms at y=6.0.

## Open / deferred

- **Task #13 (deferred at user request):** Remove obsolete single-bath wide topologies, briefs, outputs. User asked not to remove yet.
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
