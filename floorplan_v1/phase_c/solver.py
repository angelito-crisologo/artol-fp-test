"""Phase C.1 — CP-SAT geometric solver from an adjacency-graph topology.

Takes a Topology + Lot + Rules and produces a Layout by solving for room
rectangles that satisfy every hard PD 1096 rule and every required adjacency,
optimizing a weighted-area objective biased toward PH room priorities.

Hard constraints encoded:
  - each room within the buildable envelope
  - AddNoOverlap2D over all rooms
  - min least-dimension (w >= min_least, h >= min_least)
  - min area (via AddMultiplicationEquality)
  - shared-wall adjacency >= the topology's min_shared_wall_m (4-way disjunction)
  - window access: each habitable room touches the envelope boundary on >=1 side

Setback elements (carport / dirty kitchen / service area) are placed
deterministically after the solver runs, the same way the templates do.
"""
import os
import sys
from typing import Dict, List
from ortools.sat.python import cp_model

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # let us import the shared modules

from model import Lot, Rect, Room, Layout         # noqa: E402
from rules import Rules                           # noqa: E402
from engine import _setback_elements              # noqa: E402  (helper reuse only)

from topology import Topology                     # noqa: E402

GRID_CM = 5                                       # 5 cm grid resolution


class AdjustmentError(ValueError):
    """User-side error in the brief's `adjustments` block — distinct from any
    error that the solver could otherwise produce.

    Why it matters: callers should NOT treat this like a stale-cache signal
    (so don't wipe the cache) and should NOT feed it into the LLM repair loop
    (Claude can't fix a typo in the brief). It surfaces cleanly to the user,
    who fixes the brief and reruns."""
    pass

PRIORITY_WEIGHTS = {
    "public_LDK":        4,
    "master_bedroom":    3,
    "other_bedrooms":    2,
    "service_and_baths": 1,
}

HABITABLE = {"bedroom_standard", "master_bedroom", "living_room",
             "dining_room", "great_room", "maids_room"}


# Per-type hard aspect cap. Encoded as (numerator, denominator) so we can
# express non-integer ratios like 1.8:1 inside the integer CP-SAT model.
# The constraint w*den <= h*num is equivalent to w/h <= num/den; we apply it
# in both directions so neither side of the room can exceed the ratio.
ASPECT_CAPS = {
    "master_bedroom":   (9, 5),   # 1.8:1 — bedrooms shouldn't read as corridors
    "bedroom_standard": (9, 5),
    "maids_room":       (2, 1),   # 2:1
    "living_room":      (9, 5),   # 1.8:1
    "great_room":       (9, 5),
    "dining_room":      (2, 1),   # 2:1 — slightly tolerant, bench-along-wall OK
    "kitchen":          (5, 2),   # 2.5:1 — galley kitchens are legitimate
    "hallway":          (4, 1),   # 4:1 — hallways ARE corridors
    "ensuite_bath":     (2, 1),   # unchanged from previous bath cap
    "common_bath":      (2, 1),
    "bath_toilet":      (2, 1),
    "powder_room":      (2, 1),
    "foyer":            (2, 1),
}
DEFAULT_ASPECT = (5, 2)           # 2.5:1 fallback for any unknown type

# Per-type RELAXED aspect cap that kicks in when BOTH sides of the room are
# already "wide enough" (short side >= threshold_m). The corridor feeling
# comes from a narrow short side, not from a long long side: a 4.2 x 8 m
# great room reads as an open LDK, not a corridor, because 4.2 m clears the
# room-vs-corridor threshold. So when both w and h are >= threshold, we let
# the ratio go to the relaxed cap; otherwise the strict ASPECT_CAPS value
# above still binds. Room types not listed here use ASPECT_CAPS unchanged.
# Encoded as (threshold_m, relaxed_num, relaxed_den).
ASPECT_RELAX = {
    "great_room":       (3.0, 5, 2),    # strict 1.8 -> 2.5 when both sides >= 3 m
    "living_room":      (3.0, 5, 2),
    "dining_room":      (3.0, 5, 2),
    "master_bedroom":   (3.0, 11, 5),   # strict 1.8 -> 2.2 when both sides >= 3 m
    "bedroom_standard": (3.0, 11, 5),
    "common_bath":      (2.0, 5, 2),    # strict 2.0 -> 2.5 when both sides >= 2 m
    "ensuite_bath":     (2.0, 5, 2),
    "bath_toilet":      (2.0, 5, 2),
    "powder_room":      (2.0, 5, 2),
    # kitchen (already 2.5:1) and hallway (4:1) intentionally not relaxed.
}

