"""Loads ph_floorplan_rules.json and exposes per-room hard minimums,
preferred areas, and sizing priorities for the validator and optimizer.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# core/ → floorplan_v1/ → repo root (artol-ai/)
_RULES_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "..", "ph_floorplan_rules.json"))

# Priority tier -> weight. Was (4, 3, 2, 1) which produced LDK-heavy plans
# (LDK:private ≈ 1.7:1). Master is now STRICTLY highest so the solver has
# a positive incentive to shrink LDK rectangles in favour of the master
# bedroom when geometry allows; standard bedrooms moved up to tie with
# LDK so they also get pulled above the preferred-low when there's slack.
# Targets the PH mid-market norm of ~1.4:1 LDK:private.
#
# Note: master's tendency to grow past preferred-high (20 m²) is NOT
# controlled by this weight — that growth happens in post-solve passes
# (snap_gaps + claim_ensuite_alcove), which now respect per-room
# max_area_sqm caps when set (see snap_gaps.py).
PRIORITY_WEIGHT = {
    "public_LDK": 3.0,
    "master_bedroom": 4.0,
    "other_bedrooms": 3.0,
    "service_and_baths": 1.0,
}


class Rules:
    def __init__(self, path: str = _RULES_PATH):
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self._catalog = {r["id"]: r for r in self.data["room_catalog"]}
        self.global_ = self.data["global_constraints"]
        self.setback_policy = self.data["setback_usage_policy"]
        self.sizing = self.data["sizing_policy"]
        self.v1 = self.data["v1_scenario"]

    # ---- hard minimums ----
    def hard_min_area(self, room_type: str) -> float:
        r = self._catalog.get(room_type, {})
        return float(r.get("hard", {}).get("min_area_sqm", 0.0) or 0.0)

    def hard_min_least(self, room_type: str) -> float:
        r = self._catalog.get(room_type, {})
        return float(r.get("hard", {}).get("min_least_dimension_m", 0.0) or 0.0)

    def requires_window(self, room_type: str) -> bool:
        r = self._catalog.get(room_type, {})
        h = r.get("hard", {})
        return bool(h.get("requires_exterior_window") or h.get("requires_natural_light_vent_or_artificial"))

    # ---- preferred sizing ----
    def preferred_area_range(self, room_type: str):
        r = self._catalog.get(room_type, {})
        soft = r.get("soft", {})
        if "preferred_area_sqm" in soft:
            lo, hi = soft["preferred_area_sqm"]
            return float(lo), float(hi)
        dims = soft.get("preferred_dimensions_m")
        if dims:
            a = float(dims[0]) * float(dims[1])
            return a, a
        return None

    def size_priority(self, room_type: str) -> str:
        r = self._catalog.get(room_type, {})
        return r.get("size_priority", "service_and_baths")

    def priority_weight(self, room_type: str) -> float:
        return PRIORITY_WEIGHT.get(self.size_priority(room_type), 1.0)

    def occupancy_cap_pct(self, corner: bool = False) -> float:
        h = self.global_["lot_occupancy"]["hard"]
        return float(h["max_occupancy_corner_lot_pct"] if corner else h["max_occupancy_inside_lot_pct"])

    def valid_room_types(self) -> set:
        """Set of room type ids defined in the room_catalog (master_bedroom,
        bedroom_standard, kitchen, ...). Useful for validating brief inputs
        that reference room types by name."""
        return set(self._catalog.keys())
