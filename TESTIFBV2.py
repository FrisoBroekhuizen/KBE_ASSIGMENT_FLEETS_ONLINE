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

