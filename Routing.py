# Routing.py
from __future__ import annotations
import math
import os
import time
from typing import Tuple, List

from parapy.geom import Point, Polyline
from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter
from parapy.core.validate import OneOf

from routingpy import ORS
from routingpy.exceptions import RouterApiError  # <<< MISSING IMPORT

maindir = os.path.dirname(__file__)

# ---------------------------------------------------------------------
# Global map bounds (lat, lon) for your screenshots
# ---------------------------------------------------------------------
# Small MAP1:
MAP1_CORNER_1: Tuple[float, float] = (51.084598, 4.210087)  # bottom-left (lat, lon)
MAP1_CORNER_2: Tuple[float, float] = (51.95, 6.049)  # top-right (lat, lon) – adjust when you know it

# Large MAP2:
MAP2_CORNER_1: Tuple[float, float] = (43.312459, -1.987007)
MAP2_CORNER_2: Tuple[float, float] = (54.65, 22.928525)


def HaversineDistance(
    lat1: float, lon1: float,
    lat2: float, lon2: float
) -> float:
    """Great-circle distance between two GPS points in meters."""
    R = 6371000.0  # Earth radius [m]
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def ComputeRoute(start, end, machine_type):
    """
    start, end: (lat, lon)
    machine_type: "Vehicle" -> driving-car, anything else -> driving-hgv
    """
    start_lat, start_lon = start
    end_lat, end_lon = end

    # ORS expects [lon, lat]
    coordinates = [
        [start_lon, start_lat],
        [end_lon, end_lat],
    ]

    # Option A: environment variable
    api_key = os.environ.get("ORS_API_KEY", None)
    if api_key is None:
        # Option B: hard-code (use the SAME value as in your working test script)
        api_key = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImY0OThhNGEyMGQwYjRmZjE5MDdmOGU2NjQzMDY0ZGVjIiwiaCI6Im11cm11cjY0In0="

    client = ORS(api_key=api_key)

    profile = "driving-car" if machine_type == "Vehicle" else "driving-hgv"

    try:
        route = client.directions(locations=coordinates, profile=profile)
    except RouterApiError as e:
        # Keep ParaPy running even if ORS fails: straight-line fallback
        print(f"[ComputeRoute] ORS error: {e}")
        (lat1, lon1) = start
        (lat2, lon2) = end

        n = 20
        geometry: List[List[float]] = []
        for i in range(n + 1):
            t = i / n
            lat = lat1 + t * (lat2 - lat1)
            lon = lon1 + t * (lon2 - lon1)
            geometry.append([lon, lat])  # [lon, lat]

        total_dist = HaversineDistance(lat1, lon1, lat2, lon2)
        avg_speed = 20.0  # m/s ~ 72 km/h
        duration = total_dist / avg_speed
        return duration, total_dist, geometry

    duration = route.duration
    distance = route.distance
    geometry = route.geometry

    # print("Time taken: {} seconds".format(duration))
    # print("Route distance: {} meters".format(distance))

    return duration, distance, geometry


    duration = route.duration
    distance = route.distance
    geometry = route.geometry

    print("Time taken: {} seconds".format(duration))
    print("Route distance: {} meters".format(distance))

    return duration, distance, geometry
# ---------------------------------------------------------------------
# Helpers for map selection + projection
# ---------------------------------------------------------------------
def _latlon_to_xy(
    lat: float,
    lon: float,
    origin_lat: float,
    origin_lon: float,
) -> Tuple[float, float]:
    """Project (lat, lon) to local (x, y) in meters w.r.t. (origin_lat, origin_lon).

    x: east-positive distance
    y: north-positive distance
    """
    # north-south distance (same lon)
    dy = HaversineDistance(origin_lat, origin_lon, lat, origin_lon)
    if lat < origin_lat:
        dy = -dy

    # east-west distance (same lat)
    dx = HaversineDistance(origin_lat, origin_lon, origin_lat, lon)
    if lon < origin_lon:
        dx = -dx

    return dx, dy


