# PH floor-plan fixture library

55 furniture and fixture symbols for Philippine house plans, drawn as
plain SVG in metres. Each symbol has a matching `.json` record describing how
it may be placed and what clearance it needs.

Nothing here imports or depends on any code. It is a drawing library plus data.

Open **`contact-sheet.html`** to see every symbol — large, and again at 42 px
per metre, which is the scale the plans actually render at. That second view is
the one worth trusting: a symbol that turns to mush at 42 px/m is not finished,
however good it looks blown up.

## The convention, in one paragraph

Every symbol is drawn in **metres**, in its own local space. The wall the
fixture backs onto is at **y = 0** — the top of the picture when you open the
file. The fixture **faces +y**, into the room. The origin is the **back-left
corner of the footprint**. That is the whole convention, and it is what lets a
single transform place any symbol anywhere:

```
translate(px, py) scale(S, -S) rotate(θ)
```

where `S` is pixels per metre and `θ` is 0 / 90 / 180 / 270. That one transform
carries the metre-to-pixel conversion and the y-flip together, so nobody
drawing a symbol ever has to think in pixels or in flipped coordinates.

Two rules that will bite if ignored:

- Keep `vector-effect="non-scaling-stroke"` on stroked elements. Without it,
  every line multiplies by `S` and a 0.9 px outline becomes a 38 px slab. It is
  already set on every element in every file. Browsers and resvg honour it;
  CairoSVG historically does not, so if you rasterise with CairoSVG, scale
  stroke widths by `1/S` instead.
- **Rotation is orthogonal only.** Angled furniture buys nothing in PH
  developer plans and breaks the rectangle model that makes fit-checking
  possible in the first place. Handed pieces mirror with `scale(-1, 1)` about
  the footprint centre — the `handed` flag says which ones.

## viewBox is not always the footprint

Some symbols legitimately draw outside their own box: dining chairs sit around
the table, a fridge door swings into the room. For those, the viewBox is larger
than the footprint and the manifest's `origin` gives where the footprint's
back-left corner sits inside it. When `origin` is `(0, 0)` and `viewbox` equals
`footprint`, there is no overhang.

This is deliberate rather than sloppy. The chairs around a dining table are
drawn where they physically are, which happens to be in the clearance zone —
and seeing that overlap is exactly how you notice a dining room is too tight.

## Not every footprint is a rectangle

Three symbols would be misread by anything that assumes one:

- **Round dining tables.** A ⌀1.35 m table is not a 1.35 × 1.35 m obstruction —
  the corners of that square are free floor. That is the round table's actual
  advantage on a squarish dining room.
- **The L-shaped sofa.** `w` and `d` give only the bounding box; `footprint.cells`
  gives the two rectangles it really occupies. The inner corner of the L is
  free floor, and it is where the coffee table goes.

Check `footprint.shape` before treating `w × d` as solid.

## The manifest

Each `<id>.json` carries:

| field | means |
| --- | --- |
| `footprint` | the space the fixture actually occupies, in metres, plus `shape` and `cells` |
| `footprint.shape` | `rect`, `circle` or `L` |
| `footprint.cells` | only for `L`: the rectangles actually occupied. `w`/`d` are then just the bounding box |
| `viewbox` / `origin` | the drawing extent, and where the footprint sits in it |
| `anchor` | `wall_back` (one wall behind), `corner` (two walls meeting at the origin), `free` (sits anywhere), `center` (positioned by its middle) |
| `must_back_wall` | whether a wall behind it is required, not just preferred |
| `needs_plumbing_wall` | whether it drives which wall is wet |
| `handed` | whether mirroring produces a different, valid piece |
| `stretch` | for wall runs: axis, min, max, repeat unit, and how to extend |
| `clearance` | list of `{side, depth, reason}` — the floor that must stay clear |
| `rooms` | room types this belongs in, matching the topology room vocabulary |

`clearance` sides are given in **local space**: `front` is +y (into the room),
`back` is −y, `left` is −x, `right` is +x. They rotate with the symbol.

The `reason` string on each clearance entry is there on purpose. A clearance
that cannot be explained in plain words is usually a number someone copied.

