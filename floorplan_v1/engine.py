"""Subdivision engine. Two topology templates:

DEEP  - two front-to-rear spines (private | public), rooms stacked in depth.
        Suits a narrow, deep buildable envelope.
WIDE  - bedrooms + baths as side-by-side strips on one side; living spread
        across the wide front; dining + kitchen side by side at the rear.
        Suits a wide, shallow buildable envelope.

Both keep the shared adjacency intent: living at the front (main entry),
kitchen at the rear (door to the open dirty kitchen/service in the rear
setback), bedrooms clustered and buffered, ensuite off the master, common
bath reachable from the public side. Uncovered setback elements (carport,
dirty kitchen, service area) sit in the surrounding setbacks, never in the
footprint. The public/service spine sits on the carport side.
"""
from typing import Dict, List
from model import Rect, Room, Lot, Layout

DISCRETE_KEYS = ("template", "carport_side", "master_position", "ensuite_position",
                 "supported_shells")

DEFAULTS = {
    # ---- NARROW category (width:depth < 0.80) ----
    "narrow_stacked": {
        "template": "narrow_stacked", "carport_side": "right", "master_position": "rear",
        "supported_shells": ["narrow"],
        "rL": 0.50, "pf1": 0.32, "pf2": 0.18, "pf3": 0.75, "qg1": 0.46, "qg2": 0.55,
    },
    # ---- WIDE category (width:depth >= 1.30) ----
    "wide_hall_notch": {
        # generative wide template with the small hallway notch + bath-band middle.
        "template": "wide_hall_notch", "carport_side": "right", "master_position": "rear",
        "ensuite_position": "alongside_master",  # alongside_master | twin_mid | twin_side
        "supported_shells": ["wide"],
        "wL": 0.40, "hp1": 0.40, "hp2": 0.28, "we": 0.34, "pfront": 0.50, "pdk": 0.50,
    },
    "wide_central_hall": {
        # faithful to bungalow_wide: bedrooms stacked left, ensuite at the front-left
        # corner, common T&B rear-center sharing a wall with the kitchen, central hall.
        "template": "wide_central_hall", "carport_side": "right",
        "supported_shells": ["wide"],
        "wcL": 0.55, "wcf": 0.45, "wce": 0.34, "wcCommon": 0.28, "lf": 0.42, "dk": 0.5,
    },
    # ---- SQUARISH category (0.80 <= width:depth < 1.30) ----
    "squarish_two_bedroom": {
        # faithful to bungalow_square: bedrooms stacked left (master front + ensuite
        # mid-left + standard rear), common T&B rear-center next to kitchen,
        # L-D-K stacked right. Open central dining acts as the circulation hub.
        "template": "squarish_two_bedroom", "carport_side": "right",
        "supported_shells": ["squarish"],
        "sqL": 0.50,       # left column width fraction
        "sqFront": 0.40,   # master / living front band depth fraction
        "sqEns": 0.25,     # ensuite / dining mid band depth fraction
        "sqEnsW": 0.55,    # ensuite width fraction of the left column
        "sqCommon": 0.20,  # common T&B width fraction of total width
    },
    "wide_open_plan": {
        # faithful to bungalow_wide config 2: master+ensuite left, 2nd bedroom right,
        # kitchen + common T&B rear-center, L-shaped open-plan GREAT ROOM through the
        # center-front wrapping under the right bedroom.
        "template": "wide_open_plan", "carport_side": "right",
        "supported_shells": ["wide"],
        "wEnsW": 0.17, "wMasW": 0.34, "wBedW": 0.30,
        "wRearD": 0.28, "wBedD": 0.58, "wKit": 0.60,
    },
}


def float_keys(genome: Dict) -> List[str]:
    return [k for k in genome
            if k not in DISCRETE_KEYS and isinstance(genome[k], (int, float))]


def _hsplit(rect: Rect, ratio: float):
    """Split by depth (y). front = smaller y, rear = larger y."""
    ycut = rect.y0 + ratio * (rect.y1 - rect.y0)
    return Rect(rect.x0, rect.y0, rect.x1, ycut), Rect(rect.x0, ycut, rect.x1, rect.y1)


