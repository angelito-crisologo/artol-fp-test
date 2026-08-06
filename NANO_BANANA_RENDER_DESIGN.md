# Polished 2D render via Gemini "Nano Banana" — design

**Status: DESIGN ONLY (2026-08-06), no code written.** Per the project's
ask-before-coding convention.

Purpose: take a solved + rendered floor plan and produce a polished 2D
architectural diagram with fixtures, furniture, landscaping and cars, for
customer discussion.

---

## 1. Framing — TWO artifacts, and only one of them is the plan

Settled decision (option **D**): the polished image **never replaces** the
technical drawing. Every brief that opts in produces both:

| artifact | role | authority |
|---|---|---|
| `<brief>.svg` / `.png` | dimensioned technical drawing from the solver | **plan of record** |
| `<brief>_render.png` | Nano Banana output, produced ONLY by an explicit `polish.py` run | **illustrative only** |

This matters because of what these documents are for (see
`TOPOLOGY_CHANGES.md`, 2026-08-06 scope decision): the plan is a customer
discussion aid AND a brief handed to an architect. An unpolished drawing is
fine input to an architect. A beautiful drawing whose geometry silently
disagrees with its own dimension labels is *worse than useless* — it is
misleading input, and the drift is invisible without measuring.

**So the polished image must be labelled illustrative wherever it is shown,
and must never be the file an architect works from.**

## 2. What we send — grounded image-to-image (option B)

Nano Banana is a **generative** model: given a floor plan it redraws rather
than annotates. Decision #3 leans into this — it generates the whole diagram,
not an overlay on ours. That maximises visual quality and **eliminates any
possibility of mechanical fidelity checking** (see §6). Grounding therefore
has to come from the prompt, not from post-hoc verification.

Two inputs:

1. **The rendered composite PNG** — existing `core/render.py` output,
   rasterised via `cairosvg` (already a dependency). Decision #2: send the
   COMPOSITE, so 2-storey plans go as one side-by-side image.
2. **A structured manifest** derived from the `ArchPlan`, so the model has
   ground truth in text rather than having to infer it from pixels.

### 2.1 Manifest (JSON, embedded in the prompt)

Everything below is already computed and available on `ArchPlan` / `Layout`:

```json
{
  "lot": {"width_m": 12.0, "depth_m": 11.0, "front": "south"},
  "storeys": [
    {"storey": 1, "envelope_m": [8.0, 6.0],
     "rooms": [
       {"id": "master", "type": "master_bedroom", "label": "MASTER BR",
        "rect_m": [2.0, 5.0, 5.4, 8.7], "area_sqm": 12.6,
        "orientation": {"head_wall": "N"},
        "doors": [{"wall": "S", "position_m": 1.2, "width_m": 0.9}],
        "windows": [{"wall": "N", "position_m": 0.8, "width_m": 1.2}]}
     ]}
  ],
  "setback_elements": [
    {"type": "carport", "rect_m": [9.0, 2.0, 12.0, 8.0], "covered": false}
  ]
}
```

The `orientation` block is the important one and it **already exists** —
`solver/fixture_orientation.py` ("Phase E.1") derives per room which wall is
the bed head, the kitchen sink/counter run, the bath wet wall and the shower
wall. Its own docstring notes it does this *"WITHOUT placing actual furniture
rectangles"*, which is exactly the gap this feature fills. Feeding those hints
to the model is what stops it putting the bed across the window or the toilet
on the wall shared with the kitchen.

### 2.2 Prompt shape

Roughly:

- **Role**: produce a clean 2D architectural presentation floor plan.
- **Hard constraints**: reproduce the room layout, adjacency and relative
  proportions in the supplied image and manifest EXACTLY; do not add, remove,
  merge or rename rooms; keep every room label and area figure verbatim.
