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

_Nothing pending — regenerated 2026-08-14._

**2026-08-14 — SHARED CODE (`solver/fixtures.py`): Layer D no longer demands a
dining table in counter-served rooms**
A `counter_divider` adjacency puts a dining counter on the kitchen seam, built
by `architectural_plan.py` and drawn by `render.py` (`plan.counters`). Layer D
did not know, so it reported "no dining table fits" for rooms whose dining
function was already present — a false defect, and the catalog's deliberate
answer for compact plans at that. `_has_dining_counter` now checks
`Counter.room`/`Counter.facing`; those rooms skip the table and give the
seating group the WHOLE room rather than half, which is the point of the
parti. "No dining table" reports 8 → 3, fixtures 941 → 944.

**2026-08-14 — SHARED CODE (`solver/fixtures.py`): the counter no longer
blocks its own appliances**
A sink, range or fridge is set INTO the counter run, so the counter is not an
obstruction to them. `check_door_clearance` passed it in the blocker list
anyway, so every position along the counter wall read as occupied and the
appliance was DELETED rather than slid along the run. New `_may_overlap`
exempts the by-design pairs. Recovered 19 fixtures (922 → 941) and cut unfit
140 → 121; all four placement invariants still 0. `--furnish` only, 0 baselines
moved.

**2026-08-14 — SHARED CODE (`solver/fixtures.py`), NO regen needed: Layer D**
Placers for living / dining / great rooms and the carport. Adds the `center`
anchor (dining tables, on a zone's middle — the first placement in the module
not measured from a wall) and `free` (coffee table, positioned relative to the
sofa). A great_room splits across its longer axis, seating one half and dining
the other. The car comes off `layout.elements` rather than the room loop,
because carports are setback elements, not rooms.
289 new pieces (49 3-seat sofas, 39 coffee tables, 39 TV consoles, 47 dining
tables, 5 cars); 633 → 922 fixtures with all four invariants still at 0.
Nothing in the catalog path calls it — `--furnish` only — so 0 baselines moved
and no regen is owed. `corner` (sofa_l) is still deferred.

## Applied history

### Regenerated 2026-08-14 — 44 topologies / 51 implementations
(41 verified, 10 not yet tested; was 41/48.) Also removed one ORPHAN left
behind by the build: `build_catalog.py` adds and overwrites but never deletes,
so the deleted wide `center_spine` survived in `data/topologies/` until swept
by hand. Everything below was folded into that build.

**2026-08-14 — the four WIDE 3BR topologies resolved: 3 shipped, 1 deleted**
Completes the `1s/3br/wide/` set, unvalidated since 2026-07-18. All four
declared left+right+rear together, but the signature turned out to be a reason
to TEST, not a diagnosis — the causes differed and one file had no problem at
all.
- **`1s_3br_wd_side_split_baths_cl_hall_gr` — shipped, NO fix needed.** Solves
  as authored at every size 13x10 to 18x13; it had simply never been run.
  Canonical 16x12, 83.6 m², 0 errors, 0 warnings, master largest at 13.0.
- **`1s_3br_wd_split_wings_baths_ds_hall_gr` — shipped.** Was infeasible
  everywhere, but **not** the anchor trap: the anchors are fine and
  `front_to_rear_stacks` was the blocker (bisected at 25x18), now null.
  Canonical 17x12, 91.0 m², 0e 0w. Known weakness in its notes: the hall runs
  oversized for a circulation node (8.4 at 16x12 → 19.2 at 18x13) because the
  post-solve passes funnel slack into it, so ~17x12 is the practical ceiling.
- **`1s_3br_wd_half_spine_baths_ds_hall_lk` — shipped.** The classic trap:
  left + right + `zone_split`, all three must go. Canonical 17x12, 90.7 m²,
  0e 0w. Honest caveat recorded: the label says HALF spine but the realized
  corridor runs nearly the full width, so it reads as a full spine.
- **`1s_3br_wd_center_spine_baths_ds_hall_gr` — DELETED.** Only ONE lot size
  (18x13) is feasible after any fix, and it is degenerate: **ensuite 1.2 m²**,
  kitchen 33.6, great 43.7, master 9.5. A 1.2 m² ensuite is not a bathroom.
  Same outcome as its squarish namesake, deleted 2026-08-13.
  - **Fallback repointed:** `split_wings` pointed at it and now points at
    `half_spine_lk`. Verified no other inbound reference. Note
    `artol-topologies/data/topologies/` still carries a stale copy — that is a
    build artifact and the regen will drop it.
- **This closes the "environment issue" story.** The squarish `half_spine`
  notes cited this wide sibling's infeasibility as proof of "a reproducible,
  environment-specific solver issue affecting the spine/hall parti family". The
  wide sibling is indeed infeasible — from the same in-file mistake. No
  environment issue ever existed; it was the same authoring error in both.
- **58 pass / 0 fail** (was 55), 51 sweep pass. The unvalidated-3BR backlog
  CLAUDE.md tracks drops from 10 to 6.

**2026-08-13 — `1s_3br_sq_center_spine_baths_ds_gr` DELETED**
Investigated, then removed at user request. Regen note: it never had a brief,
a baseline or an inbound `fallback_topology`, so nothing else moves — but the
squarish 3BR group loses a file it never counted as an entry.

The unrelated wide `1s_3br_wd_center_spine_baths_ds_hall_gr` is a DIFFERENT
topology and is untouched; `1s_3br_wd_split_wings_baths_ds_hall_gr` falls back
to it and that reference was verified to still resolve.

Why it was dropped:
Completes the 2026-08-12 drop. Same trap (`left_anchored` + `right_anchored` +
`zone_split` infeasible together), but here the anchors ENCODE the parti —
`[master, ensuite, kitchen]` / `[br2, br3, common]` are exactly the three
columns flanking the full-depth great_room. Keeping them and dropping
everything else was tried in all four combinations; all infeasible. The only
solving configuration discards the parti.
- **The file contradicts its own label**, worth knowing for any redraw:
  `zone_split` is horizontal/private-rear (a front BAND, incompatible with a
  full-depth spine); `kitchen` is declared public by `zone_split` yet also
  sits in `rear_anchored`, so it is required front and rear at once; and
  `front_to_rear_stacks` puts great IN FRONT OF the bedrooms, again a band
  reading rather than a spine.
- **The feasible version is permanently degenerate.** `great` takes **47-48%
  of the floor at every size** (38.5 / 42.0 / 52.5 / 53.2 at 13.5 / 14 / 15 /
  16 square) while br2 and br3 stay at or beside the 6.0 m² PD 1096 floor.
  Added area never reaches the bedrooms — it goes to great_room and master.
- **And it is a near-duplicate** of `1s_3br_sq_front_back_split_baths_ds_hall_gr`
  shipped the same day: same front-block-plus-rear-band shape, differing only
  by having no corridor, worse in every proportion (great 48% vs 39%, both
  bedrooms at the floor vs 6.0/7.5), and reaching no smaller lot. Same
  near-duplicate reasoning that retired `1s_2br_wd_l_wrap_bath_hall_gr`.
- No brief, no baseline, topology unchanged. 55 pass / 0 fail.

**All four topologies from the 2026-08-12 drop are now resolved:** 4BR
split_wings and side_corridor shipped, half_spine's resolution shipped under
an honest name (`front_back_split_baths_ds_hall_gr`) with the parent retained
for redraw, center_spine recommended for deletion.

