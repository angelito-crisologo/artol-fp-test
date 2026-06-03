"""Setback-element placement helper.

Places the three uncovered exterior elements (carport, dirty kitchen, service
area) around the buildable footprint. Extracted from the legacy subdivision
engine — the only piece of that codebase still in use after the CP-SAT solver
took over.
"""
from model import Lot, Rect, Room


def _setback_elements(lot: Lot, carport_side: str, kitchen: Rect,
                      service_rect_xspan, dirty_kitchen_at: str = "rear",
                      carport_depth_m: float = 5.0,
                      carport_width_m: float = 2.6):
    """Place the three uncovered setback elements (carport, dirty kitchen,
    service area) around the buildable footprint.

    `dirty_kitchen_at`:
      - "rear"  (default): dirty kitchen sits in the rear setback behind kitchen.
      - "side":            dirty kitchen sits in the kitchen-side setback,
                           alongside the kitchen rather than behind it. Useful
                           for open-plan layouts where the kitchen wants to
                           preserve a connection to the rear yard/lanai through
                           the rear elevation rather than have it occupied by
                           the dirty kitchen.

    `carport_depth_m` / `carport_width_m`:
      Per-topology overrides — set when the topology's building_void was
      sized for a non-default carport (e.g., a 5.5 m deep carport whose
      rear edge meets a void of matching depth). Front-parallel carports
      use a fixed 5.0 m width × 2.6 m depth and ignore these overrides.
    """
    elements = []
    if carport_side == "front":
        # HORIZONTAL (parallel-parked) carport across the front setback: the car
        # length runs along the lot width, the car width runs into the lot.
        # Only ~3 m of front setback is needed, not the 5 m of a side carport.
        cx_center = lot.width / 2.0
        cx0 = cx_center - 2.5
        cx1 = cx_center + 2.5
        cy0 = 0.3
        cy1 = cy0 + 2.6
        elements.append(Room("carport", "carport",
                             Rect(cx0, cy0, cx1, cy1), "service", covered=False))
    elif carport_side == "right":
        # Side carport sits in the right setback strip, with its FRONT EDGE
        # flush against the lot's front line (street side, with a small 0.3 m
        # buffer for the property edge). The car enters directly from the
        # street rather than driving past the front setback to reach it.
        cx1 = lot.width - 0.4
        cx0 = cx1 - carport_width_m
        cy0 = 0.3
        cy1 = cy0 + carport_depth_m
        elements.append(Room("carport", "carport",
                             Rect(cx0, cy0, cx1, cy1), "service", covered=False))
    else:  # "left"
        cx0 = 0.4
        cx1 = cx0 + carport_width_m
        cy0 = 0.3
        cy1 = cy0 + carport_depth_m
        elements.append(Room("carport", "carport",
                             Rect(cx0, cy0, cx1, cy1), "service", covered=False))
    rear_y0 = lot.depth - lot.rear + 0.1
    rear_y1 = lot.depth - 0.3

    if dirty_kitchen_at == "side":
        # Side placement — alongside the kitchen in the kitchen-side setback
        # (the wider side, by canonical orientation the right). Past the
        # carport's y range so they don't overlap.
        if lot.right >= lot.left:
            dk_x1 = lot.width - 0.3
            dk_x0 = lot.width - lot.right + 0.1
        else:
            dk_x0 = 0.3
            dk_x1 = lot.left - 0.1
        elements.append(Room("dirty_kitchen", "dirty_kitchen",
                             Rect(dk_x0, kitchen.y0, dk_x1, kitchen.y1),
                             "service", covered=False))
    else:
        # Default — rear placement, immediately behind the kitchen.
        elements.append(Room("dirty_kitchen", "dirty_kitchen",
                             Rect(kitchen.x0, rear_y0, kitchen.x1, rear_y1),
                             "service", covered=False))

    sx0, sx1 = service_rect_xspan
    elements.append(Room("service_area", "service_area",
                         Rect(sx0, rear_y0, sx1, rear_y1), "service", covered=False))
    return elements
