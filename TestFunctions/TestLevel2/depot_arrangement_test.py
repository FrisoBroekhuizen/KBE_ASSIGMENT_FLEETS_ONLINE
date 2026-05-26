from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.geom import GeomBase, Box, Plane, translate, rotate, CommonSolid
from parapy.exchange import STEPWriter

from typing import List, Tuple, Optional

import numpy as np

import machine

class Depot(GeomBase):
    location: Tuple[float, float] = Input((0.0, 0.0))
    rotation: float = Input(0.0)  # 0 deg is long side horizontal
    # overall_dimensions: (long side, short side, height) in meters
    overall_dimensions: Tuple[float, float, float] = Input((30, 30, 0.0))

    parking_gap = 0.6

    machines: List[machine.Machine] = Input([machine.Tool(vehicle_attachable=True, overall_dimensions=[1, 2, 2]),machine.Tool(vehicle_attachable=True, overall_dimensions=[0.5, 2, 2]), machine.Tool(vehicle_attachable=True, overall_dimensions=[2, 2, 2]), machine.Tool(vehicle_attachable=True, overall_dimensions=[2, 2, 2]), machine.Tool(vehicle_attachable=False, overall_dimensions=[2, 2, 2]), machine.Truck(overall_dimensions=[3, 2.5, 2]), machine.Truck(overall_dimensions=[2, 1.5, 2]), machine.Truck(overall_dimensions=[4, 2, 2]), machine.Truck(overall_dimensions=[5, 2, 2]), machine.Truck(overall_dimensions=[6, 2.5, 2.5]), machine.Truck(overall_dimensions=[3, 2, 2]), machine.Truck(overall_dimensions=[4, 2, 2]), machine.Truck(overall_dimensions=[7, 1.5, 1.5]), machine.Truck(overall_dimensions=[7, 2, 2])])

    non_attachable_tools: List[machine.Machine] = Input([])
    attachable_tools: List = Input([])

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
        for i, vehicle in enumerate(self.sorted_machines):
            if row_width + vehicle.overall_dimensions[1] + self.parking_gap < self.overall_dimensions[1]:
                # If the machine is a tool, it should be added to the attachable_tools list to create the ghost vehicle
                if type(vehicle).__bases__[0].__name__ == "Tool" or type(vehicle).__name__ == "Tool":
                    positions.append([row_height - max_vehicle_length, row_width])
                    self.attachable_tools[attachable_tool_index].append(row_height - (max_vehicle_length - vehicle.overall_dimensions[0]))
                    self.attachable_tools[attachable_tool_index].append(row_width)
                    attachable_tool_index += 1
                    row_width += vehicle.overall_dimensions[1] + self.parking_gap
                    continue
                else:
                    positions.append([row_height - vehicle.overall_dimensions[0], row_width])
                row_width += vehicle.overall_dimensions[1] + self.parking_gap
                # The longest vehicle is kept track of which is to be used to determine the path width
                if longest_vehicle == None:
                    longest_vehicle = vehicle
                elif longest_vehicle.overall_dimensions[0] < vehicle.overall_dimensions[0]:
                    longest_vehicle = vehicle
            else:
                row_width = 0
                path_width = self.DeterminePathWidth(longest_vehicle)
                row_height += path_width + max_vehicle_length
                positions.append([row_height - vehicle.overall_dimensions[0], row_width])
                row_width += vehicle.overall_dimensions[1] + self.parking_gap
        return positions

    # Determine the width between two rows of vehicles based on collision detection of a vehicle making a turn with its corresponding turning radius
    def DeterminePathWidth(self, longest_vehicle):
        turn_radius = longest_vehicle.TurnRadius
        offset = [0, turn_radius, 0]
        dx = 0.1 # [m]
        common_volume = 1 # Just a number

        # Start the turn slightly later until the rotating vehicle no longer collides with the parked neighbouring vehicle
        while common_volume > 0:
            obstacle = self.MakeStationaryVehicle(turn_radius, longest_vehicle)
            for dt in range(5):
                candidate_position = self.MakeTurningVehicle(offset, longest_vehicle, dt)
                try: common_volume = self.CommonVolume(obstacle, candidate_position)
                except: common_volume = 0
                if common_volume > 0:
                    offset[0] += dx
                    break

        return (turn_radius + offset[0])

    # Make the 'obstacle' box representing the vehicle parked next to the turning vehicle
    def MakeStationaryVehicle(self, turn_radius, vehicle):
        return Box(width=vehicle.overall_dimensions[0],
                   length = 2,
                   height = 2,
                   position=translate(self.position, 'x', 0, 'y', turn_radius - self.parking_gap - 2))

    # -- Debugging Part --
    # @Part
    # def MakeObstacle(self):
    #     return Box(width=5,
    #                length = 2,
    #                height = 2,
    #                position=translate(self.position, 'x', 0, 'y', 7 - self.parking_gap - 2))

    # Make the 'candidate position' box representing the turning vehicle at a specific point in time dt during the turn
    def MakeTurningVehicle(self, offset, vehicle, dt):
        return Box(width = vehicle.overall_dimensions[0],
                   length = vehicle.overall_dimensions[1],
                   height = vehicle.overall_dimensions[2],
                   position=translate(rotate(self.position, (0, 0, -1), np.pi/8*dt), 'x', offset[0], 'y', offset[1]))

    # -- Debugging Part --
    # @Part
    # def MakeCandidatePosition(self):
    #     return Box(quantify=5, width=5,
    #                length=2,
    #                height=2,
    #                position=translate(rotate(self.position, (0, 0, -1), np.pi / 8 * child.index), 'x', 0, 'y',
    #                                   7))

    # Returns the common shape between the parked and turning vehicles, if its volume is non-zero a collision happens
    def CommonVolume(self, stationary_vehicle, turning_vehicle):
        return CommonSolid(shape_in = stationary_vehicle, tool = turning_vehicle).volume

    # @Part
    # def Common(self):
    #     return CommonSolid(shape_in = self.MakeObstacle, tool = self.MakeCandidatePosition)

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

    @Part
    def PlaceGhosts(self):
        return Box(quantify=len(self.attachable_tools),
                   width = max(m.overall_dimensions[0] for m in self.sorted_machines) - self.attachable_tools[child.index][0].overall_dimensions[0],
                   length = self.attachable_tools[child.index][0].overall_dimensions[1],
                   height = self.attachable_tools[child.index][0].overall_dimensions[2],
                   position=translate(self.position, 'x', self.attachable_tools[child.index][1], 'y', self.attachable_tools[child.index][2]),
                   color = "Black")


if __name__ == '__main__':
    from parapy.gui import display

    app = Depot()
    display(app)