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

    age: float = Input(0.0) # Years
    prediction_tool: str = Input("")
    historical_data_file: str = Input("")   # can point to .xlsx / .csv, etc.

    worth: float = Input(0.0) # Million Euro's
    energy_source: str = Input("") # Can be: Diesel, Gasoline, Electric, Hybrid
    mass: float = Input(0.0)

    # overall_dimensions: array[x, y, z]
    overall_dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))

    # GPS location of the machine: (latitude [deg], longitude [deg])
    gps_location: Tuple[float, float] = Input((0.0, 0.0))
    availability: bool = Input(True)

    operating_fraction = 8  # Assumed data contains hours/day
    idle_fraction = 2  # Assumed data contains hours/day

    # Weights of wear caused by different ways of using the machine
    w_operating = 1e-5
    w_idle = 3e-6
    w_stationary = 5e-7

    energy_source_factors = {"Diesel": 1.2,
                             "Gasoline": 1.1,
                             "Electric": 0.8,
                             "Hybrid": 1.3}

    machine_type_factors = {"Crane": 1.6,
                            "Tractor": 1.3,
                            "Truck": 1.1,
                            "Vehicle": 1,
                            "Tool": 1.6,
                            "Pump": 1.9}

    # UML operations – placeholders
    # look at comments in main
    def CalculateIndividualCO2(self) -> float:
        raise NotImplementedError

    def CalculateIndividualNOX(self) -> float:
        raise NotImplementedError

    def CalculateIndividualCost(self) -> float:
        raise NotImplementedError

    def CalculateIndividualMaintenance(self) -> float:
        # Normalize hours spend by the machine as a base decay_factor
        total_hours = self.age * 365 * 24
        operating_hours = total_hours * self.operating_fraction / 24
        idle_hours = total_hours * self.idle_fraction / 24
        stationary_hours = total_hours - operating_hours - idle_hours

        decay_factor = 8760 * (
                    self.w_operating * operating_hours + self.w_idle * idle_hours + self.w_stationary * stationary_hours) / total_hours

        # Alter the decay factor based on machine worth, energy_source and machine_type
        decay_factor *= (1 + 0.01 * self.worth)
        decay_factor *= self.energy_source_factors[self.energy_source]
        decay_factor *= self.machine_type_factors[type(self).__name__]

        productivity = np.exp(-decay_factor * self.age)
        return productivity


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
    wheelbase: float = Input(1)
    wheelbase_rear: float = Input(5)
    wheelbase_track: float = Input(2)
    number_of_axles: int = Input(2)
    max_steering_angle: float = Input(30.0)

    dimensions: Tuple[float, float, float] = Input((1, 2, 2))
    dimensions_rear: Tuple[float, float, float] = Input((5, 2, 2))

    @Attribute
    def TurnRadius(self):
        max_steering_angle = self.max_steering_angle * np.pi / 180

        # 2-axle vehicles (cars)
        # Using the low-speed Ackerman model
        if self.number_of_axles <= 2:
            rear_turning_radius = self.wheelbase / np.tan(max_steering_angle)
            outer_steering_angle = np.arctan(self.wheelbase / (rear_turning_radius + self.wheelbase_track))
            max_turning_radius = (rear_turning_radius + self.wheelbase_track) / np.cos(outer_steering_angle)

            overhang = np.sqrt(((self.dimensions[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions[1] - self.wheelbase_track) / 2) ** 2)

            max_turning_radius += overhang

        # 3-axle vehicles (trucks)
        # Low-speed non-Ackerman with articulation
        elif self.number_of_axles >= 3:
            center_turning_radius = self.wheelbase / np.tan(max_steering_angle)
            outer_front_steering_angle = np.arctan(self.wheelbase / (center_turning_radius + self.wheelbase_track))
            max_front_turning_radius = (center_turning_radius + self.wheelbase_track) / np.cos(outer_front_steering_angle)

            overhang_front = np.sqrt(((self.dimensions[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions[1] - self.wheelbase_track) / 2) ** 2)
            max_front_turning_radius += overhang_front

            max_center_turning_radius = (center_turning_radius + self.wheelbase_track)

            overhang_center = (self.dimensions[1] - self.wheelbase_track) / 2
            max_center_turning_radius += overhang_center

            if self.wheelbase_rear > center_turning_radius:
                # Truck trailer is longer then its turning radius: the rear of the trailer will not move and the turning radius is therefore 0
                rear_turning_radius = 0
            else:
                rear_turning_radius = np.sqrt(center_turning_radius ** 2 - self.wheelbase_rear ** 2)

            max_rear_turning_radius = rear_turning_radius + self.wheelbase_track

            overhang_rear = np.sqrt(((self.dimensions_rear[0] - self.wheelbase) / 2) ** 2 + ((self.dimensions_rear[1] - self.wheelbase_track) / 2) ** 2)
            max_rear_turning_radius += overhang_rear

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

if __name__ == "__main__":
    from parapy.gui import display
    app = Vehicle()
    display(app)