**2026-08-13 — `1s_3br_sq_side_corridor_baths_ds_hall_gr` VERIFIED and shipped
under its own name**
Unlike its two siblings this one keeps its parti once made feasible, so it
ships as authored rather than being renamed.
- Same trap: `left_anchored` + `right_anchored` + `front_to_rear_stacks`
  declared together, infeasible at every lot size. No single knob and no pair
  is enough; all three must go. Finer edits all fail too — dropping only the
  `[great, hall]` stack entry, that plus either anchor list, and removing the
  stacks while keeping both anchor lists. `rear_anchored` plus
  `match_bedroom_widths` now do the shaping.
- **The parti survives:** `hall` still serves every private room — master,
  br2, br3, bath1, bath2 all door onto it — and still opens into the
  great_room. Two honest caveats recorded in the notes: br3 lands front-right
  rather than in the bedroom column, so the corridor is single-loaded for only
  two of three bedrooms; and the corridor sits between the bedroom column and
  the public zone rather than against a side wall, so it reads as the side of
  the BEDROOM BLOCK, not of the plan.
- Canonical brief `1s_3br_13.5x13.5_sq_side_corridor_baths_ds_hall_gr_ncp`:
  80.7 m², 0 errors, 1 warning (`window_area_habitable`, present at every size
  tested). Deliberately at the band FLOOR, not mid-band: bedroom hierarchy is
  tight (master ~12.9 vs br2 ~13.1) and degrades as the lot grows (at 14x14,
  br3 14.2 vs master 13.0), so a bigger canonical would show a standard
  bedroom clearly outsizing the master. Also solves 13x13 (72.0, below band),
  14x14 (90.0), 14.5x14.5 (99.7). Baseline written.
  **55 pass / 0 fail** (was 54), 51 sweep pass.
- Its `lot_adjustment_profiles` entry is INERT — verified by forcing it to
  always apply, no difference at any size. Kept because harmless; do not
  assume it is doing work.

Remaining from the 2026-08-12 drop: only `1s_3br_sq_center_spine_baths_ds_gr`
is still unvalidated.

**2026-08-13 — NEW: `1s_3br_sq_front_back_split_baths_ds_hall_gr`, VERIFIED**
Front half is master (left) + great_room (right) side by side, both full
depth; the rear band holds common_e, br2, common_w, br3 and the kitchen, with
`hall_e` running east-west along that band's front edge and opening into the
great_room. br3's bath doors off the bedroom; common_e doors off the corridor.
- **Provenance matters here.** This is not drawn from a precedent — it is what
  `1s_3br_sq_half_spine_baths_ds_hall_gr` actually resolves to once made
  feasible, promoted to its own file under an honest name. Keeping it under
  the half_spine id would have been the "relabelled side_split" that file's
  own notes warn against. The parent stays unshipped for a proper redraw.
- **The unlock was removing `hall_w`**, the bath vestibule. It sat between br3
  and a great_room that also had to reach hall_e and the kitchen, so
  great_room wrapped the west side and crushed it. Removing it recovers the
  kitchen 3.5 → 7.0, br3 6.2 → 9.0, drops master 32.2 → 24.9, and lets
  `common_bath` reach its 3.0 m² legal floor — which was unsatisfiable at
  EVERY lot size with hall_w present, tested up to 20x16.
- Also: `left_anchored` / `right_anchored` nulled (declared together they are
  the over-constrained-anchors trap), `zone_split` nulled (the parent's was
  wrong regardless — it declared private_side "right" while listing only the
  east rooms, though br3 and common_w are private and sit west).
- **The `common_bath` 3.0 m² floor in `lot_adjustment_profiles` is
  load-bearing**, and its threshold is deliberately generous (200 m²) so it
  applies at every size the topology reaches. Caps on master_bedroom /
  bedroom_standard and a hallway least-dimension floor are each individually
  INFEASIBLE here — absent on purpose, not forgotten.
- Canonical brief `1s_3br_14x14_sq_front_back_split_baths_ds_hall_gr_ncp`:
  90.0 m², 0 errors, **0 warnings**. Feasible 13.5x13.5 (80.8, band floor)
  through 15x15 (110.0); INFEASIBLE at 13x13 and below. Baseline written.
  **54 pass / 0 fail** (was 53), 51 sweep pass.
- Known weakness recorded in the notes: br2 sits at the 6.0 m² hard floor
  while master takes ~25, so the bedroom hierarchy is lopsided. Both cap
  routes are infeasible and `set_max_area_sqm` does not bite (post-solve
  inflation), so it is documented rather than fixed.

**2026-08-12 — NEW: `1s_4br_wd_split_wings_baths_multi_hall_gr` (the catalog's
first 4-bedroom topology), VERIFIED**
Twin symmetric bedroom wings flanking a central public core: master +
ensuite_m + common_w + hall_w + br_guest1 west, br2 + ensuite2 + common_e +
hall_e + br_guest2 east, great_room (front) + kitchen (rear) between. Every
bedroom reaches a bath inside its own wing and both shared-bath doors open onto
a hall lobby, never onto the LDK — two corrections against the source
precedent (pep_SHD-2015021).
- **Was INFEASIBLE at every lot size as authored.** `left_anchored` +
  `right_anchored` + `front_to_rear_stacks` declared together over-constrain
  the solver against the topology's own adjacency graph — the recurring trap
  recorded 2026-07-19. Bisected at a 25x25 envelope: dropping any one or any
  two of the three still fails; dropping all three solves. All three are now
  null, `rear_anchored` alone does the shaping.
- **The parti survives the relaxation** — checked at 18x13, which a solve alone
  cannot tell you. master 12.0, guest bedrooms 14.0 / 10.8, br2 9.2, great
  27.2, kitchen 10.6, baths 4.0 each, halls 6.0 each.
- Canonical brief `1s_4br_18x13_wd_split_wings_baths_multi_hall_gr_ncp`
  (112.0 m² floor, inside the 100-150 m² 4BR/3-bath band). Feasible 18x13 /
  17x12 / 16x12; 15x11 solves at 65.3 m² but is far below band. Baseline
  written. **53 pass / 0 fail** (was 52), 51 sweep pass.
- New directory `topologies/1s/4br/wide/` — first 4BR in the catalog, so the
  regen adds a bedroom-count group.

**2026-08-12 — THREE new squarish 3BR topologies added but NOT validated**
`1s_3br_sq_center_spine_baths_ds_gr`, `1s_3br_sq_half_spine_baths_ds_hall_gr`,
`1s_3br_sq_side_corridor_baths_ds_hall_gr`. All three are INFEASIBLE as
authored, all three by the same over-constrained-anchors trap. No test briefs,
no baselines — they must not be counted as catalog entries until validated.
- **Their `notes` carry a WRONG diagnosis**, since corrected on `half_spine`:
  they claim "a reproducible, environment-specific solver issue affecting the
  spine/hall parti family broadly, not a defect this file introduces". It is a
  defect in the files. Anchor bisection gives a minimal fix for each
  (`center_spine`: drop left+right+`zone_split`; `half_spine`: drop
  left+right; `side_corridor`: drop left+right+`front_to_rear_stacks`).
- **Relaxing is not enough for two of them.** `center_spine` loses its
  private/public separation and lands the kitchen between br2 and the ensuite.
  `half_spine` solves at 15x15 but degenerately — great 50.6 and master 32.2
  against a 3.5 m² kitchen and both standard bedrooms pinned at the 6.0 m²
  hard floor; `set_max_area_sqm` does NOT help, because snap_gaps and the
  dead-strip claimer inflate after the solve. These need authoring, not a flag
  change. `side_corridor` relaxes to a solve whose corridor lands mid-plan
  rather than along a side.

