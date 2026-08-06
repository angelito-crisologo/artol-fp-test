# Room sizing tiers & the preferred-low cliff — investigation + prototype

Status as of **2026-08-05**: investigation complete, values changed (§7), and
the **graded credit is now ADOPTED and ON BY DEFAULT** (§8) — concave shape,
zero anchor, `STEP_DIV` 8.

§1-§4 below describe the state *before* those changes and are kept as the
rationale record — the measurements are what justified the decisions. Read §7
first for what is true now.

Read this before touching room-size numbers in the rules catalog or the
sizing terms in `solver/solver.py`'s objective.

---

## 1. What the tiers actually are

`data/ph_floorplan_rules.json` declares a THREE-step `sizing_policy.progression`:

```json
"progression": ["preferred", "relaxed_minimum", "hard_minimum"]
```

**The middle tier is declared but never read.** `core/rules.py` exposes only
`hard_min_area()`, `hard_min_least()` and `preferred_area_range()`. Nothing
reads `soft.min_area_sqm` or `soft.min_dimensions_m` — `min_dimensions_m`
appears in zero Python files in the repo. What the solver implements is:

| tier | source | enforced as |
|---|---|---|
| hard minimum | `room_catalog[].hard` | hard constraint (PD 1096) |
| *relaxed minimum* | `room_catalog[].soft.min_*` | **declared, not implemented** |
| preferred-low | `soft.preferred_area_sqm[0]` | soft — reified bool in the objective |
| preferred-high | `soft.preferred_area_sqm[1]` | **hard area cap**, not an aspiration |

Note preferred-high is a CAP. Only `set_max_area_sqm` can raise it;
`max_area_sqm` can only lower it.

A second, unrelated two-tier system also uses the word "preferred":
`lot_adjustment_profiles`' `auto_apply` (always on) and `preferred_apply`
(tried first, dropped on infeasibility with a `tiered_preferred_dropped`
warning). That one does the real per-shell tuning work in this catalog. The
two systems are easy to confuse in code review.

### The relaxed tier is not merely unimplemented — it is inconsistent

Only 9 of 20 room types define it, and the ordering it promises
(hard ≤ relaxed ≤ preferred) holds for just 3:

| room type | hard | relaxed | pref-low | |
|---|---|---|---|---|
| living_room | 6.0 | 12.0 | 16.0 | genuine middle tier |
| common_bath | 1.2 | 2.6 | 3.0 | genuine, tiny |
| ensuite_bath | 1.2 | 2.8 | 3.0 | genuine, tiny |
| master_bedroom | 6.0 | 12.0 | 12.0 | collapsed |
| dining_room | 6.0 | 10.0 | 10.0 | collapsed |
| powder_room / maids_bath | 1.2 | 1.4 | 1.4 | collapsed |
| **bedroom_standard** | 6.0 | **10.0** | **9.0** | **inverted** |
| **kitchen** | 3.0 | **8.0** | **6.0** | **inverted** |

The inversions have a cause, visible in the catalog's own `source` fields:
*"min_dimensions_m and min_area_sqm set to client preferred minimums
(2026-06-25)"*. That change raised `soft.min_area_sqm` to the client's numbers
without touching `preferred_area_sqm`, so for the two types where the client
wanted MORE than the old preferred, the two crossed over.

**Consequence: the 2026-06-25 client direction has never bound on anything.**
Measured across the full suite, 77% of realized kitchens sit below the client's
8.0 m², median exactly 6.0 (the preferred-low). No validator suggestion fires
until a kitchen drops under 6.0, so the 8.0 ask is invisible in the output.

Deleting the relaxed tier is therefore a decision that the directive is void —
not a schema cleanup. That decision is still open.

---

## 2. Why raising a target backfires: the cliff

`solver/solver.py`'s objective:

```python
BIG = EW * EH                                  # ~max grid area
terms.append(area[r.id] * w)                   # continuous, small
terms.append(meets_pref[r.id] * BIG * w)       # STEP, huge
```

`meets_pref` is a reified bool (`area >= preferred-low`, or not). A room either
clears the bar and collects `BIG*w`, or collects nothing but the tiny
continuous term.

**So a room that CANNOT reach its target has almost no incentive to get close,
and the solver strips its area to push some other room over ITS cliff.**

