# TrailerArrangement.py
# ---------------------------------------------------------------------------
# 3D packing logic + ParaPy visualization for trailer loading
#
# Public API:
#   - Item, ItemType
#   - PlacedItem
#   - pack_single_trailer
#   - pack_items_into_trailers
#   - TrailerPackingVisualization (ParaPy model for visualization)
#
# Usage from main application (example):
#
#   from TrailerArrangement import Item, TrailerPackingVisualization
#
#   class MissionStrategyApp(Base):
#       ...
#       def PackagedVisualization(self):
#           return TrailerPackingVisualization(
#               items=self.items_to_pack,   # List[Item]
#               trailers=self.trailers,     # list of trailer-like objects
#           )
# ---------------------------------------------------------------------------

from __future__ import annotations

import random
from typing import List, Tuple, Literal, Any

from parapy.core import Base, Input, Attribute, Part, child
from parapy.geom import Box, XOY

# ----------------------------------------------------------------------------------------------------------------------
# 3D PACKING CORE TYPES
# ----------------------------------------------------------------------------------------------------------------------

ItemType = Literal["vehicle", "tool"]


class Item:
    """Logical item to be packed.

    lx, ly, lz are the *nominal* local dimensions of the bounding box.

    item_type:
    - "vehicle": must be placed on floor (z = 0), no stacking.
    - "tool": can be stacked in 3D, subject to flags:

        upright_only:
            - if True: behaves like a vehicle for packing:
              * only on floor (z = 0),
              * stays upright (no rotation that swaps Z),
              * nothing can be stacked above its XY footprint.
            - if False: normal stackable tool.

        vehicle_attachable:
            - used together with Trailer.has_ceiling:
              * if trailer.has_ceiling is False (open trailer), only items
                that are vehicles or tools with (vehicle_attachable AND
                upright_only) may be loaded in that trailer.
    """

    id: str
    lx: float
    ly: float
    lz: float
    item_type: ItemType
    upright_only: bool
    vehicle_attachable: bool

    def __init__(
        self,
        id: str,
        lx: float,
        ly: float,
        lz: float,
        item_type: ItemType,
        upright_only: bool = False,
        vehicle_attachable: bool = False,
    ):
        self.id = id
        self.lx = lx
        self.ly = ly
        self.lz = lz
        self.item_type = item_type
        self.upright_only = upright_only
        self.vehicle_attachable = vehicle_attachable


class PlacedItem:
    """Result of packing one item in a particular trailer.

    trailer_index: index into the returned list from pack_items_into_trailers
    (0 = first trailer).
    (x, y, z): lower-left-front corner of the placed box in trailer coords.
    (wx, wy, wz): oriented dimensions actually used.
    """

    item: Item
    trailer_index: int
    x: float
    y: float
    z: float
    wx: float
    wy: float
    wz: float

    def __init__(
        self,
        item: Item,
        trailer_index: int,
        x: float,
        y: float,
        z: float,
        wx: float,
        wy: float,
        wz: float,
    ):
        self.item = item
        self.trailer_index = trailer_index
        self.x = x
        self.y = y
        self.z = z
        self.wx = wx
        self.wy = wy
        self.wz = wz


class FreeRect:
    """2D free rectangle on the trailer floor (for floor-only items)."""

    x: float
    y: float
    w: float
    h: float

    def __init__(self, x: float, y: float, w: float, h: float):
        self.x = x
        self.y = y
        self.w = w
        self.h = h


class FreeBox:
    """3D free box for stackable tools in a floor-free XY region."""

    x: float
    y: float
    z: float
    L: float
    W: float
    H: float

    def __init__(self, x: float, y: float, z: float, L: float, W: float, H: float):
        self.x = x
        self.y = y
        self.z = z
        self.L = L
        self.W = W
        self.H = H


# ---------------------------------------------------------------------------
# Orientation helpers
# ---------------------------------------------------------------------------

