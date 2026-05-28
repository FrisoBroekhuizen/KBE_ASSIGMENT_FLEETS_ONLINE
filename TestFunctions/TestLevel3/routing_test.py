from __future__ import annotations
import random

import os
import sys
from typing import List, Tuple

from parapy.core import Base, Input, Attribute, Part, child
from parapy.gui import display
from parapy.geom import Point, Position, Polyline
from parapy.geom.occ.visual import Image

# ---------------------------------------------------------------------------
# Put project root on sys.path so we can import Routing.py from anywhere
# ---------------------------------------------------------------------------

THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))  # ../../ from this file

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

import Routing  # now resolves via PROJECT_ROOT


class RouteTest(Base):
    """Visualize multiple ORS routes as Polylines on a single map."""

    # List of (start, end) pairs. Each start/end is (lat, lon).
    routes: List[Tuple[Tuple[float, float], Tuple[float, float]]] = Input([
        ((51.586911, 5.101759), (51.416232, 5.507185)),
        ((51.685523, 5.310957), (51.416232, 5.507185)),
        # ((lat3, lon3), (lat4, lon4)),
    ])

    # Same machine type for all routes for now
    machine_type: str = Input("Vehicle")

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
            print(f"Route {start} -> {end}: duration [s]: {duration}, distance [m]: {distance}")
            results.append((start, end, duration, distance, geometry))
        return results

    @Attribute
    def route_geometries(self):
        """List of geometries [[lon, lat], ...], one per route."""
        return [res[4] for res in self.route_results]

    @Attribute
    def all_points(self):
        """Flat list of all (lat, lon) points from all routes."""
        pts: List[Tuple[float, float]] = []
        for start, end in self.routes:
            pts.append(start)
            pts.append(end)
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

        This returns a plain Python list of Polyline objects.
        ParaPy will treat each Polyline as a separate child.
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
                    for lon, lat in geometry
                ],
                color=random_red_color(idx),
                line_thickness=8,
            )
            for idx, geometry in enumerate(self.route_geometries)
        ]
def random_red_color(idx: int):
    """Deterministic 'random' shade of red per route index."""
    rng = random.Random(idx)  # same idx -> same color every time
    g = rng.randint(0, 120)   # green component (darker red if low)
    b = rng.randint(0, 120)   # blue component
    return (255, g, b)        # bright red channel, varying GB
if __name__ == "__main__":
    obj = RouteTest()
    display(obj)