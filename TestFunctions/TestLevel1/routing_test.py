from __future__ import annotations

import os
import sys

from parapy.core import Base, Input, Attribute, Part
from parapy.gui import display
from parapy.geom import Point, Position
from parapy.geom.occ.visual import Image

# -----------------------------------------------------------------------------
# Put project root on sys.path so we can import Routing.py from anywhere
# -----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Put project root on sys.path so we can import main and machine
# ---------------------------------------------------------------------------

THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))  # ../../ from this file

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

import Routing  # now resolves via PROJECT_ROOT

class RouteTest(Base):
    """Simple test model: visualize one ORS route as a Polyline."""

    # Inputs: (lat, lon)
    start = Input((51.15, 5))
    end = Input((51.547740, 5.5))
    machine_type = Input("Vehicle")

    @Attribute
    def route_result(self):
        """Call Routing.ComputeRoute and cache the result."""
        duration, distance, geometry = Routing.ComputeRoute(
            self.start, self.end, self.machine_type
        )
        print(f"Route duration [s]: {duration}")
        print(f"Route distance [m]: {distance}")
        return duration, distance, geometry

    @Attribute
    def route_geometry(self):
        """Just the geometry [[lon, lat], ...] from ORS / fallback."""
        return self.route_result[2]

    @Attribute
    def map_image_params(self):
        bottom_lat, top_lat, left_lon, right_lon, filename = Routing.choose_map(
            self.start, self.end
        )

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
    def route_polyline(self):
        """Polyline in XY from the routing geometry."""
        return Routing.RouteVisualization(
            geometry=self.route_geometry,
            start=self.start,
            end=self.end,
        )


if __name__ == "__main__":
    obj = RouteTest()
    display(obj)