def vehicle_orientations(item: Item) -> List[Tuple[float, float, float]]:
    """Allowed orientations for vehicles and upright_only tools:
    90° rotations around Z only.

    Z always stays "up", so we only swap L/W.
    """
    return [
        (item.lx, item.ly, item.lz),
        (item.ly, item.lx, item.lz),
    ]


def tool_orientations(item: Item) -> List[Tuple[float, float, float]]:
    """Allowed orientations for stackable tools: all axis-aligned 90° rotations
    (all 6 permutations of the axes).
    """
    l, w, h = item.lx, item.ly, item.lz
    # Use a set to avoid duplicates if dimensions are equal
    return list({
        (l, w, h),
        (l, h, w),
        (w, l, h),
        (w, h, l),
        (h, l, w),
        (h, w, l),
    })


# ---------------------------------------------------------------------------
# 2D packing for floor-only items (vehicles + upright_only tools)
# ---------------------------------------------------------------------------

def pack_vehicles_2d(
    vehicles: List[Item],
    L: float,
    W: float
) -> Tuple[
    List[Tuple[Item, float, float, float, float, float, float]],
    List[Item],
    List[FreeRect],
]:
    """Pack floor-only items on the floor (z = 0) of a single trailer.

    Here, "vehicles" can be:
    - real vehicles (item_type == "vehicle")
    - or upright_only tools (item_type == "tool", upright_only == True).

    Returns:
        placed:
            list of tuples
            (item, x, y, z, wx, wy, wz)
            where z is always 0.0 and (wx, wy, wz) are oriented dims.
        unplaced:
            list of items that do not fit in this trailer.
        free_rects:
            remaining free rectangles on the floor (used later for 3D tools).

    Strategy: simple greedy guillotine 2D packing:
        - start with one free rectangle [0,0,L,W]
        - sort items by decreasing footprint (lx*ly)
        - for each item, try to place in first free rect (two orientations)
          that fits; then guillotine-split that rect into right + top parts.
    """

    # Sort largest footprint first
    veh_sorted = sorted(vehicles, key=lambda v: v.lx * v.ly, reverse=True)

    free_rects: List[FreeRect] = [FreeRect(0.0, 0.0, L, W)]
    placed: List[Tuple[Item, float, float, float, float, float, float]] = []
    unplaced: List[Item] = []

    for v in veh_sorted:
        placed_v = False
        for rect_index, rect in enumerate(list(free_rects)):
            for wx, wy, wz in vehicle_orientations(v):
                if wx <= rect.w and wy <= rect.h:
                    # Place at (rect.x, rect.y) on the floor
                    x, y, z = rect.x, rect.y, 0.0
                    placed.append((v, x, y, z, wx, wy, wz))

                    # Guillotine split: remove used rect and create right + top
                    del free_rects[rect_index]

                    # Right rectangle (to the +x side)
                    rw = rect.w - wx
                    if rw > 0.0:
                        free_rects.append(
                            FreeRect(
                                x=x + wx,
                                y=rect.y,
                                w=rw,
                                h=rect.h
                            )
                        )

                    # Top rectangle (to the +y side, above the placed box)
                    rh = rect.h - wy
                    if rh > 0.0:
                        free_rects.append(
                            FreeRect(
                                x=rect.x,
                                y=y + wy,
                                w=wx,
                                h=rh
                            )
                        )

                    placed_v = True
                    break
            if placed_v:
                break

        if not placed_v:
            unplaced.append(v)

    return placed, unplaced, free_rects


# ---------------------------------------------------------------------------
# 3D packing for stackable tools in floor-free regions
# ---------------------------------------------------------------------------

