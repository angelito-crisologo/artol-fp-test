"""Simulated-annealing optimizer over a slicing-tree genome.

Template-agnostic: it tunes whatever continuous cut-ratio keys a template
exposes (float_keys), keeping the discrete structure (template, carport side,
master position) fixed per run. Energy = -fitness, so SA is pushed away from
hard violations and toward preferred room sizes under the LDK > master >
bedroom priority.
"""
import math
import random
from typing import Dict, List, Callable
from model import Lot, Layout
from engine import build_layout, DEFAULTS, float_keys
from validator import validate, is_compliant
from rules import Rules


def _random_genome(rng: random.Random, base: Dict) -> Dict:
    # Seed near the template's intended proportions (defaults) with small noise,
    # so the design holds and the optimizer refines locally rather than drifting
    # to arbitrary feasible proportions when the fitness is flat.
    g = dict(base)
    for k in float_keys(base):
        g[k] = min(0.82, max(0.18, base[k] + rng.gauss(0, 0.07)))
    return g


def _neighbor(g: Dict, rng: random.Random) -> Dict:
    ng = dict(g)
    keys = float_keys(g)
    k = rng.choice(keys)
    ng[k] = min(0.82, max(0.18, g[k] + rng.gauss(0, 0.08)))
    return ng


def anneal(lot: Lot, rules: Rules, base: Dict, seed: int = 0,
           iters: int = 4000, t0: float = 5.0, t1: float = 0.02) -> Layout:
    rng = random.Random(seed)
    cur = _random_genome(rng, base)
    cl = build_layout(lot, cur)
    validate(cl, rules)
    cur_e = -cl.score
    best, best_e = cur, cur_e

    for i in range(iters):
        frac = i / max(1, iters - 1)
        t = t0 * (t1 / t0) ** frac
        cand = _neighbor(cur, rng)
        c = build_layout(lot, cand)
        validate(c, rules)
        e = -c.score
        if e < cur_e or rng.random() < math.exp(-(e - cur_e) / max(t, 1e-9)):
            cur, cur_e = cand, e
            if e < best_e:
                best, best_e = cand, e

    layout = build_layout(lot, best)
    validate(layout, rules)
    return layout


def generate_candidates(make_lot: Callable[[str], Lot], rules: Rules,
                        template: str, variants: List[Dict],
                        seeds_per_combo: int = 6, iters: int = 4000,
                        optimize: bool = True) -> List[Layout]:
    """Produce one compliant candidate per requested variant. Each `variant` is
    a dict of discrete overrides (e.g. master_position, ensuite_position).
    When optimize=True the cut ratios are tuned by simulated annealing; when
    False (faithful reproduction templates) the template's fixed default
    proportions are used directly. `make_lot(carport_side) -> Lot`."""
    results = []
    for variant in variants:
        carport_side = variant.get("carport_side", "right")
        lot = make_lot(carport_side)
        base = dict(DEFAULTS[template])
        base.update(variant)
        if not optimize:
            L = build_layout(lot, base)
            validate(L, rules)
            if is_compliant(L):
                results.append(L)
            continue
        best = None
        for s in range(seeds_per_combo):
            L = anneal(lot, rules, base, seed=s, iters=iters)
            if not is_compliant(L):
                continue
            if best is None or L.score > best.score:
                best = L
        if best is not None:
            results.append(best)
    return results
