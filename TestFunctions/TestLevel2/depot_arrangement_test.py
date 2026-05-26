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
    overall_dimensions: Tuple[float, float, float] = Input((40, 10, 0.0))

    parking_gap = 0.6

    machines: List[machine.Machine] = Input([machine.Truck(overall_dimensions=[3, 2, 2]), machine.Truck(overall_dimensions=[2, 2, 2]), machine.Truck(overall_dimensions=[4, 2, 2]), machine.Truck(overall_dimensions=[5, 2, 2]), machine.Truck(overall_dimensions=[6, 2, 2]), machine.Truck(overall_dimensions=[3, 2, 2]), machine.Truck(overall_dimensions=[4, 2, 2]), machine.Truck(overall_dimensions=[7, 2, 2]), machine.Truck(overall_dimensions=[7, 2, 2])])
    # machines: List[machine.Machine] = Input(
    #     [machine.Truck(overall_dimensions=[5, 2, 2]), machine.Truck(overall_dimensions=[5, 2, 2]),
    #      machine.Truck(overall_dimensions=[4, 2, 2])])

    @Attribute
    def sorted_machines(self):
        return sorted(self.machines, key=lambda m: m.overall_dimensions[0])

    @Attribute
    def machine_positions(self):
        row_width = 0
        positions = []
        max_vehicle_length = max(m.overall_dimensions[0] for m in self.machines)
        row_height = max_vehicle_length
        longest_vehicle = None
        for vehicle in self.sorted_machines:
            if row_width + vehicle.overall_dimensions[1] + self.parking_gap < self.overall_dimensions[1]:
                # if max_vehicle_length < vehicle.overall_dimensions[0]:
                #     max_vehicle_length = vehicle.overall_dimensions[0]
                positions.append([row_height - vehicle.overall_dimensions[0], row_width])
                row_width += vehicle.overall_dimensions[1] + self.parking_gap

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

    def DeterminePathWidth(self, longest_vehicle):
        turn_radius = longest_vehicle.TurnRadius
        offset = [0, turn_radius, 0]
        dx = 0.1

        common_volume = 1

        while common_volume > 0:
            obstacle = self.MakeObstacle(turn_radius, longest_vehicle)
            for dt in range(5):
                candidate_position = self.MakeCandidatePosition(offset, longest_vehicle, dt)
                try: common_volume = self.Common(obstacle, candidate_position)
                except: common_volume = 0
                if common_volume > 0:
                    offset[0] += dx
                    break

        return (turn_radius + offset[0])

    def MakeObstacle(self, turn_radius, vehicle):
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

    def MakeCandidatePosition(self, offset, vehicle, dt):
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

    def Common(self, obstacle, candidate_position):
        return CommonSolid(shape_in = obstacle, tool = candidate_position).volume

    # @Part
    # def Common(self):
    #     return CommonSolid(shape_in = self.MakeObstacle, tool = self.MakeCandidatePosition)

    @Part
    def Floor(self):
        return Box(width=self.overall_dimensions[0],
                   length=self.overall_dimensions[1],
                   height=0.1,
                   position=translate(self.position, 'z', -0.1))

    @Part
    def PlaceMachines(self):
        return Box(quantify=len(self.machines),
                   width=self.sorted_machines[child.index].overall_dimensions[0],
                   length=self.sorted_machines[child.index].overall_dimensions[1],
                   height=self.sorted_machines[child.index].overall_dimensions[2],
                   position=translate(self.position, 'x', self.machine_positions[child.index][0], 'y', self.machine_positions[child.index][1]))
                   # position=(self.position if child.index == 0
                   #           else child.previous.position.translate('y', self.machines[child.index].overall_dimensions[1] + 0.9)))

    # return Box(quantify=self.n_step,
    #            centered=True,
    #            width=self.w_step,
    #            length=self.l_step,
    #            height=self.h_step * 20 if child.index == 19 else self.t_step,
    #            color=self.colors[child.index % len(self.colors)],
    #            position=(
    #                self.position if child.index == 0
    #                else child.previous.position.translate('y', self.l_step, 'z',
    #                                                       self.h_step * -9.5) if child.index == 19
    #                else child.previous.position.translate('y', self.l_step, 'z', self.h_step)
    #            ))

if __name__ == '__main__':
    from parapy.gui import display

    app = Depot()
    display(app)