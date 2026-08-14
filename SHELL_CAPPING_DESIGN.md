# Buildable-shell capping via inflated setbacks — design

**Status: FULLY IMPLEMENTED 2026-08-05.** §1a (occupancy-driven setbacks) and
§2-2.7 (shell capping) are both live. This document is now the rationale
record, not a proposal. What actually shipped, and where it differs from the
design as written, is in §8.

---

## 1. Problem

Setbacks today are fixed — 2 m all round (see §1a: not even legal at the
front), 3 m on a carport side for `fcp` —
and the buildable shell is simply lot minus setbacks. Nothing relates the shell
to the size of the program that has to fit inside it, so a generous lot yields
a grossly oversized shell and the solver's post-passes inflate rooms to fill it.

Measured on the current test suite:

```
1s_2br_14.45x17_sq_side_split_bath_pwd_gr_ncp_min
    buildable shell 135.8 m2   vs   sum(preferred-high) 86.5 m2   ratio 1.57
    -> great_room 73.92 m2 (preferred-high 36.0)
    -> master     38.31 m2 (preferred-high 20.0)
```

Note the rooms exceed their preferred-high *caps*: those caps bind the solver's
placement, but `snap_gaps` and `claim_dead_strips` run afterwards and expand
rooms into leftover space. Capping the shell attacks the cause rather than the
symptom — with less surplus, there is less for the post-passes to give away.

**Scope check: only 1 of 51 test briefs is currently oversized.** This catalog
is built around minimum-boundary briefs, so baseline churn will be near zero —
but the regression suite also will not protect this feature. It needs its own
oversized-lot fixtures. The real exposure is the app and AI paths, where lot
dimensions are arbitrary; a 2BR program sums to ~86 m² of preferred-high, so
capping starts to bite around a 13×13 lot, well inside normal PH mid-market
lot sizes.

---

## 1a. PREREQUISITE — occupancy-driven setback minimums (front 2.0 → 3.0)

**STATUS: IMPLEMENTED 2026-08-05.** All six remediation steps below are done;
`run.py --test` 51 pass, `sweep_test.py` 51 pass, and all 49
`setback_below_irr_baseline` suggestions are gone (plans now comply rather
than being measured against a rule the solver ignored). §2 onward shipped the
same day — see §8 for as-built notes and deviations.

**This had to land before the capping work below**, because capping compares
`target_area` against the raw shell, and the raw shell changes for every lot.
Calibrating `SLACK` / `INFLATE_THRESHOLD` against numbers about to shift would
waste the effort.

### The rule

Front setback under PD 1096 depends on residential occupancy class:

| class | front | side | rear | |
|---|---|---|---|---|
| **R-1** low-density single-detached | **4.5** | 2.0 | 2.0 | the strict national standard |
| **R-2** medium-density | **3.0** | 2.0 | 2.0 | **the project default** |
| R-3 / R-4 | 3.0 | 2.0 | 2.0 | |
| R-5 | 6.0 | 3.0 | 3.0 | |

2.0 m is the minimum for **side/rear** yards (PD 1096 Sec. 708(a)), or for
economic housing under BP 220 — **not** for a front yard. Using 2.0 m at the
front, as the whole catalog does today, is not supported by any class.

**We default to R-2 (3.0 m front). The R-1 4.5 m standard is retained in the
table and applies automatically to any brief that declares `occupancy_class:
"R-1"`.**

### It is already in the code — just not wired up

`core/validator.py::SETBACK_MIN_BY_OCCUPANCY` already holds exactly this table
and is already the source of truth for the `setback_below_irr_baseline`
suggestion. But it is referenced in **one place only** (validator.py:167) and
`ai/pipeline.py::_make_default_lot` ignores it entirely, hardcoding 2.0.

That split is why every single run emits
`R-1 front setback 2.00 m is below the IRR Rule VIII Table VIII.2 baseline of
4.5 m` — all 108 briefs declare `occupancy_class: "R-1"` while being built at a
2.0 m front. The solver and the validator disagree about the same rule.