def _normalize_bounds(c1: Tuple[float, float],
                      c2: Tuple[float, float]) -> Tuple[float, float, float, float]:
    """From two corners (lat, lon) return (bottom_lat, top_lat, left_lon, right_lon)."""
    lat1, lon1 = c1
    lat2, lon2 = c2
    top_lat = max(lat1, lat2)
    bottom_lat = min(lat1, lat2)
    left_lon = min(lon1, lon2)
    right_lon = max(lon1, lon2)
    return bottom_lat, top_lat, left_lon, right_lon


def _point_in_bounds(lat: float, lon: float,
                     bottom_lat: float, top_lat: float,
                     left_lon: float, right_lon: float) -> bool:
    return (bottom_lat <= lat <= top_lat) and (left_lon <= lon <= right_lon)

def choose_map(start: Tuple[float, float],
               end: Tuple[float, float]) -> Tuple[float, float, float, float, str]:
    """
    Decide which map to use and return its bounds + filename.

    Returns
    -------
    bottom_lat, top_lat, left_lon, right_lon, filename
    """
    # unpack map bounds
    map1_bottom, map1_top, map1_left, map1_right = _normalize_bounds(
        MAP1_CORNER_1, MAP1_CORNER_2
    )
    map2_bottom, map2_top, map2_left, map2_right = _normalize_bounds(
        MAP2_CORNER_1, MAP2_CORNER_2
    )

    start_lat, start_lon = start
    end_lat, end_lon = end

    # in‑bounds checks
    start_in_map1 = _point_in_bounds(start_lat, start_lon,
                                     map1_bottom, map1_top,
                                     map1_left, map1_right)
    end_in_map1 = _point_in_bounds(end_lat, end_lon,
                                   map1_bottom, map1_top,
                                   map1_left, map1_right)

    if start_in_map1 and end_in_map1:
        # small MAP1
        bottom_lat = map1_bottom
        top_lat = map1_top
        left_lon = map1_left
        right_lon = map1_right
        filename = os.path.join(maindir, "MAPS", "MAP1.png")
    else:
        # large MAP2
        bottom_lat = map2_bottom
        top_lat = map2_top
        left_lon = map2_left
        right_lon = map2_right
        filename = os.path.join(maindir, "MAPS", "MAP2.png")

    return bottom_lat, top_lat, left_lon, right_lon, filename

def choose_map_for_points(points: List[Tuple[float, float]]
                          ) -> Tuple[float, float, float, float, str]:
    """
    Decide which map to use based on a list of (lat, lon) points.

    - If ALL points are inside MAP1, use MAP1.
    - Otherwise, fall back to MAP2.

    Returns
    -------
    bottom_lat, top_lat, left_lon, right_lon, filename
    """
    # unpack map bounds
    map1_bottom, map1_top, map1_left, map1_right = _normalize_bounds(
        MAP1_CORNER_1, MAP1_CORNER_2
    )
    map2_bottom, map2_top, map2_left, map2_right = _normalize_bounds(
        MAP2_CORNER_1, MAP2_CORNER_2
    )

    # if no points are given, just use MAP2 by default
    if not points:
        bottom_lat = map2_bottom
        top_lat = map2_top
        left_lon = map2_left
        right_lon = map2_right
        filename = os.path.join(maindir, "MAPS", "MAP2.png")
        return bottom_lat, top_lat, left_lon, right_lon, filename

    # check if all points lie in MAP1
    all_in_map1 = True
    for lat, lon in points:
        if not _point_in_bounds(lat, lon,
                                map1_bottom, map1_top,
                                map1_left, map1_right):
            all_in_map1 = False
            break

    if all_in_map1:
        # small MAP1
        bottom_lat = map1_bottom
        top_lat = map1_top
        left_lon = map1_left
        right_lon = map1_right
        filename = os.path.join(maindir, "MAPS", "MAP1.png")
    else:
        # large MAP2
        bottom_lat = map2_bottom
        top_lat = map2_top
        left_lon = map2_left
        right_lon = map2_right
        filename = os.path.join(maindir, "MAPS", "MAP2.png")

    return bottom_lat, top_lat, left_lon, right_lon, filename