def _vsplit(rect: Rect, ratio: float):
    """Split by width (x). low = smaller x, high = larger x."""
    xcut = rect.x0 + ratio * (rect.x1 - rect.x0)
    return Rect(rect.x0, rect.y0, xcut, rect.y1), Rect(xcut, rect.y0, rect.x1, rect.y1)


def _setback_elements(lot: Lot, carport_side: str, kitchen: Rect, service_rect_xspan):
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
        cx1 = lot.width - 0.4
        cx0 = cx1 - 2.6
        elements.append(Room("carport", "carport",
                             Rect(cx0, lot.front, cx1, lot.front + 5.0), "service", covered=False))
    else:  # "left"
        cx0 = 0.4
        cx1 = cx0 + 2.6
        elements.append(Room("carport", "carport",
                             Rect(cx0, lot.front, cx1, lot.front + 5.0), "service", covered=False))
    rear_y0 = lot.depth - lot.rear + 0.1
    rear_y1 = lot.depth - 0.3
    elements.append(Room("dirty_kitchen", "dirty_kitchen",
                         Rect(kitchen.x0, rear_y0, kitchen.x1, rear_y1), "service", covered=False))
    sx0, sx1 = service_rect_xspan
    elements.append(Room("service_area", "service_area",
                         Rect(sx0, rear_y0, sx1, rear_y1), "service", covered=False))
    return elements


def build_deep(lot: Lot, g: Dict) -> Layout:
    env = lot.envelope()
    low_col, high_col = _vsplit(env, g["rL"])
    if g["carport_side"] == "right":
        private_col, public_col = low_col, high_col
    else:
        private_col, public_col = high_col, low_col

    rooms = []
    if g.get("master_position", "rear") == "rear":
        bedroom_rect, rest = _hsplit(private_col, g["pf1"])
        common_bath_rect, rest2 = _hsplit(rest, g["pf2"])
        master_rect, ensuite_rect = _hsplit(rest2, g["pf3"])
    else:
        master_rect, rest = _hsplit(private_col, g["pf1"] + 0.30)
        ensuite_rect, rest2 = _hsplit(rest, g["pf2"])
        common_bath_rect, bedroom_rect = _hsplit(rest2, 1.0 - g["pf3"])
    rooms.append(Room("bedroom_standard", "bedroom_standard", bedroom_rect, "private"))
    rooms.append(Room("common_bath", "common_bath", common_bath_rect, "service"))
    rooms.append(Room("master_bedroom", "master_bedroom", master_rect, "private"))
    rooms.append(Room("ensuite_bath", "ensuite_bath", ensuite_rect, "private"))

    living_rect, prest = _hsplit(public_col, g["qg1"])
    dining_rect, kitchen_rect = _hsplit(prest, g["qg2"])
    rooms.append(Room("living_room", "living_room", living_rect, "public"))
    rooms.append(Room("dining_room", "dining_room", dining_rect, "public"))
    rooms.append(Room("kitchen", "kitchen", kitchen_rect, "service"))

    elements = _setback_elements(lot, g["carport_side"], kitchen_rect,
                                 (private_col.x0, private_col.x1))
    return Layout(lot=lot, rooms=rooms, elements=elements,
                  carport_side=g["carport_side"], genome=g)


NOTCH_WIDTH = 1.1   # m — small access alcove (>= 0.90 m min)