**Implementation: make `SETBACK_MIN_BY_OCCUPANCY` the single source of truth
and have `_make_default_lot` derive minimums from it**, rather than hardcoding
3.0 anywhere. Then switching a brief's class automatically moves its setbacks,
and the suggestion stops firing because the plan actually complies — not
because it was suppressed.

### It must clamp explicit brief setbacks

All 108 briefs declare `"front": 2.0` explicitly, and `Brief.setbacks`
currently wins outright — so changing a default alone would do nothing. A legal
minimum has to floor even an explicit override:

```
front = max(SETBACK_MIN_BY_OCCUPANCY[occ]["front"], specified_front)
```

Otherwise 108 files need hand-editing and any future brief can silently go
sub-legal.

### Measured impact (front 2.0 → 3.0)

- **26 of 51 briefs go infeasible**, across 22 topologies.
- **All 26 are remedied by adding exactly 1.0 m of lot depth** — zero remain
  failing, and **zero `shell_category` flips**. The arithmetic is exact:
  `(depth+1) − (front+1) − rear = depth − front − rear`, so the buildable
  envelope is unchanged.
- **45 of 51 plans come out dimensionally identical**; only the lot rectangle
  around them grows. These are not broken topologies — every canonical minimum
  in the catalog was derived under a 2 m front and is uniformly 1 m short.
- 6 briefs do change room dimensions and want a look (all mid-size, not
  minimums): `1s_2br_11x12_..._ds_ld_fcp`, `1s_2br_11x9_wd_..._hall_gr_ncp`,
  `1s_2br_12x10_wd_front_back_split_bath_hall_ld_ncp`,
  `1s_2br_12x10_wd_side_split_bath_hall_ld_ncp`,
  `1s_2br_12x12_..._ds_ld_fcp`, `1s_3br_13.3x13_..._cl_hall_lk_ncp`.

### Remediation scope

1. Wire `SETBACK_MIN_BY_OCCUPANCY` into `_make_default_lot`, clamping explicit
   setbacks.
2. Switch the project default and all 108 briefs from `R-1` to `R-2`.
3. Add 1.0 m of lot depth to the 26 affected briefs; rename the ones whose
   filenames encode dimensions (`1s_2br_10x10_...` → `1s_2br_10x11_...`).
4. Refresh baselines; re-publish ~30 minimum lot sizes in `CLAUDE.md` (all gain
   1 m of depth).
5. Update the stale comment at `validator.py:162-166`, which currently says
   "almost all PH mid-market subdivisions use a 2.0 m front setback regardless
   of strict R-1 baseline."
6. Record the R-2 default and its basis in
   `data/ph_floorplan_rules.json::global_constraints.setbacks`, whose
   `refinement` block is still marked "TO CONFIRM" and mentions only R-1.

---

## 2. Algorithm

### 2.1 Target area

```
per_storey[s] = sum(preferred_high(room.type) for room in topology.rooms
                    if room.storey == s)
target_area   = max(per_storey.values()) * SLACK        # SLACK = 1.10
```

Two-storey uses the **largest storey, not the sum** — the shell is a footprint.
`SLACK` covers the fact that rectangles do not tile perfectly; 1.10 is a
starting value to be measured, not a fitted one. Every room type in the catalog
has a preferred-high defined (verified), so there is no fallback case.

### 2.2 The minimum shell, and when inflation is allowed at all

The **minimum shell is derived from the lot, not stored per topology**:

```
minimum setback per side:
    SETBACK_MIN_BY_OCCUPANCY[occupancy_class]   # R-2 default: front 3.0,
                                                # side 2.0, rear 2.0  (see §1a)
    ...but at least 3.0 m on the carport side, when a carport is required
       (carport_side may be left / right / FRONT)

raw shell = lot - those minimums
```

**A required carport sets a 3.0 m floor on its side — it is a requirement, not
a preference**, so the clearance is reserved before any capping arithmetic
happens. A front carport therefore has a 3.0 m floor and the 4.5 m front cap
of §2.4 as its ceiling.

