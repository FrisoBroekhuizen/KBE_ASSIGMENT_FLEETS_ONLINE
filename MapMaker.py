# MapMaker.py
from __future__ import annotations

import os
from typing import List, Tuple, Optional

from parapy.core import Base, Input, Attribute, Part, child
from parapy.geom import Point, Position, Polyline, Box, XOY
from parapy.geom.occ.visual import Image

import Routing

maindir = os.path.dirname(__file__)


class MapMaker(Base):
    """
    Generic map visualization for:
    - multiple transport routes
    - depot locations
    - work site locations

    routes:
        List of (start, end, machine_type) tuples.
        start, end: (lat, lon)
        machine_type: e.g. "Truck", "Tractor", "Vehicle".

    depots:
        List of depot GPS points (lat, lon).

    depot_sizes:
        Optional per‑depot box sizes (L, W, H) in meters.
        If empty or shorter than depots, a default cube_size is used.

    depot_rotations_deg:
        Optional per‑depot rotation around Z in degrees.
        Angle is applied in map XY, positive = CCW.

    work_sites:
        List of work site GPS points (lat, lon).

    worksite_sizes:
        Optional per‑worksite box sizes (L, W, H) in meters.

    worksite_rotations_deg:
        Optional per‑worksite rotation around Z in degrees.

    depot_cube_size:
        Fallback size if no specific size is given.
    """

    # (lat, lon, machine_type_str)
    routes: List[
        Tuple[Tuple[float, float], Tuple[float, float], str]
    ] = Input([])

    # (lat, lon)
    depots: List[Tuple[float, float]] = Input([])
    work_sites: List[Tuple[float, float]] = Input([])

    # Optional per‑object sizes and rotations
    depot_sizes: List[Tuple[float, float, float]] = Input([])
    depot_rotations_deg: List[float] = Input([])

    worksite_sizes: List[Tuple[float, float, float]] = Input([])
    worksite_rotations_deg: List[float] = Input([])

    depot_cube_size: float = Input(2000.0)

    # ------------------------------------------------------------------
    # Routing computations
    # ------------------------------------------------------------------
    @Attribute
    def route_results(self):
        """
        List of (start, end, duration, distance, geometry) for each route.
        geometry: [[lon, lat], ...] in ORS format.
        """
        results = []
        for start, end, machine_type in self.routes:
            duration, distance, geometry = Routing.ComputeRoute(
                start, end, machine_type
            )
            print(
                f"Route {start} -> {end} ({machine_type}): "
                f"duration [s]: {duration}, distance [m]: {distance}"
            )
            results.append((start, end, duration, distance, geometry))
        return results

    @Attribute
    def route_geometries(self):
        """List of geometries [[lon, lat], ...], one per *non-degenerate* route."""
        return [
            geometry
            for start, end, duration, distance, geometry in self.route_results
            if geometry and (distance is not None and distance >= 1.0)
        ]

    # ------------------------------------------------------------------
    # Map selection + image parameters
    # ------------------------------------------------------------------
    @Attribute
    def all_points(self):
        """All relevant GPS points: route endpoints + depots + work sites."""
        pts: List[Tuple[float, float]] = []
        for start, end, _ in self.routes:
            pts.append(start)
            pts.append(end)
        pts.extend(self.depots)
        pts.extend(self.work_sites)
        return pts

    @Attribute
    def map_selection(self):
        """
        bottom_lat, top_lat, left_lon, right_lon, filename
        for the single map (MAP1 or MAP2) that will contain all points.
        """
        return Routing.choose_map_for_points(self.all_points)

    @Attribute
    def map_image_params(self):
        bottom_lat, top_lat, left_lon, right_lon, filename = self.map_selection

        # width: east-west extent at bottom latitude
        width = Routing.HaversineDistance(
            bottom_lat, left_lon,
            bottom_lat, right_lon,
        )

        # length: north-south extent at left longitude
        length = Routing.HaversineDistance(
            bottom_lat, left_lon,
            top_lat, left_lon,
        )

        return filename, width, length

    @Attribute
    def map_origin_lat_lon(self):
        """Bottom-left GPS (lat, lon) used as (0, 0) in XY."""
        bottom_lat, top_lat, left_lon, right_lon, filename = self.map_selection
        return bottom_lat, left_lon

    # ------------------------------------------------------------------
    # Helpers to get per‑object sizes / rotations with fallbacks
    # ------------------------------------------------------------------
    @Attribute
    def _depot_sizes_effective(self) -> List[Tuple[float, float, float]]:
        """Return per‑depot sizes, using depot_cube_size for missing entries."""
        n = len(self.depots)
        base = list(self.depot_sizes)
        while len(base) < n:
            base.append((self.depot_cube_size,
                         self.depot_cube_size,
                         self.depot_cube_size))
        return base[:n]

    @Attribute
    def _depot_rot_effective(self) -> List[float]:
        """Return per‑depot rotations, missing -> 0.0 deg."""
        n = len(self.depots)
        base = list(self.depot_rotations_deg)
        while len(base) < n:
            base.append(0.0)
        return base[:n]

    @Attribute
    def _worksite_sizes_effective(self) -> List[Tuple[float, float, float]]:
        n = len(self.work_sites)
        base = list(self.worksite_sizes)
        while len(base) < n:
            base.append((self.depot_cube_size,
                         self.depot_cube_size,
                         self.depot_cube_size))
        return base[:n]

    @Attribute
    def _worksite_rot_effective(self) -> List[float]:
        n = len(self.work_sites)
        base = list(self.worksite_rotations_deg)
        while len(base) < n:
            base.append(0.0)
        return base[:n]

    # ------------------------------------------------------------------
    # Geometry: background map + routes + depots + worksites
    # ------------------------------------------------------------------
    @Part(parse=False)
    def map_image(self):
        """Background MAP1/MAP2 rectangle with texture."""
        return Image(
            filename=self.map_image_params[0],
            width=self.map_image_params[1],
            length=self.map_image_params[2],
            position=Position(
                location=Point(
                    self.map_image_params[1] / 2.0,
                    self.map_image_params[2] / 2.0,
                    0.0,
                )
            ),
        )

    @Part(parse=False)
    def route_polylines(self):
        """One Polyline per route, projected into XY using the chosen map."""
        return [
            Polyline(
                points=[
                    Point(
                        *Routing._latlon_to_xy(
                            lat,
                            lon,
                            self.map_origin_lat_lon[0],
                            self.map_origin_lat_lon[1],
                        ),
                        0.0,
                    )
                    for lon, lat in geometry
                ],
                color=(255, 0, 0),
                line_thickness=8,
            )
            for geometry in self.route_geometries
        ]

    @Part
    def depot_boxes(self):
        """Oriented Boxes at each depot location, using depot_sizes and
        depot_rotations_deg.
        """
        return Box(
            quantify=len(self.depots),
            width=self._depot_sizes_effective[child.index][0],
            length=self._depot_sizes_effective[child.index][1],
            height=self._depot_sizes_effective[child.index][2],
            position=XOY.translate(
                'x',
                Routing._latlon_to_xy(
                    self.depots[child.index][0],
                    self.depots[child.index][1],
                    self.map_origin_lat_lon[0],
                    self.map_origin_lat_lon[1],
                )[0],
                'y',
                Routing._latlon_to_xy(
                    self.depots[child.index][0],
                    self.depots[child.index][1],
                    self.map_origin_lat_lon[0],
                    self.map_origin_lat_lon[1],
                )[1],
                'z',
                self._depot_sizes_effective[child.index][2] / 2.0,
            ).rotate(
                'z',
                self._depot_rot_effective[child.index],
                deg=True,
            ),
            color="black",
            transparency=0.2,
        )

    @Part
    def worksite_boxes(self):
        """Oriented Boxes at each worksite location, using worksite_sizes and
        worksite_rotations_deg. Colored purple.
        """
        return Box(
            quantify=len(self.work_sites),
            width=self._worksite_sizes_effective[child.index][0],
            length=self._worksite_sizes_effective[child.index][1],
            height=self._worksite_sizes_effective[child.index][2],
            position=XOY.translate(
                'x',
                Routing._latlon_to_xy(
                    self.work_sites[child.index][0],
                    self.work_sites[child.index][1],
                    self.map_origin_lat_lon[0],
                    self.map_origin_lat_lon[1],
                )[0],
                'y',
                Routing._latlon_to_xy(
                    self.work_sites[child.index][0],
                    self.work_sites[child.index][1],
                    self.map_origin_lat_lon[0],
                    self.map_origin_lat_lon[1],
                )[1],
                'z',
                self._worksite_sizes_effective[child.index][2] / 2.0,
            ).rotate(
                'z',
                self._worksite_rot_effective[child.index],
                deg=True,
            ),
            color="purple",
            transparency=0.3,
        )