def build_wide(lot: Lot, g: Dict) -> Layout:
    env = lot.envelope()
    cs = g["carport_side"]

    # private zone gets fraction wL of width; public/service on the carport side
    if cs == "right":
        private_zone, public_zone = _vsplit(env, g["wL"])     # private left, public right
        inner_high = True                                     # private's inner edge = high-x
    else:
        public_zone, private_zone = _vsplit(env, 1.0 - g["wL"])  # private right, public left
        inner_high = False                                    # private's inner edge = low-x

    # depth bands: front bedroom (full width), thin middle band, rear master (full width)
    if g.get("master_position", "rear") == "rear":
        bedroom_band, rest = _hsplit(private_zone, g["hp1"])
        middle_band, master_band = _hsplit(rest, g["hp2"])
    else:
        master_band, rest = _hsplit(private_zone, g["hp1"])
        middle_band, bedroom_band = _hsplit(rest, g["hp2"])

    # hallway NOTCH on the inner edge of the middle band (touches the LDK). It is
    # the circulation node every private room opens onto.
    if inner_high:   # inner edge = high-x
        ncx = middle_band.x1 - NOTCH_WIDTH
        mid_outer = Rect(middle_band.x0, middle_band.y0, ncx, middle_band.y1)
        hall_rect = Rect(ncx, middle_band.y0, middle_band.x1, middle_band.y1)
    else:            # inner edge = low-x
        ncx = middle_band.x0 + NOTCH_WIDTH
        hall_rect = Rect(middle_band.x0, middle_band.y0, ncx, middle_band.y1)
        mid_outer = Rect(ncx, middle_band.y0, middle_band.x1, middle_band.y1)

    master_rear = g.get("master_position", "rear") == "rear"
    ens_pos = g.get("ensuite_position", "alongside_master")
    if ens_pos == "twin_mid":
        # STACKED twins: ensuite and common T&B are equal, split by depth, flanking
        # the notch. The bath nearer the master is the ensuite. Master is full width.
        front_half, rear_half = _hsplit(mid_outer, 0.5)
        if master_rear:
            common_rect, ensuite_rect = front_half, rear_half   # ensuite at rear, by master
        else:
            ensuite_rect, common_rect = front_half, rear_half   # ensuite at front, by master
        master_rect = master_band
    elif ens_pos == "twin_side":
        # SIDE-BY-SIDE twins: equal baths split by width, both full middle-band depth.
        # Inner one (by the notch) = common; outer one (by the exterior wall) = ensuite,
        # which still touches the full-width master along its rear/front edge.
        low_half, high_half = _vsplit(mid_outer, 0.5)
        if inner_high:   # notch on high-x -> inner half = high_half = common
            ensuite_rect, common_rect = low_half, high_half
        else:            # notch on low-x -> inner half = low_half = common
            common_rect, ensuite_rect = low_half, high_half
        master_rect = master_band
    else:
        # alongside_master: common bath fills the middle-band outer block; ensuite is
        # carved beside the master on its OUTER side (master keeps inner edge on notch).
        common_rect = mid_outer
        mw = master_band.x1 - master_band.x0
        if inner_high:   # master inner = high-x, ensuite outer = low-x
            ex = master_band.x0 + g["we"] * mw
            ensuite_rect = Rect(master_band.x0, master_band.y0, ex, master_band.y1)
            master_rect = Rect(ex, master_band.y0, master_band.x1, master_band.y1)
        else:            # master inner = low-x, ensuite outer = high-x
            ex = master_band.x1 - g["we"] * mw
            master_rect = Rect(master_band.x0, master_band.y0, ex, master_band.y1)
            ensuite_rect = Rect(ex, master_band.y0, master_band.x1, master_band.y1)

    rooms = [
        Room("bedroom_standard", "bedroom_standard", bedroom_band, "private"),
        Room("master_bedroom", "master_bedroom", master_rect, "private"),
        Room("common_bath", "common_bath", common_rect, "service"),
        Room("ensuite_bath", "ensuite_bath", ensuite_rect, "private"),
        Room("hallway", "hallway", hall_rect, "circulation"),
    ]

    # public zone: living across the front; dining (inner) + kitchen (outer) at the rear
    living_rect, rear = _hsplit(public_zone, g["pfront"])
    if cs == "right":   # public right -> dining inner (low-x), kitchen outer (high-x)
        dining_rect, kitchen_rect = _vsplit(rear, 1.0 - g["pdk"])
    else:                # public left -> kitchen outer (low-x), dining inner (high-x)
        kitchen_rect, dining_rect = _vsplit(rear, g["pdk"])
    rooms += [
        Room("living_room", "living_room", living_rect, "public"),
        Room("dining_room", "dining_room", dining_rect, "public"),
        Room("kitchen", "kitchen", kitchen_rect, "service"),
    ]

    elements = _setback_elements(lot, cs, kitchen_rect,
                                 (private_zone.x0, private_zone.x1))
    return Layout(lot=lot, rooms=rooms, elements=elements, carport_side=cs, genome=g)