## Contents

Tier 1 is what a plan needs before it reads as finished (30
symbols). Tier 2 is the Philippine-specific set — dirty kitchen, service area,
tabo, water tank (23 symbols). Tier 3 is a couple of extras drawn
while nearby (2).

### Bedroom

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `bed_double` | Double bed | 1.37 × 1.9 | 1 | |
| `bed_king` | King bed | 1.83 × 2.03 | 1 | |
| `bed_queen` | Queen bed | 1.52 × 2.03 | 1 | |
| `bed_single` | Single bed | 0.91 × 1.9 | 1 | |
| `nightstand` | Nightstand | 0.45 × 0.4 | 1 | |
| `wardrobe` | Wardrobe / closet | 1.2 × 0.6 | 1 | _stretch 0.9–2.4 m_ |
| `cabinet_small` | Small cabinet | 0.6 × 0.5 | 2 | |
| `wic_unit` | Walk-in closet unit | 1.2 × 0.6 | 2 | _stretch 0.6–3.0 m_ |

### Bath & toilet

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `lavatory` | Lavatory (counter basin) | 0.55 × 0.45 | 1 | _plumbing_ |
| `shower_stall` | Shower stall | 0.9 × 0.9 | 1 | _plumbing_ |
| `toilet` | Water closet | 0.4 × 0.7 | 1 | _plumbing_ |
| `floor_drain` | Floor drain | 0.15 × 0.15 | 2 | _free-standing, plumbing_ |
| `lavatory_pedestal` | Lavatory (pedestal) | 0.48 × 0.42 | 2 | _plumbing_ |
| `tabo_set` | Tabo and pail set | 0.45 × 0.45 | 2 | _plumbing_ |
| `water_heater` | Water heater (wall) | 0.35 × 0.25 | 2 | _plumbing_ |
| `bathtub` | Bathtub | 1.7 × 0.75 | 3 | _plumbing, handed_ |

### Kitchen

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `fridge` | Refrigerator | 0.7 × 0.7 | 1 | _handed_ |
| `kitchen_counter` | Kitchen counter run | 2.4 × 0.6 | 1 | _plumbing, stretch 0.9–6.0 m_ |
| `kitchen_counter_l` | Kitchen counter, L-shaped | 2.4 × 1.8 | 1 | _L-shaped, needs a corner, plumbing, handed, stretch 0.9–6.0 m_ |
| `kitchen_sink` | Kitchen sink (double bowl) | 0.8 × 0.55 | 1 | _plumbing_ |
| `range_electric` | Range / cooktop (4 burner) | 0.6 × 0.6 | 1 | |
| `stove_gas_2burner` | Gas stove (2 burner) | 0.6 × 0.35 | 2 | |

### Dining

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `counter_dining_divider` | Dining counter divider | 2.1 × 0.9 | 1 | _free-standing, stretch 1.5–3.0 m_ |
| `counter_peninsula` | Peninsula counter (mini-bar) | 1.8 × 0.6 | 1 | _free-standing, stretch 1.2–2.7 m_ |
| `dining_4` | Dining table, 4-seat | 1.4 × 0.85 | 1 | _free-standing_ |
| `dining_6` | Dining table, 6-seat | 1.8 × 0.95 | 1 | _free-standing_ |
| `dining_compact_4` | Compact dining table, 4-seat | 0.9 × 0.9 | 1 | _free-standing_ |
| `dining_round_4` | Round dining table, 4-seat | ⌀ 1.05 | 1 | _round, free-standing_ |
| `dining_round_6` | Round dining table, 6-seat | ⌀ 1.35 | 1 | _round, free-standing_ |
| `bar_stool` | Bar stool | ⌀ 0.36 | 2 | _round, free-standing_ |
| `dining_8` | Dining table, 8-seat | 2.2 × 1 | 2 | _free-standing_ |
| `dining_compact_2` | Compact dining table, 2-seat | 0.75 × 0.75 | 2 | _free-standing_ |
| `dining_round_8` | Round dining table, 8-seat | ⌀ 1.55 | 2 | _round, free-standing_ |

