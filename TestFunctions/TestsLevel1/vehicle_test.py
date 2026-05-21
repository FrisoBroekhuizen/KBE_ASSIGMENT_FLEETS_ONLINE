# from parapy.core import Base, Input, Attribute, Part, child, action
# from parapy.exchange import STEPWriter

import numpy as np
# import pytest

class Vehicle():
    """
    Description:
        Superclass for self-propelled machines (Tractor, Truck, Crane, Forklift).

    UML attributes:
        - vehicle_id: string
        - wheelbase: float
        - wheelbase_track: float
        - number_of_axles: float
    """

    dimensions = [2, 1.5, 2]
    dimensions_rear = [6, 1.5, 2]

    # TEST 1 - Test case from P. 11 of VME exercises
    # wheelbase = 1.5
    # wheelbase_rear = 5
    # wheelbase_track = 1
    # number_of_axles = 3
    # max_steering_angle = 25

    # TEST 2 - Test case from P. 33 of VME exercises
    wheelbase = 4
    wheelbase_rear = 6
    wheelbase_track = 0
    number_of_axles = 3
    max_steering_angle = 30

    def TurnRadius(self):
        max_steering_angle = self.max_steering_angle * np.pi / 180

        # 2-axle vehicles (cars)
        # Using the low-speed Ackerman model
        if self.number_of_axles <= 2:
            rear_turning_radius = self.wheelbase / np.tan(max_steering_angle)
            outer_steering_angle = np.arctan(self.wheelbase / (rear_turning_radius + self.wheelbase_track))
            max_turning_radius = (rear_turning_radius + self.wheelbase_track) / np.cos(outer_steering_angle)

            assert round(max_turning_radius, 3) == 4.476

            overhang = np.sqrt(((self.dimensions[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions[1] - self.wheelbase_track) / 2) ** 2)

            max_turning_radius += overhang

        # 3-axle vehicles (trucks)
        # Low-speed non-Ackerman with articulation
        elif self.number_of_axles >= 3:
            center_turning_radius = self.wheelbase / np.tan(max_steering_angle)
            outer_front_steering_angle = np.arctan(self.wheelbase / (center_turning_radius + self.wheelbase_track))
            max_front_turning_radius = (center_turning_radius + self.wheelbase_track) / np.cos(outer_front_steering_angle)
            assert round(max_front_turning_radius, 2) == 8

            overhang_front = np.sqrt(((self.dimensions[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions[1] - self.wheelbase_track) / 2) ** 2)
            max_front_turning_radius += overhang_front

            max_center_turning_radius = (center_turning_radius + self.wheelbase_track)
            assert round(max_center_turning_radius, 2) == 6.93

            overhang_center = (self.dimensions[1] - self.wheelbase_track) / 2
            max_center_turning_radius += overhang_center

            if self.wheelbase_rear > center_turning_radius:
                # Truck trailer is longer then its turning radius: the rear of the trailer will not move and the turning radius is therefore 0
                rear_turning_radius = 0
            else:
                rear_turning_radius = np.sqrt(center_turning_radius ** 2 - self.wheelbase_rear ** 2)

            max_rear_turning_radius = rear_turning_radius + self.wheelbase_track
            assert round(max_rear_turning_radius, 2) == 3.46

            overhang_rear = np.sqrt(((self.dimensions_rear[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions_rear[1] - self.wheelbase_track) / 2) ** 2)
            max_rear_turning_radius += overhang_rear

            print(max_front_turning_radius, max_center_turning_radius, max_rear_turning_radius)

            max_turning_radius = max(max_front_turning_radius, max_center_turning_radius, max_rear_turning_radius)
        else:
            # Can optionally also implement more axles on the rear of the trailer
            max_turning_radius = 0

        return max_turning_radius

if __name__ == "__main__":
    vehicle = Vehicle()
    turnRadius = vehicle.TurnRadius()
    print(turnRadius)