**2026-08-12 — Furniture sits against the wall FACE, not the room edge**
A `Room`'s rect is the wall CENTRELINE and adjacent rooms share it exactly, so
furniture placed flush to the rect was drawn INSIDE the wall band. Where two
rooms share a party wall their furniture met at the centreline: in the
lobby-hub plan the two bedrooms' headboards touched at a gap of exactly
0.000 m, reading as two beds shoved together with no wall between them.
- `_clear_cell` / `_RoomFloor` pull a cell in by half the wall thickness per
  side, exterior vs interior decided by `make_outside_probe` — the same shared
  definition the renderer uses, so furniture and drawn wall cannot disagree. A
  side opening into the room's own alcove has no wall and is not inset.
- **Applied to the RESULT, not the search space** (`_clip_to_clear_floor`, run
  after door clearance). Insetting BEFORE placement was tried first and is
  wrong: it shrinks the room the placer reasons about and fixtures fall out of
  rooms that hold them fine — both lobby-hub bedrooms lost their beds, a worse
  drawing than the one being fixed. Clipping after costs nothing: **633 placed
  / 108 unfit, unchanged**, 0 fixtures intruding into a wall band, 0 overlaps.
- The two headboards are now 0.100 m apart, exactly the interior wall drawn
  between them.
- Clearance is measured on the clear floor too, which is the honest floor:
  findings 215 → 286, but the rise is concentrated in the trivial band
  (`<0.10 m` shortfall 34 → 81) while the `>=0.30 m` headline `--furnish`
  prints moved only 115 → 134.
- Door zones deliberately keep TRUE geometry: a door's `position_m` is measured
  from the original rect's origin, so deriving zones from an inset cell slides
  every zone off its own doorway. Caught by a spike in bogus
  "blocked by a doorway" removals.

**2026-08-12 — SHARED CODE, NO regen needed: `run.py --furnish` (opt-in)**
Until now Phase E.2 furniture appeared in NO generated plan at all —
`place_fixtures` had exactly one consumer in the repo, `polish.py`, and
`run.py` / `app.py` / `build_catalog.py` never imported it. `--furnish` writes
`<name>.furnished.svg` **beside** the plain plan and prints the fit report
(placed / did-not-fit / tight, with examples).

- **Sidecar, never in place.** The plain drawing stays what the validator and
  the catalog describe, and no baseline moves. Verified: full suite with
  `--furnish` writes 52 sidecars and touches 0 baselines; `test_output/` is
  already gitignored.
- **Off by default, lazy-imported.** The fixture stack is post-solve cosmetics
  that must never influence a solve or a validation; keeping the import inside
  the `--furnish` path means an ordinary run cannot reach it.
- Multi-storey furnishes each floor from ITS OWN sub-layout (`plan.layout`),
  not the parent — the both-storeys trap in CLAUDE.md. Verified visually on a
  2s 3BR composite.
- Labels are lifted above the furniture by `inject_overlay`, which is what
  keeps them readable. `mask_behind_labels` is deliberately NOT passed: those
  opaque chips exist for polish.py, to paint over text an image model writes
  despite being told not to. Nothing in this path writes rogue text, so the
  chips had nothing to cover and merely hid the furniture behind every label.
- **Layer C landed the same day:** it now draws the library's REAL symbols,
  not neutral rectangles. `core/render.py` gains `fixture_symbol_svg` and
  `fixtures_overlay_svg(..., symbols=True)`; anything the library cannot draw
  falls back to the old rectangle. `fixture_library.py` MOVED `solver/` →
  `core/`, since both layers need it and core/ is the lower one (imports are
  unaffected — both dirs are on sys.path). 1204 symbols across the suite,
  0 fallbacks.
- **The cairosvg stroke trap is handled.** The library sets
  `vector-effect="non-scaling-stroke"`; cairosvg does not implement it, so at
  SCALE=42 a 0.9 px line rasterises ~38 px and every symbol becomes a blob.
  Stroke widths are divided by SCALE **and the attribute removed** — doing one
  without the other is broken in one renderer or the other (a renderer that
  DOES honour it would then draw 0.9/42 px, i.e. nothing).

**2026-08-12 — SHARED CODE, but NO regen needed: fixture library adopted
(new `solver/fixture_library.py`, `solver/fixtures.py`, `core/render.py`,
`ai/render_prompt.py`)**
Layers A + B of taking up the `floorplan_v1/fixtures/` drawing library (55 SVG
symbols in metres, each with a placement/clearance manifest). **No geometry
moved anywhere** — 52 pass / 51 sweep pass, and the fixture rectangles and
`unfit` list are multiset-identical to before across all 61 floors. Nothing in
`run.py` / `app.py` / `build_catalog.py` imports any of it, and
`polish.py --self-check` still passes, so the catalog is unaffected. Logged
because `solver/*.py` and `core/render.py` are shared code.

- **A. `solver/fixture_library.py` (new)** — loads `fixtures/index.json` into
  frozen dataclasses (`FixtureSpec`, `Footprint`, `Clearance`, `Stretch`).
  `fixtures.py`'s hardcoded dimension block now reads from it. The swap was
  exact: every one of the 16 constants already matched the library to the
  centimetre, and the replay diff was byte-identical.
- **A. `Fixture.kind` is now the library id.** `shower`→`shower_stall`,
  `counter`→`kitchen_counter`, `sink`→`kitchen_sink`, `range`→`range_electric`;
  the rest already matched. One identifier instead of two, so `LIB.get(f.kind)`
  always resolves. `_RUN_KINDS` updated with it.
- **A. `core/render.py::fixtures_overlay_svg`** — family detection was
  `kind.split("_")[0]`, which reads `kitchen_sink` as family "kitchen" and
  silently drops the basin ellipse. Replaced by an explicit `_FIXTURE_GLYPH`
  map. Verified glyph counts unchanged (172 basins = 81 WC + 60 lavatory + 31
  sink; 29 ranges × 4 burners).
- **A. `ai/render_prompt.py::_FIXTURE_PROSE`** — rekeyed to library ids. Its
  fallback is `kind.replace("_"," ")`, so stale keys degraded quietly into
  worse prompt prose ("range electric") rather than erroring.
- **B. `check_clearances` + `ClearanceIssue`** — the library's per-side,
  per-reason clearances replace a single `CLEARANCE = 0.60` that applied to
  one fixture. Reports only; never moves or drops anything. Structured
  (`required` / `actual` / `shortfall` / `blocked_by` / the manifest's own
  `reason`) so callers can rank, with `FixtureReport.tight()` for worst-first.
  The hand-rolled bed check it replaces **never fired once** across the suite.
- **B. Three false-positive classes were found and fixed before trusting any
  number** — see the notes in `fixtures.py`: side-circulation on a non-handed
  piece is satisfied by EITHER side (a bed's aisle may be on either side of
  it); the two halves of one shared gap are collapsed into a single finding;
  and a neighbour must cover more than half an approach to count as blocking
  it (`_BLOCK_FRAC`). Raw count 323 → 200.
- **B. `_dedupe_facing` now keys on the DIRECTION as well as the pair.** Keying
  on the pair alone kept one issue per neighbour, so a wrap-around neighbour
  blocking two distinct gaps could have one collapse wrongly against the
  other. Inert on today's data (0 occurrences, verified); covered by a unit
  test of the pure function.
- **GEOMETRY MOVED: L-shaped rooms are no longer treated as rectangles.**
  Placement only ever looked at `cells[0]`, so the 72.9 m² of alcove across 31
  rooms may as well not have existed, and — worse — a cell edge at an alcove
  MOUTH was treated as a wall, so **12 must-back-wall fixtures (beds,
  nightstands, a WC, wardrobes) were drawn floating against thin air.** New
  `_backed_by_wall` tests the sliver directly behind a candidate rather than
  the cell's whole side, since an alcove usually meets only part of one.
  Placement, door-clearance rescue and clearance measurement are all now
  cell-aware. Net across the suite: **607 fixtures / 134 unfit** (from 605 /
  138), 4 fixtures rehoused in an alcove, **0 floating, 0 outside their cell**.