class FleetMapMaker(MapMaker):
    """
    Fleet overview map:
    - shows background map (same as MapMaker),
    - shows depots and work sites (same as MapMaker),
    - DOES NOT show route polylines,
    - additionally shows all assets (machines + trailers) as stacked boxes.

    Assets are:
        - positioned at their gps_location,
        - dimensions = overall_dimensions * 100 (for visibility),
        - grouped by identical gps_location and stacked in +Z,
        - colored from the asset's .color attribute (fallback: 'gray').

    Inputs
    ------
    assets:
        List of objects that at least have:
            - gps_location: (lat, lon)
            - overall_dimensions: (L, W, H)
            - color (optional)
    """

    # All routes are ignored visually, but keep the attribute for completeness
    assets: List[object] = Input([])

    # ------------------------------------------------------------------
    # Override all_points so map selection also considers assets
    # ------------------------------------------------------------------
    @Attribute
    def all_points(self):
        """All relevant GPS points: routes, depots, work sites AND assets."""
        pts: List[Tuple[float, float]] = []
        # routes
        for start, end, _ in self.routes:
            pts.append(start)
            pts.append(end)
        # depots & worksites
        pts.extend(self.depots)
        pts.extend(self.work_sites)
        # assets
        for obj in self.assets:
            latlon = getattr(obj, "gps_location", None)
            if latlon is not None:
                pts.append(tuple(latlon))
        return pts

    # ------------------------------------------------------------------
    # Disable red polylines
    # ------------------------------------------------------------------
    @Part(parse=False)
    def route_polylines(self):
        """No route polylines for the fleet overview."""
        return []

    # ------------------------------------------------------------------
    # Asset grouping & stacking
    # ------------------------------------------------------------------
    @Attribute
    def _asset_infos(self):
        """
        Flattened list of asset descriptors:
        [
          {
            'lat': float,
            'lon': float,
            'x': float,
            'y': float,
            'L': float,   # extent in x (Box.width)
            'W': float,   # extent in y (Box.length)
            'H': float,   # box height
            'color': Any,
            'z_center': float,
          },
          ...
        ]

        Assets are stacked vertically whenever their projected XY
        boxes intersect on the map.
        """

        def overlap_1d(c1, size1, c2, size2):
            """Check 1D interval overlap, center + full size."""
            return abs(c1 - c2) < 0.5 * (size1 + size2)

        from collections import deque

        origin_lat, origin_lon = self.map_origin_lat_lon

        # --- build raw list with projected XY and scaled sizes ---
        raw = []
        for obj in self.assets:
            latlon = getattr(obj, "gps_location", None)
            if latlon is None:
                continue

            lat, lon = latlon
            x, y = Routing._latlon_to_xy(lat, lon, origin_lat, origin_lon)

            dims = getattr(obj, "overall_dimensions", None)
            if not dims or len(dims) != 3:
                dims = (2.0, 2.0, 2.0)  # fallback cube

            scale = 500.0
            L = float(dims[0]) * scale  # x-extent  (Box.width)
            W = float(dims[1]) * scale  # y-extent  (Box.length)
            H = float(dims[2]) * scale

            color = getattr(obj, "color", "gray")

            raw.append({
                "lat": float(lat),
                "lon": float(lon),
                "x": x,
                "y": y,
                "L": L,
                "W": W,
                "H": H,
                "color": color,
                # z_center will be filled in during stacking
            })

        # Stable ordering: bottom‑to‑top in some deterministic way
        raw.sort(key=lambda d: (d["y"], d["x"]))

        placed = []

        # --- stacking logic: stack on top of any overlapping XY boxes ---
        for info in raw:
            base_z = 0.0  # bottom of this box

            for other in placed:
                # Check intersection in XY (axis‑aligned boxes)
                if (overlap_1d(info["x"], info["L"], other["x"], other["L"])
                        and overlap_1d(info["y"], info["W"], other["y"], other["W"])):
                    top_other = other["z_center"] + 0.5 * other["H"]
                    if top_other > base_z:
                        base_z = top_other

            info["z_center"] = base_z + 0.5 * info["H"]
            placed.append(info)

        return placed

    @Part
    def asset_boxes(self):
        """Stacked boxes for all machines / tools / trailers."""
        return Box(
            quantify=len(self._asset_infos),
            width=self._asset_infos[child.index]["L"],
            length=self._asset_infos[child.index]["W"],
            height=self._asset_infos[child.index]["H"],
            position=XOY.translate(
                'x', self._asset_infos[child.index]["x"],
                'y', self._asset_infos[child.index]["y"],
                'z', self._asset_infos[child.index]["z_center"],
            ),
            color=self._asset_infos[child.index]["color"],
            transparency=0.1,
        )


if __name__ == "__main__":
    from parapy.gui import display

    # simple test
    test_routes = [
        ((51.586911, 5.101759), (51.416232, 5.507185), "Truck"),
    ]
    test_depots = [(51.55, 5.10)]
    test_worksites = [(51.52, 5.30)]

    obj = MapMaker(
        routes=test_routes,
        depots=test_depots,
        depot_sizes=[(3000, 1500, 1000)],
        depot_rotations_deg=[30.0],
        work_sites=test_worksites,
        worksite_sizes=[(2500, 1200, 1000)],
        worksite_rotations_deg=[-15.0],
    )
    display(obj)
