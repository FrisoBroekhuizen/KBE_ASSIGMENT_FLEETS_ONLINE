from __future__ import annotations

import math
import time
from typing import List, Tuple, Optional, Any

import numpy as np

from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter
from parapy.geom import GeomBase, Box, Plane, translate, rotate, CommonSolid

from assets import Machine, Trailer, Tool, Truck
from Routing import HaversineDistance
import assets

class DepotAssetMarker(GeomBase):
    """Clickable marker for a machine / trailer in a depot.

    - asset: underlying Machine or Trailer object.
    - position: inherited from Depot; we place this marker at the parked location.
    """

    asset: object = Input()
    color: Any = Input("yellow")

    @Attribute
    def label(self) -> str:
        mid = getattr(self.asset, "machine_id", None)
        # trailers have trailer_id instead
        if mid in (None, "") or mid is None:
            mid = getattr(self.asset, "trailer_id", None)

        mtype = getattr(self.asset, "machine_type", None) or type(
            self.asset
        ).__name__

        if mid not in (None, "") and mid is not None:
            return f"{mtype} {mid}"
        return mtype

    @Part
    def box(self):
        """Actual visible geometry for this parked asset."""
        return Box(
            width=self.asset.overall_dimensions[0],
            length=self.asset.overall_dimensions[1],
            height=self.asset.overall_dimensions[2],
            position=self.position,  # already positioned by Depot
            color=self.color,
            label=self.label,
        )

