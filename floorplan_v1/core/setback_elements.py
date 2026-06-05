"""Setback-element placement helper.

Places the three uncovered exterior elements (carport, dirty kitchen, service
area) around the buildable footprint. Extracted from the legacy subdivision
engine — the only piece of that codebase still in use after the CP-SAT solver
took over.
"""
from model import Lot, Rect, Room


def _setback_elements(lot: Lot, carport_side: str, kitchen: Rect,
                      service_rect_xspan, dirty_kitchen_at: str = "rear",
                      service_at: str = "rear",
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

    `service_at`:
      - "rear"  (default): service area fills whatever rear-setback width
                           remains after dirty kitchen takes its bay (so it
                           sits next to dirty kitchen along the rear wall).
      - "side":            service area moves to the OPPOSITE side setback
                           from the carport, occupying a strip alongside the
                           kitchen. Used when a private-zone room (typically
                           the master bedroom after swap_master_standard) sits
                           directly south of the planned rear service strip —
                           keeping a clean rear elevation for the master
                           bedroom while still placing service near the
                           kitchen's plumbing/water supply.

    `carport_depth_m` / `carport_width_m`:
      Per-topology overrides — set when the topology's building_void was
      sized for a non-default carport (e.g., a 5.5 m deep carport whose
      rear edge meets a void of matching depth). Front-parallel carports
      use a fixed 5.0 m width × 2.6 m depth and ignore these overrides.
    """
    elements = []
    if carport_side == "none":
        # Brief opted out of a carport. Skip carport generation; the dirty
        # kitchen + service area still get placed in the rear setback below.
        pass
    elif carport_side == "front":
        # HORIZONTAL (parallel-parked) carport across the front setback: the car
        # length runs along the lot width, the car width runs into the lot.
        # Only ~3 m of front setback is needed, not the 5 m of a side carport.
        cx_center = lot.width / 2.0
        cx0 = cx_center - 2.5
        cx1 = cx_center + 2.5
        cy0 = 0.0
        cy1 = cy0 + 2.6
        elements.append(Room("carport", "carport",
                             Rect(cx0, cy0, cx1, cy1), "service", covered=False))
    elif carport_side == "right":
        # Side carport sits flush with the lot's front-right corner: its right
        # face is on the lot's right property line and its front face is on the
        # lot's front line. This makes the geometry tidy when the topology
        # declares a matching building_void on the front_right corner — a
        # (carport_width_m - side_setback) x (carport_depth_m - front_setback)
        # rectangle is then carved cleanly out of the building envelope.
        cx1 = lot.width
        cx0 = cx1 - carport_width_m
        cy0 = 0.0
        cy1 = cy0 + carport_depth_m
        elements.append(Room("carport", "carport",
                             Rect(cx0, cy0, cx1, cy1), "service", covered=False))
    else:  # "left"
        cx0 = 0.0
        cx1 = cx0 + carport_width_m
        cy0 = 0.0
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

    if service_at == "side":
        # Move service to the side setback ADJACENT to the kitchen — the same
        # side the kitchen sits on, so plumbing/water access stays close to
        # the kitchen wet wall and the service strip doesn't end up behind a
        # bedroom (which is the whole point of routing it off the rear in the
        # first place). The strip spans the kitchen's y-range (its rear half
        # of the side setback). On lots where the kitchen-side setback is
        # also occupied by a side carport, the carport sits at the FRONT of
        # that setback (y=0 to ~5 m) while the kitchen sits at the REAR, so
        # the service strip alongside the kitchen stays clear of the carport.
        env_mid_x = lot.left + (lot.width - lot.left - lot.right) / 2.0
        kitchen_at_right = (kitchen.x1 > env_mid_x)
        if kitchen_at_right:
            svc_x0 = lot.width - lot.right + 0.1
            svc_x1 = lot.width - 0.3
        else:
            svc_x0 = 0.3
            svc_x1 = lot.left - 0.1
        elements.append(Room("service_area", "service_area",
                             Rect(svc_x0, kitchen.y0, svc_x1, kitchen.y1),
                             "service", covered=False))
    else:
        sx0, sx1 = service_rect_xspan
        elements.append(Room("service_area", "service_area",
                             Rect(sx0, rear_y0, sx1, rear_y1),
                             "service", covered=False))
    return elements
