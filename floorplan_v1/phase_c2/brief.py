"""User brief — structured input the pipeline turns into a topology."""
from dataclasses import dataclass, field
from typing import List, Optional


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
    carport_preference: Optional[str] = None       # "right" | "left" | "front" | None

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
        if self.carport_preference:
            parts.append(f"carport preference: {self.carport_preference}")
        return " | ".join(parts) + f"\nintent: {self.intent}"
