# Testing guide — regression briefs & lot-size sweeps

Reference for the two test mechanisms in `floorplan_v1/`: the **regression
suite** (`briefs/test/`, run via `run.py --test`) and the **lot-size sweep**
tooling (`briefs/test_sweep/`, run via `sweep_test.py` / `sweep_discover.py`
/ `lot_size_sweep*.py`). Both are solver-only (hand-authored topology +
brief JSON in, solved layout out) — no Claude/API calls, no network.

§4 covers the one mechanism that *is* networked: the AI generation path
(`briefs/ai/`, run via `run.py --mode ai`), which composes a topology
through a real Claude call instead of reading one off disk.

All commands assume you're in `floorplan_v1/` with the venv active:

```bash
cd floorplan_v1
source ../.venv/bin/activate
```

(`.venv` has `ortools` + `cairosvg` installed; without the venv, `run.py`
fails immediately with `ModuleNotFoundError: No module named 'ortools'`.)

---

## 1. Regression test briefs (`briefs/test/`)

The main "did I break anything" check. Each brief in `briefs/test/`
(nested by storey/bedroom-count/shell, e.g. `1s/2br/wide/...`, plus a
`test_mins/` subfolder for minimum-boundary briefs) is solved, validated,
and rendered. **PASS** = the validator emitted zero hard errors; warnings
and suggestions don't fail the run, they're just reported in the summary.

```bash
python3 run.py --test                       # every brief in briefs/test/
python3 run.py --test --brief=<name>        # one brief, by filename stem
python3 run.py --test --png                 # also write PNGs (needs cairosvg)
python3 run.py --test --update-baselines    # refresh test_baselines/ instead of test_output/
```

- Output SVGs (and PNGs with `--png`) land in `test_output/` (gitignored
  scratch — safe to `find test_output -mindepth 1 -delete` any time).
- `test_baselines/` is the committed visual-reference folder. Only
  `--update-baselines` writes there.
- `<name>` is the brief's filename stem, e.g.
  `1s_2br_12x10_wd_side_split_baths_cl_ld_ncp` for
  `briefs/test/1s_2br_12x10_wd_side_split_baths_cl_ld_ncp.json`.

### Updating baselines — do this narrowly, not in bulk

**Never run a blanket `--update-baselines` across the whole suite.** A few
complex/borderline-solve topologies are non-deterministic in SVG *element
order* between runs (geometry is identical, just emitted in a different
sequence — harmless, but it makes a byte-diff flag files that didn't
really change). A full-suite update mixes real changes in with this noise
and makes the commit hard to review.

Instead, refresh only the brief(s) your change actually affects:

```bash
python3 run.py --test --update-baselines --png --brief=<name>
```

Repeat per-brief for each one you intend to change. Before trusting a diff
as "real," it's worth re-running the same brief 2-3 times and confirming
the SVG is byte-stable — if it isn't, that specific file is in the known
non-deterministic-order category and not something to chase.

---

## 2. Lot-size sweep fixtures (`briefs/test_sweep/`)

A lighter-weight, per-topology companion to the regression suite: instead
of one canonical brief, a topology gets 2-3 fixtures pinned at its
discovered feasibility boundaries (typically `_min` / `_med` / `_max`,
sometimes with a ratio-class tag like `_near_min`). These live under
`briefs/test_sweep/<same path as topologies/>/<topology_id>/`.

**Two separate tools, two separate jobs:**

- `sweep_discover.py` — **finds** the boundaries and **writes** the fixture
  JSON files. Run this after a topology/solver change that might plausibly
  shift feasibility, or when building sweep coverage for a new topology.
- `sweep_test.py` — **solves** whatever fixtures already exist and reports
  PASS/FAIL. This is the one to run routinely (fast — no re-discovery).

```bash
# Solve existing sweep fixtures (routine check)
python3 sweep_test.py                        # every fixture
python3 sweep_test.py --topology=<id>        # only one topology's fixtures
python3 sweep_test.py --topology=<id> --png  # also write PNGs

# Regenerate fixtures after a change that might move feasibility boundaries
python3 sweep_discover.py                    # every topology in its SPECS list
python3 sweep_discover.py --topology=<id>    # just one
```

`<id>` is the topology id (e.g. `1s_2br_wd_side_split_baths_cl_ld`), not
the filename — `--topology` matches on folder-path substring.

Output SVGs (and PNGs) land in `sweep_output/` (gitignored scratch, same
role as `test_output/` — safe to clear anytime).

**`sweep_discover.py`'s SPECS list is deliberately incomplete.** Several
topologies are omitted ON PURPOSE — their fixtures were hand-curated
(user-specified round-number progressions, or restricted to compact-only
points) rather than tool-discovered. Re-adding them to SPECS and re-running
would silently discard those decisions. Read the comments at the top of the
SPECS dict before touching it. When a rule change invalidates hand-curated
fixtures, adjust them in place instead of re-discovering — after the
2026-08-05 front-setback change, 24 hand-curated fixtures were bumped +1 m
depth by hand while only the 2 SPECS-covered topologies were re-discovered.

**Reading a FAIL:** for a `_min`/`_max` fixture, a FAIL after a change is
a real signal the feasibility boundary moved — not necessarily a bug.
Confirm the new boundary is expected, then re-run `sweep_discover.py` for
that topology to refresh the fixture at its new true boundary.

Sweep fixtures are never touched by `run.py --test` and don't affect
regression pass/fail — they're a separate, opt-in check.

---

## 3. Broader systematic sweeps (`lot_size_sweep.py`, `lot_size_sweep_1br.py`)