- **Alcove exile is restricted by MEANING, not geometry** (`_ALCOVE_EXILE_OK`
  = wardrobe, fridge, shower_stall). A nightstand and a kitchen sink both
  placed fine in an alcove, but a nightstand IS its adjacency to the bed and a
  sink IS part of the counter run; three metres away each becomes a drawing
  that quietly says something false. Missing is a finding the reader can act
  on; misplaced is not.
- **The toilet now falls back off the wet wall** when that wall turns out to
  be an alcove mouth, the way the lavatory already did.
- **GEOMETRY MOVED (the only change here that does):** `_place_bath` placed
  the WC at an invented `prefer=0.05` while its manifest asks 0.10 m of elbow
  room. Now read from the library. Net effect: **one MORE fixture placed
  (604 → 605), one FEWER unfit (139 → 138)**, WC elbow findings 62 → 25, and
  every other clearance finding unchanged at 138 — a surgical change. The 25
  that remain are genuine: 23 are the pan touching the lavatory, 2 are walls
  with no room to honour it. 52 pass / 51 sweep pass; no baselines involved,
  since nothing in the generation path imports `fixtures.py`.
- **FIXED — 44 fixtures physically intersected another fixture in the same
  room** (long-standing; measured identical across every change above before
  being addressed). An overlap outranks any clearance finding: a clearance
  finding says a room is tight, an overlap says the drawing is impossible.
  Two independent causes, split by whether either piece carried a
  "moved clear of a doorway" note:
  - **35 — `check_door_clearance` moved pieces onto ones it could not see.**
    Its blocker list was `[k.rect for k in keep ...]`, and `keep` holds only
    fixtures the loop has already reached, so everything later in
    `rep.fixtures` was invisible and a displaced piece came to rest on top of
    it. Now built from all other fixtures in the room. The counter's TRIM path
    deliberately keeps no such check — a counter is supposed to overlap the
    sink and range set into it.
  - **9 — the kitchen sink and range were positioned independently.** The sink
    was centred on the wall and the range pinned 0.05 m from the end, with a
    guard that checked only the TOTAL width; on a 1.50 m run that gives sink
    0.35–1.15 against range 0.05–0.65. Appliances now go in from the ends and
    the sink takes the clear space between them.
- **Relocation before deletion, which the above made necessary.** Blocking
  properly turned 35 overlaps into 36 deletions, because `_shift_along` only
  ever slid a piece along the wall it was already on. Displaced fixtures now
  try the room's other walls (`_RELOCATABLE` — wardrobe, fridge, shower,
  lavatory, WC; not the position-defined nightstand or sink), and a wet
  fixture prefers a wall that is already wet, so a WC and basin do not end up
  on opposite walls of a 1.5 m bath. Net **633 placed / 108 unfit**, from
  604 / 139 at the start of the session.
- **Verified invariants across all 633 fixtures: 0 outside their cell, 0
  backed on air, 0 overlapping, 0 standing in a doorway.** Replay confirmed
  byte-deterministic.

**2026-08-06 — SHARED CODE, but NO regen needed: fixture overlay legibility
(core/render.py)**
Two additive functions at the end of `render.py` serving Phase E.2 furniture
placement (`solver/fixtures.py`). **Nothing in the generation or catalog path
calls them yet** — `run.py` and `build_catalog.py` are untouched, all 52
baselines are byte-stable, and the catalog does not show furniture. Logged
because the file is shared code, not because a regen is owed.

- `fixtures_overlay_svg(fixtures, layout)` — furniture rectangles. Fill is now
  a SINGLE neutral (`#e3ded4`) for every family. The first cut coloured by
  family and a pale-blue shower inside a bath read as a separate ROOM against
  the public zone's `#cfe2f3`. Room fill means zone; fixture fill must mean
  "contents". Kinds are distinguished by LINEWORK instead — pillow band, basin
  ellipse, burner circles — which also survives greyscale printing.
- `archplan_to_svg(plan, door_emphasis=False)` — overdraws doors in magenta
  for the image model. Default False; the technical drawing is unchanged.
- `polished_image_overlay(layout, png)` / `room_label_masks(layout)` — place a
  returned image over the lot rect and cover each room's label zone, so our
  own labels can be composited on top. polish.py only.
- `inject_overlay(svg_doc, overlay)` — SVG has no z-index, so an appended
  overlay covered the room labels and a bed landed across
  `MASTER BR / 5.4x3.7 m . 20.0 sqm`. It now lifts the label `<text>` elements
  out of the finished document and re-emits them after the overlay. Chosen
  over teaching the drawing passes about a furniture layer specifically to
  avoid moving text in 52 baselines for a feature nothing calls yet; a
  document with no overlay is returned untouched.

**2026-08-06 — SHARED CODE: ONE definition of "exterior wall" (core/model.py)**
`core/render.py` and `solver/architectural_plan.py` each had their own answer
to "is this wall exterior", and they disagreed. Render used connectivity (does
the space beyond reach the outside); architectural_plan used strict
envelope-edge equality. So a wall that is exterior only because it faces an
UNCLAIMED PERIMETER STRIP was drawn at exterior weight but got **no window and
could host no exterior door**.

The single definition now lives in `core/model.py` — the natural home, since
`Layout.footprint_area` already established that the footprint is the union of
ROOM CELLS, not the envelope rectangle:
- `make_outside_probe(env, obstacles)` -> `faces_outside(x, y)`
- `probe_point(rect, side)` -> the point just beyond a wall to test

Both modules consume it, so they can no longer drift apart. All FOUR
`_touches_exterior` call sites benefit, not just windows: perpendicular-wall
detection, window placement, the dirty-kitchen service door, and the front
door. Verified on a 20x20 solve — the bedroom's set-back south wall now
carries a 2.09 m window where it previously had none.

**Two bugs found by the baseline refresh, both in the new code:**
- The probe was held in a MODULE GLOBAL (`_OUTSIDE_PROBE`) and not cleared
  after use, so a stale probe leaked into the next brief: the full-suite
  result for `2s_3br_9x13_nw_side_spine_stair_baths_ds_gr` diverged from
  running the same brief alone (deterministic, but context-dependent). Now
  cleared on return; any call outside `architecturalize()` falls back to the
  deterministic envelope-edge test. **The global was justified when added as
  "safe because the pipeline is sequential" — that was exactly backwards.
  Sequential execution is what let one brief's state reach the next.**
- The probe was built from ALL of `layout.rooms`, so on a multi-storey layout
  the upper floor's footprint masked the ground floor's perimeter gaps. Now
  scoped to the storey being processed. This is why the 2-storey baseline
  changed a second time; the later value is the correct one.

11 baselines refreshed; 0 drift across three consecutive full-suite runs.


**2026-08-06 — SCOPE DECISION: these plans are CUSTOMER-DISCUSSION documents**
Recorded because it changes how several rules below are justified. The output
is an initial discussion aid and a brief handed to an architect who produces
the official drawing — it is NOT a construction set. So post-solve cleanup is
allowed to favour a readable plan over strict rule-keeping: an unexplained
interior void reads to a customer as a mistake, while a slightly irregular
room just reads as "this space belongs to the living room". What is NOT
negotiable is anything that makes the plan an unusable brief — a hard PD 1096
violation such as a windowless bath.

