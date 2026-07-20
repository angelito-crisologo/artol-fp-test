# Backup & Restore Instructions — artol-ai / Claude memory

**Written:** 2026-07-12, ahead of a Mac reset (new user account, Claude to be reinstalled afterward).

## 1. What to copy to external storage before the reset

**Required — the project's working folder:**

```
/Users/tolitz/Documents/Claude/Projects/artol-ai
```

This is the actual project folder connected to Claude and contains all the code, topologies, test briefs, and this export. Copy the whole folder to an external drive, cloud storage, or wherever you're staging the reset.

**Belt-and-suspenders extra — Claude's local app data:**

```
~/Library/Application Support/Claude/
```

Claude's memory store and local session data live under here. It's not guaranteed to survive a clean reset + new macOS user account (a new account gets a fresh `~/Library`), and Claude's memory system is designed to be rebuilt from `Claude-Memory-Export.md` rather than restored from raw internal files — so treat this as a nice-to-have, not the primary recovery path. Copy it if you have space; don't block the reset on it.

## 2. Restore steps, after the reset

1. **Reinstall Claude** (desktop app) and log back in with your account.
2. **Copy the `artol-ai` folder back** from external storage to wherever you want it to live on the new account (e.g. `~/Documents/Claude/Projects/artol-ai`, matching the old path, or a new location — your choice).
3. **Reconnect the folder to a project in Cowork:** create or open the artol-ai project in Claude, then connect/select that folder so Claude has file access to it again.
4. **Recreate the project's custom instructions (`CLAUDE.md`)** if they don't carry over automatically with the folder. They should already be sitting in the folder as `CLAUDE.md` since it's a real file inside `artol-ai` (not separate metadata) — but if for any reason it's missing, the full verbatim text is quoted below so you can recreate it.
5. **Tell the new Claude session to read `Claude-Memory-Export.md` first**, e.g.: *"Before we do anything else, read Claude-Memory-Export.md in this folder — it's the full context from before a Mac reset."* Claude's own memory system (the persistent `MEMORY.md` + memory files) will NOT carry over automatically to a fresh account/install — it lived under `~/Library/Application Support/Claude/`, which a new user account does not inherit. `Claude-Memory-Export.md` is the portable substitute: it contains everything that was in that memory system as of 2026-07-12, consolidated into one file. Once Claude has read it, you can ask it to re-save the key facts back into its memory system so future sessions pick them up automatically again.

## 3. Key files in this folder and what they're for

| File | Purpose |
|---|---|
| `CLAUDE.md` | The project's live, maintained context doc — current focus, recently completed work, open items, conventions, useful paths. This is the single most important file to keep current; Claude reads it automatically at the start of every session in this project. |
| `Claude-Memory-Export.md` | One-time snapshot (2026-07-12) of everything Claude's persistent memory system + `CLAUDE.md` knew about this project and about you, written so a memoryless Claude session can reconstruct full context by reading it. Use this to bootstrap a fresh install; not meant to be maintained ongoing (update `CLAUDE.md` instead going forward). |
| `Backup-Restore-Instructions.md` | This file. |
| `floorplan_v1/` | The actual product code — solver, topologies, briefs, renderer, Streamlit tester (`app.py`), AI extraction (`ai/extract.py`, `ai/match.py`, `ai/prompt.py`). |
| `requirements.txt` (repo root) | Python dependencies for the Streamlit tester and solver. |
| `DEPLOY.md` | Steps for pushing to GitHub and deploying the Streamlit tester to Streamlit Community Cloud, including secrets setup. |
| `.streamlit/secrets.toml.example` | Template for the secrets file (`ANTHROPIC_API_KEY`, `APP_PASSWORD`) needed to run the AI-extraction path and password-gate the deployed app. The real `secrets.toml` is gitignored — you'll need to recreate it locally/on Streamlit Cloud after the reset. |
| `LANAI_REQUIREMENTS.md` (if present at repo root) | Draft requirement doc for a more selectable-side lanai feature; not yet approved as of the last check — see `Claude-Memory-Export.md` section 3.12 for context. |

## 4. `CLAUDE.md` — full verbatim text (as of 2026-07-12)

Quoted in full below so it can be recreated if it doesn't carry over with the folder copy.

---

```markdown
# artol-ai — Active project context

PH floor plan generator + validator. Single-detached mid-market houses. CP-SAT solver.

## Session handoff (2026-07-09) — read this first

Switching from Cowork to Claude Code CLI mid-task. The interactive tester
(`floorplan_v1/app.py`, see "Recently completed" below) is built and
locally verified, but NOT yet deployed. Pick up from here:

- **Git:** this repo has no remote configured (`git remote -v` is empty).
  Working tree has uncommitted changes:
  - New from this session: `floorplan_v1/app.py`, `floorplan_v1/ai/extract.py`,
    `floorplan_v1/ai/match.py`, root `requirements.txt`, `DEPLOY.md`,
    `.streamlit/secrets.toml.example`, a `.gitignore` edit (added
    `.streamlit/secrets.toml`), and this file.
  - Pre-existing and unrelated to the tester — review/commit separately:
    `1s_2br_16x12_sq_side_split_bath_pwd_gr_ncp.svg` (modified),
    `floorplan_v1/briefs/test/1s_2br_16x12_sq_side_split_bath_pwd_gr_ncp.json`
    (modified), `1s_2br_12x12_sq_side_split_baths_cl_gr_ncp.svg` (untracked).
    Small diffs (1-2 lines) — worth a quick look before folding into any commit.
- **Not yet done:** push to GitHub, create the Streamlit Community Cloud app,
  set secrets. Full steps in `DEPLOY.md`.
- **Not yet verified:** `ai/extract.py`'s `ClaudeExtractor` (real Claude-based
  NL→requirements extraction) — only `StubExtractor` (regex/keyword fallback,
  no API key needed) was exercised, via `streamlit.testing.v1.AppTest`
  simulating the full click-through (parse → edit fields → find topologies →
  run selected, plus the empty-match path). Worth a real run with
  `ANTHROPIC_API_KEY` set before this goes in front of the business partner.
- **Local run:** `pip install -r requirements.txt` (repo root, `--break-system-packages`
  if needed) then `streamlit run floorplan_v1/app.py` from repo root.
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

**Square 2BR topologies** (`floorplan_v1/topologies/1s/2br/squarish/`):

- `1s_2br_sq_side_split_bath_gr` — single bath, private column left
- `1s_2br_sq_side_split_bath_pwd_gr` — single bath + powder room, 4-room rear band; buildable width ≤ ~11 m
- `1s_2br_sq_side_split_baths_cl_gr` — clustered baths (ensuite + common), private column
- `1s_2br_sq_side_split_baths_cl_hall_gr` — clustered baths with hall
- `1s_2br_sq_side_split_baths_ds_gr` — distributed baths, great room
- `1s_2br_sq_side_split_baths_ds_ld` — distributed baths, living/dining

**Test suite status:** 29 pass, 0 fail, 0 error.

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
```

---

**Note:** the `[[double-bracket]]` references above (e.g. `[[ask-before-coding]]`, `[[floorplan-quality]]`) point to entries in Claude's separate persistent memory system, not files in this folder. That memory system's content is fully reproduced in `Claude-Memory-Export.md` — see that file for the material each reference points to.
