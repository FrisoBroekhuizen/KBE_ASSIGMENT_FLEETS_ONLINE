from __future__ import annotations

import os
from typing import List, Tuple, Any

from parapy.core import Base, Input, Attribute, Part, child
from parapy.geom import Point, Position, Polyline, Box, XOY
from parapy.geom.occ.visual import Image

import Routing

maindir = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Marker objects that wrap geometry + keep a reference to real objects
# ---------------------------------------------------------------------------

class DepotMarker(Base):
    """Visual marker for a Depot on the map, keeps a reference to the Depot."""
    depot: object = Input()
    size: Tuple[float, float, float] = Input()
    x: float = Input(0.0)
    y: float = Input(0.0)
    z: float = Input(0.0)
    rotation_deg: float = Input(0.0)

    @Attribute
    def label(self) -> str:
        name = getattr(self.depot, "name", None) if self.depot is not None else None
        return f"Depot: {name}" if name not in (None, "") else "Depot"

    @Part
    def box(self):
        return Box(
            width=self.size[0],
            length=self.size[1],
            height=self.size[2],
            position=XOY.translate(
                "x", self.x,
                "y", self.y,
                "z", self.z,
            ).rotate(
                "z", self.rotation_deg, deg=True,
            ),
            color="black",
            transparency=0.2,
            label=self.label,
        )


class WorksiteMarker(Base):
    """Visual marker for a WorkJob / work site, keeps a reference to the WorkJob."""
    worksite: object = Input()
    size: Tuple[float, float, float] = Input()
    x: float = Input(0.0)
    y: float = Input(0.0)
    z: float = Input(0.0)
    rotation_deg: float = Input(0.0)

    @Attribute
    def label(self) -> str:
        name = getattr(self.worksite, "name", None) if self.worksite is not None else None
        return f"Work site: {name}" if name not in (None, "") else "Work site"

    @Part
    def box(self):
        return Box(
            width=self.size[0],
            length=self.size[1],
            height=self.size[2],
            position=XOY.translate(
                "x", self.x,
                "y", self.y,
                "z", self.z,
            ).rotate(
                "z", self.rotation_deg, deg=True,
            ),
            color="purple",
            transparency=0.3,
            label=self.label,
        )


class RouteMarker(Base):
    """Visual marker for a transport route, keeps a reference to the
    main vehicle and (indirectly) everything it is carrying.
    """

    # The main moving object: typically job.transporting_vehicle
    vehicle: object = Input(None)

    # ORS geometry in [ [lon, lat], ... ] format
    geometry_latlon: List[Tuple[float, float]] = Input([])

    # Map origin used for lat/lon -> XY
    origin_lat: float = Input()
    origin_lon: float = Input()

    color: Any = Input((255, 0, 0))
    line_thickness: float = Input(4.0)

    @Attribute
    def objects(self) -> List[object]:
        """All logical objects involved in this leg:
        [truck] or [truck, trailer] or [truck, trailer, tractor], ...
        """
        objs: List[object] = []
        v = self.vehicle
        if v is None:
            return objs

        objs.append(v)

        cont = getattr(v, "contents", None)
        if cont is not None:
            objs.append(cont)
            inner = getattr(cont, "contents", None)
            if isinstance(inner, list):
                for m in inner:
                    if m is not None:
                        objs.append(m)

        return objs

    @Attribute
    def label(self) -> str:
        """Human-readable description, shown when you click the polyline."""
        if self.vehicle is None:
            return "Route"

        names: List[str] = []

        # main vehicle
        v = self.vehicle
        v_type = getattr(v, "machine_type", None) or type(v).__name__
        v_id = getattr(v, "machine_id", None)
        names.append(f"{v_type} {v_id}" if v_id else v_type)

        # trailer (if any)
        cont = getattr(v, "contents", None)
        if cont is not None:
            c_type = type(cont).__name__
            c_id = getattr(cont, "machine_id", None)
            if hasattr(cont, "trailer_id"):
                c_id = getattr(cont, "trailer_id")
            names.append(f"{c_type} {c_id}" if c_id else c_type)

            inner = getattr(cont, "contents", None)
            if isinstance(inner, list):
                for m in inner:
                    if m is None:
                        continue
                    m_type = getattr(m, "machine_type", None) or type(m).__name__
                    m_id = getattr(m, "machine_id", None)
                    names.append(f"{m_type} {m_id}" if m_id else m_type)

        return " + ".join(names)

    @Attribute
    def _points_xy(self) -> List[Point]:
        """Convert ORS geometry [lon, lat] to local XY points."""
        pts: List[Point] = []
        for lon, lat in self.geometry_latlon:
            x, y = Routing._latlon_to_xy(
                lat, lon,
                self.origin_lat,
                self.origin_lon,
            )
            pts.append(Point(x, y, 0.0))
        return pts

    @Part
    def polyline(self):
        return Polyline(
            points=self._points_xy,
            color=self.color,
            line_thickness=self.line_thickness,
            label=self.label,
        )