**2026-08-06 — SHARED CODE: `claim_dead_strips` is ALWAYS ON (flag removed)**
Was an opt-in per-topology flag, default off, purely to keep 60+ frozen
single-storey baselines untouched — a reason that expired once the catalog was
re-baselined. **77% of the catalog's remaining dead space was simply
topologies that had never opted in.**

The flag is REMOVED, not left inert (dormant config is what produced the
month-long dangling `fallback_topology` bug): gone from the `Topology`
dataclass, its JSON loader, 4 copy sites in `solver/topology.py`, 3 in
`run.py`, the gate in `run.py`, and 5 topology JSONs.

Dead space across the catalog **25.3 -> 9.4 m2** (-63%); worst single floor
8.90 -> 3.28 m2; 51 of 61 floors now fully claimed. 14 baselines refreshed.

**2026-08-06 — SHARED CODE `solver/snap_gaps.py`: claim rules relaxed + daylight guard**
Per the scope decision above, reclaiming now favours the room that obviously
owns a strip over rule enforcement:
- **Master-supremacy guard REMOVED from the claimer only.** The rule still
  holds where it belongs — a hard CP-SAT constraint at solve time (1 m2 margin
  vs EVERY standard) and a growth cap during snapping. Both act on real room
  allocation; the claimer only decides who mops up a scrap the solver already
  declined to allocate. **Consequence: a standard bedroom may now show a
  marginally larger area than the master in the LABELS.** If that ever reads
  wrong to a customer, fix it HERE, not in the two layers above.
- **Room-type priority is a tie-break, never a gate** — unlisted types sort
  last instead of being excluded.
- `MIN_ALCOVE_THICKNESS_M` 0.55 -> **0.25**; `CLAIM_MIN_CONTACT_FRAC` 0.5 ->
  **0.2** (kept non-zero so nothing claims a strip it barely grazes, which
  produces finger-shaped rooms that look like a bug).
- **NEW `_daylight_reachable` guard — the one check that survives.** A claim is
  skipped if it would cut any window-requiring room off from the exterior.
  Relaxing the rules surfaced two live cases where a strip sealed a GF bath's
  light path (`2s_2br_sq_rear_stair_bath_gr`,
  `2s_3br_nw_side_spine_stair_baths_ds_gr`) — a hard IRR Rule VIII §10 error.
  **Do not remove this when loosening further.**

**2026-08-06 — SHARED CODE: windows may sit on an L-shaped room's ALCOVE**
`_place_windows` only ever examined `room.rect`, never `rect2`. When a
dead-strip claim extended a previously-interior room out to the envelope via
its alcove, the validator saw an exterior wall and demanded a window while the
placer saw none and placed nothing — a hard `window area 0.00` failure. The
candidate loop now iterates `room.cells`, and `Window` gains **`cell_index`**
(0 = rect, 1 = alcove) which `core/render.py::_window_svg` honours, so the
opening is drawn on the right cell. Defaults to 0; pre-existing windows are
unaffected.


**2026-08-05 — SHARED CODE `core/render.py`: building outline follows the ROOMS, not the envelope**
Pass B decided "exterior wall" by asking whether the wall coordinate lay on the
envelope edge. It now asks whether the empty space the wall FACES reaches the
outside (grid flood-fill from the envelope border). An unclaimed perimeter
strip is therefore OUTSIDE the building, and the wall behind it is a real
exterior wall.

This makes the drawing agree with arithmetic that was already correct:
`Layout.footprint_area` has always summed ROOM areas, not the envelope, so
occupancy never counted these strips. Only the render disagreed — it drew such
walls at interior thickness (0.10 m), which read as a missing exterior wall.

**Footprints are now legitimately non-rectangular** where rooms don't reach the
envelope: stepped outlines, with the setback drawn wider on that side. A gap
fully ENCLOSED by rooms (courtyard / light well) is unaffected and keeps
interior thickness — the connectivity test is what distinguishes them.

12 baselines refreshed; every change moves walls interior -> exterior (e.g.
`1s_3br_13.3x13_sq_front_back_split_baths_cl_hall_lk_ncp` ext 29->43,
int 40->26). No geometry, area or validator change — render classification only.

**2026-08-05 — SHARED CODE `solver/snap_gaps.py`: smarter dead-strip claimant selection**
Three fixes to `claim_dead_strips`, prompted by a 20x20 solve handing a
3.80 x 0.52 m strip under the bedroom to the LIVING room, which touched only
0.52 m of it while the bedroom touched all 3.80 m.

- **Geometry first, type second.** Selection ranked purely on
  `_STRIP_CLAIM_PRIORITY` (living_room 0 beats bedroom_standard 3) and never
  looked at shared-wall length. Now keyed on `(-contact, type_rank)`.
- **New `CLAIM_MIN_CONTACT_FRAC = 0.5`** — a room must abut at least half the
  strip's LONGEST side. Stops a room owning a strip it merely grazes.
- **`MIN_ALCOVE_THICKNESS_M` 0.15 -> 0.55**, calibrated against the strips
  actually occurring in the catalog (thin sides cluster at 0.25/0.30/0.50 =
  wall thickening, vs 0.60 = the cl_ld pockets this flag exists for). Do NOT
  use 0.60: coordinates carry float noise (the cl_ld strip measures
  0.5999999999999996) so an exactly-equal threshold is decided by rounding.
  A first pass at 0.90 m rejected the cl_ld pockets and defeated the purpose.

Catalog-wide: applies to every topology with `claim_dead_strips` plus all
2-storey (always-on). 8 baselines refreshed. Sub-0.55 m slivers now render as
honest declared dead space instead of implausible L-alcoves.

**2026-08-05 — `1s_2br_sq_side_split_bath_ld`: `claim_dead_strips: true` + new oversized-lot brief**
Enabled the per-topology dead-strip claimer. The topology left a persistent
~2.5 m2 unclaimed interior pocket between `standard` and `dining` at generous
lot sizes; `dining` (and sometimes `living`) now absorbs it as an L-alcove.
**100% coverage / 0.00 m2 dead at 14x14, 15x15, 18x18, 20x20 and 25x25.**

Notably **zero existing baselines changed** — the pocket only appears above the
sizes the suite previously covered, which is why it went unnoticed. Realized-
geometry cleanup only; never touches solver feasibility.

- New brief + baseline: `1s_2br_15x15_sq_side_split_bath_ld_ncp` — the first
  OVERSIZED-lot fixture (raw shell 110 m2 vs a 93 m2 target), added to give
  shell capping actual regression coverage. Suite 51 -> 52.
- Regen touches this id's **gallery card** (its canonical brief is unchanged,
  so the thumbnail only moves if the claimer alters it), **Detail -> Output**,
  and **Detail -> Definition** (the new `claim_dead_strips` key renders under
  Notable overrides).

_Everything else was applied in the 2026-08-05 regen below._


**2026-08-05 — SHARED CODE `solver/solver.py`: graded preferred-credit ADOPTED (default ON)**
Supersedes the "NO REGEN NEEDED" entry further down — that entry described the
same code while it was still default-OFF. Defaults are now `GRADED_PREF` on,
`GRADED_SHAPE=concave`, `GRADED_KNEE_ANCHOR=zero`, `GRADED_STEP_DIV=8`. The
objective's preferred-low bonus is no longer an all-or-nothing step, so a room
that cannot reach its target is no longer stripped toward its hard minimum to
fund another room's step. **Rooms pinned at their hard minimum: 20 -> 12**,
total area -0.6 m2. Catalog-wide geometry change: 25 of 51 baselines refreshed,
site regenerated. `ARTOL_GRADED_PREF=0` restores the old behaviour.