# Bath types that prefer a window over a vent shaft. Soft pull only — interior
# placement is still legal under PD 1096 Sec. 809 (vent shaft), but exterior
# placement is cheaper and more common in PH mid-market practice. The solver
# bonuses any bath in this set when it touches the buildable envelope edge.
BATH_AT_WALL_TYPES = {"common_bath", "ensuite_bath", "bath_toilet", "powder_room"}


# Soft "chunky" preference per room type: the least-dimension threshold the
# solver tries to meet via an objective bonus. Hard cap above still binds;
# this just nudges shapes toward natural-looking proportions inside it.
# Rooms intentionally absent (hallway, foyer) shouldn't be pushed chunky.
CHUNKY_LEAST_M = {
    "master_bedroom":   2.7,
    "bedroom_standard": 2.5,
    "maids_room":       2.2,
    "living_room":      3.0,
    "great_room":       3.0,
    "dining_room":      2.5,
    "kitchen":          2.0,
    "ensuite_bath":     1.5,
    "common_bath":      1.5,
    "bath_toilet":      1.5,
}


def _u(m: float) -> int:
    return int(round(m * 100 / GRID_CM))


def _m(u: int) -> float:
    return round(u * GRID_CM / 100, 2)


def _add_min_max(model, name, kind, a, b, lo, hi):
    """Helper: return an IntVar equal to min(a,b) (kind='min') or max(a,b)."""
    v = model.NewIntVar(lo, hi, name)
    if kind == "min":
        model.AddMinEquality(v, [a, b])
    else:
        model.AddMaxEquality(v, [a, b])
    return v