Measured, raising `bedroom_standard` 9.0 → 10.0 and `kitchen` 6.0 → 8.0
together, inside a fixed envelope on `1s_1br_8x10_nw_front_back_split_bath_gr`:

```
kitchen   6.00 -> 9.00   (+3.00)   crosses its new 8.0 cliff
bedroom   9.00 -> 6.00   (-3.00)   funds it — lands on the PD 1096 legal floor
```

The bedroom had been sitting exactly at the old 9.0 preferred-low collecting
its bonus. Raising the target to 10.0 — unreachable on an 8×10 lot — turned
that 3 m² into free currency.

### Kitchen-only is not safe either

Isolating the kitchen raise (bedroom left at 9.0) stops the bedroom collapse —
the bedroom keeps its bonus, so the solver refuses to fund the kitchen out of
it. But measured across **all 51 briefs** (not a sample), the kitchen raise on
its own still redistributes rather than improves:

| | before | after |
|---|---|---|
| kitchens grew | — | 7 |
| kitchens **shrank** | — | **6** |
| total kitchen area | 342.2 | 346.8 (+4.6) |
| meets 8.0 | 14 | 18 |
| **below 6.0** (the old target) | **21** | **25** |

The +4.6 is one topology (`2s_3br_12x10_wd_rear_stair` alone contributes
+7.70); strip it and the change is **−3.1 m²** across everything else. Worst
regressions:

```
-2.71   6.12 -> 3.41   1s_2br_16x12_sq_side_split_bath_pwd_gr_ncp
-1.81   9.90 -> 8.09   1s_2br_10x14_nw_side_corridor_baths_ds_hall_ncp
-1.50   6.00 -> 4.50   1s_3br_13.5x14.5_sq_hall_core_baths_ds_hall_gr_ccp
-1.49   6.03 -> 4.54   1s_2br_14.45x17_sq_side_split_bath_pwd_gr_ncp_min
```

A 16×12 lot — one of the roomiest in the suite — drops its kitchen to
**3.41 m², barely above the 3.0 legal floor**.

> **Methodology warning.** An earlier pass sampled every 3rd brief and reported
> "4 grew, 0 shrank". The sample happened to exclude every loser. Sizing
> changes must be measured on the FULL suite.

---

## 3. The prototype: graded preferred credit

Built in `solver/solver.py`, three hooks, **all gated, default OFF**:

- `pref_progress[r] = min(area, preferred-low)` — an IntVar for progress toward
  the target
- objective pays that progress over `0..preferred-low`, scaled so **reaching the
  target scores exactly what the old cliff scored** (rooms already meeting
  their target are unaffected by construction)
- a residual step `BIG//GRADED_STEP_DIV · w` so exactly meeting still beats
  just missing

```bash
ARTOL_GRADED_PREF=1                      # enable (default off)
ARTOL_GRADED_SHAPE=linear|concave        # credit shape (default linear)
ARTOL_GRADED_STEP_DIV=8                  # residual step = BIG//N
ARTOL_KNEE_POS=2/3  ARTOL_KNEE_VAL=4/5   # concave knee
ARTOL_KNEE_ANCHOR=band|zero              # what the knee position is measured from
```

### Linear grading: one slope, two jobs

A straight ramp has to both stop collapse near the hard floor AND stop drift
near the target. Tuning the residual step just trades one for the other:

| variant | kitchen | bed_std | kit@3.0 floor |
|---|---|---|---|
| **A** cliff, kit 6.0 *(today)* | 342.2 | 549.0 | 4 |
| **C** cliff, kit 8.0 | 346.8 | 546.7 | 4 |
| **D** linear div=8, kit 8.0 | 355.9 | **537.9** | **2** |
| **E** linear div=2, kit 8.0 | 356.6 | **545.2** | **4** |

D protects the floor and loses 11 m² of bedrooms; E protects bedrooms and gives
the floor protection back.

### Concave grading: the trade was an artifact of the shape

A concave piecewise-linear function is the pointwise MINIMUM of its segment
lines, so it needs no new machinery — bound the credit var by both lines and
let the maximizer settle on the lower one. Verified independently: equals the
old cliff exactly at the target, 0 at 0, concave throughout, **4× the marginal
value near the floor**.