**2026-08-05 REGEN — everything below this line was applied in that build.**
The site now reports **41 topologies / 48 implementations / 35 verified**
(was 48 flat), because size-gated sibling files are collapsed into single
catalog entries. Build output: `grouped 48 topology files into 41 catalog
entries (7 with 2 size-gated implementations)`.

**2026-08-05 — CATALOG: size-gated siblings collapse into one entry (build_catalog.py + assets)**
`group_siblings()` merges two topology FILES linked by
`fallback_below_buildable_sqm` into one catalog entry — keyed on that link, not
on an `_ld`/`_gr` name suffix, so it also covers the hall / hall-less 2s pair.
The merged entry is named by the common prefix with the differing suffix
stripped (`1s_1br_sq_side_split_bath`), and each implementation keeps its own
rendered plan under `plans/`.
- **Gallery card** — one plan at a time with overlay tabs; default is the gated
  implementation (`ld` / `hall`). The card became a `<div>` wrapping an
  `<a class="thumb-hit">` with tabs positioned over the media, because a
  `<button>` nested inside an `<a>` is invalid HTML.
- **Detail page** — `Default` / `Fallback` tabs, each holding that
  implementation's full Definition + Test brief + Output stack. Heading uses
  the merged name.
- **Header stats** — now `Topologies 41` + a new `Implementations 48`;
  accordion counts read `N topologies · M impls · K verified`.
- New `.thumb-tab*` / `.impl-*` styles in `assets/styles.css` and two delegated
  click handlers in `assets/app.js`. The gallery handler runs in the CAPTURE
  phase with preventDefault/stopPropagation so a tab click swaps the plan
  instead of following the card link.
- **Gotcha:** string replacements in `build_catalog.py` fail SILENTLY if the
  anchor doesn't match — two edits (header stats, accordion counts) were lost
  on the first build and only caught on verification. Assert every replacement.

**2026-08-05 — 6 topology pairs became size-gated siblings (gr/ld collapse)**
Each `_ld` gained `fallback_below_buildable_sqm` → its `_gr`, so the runner
routes by buildable area before attempting a solve. Gates:
`1s_1br_sq_side_split_bath` 42.0 · `1s_1br_nw_front_back_split_bath` 35.0 ·
`1s_1br_wd_side_split_bath` 27.9 · `1s_1br_wd_split_wing_bath` 27.9 ·
`1s_2br_wd_side_split_bath_hall` 40.0 · `1s_2br_wd_side_split_baths_cl` 40.0.
The gate is read off the RAW envelope, not the shell-capped one. Also re-based
`1s_2br_12x10_wd_side_split_bath_hall_ld_ncp` and `..._cl_ld_ncp` to **12×11**
— both were silently falling back to their `_gr` siblings while still
reporting PASS.

**2026-08-05 — SHARED CODE: buildable-shell capping (`ai/pipeline.py`, `run.py`)**
Oversized shells now shrink to `sum(preferred_high) × 1.10` and push the
surplus into setbacks. Affects any brief whose raw shell exceeds the target —
1 of 51 today, but arbitrary lots through the app/AI path. 13 baselines
refreshed (capping + the kitchen sizing change together).

**2026-08-05 — DATA `ph_floorplan_rules.json`: sizing tiers finalised**
`kitchen` preferred-low 6.0 → 7.0, `maids_room` 6.0 → 8.0, `bedroom_standard`
held at 9.0. `sizing_policy.progression` rewritten to the three tiers the code
implements; dead `relaxed_minimum` tier removed from every room type. Changes
solved geometry catalog-wide.

**2026-08-05 — NEW topology `1s_3br_sq_bedroom_lobby_hub_baths_ds_hall_gr` + 2 test briefs (promoted to official)**
Fifth entry in `1s/3br/squarish/`, and the catalog's first BEDROOM-LOBBY
HUB parti: a small square lobby at the geometric centre takes all three
bedroom doors (br2+br3 paired on one wall, master alone on another) plus
the common bath's door on a third, with its fourth side open to the
great_room — zero corridor run. `zone_split` is deliberately null (the
private rooms wrap the hub on multiple sides rather than forming a
column, so the usual two-column split model doesn't apply);
`match_bedroom_widths: true`; distributed baths, gr-style open-plan
great_room + kitchen. Authored in a Claude cowork session from a
5-of-53-house precedent run; solver-verified and promoted to official
2026-08-05.

- New: `topologies/1s/3br/squarish/1s_3br_sq_bedroom_lobby_hub_baths_ds_hall_gr.json`
- New briefs + baselines: `1s_3br_11x11.25_sq_bedroom_lobby_hub_baths_ds_hall_gr_ncp`
  (canonical — `pick_canonical_brief` will select this one: ncp + smaller lot),
  `1s_3br_12.5x12.5_sq_bedroom_lobby_hub_baths_ds_hall_gr_ccp`
- The ccp brief was re-based 12x12 → 12.5x12.5 the same day (user request).
  12x12 is the raw ccp feasibility floor but solves degenerate — hub
  4.25 x 1.00 m, ensuite 1.25 x 5.00 m, at 0 warnings — which defeats the
  parti the topology exists for. 12.5x12.5 reads correctly (hub aspect
  1.28, square ensuite). The 12x12 brief + baselines were deleted, so if
  a regen ran between the two states, this id's **Detail → Test Brief**
  and **Detail → Output** subsheets both changed again.
- Corrected the topology's own `notes` caveat, which had the size
  relationship backwards (see CLAUDE.md entry). No geometry change — notes
  only — but the **Detail → Definition** subsheet renders `notes`, so the
  regen picks this up.

Regen touches: new **gallery card** + all four **Detail** subsheets for
this id; **header stats** (total/verified +1); **accordion + filter
counts** (3BR group, `sq` shape pill). No other topology affected — no
shared code was touched.

**2026-08-05 — SHARED CODE + ALL BRIEFS: occupancy-driven setbacks, front 2.0 → 3.0 m (REGEN THE WHOLE SITE)**
Lot setbacks are now derived from `core/validator.py::SETBACK_MIN_BY_OCCUPANCY`
instead of a hardcoded 2.0 m, and the project defaults to R-2 (front 3.0,
side/rear 2.0). 2.0 m was never a legal front yard — it is the Sec. 708(a)
minimum for side/rear yards. **Every plan in the catalog moves**: the lot
rectangle grows by 1 m of depth relative to the building.

- `ai/pipeline.py::_make_default_lot` — derives per-side minimums from the
  table; clamps explicit `Brief.setbacks` (firewall `0` excepted).
- `ai/brief.py` — `occupancy_class` default R-1 → R-2.
- All 108 briefs under `floorplan_v1/briefs/` — `occupancy_class` → R-2.
- 26 test briefs re-based +1.0 m lot depth and **renamed** (dimension tokens in
  filenames changed, e.g. `1s_2br_10x10_...` → `1s_2br_10x11_...`); their old
  baselines were deleted and all 51 refreshed.
- 24 hand-curated sweep fixtures bumped +1 m depth; 8 superseded ones deleted.
- `core/validator.py` comment and
  `data/ph_floorplan_rules.json::global_constraints.setbacks` updated — the
  latter gains a full `by_occupancy_class` block (the old `refinement` block
  was marked "TO CONFIRM" and mentioned only R-1).

Regen touches **every** gallery card, every **Detail → Output** subsheet (all
plans re-render with the new lot rectangle), every **Detail → Test Brief**
subsheet (26 renamed briefs, 108 changed `occupancy_class`), and the
**header stats**. Note `artol-topologies/data/briefs/` still carries 34 copies
of the old `"occupancy_class": "R-1"` — that is build-artifact staleness and
self-corrects on regen; do not hand-edit it.

**2026-08-05 — SHARED CODE `solver/solver.py`: graded-preferred prototype (SUPERSEDED — see the ADOPTED entry above; this described it while still default-off)**
Added a graded/concave alternative to the objective's all-or-nothing
preferred-low bonus, behind `ARTOL_GRADED_PREF` (+ `ARTOL_GRADED_SHAPE`,
`ARTOL_GRADED_STEP_DIV`, `ARTOL_KNEE_POS`, `ARTOL_KNEE_VAL`,
`ARTOL_KNEE_ANCHOR`). Logged here because it touches `solver/*.py`, which
normally means catalog-wide blast radius — but it is **default-OFF and
verified byte-identical** to previous output across the whole suite, so
**no regen is required for this entry**. Full rationale and measurements:
`SIZING_OBJECTIVE_INVESTIGATION.md`.

If the prototype is ever switched on by default, that IS a catalog-wide
geometry change (~80 of 203 tracked rooms move) — regenerate the whole
site and refresh most baselines, per workflow note 2 above.

_Everything above is new since the 2026-07-23 full regen; the 2026-07-23
entry itself is already applied (see Applied history)._

**2026-07-23 — NEW topology `2s_2br_sq_l_landing_stair_bath_gr` + SHARED CODE: first non-straight stair type (user request)**
The catalog's first stair type other than a straight single flight: an
L-shaped stair that turns 90° at a quarter landing. Sibling of
`2s_2br_sq_rear_stair_bath_gr` — identical hall-less squarish 2BR/2-bath
room program, differing only in the stair's own shape (boards off the
great room's south wall, turns, arrives into `hall2`'s east wall).
Squarish is the shell this actually helps: a straight run needs ≥3.5 m in
one axis; folding it into a near-square ~2.1–3.6 m bounding box only pays
off where width and depth are both moderately scarce (narrow shells
already have depth to spare, so folding buys nothing there).

