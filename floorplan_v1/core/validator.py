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
# Window-eligible rooms include the kitchen (over-sink window for ventilation
# per PH practice; not a Sec. 808 habitable room but PD 1096 still requires
# light/ventilation). Kitchens take the habitable-room window-area rule.
HABITABLE_FOR_WINDOWS = HABITABLE | {"kitchen"}
BATH_TYPES = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room"}
# PD 1096 §808(a) + IRR Rule VIII §10:
#   habitable rooms: window area >= 10% of floor area, but never less than 1.00 m²
#   bath / WC:       window area >=  5% of floor area, but never less than 0.24 m²
WINDOW_RATIO_HABITABLE = 0.10
WINDOW_AREA_MIN_HABITABLE_SQM = 1.00
WINDOW_RATIO_BATH = 0.05
WINDOW_AREA_MIN_BATH_SQM = 0.24
# Fallback when a Window has no height_m set (e.g. older archplans). Standard
# PH window head sits ~2.1 m, sill ~0.9 m → ~1.2 m glazed height.
WINDOW_DEFAULT_HEIGHT_M = 1.2

# PD 1096 IRR Rule VII / Rule VIII Table VIII.2 setback minimums per
# residential occupancy class (m). Values: (front, side, rear). Side applies
# to both left and right unless one is a firewall (allowed by occupancy
# class). LGU zoning often overrides upward but never downward.
SETBACK_MIN_BY_OCCUPANCY = {
    "R-1": {"front": 4.5, "side": 2.0, "rear": 2.0},
    "R-2": {"front": 3.0, "side": 2.0, "rear": 2.0},
    "R-3": {"front": 3.0, "side": 2.0, "rear": 2.0},
    "R-4": {"front": 3.0, "side": 2.0, "rear": 2.0},
    "R-5": {"front": 6.0, "side": 3.0, "rear": 3.0},
}
# PD 1096 §704 + RA 9514: which residential classes may have a firewall
# (zero-setback exterior wall against a neighbor). R-1 cannot have any;
# R-2 / R-3 / R-4 may have side firewalls (party walls). None may have a
# front (street-side) firewall.
FIREWALL_ALLOWED_SIDES = {
    "R-1": set(),                # absolutely no firewalls
    "R-2": {"left", "right"},    # one or two side firewalls
    "R-3": {"left", "right", "rear"},
    "R-4": {"left", "right", "rear"},
    "R-5": {"left", "right", "rear"},
}
# §808: window must open to a court / yard / public street / alley / open
# watercourse. The court minimum is 2.0 m. For our purposes a window on
# a wall whose lot setback is ≥ 2.0 m is presumed to face an adequate yard.
WINDOW_OPENS_TO_YARD_MIN_M = 2.0

HARD_PENALTY = 100000.0
WARN_PENALTY = 500.0


def _side_setback(lot, side: str) -> float:
    """Setback (m) for a given compass side N/S/E/W on a lot.
    Mapping (street_side='front'): S→front, N→rear, W→left, E→right."""
    if side == "S": return lot.front
    if side == "N": return lot.rear
    if side == "W": return lot.left
    if side == "E": return lot.right
    return 0.0