def split_free_box(
    box: FreeBox,
    placed_dims: Tuple[float, float, float]
) -> List[FreeBox]:
    """Guillotine split of a free box after placing an item at its origin.

    The item is placed at the lower-left-front corner of `box`. We then
    split the remaining volume into up to three new free boxes:

    - right of the item
    - front of the item
    - above the item
    """
    wx, wy, wz = placed_dims

    new_boxes: List[FreeBox] = []

    # Right box: same W,H, reduced L, shifted in +x
    rem_L = box.L - wx
    if rem_L > 0.0:
        new_boxes.append(
            FreeBox(
                x=box.x + wx,
                y=box.y,
                z=box.z,
                L=rem_L,
                W=box.W,
                H=box.H,
            )
        )

    # Front box: same H, reduced W, limited in L to wx
    rem_W = box.W - wy
    if rem_W > 0.0:
        new_boxes.append(
            FreeBox(
                x=box.x,
                y=box.y + wy,
                z=box.z,
                L=wx,
                W=rem_W,
                H=box.H,
            )
        )

    # Above box: reduced H, same L,W as the placed item footprint
    rem_H = box.H - wz
    if rem_H > 0.0:
        new_boxes.append(
            FreeBox(
                x=box.x,
                y=box.y,
                z=box.z + wz,
                L=wx,
                W=wy,
                H=rem_H,
            )
        )

    return new_boxes


def pack_tools_3d(
    tools: List[Item],
    free_boxes: List[FreeBox]
) -> Tuple[
    List[Tuple[Item, float, float, float, float, float, float]],
    List[Item],
]:
    """Pack *stackable* tools (upright_only == False) in a set of free 3D boxes.

    Returns:
        placed:
            list of tuples
            (item, x, y, z, wx, wy, wz)
        unplaced:
            tools that did not fit in any free box.

    Strategy:
        - sort tools by volume descending
        - for each tool, try each free box and all 6 axis-aligned orientations
        - when a placement is found, split the box and continue
    """
    tools_sorted = sorted(tools, key=lambda t: t.lx * t.ly * t.lz, reverse=True)

    placed: List[Tuple[Item, float, float, float, float, float, float]] = []
    unplaced: List[Item] = []

    free = list(free_boxes)

    for tool in tools_sorted:
        placed_t = False
        for box_index, box in enumerate(list(free)):
            for wx, wy, wz in tool_orientations(tool):
                if wx <= box.L and wy <= box.W and wz <= box.H:
                    # Place tool at origin of box
                    x, y, z = box.x, box.y, box.z
                    placed.append((tool, x, y, z, wx, wy, wz))

                    # Remove used box and create new free boxes
                    del free[box_index]
                    free.extend(split_free_box(box, (wx, wy, wz)))

                    placed_t = True
                    break
            if placed_t:
                break

        if not placed_t:
            unplaced.append(tool)

    return placed, unplaced


# ---------------------------------------------------------------------------
# Per-trailer packing with upright_only semantics
# ---------------------------------------------------------------------------