**New shared-code stair-type mechanism** (prototyped earlier this session
on a scratch/throwaway topology, now used for real):
- `RoomSpec.stair_type` (`solver/topology.py`) — per-room, defaults
  `"straight"`; auto-loaded via the existing generic JSON-to-dataclass
  filter, no threading needed.
- `Adjacency.stair_wall` (N/S/E/W) — lets a topology author FIX which wall
  of a turning stair a `stair_boarding`/`stair_arrival` neighbor reaches,
  since a turning stair's entry/exit walls are typically perpendicular (or
  same-wall-different-offset for a U-turn) — a case the existing solver-
  chosen ascent-axis boolean (`stair_asc`/`stair_rv`) structurally can't
  express (it always treats one axis as "the two ends," the other as
  flanks). `solver.py`'s stair_boarding/stair_arrival block forces the one
  orientation variable matching the declared wall instead of deriving it
  from ascent direction when `stair_wall` is set; untouched (old asc/rv
  logic) when absent, so every existing topology is unaffected.
- `Room.stair_type` / `stair_board_wall` / `stair_arrive_wall`
  (`core/model.py`) carry the resolved values from solve to render. Fixed
  a real bug found during prototyping: boarding/arrival wall info only
  ever landed on whichever floor's adjacency declared it (GF flight got
  `board`, 2F stairwell got `arrive`) — both floors need BOTH values (same
  physical turn), so `solver.py` now propagates across the
  `stair_vertical` link.
- `_l_landing_glyph` (`core/render.py`) — draws the two-leg + landing
  turn glyph, dispatched off `room.stair_type`; `_stair_glyph`'s tread-line
  drawing was factored into a shared `_tread_lines_svg` helper reused by
  both.

**Sizing gotcha, now documented in the topology's own notes**: setting
`min_area_sqm` equal to the "stairs" room-catalog's own
`preferred_area_sqm` ceiling (both 4.5, tuned for a straight stair)
silently pins the area to an exact value with no valid grid-integer
solution once both dimensions also floor at 2.1 m (confirmed via
factor-pair arithmetic — 1800 grid-unit² has no factor pair both ≥42) —
genuinely infeasible at every lot size tested, not a tightness issue.
Fixed by also setting `set_max_area_sqm: 10.5` (near the ~3.2×3.2
preferred footprint) so the floor and cap don't collide.