def build_wide_config(lot: Lot, g: Dict) -> Layout:
    """Faithful reproduction of the bungalow_wide drawing."""
    env = lot.envelope()
    cs = g["carport_side"]
    if cs == "right":
        private, public = _vsplit(env, g["wcL"])      # private left, public right
        inner_high = True                             # private inner edge = high-x
    else:
        public, private = _vsplit(env, 1.0 - g["wcL"])  # private right, public left
        inner_high = False

    HALL = 1.3
    pd = private.y1 - private.y0

    # hall column on the inner side of the private zone (touches the LDK)
    if inner_high:
        hx = private.x1 - HALL
        rooms_block = Rect(private.x0, private.y0, hx, private.y1)
        hcx0, hcx1 = hx, private.x1
    else:
        hx = private.x0 + HALL
        rooms_block = Rect(hx, private.y0, private.x1, private.y1)
        hcx0, hcx1 = private.x0, hx

    # hall column split by depth: hall (front+mid) + common T&B (rear, next to kitchen)
    ccut = private.y1 - g["wcCommon"] * pd
    hall_rect = Rect(hcx0, private.y0, hcx1, ccut)
    common_rect = Rect(hcx0, ccut, hcx1, private.y1)

    # rooms block: front band (ensuite + master), rear band (standard bedroom)
    fcut = private.y0 + g["wcf"] * pd
    front_band = Rect(rooms_block.x0, private.y0, rooms_block.x1, fcut)
    standard_rect = Rect(rooms_block.x0, fcut, rooms_block.x1, private.y1)
    fw = front_band.x1 - front_band.x0
    if inner_high:   # master inner = high-x, ensuite outer = low-x (front-left corner)
        ex = front_band.x0 + g["wce"] * fw
        ensuite_rect = Rect(front_band.x0, front_band.y0, ex, front_band.y1)
        master_rect = Rect(ex, front_band.y0, front_band.x1, front_band.y1)
    else:            # master inner = low-x, ensuite outer = high-x
        ex = front_band.x1 - g["wce"] * fw
        master_rect = Rect(front_band.x0, front_band.y0, ex, front_band.y1)
        ensuite_rect = Rect(ex, front_band.y0, front_band.x1, front_band.y1)

    rooms = [
        Room("master_bedroom", "master_bedroom", master_rect, "private"),
        Room("bedroom_standard", "bedroom_standard", standard_rect, "private"),
        Room("ensuite_bath", "ensuite_bath", ensuite_rect, "private"),
        Room("common_bath", "common_bath", common_rect, "service"),
        Room("hallway", "hallway", hall_rect, "circulation"),
    ]

    # public zone: living (front) -> dining (mid) -> kitchen (rear)
    lcut = public.y0 + g["lf"] * (public.y1 - public.y0)
    living_rect = Rect(public.x0, public.y0, public.x1, lcut)
    rear_pub = Rect(public.x0, lcut, public.x1, public.y1)
    dcut = rear_pub.y0 + g["dk"] * (rear_pub.y1 - rear_pub.y0)
    dining_rect = Rect(rear_pub.x0, rear_pub.y0, rear_pub.x1, dcut)
    kitchen_rect = Rect(rear_pub.x0, dcut, rear_pub.x1, rear_pub.y1)
    rooms += [
        Room("living_room", "living_room", living_rect, "public"),
        Room("dining_room", "dining_room", dining_rect, "public"),
        Room("kitchen", "kitchen", kitchen_rect, "service"),
    ]

    elements = _setback_elements(lot, cs, kitchen_rect, (private.x0, private.x1))
    return Layout(lot=lot, rooms=rooms, elements=elements, carport_side=cs, genome=g)


