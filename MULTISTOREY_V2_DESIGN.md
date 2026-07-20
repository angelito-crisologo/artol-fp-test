# Multi-storey v2 — design & implementation plan

**Status: IMPLEMENTED 2026-07-18 · all 8 tasks complete · regression 66/66**

First running topology: `2s_2br_nw_side_spine_stair_bath_hall` (8×12 lot,
COMPLIANT, 0 warnings; stair + stairwell land identical at the drawn
0.9 × 3.5 m; test brief `2s_2br_8x12_nw_side_spine_stair_bath_hall_ncp`).

**Landing fix (added 2026-07-18, same day):** working the riser math against
the solved plan exposed a functional defect carried over from the reference
drawing — the flight topped out at the rear end of the stairwell where only
a bedroom adjoins, while the upstairs hall sat at the bottom end. Fixed
with two new adjacency kinds + a per-stair-pair ascent decision:
- `stair_boarding` (GF circulation ↔ flight) and `stair_arrival` (upper
  circulation ↔ stairwell) — beyond the normal shared-wall requirement,
  each must meet the stair at the correct END of the run. Ends are tied to
  a shared CP-SAT ascent bool per `stair_vertical` pair, so boarding and
  arrival are always opposite ends; an end-cap neighbor fixes the ascent
  outright, a flanking neighbor's overlap must reach within 1.0 m
  (`STAIR_END_ZONE_U`) of its end. Run axis (vertical/horizontal) is its
  own decision bool, so the constraint is orientation-general.
- `architectural_plan._effective_kind` renders both kinds as open_plan.
- On the canonical lot the solver resolved it by REVERSING the ascent:
  boarding at the rear off the hall's rear leg, arriving at mid-plan into
  hall2, which now serves master/bath2/br2 directly. Regression 66/66.

**Dead-strip claimer + 8×10 canonical lot (added 2026-07-18, same day):**
- `snap_gaps.claim_dead_strips` — post-snap pass that flood-fills unowned
  interior cells, and hands each strictly-rectangular unowned strip to an
  adjacent room as its rect2 (L-alcove). Claim priority: living/great >
  hallway > dining > bedrooms > kitchen; stairs never claim; one alcove
  per room; non-rectangular holes are left alone. Wired into the
  multi-storey pipeline only — the 1s path is deliberately untouched to
  keep its 65 baselines byte-stable. Result: 100% floor coverage on both
  storeys at 8×12 and 8×10.
- Canonical lot moved 8×12 → 8×10 per user direction. The reference's
  separate living + dining is arithmetically impossible on 8×10 (GF hard
  minimums 6+6+3+1.2+1.5+2.6 = 26.3 m² > the 4×6 = 24 m² buildable), so
  the ground floor converted lk → gr: one open great_room (entry, dining
  folds in). No dining counter is possible in this parti (great_room and
  kitchen never share a wall — the bath band sits between), so dining
  furniture lives in the great room. Verified COMPLIANT at 8×10 and 8×12;
  test brief now `2s_2br_8x10_nw_side_spine_stair_bath_hall_ncp`.

**Hall-less compact sibling + shell-conditional selection (2026-07-19):**
The user asked whether the GF hall could be conditional on shell size.
Decision: siblings, not a conditional room (a hall isn't a knob — removing
it retargets the boarding edge, the bath's door host, the kitchen's access
edge, and the stacks; the 1s catalog's `_hall`/no-hall pairs are the
precedent), plus one new general field to encode the size rule:
- `fallback_below_buildable_sqm` on a topology (paired with
  `fallback_topology`): below this buildable area per floor, the runner
  routes straight to the fallback sibling BEFORE solving — intent, not
  failure, recorded as a `compact_fallback` suggestion (the infeasibility
  fallback stays a warning). Threaded through the same copy sites as
  `fallback_topology`.