class Depot(GeomBase):
    gps_location: Tuple[float, float] = Input((0.0, 0.0))
    rotation: float = Input(0.0)  # 0 deg is long side horizontal
    # overall_dimensions: (long side, short side, height) in meters
    overall_dimensions: Tuple[float, float, float] = Input((60, 30, 15))

    name = Input("depot_name")

    parking_gap = 0.6

    machines: List[Machine] = Input([])
    trailers: List[Trailer] = Input([])

    non_attachable_tools: List[Machine] = Input([])
    attachable_tools: List = Input([])

    available_machine_types = Input([])

    # --------------------------------
    #  FUNCTION 1: Allocating assets to specific depots
    # --------------------------------
    # -------
    # Generic allocation helper (no generics, just duck-typing on gps_location)
    # -------
    def _allocate_assets(
        self,
        assets_list,
        trailers: List[Trailer],
        range_m: float,
    ):
        """Snap nearby assets (with gps_location) to depot;
        return (in_depot, street, trailers_in_depot)."""
        self.available_machine_types = []
        depot_lat, depot_lon = self.gps_location
        long_side, short_side, _ = self.overall_dimensions
        depot_radius = 0.5 * math.sqrt(long_side**2 + short_side**2)
        critical_proximity = range_m + depot_radius

        in_depot = []
        trailers_in_depot: List[Trailer] = []
        street = []

        for asset in assets_list:
            a_lat, a_lon = asset.gps_location
            distance = HaversineDistance(a_lat, a_lon, depot_lat, depot_lon)

            if distance <= critical_proximity:
                asset.gps_location = (depot_lat, depot_lon)
                if type(asset).__name__ == "Trailer":
                    trailers_in_depot.append(asset)
                else:
                    in_depot.append(asset)
                    if (
                        type(asset).__name__
                        not in self.available_machine_types
                    ):
                        self.available_machine_types.append(
                            type(asset).__name__
                        )
                        if type(asset).__name__ == "Truck":
                            if asset.contents is not None:
                                for c in asset.contents.contents:
                                    self.available_machine_types.append(
                                        c.machine_type
                                    )
            else:
                street.append(asset)

        for trailer in trailers:
            a_lat, a_lon = trailer.gps_location
            distance = HaversineDistance(a_lat, a_lon, depot_lat, depot_lon)
            if distance <= critical_proximity:
                trailer.gps_location = (depot_lat, depot_lon)
                trailers_in_depot.append(trailer)

        return in_depot, street, trailers_in_depot

    # -------
    # Public API: machines
    # -------
    def DepotMachineAllocation(
        self,
        range_m: float = 500.0,
    ) -> Tuple[List["Machine"], List["Machine"]]:
        """Assign nearby machines to this depot; return (in_depot, road_parked)."""
        depot_machines, road_parked, depot_trailers = self._allocate_assets(
            self.machines,
            self.trailers,
            range_m,
        )
        self.machines = depot_machines
        self.trailers = depot_trailers
        return depot_machines, road_parked

    # ------
    # Public API: trailers
    # -------
    def DepotTrailerAllocation(
        self,
        range_m: float = 500.0,
    ) -> Tuple[List["Trailer"], List["Trailer"]]:
        """Assign nearby trailers to this depot; return (in_depot, street_parked)."""
        depot_trailers, street_trailers = self._allocate_assets(
            self.trailers,
            [],
            range_m,
        )
        self.trailers = depot_trailers
        return depot_trailers, street_trailers

    # ---------------------------------------------
    # FUNCTION 2: Depot arrangement
    # ---------------------------------------------
    @Attribute
    def machine_colors(self):
        """Color per sorted machine, using machine.color if set,
        otherwise yellow for vehicles, blue for tools."""
        colors = []

        for m in self.sorted_machines:
            # 1) explicit color on machine → use it
            c = getattr(m, "color", None)
            if c not in (None, ""):
                colors.append(c)
                continue

            # 2) fallback based on type
            is_tool = (
                isinstance(m, Tool)
                or m.__class__.__name__ == "Tool"
                or (
                    m.__class__.__bases__
                    and m.__class__.__bases__[0].__name__ == "Tool"
                )
            )
            if is_tool:
                colors.append("blue")
            else:
                colors.append("yellow")

        return colors

    # Returns the machines list sorted based on the length of the vehicles
    @Attribute
    def sorted_machines(self):
        trailer_vehicles = []
        trailer_attachable_tools = []
        trailer_nonattachable_tools = []

        self.non_attachable_tools = []

        for machine in list(self.machines):
            if (
                type(machine).__bases__[0].__name__ == "Tool"
                or type(machine).__name__ == "Tool"
            ):
                if machine.vehicle_attachable is False:
                    self.machines.remove(machine)
                    self.non_attachable_tools.append(machine)
                else:
                    self.attachable_tools.append([machine])
            else:
                try:
                    machine.total_length = (
                        machine.overall_dimensions[0]
                        + machine.contents.overall_dimensions[0]
                    )
                    for v in machine.contents.contents:
                        if (
                            type(v).__bases__[0].__name__ == "Tool"
                            or type(v).__name__ == "Tool"
                        ):
                            if v.vehicle_attachable is False:
                                trailer_nonattachable_tools.append(v)
                            else:
                                trailer_attachable_tools.append(v)
                        else:
                            v.total_length = v.overall_dimensions[0]
                            trailer_vehicles.append(v)
                except Exception:
                    machine.total_length = machine.overall_dimensions[0]

        self.machines.extend(trailer_vehicles)
        self.attachable_tools.extend(trailer_attachable_tools)
        self.non_attachable_tools.extend(trailer_nonattachable_tools)

        self.attachable_tools = sorted(
            self.attachable_tools,
            key=lambda m: m[0].overall_dimensions[0],
        )
        return sorted(self.machines, key=lambda m: -m.total_length)

    @Attribute
    def non_attachable_tools_storage(self):
        area = 0.001  # Arbitrary small value
        for tool in self.non_attachable_tools:
            area += (
                tool.overall_dimensions[0] * tool.overall_dimensions[1]
            )

        return area

    # Returns a list of positions of the vehicles in the depot, using
    # the sorted machines list and a path width dependent on the
    # turning radius of the largest vehicle in the row.
    @Attribute
    def machine_positions(self):
        row_width = 0
        positions = []

        if len(self.sorted_machines) == 0:
            print(
                f"Warning: Depot {self.name} does not have any machines "
                f"assigned to it."
            )
            return []

        max_width = (
            max(
                [
                    m.overall_dimensions[1]
                    for m in self.sorted_machines
                ]
            )
            + 2 * self.parking_gap
        )

        row_height = 0
        longest_vehicle = None
        attachable_tool_index = 0
        trailers_local = []
        longest_vehicle_length = 0

        for i, vehicle in enumerate(self.sorted_machines):
            if (
                row_width
                + vehicle.overall_dimensions[1]
                + self.parking_gap
                + max_width
                < self.overall_dimensions[1]
            ):
                # If the machine is a tool, it should be added to the
                # attachable_tools list to create the ghost vehicle
                if (
                    type(vehicle).__bases__[0].__name__ == "Tool"
                    or type(vehicle).__name__ == "Tool"
                ):
                    positions.append(
                        [
                            row_height,
                            row_width + self.gps_location[1],
                        ]
                    )
                    self.attachable_tools[attachable_tool_index].append(
                        row_height + vehicle.overall_dimensions[0]
                    )
                    self.attachable_tools[attachable_tool_index].append(
                        row_width
                    )
                    attachable_tool_index += 1
                elif type(vehicle).__name__ == "Truck":
                    if vehicle.contents is not None:
                        # Trailer
                        positions.append(
                            [
                                row_height
                                - vehicle.contents.overall_dimensions[0],
                                row_width + self.gps_location[1],
                            ]
                        )
                        # Truck
                        positions.append(
                            [
                                row_height,
                                row_width + self.gps_location[1],
                            ]
                        )
                        trailers_local.append(
                            [i + len(trailers_local), vehicle.contents]
                        )
                    else:
                        positions.append(
                            [
                                row_height,
                                row_width + self.gps_location[1],
                            ]
                        )
                else:
                    positions.append(
                        [row_height, row_width + self.gps_location[1]]
                    )

                row_width += (
                    vehicle.overall_dimensions[1] + self.parking_gap
                )

                # Track the longest vehicle for path width
                if (
                    type(vehicle).__name__ != "Trailer"
                    and type(vehicle).__name__ != "Tool"
                    and type(vehicle).__bases__[0].__name__ != "Tool"
                ):
                    if longest_vehicle is None:
                        longest_vehicle_length = (
                            vehicle.overall_dimensions[0]
                        )
                        try:
                            if vehicle.contents is not None:
                                longest_vehicle_length += (
                                    vehicle.contents.overall_dimensions[
                                        0
                                    ]
                                )
                        except Exception:
                            longest_vehicle = vehicle
                        longest_vehicle = vehicle
                    elif (
                        longest_vehicle_length
                        < vehicle.overall_dimensions[0]
                    ):
                        longest_vehicle = vehicle
                        longest_vehicle_length = (
                            vehicle.overall_dimensions[0]
                        )
                        try:
                            if vehicle.contents is not None:
                                longest_vehicle_length += (
                                    vehicle.contents.overall_dimensions[
                                        0
                                    ]
                                )
                        except Exception:
                            pass
                    else:
                        try:
                            if (
                                longest_vehicle_length
                                < vehicle.overall_dimensions[0]
                                + vehicle.contents.overall_dimensions[0]
                            ):
                                longest_vehicle_length = (
                                    vehicle.overall_dimensions[0]
                                    + vehicle.contents.overall_dimensions[
                                        0
                                    ]
                                )
                                longest_vehicle = vehicle
                        except Exception:
                            continue
            else:
                row_width = 0
                path_width = self.DeterminePathWidth(longest_vehicle)
                print(row_height, path_width, longest_vehicle_length)
                row_height += path_width + longest_vehicle_length
                positions.append(
                    [row_height, row_width + self.gps_location[1]]
                )
                row_width += (
                    vehicle.overall_dimensions[1] + self.parking_gap
                )
                longest_vehicle = None
                longest_vehicle_length = 0

        for i, trailer in enumerate(self.trailers):
            self.sorted_machines.append(trailer)
            if (
                row_width
                + trailer.overall_dimensions[1]
                + self.parking_gap
                + max_width
                < self.overall_dimensions[1]
            ):
                positions.append(
                    [row_height, row_width + self.gps_location[1]]
                )
                row_width += (
                    trailer.overall_dimensions[1] + self.parking_gap
                )
                if longest_vehicle is None:
                    longest_vehicle = trailer
                    longest_vehicle_length = (
                        trailer.overall_dimensions[0]
                    )
                elif (
                    longest_vehicle_length
                    < trailer.overall_dimensions[0]
                ):
                    longest_vehicle = trailer
                    longest_vehicle_length = (
                        trailer.overall_dimensions[0]
                    )
            else:
                row_width = 0
                path_width = self.DeterminePathWidth(longest_vehicle)
                print(row_height, path_width, longest_vehicle_length)
                row_height += path_width + longest_vehicle_length
                positions.append(
                    [row_height, row_width + self.gps_location[1]]
                )
                row_width += (
                    trailer.overall_dimensions[1] + self.parking_gap
                )
                longest_vehicle = None
                longest_vehicle_length = 0

        for trailer in trailers_local:
            self.sorted_machines.insert(trailer[0], trailer[1])

        return positions

    # Determine the width between two rows of vehicles based on
    # collision detection of a vehicle making a turn with its
    # corresponding turning radius
    def DeterminePathWidth(self, longest_vehicle):
        # TODO: Remove once this information is read from JSON
        longest_vehicle.wheelbase = longest_vehicle.overall_dimensions[0]
        # TODO: Remove once this information is read from JSON
        longest_vehicle.dimensions = longest_vehicle.overall_dimensions

        if type(longest_vehicle).__name__ == "Trailer":
            m = Truck(
                overall_dimensions=[4, 2, 2],
                contents=longest_vehicle,
            )
            longest_vehicle = m
            has_trailer = True

        turn_radius = longest_vehicle.turn_radius
        offset = [0, turn_radius, 0]
        offset_trailer = [0, 0, 0]

        try:
            if (
                type(longest_vehicle).__name__ != "Trailer"
                and longest_vehicle.contents is not None
            ):
                has_trailer = True
            else:
                has_trailer = False
        except Exception:
            has_trailer = False

        if has_trailer:
            trailer = longest_vehicle.contents
            # TODO: Remove once this information is read from JSON
            longest_vehicle.wheelbase = (
                longest_vehicle.overall_dimensions[0]
            )
            longest_vehicle.wheelbase_rear = (
                trailer.overall_dimensions[0]
            )
            longest_vehicle.wheelbase_track = (
                trailer.overall_dimensions[1]
            )
            longest_vehicle.number_of_axles = 3
            # TODO: Remove once this information is read from JSON
            longest_vehicle.dimensions = (
                longest_vehicle.overall_dimensions
            )
            longest_vehicle.dimensions_rear = (
                trailer.overall_dimensions
            )
            turn_radius = longest_vehicle.turn_radius
            R_tractor = np.sqrt(
                turn_radius**2
                - longest_vehicle.overall_dimensions[0] ** 2
            )
            R_trailer = np.sqrt(
                turn_radius**2
                - longest_vehicle.overall_dimensions[0] ** 2
            )
            offset = [0, R_tractor, R_trailer - R_tractor]
            offset_trailer = [
                -longest_vehicle.contents.overall_dimensions[0] / 2,
                np.sqrt(
                    turn_radius**2
                    - longest_vehicle.overall_dimensions[0] ** 2
                ),
                0,
            ]

        dx = 0.1  # [m]
        common_volume = 1  # Just a number

        # Note: common_volume_trailer is intentionally left uninitialized
        # here to preserve original logic exactly.

        # Start the turn slightly later until the rotating vehicle no
        # longer collides with the parked neighbouring vehicle
        while common_volume > 0 or common_volume_trailer > 0:
            for dt in range(5):
                candidate_position = self.MakeTurningVehicle(
                    offset,
                    longest_vehicle,
                    dt,
                )
                if has_trailer:
                    candidate_position_trailer = self.MakeTurningVehicle(
                        offset_trailer,
                        longest_vehicle,
                        dt,
                    )
                    obstacle = self.MakeStationaryVehicle(
                        np.sqrt(
                            turn_radius**2
                            - longest_vehicle.overall_dimensions[0] ** 2
                        ),
                        longest_vehicle,
                    )
                else:
                    obstacle = self.MakeStationaryVehicle(
                        turn_radius,
                        longest_vehicle,
                    )

                try:
                    common_volume = self.CommonVolume(
                        obstacle,
                        candidate_position,
                    )
                except Exception:
                    common_volume = 0

                try:
                    common_volume_trailer = self.CommonVolume(
                        obstacle,
                        candidate_position_trailer,
                    )
                except Exception:
                    common_volume_trailer = 0

                if common_volume > 0 or common_volume_trailer > 0:
                    offset[0] += dx
                    offset_trailer[0] += dx

        return turn_radius + offset[0] - offset_trailer[0]

    # Make the 'obstacle' box representing the vehicle parked next to
    # the turning vehicle
    def MakeStationaryVehicle(self, turn_radius, vehicle):
        return Box(
            width=vehicle.overall_dimensions[0],
            length=2,
            height=2,
            position=translate(
                self.position,
                "x",
                0,
                "y",
                turn_radius - self.parking_gap - 2,
            ),
        )

    # Make the 'candidate position' box representing the turning
    # vehicle at a specific point in time dt during the turn
    def MakeTurningVehicle(self, offset, vehicle, dt):
        return Box(
            width=vehicle.overall_dimensions[0],
            length=vehicle.overall_dimensions[1],
            height=vehicle.overall_dimensions[2],
            position=translate(
                rotate(
                    translate(self.position, "z", offset[2]),
                    (0, 0, -1),
                    np.pi / 8 * dt,
                ),
                "x",
                offset[0],
                "y",
                offset[1],
            ),
        )

    # Returns the common shape between the parked and turning vehicles,
    # if its volume is non-zero a collision happens
    def CommonVolume(self, stationary_vehicle, turning_vehicle):
        return CommonSolid(
            shape_in=stationary_vehicle,
            tool=turning_vehicle,
        ).volume

    @Part
    def Floor(self):
        return Box(
            width=self.overall_dimensions[0],
            length=self.overall_dimensions[1],
            height=0.1,
            position=translate(
                self.position,
                "z",
                -0.1,
                "y",
                self.gps_location[1],
            ),
            color=(143, 144, 150),
        )

    @Part
    def Roof(self):
        return Box(
            width=self.overall_dimensions[0],
            length=self.overall_dimensions[1],
            height=self.overall_dimensions[2],
            position=translate(
                self.position,
                "y",
                self.gps_location[1],
            ),
            color=(247, 247, 250),
            transparency=0.95,
        )

    @Part
    def NonAttachableToolStorage(self):
        return Box(
            width=np.sqrt(self.non_attachable_tools_storage),
            length=np.sqrt(self.non_attachable_tools_storage),
            height=0.1,
            position=translate(
                self.position,
                "x",
                self.overall_dimensions[0]
                - np.sqrt(self.non_attachable_tools_storage),
                "y",
                self.overall_dimensions[1]
                - np.sqrt(self.non_attachable_tools_storage)
                + self.gps_location[1],
            ),
            color="Green",
        )

    @Part
    def PlaceMachines(self):
        """Markers for all parked machines / trailers in this depot.

        Each marker:
        - is a separate object in the tree,
        - keeps a reference to the real Machine/Trailer via .asset,
        - has a Box child for the visible geometry.
        """
        return DepotAssetMarker(
            quantify=len(self.machine_positions),
            asset=self.sorted_machines[child.index],
            # Place marker at same XY position as old Box logic:
            position=translate(
                self.position,
                "x",
                self.machine_positions[child.index][0],
                "y",
                self.machine_positions[child.index][1],
            ),
            color=self.machine_colors[child.index],
        )

    @action(label="Export", button_label="Export depot to STEP file")
    def Export(self):
        writer = STEPWriter(trees=[self], filename="depots.stp")
        writer.write()

def AllocateMachines(app):
    machines = app.machines
    for machine in machines:
        machine.number_of_this_type = (
            app.number_of_machines_per_type[machine.machine_type]
        )
    trailers = app.trailers
    road_parked: List[Machine] = []

    for depot in app.depots:
        depot.machines = machines
        depot.trailers = trailers
        _, road_parked = depot.DepotMachineAllocation()
        machines = road_parked

    return road_parked

if __name__ == "__main__":
    from parapy.gui import display

    app = Depot()
    display(app)