Different from the two tools above: these don't read/write
`briefs/test_sweep/` fixtures at all. Each is a **hardcoded** list of
topologies swept across a wide, fine-grained range of lot sizes/ratios
(no `--topology` filter, no CLI args) to map out the *entire* feasible
band — used for one-off investigation (e.g. "where exactly does this
topology stop solving?"), not routine regression.

```bash
python3 lot_size_sweep.py        # squarish 2BR catalog (multi-sibling)
python3 lot_size_sweep_1br.py    # one topology per shape, 1BR catalog
```

Both write a Markdown + JSON report to `output/` (gitignored, regenerated
each run) — `lot_size_sweep_report.md` / `_1br_report.md`. Durable,
written-up findings from past sweeps live in
`floorplan_v1/LOT_SIZE_SWEEP_FINDINGS.md`, not in these regenerated
reports.

To sweep a *different* topology than what's hardcoded, edit the
`TOPOLOGIES` list (or the shape-keyed spec dict in the 1BR version) at the
top of the script — there's no config flag for this.

---

## 4. AI generation path (`briefs/ai/`, `run.py --mode ai`)

The only path here that **calls Claude and costs money**. Instead of naming
a topology file, a brief in `briefs/ai/` is composed into a topology by the
model, then run through the same solver/validator/renderer as everything
else. Briefs are the same JSON schema as `briefs/test/` minus the
`topology` field.

```bash
python3 run.py --mode ai                      # every brief in briefs/ai/
python3 run.py --mode ai --brief=<name>       # one brief, by filename stem
```

Output SVGs land in `output/` (gitignored). There is no PASS/FAIL summary
and no baseline comparison — the model's output isn't reproducible enough
to diff. Judge a run by the printed `COMPLIANT` line, the warning/
suggestion counts, and eyeballing the SVG.

**The API key.** `run.py::_make_ai_client` reads `ANTHROPIC_API_KEY` from
the environment and **silently falls back to `StubLLM` when it's absent** —
so a run with no key still "works," it just never touches `ai/prompt.py`.
Check the `LLM client:` line in the output: `ClaudeLLM` means a real call,
`StubLLM` means you tested nothing. The key lives in `.streamlit/secrets.toml`
(gitignored, also used by the Streamlit app); export it for a CLI run:

```bash
export ANTHROPIC_API_KEY=$(python3 -c "import tomllib;print(tomllib.load(
  open('../.streamlit/secrets.toml','rb'))['ANTHROPIC_API_KEY'])")
```

**Repair rounds are expected, not failures.** The pipeline retries up to
`MAX_REPAIR` (2) times, feeding the schema/structural/solver error back to
Claude. A first attempt failing on e.g. `habitable room 'master' is
unreachable from entry` followed by a COMPLIANT repair round is the loop
working as designed.

**Checking exemplar selection.** Since 2026-08-05 the few-shot exemplars
are chosen per brief from the catalog rather than being a fixed pair
(`ai/prompt.py::select_exemplars`). The `reasoning:` line names the ones
that were used, so a 3BR brief and a 2BR brief should print different
files:

```
reasoning: [claude/claude-sonnet-4-5/T=0.0] tool_use; tokens: in=13025 out=1890;
           exemplars: 1s_3br_sq_bedroom_lobby_hub_baths_ds_hall_gr,
                      1s_3br_sq_front_back_split_baths_cl_hall_lk
```

To check selection without spending tokens, call `select_exemplars(brief)`
directly — it's pure catalog logic with no network dependency.

**A PASS does not mean the brief tested what it claims.** When a topology
declares `fallback_topology`, a brief that becomes infeasible will quietly
solve as the SIBLING and still report PASS — the fixture silently stops
covering its own topology. Two briefs did exactly this after the 2026-08-05
setback change. `run.py --test` cannot detect it; compare the solved
`topo.id` against the topology the brief declares:

```python
layout, topo, _ = run._run_hand_authored(brief, topology_fname, ...)
assert topo.id == os.path.basename(topology_fname)[:-5]
```

Audit this after any change to setbacks, room sizes, or solver constraints.

**`run.py --test` never exercises any of this.** The regression suite goes
through `_run_hand_authored`, so an `ai/prompt.py` or `ai/llm.py` change
can pass 49/49 while being completely broken. Verify AI-path changes with
an actual `--mode ai` run.

---

## Quick reference: "I changed X, what do I run?"

| Change | Run this |
|---|---|
| Any topology JSON, solver code, or renderer code | `run.py --test` (full regression) |
| One specific brief/topology after a targeted fix | `run.py --test --brief=<name>` |
| Confirm a topology's declared min/med/max fixtures still hold | `sweep_test.py --topology=<id>` |
| Topology/solver change might have moved feasibility boundaries | `sweep_discover.py --topology=<id>`, then `sweep_test.py --topology=<id>` |
| Deep investigation of exactly where a topology's feasible band lies | `lot_size_sweep.py` / `lot_size_sweep_1br.py` (edit the hardcoded list first if needed) |
| After any intentional visual change, before committing | refresh only the affected baseline(s) with `--update-baselines --brief=<name>` — never blanket |
| `ai/prompt.py`, `ai/llm.py`, or anything on the Claude path | `run.py --mode ai --brief=<name>` with a real key — `run.py --test` does **not** cover it (§4) |
| Changed setbacks, room sizes, or solver constraints | audit for SILENT TOPOLOGY SUBSTITUTION (§4) — a fallback can mask a broken fixture behind a PASS |
| Added or deleted a topology JSON | also worth a `--mode ai` run: exemplar selection reads `topologies/` live, so the catalog change alters the prompt (§4) |

See also: `CLAUDE.md` → "Useful paths" for the topology/brief directory
layout, and `TOPOLOGY_CHANGES.md` for the convention of logging every
topology/brief/shared-code change ahead of an `artol-topologies/` catalog
regen.