Verified: true floor 9.2×9.2 (buildable 5.2×5.2), clean 0-warning solves
9.2×9.2 through 14×14 (published canonical minimum 9.5×9.5). Kitchen
needed `mechanical_vent: true` — the wider ~2.1–3.6 m stair footprint (vs.
the straight sibling's 0.9–1.2 m) compresses kitchen's own width enough
to miss the PD 1096 §808 10% window-area floor at the compact end; no
other program change from the straight-stair sibling. 49/49 regression
pass (was 48, +1 new brief); zero effect confirmed on the other 48
briefs, including the straight-stair sibling itself.

**2026-07-23 — `1s_2br_wd_side_split_baths_cl_ld`: match_depths ensuite=common + SHARED CODE new match_depths feature (user request)**
Added `match_depths: [["ensuite","common"]]` so the two rear-band baths
render at the same depth (previously differed, e.g. 1.25 m vs 1.5 m at
12×10). New shared-code feature (`match_depths` didn't exist before): the
y-axis mirror of `match_widths` — same generic id-pair mechanism threaded
through `solver/topology.py` (dataclass + loader + all 4 in-file
copy-constructors), `run.py` (3 copy-constructors), and a new
`solver.py` constraint block (`rh[a] == rh[b]`). Built the `snap_gaps`
group-lockstep support (`matched_y_pairs` alongside `matched_x_pairs`,
same union-find grouping, capped/extended on north/south) IN FROM THE
START this time, learning from `match_widths`' own silent-override bug
found earlier this session. Verified solver-safe: identical feasibility
at every known size (12×10 through 15×11.5, oversized 20×15/25×18, the
true floor) with vs without the constraint. Along the way, switched the
shared `group_of`/`group_of_y` structures in `snap_gaps.py` from
`frozenset` to sorted tuples — frozenset iteration order is hash-
randomized per-process, which was letting `deterministic=True` produce
byte-different (though geometrically identical) SVG element order across
runs; confirmed this specific reordering issue predates today's work
(reproduced on `cl_gr`, which touches neither `match_widths` nor
`match_depths`) so it's noted but not chased further. Also tested (and
explicitly REJECTED, not applied) `match_bedroom_widths`-style pairing of
`master`/`ensuite` per the same user request: unlike living/dining/
kitchen or ensuite/common, master and ensuite aren't naturally close in
width, and forcing them equal breaks the topology at its own published
canonical minimum (12×10) plus 11.9×10/13×11/14×11 — all silently
fall back to `cl_gr`. Documented as a "tested and rejected, don't retry"
note in the topology's own JSON. 48/48 regression pass; 1 baseline
refreshed (target topology only — confirmed via repeated re-solves that
the ~5-10 other topologies flagged as differing are pre-existing
non-deterministic element-order noise, unrelated to this change).

**2026-07-22/23 — SHARED CODE: stair rail + opening render for 2-storey plans (user request)**
The boarding/arrival boundary between a stairs room and its GF/2F
circulation neighbor was previously 100% invisible (rendered like an
open-plan LDK seam — the whole shared wall suppressed). Added
`_stair_rail_svg` (`core/render.py`): draws a thin partition line along
the flanking side of the run, with a gap sized `STAIR_OPENING_M` (0.9 m)
left at the correct end — the LOW end on the boarding/ground floor
(opposite the solver's own `stair_up` ascent vector), the HIGH end on the
arrival/upper floor — marking exactly where a person steps on/off the
flight. No-ops (leaves fully open, unchanged) on a perpendicular end-cap
edge, which already reads as a full-width entrance on its own. Verified
across both vertical- and horizontal-run topologies (narrow side-spine,
wide rear-stair). Refreshed all 8 two-storey test baselines (2 briefs
per topology across the 2BR/3BR × narrow/squarish/wide 2-storey matrix,
plus the hall variant). 48/48 regression pass.

**2026-07-23 — `1s_1br_nw_front_back_split_bath_gr`: removed `dirty_kitchen: true` from test brief**
Reverted to no dirty-kitchen box requested — the kitchen still gets its
exterior door via the shared rear/side fallback (2026-07-22), matching
how the `_ld` sibling behaves (plain door, no service-yard box). Baseline
refreshed.

**2026-07-23 — `1s_2br_wd_side_split_baths_cl_ld`: match_widths living/dining/kitchen + SHARED CODE snap_gaps fix (user request)**
Added `match_widths: [[living,dining],[dining,kitchen]]` so all three
public rooms render at the same width (previously only dining/kitchen
matched by construction; living, the entry-hosting front room, could
drift wider on its own — e.g. 3.6 m vs 3.0 m at 12×10). Verified
solver-safe first: identical feasibility/warnings at every known size
(12×10 through 15×11.5, oversized 20×15/25×18, the ~11.9×10 true floor)
with vs without the constraint. The JSON field alone wasn't sufficient
though — `snap_gaps` (post-solve gap-filler) had no awareness of
`match_widths` and silently re-widened `living` past its matched
partners while closing a leftover boundary gap. Fixed in shared code
(`solver/snap_gaps.py` + `run.py`): `match_widths` pairs now union into
proper multi-room groups via union-find (not the old pairwise dict used
for `match_bedroom_widths`/`match_bath_widths`), so every group member is
gap-capped and extended in lockstep — a 3+-room chain holds as ONE
invariant through `snap_gaps` instead of only the nearest-neighbor pair.
Side effect (this topology only): the dead pocket that used to land on
`living` as an L-alcove now lands on the private side (bedroom/hall)
instead, since living can no longer independently absorb it — still 0
dead space, still 0 warnings, just a different room claims it now.
**Also fixes 2 other pre-existing topologies** whose own `match_widths`
fields had been silently unenforced by `snap_gaps` since the field was
first added to the schema: `1s_1br_sq_side_split_bath_gr` and
`1s_1br_wd_split_wing_bath_gr` — their declared width-matches are now
actually durable in the final render too. 3 baselines refreshed
(the target topology + the 2 incidentally-fixed ones). 48/48 regression
pass; confirmed the ~6 other topologies using `match_widths`/
`match_bedroom_widths`/`match_bath_widths` are unaffected (simple 2-room
pairs behave identically under the new union-find grouping).

**2026-07-22 — SHARED CODE: kitchen exterior door generalized catalog-wide (user request)**
`brief.kitchen_back_door` (default `true`) is now the single global "does
the kitchen get an exterior door" option for every topology, working as
originally documented instead of only working when the kitchen's rear
wall happens to be exterior. `_dirty_kitchen_door` (`solver/architectural_plan.py`)
without a declared `dirty_kitchen` setback element now searches REAR (N)
first, then the two SIDE walls (E, then W) — never the front (S) wall,
which is the street facade already hosting the main entry. A declared
`dirty_kitchen` element still pins its own wall exactly as before (rear,
or side_setback's E/W) and still overrides the option (a requested dirty
kitchen always forces the door regardless of `kitchen_back_door`) —
unchanged, already worked this way.

Removed the one-off `kitchen_side_door` Topology flag added earlier this
session for `1s_1br_nw_front_back_split_bath_ld` — superseded by the
general default, deleted from `solver/topology.py` (dataclass + loader +
all 4 in-file copy-constructors) and `run.py` (3 setback-stripping
copy-constructors); the `_ld` topology's own flag reference removed too
(same rendered door, now via the general path).

Audited all 46 topologies (33 solvable via a real test brief, 13 with no
test brief yet — unchanged): 28 already got a kitchen door via the rear
wall; **5 gained a new door** they were structurally entitled to but never
got — `1s_1br_nw_front_rear_bath_gr` (also had a now-stale
`kitchen_back_door: false` in its brief, removed — the reason it was set
false no longer applies), `1s_2br_nw_side_corridor_baths_ds_hall`,
`1s_2br_wd_front_back_split_bath_hall_ld`,
`1s_3br_sq_front_back_split_baths_cl_hall_lk`,
`1s_3br_sq_hall_core_baths_ds_hall_gr` (last one already declared a
side-setback `dirty_kitchen` element, but its canonical brief never set
`brief.dirty_kitchen: true`, so it got stripped before solving and the
door never rendered — now covered by the generalized default regardless).
The 13 untested topologies all already declare a `dirty_kitchen` element
(mostly rear_setback), so they're unaffected either way.

Verified via two identical back-to-back full-suite runs that ~10 OTHER
baselines drift run-to-run regardless of this change (pre-existing
solver non-determinism on borderline/complex topologies, not caused by
this edit) — left those untouched per the baseline-regen convention;
only refreshed the 6 baselines (5 topologies, one with 2 briefs) that
genuinely and reproducibly changed. 48/48 regression pass both times.

**2026-07-22 — `1s_1br_nw_front_back_split_bath_ld`: exterior kitchen door, no dirty-kitchen box (user request)**
Same underlying problem as the gr sibling's same-day fix (kitchen has no
rear exterior wall — bath stacks behind it — so the door-generator's
default rear-wall check never fires), but this time the user explicitly
did NOT want a dirty_kitchen setback element (no visible service-yard
box). Added a new narrow opt-in Topology flag,
`kitchen_side_door: bool = False` (`solver/topology.py`, threaded through
`load_topology` + all 4 in-file copy-constructors + run.py's 3
setback-stripping copy-constructors — same "thread through every copy
site" pattern as `ldk_horizontal`/`kitchen_rear_pin`). When True and no
`dirty_kitchen` setback element is declared, `_dirty_kitchen_door`
(`solver/architectural_plan.py`) now also tries the kitchen's SIDE (E/W)
wall instead of only ever the REAR (N) wall — same wall-selection logic a
side-setback dirty kitchen already uses, just without declaring one.
Enabled only on this one topology. Verified: door renders on kitchen's
east wall with no dashed box; the gr sibling and every other topology
using the shared `_dirty_kitchen_door` default path are unaffected
(default False). 48/48 regression pass.

**2026-07-22 — `1s_1br_nw_front_back_split_bath_gr`: exterior kitchen service door (user request)**
Kitchen's rear wall is interior (bath stacks behind it on the plumbing
line), so the default rear-behind-kitchen dirty-kitchen placement was
impossible and no exterior door existed off the kitchen. Added
`setback_elements[dirty_kitchen]` with `location: side_setback, behind:
kitchen` — same pattern already used by `1s_2br_nw_front_back_split_bath`
— which puts the service pocket (and the kitchen's exterior service door)
on kitchen's side wall (right, non-carport side) instead. Opt-in via
`brief.dirty_kitchen = true`; canonical brief
`1s_1br_8x10_nw_front_back_split_bath_gr_ncp` updated to request it
(dropped the now-moot `kitchen_back_door: false`) and its baseline
refreshed. Verified: door only appears when a brief opts in (the
`_compact` sweep fixture, which doesn't set `dirty_kitchen`, is
unaffected). 48/48 regression pass. Catalog regenerated same day (folded
into the run below).

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