| variant | kitchen | bed_std | kit@3.0 | hall_core | 16×12 |
|---|---|---|---|---|---|
| **A** *(today)* | 342.2 | 549.0 | 4 | 6.00 | 6.12 |
| **D** linear d8, kit 8.0 | 355.9 | 537.9 | 2 | 5.80 | 6.75 |
| **F** concave zero-anchor, kit 8.0 | 346.8 | **546.0** | **2** | 4.50 | 5.83 |
| **I** concave band 1/2, kit 8.0 | 349.8 | 538.8 | 2 | **5.80** | 5.83 |
| **J** concave band 2/3, kit 8.0 | 352.2 | 538.9 | 2 | **5.80** | 5.83 |
| **K** concave band 3/4, kit 8.0 | 352.8 | 539.5 | 2 | **5.80** | 6.75 |

**F clears both aggregate criteria at once** (floor ≤ 2 AND bedrooms ≥ 545),
which no linear config can. Kitchen-floor protection and bedroom area were NOT
competing for the same square metres — one slope was doing two jobs badly.

### Knee anchoring

F still left `1s_3br_13.5x14.5_sq_hall_core` at 4.50 (today: 6.00). Cause,
measured directly: with the knee at 1/2 of an 8.0 target it sits at **4.0 m²,
only 1 m² above the 3.0 hard floor**, so a kitchen at 4.50 has already banked
82.5% of the credit and moving to 5.80 earns just 6.5% more. Linear earned
16.3% for the same move, which is why linear bothered.

Fix: measure the knee inside the **usable band** `[hard-min .. preferred-low]`
rather than from zero (`ARTOL_KNEE_ANCHOR=band`, now the default when concave
is on). Marginal credit for that same 4.50 → 5.80 move:

```
zero  1/2 :  6.5%      band 2/3 : 17.3%
band  1/2 : 13.3%      band 3/4 : 19.5%      (linear: 16.3%)
```

Band anchoring repairs `hall_core` to 5.80 in every config — but costs ~7 m²
of bedroom area, so I/J/K fail the bedroom criterion that F passes.

**No configuration passes all three** (floor ≤ 2, bedrooms ≥ 545, hall_core
repaired) with the kitchen target at 8.0.

### Shape change alone, no target raise

| variant | kitchen | bed_std | master | kit@3.0 | net |
|---|---|---|---|---|---|
| **A** cliff *(today)* | 342.2 | 549.0 | 522.0 | 4 | — |
| **H** concave zero-anchor, kit 6.0 | 344.3 | 544.7 | 524.3 | **2** | **+4.1** |
| **L** concave band 2/3, kit 6.0 | 344.8 | 539.3 | 520.1 | 2 | −6.0 |

**H is the only configuration that improves on today without any target
change**: hard-floor kitchens halved, +4.1 m² net. Note the anchor preference
INVERTS here — band anchoring helps when a target is raised and hurts when it
isn't.

---

## 4. Where this leaves it

- The cliff is real, diagnosed, and reproducible; both target-raise failures
  trace to it.
- Concave grading demonstrably improves the frontier. **H** (concave,
  zero-anchor, no target change) is the strongest adoption candidate.
- Adopting any of it is a **catalog-wide geometry change** — 80 of 203 tracked
  rooms move under H alone — so it means refreshing most baselines and a full
  `artol-topologies/` regen.
- The knee (position, value, anchor) is **untuned** beyond the four points
  above. They were hand-picked, not fitted.
- Raising `kitchen` or `bedroom_standard` to the client minimums is **still not
  safe**, even with grading. The honest options remain: adopt grading first and
  re-test, change the room program, or accept that the client minimums don't
  fit the shells this catalog targets.

## 5. Reproducing

```bash
cd floorplan_v1 && source ../.venv/bin/activate
python3 run.py --test                                    # baseline, 51 pass
ARTOL_GRADED_PREF=1 ARTOL_GRADED_SHAPE=concave \
  ARTOL_KNEE_POS=2/3 python3 run.py --test               # prototype
```

Compare SVGs by **element multiset**, not bytes — these SVGs are emitted as a
single line, so a naive line-diff cannot detect reordering, and up to 13 files
reshuffle between runs with byte-identical inputs. See `TESTING.md`.

