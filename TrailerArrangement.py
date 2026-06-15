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
class WinningMissionTrailerPacking(Base):
    """Visualization of trailers and their *current* contents in a winning mission.

    - trailers: list of real Trailer objects (as in winning_mission).
    - cargo_per_trailer: parallel list of lists of Machine/Tool objects.
    - For each trailer, we:
        * build Items from the machines/tools,
        * run pack_single_trailer() to place them in 3D,
        * visualize trailers and cargo with real dimensions & colors,
        * preserve references to the original assets via CargoMarker.asset.
    """

    trailers: List[Any] = Input()
    cargo_per_trailer: List[List[object]] = Input()  # len == len(trailers)

    # ----------------- Derived: sizes & offsets -----------------

    @Attribute
    def trailer_sizes(self) -> List[Tuple[float, float, float]]:
        """Use each trailer.overall_dimensions as [L, W, H]."""
        sizes = []
        for tr in self.trailers:
            L, W, H = getattr(tr, "overall_dimensions", (0.0, 0.0, 0.0))
            sizes.append((float(L), float(W), float(H)))
        return sizes

    @Attribute
    def trailer_offsets_x(self) -> List[float]:
        """Lay out trailers next to each other along +X."""
        offsets = []
        x = 0.0
        gap = 1.0  # 1 m gap between trailers
        for (L, _, _) in self.trailer_sizes:
            offsets.append(x)
            x += L + gap
        return offsets

    # ----------------- Derived: packing per trailer -----------------

    @Attribute
    def placements_per_trailer(self) -> List[List[PlacedItem]]:
        """Run pack_single_trailer per trailer, using its own contents only."""
        all_placements: List[List[PlacedItem]] = []

        for idx, (tr, cargo_list) in enumerate(
            zip(self.trailers, self.cargo_per_trailer)
        ):
            if not cargo_list:
                all_placements.append([])
                continue

            # trailer size
            L, W, H = self.trailer_sizes[idx]

            # Build Items from actual machines/tools
            items: List[Item] = [
                item_from_machine(m) for m in cargo_list if m is not None
            ]
            vehicles = [it for it in items if it.item_type == "vehicle"]
            tools = [it for it in items if it.item_type == "tool"]

            # Use your existing per-trailer packing heuristic
            placed, veh_unplaced, tools_unplaced = pack_single_trailer(
                vehicles=vehicles,
                tools=tools,
                L=L,
                W=W,
                H=H,
            )

            if veh_unplaced or tools_unplaced:
                print(
                    f"[WinningMissionTrailerPacking] WARNING: "
                    f"{len(veh_unplaced)} vehicles and "
                    f"{len(tools_unplaced)} tools did not fit in trailer "
                    f"{getattr(tr, 'trailer_id', None)}."
                )

            # Set trailer_index to this trailer
            for p in placed:
                p.trailer_index = idx

            all_placements.append(placed)

        return all_placements

    @Attribute
    def flat_placed(self) -> List[PlacedItem]:
        return [p for trailer in self.placements_per_trailer for p in trailer]

    # ----------------- Geometry: trailers -----------------

    @Part
    def trailer_markers(self):
        """One TrailerMarker per trailer, using real dimensions."""
        return TrailerMarker(
            quantify=len(self.trailers),
            asset=self.trailers[child.index],
            L=self.trailer_sizes[child.index][0],
            W=self.trailer_sizes[child.index][1],
            H=self.trailer_sizes[child.index][2],
            offset_x=self.trailer_offsets_x[child.index],
            color=(160, 32, 240),
            transparency=0.8,
        )

    # ----------------- Geometry: cargo -----------------

    @Part
    def cargo_markers(self):
        """Boxes for all placed items, pointing back to the real Machine/Tool."""
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
            color=(
                getattr(
                    self.flat_placed[child.index].item,
                    "color",
                    getattr(
                        self.flat_placed[child.index].item.source,
                        "color",
                        "gray",
                    ),
                )
            ),
        )

    @action(
        label="Export",
        button_label="Export trailer arrangement to .stp",
    )
    def Export(self):
        writer = STEPWriter(trees=[self], filename="winning_trailers.stp")
        writer.write()
