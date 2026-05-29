"""Validator + fitness function.

Checks a Layout against the PD 1096 hard rules and the soft PH preferences,
returning structured issues and a numeric fitness score that the optimizer
maximizes. Severity follows the rules file: error (hard), warning (IRR/LGU),
suggestion (soft).
"""
from typing import List, Tuple
from model import Layout
from rules import Rules

HABITABLE = {"bedroom_standard", "master_bedroom", "living_room", "dining_room", "great_room", "maids_room"}
HARD_PENALTY = 100000.0
WARN_PENALTY = 500.0


class Issue:
    def __init__(self, severity, code, msg):
        self.severity = severity  # error | warning | suggestion
        self.code = code
        self.msg = msg

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.msg}"


def validate(layout: Layout, rules: Rules) -> Tuple[List[Issue], float]:
    issues: List[Issue] = []
    env = layout.lot.envelope()

    # ---------- HARD: room minimums ----------
    for r in layout.rooms:
        amin = rules.hard_min_area(r.type)
        lmin = rules.hard_min_least(r.type)
        if amin and r.area + 1e-6 < amin:
            issues.append(Issue("error", "min_area",
                f"{r.type}: area {r.area:.2f} sqm < hard min {amin:.2f} sqm"))
        if lmin and r.least + 1e-6 < lmin:
            issues.append(Issue("error", "min_least_dim",
                f"{r.type}: least dim {r.least:.2f} m < hard min {lmin:.2f} m"))

    # ---------- HARD: no overlap among footprint rooms ----------
    for i in range(len(layout.rooms)):
        for j in range(i + 1, len(layout.rooms)):
            if layout.rooms[i].overlaps_room(layout.rooms[j]):
                issues.append(Issue("error", "overlap",
                    f"{layout.rooms[i].type} overlaps {layout.rooms[j].type}"))

    # ---------- HARD: footprint stays within buildable envelope ----------
    for r in layout.rooms:
        if not r.within(env):
            issues.append(Issue("error", "out_of_envelope",
                f"{r.type} extends beyond the buildable envelope"))

    # ---------- HARD: lot occupancy ----------
    cap = rules.occupancy_cap_pct()
    if layout.occupancy_pct > cap + 1e-6:
        issues.append(Issue("error", "occupancy",
            f"occupancy {layout.occupancy_pct:.1f}% > {cap:.0f}% cap"))

    # ---------- HARD: window / exterior access for habitable rooms (Sec. 808) ----------
    for r in layout.rooms:
        if r.type in HABITABLE and not r.touches_boundary(env):
            issues.append(Issue("error", "window_access",
                f"{r.type} has no exterior wall (needs window per Sec. 808, or a court/vent shaft)"))

    # ---------- HARD: ensuite must touch master; kitchen adjacent to dirty kitchen ----------
    rmap = {r.type: r for r in layout.rooms}
    # ---------- ensuite_bath rules (supports >1 ensuite for twin-ensuite topologies) ----------
    # Every ensuite must be adjacent to a bedroom (the "private" relationship);
    # at least one ensuite must be adjacent to the master. The first rule keeps
    # each ensuite genuinely private; the second preserves PH convention that
    # the master always has its own bath.
    ensuites = [r for r in layout.rooms if r.type == "ensuite_bath"]
    bedrooms = [r for r in layout.rooms
                if r.type in ("master_bedroom", "bedroom_standard")]
    master = next((r for r in layout.rooms if r.type == "master_bedroom"), None)
    for e in ensuites:
        if bedrooms and not any(e.adjacent_room(b) for b in bedrooms):
            issues.append(Issue("error", "ensuite_access",
                f"ensuite_bath '{e.id}' is not adjacent to any bedroom "
                f"(ensuites must be private to a bedroom)"))
    if ensuites and master and not any(e.adjacent_room(master) for e in ensuites):
        issues.append(Issue("error", "ensuite_access",
            "no ensuite_bath is adjacent to master_bedroom"))
    # ---------- HARD: bedrooms must be reachable from a hallway or public room ----------
    ACCESS_FROM = {"living_room", "dining_room", "great_room", "hallway"}
    for r in layout.rooms:
        if r.type in ("bedroom_standard", "master_bedroom"):
            neighbors = [o for o in layout.rooms
                         if o is not r and r.adjacent_room(o)]
            if not any(o.type in ACCESS_FROM for o in neighbors):
                issues.append(Issue("error", "no_access",
                    f"{r.type} has no access from a hallway or public room "
                    f"(only reachable through a private/service room)"))

    emap = {e.type: e for e in layout.elements}
    if "kitchen" in rmap and "dirty_kitchen" in emap:
        if not rmap["kitchen"].adjacent_room(emap["dirty_kitchen"], tol=0.35):
            issues.append(Issue("warning", "dirty_kitchen_adjacency",
                "dirty kitchen is not adjacent to the kitchen's rear wall"))

    # ---------- HARD: setback elements must be uncovered & inside a setback ----------
    for e in layout.elements:
        if e.covered:
            issues.append(Issue("error", "covered_in_setback",
                f"{e.type} is covered but sits in a setback (needs firewall or footprint)"))
        # must NOT intrude into the buildable envelope
        if e.rect.overlaps(env):
            issues.append(Issue("warning", "element_in_envelope",
                f"{e.type} overlaps the buildable footprint"))

    # ---------- SOFT: preferred sizes (also drives fitness) ----------
    soft_score = 0.0
    for r in layout.rooms:
        pref = rules.preferred_area_range(r.type)
        w = rules.priority_weight(r.type)
        if not pref:
            continue
        plo, phi = pref
        amin = rules.hard_min_area(r.type) or plo * 0.5
        oversize_cap = phi * 1.4          # comfortably above preferred before we penalize
        a = r.area
        if a < plo:
            sat = 0.0 if a <= amin else (a - amin) / (plo - amin)
            issues.append(Issue("suggestion", "below_preferred",
                f"{r.type}: {a:.1f} sqm below preferred {plo:.1f} sqm (satisfaction {sat:.0%})"))
        elif a <= oversize_cap:
            sat = 1.0
        else:
            sat = max(0.0, 1.0 - (a - oversize_cap) / oversize_cap)
            issues.append(Issue("suggestion", "oversized",
                f"{r.type}: {a:.1f} sqm well above preferred {phi:.1f} sqm "
                f"(area could go to priority rooms)"))
        soft_score += w * sat

    # ---------- aggregate fitness ----------
    n_err = sum(1 for i in issues if i.severity == "error")
    n_warn = sum(1 for i in issues if i.severity == "warning")
    fitness = soft_score - HARD_PENALTY * n_err - WARN_PENALTY * n_warn

    layout.issues = issues
    layout.score = round(fitness, 4)
    return issues, layout.score


def is_compliant(layout: Layout) -> bool:
    return not any(i.severity == "error" for i in layout.issues)