- **Furniture** (decision #5 — complete): beds sized to room type, wardrobes,
  sofa + TV, dining table + chairs, kitchen counter/sink/range/fridge,
  toilet + lavatory + shower, laundry, **cars in carports**, planting in
  setbacks, dirty-kitchen equipment, lanai furniture.
- **Placement rules**: obey the `orientation` hints; never block a door swing
  or a window; keep circulation clear.
- **Style**: top-down orthographic, consistent line weights, muted
  architectural palette, north arrow, no perspective, no 3D.

## 3. Model & SDK

- Model: **Gemini 2.5 Flash Image** ("Nano Banana"), via the `google-genai`
  SDK (`from google import genai`).
- **Neither `google-genai` nor `google-generativeai` is currently installed**,
  and `.streamlit/secrets.toml` holds only `ANTHROPIC_API_KEY` and
  `APP_PASSWORD` — a `GEMINI_API_KEY` must be added alongside.
- **Pin the model id and the request/response shape in ONE module-level
  constant and verify both against current Google docs at implementation
  time.** Image-model ids and the exact `generate_content` part types move
  faster than this repo does; do not scatter them.

## 4. Where it plugs in — a SEPARATE COMMAND, not a flag

**Hard requirement (user, 2026-08-06): this must only ever run on a manually
selected plan. It must NEVER fire automatically when floor plans are
generated.**

That is a structural guarantee, not a default-off flag. A `--polish` flag on
the normal run path would still be a code path from "generate" to "call
Gemini" — one batch script or one changed default away from firing. So the
generation pipeline gains **no import of the polish module and no flag at
all**:

```
python3 run.py --brief=X          # solve + render. No polish flag exists.
python3 polish.py --brief=X       # separate command, on ALREADY-WRITTEN output
```

`polish.py` re-solves (or reads) the named brief, rebuilds the manifest,
sends the existing rendered composite, and writes `<brief>_render.png`
alongside it. Because `run.py` never imports it, there is no enabled-or-
disabled path from plan generation to an API call.

### 4.1 Guarantees to implement

1. **No import of the polish module from `run.py`, `app.py` or
   `build_catalog.py`.** Backed by a grep-style test so a future edit cannot
   quietly wire it in.
2. **`--brief` is REQUIRED and takes explicit names.** No directory sweep, no
   "polish everything" mode, no glob default.
3. **Confirmation before spending.** Print the target brief, the output path
   and the estimated cost; require `--yes` to proceed non-interactively.
4. **Never reachable from `run.py --test`.** The suite runs 52 briefs; image
   generation is billed per image and non-deterministic, so it can have no
   baselines and must not gate regression.
5. Decision #4: **no catalog integration.** `artol-topologies/` keeps showing
   the technical SVG only, which also keeps `build_catalog.py` free of API
   cost and network dependence.

## 5. Cost & caching

Billed per image. Cache on a hash of (manifest JSON + prompt version + source
PNG bytes) so re-running an unchanged brief is free. Bump a `PROMPT_VERSION`
constant to invalidate deliberately.

## 6. What we can and cannot verify

**Cannot:** because the model regenerates the whole diagram (decision #3),
there is no pixel or geometry correspondence to check against. A
wall-position diff would fail on every image by design. **There is no
automated fidelity gate for this feature.**

**Can, cheaply:**
- the call returned an image of the expected dimensions/aspect;
- OCR-free sanity: response is non-empty, correct MIME type, decodes;
- optional and worthwhile — a **second Gemini call as a checker**, handing it
  the original PNG, the polished image, and the manifest, and asking whether
  the room count, labels and adjacencies match. Cheap relative to a bad render
  reaching a customer, and the only realistic automated check available.

Everything else is human review. That is acceptable *only* because of the §1
framing: the technical SVG is unaffected by whatever the model returns.

## 7. Direction of travel — option C

Longer term, finish **Phase E**: place furniture as real rectangles ourselves
using the orientation data, so furniture becomes *queryable* (does a double
bed plus 600 mm circulation actually fit?) rather than decorative. At that
point Nano Banana's job narrows to styling a plan that is already correct,
and fidelity risk drops sharply.

Note for whoever does that work: `solver/fixture_orientation.py` carries its
own private `_touches_exterior` — a THIRD copy of the exterior-wall test that
was unified into `core/model.py::make_outside_probe` on 2026-08-06. Fold it
in rather than propagating a fourth.

## 8. Open items

- Exact model id + SDK call shape (§3) — verify before writing.
- Composite vs per-floor: composite is the decision, but if 2-storey output
  degrades (the model has to reproduce two panels consistently), per-floor
  with client-side compositing is the fallback. Worth testing early on a 2s
  brief specifically.
- Whether the checker call in §6 is worth its cost — decide after seeing
  first-pass output quality.
- Where the output lands: alongside the SVG in `output/`, or a sibling
  `render/` tree. Leaning alongside, so a brief's artifacts stay together.

---

# 9. Evaluation, 2026-08-06 — ten billed calls

Ten images, ~$0.40, model `gemini-2.5-flash-image`. Written up because the
findings are counter-intuitive and expensive to re-derive.

## 9.1 The headline

**Prompt FRAMING dominated every other variable.** Six versions written here
(`ai/render_prompt.py`, v1-v6) all said "redraw" or "restyle" and all invented
dimension figures — `LIVING 3.7x2.6 m . 14.8 sqm` where the plan says 33.1.
A user-written prompt opening with *"**Convert** the provided floor plan image
into a 2D architectural render"* got **every figure on the page correct on its
first attempt**, having been told nothing about numbers at all.

"Redraw"/"restyle" licenses regeneration. "Convert" reads as image-to-image
translation. That one word was worth more than ~400 lines of fidelity clauses.
It is kept verbatim at **`floorplan_v1/ai/prompts/convert_render.txt`**.

## 9.2 What works, in order of reliability

1. **Counted checklists.** "This plan has EXACTLY 5 doors" / "7 labels:
   BEDROOM, LIVING, ..." Every time a count was given, the model matched it —
   it produced the long-missing kitchen service door, and restored a dropped
   DINING label. Giving it something to check itself against beats any
   prohibition. Counts are derivable from the manifest, so this generalises.
2. **Marking the target IN THE IMAGE.** Four prose attempts failed to make the
   model draw the kitchen's exterior service door; overdrawing every door in
   magenta (`archplan_to_svg(door_emphasis=True)`) produced all five first
   try. **This model follows the picture far more than the paragraph** — the
   single most consistent finding across all ten runs.
3. **Naming a specific misplacement.** "The dining table must be inside
   DINING, not in LIVING" moved it. Worked once, did not work for the kitchen
   counter (see 9.3).

## 9.3 What does not work

- **Prohibitions without a count.** "Do not add..." was violated repeatedly.
- **Instructions it simply overrides.** "YOUR IMAGE MUST CONTAIN NO TEXT
  WHATSOEVER", stated as instruction #1 in capitals, was ignored in full.
- **Repeating a failed instruction more forcefully.** The kitchen counter and
  fridge sat in the dining room through three differently-worded bans.
- **Our measured furniture.** Phase E.2 rectangles were sent in the image AND
  listed in the manifest as ground truth; the model still moved the master bed
  to a different wall in every render. Furniture is illustrative; labels no
  longer have to be.

## 9.4 Whack-a-mole is the steady state

Across ten runs each round fixed the named defect and introduced a different
one. Room count, labels, dimensions, doors, furniture ownership, a `DIING`
typo, an invented roof plane — each has been correct in some render and wrong
in another, **never all at once**. Treat that as a property of a generative
model, not as a prompt that is not yet good enough. Do not expect a version
that nails everything simultaneously, and budget accordingly.

## 9.5 The durable answer: composite, do not negotiate

Built and working (`core/render.py`):

- `polished_image_overlay(layout, png)` — the returned image over the LOT rect.
- `room_label_masks(layout)` — opaque chips over each room's label zone, sized
  to the **room**, so whatever the model wrote is covered whatever its length.
- `inject_overlay(..., mask_behind_labels=)` — re-emits OUR label text on top.

Alignment comes from cropping the model's output to its lawn bounding box,
which also discards the ruler and caption it draws despite being told not to.
Result: the picture is the model's, **every number is ours**, and `DIING`
becomes structurally impossible. Deterministic, free, and independent of the
model obeying anything.

Caveat: the crop currently keys on GREEN pixels. Once the setback rule was
changed to force grass that is safe, but a paved-setback render would need a
different anchor.

## 9.6 Verdict

The model reliably delivers **styling** and reliably fails at **facts**. Use it
for styling only, supply every fact by composite, and keep §1's rule: the
dimensioned SVG is the plan of record.

Tooling: `polish.py --plain` (send the solver drawing unmodified),
`--prompt-file` (verbatim, nothing appended — a hand-written prompt is a
controlled experiment), `--raw-output` (skip the composite).