# ---------------------------------------------------------------------------
# MapMaker
# ---------------------------------------------------------------------------

class MapMaker(Base):
    """
    Generic map visualization for:
    - multiple transport routes
    - depot locations
    - work site locations
    """

    # (lat, lon, owner) where owner is either a machine_type string
    # or the actual transporting_vehicle object
    routes: List[
        Tuple[Tuple[float, float], Tuple[float, float], Any]
    ] = Input([])

    # (lat, lon)
    depots: List[Tuple[float, float]] = Input([])
    work_sites: List[Tuple[float, float]] = Input([])

    # Optional per‑object sizes and rotations
    depot_sizes: List[Tuple[float, float, float]] = Input([])
    depot_rotations_deg: List[float] = Input([])

    worksite_sizes: List[Tuple[float, float, float]] = Input([])
    worksite_rotations_deg: List[float] = Input([])

    # references to actual objects
    depot_objects: List[object] = Input([])
    worksite_objects: List[object] = Input([])

    depot_cube_size: float = Input(2000.0)

    # ------------------------------------------------------------------
    # Routing computations
    # ------------------------------------------------------------------
    @Attribute
    def route_results(self):
        """
        List of per-route dicts:
        {
          'start': (lat, lon),
          'end': (lat, lon),
          'machine_type': str,
          'vehicle': object | None,
          'duration': float,   # seconds
          'distance': float,   # meters
          'geometry': [[lon, lat], ...],
        }
        """
        results = []
        for start, end, owner in self.routes:
            vehicle = None
            if isinstance(owner, str):
                machine_type = owner
            else:
                vehicle = owner
                machine_type = type(owner).__name__

            duration, distance, geometry = Routing.ComputeRoute(
                start, end, machine_type
            )
            print(
                f"Route {start} -> {end} ({machine_type}): "
                f"duration [s]: {duration}, distance [m]: {distance}"
            )
            results.append({
                "start": start,
                "end": end,
                "machine_type": machine_type,
                "vehicle": vehicle,
                "duration": duration,
                "distance": distance,
                "geometry": geometry,
            })
        return results

    @Attribute
    def route_results_filtered(self):
        """Filter out degenerate / zero-length routes."""
        return [
            r for r in self.route_results
            if r["geometry"] and (r["distance"] is None or r["distance"] >= 1.0)
        ]

    # ------------------------------------------------------------------
    # Map selection + image parameters
    # ------------------------------------------------------------------
    @Attribute
    def all_points(self):
        """All relevant GPS points: route endpoints + depots + work sites."""
        pts: List[Tuple[float, float]] = []
        for r in self.route_results:
            pts.append(r["start"])
            pts.append(r["end"])
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

    @Part
    def route_markers(self):
        """One RouteMarker per (non-degenerate) route, clickable in the GUI."""
        return RouteMarker(
            quantify=len(self.route_results_filtered),
            vehicle=self.route_results_filtered[child.index]["vehicle"],
            geometry_latlon=self.route_results_filtered[child.index]["geometry"],
            origin_lat=self.map_origin_lat_lon[0],
            origin_lon=self.map_origin_lat_lon[1],
        )

    @Part
    def depot_markers(self):
        """Depot markers that keep a reference to the actual Depot object."""
        return DepotMarker(
            quantify=len(self.depots),
            depot=(
                self.depot_objects[child.index]
                if len(self.depot_objects) > child.index
                else None
            ),
            size=self._depot_sizes_effective[child.index],
            x=Routing._latlon_to_xy(
                self.depots[child.index][0],
                self.depots[child.index][1],
                self.map_origin_lat_lon[0],
                self.map_origin_lat_lon[1],
            )[0],
            y=Routing._latlon_to_xy(
                self.depots[child.index][0],
                self.depots[child.index][1],
                self.map_origin_lat_lon[0],
                self.map_origin_lat_lon[1],
            )[1],
            z=self._depot_sizes_effective[child.index][2] / 2.0,
            rotation_deg=self._depot_rot_effective[child.index],
        )

    @Part
    def worksite_markers(self):
        """Work site markers that keep a reference to the actual WorkJob."""
        return WorksiteMarker(
            quantify=len(self.work_sites),
            worksite=(
                self.worksite_objects[child.index]
                if len(self.worksite_objects) > child.index
                else None
            ),
            size=self._worksite_sizes_effective[child.index],
            x=Routing._latlon_to_xy(
                self.work_sites[child.index][0],
                self.work_sites[child.index][1],
                self.map_origin_lat_lon[0],
                self.map_origin_lat_lon[1],
            )[0],
            y=Routing._latlon_to_xy(
                self.work_sites[child.index][0],
                self.work_sites[child.index][1],
                self.map_origin_lat_lon[0],
                self.map_origin_lat_lon[1],
            )[1],
            z=self._worksite_sizes_effective[child.index][2] / 2.0,
            rotation_deg=self._worksite_rot_effective[child.index],
        )


