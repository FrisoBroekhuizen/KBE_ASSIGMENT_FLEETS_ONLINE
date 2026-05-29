# """
# Very simple visual test for trailer packing under the new rules.
#
# - Edit the VEHICLES / UPRIGHT_TOOLS / ATTACHABLE_UPRIGHT_TOOLS / STACKABLE_TOOLS
#   lists below to define your test case.
# - Run this file (e.g. via PyCharm) to open a ParaPy GUI window.
#
# Conventions:
# - All tuples are (L, W, H) in meters, i.e. bounding boxes.
# - Vehicles:
#     * floor-only (z = 0), cannot be stacked on or under.
# - Tools:
#     * if upright_only == True:
#         - behave like vehicles: floor-only, upright, no stacking above.
#     * otherwise: stackable in 3D where allowed.
# - Trailers:
#     * open (has_ceiling=False): only accept
#         - vehicles; and
#         - tools with vehicle_attachable == True AND upright_only == True.
#       Visualized as light grey, very transparent boxes.
#     * closed (has_ceiling=True): accept all items.
#       Visualized as purple, semi-transparent boxes.
#
# Colors:
# - Vehicles: random yellowish colors.
# - Tools:
#     * attachable + upright_only: solid purple (fixed color).
#     * if only upright_only (nonturnable): very light/baby blue
#     * if only vehicle_attachable: pink
#     * other tools: random bluish colors.
# """
#
# from __future__ import annotations
#
# import os
# import sys
# import random
# from typing import List, Tuple
#
# from parapy.core import Base, Part, Attribute, Input, child
# from parapy.geom import Box, XOY
# from parapy.gui import display
#
# # -----------------------------------------------------------------------------
# # Put project root on sys.path so we can import GeomArrangement
# # -----------------------------------------------------------------------------
#
# THIS_DIR = os.path.dirname(__file__)
# PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))  # ../../ from this file
#
# if PROJECT_ROOT not in sys.path:
#     sys.path.append(PROJECT_ROOT)
#
# from TrailerArrangement import Item, pack_items_into_trailers
# # -----------------------------------------------------------------------------
# # Simple trailer config class used by this test
# # -----------------------------------------------------------------------------
# class SimpleTrailer:
#     """Minimal trailer-like object for the pack_items_into_trailers API."""
#
#     def __init__(
#         self,
#         trailer_id: str,
#         carrying_bounding_box: Tuple[float, float, float],
#         has_ceiling: bool,
#     ):
#         self.trailer_id = trailer_id
#         self.carrying_bounding_box = carrying_bounding_box
#         self.has_ceiling = has_ceiling
# # -----------------------------------------------------------------------------
# # CONFIG: edit these lists to define your test scenario
# # -----------------------------------------------------------------------------
#
# # Vehicles: (L, W, H) [m]
# VEHICLES: List[Tuple[float, float, float]] = [
#     (4.0, 2.5, 2.0),  # Vehicle 1
#     (3.0, 2.0, 1.8),  # Vehicle 2
# ]
#
# # Upright-only, non-attachable tools (behave like vehicles regarding packing)
# UPRIGHT_TOOLS: List[Tuple[float, float, float]] = [
#     (2.0, 1.5, 1.5),
#
# ]
#
# # Large attachable, upright-only tool (allowed on open trailers)
# ATTACHABLE_UPRIGHT_TOOLS: List[Tuple[float, float, float]] = [
#     (5.0, 2.0, 1.8),  # big trailer-behind type implement
# ]
#
# # Normal stackable tools (can be rotated in all 3 axes, stacked in 3D)
# STACKABLE_TOOLS: List[Tuple[float, float, float]] = [
#     (2.0, 1.0, 1.0),
#     (1.2, 1.0, 1.5),
#     (1.8, 1.2, 1.3)
# ]
#
# # Trailer configurations:
# # - 1 open (no ceiling), 2 closed (one smaller than the other).
# TRAILERS: List[SimpleTrailer] = [
#     SimpleTrailer("T1_open",  (26.0, 2.5, 2.5), False),  # open flatbed
#     SimpleTrailer("T2_small", (7.0, 2.5, 3.0), True),   # small closed
#     SimpleTrailer("T3_large", (9.0, 2.8, 3.5), True),   # large closed
# ]
#
#
# # -----------------------------------------------------------------------------
# # ParaPy visualization model
# # -----------------------------------------------------------------------------
#
# class PackingTest(Base):
#     """Simple ParaPy model that runs the packing algorithm and visualizes it."""
#
#     # List of trailers we allow the algorithm to use
#     trailers: List[SimpleTrailer] = Input(TRAILERS)
#
#     @Attribute
#     def items(self) -> List[Item]:
#         """Convert config lists into Item objects with proper flags."""
#         items: List[Item] = []
#
#         # Vehicles
#         for i, (L, W, H) in enumerate(VEHICLES, start=1):
#             items.append(
#                 Item(
#                     id=f"V{i}",
#                     lx=L,
#                     ly=W,
#                     lz=H,
#                     item_type="vehicle",
#                     upright_only=True,          # vehicles are effectively upright-only
#                     vehicle_attachable=False,   # domain-specific; change if needed
#                 )
#             )
#
#         # Upright-only tools (non attachable)
#         for i, (L, W, H) in enumerate(UPRIGHT_TOOLS, start=1):
#             items.append(
#                 Item(
#                     id=f"UT{i}",
#                     lx=L,
#                     ly=W,
#                     lz=H,
#                     item_type="tool",
#                     upright_only=True,
#                     vehicle_attachable=False,
#                 )
#             )
#
#         # Attachable + upright-only tools
#         for i, (L, W, H) in enumerate(ATTACHABLE_UPRIGHT_TOOLS, start=1):
#             items.append(
#                 Item(
#                     id=f"AT{i}",
#                     lx=L,
#                     ly=W,
#                     lz=H,
#                     item_type="tool",
#                     upright_only=True,
#                     vehicle_attachable=True,
#                 )
#             )
#
#         # Normal stackable tools
#         for i, (L, W, H) in enumerate(STACKABLE_TOOLS, start=1):
#             items.append(
#                 Item(
#                     id=f"ST{i}",
#                     lx=L,
#                     ly=W,
#                     lz=H,
#                     item_type="tool",
#                     upright_only=False,
#                     vehicle_attachable=False,
#                 )
#             )
#
#         return items
#
#     @Attribute
#     def packed_trailers(self):
#         """Run the packing algorithm on the current items and trailers."""
#         return pack_items_into_trailers(
#             self.items,
#             self.trailers,
#         )
#
#     @Attribute
#     def flat_placed(self):
#         """Flatten [ [PlacedItem,...], [PlacedItem,...], ... ] into one list."""
#         return [p for trailer in self.packed_trailers for p in trailer]
#
#     @Attribute
#     def nb_trailers(self) -> int:
#         """Number of trailers actually used."""
#         if not self.flat_placed:
#             return 0
#         return max(p.trailer_index for p in self.flat_placed) + 1
#
#     # --- Derived trailer size / layout info ----------------------------------
#
#     @Attribute
#     def trailer_sizes_used(self) -> List[Tuple[float, float, float]]:
#         """Sizes of trailers that are actually used (subset of TRAILERS)."""
#         return [
#             self.trailers[i].carrying_bounding_box
#             for i in range(self.nb_trailers)
#         ]
#
#     @Attribute
#     def trailer_Ls(self) -> List[float]:
#         return [sz[0] for sz in self.trailer_sizes_used]
#
#     @Attribute
#     def trailer_Ws(self) -> List[float]:
#         return [sz[1] for sz in self.trailer_sizes_used]
#
#     @Attribute
#     def trailer_Hs(self) -> List[float]:
#         return [sz[2] for sz in self.trailer_sizes_used]
#
#     @Attribute
#     def trailer_offsets_x(self) -> List[float]:
#         """Cumulative X offsets for each trailer so they don't overlap."""
#         offsets: List[float] = []
#         x = 0.0
#         gap = 1.0  # 1 m gap between trailers
#         for L in self.trailer_Ls:
#             offsets.append(x)
#             x += L + gap
#         return offsets
#
#     # --- Open/closed trailer index helpers -----------------------------------
#
#     @Attribute
#     def open_trailer_indices(self) -> List[int]:
#         """Indices of open (no-ceiling) trailers that are actually used."""
#         return [
#             i for i in range(self.nb_trailers)
#             if not self.trailers[i].has_ceiling
#         ]
#
#     @Attribute
#     def closed_trailer_indices(self) -> List[int]:
#         """Indices of closed (ceiling) trailers that are actually used."""
#         return [
#             i for i in range(self.nb_trailers)
#             if self.trailers[i].has_ceiling
#         ]
#
#     @Attribute
#     def trailer_top_heights(self) -> List[float]:
#         """For each used trailer, height of the open 'envelope' box.
#
#         For trailer i, we take:
#             max_top_z = max(p.z + p.wz for p in items on that trailer)
#             envelope_height = max_top_z * 1.1
#
#         If a trailer is empty (shouldn't really happen for used ones),
#         we fall back to its carrying_bounding_box height.
#         """
#         heights: List[float] = []
#         for i in range(self.nb_trailers):
#             items_i = [p for p in self.flat_placed if p.trailer_index == i]
#             if items_i:
#                 max_top_z = max(p.z + p.wz for p in items_i)
#                 heights.append(max_top_z * 1.1)
#             else:
#                 # fall back to nominal trailer height
#                 heights.append(self.trailers[i].carrying_bounding_box[2])
#         return heights
#
#     # --- Cargo color helpers --------------------------------------------------
#
#     @Attribute
#     def vehicle_colors(self):
#         """Deterministic random yellowish colors for vehicles."""
#         random.seed(1)
#         vs = [p for p in self.flat_placed if p.item.item_type == "vehicle"]
#         colors = {}
#         for p in vs:
#             # Yellowish: high R and G, low B
#             r = 200 + random.randint(0, 55)
#             g = 200 + random.randint(0, 55)
#             b = random.randint(0, 70)
#             colors[p.item.id] = [r, g, b]
#         return colors
#
#     @Attribute
#     def tool_colors(self):
#         """Colors for tools:
#         - only attachable (vehicle_attachable == True, upright_only == False): pink
#         - only upright_only (upright_only == True, vehicle_attachable == False): very light/baby blue
#         - both attachable and upright_only: purple
#         - neither: bluish random (fallback)
#         """
#         random.seed(2)
#         ts = [p for p in self.flat_placed if p.item.item_type == "tool"]
#         colors = {}
#         for p in ts:
#             it = p.item
#             if it.vehicle_attachable and not it.upright_only:
#                 # Only attachable: pink
#                 colors[it.id] = [255, 105, 180]  # hot pink
#             elif it.upright_only and not it.vehicle_attachable:
#                 # Only upright_only: very light / baby blue
#                 colors[it.id] = [173, 216, 230]
#             elif it.vehicle_attachable and it.upright_only:
#                 # Both: purple
#                 colors[it.id] = [160, 32, 240]
#             else:
#                 # Neither: bluish random fallback
#                 r = random.randint(0, 60)
#                 g = random.randint(0, 140)
#                 b = 180 + random.randint(0, 70)
#                 colors[it.id] = [r, g, b]
#         return colors
#
#     @Attribute
#     def cargo_colors(self):
#         """Color per placed item index (already flattened)."""
#         colors: List[List[int]] = []
#         for p in self.flat_placed:
#             if p.item.item_type == "vehicle":
#                 colors.append(self.vehicle_colors[p.item.id])
#             else:
#                 colors.append(self.tool_colors[p.item.id])
#         return colors
#
#     # --- Geometry: trailers (closed vs open) ---------------------------------
#
#     @Part
#     def closed_trailer_boxes(self):
#         """Closed trailer volumes: purple, semi-transparent."""
#         return Box(
#             quantify=len(self.closed_trailer_indices),
#             width=self.trailer_Ls[self.closed_trailer_indices[child.index]],
#             length=self.trailer_Ws[self.closed_trailer_indices[child.index]],
#             height=self.trailer_Hs[self.closed_trailer_indices[child.index]],
#             position=XOY.translate(
#                 "x",
#                 self.trailer_offsets_x[self.closed_trailer_indices[child.index]],
#             ),
#             color=[160, 32, 240],
#             transparency=0.8,
#         )
#
#     @Part
#     def closed_trailer_floors(self):
#         """Closed trailer floor 'material': darker grey, 0.3 m thick, extending downward."""
#         return Box(
#             quantify=len(self.closed_trailer_indices),
#             width=self.trailer_Ls[self.closed_trailer_indices[child.index]],
#             length=self.trailer_Ws[self.closed_trailer_indices[child.index]],
#             height=0.3,
#             position=XOY.translate(
#                 "x",
#                 self.trailer_offsets_x[self.closed_trailer_indices[child.index]],
#                 "z",
#                 -0.3,
#             ),
#             color=[120, 120, 120],
#             transparency=0.2,
#         )
#
#     @Part
#     def open_trailer_tops(self):
#         """Open trailer 'envelope' volumes: very light grey, highly transparent.
#
#         Height computed as 1.1 * max cargo top (z + wz) for that trailer.
#         """
#         return Box(
#             quantify=len(self.open_trailer_indices),
#             width=self.trailer_Ls[self.open_trailer_indices[child.index]],
#             length=self.trailer_Ws[self.open_trailer_indices[child.index]],
#             height=self.trailer_top_heights[self.open_trailer_indices[child.index]],
#             position=XOY.translate(
#                 "x",
#                 self.trailer_offsets_x[self.open_trailer_indices[child.index]],
#                 "z",
#                 0.0,
#             ),
#             color=[230, 230, 230],
#             transparency=0.9,
#         )
#
#     @Part
#     def open_trailer_floors(self):
#         """Open trailer floor 'material': darker grey, 0.3 m thick, extending downward."""
#         return Box(
#             quantify=len(self.open_trailer_indices),
#             width=self.trailer_Ls[self.open_trailer_indices[child.index]],
#             length=self.trailer_Ws[self.open_trailer_indices[child.index]],
#             height=0.3,
#             position=XOY.translate(
#                 "x",
#                 self.trailer_offsets_x[self.open_trailer_indices[child.index]],
#                 "z",
#                 -0.3,
#             ),
#             color=[120, 120, 120],
#             transparency=0.2,
#         )
#
#     # --- Geometry: cargo ------------------------------------------------------
#
#     @Part
#     def cargo_boxes(self):
#         """All placed vehicles/tools as colored boxes inside trailers."""
#         return Box(
#             quantify=len(self.flat_placed),
#             width=self.flat_placed[child.index].wx,
#             length=self.flat_placed[child.index].wy,
#             height=self.flat_placed[child.index].wz,
#             position=XOY.translate(
#                 "x",
#                 self.trailer_offsets_x[
#                     self.flat_placed[child.index].trailer_index
#                 ] + self.flat_placed[child.index].x,
#                 "y",
#                 self.flat_placed[child.index].y,
#                 "z",
#                 self.flat_placed[child.index].z,
#             ),
#             color=self.cargo_colors[child.index],
#         )
#
#
#
# # -----------------------------------------------------------------------------
# # Run as script
# # -----------------------------------------------------------------------------
#
# if __name__ == "__main__":
#     display(PackingTest())