def build_wide_config2(lot: Lot, g: Dict) -> Layout:
    """Faithful to bungalow_wide config 2: opposite-side bedrooms with a central
    L-shaped open-plan great room."""
    env = lot.envelope()
    cs = g["carport_side"]
    x0, x1, y0, y1 = env.x0, env.x1, env.y0, env.y1   # y0 = front, y1 = rear
    W, D = x1 - x0, y1 - y0

    ex = x0 + g["wEnsW"] * W           # ensuite right edge (narrow, rear-left)
    mx = x0 + g["wMasW"] * W           # master right edge (wider than ensuite)
    bx = x1 - g["wBedW"] * W           # right bedroom left edge
    ry = y1 - g["wRearD"] * D          # rear strip (ensuite|kitchen|common) front edge
    by = y1 - g["wBedD"] * D           # right bedroom front edge (deeper than the strip)
    kx = ex + g["wKit"] * (bx - ex)    # kitchen vs common T&B split

    # rear strip: ensuite (narrow, left) | kitchen | common T&B
    ensuite_rect = Rect(x0, ry, ex, y1)
    kitchen_rect = Rect(ex, ry, kx, y1)
    common_rect = Rect(kx, ry, bx, y1)
    # front-left master (wider than the ensuite, runs under the kitchen)
    master_rect = Rect(x0, y0, mx, ry)
    # right bedroom (rear, deeper than the strip) with the great room wrapping under it
    bedroom_rect = Rect(bx, by, x1, y1)
    # L-shaped great room: center cell + foot under the bedroom
    great_cell1 = Rect(mx, y0, bx, ry)
    great_cell2 = Rect(bx, y0, x1, by)

    rooms = [
        Room("master_bedroom", "master_bedroom", master_rect, "private"),
        Room("ensuite_bath", "ensuite_bath", ensuite_rect, "private"),
        Room("bedroom_standard", "bedroom_standard", bedroom_rect, "private"),
        Room("kitchen", "kitchen", kitchen_rect, "service"),
        Room("common_bath", "common_bath", common_rect, "service"),
        Room("great_room", "great_room", great_cell1, "public", rect2=great_cell2),
    ]
    elements = _setback_elements(lot, cs, kitchen_rect, (x0, mx))
    return Layout(lot=lot, rooms=rooms, elements=elements, carport_side=cs, genome=g)


def build_squarish_two_bedroom(lot: Lot, g: Dict) -> Layout:
    """Faithful to bungalow_square: bedrooms stacked left (master front, ensuite mid,
    standard rear), L-D-K stacked right, common T&B rear-center next to kitchen."""
    env = lot.envelope()
    cs = g["carport_side"]
    x0, x1, y0, y1 = env.x0, env.x1, env.y0, env.y1
    W, D = x1 - x0, y1 - y0

    lx = x0 + g["sqL"] * W            # left/right column boundary
    yf = y0 + g["sqFront"] * D         # front band depth (master/living)
    ym = yf + g["sqEns"] * D           # mid band end (ensuite/dining)
    ew = (lx - x0) * g["sqEnsW"]       # ensuite width within the left column
    cw = W * g["sqCommon"]             # common T&B width

    master_rect = Rect(x0, y0, lx, yf)
    ensuite_rect = Rect(x0, yf, x0 + ew, ym)
    standard_rect = Rect(x0, ym, lx, y1)
    common_rect = Rect(lx, ym, lx + cw, y1)
    kitchen_rect = Rect(lx + cw, ym, x1, y1)
    living_rect = Rect(lx, y0, x1, yf)
    dining_rect = Rect(x0 + ew, yf, x1, ym)   # central open dining (circulation hub)

    rooms = [
        Room("master_bedroom", "master_bedroom", master_rect, "private"),
        Room("ensuite_bath", "ensuite_bath", ensuite_rect, "private"),
        Room("bedroom_standard", "bedroom_standard", standard_rect, "private"),
        Room("common_bath", "common_bath", common_rect, "service"),
        Room("kitchen", "kitchen", kitchen_rect, "service"),
        Room("living_room", "living_room", living_rect, "public"),
        Room("dining_room", "dining_room", dining_rect, "public"),
    ]
    elements = _setback_elements(lot, cs, kitchen_rect, (x0, lx))
    return Layout(lot=lot, rooms=rooms, elements=elements, carport_side=cs, genome=g)


def build_layout(lot: Lot, genome: Dict) -> Layout:
    template = (genome or {}).get("template", "narrow_stacked")
    g = dict(DEFAULTS[template])
    g.update(genome or {})
    if template == "wide_open_plan":
        return build_wide_config2(lot, g)
    if template == "wide_central_hall":
        return build_wide_config(lot, g)
    if template == "wide_hall_notch":
        return build_wide(lot, g)
    if template == "squarish_two_bedroom":
        return build_squarish_two_bedroom(lot, g)
    return build_deep(lot, g)
