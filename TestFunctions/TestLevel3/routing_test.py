from __future__ import annotations
import os
import sys
import random
from typing import List, Tuple
import subprocess, sys, os
from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.gui import display
from parapy.geom import Point, Position, Polyline, Cube
from parapy.geom.occ.visual import Image

# ---------------------------------------------------------------------------
# Put project root on sys.path so we can import Routing.py from anywhere
# ---------------------------------------------------------------------------

THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))  # ../../ from this file

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

import Routing  # now resolves via PROJECT_ROOT


def random_red_color(idx: int):
    """Deterministic 'random' shade of red per route index."""
    rng = random.Random(idx)  # same idx -> same color every time
    g = rng.randint(0, 120)   # green component (darker red if low)
    b = rng.randint(0, 120)   # blue component
    return (255, g, b)        # bright red channel, varying GB


class RouteTest(Base):
    """Visualize multiple routes as polylines on a single map."""

    # List of (start, end) pairs. Each start/end is (lat, lon).
    routes: List[Tuple[Tuple[float, float], Tuple[float, float]]] = Input([
        ((51.586911, 5.101759), (51.416232, 5.507185)),
        ((51.685523, 5.310957), (51.416232, 5.507185)),
    ])

    # Same machine type for all routes for now
    machine_type: str = Input("Vehicle")

    # Work site and depot locations (lat, lon)
    work_sites: List[Tuple[float, float]] = Input([
        (51.416232, 5.507185),
    ])
    depots: List[Tuple[float, float]] = Input([
        (51.586911, 5.101759),
        (51.685523, 5.310957),
    ])

    # Size of depot/worksite cubes in map units (meters)
    depot_cube_size: float = Input(2000.0)

    # ------------------------------------------------------------------
    # Routing computations
    # ------------------------------------------------------------------
    @Attribute
    def route_results(self):
        """List of (start, end, duration, distance, geometry) for each route."""
        results = []
        for start, end in self.routes:
            duration, distance, geometry = Routing.ComputeRoute(
                start, end, self.machine_type
            )
            print(
                f"[RouteTest] Route {start} -> {end}: "
                f"duration [s]: {duration}, distance [m]: {distance}"
            )
            results.append((start, end, duration, distance, geometry))
        return results

    @Attribute
    def route_geometries(self):
        """List of geometries [[lon, lat], ...], one per route."""
        return [res[4] for res in self.route_results]

    @Attribute
    def all_points(self):
        """All (lat, lon) points from all routes, depots and work sites."""
        pts: List[Tuple[float, float]] = []
        for start, end in self.routes:
            pts.append(start)
            pts.append(end)
        pts.extend(self.depots)
        pts.extend(self.work_sites)
        return pts

    # ------------------------------------------------------------------
    # Map selection + image parameters
    # ------------------------------------------------------------------
    @Attribute
    def map_selection(self):
        """
        bottom_lat, top_lat, left_lon, right_lon, filename
        for the single map that will contain all routes.
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
        """Bottom-left GPS (lat, lon) of the selected map, used as XY origin."""
        bottom_lat, top_lat, left_lon, right_lon, filename = self.map_selection
        return bottom_lat, left_lon

    # ------------------------------------------------------------------
    # Geometry: background map + multiple route polylines
    # ------------------------------------------------------------------
    @Part(parse=False)
    def map_image(self):
        """Background map rectangle with MAP1/MAP2 texture."""
        filename, width, length = self.map_image_params
        # center of rectangle at (width/2, length/2, 0)
        pos = Position(location=Point(width / 2.0, length / 2.0, 0.0))
        return Image(
            filename=filename,
            width=width,
            length=length,
            position=pos,
        )

    @Part(parse=False)
    def route_polylines(self):
        """
        One Polyline per route, all projected in the same XY coordinate system.
        """
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
                    for lon, lat in geometry  # ORS-style [lon, lat]
                ],
                color=random_red_color(idx),
                line_thickness=8,
            )
            for idx, geometry in enumerate(self.route_geometries)
        ]

    @Part(parse=False)
    def depot_cubes(self):
        """Black cubes at each depot location (lat, lon) projected on the map."""
        if not self.depots:
            return []  # no depots -> no children

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
                        size / 2.0,  # sit on top of the map plane (z=0)
                    )
                ),
                color="black",
            )
            for (lat, lon) in self.depots
        ]

    @Part(parse=False)
    def worksite_cubes(self):
        """Purple cubes at each work site location (lat, lon) projected on the map."""
        if not self.work_sites:
            return []  # no work sites -> no children

        origin_lat, origin_lon = self.map_origin_lat_lon
        size = self.depot_cube_size  # same size as depots

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
                        size / 2.0,  # sit on top of the map plane (z=0)
                    )
                ),
                color="purple",  # ParaPy accepts named colors like 'purple'
            )
            for (lat, lon) in self.work_sites
        ]

    # ------------------------------------------------------------------
    # ACTION: open this RouteTest in a new window
    # ------------------------------------------------------------------
    @action(button_label="Open RouteTest (external)")
    def open_route_test(self):
        # launch new Python process running route_test.py
        script = os.path.join(os.path.dirname(__file__), "routing_test.py")
        subprocess.Popen([sys.executable, script])


if __name__ == "__main__":
    # When running this file directly:
    # - a RouteTest root will appear
    # - in the inspector you’ll see the "Open RouteTest Viewer" action button
    obj = RouteTest()
    display(obj)
