# Claude Memory Export — artol-ai

**Export date:** 2026-07-12
**Purpose:** Portable snapshot of everything Claude has learned in this project (the persistent memory store plus the project's `CLAUDE.md`), captured before a Mac reset so a future Claude session with zero prior context can pick up where this one left off. Read this whole file before doing any work on artol-ai.

---

## 1. Who I am / my role

Angelito Crisologo (angelito.crisologo@aisolutionmaven.com) works at AI Solution Maven, building AI products. He is leading an AI-assisted floor plan generator for the Philippine market (project name: **artol-ai**).

He thinks in product phases and tends to ask for recommendations on how to start or structure work. He responds well to a clearly phased approach and to being asked to explicitly confirm scope decisions upfront, rather than having decisions made for him silently.

## 2. My preferences and working conventions

**Always ask before coding.** Get explicit go-ahead from Angelito before writing or running any implementation code — new files, edits, build/implementation scripts, throwaway spikes, everything. He stated this directly on 2026-05-24 while scoping the generator: he wants to stay in control of when implementation begins and to keep discussing/aligning on design first.
- Research, discussion, planning, and producing documents/reports are fine without asking.
- Pause and get a clear green light before any actual software implementation.
- Default to discussing approach and confirming scope until he says go.

**Floor plan design-correctness rules** (from his review on 2026-05-24 — treat as durable product requirements, not one-off feedback):
1. Every bedroom/habitable room must have real access — reachable from a hallway or a public room (living/dining), never only through a bathroom or another private room. He flagged early wide-shell outputs as "wrong" because bathrooms walled off bedrooms from public space. This is enforced as a hard validator error, code `no_access`.
2. Hallways should be minimal access notches, not full-length corridors — a full-depth 1m hallway strip "looks like part of the LDK." Prefer a small recessed alcove/notch that bedrooms and the common bath open onto, keeping bedrooms large and full-width.
3. Don't present mirror-image variants (e.g. carport-left vs carport-right) as distinct designs — with orientation scoring off, these are reflections that add no real choice. Vary substantive structure instead (e.g. master-bedroom rear vs front).

**General style:** phased plans, explicit scope confirmation, concise communication (he has a standing "be concise and direct" preference at the account level, not project-specific).

## 3. Project-specific facts and decisions (artol-ai)

### 3.1 Product framing
AI-assisted floor plan layout generator for the Philippine market, built by AI Solution Maven. Workspace folder name: `artol-ai`.

- **Why Philippines-specific matters:** layout rules and build preferences must follow PH regulation and market practice, not generic architecture defaults.
- **Target segment (locked 2026-05-24):** single-detached, mid-market homes (NBCP Group A). Not BP 220 economic/socialized housing (smaller minimums) — flagged as a likely future segment.
- **Product shape:** a 2D floor plan generator + a code-validation engine. Build order: validator first, then generator (the validator doubles as the generator's scoring/fitness function).
- **Rule architecture:** rules are split into HARD constraints (statutory, from PD 1096 National Building Code) vs SOFT preferences (PH design practice — preferred dimensions, dirty kitchen, service area, lanai, three-zone public/private/service layout, tropical orientation).
- **Phase 1 deliverables (2026-05-24):** `ph_floorplan_rules.json` (machine-readable rule set) and `PH_FloorPlan_Generator_Phase1_Report.docx`.
- **Open items flagged early, may still need confirming:** NBCP IRR (2004) + LGU zoning layer for fine setbacks/parking ratios (currently placeholders in the JSON); validate preferred dimensions with a local architect; confirm target lot-size band (~120–200 sqm assumed).

### 3.2 Generation approach (locked 2026-05-24)
Hybrid constraint/optimization pipeline, explicitly **not** generative ML:
Topology first (PH adjacency templates) → geometry via slicing-tree subdivision, originally optimized by simulated annealing, later upgraded to **CP-SAT / OR-Tools** (the current solver) → validator as fitness function (lexicographic objective: hard rules → zoning coherence → preferred dimensions) → 2D SVG render.
- LLM is a future input/edit layer only.
- Generative ML (HouseGAN/diffusion) is a deferred realism layer — can't guarantee hard rules and there's no PH training dataset.
- Rationale: only constraint-based methods can *guarantee* PD 1096 hard rules, which is non-negotiable for a compliance product.

**Key regulatory fact:** PD 1096 §708(a) makes the 2 m setback from the property line a hard rule on all sides for single-detached dwellings. A 120 sqm (10×12) lot yields only 48 sqm single-storey footprint — this is why real PH homes on small lots go two-storey.

### 3.3 v1 proof-of-concept scope (2026-05-24)
10×15 m (150 sqm) inside lot, single-storey. Program: 2 bedrooms, 1 T&B, living, dining, kitchen, service/laundry area, carport. Orientation scoring deferred to v2.

**Carport placement rule:** prefer a side yard (engine tries left and right, keeps the better one); front yard is fallback. On the carport side, setback widens from the 2 m hard minimum to 3 m to fit a ~2.5 m-wide car; carport sits at the front corner of that side for street access. Net buildable on the 150 sqm lot with a side carport = 5×11 = 55 sqm (vs 45 sqm front-placed). Space lever: widen the 3 m setback only along the carport's 5 m length (L-shaped envelope) to recover ~10 sqm if rooms get tight — this became the `ccp` claimed-carport type later.

### 3.4 2BR topology / program decisions (2026-05-24)
Three hand-drawn topology templates (bungalow square/deep/wide) treated as starting points, not fixed templates — same adjacency graph, three footprint aspect ratios. Shared topology: bedrooms clustered left (private spine), L-D-K right running front→rear (living front w/ main entry, dining middle, kitchen rear), service area rear, carport at side.

Program: MASTER bedroom (larger, ensuite T&B accessible only from master) + 1 standard bedroom + 1 common T&B (accessed from public space) + living + dining + kitchen. Front door opens into living. Kitchen on rear wall with exit door to rear service area. Master bedroom placement: prefer rear, front as fallback. Sizing priority: public LDK outranks bedrooms, master bedroom outranks the other bedroom (PH context: public/gathering space is prioritized over private space).

### 3.5 Setback-usage policy (locked 2026-05-24)
Setback = legally open space (light/vent/fire). Only uncovered elements may occupy setbacks; covered/roofed/walled structures must sit in the buildable footprint unless a firewall abutment is declared.

- **Firewall abutment:** a toggle, default OFF for v1 (many LGU/HOA ban it). When on: ≤80% of one side or ≤50% of rear, ≤50% of total perimeter, fire-rated, zero openings facing neighbor. These % limits are IRR-level, not base PD 1096 §804 (party walls) — cite correctly if this comes up again.
- **v1 choices:** carport = uncovered open-air parking in a side setback (engine explores left & right, doesn't consume footprint). Service area = open-air (uncovered) in rear setback hosting an open/uncovered dirty kitchen + laundry/wash, adjacent to the indoor kitchen (which has an exit door onto it). No permanent roof; an optional collapsible/retractable fabric sail is allowed since it's temporary/non-structural and doesn't change "uncovered" status — legality depends on it staying genuinely retractable (a fixed permanent roof frame risks being treated as a structure; flagged as an LGU-interpretation question, not resolved).
- Modeled as `covered:false` + optional `retractable_shade` amenity.
- Eaves/roof projection must stay ≥0.75 m (used 1.0 m) from property line. Covered-structure front setback default 3.0 m (configurable); uncovered parking exempt.
- Net effect: full ~55 sqm footprint preserved for habitable rooms on the 150 sqm v1 lot.
- Stack: Python + Shapely (early plan; solver later moved to CP-SAT/OR-Tools per 3.2).

### 3.6 Floor area per bedroom-count bands (locked convention)
PH single-storey single-detached, mid-market. Includes minimum bath count per program:

| Program | Floor area | Baths |
|---|---|---|
| 2BR / 1 bath | 45–65 m² | 1 common T&B, no ensuite |
| 2BR / 2 baths | 65–80 m² | 1 ensuite + 1 common T&B |
| 3BR / 2 baths | 80–120 m² | 1 ensuite + 1 common T&B (shared by 2 standard BRs) |
| 4BR / 3 baths | 100–150 m² | 1 ensuite + 2 common T&Bs (shared by 3 standard BRs) |

`per_room` (premium) topology — one ensuite per bedroom, powder room is a brief-level toggle (not a separate topology):
- 2BR per_room, powder OFF (default): 65–80 m², 2 ensuites
- 2BR per_room, powder ON: 75–95 m², 2 ensuites + 1 powder
- 3BR per_room, powder ON (default): 95–130 m², 3 ensuites + 1 powder
- 3BR per_room, powder OFF: 85–115 m², 3 ensuites
- 4BR per_room, powder ON (default): 120–165 m², 4 ensuites + 1 powder
- 4BR per_room, powder OFF: 110–150 m², 4 ensuites

Powder defaults: 2BR off (intimate home, no guest powder), 3BR+ on (3rd bedroom unlocks dedicated guest WC). Brief field: `adjustments.powder_room.enabled` (bool) + optional `size_m2`; injected into topology's room list at solve time.

**Why these bands:** 2BR/1-bath lower bound (45 m²) = master 9 + std 7 + 1 bath 3 + kitchen 6 + LDK 16 + ~10% walls/hall — below this, rooms hit PD 1096 hard minimums and the LDK becomes one cramped 12 m² room. 65 m² is the PH developer convention (Camella Easy, Lumina Cara, Pag-IBIG starter 2BR) for the 1-bath→2-bath transition. 3BR lower bound (80 m²) adds one std bedroom (+9) and an LDK bump (+4) over 2BR. 4BR lower bound (100 m²) adds two stds and a second common T&B — PH market practice rejects 3 standard bedrooms sharing 1 bath above 3BR.

**Upper bounds / program-swap knees:** 2BR→3BR at ~80 m² floor (~200 m² lot single-storey); 3BR→4BR at ~120 m²; 4BR→larger at ~150 m². PH mainstream developers (Camella, Avida, Lessandra) swap the program rather than scale the smaller variant past its knee. These bands apply to single-storey specifically — two-storey math differs.

**How to apply:** pick bedroom count to match floor area and verify minimum bath count is feasible. 4BR topologies must declare ≥3 baths. Single-storey 2BR caps at ~200 m² lot / ~100 m² shell / ~80 m² floor.

### 3.7 Rear-linear topology is infeasible — do not attempt
A true "rear-linear" topology (bedrooms side-by-side across the rear wall, e.g. `[standard | common | master | kitchen]` with great_room spanning the front) is structurally infeasible in the solver, even on generous lots (tested up to 20×14).

**Root cause (in `solver/solver.py` as of the diagnostic session):**
1. Kitchen hard-pinned to rear (`kitchen.y_end = env.y_end`, ~line 444).
2. LDK rule forces kitchen + great_room to stack front-to-rear (~lines 595–602).
3. Any bedroom↔great_room horizontal-wall adjacency forces all such bedrooms to share `y_start = great.y_end = kitchen.y_start` — all rear-band rooms end up at the same depth.
4. Bedroom rules (`min_least_dim 2.0` + `aspect_cap 1.8` + `area ≥ 8 m²`) at that shared depth require width ≥4 m for area but ≤3.6 m for aspect → empty solution space.

Confirmed diagnostically: removing the `standard↔great_room` adjacency makes it feasible; lowering `min_shared_wall_m` does not help even at 0.1 m. It's a topology-shape problem, not a parameter-tuning problem.

**Rule going forward:** the solver is designed around column-stack topologies (rooms stack front-to-rear in vertical columns, columns sit side-by-side horizontally). Use side-split / column-stack for any new topology — private wing as left column, public wing as right column, kitchen at rear of right column. Never propose bedrooms tiled across the rear wall; if research suggests a rear-linear pattern, model it as a wider side-split instead. A broken topology `1s_2br_w_rear_linear_gr.json` was deleted for this reason on 2026-06-05; the approved alternative is the wide-shell side-split catalog (3.8 below).

### 3.8 Wide-shell topology catalog
Wide shell = aspect ratio 1.30–1.85.

**Phase 1 — 2BR, built as of 2026-06-11 (commit feb677a).** Six topologies under `floorplan_v1/topologies/1s/2br/wide/` at that time (note: current project state per `CLAUDE.md` as of 2026-07-09 lists a different, updated set of 3 wide topologies — treat the list below as historical/superseded and verify current topology files before relying on names):
1. `1s_2br_w_side_split_gr` — single bath, private column left, great+kitchen right
2. `1s_2br_w_side_split_hall_gr` — single bath, hall threading private column
3. `1s_2br_w_side_split_mid_bath_gr` — bath between bedrooms
4. `1s_2br_w_side_split_rear_baths_gr` — baths at rear band
5. `1s_2br_w_rear_bedrooms_gr` — bedrooms at rear, great room front (matches dominant PH 60 sqm bungalow pattern; column-stack, not true rear-linear)
6. `1s_2br_w_l_gr_hall` — L-shape great room with mid-band hall

**Phase 2 — 3BR wide-only, NOT STARTED as of the last check:**
- `1s_3br_w_side_split_hall_ld` — 3 bedrooms front-to-rear in left column, hall threading them, common bath at rear-middle, separate LDK right
- `1s_3br_w_side_split_clustered_baths_ld` — 3 bedrooms left, 2 baths (ensuite + common) clustered between bedrooms and kitchen

**Deferred cleanup — Task #13:** remove obsolete single-bath wide topologies/briefs/outputs. Angelito asked not to remove yet.

**Constraint shape reused from squarish (works):** `left_anchored` private column, `right_anchored` kitchen, `rear_anchored` rear band, `front_to_rear_stacks` per column. Wide-bungalow PH practice keeps the same logical layout as squarish but stretches columns horizontally — master can stretch to ~16–18 m², LDK gets a wider open feel.

**How to apply:** before building any new topology, verify it doesn't accidentally become true rear-linear (3.7) — side-split/column-stack is the only pattern the solver can represent.

### 3.9 Carport type system (locked 2026-06-11, commit e8e2b7e)
Brief fields: `carport_side` (`"left"|"right"|"front"|None`) + `carport_type` (`"fcp"|"ccp"|None`).

- **`ncp`** — no carport. Both fields None. Runner calls `_strip_carport_from_topology` (removes carport setback element + building_void). Rectangular envelope, 2 m setbacks all sides.
- **`fcp`** — full carport. The entire named side is 3 m setback throughout. Runner calls `_strip_carport_void_only` (keeps carport element, removes L-notch void). Rectangular envelope (narrower shell than ccp). Brief sets explicit `setbacks.{side}: 3.0`. Front fcp bumps `lot.front` to 3.0 if needed. Wide fcp lots need ≥11 m depth (topology needs ≥7 m buildable depth after 2+2 setbacks).
- **`ccp`** — claimed carport (default when `carport_side` is set and type isn't fcp). 3 m setback for first 6 m depth, 2 m beyond — L-notch via `building_void` in the topology. Brief sets all `setbacks` to 2.0 (the void geometry creates the carport space).

**Why:** fcp = simpler build, narrower shell. ccp = L-shaped shell, more floor area, more complex framing.

### 3.10 Door-host selection (which wall hosts a room's door) — shipped 2026-06-11
A tier above where-on-the-wall placement (3.11). Principle: a door sterilizes approach-side floor and breaks furnishable wall; cost ≈ 0 when its approach zone overlaps existing circulation (e.g. a kitchen aisle already serving a dirty-kitchen door). Originated from Angelito's observation on `1s_2br_sq_side_split_bath_gr`'s T&B door.

**Mechanism (generic, not kitchen-specific):**
- `Adjacency` fields in `topology.py`: `door_host_group` (members = alternate hosts, exactly one emits a door), `door_allowed` (a no-door-kind member may host), `door_kind` (kind when a wet_core edge hosts; default `bath_door`), `min_solid_wall_m` (plumbing-band guard — door refused unless shared wall ≥ clear + 0.20 + guard; falls back to default host on refusal).
- `Brief.door_host: {room_id: neighbor_id}` override — wins outright, including forcing the default back (e.g. `{"common": "great"}`). Wired into `run.py`'s `_BRIEF_FIELDS`.
- `architecturalize(layout, topo, door_host=...)` Pass 1a resolves groups before the main adjacency loop; new `wall_only` kind added to `_NO_DOOR_KINDS`.
- Validator soft flag `bath_door_into_kitchen` (warning) — deliberately a soft penalty, never a hard block (Angelito's explicit call).

**Auto-scoring (Phase 2, same session), `_score_door_host`:**
`+ DOOR_HOST_W_CIRCULATION(4.0) × approach-zone overlap fraction with circulation corridors` (front-door spine + dirty-kitchen-door aisle extruded full room depth + hallway rooms, computed prospectively)
`+ DOOR_HOST_W_FREED_WALL(1.0) × freed furnishable wall (≥1.5 m, public rooms only: great/living/dining)`
`− DOOR_HOST_P_SANITARY(2.0)` for bath→kitchen
`− DOOR_HOST_P_WET_WALL(1.0)` for a wet_core edge
Non-default candidate must **strictly** beat default (ties keep the authored default). Brief override still wins outright.

**Wired example:** `1s_2br_sq_side_split_bath_gr.json` group `common_access` (common↔great default, common↔kitchen alternate, 1.2 m solid guard). Test brief: `1s_2br_12x12_sq_side_split_bath_gr_ncp_kdoor`. Plain 12×12 ncp brief auto-picks the kitchen wall; tighter shells (10.5×11 etc.) keep the great-room wall because the shared wall <2.1 m and the plumbing guard refuses. Test suite: 29 pass at time of shipping.

### 3.11 Door placement / corner-preference — requested, NOT started
Requested 2026-06-11. Interior doors should default to swinging against a perpendicular wall (corner-preference); topologies should be able to override placement per adjacency.

Proposed override: `door_placement: "low_corner" | "high_corner" | "center"` on an `Adjacency` entry.

**Why:** `low_real`/`high_real` corner logic already exists in `_door_for_adjacency`, but there's no topology-level override — placement is fully automatic today. Some topologies need explicit control (center a door when both corners are constrained, or force a specific corner for space-planning reasons).

**Entry point:** `architectural_plan.py::_door_for_adjacency` (~line 375 as of last check). Planned approach: (1) read `adj.door_placement` if set; (2) if `"center"`, compute midpoint of shared edge; (3) if `"low_corner"`/`"high_corner"`, force that side (skip the real/fake wall heuristic). Need to add `door_placement: Optional[str]` to the `Adjacency` dataclass in `topology.py` first.

**Discuss approach with Angelito before coding** (standing convention, section 2).

### 3.12 Lanai feature — flag exists but is a dead no-op
`lanai: bool` flows end-to-end through `ai/extract.py` → `app.py` → `ai/brief.py` → `run.py`'s allowed-fields tuple, and `lanai` is a full `room_catalog` entry in `ph_floorplan_rules.json` (preferred dims 2.0–4.0 m, 6–16 sqm, adjacency prefer_near living/dining/rear_yard) — but **no topology ever emits a lanai setback element** and `core/setback_elements.py` has no lanai placement logic. Checking "Lanai" in the Streamlit tester currently does nothing. `ph_floorplan_rules.json` flags it explicitly: `"note": "Not in v1 program; retained for future."`

A requirement doc was drafted at repo root: `LANAI_REQUIREMENTS.md` (draft, not yet approved as of last check per the "ask before coding" convention).

**Verified pilot geometry** (checked against an actual solved SVG output, not assumed): ran topology `1s_2br_sq_side_split_bath_gr` (test brief `1s_2br_12x12_sq_side_split_bath_gr_ncp_kdoor`). Kitchen touches the rear boundary (dirty_kitchen sits behind kitchen in the rear setback). Great Room touches the front boundary (entry point, adjoins the porch), but its right (side) wall sits flush on the buildable envelope boundary. So for this side-split shell, a **side** lanai off Great Room (opposite the carport) is geometrically ready; a **rear** lanai off a public room is not available on this topology because Kitchen owns that stretch of rear wall. Rear placement needs a topology where a living/dining/great room actually reaches the rear wall — candidate `1s_2br_wd_l_wrap_bath_hall_gr` (L-wrap great room) was identified but not yet checked.

**Design decisions locked with Angelito (2026-07-09):**
- Placement: brief-selectable side (`lanai_side`: rear/left/right), mirroring `carport_side`.
- Roof treatment: uncovered setback element only for v1 (no footprint/firewall impact).
- Sizing: width matches the adjoining room, not a fixed footprint.
- Rollout: pilot on 1–2 topologies first (not full catalog), matching how `bath_pwd` and `fcp` carports were introduced.

*(Per the newer CLAUDE.md context below, a "Lanai support" feature — a simpler rear/side-setback version driven by a plain `lanai: bool` — was actually shipped on 2026-07-09. It's unclear from memory alone whether that shipped feature supersedes this `lanai_side`-selectable design or is a first increment of it. Reconcile by reading current code before continuing this feature.)*

---

## 4. References to external systems

No dedicated ticket tracker, chat channel, or dashboard has been recorded in memory for this project — work has been tracked directly in the repo (git history, `CLAUDE.md`, test briefs) rather than an external system. If Angelito sets one up (Linear, Slack, Notion, etc.), record the pointer here.

---

## 5. Latest project state (verbatim from CLAUDE.md as of 2026-07-09/2026-07-12)

This is the most current, authoritative snapshot of the project — it supersedes older memory entries above where they conflict (memory entries are historical/point-in-time; CLAUDE.md is the maintained live doc). Reproduced in full below.

> # artol-ai — Active project context
>
> PH floor plan generator + validator. Single-detached mid-market houses. CP-SAT solver.
>
> ## Session handoff (2026-07-09) — read this first
>
> Switching from Cowork to Claude Code CLI mid-task. The interactive tester
> (`floorplan_v1/app.py`, see "Recently completed" below) is built and
> locally verified, but NOT yet deployed. Pick up from here:
>
> - **Git:** this repo has no remote configured (`git remote -v` is empty).
>   Working tree has uncommitted changes:
>   - New from this session: `floorplan_v1/app.py`, `floorplan_v1/ai/extract.py`,
>     `floorplan_v1/ai/match.py`, root `requirements.txt`, `DEPLOY.md`,
>     `.streamlit/secrets.toml.example`, a `.gitignore` edit (added
>     `.streamlit/secrets.toml`), and this file.
>   - Pre-existing and unrelated to the tester — review/commit separately:
>     `1s_2br_16x12_sq_side_split_bath_pwd_gr_ncp.svg` (modified),
>     `floorplan_v1/briefs/test/1s_2br_16x12_sq_side_split_bath_pwd_gr_ncp.json`
>     (modified), `1s_2br_12x12_sq_side_split_baths_cl_gr_ncp.svg` (untracked).
>     Small diffs (1-2 lines) — worth a quick look before folding into any commit.
> - **Not yet done:** push to GitHub, create the Streamlit Community Cloud app,
>   set secrets. Full steps in `DEPLOY.md`.
> - **Not yet verified:** `ai/extract.py`'s `ClaudeExtractor` (real Claude-based
>   NL→requirements extraction) — only `StubExtractor` (regex/keyword fallback,
>   no API key needed) was exercised, via `streamlit.testing.v1.AppTest`
>   simulating the full click-through (parse → edit fields → find topologies →
>   run selected, plus the empty-match path). Worth a real run with
>   `ANTHROPIC_API_KEY` set before this goes in front of the business partner.
> - **Local run:** `pip install -r requirements.txt` (repo root, `--break-system-packages`
>   if needed) then `streamlit run floorplan_v1/app.py` from repo root.
> - Remember [[ask-before-coding]] — this project's standing convention.
>
> ## Current focus (as of 2026-06-25)
>
> **Naming convention locked:** `{storey}_{nbr}_{WxD}_{shape}_{strategy}_{bath_token}[_hall][_gr|_ld]_{carport}[_swap]`
> Shapes: `sq`, `wd`, `dp`, `swd`, `sdp` | Strategies: `side_split`, `front_rear`, `l_wrap`, `z_wrap`, `split_wing` | Bath: `bath`, `bath_pwd`, `baths_cl`, `baths_ds`, `baths_mix` | Carport: `ncp`, `fcp`, `ccp`
>
> **Carport type semantics (locked):**
> - `ncp` — no carport; building_void + carport setback element stripped; rectangular envelope.
> - `fcp` — full carport; entire side setback is 3 m throughout; building_void stripped; rectangular envelope (narrower shell than ccp). Set `carport_side` + `carport_type: fcp` in brief; explicit `setbacks.right/left: 3.0`.
> - `ccp` — claimed carport; 3 m for first 6 m of depth, 2 m beyond; L-notch via building_void. `setbacks` all 2.0, void creates cutout.
>
> **Wide 2BR topologies** (`floorplan_v1/topologies/1s/2br/wide/`):
>
> - `1s_2br_wd_side_split_bath_hall_gr` — single bath, hall in private column
> - `1s_2br_wd_side_split_baths_cl_gr` — clustered baths at rear band
> - `1s_2br_wd_l_wrap_bath_hall_gr` — L-wrap great room with mid-band hall
>
> **Square 2BR topologies** (`floorplan_v1/topologies/1s/2br/squarish/`):
>
> - `1s_2br_sq_side_split_bath_gr` — single bath, private column left
> - `1s_2br_sq_side_split_bath_pwd_gr` — single bath + powder room, 4-room rear band; buildable width ≤ ~11 m
> - `1s_2br_sq_side_split_baths_cl_gr` — clustered baths (ensuite + common), private column
> - `1s_2br_sq_side_split_baths_cl_hall_gr` — clustered baths with hall
> - `1s_2br_sq_side_split_baths_ds_gr` — distributed baths, great room
> - `1s_2br_sq_side_split_baths_ds_ld` — distributed baths, living/dining
>
> **Test suite status:** 29 pass, 0 fail, 0 error.
>
> ## Recently completed
>
> **Streamlit tester + deployment (2026-07-09):** `floorplan_v1/app.py` — free text → Claude extraction (`ai/extract.py`, stub fallback when no API key) → editable requirements form → hard-filtered topology candidate checklist (`ai/match.py`, filters catalog by bedroom_count + shell category, reusing `shell_category`/`_make_default_lot`) → "Run selected" solves each checked topology via the existing `run.py::_run_hand_authored` and renders results (SVG + validator issues/score) in tabs. Root `requirements.txt` added (didn't exist before). `DEPLOY.md` covers pushing to GitHub + Streamlit Community Cloud + secrets (`ANTHROPIC_API_KEY`, `APP_PASSWORD`). Verified locally via `streamlit.testing.v1.AppTest` (parse → edit → match → run, plus the empty-match path) — no framework installed for automated UI testing yet beyond that.
>
> **Door-host selection, Phases 1+2 (2026-06-11):** WHICH wall hosts a room's door (a tier above where-on-the-wall placement).
>
> - `Adjacency` fields (`topology.py`): `door_host_group` (members = alternate hosts, exactly one emits a door), `door_allowed` (no-door-kind member may host), `door_kind` (kind when a wet_core edge hosts; default `bath_door`), `min_solid_wall_m` (plumbing-band guard — door refused unless shared wall ≥ clear + 0.20 + guard; falls back to default host).
> - `Brief.door_host` `{room_id: neighbor_id}` override — wins outright; also forces the default back (e.g. `{"common": "great"}`).
> - Auto scoring (`architectural_plan.py` Pass 1a, `_score_door_host`): + circulation-overlap (4.0 × approach-zone fraction vs front-door spine / dirty-kitchen aisle / halls) + freed furnishable public wall (1.0/m, ≥1.5 m, great/living/dining only) − sanitary bath→kitchen (2.0) − wet-wall (1.0). Non-default must STRICTLY beat default. Weights are module constants.
> - Validator soft flag `bath_door_into_kitchen` (warning, never hard block).
> - Wired: `1s_2br_sq_side_split_bath_gr` group `common_access` (great default, kitchen alternate, 1.2 m solid guard). Plain 12x12 ncp brief now auto-picks the kitchen wall; tighter shells keep great (guard refuses <2.1 m shared wall). Test brief: `..._12x12_..._ncp_kdoor` pins the override path.
>
> **fcp carports (commit e8e2b7e):** `carport_side` + `carport_type` Brief fields; fcp wired through `run.py`; 5 fcp test briefs.
>
> **bath_pwd topology + dead zone fix (commit 02ab14f):** `powder_room: bool` Brief field; new squarish topology `1s_2br_sq_side_split_bath_pwd_gr` (4-room rear band, lot width ≤ ~11 m buildable). Removed `master_bedroom: max_area_sqm: 14.0` from wide-hall compact profile — was blocking master from filling west on 14×10 lots.
>
> **Lanai support (2026-07-09):** `lanai: bool` Brief field now places a semi-outdoor lanai in the setback. All 9 topologies now declare `{"type": "lanai", "location": "rear_setback"}` in `setback_elements` (opt-in via brief). `setback_elements.py` places it behind the great_room's x-range in the rear setback, or alongside the great_room's y-range in the non-carport side setback when `location == "side_setback"`. Rendered as a dashed `LANAI` element. Test brief: `1s_2br_12x12_sq_side_split_bath_gr_ncp_lanai`.
>
> **App improvements (2026-07-09):** Removed caching from AI pipeline (`run.py::_run_ai` — every call hits the API). Patio checkbox removed from `app.py`. AI prompt (`ai/prompt.py`) now passes the computed bath program explicitly so Claude follows 1-bath vs 2-bath briefs correctly (no stray ensuite on 1-bath briefs).
>
> ## Open / deferred
>
> - **Door placement / corner-preference (requested, not started):** `door_placement` override on adjacency: `"low_corner" | "high_corner" | "center"`. Entry point: `architectural_plan.py::_door_for_adjacency` — `low_real`/`high_real` logic exists, needs override field + center path. (Different tier from door-HOST selection, which is done.)
> - **Task #13 (deferred at user request):** Remove obsolete single-bath wide topologies, briefs, outputs.
> - Wide-shell catalog plan in memory calls for 3BR wide-only topologies as Phase 2 (`1s_3br_wd_side_split_bath_hall_ld`, `1s_3br_wd_side_split_baths_cl_ld`). Not started.
>
> ## Key project conventions
>
> - **Ask before coding.** Discuss approach, get explicit go-ahead, then write code. (See section 2 of this export.)
> - **Every bedroom needs hallway/public access** — never via a bathroom. (See section 2.)
> - **Don't present mirror-image variants** as distinct designs.
> - **Floor area bands** (see section 3.6): 2BR/1bath 45–65, 2BR/2bath 65–80, 3BR/2bath 80–120, 4BR/3bath 100–150 m².
> - **Rear-linear topology (bedrooms across rear) is infeasible** with current solver — use side-split column-stack instead. (See section 3.7.)
>
> ## Useful paths
>
> - Topologies: `floorplan_v1/topologies/{1s,2s}/{nbr}/{shape}/`
> - Test briefs: `floorplan_v1/briefs/test/`
> - Solver: `floorplan_v1/solver/architectural_plan.py`
> - Renderer: `floorplan_v1/core/render.py`
> - Run tests: `cd floorplan_v1 && python3 run.py --test`
> - Run single brief: `python3 run.py --test --brief=<name>`
> - Interactive tester: `streamlit run floorplan_v1/app.py` (see `DEPLOY.md` for hosting it online)

---

## 6. Note on staleness

Several memory entries above are 30–49 days old as of this export (2026-07-12) and are explicitly marked as point-in-time observations, not live state — file:line citations and specific code claims may have drifted. Where section 5 (CLAUDE.md, most recently touched 2026-07-09) conflicts with earlier memory sections, trust section 5. Before acting on any specific code claim in this document (a function name, a line number, a topology file name), verify against the actual current repo state.