def pack_single_trailer(
    vehicles: List[Item],
    tools: List[Item],
    L: float,
    W: float,
    H: float,
) -> Tuple[List[PlacedItem], List[Item], List[Item]]:
    """Pack as many vehicles and tools as possible into a single trailer.

    Vehicles:
        * only on floor (z = 0)
        * cannot be stacked
        * nothing can be above or below their XY footprint

    Tools:
        * if upright_only == True:
            - behave like vehicles: floor-only, upright, no stacking above
        * otherwise:
            - can be stacked in 3D, but only in floor-free XY regions
              (i.e. outside vehicle/upright-only footprints).
            - axis-aligned 90° orientations only.
    """

    # 1) Split tools into upright_only and stackable tools
    upright_tools = [t for t in tools if t.upright_only]
    stackable_tools = [t for t in tools if not t.upright_only]

    # All floor-only items: real vehicles + upright_only tools
    floor_items = list(vehicles) + upright_tools

    # 2) Place floor-only items with 2D guillotine packing
    floor_placed_raw, floor_unplaced, free_rects = pack_vehicles_2d(
        floor_items, L, W
    )

    # Split floor_unplaced back into vehicles and upright_only tools
    veh_unplaced: List[Item] = [
        it for it in floor_unplaced if it.item_type == "vehicle"
    ]
    upright_unplaced: List[Item] = [
        it for it in floor_unplaced if it.item_type == "tool"
    ]

    # 3) Build free 3D boxes for stackable tools from remaining floor rectangles
    free_boxes = [
        FreeBox(x=r.x, y=r.y, z=0.0, L=r.w, W=r.h, H=H)
        for r in free_rects
    ]

    # 4) Pack stackable tools in these 3D boxes
    tool_placed_raw, stackable_unplaced = pack_tools_3d(stackable_tools, free_boxes)

    # Tools unplaced for this trailer = those that didn't fit + upright_only that didn't fit floor
    tools_unplaced: List[Item] = stackable_unplaced + upright_unplaced

    placed_items: List[PlacedItem] = []

    # Floor-only items that did fit (vehicles + upright_only tools)
    for v, x, y, z, wx, wy, wz in floor_placed_raw:
        placed_items.append(
            PlacedItem(
                item=v,
                trailer_index=-1,  # filled in by caller
                x=x,
                y=y,
                z=z,
                wx=wx,
                wy=wy,
                wz=wz,
            )
        )

    # Stackable tools placed in 3D
    for t, x, y, z, wx, wy, wz in tool_placed_raw:
        placed_items.append(
            PlacedItem(
                item=t,
                trailer_index=-1,
                x=x,
                y=y,
                z=z,
                wx=wx,
                wy=wy,
                wz=wz,
            )
        )

    return placed_items, veh_unplaced, tools_unplaced


# ---------------------------------------------------------------------------
# Multi-trailer packing with has_ceiling / attachable rules
# ---------------------------------------------------------------------------

def pack_items_into_trailers(
    all_items: List[Item],
    trailers: List[Any],
) -> List[List[PlacedItem]]:
    """Greedy multi-trailer packing under the defined constraints.

    Args:
        all_items:
            list of Item (both vehicles and tools).
        trailers:
            list of trailer-like objects, in order of usage.
            Each trailer must at least have:
                - carrying_bounding_box: (L, W, H)
                - has_ceiling: bool

    Rules:
        - For EACH trailer:
            * Vehicles and tools are split into:
                - vehicles: Item.item_type == "vehicle"
                - tools: Item.item_type == "tool"

        - Trailer.has_ceiling == True (closed box):
            * All items are allowed (subject to geometric constraints).

        - Trailer.has_ceiling == False (open / flatbed):
            * Only:
                - vehicles, and
                - tools with (vehicle_attachable == True AND upright_only == True)
              are allowed to be loaded in this trailer.
            * Other tools are deferred to later trailers.

        - Within a trailer, packing is done by pack_single_trailer()
          which:
            * treats vehicles + upright_only tools as floor-only items,
            * stacks other tools in 3D where allowed.

    Returns:
        List[trailers], each element is a list[PlacedItem] for that trailer.
    """

    if not trailers:
        raise RuntimeError("No trailers provided.")

    # Current unplaced pools
    vehicles = [it for it in all_items if it.item_type == "vehicle"]
    tools = [it for it in all_items if it.item_type == "tool"]

    all_trailer_placements: List[List[PlacedItem]] = []

    for trailer_index, trailer in enumerate(trailers):
        if not vehicles and not tools:
            break  # everything already packed

        L, W, H = trailer.carrying_bounding_box  # type: ignore[attr-defined]
        has_ceiling: bool = bool(getattr(trailer, "has_ceiling", False))

        # Decide which tools are allowed in THIS trailer
        if has_ceiling:
            # Closed trailer: all tools are allowed
            tools_for_this = tools
            tools_kept_for_later: List[Item] = []
        else:
            # Open trailer: only vehicle-attachable, upright-only tools allowed here
            tools_for_this = [
                t
                for t in tools
                if t.vehicle_attachable and t.upright_only
            ]
            # Disallowed tools must be tried in later trailers
            tools_kept_for_later = [t for t in tools if t not in tools_for_this]

        # Use single-trailer packer
        placed, vehicles_unplaced, tools_unplaced_now = pack_single_trailer(
            vehicles=vehicles,
            tools=tools_for_this,
            L=L,
            W=W,
            H=H,
        )

        # Safety: avoid infinite loop if nothing fits in an empty trailer
        if not placed:
            raise RuntimeError(
                f"No items could be placed in trailer index {trailer_index} "
                f"with size (L={L}, W={W}, H={H}). "
                f"Check item dimensions, flags and constraints."
            )

        # Assign trailer index for all placed items
        for p in placed:
            p.trailer_index = trailer_index

        all_trailer_placements.append(placed)

        # Update remaining pools:
        vehicles = vehicles_unplaced
        # tools that did not fit this trailer + tools that were not allowed on this trailer
        tools = tools_unplaced_now + tools_kept_for_later

    # After using all trailers, fail if items remain
    if vehicles or tools:
        raise RuntimeError(
            "Ran out of trailers while items remain to be packed under ceiling/attachment rules."
        )

    return all_trailer_placements


