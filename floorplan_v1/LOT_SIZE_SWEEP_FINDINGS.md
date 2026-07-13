# Lot-size sweep findings — squarish 2BR topology catalog

**Date:** 2026-07-13
**Script:** `lot_size_sweep.py` (repo root of `floorplan_v1/`) — regenerate with
`python3 lot_size_sweep.py` from `floorplan_v1/`. Raw per-run data lands in
`output/lot_size_sweep_raw.json` and a full result table in
`output/lot_size_sweep_report.md` (both gitignored/regenerated, not durable —
this file is the curated summary meant to be kept).

## Method

- All 6 current squarish 2BR topologies (`floorplan_v1/topologies/1s/2br/squarish/`).
- ncp (no carport), symmetric 2 m setbacks on all sides — the baseline case.
- Three width/depth ratios: **1.00** (square, 0.5 m step), **0.85** and **1.15**
  (near-square rectangles, 1.0 m step). Depth swept 8–20 m.
- A combo only counts if its *buildable envelope* (lot minus the 2 m setbacks)
  falls in the `squarish` shell category — envelope aspect ratio in
  [0.80, 1.30), per `core/model.py::shell_category`. Combos outside that are
  skipped, not scored as failures.
- "Works" = the solver finds a feasible layout **and** the validator reports
  zero hard errors (same bar `_run_hand_authored` already enforces).

## Square lots (ratio 1.00)

| Topology | Smallest that solves | Infeasible again above | "Clean" range (0 warnings) |
|---|---|---|---|
| `bath_gr` | 10.5×10.5 m (42 m² floor) | 15.0×15.0 m | never fully clean — 1 warning throughout |
| `bath_pwd_gr` | 10.0×10.0 m (36 m²) | 16.5×16.5 m | 12.5×12.5 – 15.0×15.0 m |
| `baths_cl_gr` | 11.5×11.5 m (56 m²) | 18.0×18.0 m | 12.5×12.5 – 15.0×15.0 m |
| `baths_cl_hall_gr` | 9.5×9.5 m (30 m²) | 18.5×18.5 m | 11.0×11.0 – 16.0×16.0 m |
| `baths_ds_gr` | 11.0×11.0 m (49 m²) | 15.5×15.5 m | 12.0×12.0 – 15.0×15.0 m |
| `baths_ds_ld` | 11.0×11.0 m (49 m²) | **13.0×13.0 m** | never clean — 2–3 warnings throughout |

**Catalog-wide safe minimum** (works for all 6): **11.5×11.5 m** (the
most demanding topology, `baths_cl_gr`).

**`baths_ds_ld` is an outlier** — its feasible window (11.0×11.0 to 12.5×12.5
only) is far narrower than the other five, and it never solves without
warnings. Worth a closer look at that topology specifically before treating
it as interchangeable with its siblings across the same lot range.

Feasibility is **not monotonic** at the high end for several topologies
(`bath_gr`, `bath_pwd_gr`, `baths_ds_gr`) — they go infeasible, then pass
again one grid step larger, before failing for good. Confirmed as genuine
CP-SAT behavior against the topologies' fixed `max_area_sqm` room caps
(a narrow acceptable total-room-area window relative to envelope area at
certain sizes), not a sweep-script artifact.

## Near-square rectangles (ratio 0.85 and 1.15)

| Topology | ratio 0.85 min feasible | ratio 1.15 min feasible |
|---|---|---|
| `bath_gr` | 14.45×17.0 m (136 m²) | 11.5×10.0 m (45 m²) |
| `bath_pwd_gr` | 14.45×17.0 m (136 m²) | 11.5×10.0 m (45 m²) |
| `baths_cl_gr` | 14.45×17.0 m (136 m²) | 13.8×12.0 m (78 m²) |
| `baths_cl_hall_gr` | 14.45×17.0 m (136 m²) | 11.5×10.0 m (45 m²) |
| `baths_ds_gr` | 14.45×17.0 m (136 m²) | 12.65×11.0 m (61 m²) |
| `baths_ds_ld` | no feasible point tested | 12.65×11.0 m (61 m², only point tested that passes) |

**Key finding: the minimum feasible size at ratio 0.85 is dramatically
higher than at ratio 1.00** — not because the room program needs more
space, but because the fixed 2 m setback on all sides distorts the
*envelope* ratio away from the *lot* ratio at small sizes. A 10×11.8 lot
(ratio 0.85) has a 6×7.8 envelope — ratio 0.77, just outside the squarish
band (0.80–1.30) — so it gets excluded from "squarish" entirely before the
solver ever runs, regardless of whether the topology could handle it. This
distortion shrinks as lot size grows (the fixed −4 m matters proportionally
less), which is why ratio 0.85 only starts qualifying as squarish around
14–17 m. Ratio 1.15 is much less affected (closer to square, smaller
distortion), so its minimums track fairly close to the square numbers.

**Practical implication:** for non-square-but-squarish lots noticeably
deeper than wide (ratio ~0.85), don't expect these topologies to be usable
below roughly 14×17 m — well above where a same-area square lot would work.
Wider-than-deep lots near ratio 1.15 behave much closer to square.

## Floor-area / 3BR knee

Every squarish topology crosses the locked 2BR→3BR floor-area band knee
(~80 m², see project memory `floor-area-per-br`) at exactly **13.0×13.0 m**
(81 m² floor) on a square lot — pure geometry (env = lot − 4 m), identical
for all six topologies, not solver-dependent. Recommended 2BR ceiling:
**~13×13 m / 81 m² floor**, even though most topologies keep technically
solving well past that (up to 15–18.5 m depending on topology).

## Recommendations

- Treat **11.5×11.5 m** as the safe minimum square lot across the whole
  squarish 2BR catalog; below that, only some topologies (e.g.
  `baths_cl_hall_gr`, down to 9.5×9.5 m) still work.
- Treat **~13×13 m (81 m² floor)** as the practical 2BR ceiling regardless
  of continued solver feasibility — past that, offer a 3BR program instead.
- Flag `baths_ds_ld` for review — much narrower feasible band than its
  siblings, and never solves warning-free.
- For deep-not-wide lots (ratio ≲0.85), expect the usable range to start
  much higher (~14×17 m) than the equivalent-area square lot, due to the
  fixed-setback distortion described above — this is a shell-classification
  effect, not a room-program limitation.