# ---------------------------------------------------------------------
# Core: map‑aware route visualization
# ---------------------------------------------------------------------
def RouteVisualization(
    geometry: List[List[float]],
    start: Tuple[float, float],
    end: Tuple[float, float],
) -> Polyline:
    """
    Convert ORS geometry [[lon, lat], ...] into a red Polyline in local XY coordinates.

    Map selection:
    --------------
    - If BOTH start and end are inside MAP1, then MAP1 is used:
        - origin (0, 0) = bottom-left of MAP1.
    - Otherwise, MAP2 is used:
        - origin (0, 0) = bottom-left of MAP2.

    Parameters
    ----------
    geometry:
        Output from ORS (route.geometry): list of [lon, lat] pairs.
    start, end:
        (lat, lon) of the begin and end locations.

    Returns
    -------
    Polyline:
        A parapy.geom.Polyline in the XY plane (z = 0) with color="red".
        You can display it directly in ParaPy GUI.
    """
    # --- unpack map bounds ---
    map1_bottom, map1_top, map1_left, map1_right = _normalize_bounds(
        MAP1_CORNER_1, MAP1_CORNER_2
    )
    map2_bottom, map2_top, map2_left, map2_right = _normalize_bounds(
        MAP2_CORNER_1, MAP2_CORNER_2
    )

    start_lat, start_lon = start
    end_lat, end_lon = end

    # --- decide which map to use ---
    start_in_map1 = _point_in_bounds(
        start_lat, start_lon,
        map1_bottom, map1_top,
        map1_left, map1_right
    )
    end_in_map1 = _point_in_bounds(
        end_lat, end_lon,
        map1_bottom, map1_top,
        map1_left, map1_right
    )

    if start_in_map1 and end_in_map1:
        # Use small MAP1
        bottom_lat = map1_bottom
        left_lon = map1_left
    else:
        # Fall back to large MAP2
        bottom_lat = map2_bottom
        left_lon = map2_left

    origin_lat = bottom_lat
    origin_lon = left_lon

    # --- build polyline points ---
    points: List[Point] = []

    for lon, lat in geometry:
        # geometry is [lon, lat]; _latlon_to_xy expects (lat, lon)
        x, y = _latlon_to_xy(lat, lon, origin_lat, origin_lon)
        points.append(Point(x, y, 0.0))

    if not points:
        # Avoid empty polyline; could also raise
        return Polyline(points=[Point(0, 0, 0), Point(1, 0, 0)], color="red")

    return Polyline(points=points, color="red", line_thickness=8)

def gps_checker(coord: Tuple[float, float]) -> int:
    """Classify a GPS coordinate (lat, lon) w.r.t. MAP1 / MAP2.

    Returns
    -------
    int code:
        1 -> inside MAP1
        2 -> outside MAP1 but inside MAP2   (MAP2 will be used)
        3 -> outside MAP2                   (completely outside both maps)
        4 -> (0.0, 0.0)                     (placeholder / invalid)
    """
    lat, lon = coord

    # Case 4: placeholder
    if lat == 0.0 and lon == 0.0:
        return 4

    # Unpack bounds once
    map1_bottom, map1_top, map1_left, map1_right = _normalize_bounds(
        MAP1_CORNER_1, MAP1_CORNER_2
    )
    map2_bottom, map2_top, map2_left, map2_right = _normalize_bounds(
        MAP2_CORNER_1, MAP2_CORNER_2
    )

    # Case 1: inside small MAP1
    if _point_in_bounds(lat, lon,
                        map1_bottom, map1_top,
                        map1_left, map1_right):
        return 1

    # Case 2: outside MAP1 but inside large MAP2
    if _point_in_bounds(lat, lon,
                        map2_bottom, map2_top,
                        map2_left, map2_right):
        return 2

    # Case 3: completely outside MAP2
    return 3


