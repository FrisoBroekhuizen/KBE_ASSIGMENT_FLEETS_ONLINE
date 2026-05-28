from __future__ import annotations

import os
from typing import List, Tuple

from parapy.core import Base, Input, Attribute, Part
from parapy.geom import Point, Position, Polyline, Cube
from parapy.geom.occ.visual import Image

import Routing

maindir = os.path.dirname(__file__)


class MapMaker(Base):
    """
    Generic map visualization for:
      - multiple transport routes
      - depot locations
      - work site locations

    Inputs
    ------
    routes:
        List of (start, end, machine_type) tuples.
        start, end: (lat, lon)
        machine_type: e.g. "Truck", "Tractor", "Vehicle" – used by Routing.ComputeRoute.
    depots:
        List of depot locations (lat, lon).
    work_sites:
        List of work site locations (lat, lon).
    depot_cube_size:
        Size of depot / worksite cubes in meters (same units as route projection).
    """

    # (lat, lon, machine_type_str)
    routes: List[
        Tuple[Tuple[float, float], Tuple[float, float], str]
    ] = Input([])

    # (lat, lon)
    depots: List[Tuple[float, float]] = Input([])
    work_sites: List[Tuple[float, float]] = Input([])

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
        """List of geometries [[lon, lat], ...], one per route."""
        return [res[4] for res in self.route_results]

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
    # Geometry: background map + routes + depots + worksites
    # ------------------------------------------------------------------
    @Part(parse=False)
    def map_image(self):
        """Background MAP1/MAP2 rectangle with texture."""
        filename, width, length = self.map_image_params
        pos = Position(location=Point(width / 2.0, length / 2.0, 0.0))
        return Image(
            filename=filename,
            width=width,
            length=length,
            position=pos,
        )

    @Part(parse=False)
    def route_polylines(self):
        """One Polyline per route, projected into XY using the chosen map."""
        origin_lat, origin_lon = self.map_origin_lat_lon

        return [
            Polyline(
                points=[
                    Point(
                        *Routing._latlon_to_xy(
                            lat,
                            lon,
                            origin_lat,
                            origin_lon,
                        ),
                        0.0,
                    )
                    for lon, lat in geometry
                ],
                color=(255, 0, 0),  # default red-ish; you can plug in your random_red_color here if desired
                line_thickness=8,
            )
            for geometry in self.route_geometries
        ]

    @Part(parse=False)
    def depot_cubes(self):
        """Black cubes at each depot location (lat, lon)."""
        if not self.depots:
            return []

        origin_lat, origin_lon = self.map_origin_lat_lon
        size = self.depot_cube_size

        return [
            Cube(
                dimension=size,
                centered=True,
                position=Position(
                    Point(
                        *Routing._latlon_to_xy(
                            lat,
                            lon,
                            origin_lat,
                            origin_lon,
                        ),
                        size / 2.0,
                    )
                ),
                color="black",
            )
            for (lat, lon) in self.depots
        ]

    @Part(parse=False)
    def worksite_cubes(self):
        """Purple cubes at each work site location (lat, lon)."""
        if not self.work_sites:
            return []

        origin_lat, origin_lon = self.map_origin_lat_lon
        size = self.depot_cube_size

        return [
            Cube(
                dimension=size,
                centered=True,
                position=Position(
                    Point(
                        *Routing._latlon_to_xy(
                            lat,
                            lon,
                            origin_lat,
                            origin_lon,
                        ),
                        size / 2.0,
                    )
                ),
                color="purple",
            )
            for (lat, lon) in self.work_sites
        ]


if __name__ == "__main__":
    from parapy.gui import display

    # simple test
    test_routes = [
        ((51.586911, 5.101759), (51.416232, 5.507185), "Truck"),
    ]
    test_depots = [(51.55, 5.10)]
    test_worksites = [(51.52, 5.30)]

    obj = MapMaker(routes=test_routes, depots=test_depots, work_sites=test_worksites)
    display(obj)