__all__ = [
    "Item",
    "ItemType",
    "PlacedItem",
    "FreeRect",
    "FreeBox",
    "pack_single_trailer",
    "pack_items_into_trailers",
    "TrailerPackingVisualization",
    "item_from_machine",
    "TrailerAdapter",
]



# --------------------------------------------
# Visualization model
# --------------------------------------------

class TrailerPackingVisualization(Base):
    """ParaPy model that runs the packing algorithm and visualizes it.

    Inputs:
        items   : List[Item] to pack.
        trailers: list of trailer-like objects, each with
                  - carrying_bounding_box: (L, W, H)
                  - has_ceiling: bool

    Geometry:
        - Closed trailers: purple semi-transparent boxes + grey floors.
        - Open trailers: very light grey transparent envelope + grey floors.
        - Cargo: colored boxes using color rules based on item flags.
    """

    # Inputs: passed from main application
    items: List[Item] = Input()
    trailers: List[Any] = Input()

    # ------------------- Packing result -------------------

    @Attribute
    def packed_trailers(self) -> List[List[PlacedItem]]:
        """Run the packing algorithm on the current items and trailers."""
        return pack_items_into_trailers(self.items, self.trailers)

    @Attribute
    def flat_placed(self) -> List[PlacedItem]:
        """Flatten [ [PlacedItem,...], [PlacedItem,...], ... ] into one list."""
        return [p for trailer in self.packed_trailers for p in trailer]

    @Attribute
    def nb_trailers(self) -> int:
        """Number of trailers actually used."""
        if not self.flat_placed:
            return 0
        return max(p.trailer_index for p in self.flat_placed) + 1

    # ------------------- Derived trailer size / layout info -------------------

    @Attribute
    def trailer_sizes_used(self) -> List[Tuple[float, float, float]]:
        """Sizes of trailers that are actually used (subset of self.trailers)."""
        return [
            self.trailers[i].carrying_bounding_box
            for i in range(self.nb_trailers)
        ]

    @Attribute
    def trailer_Ls(self) -> List[float]:
        return [sz[0] for sz in self.trailer_sizes_used]

    @Attribute
    def trailer_Ws(self) -> List[float]:
        return [sz[1] for sz in self.trailer_sizes_used]

    @Attribute
    def trailer_Hs(self) -> List[float]:
        return [sz[2] for sz in self.trailer_sizes_used]

    @Attribute
    def trailer_offsets_x(self) -> List[float]:
        """Cumulative X offsets for each trailer so they don't overlap."""
        offsets: List[float] = []
        x = 0.0
        gap = 1.0  # 1 m gap between trailers
        for L in self.trailer_Ls:
            offsets.append(x)
            x += L + gap
        return offsets

    # ------------------- Open / closed trailer indices -------------------

    @Attribute
    def open_trailer_indices(self) -> List[int]:
        """Indices of open (no-ceiling) trailers that are actually used."""
        return [
            i for i in range(self.nb_trailers)
            if not self.trailers[i].has_ceiling
        ]

    @Attribute
    def closed_trailer_indices(self) -> List[int]:
        """Indices of closed (ceiling) trailers that are actually used."""
        return [
            i for i in range(self.nb_trailers)
            if self.trailers[i].has_ceiling
        ]

    @Attribute
    def trailer_top_heights(self) -> List[float]:
        """For each used trailer, height of the open 'envelope' box.

        For trailer i, we take:
            max_top_z = max(p.z + p.wz for p in items on that trailer)
            envelope_height = max_top_z * 1.1

        If a trailer is empty (shouldn't really happen for used ones),
        we fall back to its carrying_bounding_box height.
        """
        heights: List[float] = []
        for i in range(self.nb_trailers):
            items_i = [p for p in self.flat_placed if p.trailer_index == i]
            if items_i:
                max_top_z = max(p.z + p.wz for p in items_i)
                heights.append(max_top_z * 1.1)
            else:
                heights.append(self.trailers[i].carrying_bounding_box[2])
        return heights

    # ------------------- Cargo color helpers -------------------

    @Attribute
    def vehicle_colors(self):
        """Deterministic random yellowish colors for vehicles."""
        random.seed(1)
        vs = [p for p in self.flat_placed if p.item.item_type == "vehicle"]
        colors = {}
        for p in vs:
            # Yellowish: high R and G, low B
            r = 200 + random.randint(0, 55)
            g = 200 + random.randint(0, 55)
            b = random.randint(0, 70)
            colors[p.item.id] = [r, g, b]
        return colors

    @Attribute
    def tool_colors(self):
        """Colors for tools:
        - only attachable (vehicle_attachable == True, upright_only == False): pink
        - only upright_only (upright_only == True, vehicle_attachable == False): very light/baby blue
        - both attachable and upright_only: purple
        - neither: bluish random (fallback)
        """
        random.seed(2)
        ts = [p for p in self.flat_placed if p.item.item_type == "tool"]
        colors = {}
        for p in ts:
            it = p.item
            if it.vehicle_attachable and not it.upright_only:
                # Only attachable: pink
                colors[it.id] = [255, 105, 180]  # hot pink
            elif it.upright_only and not it.vehicle_attachable:
                # Only upright_only: very light / baby blue
                colors[it.id] = [173, 216, 230]
            elif it.vehicle_attachable and it.upright_only:
                # Both: purple
                colors[it.id] = [160, 32, 240]
            else:
                # Neither: bluish random fallback
                r = random.randint(0, 60)
                g = random.randint(0, 140)
                b = 180 + random.randint(0, 70)
                colors[it.id] = [r, g, b]
        return colors

    @Attribute
    def cargo_colors(self) -> List[List[int]]:
        """Color per placed item (flattened list)."""
        colors: List[List[int]] = []
        for p in self.flat_placed:
            if p.item.item_type == "vehicle":
                colors.append(self.vehicle_colors[p.item.id])
            else:
                colors.append(self.tool_colors[p.item.id])
        return colors

    # ------------------- Geometry: trailers (closed vs open) -------------------

    @Part
    def closed_trailer_boxes(self):
        """Closed trailer volumes: purple, semi-transparent."""
        return Box(
            quantify=len(self.closed_trailer_indices),
            width=self.trailer_Ls[self.closed_trailer_indices[child.index]],
            length=self.trailer_Ws[self.closed_trailer_indices[child.index]],
            height=self.trailer_Hs[self.closed_trailer_indices[child.index]],
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[self.closed_trailer_indices[child.index]],
            ),
            color=[160, 32, 240],
            transparency=0.8,
        )

    @Part
    def closed_trailer_floors(self):
        """Closed trailer floor: darker grey, 0.3 m thick, extending downward."""
        return Box(
            quantify=len(self.closed_trailer_indices),
            width=self.trailer_Ls[self.closed_trailer_indices[child.index]],
            length=self.trailer_Ws[self.closed_trailer_indices[child.index]],
            height=0.3,
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[self.closed_trailer_indices[child.index]],
                "z",
                -0.3,
            ),
            color=[120, 120, 120],
            transparency=0.2,
        )

    @Part
    def open_trailer_tops(self):
        """Open trailer 'envelope' volumes: very light grey, highly transparent."""
        return Box(
            quantify=len(self.open_trailer_indices),
            width=self.trailer_Ls[self.open_trailer_indices[child.index]],
            length=self.trailer_Ws[self.open_trailer_indices[child.index]],
            height=self.trailer_top_heights[self.open_trailer_indices[child.index]],
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[self.open_trailer_indices[child.index]],
                "z",
                0.0,
            ),
            color=[230, 230, 230],
            transparency=0.9,
        )

    @Part
    def open_trailer_floors(self):
        """Open trailer floor: darker grey, 0.3 m thick, extending downward."""
        return Box(
            quantify=len(self.open_trailer_indices),
            width=self.trailer_Ls[self.open_trailer_indices[child.index]],
            length=self.trailer_Ws[self.open_trailer_indices[child.index]],
            height=0.3,
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[self.open_trailer_indices[child.index]],
                "z",
                -0.3,
            ),
            color=[120, 120, 120],
            transparency=0.2,
        )

    # ------------------- Geometry: cargo -------------------

    @Part
    def cargo_boxes(self):
        """All placed vehicles/tools as colored boxes inside trailers."""
        return Box(
            quantify=len(self.flat_placed),
            width=self.flat_placed[child.index].wx,
            length=self.flat_placed[child.index].wy,
            height=self.flat_placed[child.index].wz,
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[
                    self.flat_placed[child.index].trailer_index
                ] + self.flat_placed[child.index].x,
                "y",
                self.flat_placed[child.index].y,
                "z",
                self.flat_placed[child.index].z,
            ),
            color=self.cargo_colors[child.index],
        )