This makes today's `fcp` behaviour the default for *any* carport, so `fcp`
stops being a distinct mode. Existing fcp briefs keep their current raw shell
(no change). Existing ccp briefs shift from 2 m + L-notch to a plain 3 m side —
measured cost 4.5–6.5 m² of shell, and all 3 still solve.

**Inflation is permitted only when the raw shell exceeds the target:**

```
if raw_W * raw_D <= target_area:
        no inflation. The raw shell IS the minimum shell for this lot,
        and the plan is solved at whatever size the lot affords —
        down to the minimum floor plan (sum of hard minimums).
```

This is the whole floor condition, and it is structural: inflation only ever
triggers *above* `target_area`, and only ever shrinks *to* `target_area`. Since
`target_area = sum(preferred_high) × SLACK` is by construction well above
`sum(hard_min)`, **a capped shell can never be too small for its program.** No
per-topology minimum needs to be recorded or maintained.

Today 50 of 51 test briefs fall in the no-inflation branch.

### 2.3 Shrink, preserving aspect

```
f      = sqrt(target_area / (raw_W * raw_D))
W', D' = raw_W * f, raw_D * f
```

**Aspect-preserving is a deliberate choice** (the alternative was letting the
shape follow `target_shell`). Reason: `shell_category(lot)` is what selected
this topology in the first place. Distorting the aspect while capping could
produce a shell that no longer suits the topology that was matched to it,
reintroducing the matching problem from a different direction. Preserving the
ratio keeps the capped shell the same *kind* of shell.

This also behaves correctly on wide-and-shallow lots, which was the case that
motivated the question. A 24×14 lot (buildable 20×10 = 200 m², target ~95)
gives f = 0.69 → 13.8 × 6.9; depth sheds 3.1 m and width 6.2 m. A naive
"inflate the front to 4.5 first" rule would instead have driven a 20×10 lot's
depth from 6 m to 3.5 m — an unbuildable house.

### 2.4 Distributing the surplus into setbacks

```
dD = D - D'
  front += min(dD, 4.5 - front)        # front inflates to a 4.5 m CAP
  rear  += remainder

dW = W - W'
  left += dW/2,  right += dW/2         # sides grow equally
```

The 4.5 m front cap is not arbitrary: every validation run in this repo emits
`R-1 front setback 2.00 m is below the IRR Rule VIII Table VIII.2 baseline of
4.5 m`. Inflating the front to 4.5 where the lot can afford it clears a
standing suggestion catalog-wide.

Round all setbacks to the 5 cm solver grid.

### 2.5 Carport

Both carport modes give the car the same 3 m of clearance. They differ only in
**how much of the depth pays for it**:

