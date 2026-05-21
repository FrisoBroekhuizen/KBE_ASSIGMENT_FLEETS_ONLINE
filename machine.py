from __future__ import annotations

from typing import Tuple

from parapy.core import Base, Input, Attribute

import numpy as np


# ---------------------------------------------------------------------------
# Superclass: Machine and its specializations
# ---------------------------------------------------------------------------

class Machine(Base):
    """
    Description:
        Generic superclass for all equipment in the fleet (vehicles and tools).

    UML attributes:
        - age: float
        - prediction_tool: string
        - historical_data_file: string (e.g. path to .xlsx file)
        - worth: float
        - energy_source: string
        - mass: float
        - overall_dimensions: array [x, y, z]
        - gps_location: string
        - availability: bool

    UML operations:
        - CalculateIndividualCO2()
        - CalculateIndividualNOX()
        - CalculateIndividualCost()
    """

    age: float = Input(0.0)
    prediction_tool: str = Input("")
    historical_data_file: str = Input("")   # can point to .xlsx / .csv, etc.

    worth: float = Input(0.0)
    energy_source: str = Input("")
    mass: float = Input(0.0)

    # overall_dimensions: array[x, y, z]
    overall_dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))

    gps_location: str = Input("")
    availability: bool = Input(True)

    # UML operations – placeholders
    # look at comments in main
    def CalculateIndividualCO2(self) -> float:
        raise NotImplementedError

    def CalculateIndividualNOX(self) -> float:
        raise NotImplementedError

    def CalculateIndividualCost(self) -> float:
        raise NotImplementedError


class Vehicle(Machine):
    """
    Description:
        Superclass for self-propelled machines (Tractor, Truck, Crane, Forklift).

    UML attributes:
        - vehicle_id: string
        - wheelbase: float
        - wheelbase_track: float
        - number_of_axles: float
    """

    vehicle_id: str = Input("")

    # Turning parameters for turning radius during depot arranging
    wheelbase: float = Input(0.0)
    wheelbase_rear: float = Input(0.0)
    wheelbase_track: float = Input(0.0)
    number_of_axles: float = Input(0.0)
    max_steering_angle: float = Input(30.0)

    dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))
    dimensions_rear: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))

    @Attribute
    def TurnRadius(self):
        max_steering_angle = self.max_steering_angle * np.pi / 180

        # 2-axle vehicles (cars)
        # Using the low-speed Ackerman model
        if self.number_of_axles <= 2:
            rear_turning_radius = self.wheelbase / np.tan(max_steering_angle)
            outer_steering_angle = np.arctan(self.wheelbase / (rear_turning_radius + self.wheelbase_track))
            max_turning_radius = (rear_turning_radius + self.wheelbase_track) / np.cos(outer_steering_angle)

            # P. 11 of VME exercises
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
            # P. 33 of VME exercises
            assert round(max_rear_turning_radius, 2) == 3.46

            overhang_rear = np.sqrt(((self.dimensions_rear[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions_rear[1] - self.wheelbase_track) / 2) ** 2)
            max_rear_turning_radius += overhang_rear

            print(max_front_turning_radius, max_center_turning_radius, max_rear_turning_radius)

            max_turning_radius = max(max_front_turning_radius, max_center_turning_radius, max_rear_turning_radius)
        else:
            # Can optionally also implement more axles on the rear of the trailer
            max_turning_radius = 0

        return max_turning_radius


class Tractor(Vehicle):
    """
    Description:
        Tractor used for towing or agricultural / construction work.

    UML attributes:
        - max_loading_weight: float
        - contents: object (default: empty)
    """

    max_loading_weight: float = Input(0.0)
    contents: object = Input(None)  # default: empty


class Truck(Vehicle):
    """
    Description:
        Truck used to transport slower machines and tools.

    UML attributes:
        - carrying_bounding_box: array (e.g. [L, W, H] of cargo space)
        - max_loading_weight: float
        - contents: object (default: empty)
    """

    carrying_bounding_box: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))
    max_loading_weight: float = Input(0.0)
    contents: object = Input(None)  # default: empty


class Crane(Vehicle):
    """
    Description:
        Crane used for lifting operations.

    UML attributes:
        - is_stationary: bool
    """

    is_stationary: bool = Input(False)


class Tool(Machine):
    """
    Description:
        Generic tool that requires transport (attachments, smaller equipment).

    UML attributes:
        - tool_id: string
    """

    tool_id: str = Input("")


class Pump(Tool):
    """
    Description:
        Pump or similar stationary tool.

    UML attributes:
        - energy_source: diesel (default)
    """

    # UML: energy_source: diesel (default)
    energy_source: str = Input("diesel")