# ---------------------------------------------------------------------------
# Helpers to integrate “machine-like” and “trailer-like” objects
# ---------------------------------------------------------------------------

def item_from_machine(machine, item_type_hint: str | None = None) -> Item:
    """Convert a machine-like object into an Item.

    Expects:
        machine.overall_dimensions -> [L, W, H]
        machine.machine_id -> str
    """
    L, W, H = machine.overall_dimensions
    cls_name = type(machine).__name__
    item_id = machine.machine_id

    if item_type_hint is not None:
        item_type = item_type_hint
    else:
        # Default: tractors / vehicles / trucks are 'vehicle', rest is 'tool'
        item_type = "vehicle" if cls_name in ("Truck", "Tractor", "Vehicle") else "tool"

    if item_type == "vehicle":
        upright_only = True
        vehicle_attachable = False
    else:
        upright_only = False
        vehicle_attachable = False

    return Item(
        id=item_id,
        lx=L,
        ly=W,
        lz=H,
        item_type=item_type,
        upright_only=upright_only,
        vehicle_attachable=vehicle_attachable,
    )


class TrailerAdapter:
    """Adapter to make an arbitrary Trailer-like object usable by the packer.

    Expects:
        trailer.overall_dimensions -> [L, W, H]
    """

    def __init__(self, src_trailer, trailer_id: str = ""):
        self.src = src_trailer
        L, W, H = src_trailer.overall_dimensions
        self.carrying_bounding_box = (L, W, H)
        self.has_ceiling = True  # later you can infer from src_trailer
        self.trailer_id = trailer_id or getattr(src_trailer, "machine_id", "")