Unrelated pre-existing issue found along the way:
`2s_2br_9.5x9.5_sq_l_landing_stair_bath_gr_ncp` differs from its own committed
baseline under unmodified code, so that baseline is stale and currently
protects nothing.

---

## 7. What actually changed (2026-08-05, after this investigation)

**Tiers rationalised to the three the code implements.**
`sizing_policy.progression` is now
`["hard_minimum", "preferred_low", "preferred_high"]`, and the dead
`relaxed_minimum` tier (`soft.min_area_sqm` / `min_dimensions_m`) was removed
from every room type. Its unapplied 2026-06-25 client minimums are recorded in
the progression note rather than silently deleted. §1's "declared but not
implemented" finding is therefore resolved.

**Values changed:**

| room type | minimum | preferred-low | preferred-high |
|---|---|---|---|
| kitchen | 3.0 | **6.0 → 7.0** | 12.0 |
| maids_room | 6.0 | **6.0 → 8.0** | 9.0 |
| bedroom_standard | 6.0 | 9.0 (held) | 12.0 |

`bedroom_standard` was deliberately NOT raised to its client minimum of 10.0 —
§2 measured that at 28 of 51 briefs infeasible.

**The kitchen raise reproduced this document's own prediction.** Measured in
isolation (front setback held constant), 6.0 → 7.0 gave:

```
4 kitchens grew, 7 shrank      total kitchen area  -7.4 m2
kitchens below 6.0   25 -> 30  at the 3.0 hard floor  4 -> 5
worst: 1s_2br_16x12_sq_side_split_bath_pwd_gr  6.02 -> 3.00
```

It shipped because it was an explicit decision after the risk was flagged
twice — not because the risk went away. **The concave graded-credit prototype
(§3) is the fix**: it was the only configuration measured to protect hard
floors and bedroom area simultaneously. It is still default-off, its knee is
still unfitted, and adopting it moves ~80 of 203 tracked rooms.

**Preferred-high gained a second job.** It now also drives buildable-shell
capping — `sum(preferred_high) × 1.10` is the target shell area
(`SHELL_CAPPING_DESIGN.md` §2). So changing any preferred-high value now moves
BOTH room caps and shell sizing. That coupling is why the sizing values had to
be settled before capping was calibrated.

---

## 8. ADOPTED (2026-08-05) — graded credit is now the default

`solver/solver.py` defaults flipped: `GRADED_PREF` **on**, `GRADED_SHAPE`
**concave**, `GRADED_KNEE_ANCHOR` **zero**, `GRADED_STEP_DIV` 8. Set
`ARTOL_GRADED_PREF=0` to get the old all-or-nothing step back.

**Re-measured first, and the answer changed.** Every number in §3 was taken
under a 2 m front setback, kitchen target 6.0/8.0, and no shell capping — all
three have since changed. Re-run against the shipped state:

| variant | fail | total m² | Δ | rooms at hard-min | kitchens @3.0 |
|---|---|---|---|---|---|
| OFF (the old step) | 0 | 2582.2 | — | 20 | 5 |
| **concave, zero anchor, d8** | 0 | 2581.6 | **−0.6** | **12** | **2** |
| concave, band anchor, d8 | 0 | 2577.3 | −5.0 | 13 | 2 |
| concave, band anchor, d2 | 0 | 2577.9 | −4.4 | 16 | 4 |
| linear, d8 | 0 | 2580.5 | −1.7 | 13 | 2 |

**Rooms pinned at their hard minimum: 20 → 12**, at essentially zero total-area
cost. That is the defect this whole investigation was about — rooms being
stripped to the legal floor to fund another room's step.

**The anchor preference FLIPPED.** §3 concluded band-anchoring won; against the
shipped state, zero wins on both metrics. Nothing about the reasoning in §3 was
wrong — the state it was measured against no longer exists. **Re-measure before
changing the knee or anchor; this preference has already inverted once.**

**What it did not fix.** The kitchens damaged by the 7.0 raise are *improved*
but not all restored: `1s_2br_16x12` went 3.00 → 4.20 (band anchor would have
given 5.03, at the cost of 5 m² elsewhere), and
`1s_1br_9x12_nw_front_back_split_bath_ld` stays at 5.00 in every variant —
that one is a genuine shell constraint, not a cliff artifact. Grading raises
the floor; it does not manufacture area.

25 of 51 baselines refreshed; catalog regenerated.