- `2s_2br_nw_side_spine_stair_bath` (hall-less): great room IS the GF
  circulation — stair boards off it, T&B doors into it, kitchen opens
  directly behind it, which newly enables the dining counter (great and
  kitchen share no wall in the hall parti). Needed three authored guards:
  `zone_balance_rooms` counting the whole upper floor (minus stairwell) as
  the private wing — without it the topology is PROVABLY infeasible, since
  the forced-full-width great + rear-pinned kitchen make GF public
  ≥ 16.3 m² while master+br2 top out ~15.1 on a 24 m² floor;
  `mechanical_vent` on the galley kitchen (back-door wall only); and
  common_bath shape caps in the profile (`max_greatest_dim_m` 2.5 +
  `max_area_sqm` 2.5) because post-snap aspect is unchecked and snap
  otherwise stretches the bath to 1.0×3.5. Bonus: the capped bath leaves a
  strip the dead-strip claimer hands to the kitchen as an L-pantry — the
  reference spec's under-stair storage, materialized.
- The `_hall` variant declares the fallback pair (threshold 28 m²/floor:
  hall from ~8×11 lots up, hall-less below). Verified: hall retained at
  8×11 and 8×12; auto-switch fires at 8×10 with the note; hall-less solves
  directly at 8×10 with 100% coverage. Regression 68/68 (3 × 2s briefs).

**Stair travel arrow (added 2026-07-19):** the flight now renders as a real
stair glyph, not a plain labeled box — light tread lines across the run plus
a bold direction arrow, "UP" on the ground floor and "DN" on the upper
floor. The solver already decided ascent direction (`stair_asc`/`stair_rv`);
that's now resolved at solution extraction into `Room.stair_up`, a lot-space
unit vector from the flight's bottom to its top. The renderer
(`render._stair_glyph`, replacing the generic centered label for
type=='stairs') draws the arrow along `stair_up` on the ground floor and
reversed on upper floors. On the 8×10 plan: board at the great-room (front)
end, climb toward the rear.

Known gaps after implementation (beyond the out-of-scope list):
- Wet-stack cross-floor proximity not built (the reference's
  "fully_stacked" plumbing claim was false anyway).

Goal: make 2-storey topologies (starting with
`2s_2br_nw_side_spine_stair_bath_hall`) solvable, validatable and renderable
by the existing pipeline with the smallest possible disturbance to the
single-storey (1s) catalog, whose 65-brief regression must stay green
throughout.

## Architecture in one paragraph

Both storeys share the same footprint, therefore the same x/y coordinate
plane and the same buildable envelope. That means **one joint CP-SAT solve**
can place all rooms of both floors in a single model — the only structural
change is that the no-overlap constraint applies *per storey group* instead
of globally, plus a rect-equality constraint tying the stair flight (GF) to
the stairwell opening (2F). Everything *downstream* of the solver
(validator, snap-gaps, architectural plan, renderer) stays single-storey:
the solved Layout is **split into per-storey sub-layouts** and each is
processed exactly like a 1s result. The renderer composites the per-floor
SVGs side-by-side into ONE output file, preserving the 1-brief-1-SVG
contract that the test baselines, output folder, and Streamlit app all
assume.

## Design decisions (locked for this phase)

- **D1 — storey is a room attribute, not a nested schema.** `rooms[].storey:
  1|2` on a flat list; `storeys: 2` top-level. All existing consumers
  (matcher, loader, the 7 Topology-copy transforms) keep working; storey is
  one more threaded field.
- **D2 — vertical links are adjacency kinds, not new sections.**
  `kind: "stair_vertical"` = the two rooms occupy the identical rectangle on
  their respective floors (hard). It also keeps the adjacency graph
  connected so `validate_topology`'s reachability check spans floors. A
  future `wet_stack` soft kind is out of scope this phase (noted, not
  built) — the reference design itself doesn't stack its baths.
- **D3 — joint solve, split downstream.** No two-pass solve, no retry loop.
  Split helpers produce per-storey Layout + Topology *views*; downstream
  modules are called per floor unchanged.
- **D4 — one composite SVG.** Ground floor drawn with full lot context
  (setbacks, entry, setback elements); upper floors as shell-only plans.
  Titles "GROUND FLOOR" / "SECOND FLOOR". Nested `<svg x=...>` embedding —
  zero refactor of the existing draw code.