### Living

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `armchair` | Armchair | 0.8 × 0.85 | 1 | _free-standing_ |
| `coffee_table` | Coffee table | 1.1 × 0.6 | 1 | _free-standing_ |
| `sofa_2seat` | Sofa, 2-seat | 1.5 × 0.85 | 1 | |
| `sofa_3seat` | Sofa, 3-seat | 2.1 × 0.85 | 1 | |
| `sofa_l` | Sofa, L-shaped (sectional) | 2.4 × 1.6 | 1 | _L-shaped, needs a corner, handed_ |
| `tv_console` | TV console (empty) | 1.4 × 0.4 | 1 | |
| `tv_on_console` | TV on console | 1.4 × 0.4 | 1 | |
| `altar` | Altar / prayer nook | 0.9 × 0.4 | 2 | |
| `tv_wall_mounted` | Wall-mounted TV | 1.2 × 0.1 | 2 | |

### Study

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `chair_task` | Task chair | 0.55 × 0.55 | 2 | _free-standing_ |
| `desk` | Desk | 1.2 × 0.6 | 2 | _handed_ |

### Service & utility

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `drying_area` | Drying line / area | 2.4 × 0.6 | 2 | _free-standing, stretch 1.5–4.0 m_ |
| `laundry_sink` | Laundry sink (banggerahan) | 0.6 × 0.5 | 2 | _plumbing_ |
| `lpg_tank` | LPG cylinder (11 kg) | 0.32 × 0.32 | 2 | _free-standing_ |
| `open_shelving` | Open shelving | 0.9 × 0.35 | 2 | _stretch 0.6–2.4 m_ |
| `storage_shelving` | Storage shelving | 0.9 × 0.45 | 2 | |
| `washing_machine` | Washing machine | 0.6 × 0.6 | 2 | _plumbing_ |
| `water_tank` | Water tank (1000 L) | 1.1 × 1.1 | 2 | _free-standing_ |

### Entry

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `shoe_cabinet` | Shoe cabinet | 0.9 × 0.35 | 2 | |

### Circulation

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `stair_straight` | Stair, straight flight | 0.9 × 3 | 1 | _free-standing, stretch 2.4–4.2 m_ |

### Outdoor & parking

| id | fixture | size (m) | tier | notes |
| --- | --- | --- | --- | --- |
| `car` | Car | 1.8 × 4.5 | 1 | _free-standing_ |
| `motorcycle` | Motorcycle | 0.75 × 2 | 3 | _free-standing_ |

## Styling

Every element carries both a presentation attribute and a class, so the library
renders correctly standalone and can still be restyled with CSS:

| class | role | default |
| --- | --- | --- |
| `fx-body` | the fixture outline | fill `#e3ded4`, stroke `#8a8378`, 0.9 px |
| `fx-accent` | soft secondary fill — pillows, cushions, seat pads | fill `#cbc4b4` |
| `fx-void` | an opening: basin, drum, bowl | fill `#ffffff` |
| `fx-detail` | thin linework | no fill, 0.6 px |
| `fx-hidden` | dashed: hanging rods, overhead cabinets, swings, zones | 0.5 px dashed |

One fill for every fixture body, deliberately. Colouring fixtures by family
makes a pale-blue shower read as a separate room against a pale-blue public
zone. Room fill means zone; fixture fill means contents. Kinds are told apart
by linework instead — pillow band, basin ellipse, burner circles — which also
survives greyscale printing, which colour coding does not.

## What is missing

Deliberately not drawn yet: split-AC indoor units and outdoor condensers,
window-type AC, ceiling fans, panel board, water meter, septic tank, grease
trap. Those are the ones with real compliance teeth — a condenser with nowhere
legal to sit, a septic tank too close to a property line — and they deserve
their own pass rather than being tacked onto a furniture library.

Also not drawn: L-shaped and U-shaped stairs, corner shower, kitchen island,
bunk beds, and the built-in concrete counter with an open shelf under it that
turns up constantly in real PH kitchens.

---

Version 0.1.0 · units metres · 55 symbols