def solve(topology: Topology, lot: Lot, rules: Rules,
          time_limit_s: float = 30.0, verbose: bool = True,
          adjustments: Dict[str, Dict[str, float]] = None) -> Layout:
    """Solve `topology` into a `Layout` on `lot`. `adjustments` is an optional
    per-room-type override of size constraints:

        {"master_bedroom": {"min_area_sqm": 14, "min_least_dim_m": 3.0},
         "kitchen":        {"max_area_sqm": 7}}

    Each override is applied on TOP of the rules-JSON defaults — `min_area_sqm`
    and `min_least_dim_m` raise the floor (whichever is larger wins);
    `max_area_sqm` lowers the cap. `max_greatest_dim_m` caps the LONGER side
    (max of width/depth) — useful for preventing a room from stretching long
    even when its area is within bounds. `max_least_dim_m` caps the SHORTER
    side, `min_greatest_dim_m` floors the longer side — these two together
    let you force an elongated shape if you want one. If multiple rooms share
    a type, the override applies to all of them."""
    adjustments = adjustments or {}

    # Loud-fail on adjustment keys that don't match any room in the topology.
    # Silent ignore would leave the user wondering why their tweak had no
    # effect — typical cause is using "bedroom" instead of "bedroom_standard"
    # or referring to a room type that this topology doesn't include.
    if adjustments:
        present_types = {r.type for r in topology.rooms}
        unknown = [k for k in adjustments if k not in present_types]
        if unknown:
            valid = sorted(present_types)
            raise AdjustmentError(
                f"adjustments reference room type(s) not in this topology: "
                f"{unknown}. Valid keys for this topology: {valid}"
            )
    env = lot.envelope()
    ex0, ey0 = _u(env.x0), _u(env.y0)
    ex1, ey1 = _u(env.x1), _u(env.y1)
    EW, EH = ex1 - ex0, ey1 - ey0

    model = cp_model.CpModel()

    # ---------- room variables ----------
    rx, ry, rw, rh = {}, {}, {}, {}     # x, y, width, height (in grid units)
    rx_end, ry_end = {}, {}             # x + w, y + h
    xiv, yiv = {}, {}                   # IntervalVars for AddNoOverlap2D
    area = {}                           # area = w * h  (in grid-unit^2)
    meets_pref = {}                     # BoolVar: area >= preferred-low (soft floor)
    has_pref = {}                       # whether room has a preferred range
    pref_low_u2 = {}

    OVERSIZE_MULT = 1.0                 # cap area at preferred-high (no slop)
    chunky_bonus = {}                   # room_id -> BoolVar (least dim >= CHUNKY_LEAST_M)

    for r in topology.rooms:
        min_least_m = rules.hard_min_least(r.type) or 0.0
        min_area_m  = rules.hard_min_area(r.type)  or 0.0
        pref = rules.preferred_area_range(r.type)
        if pref:
            cap_m = pref[1] * OVERSIZE_MULT
            plo_m = pref[0]
            has_pref[r.id] = True
        else:
            cap_m = max(min_area_m * 4.0, 30.0)
            plo_m = min_area_m
            has_pref[r.id] = False

        # ---- per-room-type adjustments from the brief ----
        # min_area_sqm / min_least_dim_m raise floors (take the larger of
        # rules-default and override). max_area_sqm lowers the cap.
        # max_greatest_dim_m caps the LONGER side. Adjustments are applied
        # here BEFORE the grid-unit conversion so all downstream constraints
        # see the overridden values.
        adj = adjustments.get(r.type, {})
        max_greatest_dim_m = None   # caps max(w, h)
        max_least_dim_m    = None   # caps min(w, h) -- needs OR constraint
        min_greatest_dim_m = None   # floors max(w, h) -- needs OR constraint
        if adj:
            if "min_area_sqm" in adj:
                min_area_m = max(min_area_m, float(adj["min_area_sqm"]))
            if "min_least_dim_m" in adj:
                min_least_m = max(min_least_m, float(adj["min_least_dim_m"]))
            if "max_area_sqm" in adj:
                cap_m = min(cap_m, float(adj["max_area_sqm"]))
            if "max_greatest_dim_m" in adj:
                max_greatest_dim_m = float(adj["max_greatest_dim_m"])
            if "max_least_dim_m" in adj:
                max_least_dim_m = float(adj["max_least_dim_m"])
            if "min_greatest_dim_m" in adj:
                min_greatest_dim_m = float(adj["min_greatest_dim_m"])
            # If min_area override is now above the preferred-low we treat
            # preferred-low as met by default — the bonus shouldn't shut off
            # just because the room is being forced bigger.
            if min_area_m > plo_m:
                plo_m = min_area_m
            # Defensive sanity: if max < min, the model will be infeasible,
            # which is the correct outcome (the user's tweak is impossible).

        min_least_u = max(_u(min_least_m), 1)
        min_area_u2 = int(round(min_area_m * 10000 / (GRID_CM * GRID_CM)))
        cap_area_u2 = int(round(cap_m * 10000 / (GRID_CM * GRID_CM)))
        pref_low_u2[r.id] = int(round(plo_m * 10000 / (GRID_CM * GRID_CM)))

        # max_greatest_dim_m caps each side directly: max(w, h) <= cap ⟺
        # w <= cap ∧ h <= cap. Clamp into the IntVar upper bound rather than
        # adding two explicit constraints — cheaper for the solver.
        max_w_u = EW
        max_h_u = EH
        if max_greatest_dim_m is not None:
            cap_u = max(_u(max_greatest_dim_m), min_least_u)
            max_w_u = min(max_w_u, cap_u)
            max_h_u = min(max_h_u, cap_u)

        rx[r.id] = model.NewIntVar(ex0, ex1, f"x_{r.id}")
        ry[r.id] = model.NewIntVar(ey0, ey1, f"y_{r.id}")
        rw[r.id] = model.NewIntVar(min_least_u, max_w_u, f"w_{r.id}")
        rh[r.id] = model.NewIntVar(min_least_u, max_h_u, f"h_{r.id}")

        # ---- the two "min/max of width and height" knobs need OR reification ----
        # max_least_dim_m caps the shorter side: min(w, h) <= cap ⟺ w<=cap ∨ h<=cap.
        # Reify each side and add a BoolOr so at least one is true.
        if max_least_dim_m is not None:
            cap_u = _u(max_least_dim_m)
            b_w_le = model.NewBoolVar(f"max_least_w_le_{r.id}")
            b_h_le = model.NewBoolVar(f"max_least_h_le_{r.id}")
            model.Add(rw[r.id] <= cap_u).OnlyEnforceIf(b_w_le)
            model.Add(rw[r.id] >  cap_u).OnlyEnforceIf(b_w_le.Not())
            model.Add(rh[r.id] <= cap_u).OnlyEnforceIf(b_h_le)
            model.Add(rh[r.id] >  cap_u).OnlyEnforceIf(b_h_le.Not())
            model.AddBoolOr([b_w_le, b_h_le])

        # min_greatest_dim_m floors the longer side: max(w, h) >= floor ⟺
        # w>=floor ∨ h>=floor. Same OR reification pattern.
        if min_greatest_dim_m is not None:
            floor_u = _u(min_greatest_dim_m)
            b_w_ge = model.NewBoolVar(f"min_great_w_ge_{r.id}")
            b_h_ge = model.NewBoolVar(f"min_great_h_ge_{r.id}")
            model.Add(rw[r.id] >= floor_u).OnlyEnforceIf(b_w_ge)
            model.Add(rw[r.id] <  floor_u).OnlyEnforceIf(b_w_ge.Not())
            model.Add(rh[r.id] >= floor_u).OnlyEnforceIf(b_h_ge)
            model.Add(rh[r.id] <  floor_u).OnlyEnforceIf(b_h_ge.Not())
            model.AddBoolOr([b_w_ge, b_h_ge])
        rx_end[r.id] = model.NewIntVar(ex0, ex1, f"xe_{r.id}")
        ry_end[r.id] = model.NewIntVar(ey0, ey1, f"ye_{r.id}")
        model.Add(rx_end[r.id] == rx[r.id] + rw[r.id])
        model.Add(ry_end[r.id] == ry[r.id] + rh[r.id])

        # aspect ratio cap (per-type — bedrooms 1.8, kitchen 2.5, hallway 4, etc.)
        # If the type is in ASPECT_RELAX, we apply the cap CONDITIONALLY:
        # when both sides are >= threshold_m the relaxed cap binds; otherwise
        # the strict ASPECT_CAPS value binds. Rationale: a corridor feeling
        # comes from a narrow short side, not from a long long side.
        ar_num, ar_den = ASPECT_CAPS.get(r.type, DEFAULT_ASPECT)
        relax = ASPECT_RELAX.get(r.type)
        if relax is None:
            # Unconditional: just the strict cap on both orientations.
            model.Add(rw[r.id] * ar_den <= rh[r.id] * ar_num)
            model.Add(rh[r.id] * ar_den <= rw[r.id] * ar_num)
        else:
            threshold_m, rel_num, rel_den = relax
            t_u = max(_u(threshold_m), 1)
            # w_wide_a / h_wide_a track whether each side clears the threshold.
            # chunky_a = both sides clear it (so the short side, whichever it
            # is, is at least threshold_m).
            w_wide = model.NewBoolVar(f"wwa_{r.id}")
            h_wide = model.NewBoolVar(f"hwa_{r.id}")
            chunky_a = model.NewBoolVar(f"chunkya_{r.id}")
            model.Add(rw[r.id] >= t_u).OnlyEnforceIf(w_wide)
            model.Add(rw[r.id] <  t_u).OnlyEnforceIf(w_wide.Not())
            model.Add(rh[r.id] >= t_u).OnlyEnforceIf(h_wide)
            model.Add(rh[r.id] <  t_u).OnlyEnforceIf(h_wide.Not())
            model.AddBoolAnd([w_wide, h_wide]).OnlyEnforceIf(chunky_a)
            model.AddBoolOr([w_wide.Not(), h_wide.Not()]).OnlyEnforceIf(chunky_a.Not())
            # When chunky_a -> relaxed cap binds (both orientations).
            model.Add(rw[r.id] * rel_den <= rh[r.id] * rel_num).OnlyEnforceIf(chunky_a)
            model.Add(rh[r.id] * rel_den <= rw[r.id] * rel_num).OnlyEnforceIf(chunky_a)
            # When NOT chunky_a -> strict cap binds (both orientations).
            model.Add(rw[r.id] * ar_den <= rh[r.id] * ar_num).OnlyEnforceIf(chunky_a.Not())
            model.Add(rh[r.id] * ar_den <= rw[r.id] * ar_num).OnlyEnforceIf(chunky_a.Not())

        xiv[r.id] = model.NewIntervalVar(rx[r.id], rw[r.id], rx_end[r.id], f"xiv_{r.id}")
        yiv[r.id] = model.NewIntervalVar(ry[r.id], rh[r.id], ry_end[r.id], f"yiv_{r.id}")

        area[r.id] = model.NewIntVar(0, EW * EH, f"area_{r.id}")
        model.AddMultiplicationEquality(area[r.id], [rw[r.id], rh[r.id]])
        if min_area_u2:
            model.Add(area[r.id] >= min_area_u2)
        model.Add(area[r.id] <= cap_area_u2)

        # "meets preferred low" BoolVar (soft floor for the objective)
        mp = model.NewBoolVar(f"mp_{r.id}")
        model.Add(area[r.id] >= pref_low_u2[r.id]).OnlyEnforceIf(mp)
        model.Add(area[r.id] <  pref_low_u2[r.id]).OnlyEnforceIf(mp.Not())
        meets_pref[r.id] = mp

        # Soft "chunky" preference: BoolVar that both w and h >= the per-type
        # CHUNKY_LEAST_M threshold. Pulls every applicable room toward natural
        # proportions (a master bedroom prefers >= 2.7 m on its short side,
        # living >= 3.0 m, etc.) without making narrow shapes infeasible.
        # Rooms absent from CHUNKY_LEAST_M (hallway, foyer) get no nudge —
        # they're allowed to stay corridor-shaped.
        chunky_least = CHUNKY_LEAST_M.get(r.type)
        if chunky_least is not None:
            pref_lu = _u(chunky_least)
            w_ok = model.NewBoolVar(f"wok_{r.id}")
            h_ok = model.NewBoolVar(f"hok_{r.id}")
            model.Add(rw[r.id] >= pref_lu).OnlyEnforceIf(w_ok)
            model.Add(rw[r.id] <  pref_lu).OnlyEnforceIf(w_ok.Not())
            model.Add(rh[r.id] >= pref_lu).OnlyEnforceIf(h_ok)
            model.Add(rh[r.id] <  pref_lu).OnlyEnforceIf(h_ok.Not())
            chunky = model.NewBoolVar(f"chunky_{r.id}")
            model.AddBoolAnd([w_ok, h_ok]).OnlyEnforceIf(chunky)
            model.AddBoolOr([w_ok.Not(), h_ok.Not()]).OnlyEnforceIf(chunky.Not())
            chunky_bonus[r.id] = chunky

    # ---------- building voids ----------
    # Each void is a fixed-position rectangle inside the envelope that rooms
    # can't overlap. Anchored to one of the four envelope corners by the
    # void's `location` field. The solver treats them as constant-position
    # IntervalVars that join the NoOverlap2D constraint.
    void_xiv = []
    void_yiv = []
    for v in (topology.building_voids or []):
        vw = _u(v.width_m)
        vh = _u(v.depth_m)
        loc = (v.location or "").lower()
        if loc == "front_left":
            vx0, vy0 = ex0, ey0
        elif loc == "front_right":
            vx0, vy0 = ex1 - vw, ey0
        elif loc == "rear_left":
            vx0, vy0 = ex0, ey1 - vh
        elif loc == "rear_right":
            vx0, vy0 = ex1 - vw, ey1 - vh
        else:
            # Unknown location: skip (warn at validation level if needed).
            continue
        vx_const = model.NewConstant(vx0)
        vy_const = model.NewConstant(vy0)
        vx_end = model.NewConstant(vx0 + vw)
        vy_end = model.NewConstant(vy0 + vh)
        vxi = model.NewIntervalVar(vx_const, vw, vx_end, f"void_xiv_{v.id}")
        vyi = model.NewIntervalVar(vy_const, vh, vy_end, f"void_yiv_{v.id}")
        void_xiv.append(vxi)
        void_yiv.append(vyi)

    # ---------- no overlap among rooms (+ building voids) ----------
    model.AddNoOverlap2D(list(xiv.values()) + void_xiv,
                         list(yiv.values()) + void_yiv)

    # ---------- window access: each habitable room touches the envelope boundary ----------
    for r in topology.rooms:
        if r.type not in HABITABLE:
            continue
        at_left  = model.NewBoolVar(f"bL_{r.id}")
        at_right = model.NewBoolVar(f"bR_{r.id}")
        at_front = model.NewBoolVar(f"bF_{r.id}")
        at_rear  = model.NewBoolVar(f"bRr_{r.id}")
        model.Add(rx[r.id]     == ex0).OnlyEnforceIf(at_left)
        model.Add(rx[r.id]     != ex0).OnlyEnforceIf(at_left.Not())
        model.Add(rx_end[r.id] == ex1).OnlyEnforceIf(at_right)
        model.Add(rx_end[r.id] != ex1).OnlyEnforceIf(at_right.Not())
        model.Add(ry[r.id]     == ey0).OnlyEnforceIf(at_front)
        model.Add(ry[r.id]     != ey0).OnlyEnforceIf(at_front.Not())
        model.Add(ry_end[r.id] == ey1).OnlyEnforceIf(at_rear)
        model.Add(ry_end[r.id] != ey1).OnlyEnforceIf(at_rear.Not())
        model.AddBoolOr([at_left, at_right, at_front, at_rear])

    # ---------- soft preference: baths touch the envelope (window ventilation) ----------
    # Identical boundary detection as above but as a soft preference rather than
    # a hard constraint. Bath touches exterior -> True -> objective bonus. Does
    # NOT prevent interior baths; they're legal with a vent shaft (Sec. 809).
    bath_at_wall = {}    # room_id -> BoolVar (any boundary touched)
    for r in topology.rooms:
        if r.type not in BATH_AT_WALL_TYPES:
            continue
        at_left  = model.NewBoolVar(f"bwL_{r.id}")
        at_right = model.NewBoolVar(f"bwR_{r.id}")
        at_front = model.NewBoolVar(f"bwF_{r.id}")
        at_rear  = model.NewBoolVar(f"bwRr_{r.id}")
        model.Add(rx[r.id]     == ex0).OnlyEnforceIf(at_left)
        model.Add(rx[r.id]     != ex0).OnlyEnforceIf(at_left.Not())
        model.Add(rx_end[r.id] == ex1).OnlyEnforceIf(at_right)
        model.Add(rx_end[r.id] != ex1).OnlyEnforceIf(at_right.Not())
        model.Add(ry[r.id]     == ey0).OnlyEnforceIf(at_front)
        model.Add(ry[r.id]     != ey0).OnlyEnforceIf(at_front.Not())
        model.Add(ry_end[r.id] == ey1).OnlyEnforceIf(at_rear)
        model.Add(ry_end[r.id] != ey1).OnlyEnforceIf(at_rear.Not())
        at_wall = model.NewBoolVar(f"bw_{r.id}")
        # OR-reified: at_wall <=> any boundary touched
        model.AddBoolOr([at_left, at_right, at_front, at_rear]).OnlyEnforceIf(at_wall)
        model.AddBoolAnd([at_left.Not(), at_right.Not(),
                          at_front.Not(), at_rear.Not()]).OnlyEnforceIf(at_wall.Not())
        bath_at_wall[r.id] = at_wall

    # ---------- room-type placement rules ----------
    # Kitchen must touch the REAR exterior wall — so the dirty kitchen in the
    # rear setback is genuinely adjacent ("kitchen opens out to dirty kitchen").
    # Living room must touch the FRONT exterior wall — so the main entry is on
    # the street side ("living room accessible from the front").
    for r in topology.rooms:
        if r.type == "kitchen":
            model.Add(ry_end[r.id] == ey1)
        if r.type == "living_room":
            model.Add(ry[r.id] == ey0)

    # ---------- zone split (optional hard partition) ----------
    # When the topology declares a zone_split, every room in private_rooms is
    # confined to one half of the envelope and every room in public_rooms to
    # the other half. The split position is itself an IntVar so the solver
    # chooses where the dividing wall falls.
    if topology.zone_split is not None:
        zs = topology.zone_split
        if zs.axis == "vertical":
            split = model.NewIntVar(ex0, ex1, "split_x")
            if zs.private_side == "left":
                for rid in zs.private_rooms:
                    if rid in rx_end: model.Add(rx_end[rid] <= split)
                for rid in zs.public_rooms:
                    if rid in rx: model.Add(rx[rid] >= split)
            else:   # private_side == "right"
                for rid in zs.private_rooms:
                    if rid in rx: model.Add(rx[rid] >= split)
                for rid in zs.public_rooms:
                    if rid in rx_end: model.Add(rx_end[rid] <= split)
        elif zs.axis == "horizontal":
            split = model.NewIntVar(ey0, ey1, "split_y")
            if zs.private_side == "front":
                for rid in zs.private_rooms:
                    if rid in ry_end: model.Add(ry_end[rid] <= split)
                for rid in zs.public_rooms:
                    if rid in ry: model.Add(ry[rid] >= split)
            else:   # private_side == "rear"
                for rid in zs.private_rooms:
                    if rid in ry: model.Add(ry[rid] >= split)
                for rid in zs.public_rooms:
                    if rid in ry_end: model.Add(ry_end[rid] <= split)

    # ---------- master-bigger-than-standard hard rule ----------
    # PH convention: the master bedroom is always larger than the other
    # bedroom. Without this, priority weights only bias the objective; the
    # solver can still leave master at its hard minimum if other rooms grow
    # to absorb the available space. Enforce a strict ordering with a small
    # 1 sqm margin so master is meaningfully (not just incidentally) larger.
    master_id = next((r.id for r in topology.rooms if r.type == "master_bedroom"), None)
    standard_id = next((r.id for r in topology.rooms if r.type == "bedroom_standard"), None)
    if master_id is not None and standard_id is not None:
        margin_u2 = int(round(1.0 * 10000 / (GRID_CM * GRID_CM)))   # 1 sqm in grid units²
        model.Add(area[master_id] >= area[standard_id] + margin_u2)

        # Optional design intent: bedrooms share the same width. Used by
        # topologies where the geometry should look symmetric (e.g., bath block
        # between matched-width bedrooms). With area[master] >= area[standard]+1
        # already enforced above, matching widths forces master.depth to grow
        # relative to standard.depth — the size hierarchy moves to the
        # perpendicular axis instead of widening master past standard.
        if topology.match_bedroom_widths:
            model.Add(rw[master_id] == rw[standard_id])

    # ---------- front-to-rear stack ordering hints ----------
    # Each list is a chain of rooms that must stack front-to-rear: rooms[i] in
    # front of rooms[i+1]. Implemented as y_end[i] <= y[i+1], which forces a
    # horizontal shared wall (or a gap) between consecutive rooms rather than
    # allowing them to sit side-by-side. Used by topologies whose design
    # intent calls for a specific vertical column ordering (e.g., an LDK
    # column with living-dining-kitchen front-to-rear, or a private column
    # with standard-baths-master front-to-rear).
    for stack in topology.front_to_rear_stacks:
        for a, b in zip(stack, stack[1:]):
            if a in ry_end and b in ry:
                model.Add(ry_end[a] <= ry[b])

    # ---------- rear-anchored rooms ----------
    # Kitchen is already pinned to the rear wall via a hard solver rule.
    # Topologies can opt other rooms into the same anchoring (e.g., dining)
    # to force side-by-side LDK arrangements: when two adjacent rooms both
    # touch the rear, they can't be stacked front-to-rear and must share a
    # vertical wall instead.
    for rid in topology.rear_anchored:
        if rid in ry_end:
            model.Add(ry_end[rid] == ey1)

    # ---------- left-anchored / right-anchored rooms ----------
    # Force specific rooms to touch the LEFT or RIGHT exterior wall. Used to
    # eliminate wasted-space gaps when a wing's rooms don't fill the envelope
    # width and the solver has freedom to pick where the gap goes. Pinning
    # the wing's east-most or west-most room to its exterior wall closes the
    # gap on that side.
    for rid in topology.left_anchored:
        if rid in rx:
            model.Add(rx[rid] == ex0)
    for rid in topology.right_anchored:
        if rid in rx_end:
            model.Add(rx_end[rid] == ex1)

    # ---------- canonical orientation (symmetry break) ----------
    # Anchor the kitchen on the RIGHT half of the envelope. With an x-symmetric
    # topology, the layout and its left-right mirror score identically; without
    # this constraint, the multi-shot would produce two carport candidates that
    # are pure mirrors. Pinning kitchen-on-right makes left-carport vs
    # right-carport genuinely different design choices (carport opposite the
    # kitchen vs carport next to the kitchen) rather than redundant flips.
    kitchen_id = next((r.id for r in topology.rooms if r.type == "kitchen"), None)
    if kitchen_id is not None:
        # 2 * center_x(kitchen) >= 2 * center_x(envelope)
        model.Add(rx[kitchen_id] + rx_end[kitchen_id] >= ex0 + ex1)

    # ---------- adjacency: shared wall of length >= min_shared_wall_m ----------
    for adj in topology.adjacencies:
        a, b = adj.a, adj.b
        L = max(_u(adj.min_shared_wall_m), 1)
        # 4 orientations: a-right==b-left, a-left==b-right, a-rear==b-front, a-front==b-rear
        vr = model.NewBoolVar(f"adj_{a}_{b}_R")
        vl = model.NewBoolVar(f"adj_{a}_{b}_L")
        hf = model.NewBoolVar(f"adj_{a}_{b}_Rr")   # a behind b (a.y0 == b.y1)
        hr = model.NewBoolVar(f"adj_{a}_{b}_F")    # a in front of b (a.y1 == b.y0)

        # vr: a is left of b -> a.x1 == b.x0, vertical overlap >= L
        model.Add(rx_end[a] == rx[b]).OnlyEnforceIf(vr)
        top_v  = _add_min_max(model, f"top_v_{a}_{b}",  "min", ry_end[a], ry_end[b], ey0, ey1)
        bot_v  = _add_min_max(model, f"bot_v_{a}_{b}",  "max", ry[a],     ry[b],     ey0, ey1)
        model.Add(top_v - bot_v >= L).OnlyEnforceIf(vr)

        # vl: a is right of b -> a.x0 == b.x1, vertical overlap >= L
        model.Add(rx[a] == rx_end[b]).OnlyEnforceIf(vl)
        top_vl = _add_min_max(model, f"top_vl_{a}_{b}", "min", ry_end[a], ry_end[b], ey0, ey1)
        bot_vl = _add_min_max(model, f"bot_vl_{a}_{b}", "max", ry[a],     ry[b],     ey0, ey1)
        model.Add(top_vl - bot_vl >= L).OnlyEnforceIf(vl)

        # hf: a is rear of b -> a.y0 == b.y1, horizontal overlap >= L
        model.Add(ry[a] == ry_end[b]).OnlyEnforceIf(hf)
        right_hf = _add_min_max(model, f"r_hf_{a}_{b}", "min", rx_end[a], rx_end[b], ex0, ex1)
        left_hf  = _add_min_max(model, f"l_hf_{a}_{b}", "max", rx[a],     rx[b],     ex0, ex1)
        model.Add(right_hf - left_hf >= L).OnlyEnforceIf(hf)

        # hr: a is front of b -> a.y1 == b.y0, horizontal overlap >= L
        model.Add(ry_end[a] == ry[b]).OnlyEnforceIf(hr)
        right_hr = _add_min_max(model, f"r_hr_{a}_{b}", "min", rx_end[a], rx_end[b], ex0, ex1)
        left_hr  = _add_min_max(model, f"l_hr_{a}_{b}", "max", rx[a],     rx[b],     ex0, ex1)
        model.Add(right_hr - left_hr >= L).OnlyEnforceIf(hr)

        model.AddBoolOr([vr, vl, hf, hr])

    # ---------- objective ----------
    # Three tiers:
    #  (1) BIG bonus for each room that meets its preferred-low (soft floor)
    #  (2) weighted-area term to fill the envelope by PH priority
    #  (3) negative Manhattan-distance term for each soft proximity pair
    BIG = EW * EH                       # ~ max grid area; dominates the area term
    terms = []
    for r in topology.rooms:
        w = PRIORITY_WEIGHTS.get(r.size_priority, 1)
        terms.append(area[r.id] * w)
        if has_pref[r.id]:
            terms.append(meets_pref[r.id] * BIG * w)
        # Chunky-proportion bonus: scaled by room priority so high-priority
        # rooms (master, LDK) get a stronger pull to chunky shapes than
        # service rooms. BIG//4 is the bath-baseline; multiplying by the
        # priority weight gives master_bedroom and public_LDK rooms ~3-4x
        # the nudge of a bath without dominating the area term.
        if r.id in chunky_bonus:
            terms.append(chunky_bonus[r.id] * (BIG // 4) * w)
        # Bath-at-exterior-wall bonus: soft pull so common T&B (and any other
        # bath) lands against the buildable envelope when geometry allows —
        # natural window ventilation rather than a vent shaft. Same weight as
        # the chunky bonus so the two preferences are comparable.
        if r.id in bath_at_wall:
            terms.append(bath_at_wall[r.id] * (BIG // 4))

    # soft proximity: penalize Manhattan distance between room centers.
    # Center coords are stored as 2*center (= x0 + x1) to avoid fractions; that
    # makes the distance term equal to 2 * Manhattan distance, which only shifts
    # the weight scaling and not the optimum.
    for sp in topology.soft_proximities:
        a, b = sp.a, sp.b
        dx_raw = model.NewIntVar(-2 * EW, 2 * EW, f"dx_{a}_{b}")
        dy_raw = model.NewIntVar(-2 * EH, 2 * EH, f"dy_{a}_{b}")
        model.Add(dx_raw == rx[a] + rx_end[a] - rx[b] - rx_end[b])
        model.Add(dy_raw == ry[a] + ry_end[a] - ry[b] - ry_end[b])
        adx = model.NewIntVar(0, 2 * EW, f"adx_{a}_{b}")
        ady = model.NewIntVar(0, 2 * EH, f"ady_{a}_{b}")
        model.AddAbsEquality(adx, dx_raw)
        model.AddAbsEquality(ady, dy_raw)
        terms.append(-int(sp.weight) * (adx + ady))

    model.Maximize(sum(terms))

    # ---------- solve ----------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    if verbose:
        print(f"solver status: {solver.StatusName(status)}   "
              f"walltime: {solver.WallTime():.2f}s   "
              f"obj: {solver.ObjectiveValue():.0f}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"no feasible layout (status={solver.StatusName(status)})")

    # ---------- extract solution -> Layout ----------
    rooms = []
    for r in topology.rooms:
        x0 = _m(solver.Value(rx[r.id]))
        y0 = _m(solver.Value(ry[r.id]))
        x1 = _m(solver.Value(rx_end[r.id]))
        y1 = _m(solver.Value(ry_end[r.id]))
        rooms.append(Room(r.id, r.type, Rect(x0, y0, x1, y1), r.zone,
                          mechanical_vent=getattr(r, "mechanical_vent", False)))

    # ---------- carport placement ----------
    # If the topology declares a building_void with consumed_by="carport",
    # that void's location is authoritative: the carport sits along the
    # matching side of the lot.
    # Otherwise fall back to the historical heuristic — whichever side has
    # the widest setback (>= 2.8 m) gets the carport.
    carport_side = None
    for v in (topology.building_voids or []):
        if (v.consumed_by or "").lower() == "carport":
            loc = (v.location or "").lower()
            if loc in ("front_left", "rear_left"):
                carport_side = "left"
            elif loc in ("front_right", "rear_right"):
                carport_side = "right"
            break
    if carport_side is None:
        if lot.front >= 2.8:
            carport_side = "front"
        elif lot.left >= 2.8:
            carport_side = "left"
        else:
            carport_side = "right"

    # dirty kitchen sits behind the solver-placed kitchen; service area spans
    # the rest of the rear-setback width.
    kitchen_rect = next((r.rect for r in rooms if r.type == "kitchen"), env)
    service_xspan = (env.x0, kitchen_rect.x0) if kitchen_rect.x0 > env.x0 \
                    else (kitchen_rect.x1, env.x1)

    # Read topology hint for dirty-kitchen placement. Defaults to "rear" when
    # the topology doesn't say otherwise; a topology can opt into "side"
    # placement by setting setback_elements[type=dirty_kitchen].location to
    # "side_setback".
    dk_at = "rear"
    for sb in topology.setback_elements:
        if sb.type == "dirty_kitchen" and sb.location == "side_setback":
            dk_at = "side"
            break

    elements = _setback_elements(lot, carport_side, kitchen_rect, service_xspan,
                                 dirty_kitchen_at=dk_at)

    layout = Layout(lot=lot, rooms=rooms, elements=elements,
                    carport_side=carport_side, genome={"template": "phase_c_solver"})
    return layout
