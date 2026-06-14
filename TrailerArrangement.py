"""3D trailer loading and visualization.

This module contains:
- a simple 2D/3D bin-packing heuristic for vehicles and tools;
- ParaPy geometry to visualize packed trailers and cargo;
- adapters to convert application-specific objects into generic packing types.

Key concepts:
- Vehicles and upright-only tools are floor-only (z = 0), no stacking above.
- Other tools may be stacked in remaining volume.
- Open trailers (has_ceiling == False) only accept vehicles or
  (upright_only AND vehicle_attachable) tools.
"""
from __future__ import annotations

from typing import List, Tuple, Literal, Any

from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.geom import Box, XOY
from parapy.exchange import STEPWriter

# ----------------------------------------------------------------------------------------------------------------------
# 3D PACKING CORE TYPES
# ----------------------------------------------------------------------------------------------------------------------

ItemType = Literal["vehicle", "tool"]


class CargoMarker(Base):
    """Wrapper around a cargo box that keeps a reference to the real asset.

    Clicking this in the ParaPy tree lets you reach the underlying
    Machine/Tool via the .asset Input, similar to AssetMarker in FleetMapMaker.
    """

    asset: object = Input()
    L: float = Input()
    W: float = Input()
    H: float = Input()
    x: float = Input()
    y: float = Input()
    z: float = Input()
    color: Any = Input("gray")

    @Attribute
    def label(self) -> str:
        mid = getattr(self.asset, "machine_id", None)
        mtype = getattr(self.asset, "machine_type", None) or type(
            self.asset
        ).__name__
        if mid not in (None, "") and mid is not None:
            return f"{mtype} {mid}"
        return mtype

    @Part
    def box(self):
        return Box(
            width=self.L,
            length=self.W,
            height=self.H,
            position=XOY.translate(
                "x",
                self.x,
                "y",
                self.y,
                "z",
                self.z,
            ),
            color=self.color,
            label=self.label,
        )


class TrailerMarker(Base):
    """Marker for trailers in the arrangement.

    asset:
        Underlying Trailer (or TrailerAdapter.src) this geometry represents.
    """

    asset: object = Input()
    L: float = Input()
    W: float = Input()
    H: float = Input()
    offset_x: float = Input()
    color: Any = Input((160, 32, 240))
    transparency: float = Input(0.8)

    @Attribute
    def label(self) -> str:
        tid = getattr(self.asset, "trailer_id", None)
        if tid not in (None, "") and tid is not None:
            return f"Trailer {tid}"
        return "Trailer"

    @Part
    def box(self):
        return Box(
            width=self.L,
            length=self.W,
            height=self.H,
            position=XOY.translate("x", self.offset_x),
            color=self.color,
            transparency=self.transparency,
            label=self.label,
        )


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

    source:
        Reference to original Machine/Tool object this item represents.
    """

    id: str
    lx: float
    ly: float
    lz: float
    item_type: ItemType
    upright_only: bool
    vehicle_attachable: bool
    color: Any
    source: Any  # original Machine/Tool object

    def __init__(
        self,
        id: str,
        lx: float,
        ly: float,
        lz: float,
        item_type: ItemType,
        upright_only: bool = False,
        vehicle_attachable: bool = False,
        color: Any = None,
        source: Any = None,
    ):
        self.id = id
        self.lx = lx
        self.ly = ly
        self.lz = lz
        self.item_type = item_type
        self.upright_only = upright_only
        self.vehicle_attachable = vehicle_attachable
        self.color = color
        self.source = source


class PlacedItem:
    """Physical placement of a single Item inside a specific trailer.

    Attributes
    ----------
    item :
        The original Item that has been packed.
    trailer_index :
        Integer index of the trailer this item is placed in
        (0 = first trailer in the list passed to pack_items_into_trailers).
    x, y, z :
        Coordinates of the lower-left-front corner of the placed box
        in that trailer's local coordinate system (meters).
    wx, wy, wz :
        Oriented dimensions in trailer frame.
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

    def __init__(
        self,
        x: float,
        y: float,
        z: float,
        L: float,
        W: float,
        H: float,
    ):
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
    90° rotations around Z only (swap L/W).
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
    return list(
        {
            (l, w, h),
            (l, h, w),
            (w, l, h),
            (w, h, l),
            (h, l, w),
            (h, w, l),
        }
    )


