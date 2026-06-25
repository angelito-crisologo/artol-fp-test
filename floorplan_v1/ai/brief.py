"""User brief — structured input the pipeline turns into a topology."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Brief:
    """What a user provides to the pipeline.

    Free-text `intent` carries the design feeling and special requests. The
    structured fields (lot, program) cover the things the LLM needs to be
    precise about. Anything not specified gets a sensible default."""
    intent: str                                    # natural-language brief
    lot_width: float                               # m, street frontage
    lot_depth: float                               # m, front to rear
    bedroom_count: int = 2
    must_haves: List[str] = field(default_factory=list)   # e.g. ["dirty kitchen", "open plan"]
    avoid: List[str] = field(default_factory=list)
    carport_side: Optional[str] = None             # "left" | "right" | "front" | None (None = ncp)
    carport_type: Optional[str] = None             # "fcp" | "ccp" | None (None = ncp)
    # Optional explicit setbacks (m) — keys: front, rear, left, right.
    # When given, overrides carport_side/carport_type geometry; useful
    # for firewall configs (right=0) or any non-symmetric setback need.
    setbacks: Optional[Dict[str, float]] = None
    # PD 1096 / IRR Rule VII residential occupancy class. Drives setback
    # minimums (W-H11) and firewall legality (W-H10: R-1 cannot have a
    # firewall on any side; R-2 may have one on a single side; R-3 may
    # have multiple). Defaults to R-1 (single-detached) — the project's
    # primary target.
    occupancy_class: str = "R-1"
    # When True, the runner swaps the placements of master_bedroom and
    # bedroom_standard before passing the topology to the solver. Use this
    # to flip from the topology's canonical "master at front" layout to a
    # "master at rear" layout (more typical of PH bungalow practice — quieter,
    # wet-stack-aligned, garden-adjacent) without authoring a separate
    # topology file. See solver/topology.py::swap_master_standard_in_topology
    # for exactly what the transform changes.
    swap_master_standard: bool = False
    # Optional door-host overrides: {room_id: neighbor_room_id}. For a room
    # whose topology declares a door_host_group (alternate door-host walls),
    # this picks WHICH neighbor's shared wall hosts the room's door — e.g.
    # {"common": "kitchen"} moves the common T&B door from its default host
    # (typically the great_room wall) onto the kitchen wall, freeing the
    # default wall to stay solid. Invalid or geometrically un-honorable
    # overrides fall back to the topology's default host.
    door_host: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------ #
    # Bedroom program                                                       #
    # ------------------------------------------------------------------ #
    # When False (default): bedroom_count > 1 → 1 master + (N-1) standard.
    # When True: all bedrooms are standard (no master, no ensuite).
    # Note: requires a topology variant that omits the master_bedroom room
    # type; the solver will error if the chosen topology still has a master.
    no_master: bool = False

    # ------------------------------------------------------------------ #
    # External / service spaces  (all opt-in except porch)                 #
    # ------------------------------------------------------------------ #
    # Porch: always on — uncovered landing in front of the living room,
    # door leading into living room. Size and depth governed by the topology.
    # (No field needed — porch is unconditional.)

    # Kitchen back door: service door from kitchen to exterior (rear setback /
    # dirty kitchen). Default on — PH practice always has a kitchen back door.
    # Set False only to explicitly seal the kitchen's rear wall.
    kitchen_back_door: bool = True

    # Dirty kitchen: open-air cooking area in rear setback. Default off.
    dirty_kitchen: bool = False

    # Service/laundry area: open-air wash area in rear setback. Default off.
    # Note: PD 1096 Sec. 708(c) requires washing facilities; when False the
    # validator will soft-warn unless a laundry area is present inside the plan.
    service_area: bool = False

    # Lanai: semi-outdoor living extension, typically rear or side. Default off.
    lanai: bool = False

    # Patio: outdoor paved area. Default off.
    patio: bool = False

    # ------------------------------------------------------------------ #
    # Bath count                                                            #
    # ------------------------------------------------------------------ #
    # Explicit T&B count requirement. When None, the solver applies the
    # default rule: if total floor area >= 65 m² → 2 baths; else → 1 bath.
    # Powder room (half-bath) is NOT counted toward num_baths — it is a
    # separate opt-in addition to the full bath(s).
    num_baths: Optional[int] = None

    # Powder room (half-bath: toilet + lavatory, no shower). Opt-in; default
    # off. When True, the selected topology must include a powder_room room.
    # bath_token in the topology name will be "bath_pwd" (single common bath +
    # powder room) rather than "bath".
    powder_room: bool = False

    @property
    def lot_area(self) -> float:
        return round(self.lot_width * self.lot_depth, 2)

    def summary(self) -> str:
        parts = [
            f"{self.bedroom_count}-bedroom",
            f"{self.lot_width:.1f}x{self.lot_depth:.1f} m lot ({self.lot_area:.0f} sqm)",
        ]
        if self.must_haves:
            parts.append("must have: " + ", ".join(self.must_haves))
        if self.avoid:
            parts.append("avoid: " + ", ".join(self.avoid))
        if self.carport_side:
            parts.append(f"carport: {self.carport_type or 'ccp'} on {self.carport_side}")
        return " | ".join(parts) + f"\nintent: {self.intent}"