- **D5 — building voids apply to every storey.** Conservative: the upper
  shell doesn't cantilever over a carport notch. Revisit if a 2s ccp
  topology ever needs the overhang.
- **D6 — stair rooms don't snap.** `snap_gaps` must not grow one floor's
  flight independently of the other's opening (breaks D2's equality) — and
  a stair's run is riser math, not leftover space. Stair-typed rooms are
  frozen during gap-snapping.
- **D7 — zone_split and storeys don't mix.** A `zone_split` in a 2s
  topology may only reference same-storey rooms (validation error
  otherwise). The natural 2s parti (public down / private up) needs no
  zone_split at all; the solver's existing private≥public area rule already
  works cross-floor since it just sums areas.

## Tasks

- **T1 — rules catalog: `stairs` room type.**
  `ph_floorplan_rules.json` room_catalog entry. Hard: min least dim 0.75 m
  (PD 1096 Sec. 708(h) min clear width), min area 2.1 m² (0.75 × the 2.8 m
  minimum run: 14 treads × 200 mm for a 3.0 m floor-to-floor at the 200 mm
  max riser). Preferred 3.15–4.5 m² (the 0.9 m preferred width × 3.5 m
  drawn run, up to landing-inclusive). Not habitable, not
  window-required.
- **T2 — schema/model plumbing.**
  `RoomSpec.storey: int = 1`; `Topology.storeys: int = 1` threaded through
  the loader + all Topology-copy sites (same 7-site trap as
  `ldk_horizontal`); `Room.storey: int = 1` on the solved-layout room.
  `validate_topology` additions: adjacencies same-storey only, except
  `stair_vertical` which must be cross-storey; room storey values within
  range; entry room on storey 1; zone_split same-storey (D7).
- **T3 — solver joint model.**
  Per-storey `AddNoOverlap2D` groups (voids in every group per D5);
  `stair_vertical` adjacencies emit x/y/w/h equality instead of the
  shared-wall disjunction; storey-scope the hardcoded GF-only rules
  (kitchen rear pin, living front pin, LDK arrangement rules, kitchen-side
  symmetry break → storey-1 rooms only); solved rooms carry their storey.
- **T4 — per-storey split + run.py wiring.**
  `split_layout_by_storey(layout)` (GF keeps elements) and
  `storey_view(topology, s)` (rooms/adjacencies/stacks/anchors filtered;
  stair_vertical edges dropped; setback_elements GF-only). In
  `_run_hand_authored`, branch on `topo.storeys > 1`: per-floor validate →
  snap (stairs frozen per D6) → architecturalize → re-validate; issues
  merged with `[GF]`/`[2F]` prefixes; score = sum of floor scores.
- **T5 — renderer composite.**
  `compose_floor_svgs([(title, svg), ...])` in `core/render.py` using
  nested-svg embedding; run.py writes the composite as the single output
  SVG for 2s briefs.
- **T6 — finalize the 2s topology.**
  Retype `stair`/`stairwell` to `stairs`; `aspect_overrides` 4.5 for both
  (0.9 × 3.5 = ratio 3.9 exceeds every stock cap); an always-on
  lot-adjustment profile pinning `stairs` `min_greatest_dim_m: 3.5` /
  `max_least_dim_m: 1.2` (run length is riser math the solver can't
  derive); update the notes (drop "NOT RUNNABLE").
- **T7 — test brief + baseline + regression.**
  `2s_2br_8x12_nw_side_spine_stair_bath_hall_ncp` on the reference's own
  8×12 lot; iterate to COMPLIANT; write baseline; full suite must stay
  green (65 + 1).
- **T8 — docs & memory.** Cross-reference this doc; record the v2
  architecture and any traps found in project memory.

## Out of scope (this phase)

Wet-stack soft proximity (D2); upper-floor setbacks/overhangs & balconies;
U/L-shaped stairs (straight run only); 2s entries in the naming convention
(`bath` token undercount noted in the topology); 2s floor-area bands;
converting the 3 sibling reference specs; AI-pipeline (Claude-composed) 2s
topologies.