# ---------------------------------------------------------------------------
# 2D packing for floor-only items (vehicles + upright_only tools)
# ---------------------------------------------------------------------------

def pack_vehicles_2d(
    vehicles: List[Item],
    L: float,
    W: float,
) -> Tuple[
    List[Tuple[Item, float, float, float, float, float, float]],
    List[Item],
    List[FreeRect],
]:
    """Pack floor-only items on the floor (z = 0) of a single trailer."""
    veh_sorted = sorted(
        vehicles,
        key=lambda v: v.lx * v.ly,
        reverse=True,
    )

    free_rects: List[FreeRect] = [FreeRect(0.0, 0.0, L, W)]
    placed: List[Tuple[Item, float, float, float, float, float, float]] = []
    unplaced: List[Item] = []

    for v in veh_sorted:
        placed_v = False
        for rect_index, rect in enumerate(list(free_rects)):
            for wx, wy, wz in vehicle_orientations(v):
                if wx <= rect.w and wy <= rect.h:
                    x, y, z = rect.x, rect.y, 0.0
                    placed.append((v, x, y, z, wx, wy, wz))

                    del free_rects[rect_index]

                    rw = rect.w - wx
                    if rw > 0.0:
                        free_rects.append(
                            FreeRect(
                                x=x + wx,
                                y=rect.y,
                                w=rw,
                                h=rect.h,
                            )
                        )

                    rh = rect.h - wy
                    if rh > 0.0:
                        free_rects.append(
                            FreeRect(
                                x=rect.x,
                                y=y + wy,
                                w=wx,
                                h=rh,
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
# 3D packing for stackable tools
# ---------------------------------------------------------------------------

def split_free_box(
    box: FreeBox,
    placed_dims: Tuple[float, float, float],
) -> List[FreeBox]:
    wx, wy, wz = placed_dims
    new_boxes: List[FreeBox] = []

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
    free_boxes: List[FreeBox],
) -> Tuple[
    List[Tuple[Item, float, float, float, float, float, float]],
    List[Item],
]:
    tools_sorted = sorted(
        tools,
        key=lambda t: t.lx * t.ly * t.lz,
        reverse=True,
    )

    placed: List[Tuple[Item, float, float, float, float, float, float]] = []
    unplaced: List[Item] = []

    free = list(free_boxes)

    for tool in tools_sorted:
        placed_t = False
        for box_index, box in enumerate(list(free)):
            for wx, wy, wz in tool_orientations(tool):
                if wx <= box.L and wy <= box.W and wz <= box.H:
                    x, y, z = box.x, box.y, box.z
                    placed.append((tool, x, y, z, wx, wy, wz))

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
# Per-trailer packing
# ---------------------------------------------------------------------------

def pack_single_trailer(
    vehicles: List[Item],
    tools: List[Item],
    L: float,
    W: float,
    H: float,
) -> Tuple[List[PlacedItem], List[Item], List[Item]]:
    """Pack as many vehicles and tools as possible into a single trailer."""
    upright_tools = [t for t in tools if t.upright_only]
    stackable_tools = [t for t in tools if not t.upright_only]

    floor_items = list(vehicles) + upright_tools

    floor_placed_raw, floor_unplaced, free_rects = pack_vehicles_2d(
        floor_items,
        L,
        W,
    )

    veh_unplaced: List[Item] = [
        it for it in floor_unplaced if it.item_type == "vehicle"
    ]
    upright_unplaced: List[Item] = [
        it for it in floor_unplaced if it.item_type == "tool"
    ]

    free_boxes = [
        FreeBox(x=r.x, y=r.y, z=0.0, L=r.w, W=r.h, H=H)
        for r in free_rects
    ]

    tool_placed_raw, stackable_unplaced = pack_tools_3d(
        stackable_tools,
        free_boxes,
    )

    tools_unplaced: List[Item] = stackable_unplaced + upright_unplaced

    placed_items: List[PlacedItem] = []

    for v, x, y, z, wx, wy, wz in floor_placed_raw:
        placed_items.append(
            PlacedItem(
                item=v,
                trailer_index=-1,
                x=x,
                y=y,
                z=z,
                wx=wx,
                wy=wy,
                wz=wz,
            )
        )

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
    """Greedy multi-trailer packing under the defined constraints."""
    if not trailers:
        raise RuntimeError("No trailers provided.")

    vehicles = [it for it in all_items if it.item_type == "vehicle"]
    tools = [it for it in all_items if it.item_type == "tool"]

    all_trailer_placements: List[List[PlacedItem]] = []

    for trailer_index, trailer in enumerate(trailers):
        if not vehicles and not tools:
            break

        L, W, H = trailer.carrying_bounding_box  # type: ignore[attr-defined]
        has_ceiling: bool = bool(getattr(trailer, "has_ceiling", False))

        if has_ceiling:
            tools_for_this = tools
            tools_kept_for_later: List[Item] = []
        else:
            tools_for_this = [
                t
                for t in tools
                if t.vehicle_attachable and t.upright_only
            ]
            tools_kept_for_later = [
                t for t in tools if t not in tools_for_this
            ]

        placed, vehicles_unplaced, tools_unplaced_now = pack_single_trailer(
            vehicles=vehicles,
            tools=tools_for_this,
            L=L,
            W=W,
            H=H,
        )

        if not placed:
            raise RuntimeError(
                f"No items could be placed in trailer index {trailer_index} "
                f"with size (L={L}, W={W}, H={H}). "
                f"Check item dimensions, flags and constraints."
            )

        for p in placed:
            p.trailer_index = trailer_index

        all_trailer_placements.append(placed)

        vehicles = vehicles_unplaced
        tools = tools_unplaced_now + tools_kept_for_later

    if vehicles or tools:
        raise RuntimeError(
            "Ran out of trailers while items remain to be packed under "
            "ceiling/attachment rules."
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
    """ParaPy model that runs the packing algorithm and visualizes it."""

    items: List[Item] = Input()
    trailers: List[Any] = Input()

    # ------------------- Packing result -------------------

    @Attribute
    def packed_trailers(self) -> List[List[PlacedItem]]:
        return pack_items_into_trailers(self.items, self.trailers)

    @Attribute
    def flat_placed(self) -> List[PlacedItem]:
        return [p for trailer in self.packed_trailers for p in trailer]

    @Attribute
    def nb_trailers(self) -> int:
        if not self.flat_placed:
            return 0
        return max(p.trailer_index for p in self.flat_placed) + 1

    # ------------------- Derived trailer size / layout info -------------------

    @Attribute
    def trailer_sizes_used(self) -> List[Tuple[float, float, float]]:
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
        offsets: List[float] = []
        x = 0.0
        gap = 1.0
        for L in self.trailer_Ls:
            offsets.append(x)
            x += L + gap
        return offsets

    # ------------------- Open / closed trailer indices -------------------

    @Attribute
    def open_trailer_indices(self) -> List[int]:
        return [
            i
            for i in range(self.nb_trailers)
            if not self.trailers[i].has_ceiling
        ]

    @Attribute
    def closed_trailer_indices(self) -> List[int]:
        return [
            i
            for i in range(self.nb_trailers)
            if self.trailers[i].has_ceiling
        ]

    @Attribute
    def trailer_top_heights(self) -> List[float]:
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
        vs = [p for p in self.flat_placed if p.item.item_type == "vehicle"]
        colors = {}
        default_vehicle_color = [255, 255, 0]
        for p in vs:
            it = p.item
            c = getattr(it, "color", None)
            colors[it.id] = c if c not in (None, "") else default_vehicle_color
        return colors

    @Attribute
    def tool_colors(self):
        ts = [p for p in self.flat_placed if p.item.item_type == "tool"]
        colors = {}
        default_tool_color = [0, 0, 255]
        for p in ts:
            it = p.item
            c = getattr(it, "color", None)
            colors[it.id] = c if c not in (None, "") else default_tool_color
        return colors

    @Attribute
    def cargo_colors(self) -> List[List[int]]:
        colors: List[List[int]] = []
        for p in self.flat_placed:
            if p.item.item_type == "vehicle":
                colors.append(self.vehicle_colors[p.item.id])
            else:
                colors.append(self.tool_colors[p.item.id])
        return colors

    # ------------------- Geometry: trailers (markers) -------------------

    @Part
    def trailer_markers(self):
        """One TrailerMarker per used trailer, pointing to the underlying Trailer."""
        return TrailerMarker(
            quantify=self.nb_trailers,
            asset=getattr(
                self.trailers[child.index],
                "src",
                self.trailers[child.index],
            ),
            L=self.trailer_Ls[child.index],
            W=self.trailer_Ws[child.index],
            H=self.trailer_Hs[child.index],
            offset_x=self.trailer_offsets_x[child.index],
            color=(
                [160, 32, 240]
                if getattr(self.trailers[child.index], "has_ceiling", False)
                else [230, 230, 230]
            ),
            transparency=(
                0.8
                if getattr(self.trailers[child.index], "has_ceiling", False)
                else 0.9
            ),
        )

    @Part
    def closed_trailer_floors(self):
        return Box(
            quantify=len(self.closed_trailer_indices),
            width=self.trailer_Ls[
                self.closed_trailer_indices[child.index]
            ],
            length=self.trailer_Ws[
                self.closed_trailer_indices[child.index]
            ],
            height=0.3,
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[
                    self.closed_trailer_indices[child.index]
                ],
                "z",
                -0.3,
            ),
            color=[120, 120, 120],
            transparency=0.2,
        )

    @Part
    def open_trailer_floors(self):
        return Box(
            quantify=len(self.open_trailer_indices),
            width=self.trailer_Ls[self.open_trailer_indices[child.index]],
            length=self.trailer_Ws[self.open_trailer_indices[child.index]],
            height=0.3,
            position=XOY.translate(
                "x",
                self.trailer_offsets_x[
                    self.open_trailer_indices[child.index]
                ],
                "z",
                -0.3,
            ),
            color=[120, 120, 120],
            transparency=0.2,
        )

    # ------------------- Geometry: cargo -------------------

    @Part
    def cargo_markers(self):
        """All placed vehicles/tools as marker objects pointing to the original Machine/Tool."""
        return CargoMarker(
            quantify=len(self.flat_placed),
            asset=self.flat_placed[child.index].item.source,
            L=self.flat_placed[child.index].wx,
            W=self.flat_placed[child.index].wy,
            H=self.flat_placed[child.index].wz,
            x=(
                self.trailer_offsets_x[
                    self.flat_placed[child.index].trailer_index
                ]
                + self.flat_placed[child.index].x
            ),
            y=self.flat_placed[child.index].y,
            z=self.flat_placed[child.index].z,
            color=self.cargo_colors[child.index],
        )

    @action(
        label="Export",
        button_label="Export trailer arrangement to .stp",
    )
    def Export(self):
        writer = STEPWriter(trees=[self], filename="trailers.stp")
        writer.write()


# ---------------------------------------------------------------------------
# Helpers to integrate “machine-like” and “trailer-like” objects
# ---------------------------------------------------------------------------

def item_from_machine(machine, item_type_hint: str | None = None) -> Item:
    """Convert a machine-like object into an Item."""
    L, W, H = machine.overall_dimensions
    cls_name = type(machine).__name__
    item_id = machine.machine_id

    if item_type_hint is not None:
        item_type = item_type_hint
    else:
        item_type = (
            "vehicle"
            if cls_name in ("Truck", "Tractor", "Vehicle")
            else "tool"
        )

    if item_type == "vehicle":
        upright_only = True
        vehicle_attachable = False
    else:
        upright_only = False
        vehicle_attachable = False

    color = getattr(machine, "color", None)

    return Item(
        id=item_id,
        lx=L,
        ly=W,
        lz=H,
        item_type=item_type,
        upright_only=upright_only,
        vehicle_attachable=vehicle_attachable,
        color=color,
        source=machine,
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
        self.has_ceiling = True
        self.trailer_id = trailer_id or getattr(
            src_trailer,
            "machine_id",
            "",
        )
