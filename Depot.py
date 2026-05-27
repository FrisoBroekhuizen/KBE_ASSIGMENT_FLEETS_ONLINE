from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.geom import GeomBase, Box, Plane, translate, rotate, CommonSolid
from parapy.exchange import STEPWriter

from typing import List, Tuple, Optional

import numpy as np

from assets import *
import math

import assets

class Depot(GeomBase):
    location: Tuple[float, float] = Input((0.0, 0.0))
    rotation: float = Input(0.0)  # 0 deg is long side horizontal
    # overall_dimensions: (long side, short side, height) in meters
    overall_dimensions: Tuple[float, float, float] = Input((30, 30, 0.0))

    parking_gap = 0.6

    machines: List[Machine] = Input([Tool(vehicle_attachable=True, overall_dimensions=[1, 2, 2]),Tool(vehicle_attachable=True, overall_dimensions=[0.5, 2, 2]), Tool(vehicle_attachable=True, overall_dimensions=[2, 2, 2]), Tool(vehicle_attachable=True, overall_dimensions=[2, 2, 2]), Tool(vehicle_attachable=False, overall_dimensions=[2, 2, 2]), Truck(overall_dimensions=[4, 2, 2], contents=Trailer(overall_dimensions=[12, 2, 2])), Truck(overall_dimensions=[2, 1.5, 2]), Truck(overall_dimensions=[4, 2, 2]), Truck(overall_dimensions=[3, 2, 2]),Truck(overall_dimensions=[3, 2.5, 2.5]), Truck(overall_dimensions=[3, 2, 2]), Truck(overall_dimensions=[2, 2, 2]), Truck(overall_dimensions=[3, 1.5, 1.5]), Truck(overall_dimensions=[4, 2, 2])])
    trailers: List[Trailer] = Input([])

    non_attachable_tools: List[Machine] = Input([])
    attachable_tools: List = Input([])

    # --------------------------------
    #  FUNCTION 1: Allocating assets to specific depots
    # --------------------------------

    # -------
    # Helper: distance in meters between two GPS points
    # -------
    def HaversineDistance(
            self,
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

    # -------
    # Generic allocation helper (no generics, just duck-typing on gps_location)
    # -------
    def _allocate_assets(self, assets, range_m: float):
        """Snap nearby assets (with gps_location) to depot; return (in_depot, street)."""
        depot_lat, depot_lon = self.location
        long_side, short_side, _ = self.overall_dimensions
        depot_radius = 0.5 * math.sqrt(long_side ** 2 + short_side ** 2)
        critical_proximity = range_m + depot_radius

        in_depot = []
        street = []

        for asset in assets:
            a_lat, a_lon = asset.gps_location
            distance = self.HaversineDistance(a_lat, a_lon, depot_lat, depot_lon)

            if distance <= critical_proximity:
                asset.gps_location = (depot_lat, depot_lon)
                in_depot.append(asset)
            else:
                street.append(asset)

        return in_depot, street

    # -------
    # Public API: machines
    # -------
    def DepotMachineAllocation(
            self,
            range_m: float = 500.0
    ) -> Tuple[List["Machine"], List["Machine"]]:
        """Assign nearby machines to this depot; return (in_depot, road_parked)."""
        depot_machines, road_parked = self._allocate_assets(self.machines, range_m)
        self.machines = depot_machines
        return depot_machines, road_parked

    # ------
    # Public API: trailers
    # -------
    def DepotTrailerAllocation(
            self,
            range_m: float = 500.0
    ) -> Tuple[List["Trailer"], List["Trailer"]]:
        """Assign nearby trailers to this depot; return (in_depot, street_parked)."""
        depot_trailers, street_trailers = self._allocate_assets(self.trailers, range_m)
        self.trailers = depot_trailers
        return depot_trailers, street_trailers

    # ---------------------------------------------
    # FUNCTION 2: Depot arrangement
    # ---------------------------------------------

    # Returns the machines list sorted based on the length of the vehicles
    @Attribute
    def sorted_machines(self):
        for machine in self.machines:
            if type(machine).__bases__[0].__name__ == "Tool" or type(machine).__name__ == "Tool":
                if machine.vehicle_attachable == False:
                    self.machines.remove(machine)
                    self.non_attachable_tools.append(machine)
                else:
                    self.attachable_tools.append([machine])
        self.attachable_tools = sorted(self.attachable_tools, key=lambda m: m[0].overall_dimensions[0])
        return sorted(self.machines, key=lambda m: m.overall_dimensions[0])

    @Attribute
    def non_attachable_tools_storage(self):
        area = 0
        for tool in self.non_attachable_tools:
            area += tool.overall_dimensions[0] * tool.overall_dimensions[1]

        return area

    # Returns a list of positions of the vehicles in the depot, using the sorted machines list and a path width dependent on the turning radius of the largest vehicle in the row.
    @Attribute
    def machine_positions(self):
        row_width = 0
        positions = []
        max_vehicle_length = max(m.overall_dimensions[0] for m in self.machines)
        row_height = max_vehicle_length
        longest_vehicle = None
        attachable_tool_index = 0
        trailers = []
        longest_vehicle_length = 0
        for i, vehicle in enumerate(self.sorted_machines):
            if row_width + vehicle.overall_dimensions[1] + self.parking_gap < self.overall_dimensions[1]:
                # If the machine is a tool, it should be added to the attachable_tools list to create the ghost vehicle
                if type(vehicle).__bases__[0].__name__ == "Tool" or type(vehicle).__name__ == "Tool":
                    positions.append([row_height - max_vehicle_length, row_width])
                    self.attachable_tools[attachable_tool_index].append(row_height - (max_vehicle_length - vehicle.overall_dimensions[0]))
                    self.attachable_tools[attachable_tool_index].append(row_width)
                    attachable_tool_index += 1
                elif type(vehicle).__name__ == "Truck":
                    if vehicle.contents != None:
                        positions.append([row_height - vehicle.overall_dimensions[0] - vehicle.contents.overall_dimensions[0], row_width]) # Trailer
                        positions.append([row_height - vehicle.overall_dimensions[0], row_width])  # Truck
                        trailers.append([i, vehicle.contents])
                    else:
                        positions.append([row_height - vehicle.overall_dimensions[0], row_width])
                else:
                    positions.append([row_height - vehicle.overall_dimensions[0], row_width])
                row_width += vehicle.overall_dimensions[1] + self.parking_gap
                # The longest vehicle is kept track of which is to be used to determine the path width
                if type(vehicle).__name__ != "Trailer" and type(vehicle).__name__ != "Tool" and type(vehicle).__bases__[0].__name__ != "Tool":
                    if longest_vehicle == None:
                        longest_vehicle_length = vehicle.overall_dimensions[0]
                        if vehicle.contents != None: longest_vehicle_length += vehicle.contents.overall_dimensions[0]
                        longest_vehicle = vehicle
                    elif longest_vehicle_length < vehicle.overall_dimensions[0]:
                        longest_vehicle = vehicle
                        longest_vehicle_length = vehicle.overall_dimensions[0]
                        if vehicle.contents != None: longest_vehicle_length += vehicle.contents.overall_dimensions[0]
                    elif vehicle.contents != None:
                        if longest_vehicle_length < vehicle.overall_dimensions[0] + vehicle.contents.overall_dimensions[0]:
                            longest_vehicle_length = vehicle.overall_dimensions[0] + vehicle.contents.overall_dimensions[0]
                            longest_vehicle = vehicle
            else:
                row_width = 0
                path_width = self.DeterminePathWidth(longest_vehicle)
                row_height += path_width + max_vehicle_length
                positions.append([row_height - vehicle.overall_dimensions[0], row_width])
                row_width += vehicle.overall_dimensions[1] + self.parking_gap
        for trailer in trailers:
            self.sorted_machines.insert(trailer[0], trailer[1])
        return positions

    # Determine the width between two rows of vehicles based on collision detection of a vehicle making a turn with its corresponding turning radius
    def DeterminePathWidth(self, longest_vehicle):
        longest_vehicle.wheelbase = longest_vehicle.overall_dimensions[0] # TODO: Remove once this information is read from JSON
        longest_vehicle.dimensions = longest_vehicle.overall_dimensions # TODO: Remove once this information is read from JSON
        turn_radius = longest_vehicle.TurnRadius
        offset = [0, turn_radius, 0]
        offset_trailer = [0, 0, 0]
        has_trailer = False
        if longest_vehicle.contents != None: has_trailer = True
        if has_trailer:
            trailer = longest_vehicle.contents
            longest_vehicle.wheelbase = longest_vehicle.overall_dimensions[0] # TODO: Remove once this information is read from JSON
            longest_vehicle.wheelbase_rear = trailer.overall_dimensions[0]
            longest_vehicle.wheelbase_track = trailer.overall_dimensions[1]
            longest_vehicle.number_of_axles = 3
            longest_vehicle.dimensions = longest_vehicle.overall_dimensions # TODO: Remove once this information is read from JSON
            longest_vehicle.dimensions_rear = trailer.overall_dimensions
            turn_radius = longest_vehicle.TurnRadius
            R_tractor = np.sqrt(turn_radius ** 2 - longest_vehicle.overall_dimensions[0] ** 2)
            R_trailer = np.sqrt(turn_radius ** 2 - longest_vehicle.overall_dimensions[0] ** 2 - trailer.overall_dimensions[0] ** 2)
            offset = [0, R_tractor, R_trailer - R_tractor]
            offset_trailer = [-longest_vehicle.contents.overall_dimensions[0] / 2, np.sqrt(turn_radius ** 2 - longest_vehicle.overall_dimensions[0] ** 2), 0] # - longest_vehicle.contents.overall_dimensions[0] ** 2), 0]
        dx = 0.1 # [m]
        common_volume = 1 # Just a number

        # Start the turn slightly later until the rotating vehicle no longer collides with the parked neighbouring vehicle
        while common_volume > 0 or common_volume_trailer > 0:
            for dt in range(5):
                candidate_position = self.MakeTurningVehicle(offset, longest_vehicle, dt)
                if has_trailer:
                    candidate_position_trailer = self.MakeTurningVehicle(offset_trailer, longest_vehicle, dt)
                    obstacle = self.MakeStationaryVehicle(np.sqrt(turn_radius ** 2 - longest_vehicle.overall_dimensions[0] ** 2 - trailer.overall_dimensions[0] ** 2), longest_vehicle)
                else:
                    obstacle = self.MakeStationaryVehicle(turn_radius, longest_vehicle)
                try: common_volume = self.CommonVolume(obstacle, candidate_position)
                except: common_volume = 0
                try: common_volume_trailer = self.CommonVolume(obstacle, candidate_position_trailer)
                except: common_volume_trailer = 0
                if common_volume > 0 or common_volume_trailer > 0:
                    offset[0] += dx
                    offset_trailer[0] += dx
        return (turn_radius + offset[0] - offset_trailer[0])

    # Make the 'obstacle' box representing the vehicle parked next to the turning vehicle
    def MakeStationaryVehicle(self, turn_radius, vehicle):
        return Box(width=vehicle.overall_dimensions[0],
                   length = 2,
                   height = 2,
                   position=translate(self.position, 'x', 0, 'y', turn_radius - self.parking_gap - 2))

    # Make the 'candidate position' box representing the turning vehicle at a specific point in time dt during the turn
    def MakeTurningVehicle(self, offset, vehicle, dt):
        return Box(width = vehicle.overall_dimensions[0],
                   length = vehicle.overall_dimensions[1],
                   height = vehicle.overall_dimensions[2],
                   position=translate(rotate(translate(self.position, 'z', offset[2]), (0, 0, -1), np.pi/8*dt), 'x', offset[0], 'y', offset[1]))

    # Returns the common shape between the parked and turning vehicles, if its volume is non-zero a collision happens
    def CommonVolume(self, stationary_vehicle, turning_vehicle):
        return CommonSolid(shape_in = stationary_vehicle, tool = turning_vehicle).volume

    @Part
    def Floor(self):
        return Box(width=self.overall_dimensions[0],
                   length=self.overall_dimensions[1],
                   height=0.1,
                   position=translate(self.position, 'z', -0.1),
                   color="Black")

    @Part
    def NonAttachableToolStorage(self):
        return Box(width=np.sqrt(self.non_attachable_tools_storage),
                   length=np.sqrt(self.non_attachable_tools_storage),
                   height=0.1,
                   position=translate(self.position, 'x', self.overall_dimensions[0] - np.sqrt(self.non_attachable_tools_storage), 'y', self.overall_dimensions[1] - np.sqrt(self.non_attachable_tools_storage)),
                   color="Green")

    @Part
    def PlaceMachines(self):
        return Box(quantify=len(self.sorted_machines),
                   width=self.sorted_machines[child.index].overall_dimensions[0],
                   length=self.sorted_machines[child.index].overall_dimensions[1],
                   height=self.sorted_machines[child.index].overall_dimensions[2],
                   position=translate(self.position, 'x', self.machine_positions[child.index][0], 'y', self.machine_positions[child.index][1]),
                   color=("Blue" if type(self.sorted_machines[child.index]).__bases__[0].__name__ == "Tool" or type(self.sorted_machines[child.index]).__name__ == "Tool"
                          else "Yellow"))

    # Place ghost vehicles that indicate the vehicles that will collect the vehicle attached tools
    # Currently disabled as the exact dimensions of the collecting vehicle are not known
    # @Part
    # def PlaceGhosts(self):
    #     return Box(quantify=len(self.attachable_tools),
    #                width = max(m.overall_dimensions[0] for m in self.sorted_machines) - self.attachable_tools[child.index][0].overall_dimensions[0],
    #                length = self.attachable_tools[child.index][0].overall_dimensions[1],
    #                height = self.attachable_tools[child.index][0].overall_dimensions[2],
    #                position=translate(self.position, 'x', self.attachable_tools[child.index][1], 'y', self.attachable_tools[child.index][2]),
    #                color = "Black")


if __name__ == '__main__':
    from parapy.gui import display

    app = Depot()
    display(app)