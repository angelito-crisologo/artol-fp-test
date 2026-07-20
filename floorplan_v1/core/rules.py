"""Loads ph_floorplan_rules.json and exposes per-room hard minimums,
preferred areas, and sizing priorities for the validator and optimizer.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# core/ → floorplan_v1/ → data/ph_floorplan_rules.json (app-local rules file)
_RULES_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "data", "ph_floorplan_rules.json"))

# Priority weights — protection priority (higher = shrinks last when envelope
# is tight). Weights are read by size_priority() below and used in the solver
# objective. Groups map to the size_priority field in ph_floorplan_rules.json.
#
# Order (high → low):
#   private:  master_bedroom > bedroom_standard
#   public:   living_room > kitchen > dining_room
#   service:  service_baths > laundry > maids_room
#   external: external (one tier; sub-order annotated in JSON only)
#
# Key behavioural note: bedroom_standard (5.0) now outweighs living_room (4.0).
# On tight envelopes the solver will sacrifice living area before bedroom area.
# This is intentional (client direction 2026-06-25, Option B protection priority).
PRIORITY_WEIGHT = {
    "master_bedroom":   6.0,
    "bedroom_standard": 5.0,
    "living_room":      4.0,   # also covers great_room, dk_nook
    "kitchen":          3.5,
    "dining_room":      3.0,
    "service_baths":    2.5,   # common_bath, ensuite_bath, powder_room, maids_bath
    "laundry":          2.0,   # service_area
    "maids_room":       1.5,
    "external":         1.0,   # carport, dirty_kitchen, lanai, patio, porch
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
        return r.get("size_priority", "service_baths")

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