def _element_strays_outside_voids(element_rect, env, void_rects):
    """Return True if `element_rect`'s overlap with the envelope `env` extends
    into any envelope area NOT covered by `void_rects`. We compute the
    intersection of element ∩ env and check if any sub-region of that
    intersection lies outside the union of voids."""
    # Compute the element-envelope intersection.
    ix0 = max(element_rect.x0, env.x0)
    iy0 = max(element_rect.y0, env.y0)
    ix1 = min(element_rect.x1, env.x1)
    iy1 = min(element_rect.y1, env.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False  # no overlap with envelope at all
    # For each void, subtract its area from the intersection. If anything
    # remains, the element strays outside the voids. We approximate by
    # asking: is there a single void that fully contains the intersection?
    # For our use case (one carport void per topology) this is sufficient.
    for v in void_rects:
        if (v.x0 - 1e-6 <= ix0 and v.y0 - 1e-6 <= iy0 and
                v.x1 + 1e-6 >= ix1 and v.y1 + 1e-6 >= iy1):
            return False
    return True


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

    # ---------- HARD: occupancy / setbacks / firewall legality ----------
    # W-H10: residential occupancy class controls which sides may carry a
    # firewall (setback = 0). R-1 (single-detached) absolutely cannot have
    # any firewall — every side needs the full yard. R-2 may carry a side
    # firewall (typical duplex / row house). Front firewalls are never
    # allowed for any residential class.
    occ = getattr(layout.lot, "occupancy_class", "R-1")
    allowed_fw = FIREWALL_ALLOWED_SIDES.get(occ, set())
    side_to_yard = {"front": "S", "rear": "N", "left": "W", "right": "E"}
    for side_name in ("front", "rear", "left", "right"):
        sb = getattr(layout.lot, side_name)
        if sb == 0:
            if side_name == "front":
                issues.append(Issue("error", "front_firewall_illegal",
                    f"occupancy {occ}: front setback is 0 (firewall) — "
                    f"PD 1096 forbids firewalls on the street side for any "
                    f"residential occupancy"))
            elif side_name not in allowed_fw:
                issues.append(Issue("error", "firewall_illegal_for_occupancy",
                    f"occupancy {occ}: {side_name} setback is 0 (firewall) "
                    f"but {occ} doesn't permit firewalls on that side "
                    f"(PD 1096 §704; IRR Rule VII)"))
    # W-H11: flag setbacks below the IRR Rule VIII Table VIII.2 baseline.
    # This is a WARNING (not hard error) because LGU zoning frequently
    # overrides — almost all PH mid-market subdivisions use a 2.0 m front
    # setback regardless of strict R-1 baseline (4.5 m). The validator
    # surfaces the IRR baseline so a designer can confirm with their LGU.
    mins = SETBACK_MIN_BY_OCCUPANCY.get(occ)
    if mins:
        for side_name, m_key in (("front", "front"), ("rear", "rear"),
                                  ("left", "side"), ("right", "side")):
            sb = getattr(layout.lot, side_name)
            min_sb = mins[m_key]
            # 0 was already checked for firewall legality above; skip the
            # min-setback rule when 0 is legal (the side is a party wall).
            if sb == 0:
                continue
            if sb + 1e-6 < min_sb:
                issues.append(Issue("suggestion", "setback_below_irr_baseline",
                    f"{occ} {side_name} setback {sb:.2f} m is below the "
                    f"IRR Rule VIII Table VIII.2 baseline of {min_sb:.1f} m "
                    f"(LGU zoning may permit smaller — verify locally)"))

    # ---------- HARD: window / exterior access for habitable rooms (Sec. 808) ----------
    for r in layout.rooms:
        if r.type in HABITABLE and not r.touches_boundary(env):
            issues.append(Issue("error", "window_access",
                f"{r.type} has no exterior wall (needs window per Sec. 808, or a court/vent shaft)"))

    # ---------- HARD: window OPENING AREA (PD 1096 §808 / IRR Rule VIII §10) ----------
    # W-H1: habitable rooms (+ kitchen by PH practice) need total window area
    #       >= 10% of floor area, never < 1.00 m².
    # W-H2: T&B / powder room / laundry need >= 5% of floor area, never
    #       < 0.24 m² — unless the room is declared mechanically ventilated
    #       (model attribute r.mechanical_vent, default False).
    # These checks require an attached architectural plan; rooms whose
    # archplan window list is empty fail the check. Without an attached
    # plan (e.g. solver-only path before architecturalize) the rule is
    # skipped — the layout-only validator can't see windows.
    plan = getattr(layout, "archplan", None)
    if plan is not None:
        # W-H3: every window must face a court / yard with width ≥ 2.0 m.
        # In our model the proxy is the lot setback on that compass side:
        # >= 2.0 m means there's a yard at least as wide as PD 1096's court
        # minimum (§804). Firewall sides (setback 0) already get no windows
        # in the architecturalize step.
        for w in plan.windows:
            sb = _side_setback(layout.lot, w.wall)
            if sb + 1e-6 < WINDOW_OPENS_TO_YARD_MIN_M:
                issues.append(Issue("error", "window_yard_too_narrow",
                    f"window in {w.room} on the {w.wall} wall faces a "
                    f"{sb:.2f} m yard — PD 1096 §808 / §804 requires "
                    f"≥ {WINDOW_OPENS_TO_YARD_MIN_M:.1f} m"))
        windows_by_room: dict = {}
        for w in plan.windows:
            windows_by_room.setdefault(w.room, []).append(w)
        for r in layout.rooms:
            wins = windows_by_room.get(r.id, [])
            win_area = sum(
                w.width_m * (getattr(w, "height_m", None) or WINDOW_DEFAULT_HEIGHT_M)
                for w in wins
            )
            mech_vent = getattr(r, "mechanical_vent", False)
            touches_ext = r.touches_boundary(env)
            if r.type in HABITABLE_FOR_WINDOWS:
                if mech_vent:
                    # Topology declares this room uses artificial ventilation
                    # (PD 1096 §805): skip the 10% window check.
                    continue
                required = max(WINDOW_RATIO_HABITABLE * r.area,
                               WINDOW_AREA_MIN_HABITABLE_SQM)
                if win_area + 1e-6 < required:
                    # A habitable room with no usable exterior wall is a
                    # design issue, but PD 1096 §805 lets artificial vent
                    # systems substitute. Flag as warning when the room is
                    # tightly hemmed in (touches exterior but can't fit a
                    # compliant window due to doors), and as a hard error
                    # when there's no exterior wall at all (would have
                    # already been caught by 'window_access' for HABITABLE
                    # rooms; kitchen falls through here).
                    sev = "warning" if touches_ext else "error"
                    issues.append(Issue(sev, "window_area_habitable",
                        f"{r.type} '{r.id}': window area {win_area:.2f} m² "
                        f"< required {required:.2f} m² "
                        f"(PD 1096 §808: 10% of floor, min 1.00 m². "
                        f"Use mechanical ventilation or redesign)"))
            elif r.type in BATH_TYPES:
                if mech_vent:
                    continue
                # A bath with NO exterior wall almost always uses mechanical
                # ventilation (per PD 1096 + practice). Emit a SUGGESTION
                # to confirm rather than a hard error.
                if not touches_ext:
                    issues.append(Issue("suggestion", "bath_needs_mech_vent",
                        f"{r.type} '{r.id}' has no exterior wall — must use "
                        f"mechanical ventilation (mark room.mechanical_vent=True)"))
                    continue
                required = max(WINDOW_RATIO_BATH * r.area,
                               WINDOW_AREA_MIN_BATH_SQM)
                if win_area + 1e-6 < required:
                    issues.append(Issue("error", "window_area_bath",
                        f"{r.type} '{r.id}': window area {win_area:.2f} m² "
                        f"< required {required:.2f} m² "
                        f"(IRR Rule VIII §10: 5% of floor, min 0.24 m²)"))

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

    # ---------- SOFT: bath door opening into the kitchen ----------
    # PH sanitary practice discourages a toilet door opening directly into a
    # food-prep area. Allowed (e.g., a door_host override consolidating doors
    # on the kitchen circulation aisle), but flagged as a soft-rule trade-off.
    if plan is not None:
        _rid = {r.id: r for r in layout.rooms}
        _BATH_T = {"common_bath", "bath_toilet", "powder_room", "ensuite_bath"}
        for d in plan.doors:
            da, db = _rid.get(d.room_a), _rid.get(d.room_b)
            if da is None or db is None:
                continue
            t = {da.type, db.type}
            if (t & _BATH_T) and "kitchen" in t:
                issues.append(Issue("warning", "bath_door_into_kitchen",
                    f"door {d.room_a}<->{d.room_b}: bath opens directly into "
                    f"the kitchen — sanitary soft rule (accepted trade-off "
                    f"for circulation consolidation)"))

    # ---------- HARD: setback elements must be uncovered & inside a setback ----------
    # `building_void_rects` are intentional carve-outs from the envelope
    # declared by a topology (e.g., a carport cut into the front-left). A
    # setback element that overlaps a void is expected — the void exists
    # precisely so that element can extend into the building footprint.
    void_rects = getattr(layout, "building_void_rects", None) or []
    for e in layout.elements:
        if e.covered:
            issues.append(Issue("error", "covered_in_setback",
                f"{e.type} is covered but sits in a setback (needs firewall or footprint)"))
        # must NOT intrude into the buildable envelope, EXCEPT into the
        # portions reserved as building voids (which are explicitly there).
        if e.rect.overlaps(env):
            # Check whether the envelope-overlap is entirely contained in
            # the union of voids. If so, no warning.
            overlaps_voids_only = any(
                e.rect.overlaps(v) for v in void_rects
            ) and not _element_strays_outside_voids(e.rect, env, void_rects)
            if not overlaps_voids_only:
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