# ---------------------------------------------------------------------------
# FleetMapMaker
# ---------------------------------------------------------------------------

class AssetMarker(Base):
    """Visual marker for a fleet asset, keeps a reference to the Machine/Trailer."""
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
        mtype = getattr(self.asset, "machine_type", None) or type(self.asset).__name__
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
                "x", self.x,
                "y", self.y,
                "z", self.z,
            ),
            color=self.color,
            label=self.label,
        )


class FleetMapMaker(MapMaker):
    """
    Fleet overview map:
    - background map (same as MapMaker),
    - depots and worksites (same as MapMaker),
    - no route polylines,
    - plus all assets as stacked boxes.
    """

    assets: List[object] = Input([])

    @Attribute
    def all_points(self):
        """All relevant GPS points: routes, depots, work sites AND assets."""
        pts: List[Tuple[float, float]] = []
        for r in self.route_results:
            pts.append(r["start"])
            pts.append(r["end"])
        pts.extend(self.depots)
        pts.extend(self.work_sites)
        for obj in self.assets:
            latlon = getattr(obj, "gps_location", None)
            if latlon is not None:
                pts.append(tuple(latlon))
        return pts

    @Part(parse=False)
    def route_markers(self):
        """No route markers for the fleet overview."""
        return []

    @Attribute
    def _asset_infos(self):
        """Stacking info for all assets."""
        def overlap_1d(c1, size1, c2, size2):
            return abs(c1 - c2) < 0.5 * (size1 + size2)

        origin_lat, origin_lon = self.map_origin_lat_lon

        raw = []
        for obj in self.assets:
            latlon = getattr(obj, "gps_location", None)
            if latlon is None:
                continue

            lat, lon = latlon
            x, y = Routing._latlon_to_xy(lat, lon, origin_lat, origin_lon)

            dims = getattr(obj, "overall_dimensions", None)
            if not dims or len(dims) != 3:
                dims = (2.0, 2.0, 2.0)

            scale = 500.0
            L = float(dims[0]) * scale
            W = float(dims[1]) * scale
            H = float(dims[2]) * scale

            color = getattr(obj, "color", "gray")
            mid = getattr(obj, "machine_id", "Unlabeled")

            raw.append({
                "lat": float(lat),
                "lon": float(lon),
                "x": x,
                "y": y,
                "L": L,
                "W": W,
                "H": H,
                "color": color,
                "id": mid,
                "obj": obj,
            })

        raw.sort(key=lambda d: (d["y"], d["x"]))
        placed = []

        for info in raw:
            base_z = 0.0
            for other in placed:
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
        """Stacked boxes for all machines / tools / trailers, with back‑reference."""
        return AssetMarker(
            quantify=len(self._asset_infos),
            asset=self._asset_infos[child.index]["obj"],
            L=self._asset_infos[child.index]["L"],
            W=self._asset_infos[child.index]["W"],
            H=self._asset_infos[child.index]["H"],
            x=self._asset_infos[child.index]["x"],
            y=self._asset_infos[child.index]["y"],
            z=self._asset_infos[child.index]["z_center"],
            color=self._asset_infos[child.index]["color"],
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