- **Full 3 m side (today's `fcp`)** — 3 m for the entire depth. Rectangular
  shell, costs `3.0 × depth` of lot.
- **Claimed / L-notch (today's `ccp`)** — 2 m base setback plus a
  `1.0 × 4.0 m` `building_void` at the front corner, giving 3 m only across the
  carport's own 6 m of depth. Costs less shell, at the price of an L-shaped
  footprint.

`ccp` is therefore **retained as the tight-lot fallback**, selected
automatically rather than by the brief:

```
carport required  ->  reserve 3.0 m on carport_side (§2.2)
    shell still viable?   full 3 m side, strip the building_void, no L-notch
    too tight?            fall back to 2.0 m on that side + the ccp L-notch,
                          recovering (depth - 4) m2 of shell
```

So the L-notch survives only for lots that cannot afford 3 m across the full
depth — exactly what it was invented for. A brief that says `ccp` on a generous
lot silently resolves to a plain 3 m setback carport, and one that says `fcp`
on a lot too tight for it silently falls back to the L-notch. The brief states
the *requirement* (a carport, on this side); the runner picks the mechanism.

Verified: all 3 existing `_ccp` test briefs solve on the full-3 m path,
costing only 4.5–6.5 m² of shell.

### 2.6 Infeasibility fallback — a narrow safety net

Per §2.2 the capped shell can never be too small *by area*. The one residual
risk is **shape**: aspect-preserving shrink on a very elongated lot could leave
a width or depth below what a topology needs, even with sufficient area.

No per-topology minimum needs to be recorded to handle this (and none exists —
verified: the only shell-related fields across all 48 topologies are
`target_shell`, `lot_adjustment_profiles`, `fallback_topology` and
`fallback_below_buildable_sqm`; published minimums live in `CLAUDE.md` prose
and brief intent strings only). Instead use **retry-on-infeasibility**, the
idiom this codebase already uses for `preferred_apply`:

```
solve with the capped shell
  -> infeasible? re-solve with the raw uncapped shell
                 and emit a `shell_cap_dropped` warning
```

Self-correcting, needs no new per-topology data, consistent with the existing
`tiered_preferred_dropped` pattern — and now a narrow safety net for the shape
case rather than the primary floor mechanism.

### 2.7 Deadband

Inflating when the surplus is trivial (raw shell 1.02× target) would move
setbacks by centimetres and churn baselines for no design benefit. Require a
minimum surplus before inflating at all:

```
if raw_area <= target_area * INFLATE_THRESHOLD:   no inflation
```

`INFLATE_THRESHOLD` = 1.05 proposed — measure alongside `SLACK`.

---

## 3. Override precedence

1. **`Brief.setbacks` explicit** — wins outright, disables inflation entirely.
   This already exists and is used for firewall configs.
2. **`Brief.shell_inflation: {front, rear, left, right}`** (new, optional,
   partial) — any side given is pinned to that value; the remaining sides
   absorb what is left by the rules above. This is the "place the shell
   precisely on a bigger lot" case.
3. **Neither given** — full auto-inflation per §2.

---

## 4. Architecture

`ai/pipeline.py::_make_default_lot(brief)` is the single definition (confirmed
by grep — `run.py` and `ai/match.py` both import it, so there is no
thread-through-every-copy-site trap here, unlike `ldk_horizontal` /
`claim_dead_strips`).

It cannot simply be modified in place, because capping needs the **topology**
(to sum preferred-high) while `ai/match.py` calls it **without** one, to
compute `shell_category` for candidate matching. Making the lot
topology-dependent would make matching circular.

Resolution — two lots, clearly named, never one mutated in place:

```
_make_default_lot(brief)                  # RAW: unchanged. Classification,
                                          # shell_category, topology matching.
_make_capped_lot(brief, topology, rules)  # NEW: solving only.
```

Call site is the runner (`run.py::_run_hand_authored` / `_run_ai`), after the
topology is known and before `solve()`.

---

## 5. Risks

| risk | mitigation |
|---|---|
| Capped shell too small by AREA | structurally impossible — inflation only triggers above `target_area` and shrinks only to it (§2.2) |
| Capped shell wrong SHAPE on an elongated lot | retry-on-infeasibility + `shell_cap_dropped` warning (§2.6) |
| `SLACK` too tight → widespread infeasibility | start 1.10, measure across the suite and an oversized-lot sweep before locking |
| Trivial surplus causes pointless setback churn | `INFLATE_THRESHOLD` deadband (§2.7) |
| ccp briefs shift from 2 m + L-notch to a plain 3 m side | measured: costs 4.5-6.5 m2, all 3 still solve; they re-baseline. fcp briefs are unaffected (3 m was already their behaviour) |
| `carport_type` becomes redundant as a brief field | brief states the requirement (carport + side); runner picks full-3 m vs L-notch. Keep the field as a hint or retire it — see Open items |
| ccp void geometry assumes a 2 m base setback (`width_m: 1.0` = "1 m beyond") | void only ever applies on the un-inflated path, where the base really is 2 m |
| Setback elements (lanai, dirty kitchen, service area) sized off the setback rect | bigger rear setback is strictly more room; verify `setback_elements.py` does not stretch them to fill |
| Regression suite will not exercise it (1/51 briefs) | add oversized-lot fixtures as part of the change |
| Interacts with the room-sizing decision still open | orthogonal in practice — capping only affects oversized lots, which comfortably clear any proposed kitchen floor |

---

## 6. Test plan

1. **No-op proof.** All 51 existing briefs unchanged except
   `1s_2br_14.45x17_..._min`. Compare by **element multiset**, not bytes — these
   SVGs are one line and up to 13 files reshuffle between runs (see `TESTING.md`).
2. **The oversized brief.** `14.45x17` should shed ~50 m² of shell; check
   great_room and master land at or under their preferred-high.
3. **New oversized fixtures** — at least one per shell category (narrow /
   squarish / wide) at roughly 1.5× the program's preferred-high area.
4. **Carport matrix** — ccp on a tight lot (expect L-notch retained) and ccp on
   a generous lot (expect normal setback carport, void stripped).
5. **Override matrix** — explicit `setbacks`, partial `shell_inflation`, and
   neither.
6. **Front-setback suggestion** should disappear on every brief where the front
   reaches 4.5.

---

## 7. Open items

- `SLACK` = 1.10 and `INFLATE_THRESHOLD` = 1.05 are starting values, to be measured together.
- 2-storey carports are often **inside** the ground-floor footprint, roofed by
  the storey above, rather than an open setback element. That is a different
  construct from a setback carport and interacts with capping (it would be
  inside the shell, not outside). Explicitly deferred — see `CLAUDE.md`
  Open/deferred.
- `carport_type` (`ccp`/`fcp`) is now **derived, not declared** — the runner
  picks the mechanism from what the lot can afford. Decide whether to retire
  the Brief field, keep it as an override/hint for forcing one mode, or keep
  it only for naming test fixtures (`_ccp` / `_fcp` filename tokens).
- A FRONT carport has a 3.0 m floor (§2.2) and a 4.5 m ceiling (§2.4). Confirm
  that band is intended, and what happens if the lot cannot afford 3 m at the
  front — front has no L-notch equivalent.

---

## 8. As-built notes (2026-08-05)

**Where it lives.** `ai/pipeline.py` gains `topology_target_area()`,
`capped_setbacks()` and `make_capped_lot()`; `run.py::_run_hand_authored` calls
`make_capped_lot` after the topology is loaded and the carport transforms have
run. `_make_default_lot` is unchanged and still topology-free, so
`ai/match.py`'s `shell_category` call cannot go circular.

**Deviations from the design above.**

1. **§2.6's infeasibility retry was not built.** Per §2.2 the capped shell can
   never be too small by AREA, and no shape-driven failure has been observed.
   Add it (and the `shell_cap_dropped` warning) the first time a capped solve
   goes infeasible — do not assume it is there.
2. **Override precedence forced a data change.** All 101 briefs carried
   `setbacks: {2,2,2,2}` — boilerplate restating the pre-2026-08-05 default,
   zero of them deliberate. Under §3 that counted as "brief is in control" and
   **disabled capping catalog-wide** (first build: 0 briefs capped). Those
   blocks were stripped; briefs now derive setbacks from occupancy class.
   `Brief.shell_inflation` exists and is honoured but has no user yet.
3. **`carport_type` was NOT retired** (§7 open item). `fcp` still exists and
   still forces 3 m on the carport side; ccp remains the tight-lot L-notch.

**Measured effect.** On the only oversized brief in the suite,
`1s_2br_14.45x18_sq_side_split_bath_pwd_gr_ncp_min`:

```
shell   125.4 -> 95.6 m2   front 3.0->4.5 (cap)  rear 2.0->2.05  sides 2.0->2.65
master   38.31 -> 19.80    (was ~2x its 20.0 preferred-high cap; now under it)
kitchen   6.03 ->  7.20    (meets the 7.0 preferred-low)
great    73.92 -> 51.97    STILL OVER its 36.0 cap
```

**The great_room case is only half-solved.** `SLACK = 1.10` leaves 10% surplus
and `snap_gaps`/`claim_dead_strips` funnel all of it into a single room, so the
largest public room still overruns its preferred-high. Tightening `SLACK` or
bounding post-pass expansion is the remaining work. Both `SLACK` and
`INFLATE_THRESHOLD` remain unfitted starting values, and **only 1 of 51 briefs
exercises the feature at all** — the oversized-lot fixtures from §6 are still
owed.
