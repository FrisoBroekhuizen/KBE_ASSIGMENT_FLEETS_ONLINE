from __future__ import annotations

import datetime
from typing import Tuple, List

import numpy as np

from EmissionsExternalTool import CO2Calculator, NOxCalculator
from parapy.core import Base, Input, Attribute
from parapy.core.validate import OneOf
from parapy.core.widgets import PyField, TextField


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

    machine_id = Input(
        "",
        widget=TextField(
            autocompute=True,
            background_color=lambda self: (
                "Red" if self.machine_id == "" else "White"
            ),
        ),
    )

    machine_type = Input(
        "",
        widget=TextField(
            autocompute=True,
            background_color=lambda self: (
                "Red"
                if self.machine_type
                not in ["Tractor", "Truck", "Crane", "Tool", "Pump"]
                else "White"
            ),
        ),
    )

    # default current year (new)
    build_year: int = Input(
        datetime.datetime.today().year,
        widget=PyField(autocompute=True),
    )

    # historical_data_file: str = Input("")   # can point to .xlsx / .csv, etc.
    emission_class: str = Input(
        "StageIIIB",
        validator=OneOf(
            ("Manual", "StageI", "StageII", "StageIIIA", "StageIIIB", "StageIV")
        ),
        widget=TextField(autocompute=True),
    )

    # Million Euro's
    worth: float = Input(
        1.0,
        widget=PyField(autocompute=True),
    )

    # Possible fuel types: benzine-(e10-blend), bio-ethanol-(100%), e85,
    # diesel-(b7-blend), diesel-(fossiel), biodiesel-(hvo), biodiesel-(fame),
    # gtl, cng, bio-cng, lng, bio-lng, lpg, waterstof-(grijs),
    # waterstof-(groen), marine-diesel-oil-(mdo), heavy-fuel-oil-(hfo),
    # kerosine-(jet-a1), HVO10, HVO20, HVO30, HVO50, HVO70, HVO100
    energy_source: str = Input(
        "Choose one of: Manual, diesel-(fossiel), biodiesel-(hvo), "
        "benzine-(e10-blend), Electric, Hybrid",
        widget=TextField(
            autocompute=True,
            background_color=lambda self: (
                "Red"
                if self.energy_source
                not in [
                    "Manual",
                    "diesel-(fossiel)",
                    "biodiesel-(hvo)",
                    "benzine-(e10-blend)",
                    "Electric",
                    "Hybrid",
                ]
                else "White"
            ),
        ),
    )

    mass: float = Input(
        0.0,
        widget=PyField(autocompute=True),
    )

    # Color used in visualizations (Depot, trailers, etc.).
    # None or "" means "use class-dependent default".
    color: str = Input(
        "Yellow",
        widget=TextField(
            autocompute=True,
            background_color=lambda self: self.color,
        ),
    )

    # (L or kW)/h
    consumption_per_hour = Input(
        1.0,
        widget=PyField(autocompute=True),
    )

    number_of_this_type = 1

    # overall_dimensions: array[x, y, z]
    overall_dimensions: Tuple[float, float, float] = Input(
        (0.0, 0.0, 0.0),
        widget=PyField(
            autocompute=True,
            background_color=lambda self: (
                "Red"
                if self.overall_dimensions == (0.0, 0.0, 0.0)
                else "White"
            ),
        ),
    )

    # Only used for truck + tractor combinations
    total_length = 0

    # GPS location of the machine: (latitude [deg], longitude [deg])
    gps_location: Tuple[float, float] = Input(
        (0.0, 0.0),
        widget=PyField(
            autocompute=True,
            background_color=lambda self: (
                "Red" if self.gps_location == (0.0, 0.0) else "White"
            ),
        ),
    )

    total_hours_used = Input(0.0)
    hours_used = Input(0.0)

    # Assumed data contains hours/day
    operating_fraction = 8
    # Assumed data contains hours/day
    idle_fraction = 2

    # Weights of wear caused by different ways of using the machine
    w_operating = 4e-6
    w_idle = 2e-6
    w_stationary = 1e-8

    # Current energy prices in eur per kg, L or kW
    energy_source_cost = {
        "diesel-(fossiel)": 2.19,  # /L
        "biodiesel-(hvo)": 1.9,
        "benzine-(e10-blend)": 2.31,  # /L
        "Electric": 0.8,  # /kWh
        "Hybrid": 1.4,  # /Combo
        "Manual": 0 # Tools
    }

    energy_source_factors = {
        "diesel-(fossiel)": 1.2,
        "biodiesel-(hvo)": 1.3,
        "benzine-(e10-blend)": 1.1,
        "Electric": 0.8,
        "Hybrid": 1.3,
        "Manual": 1
    }

    machine_type_factors = {
        "Crane": 1.6,
        "Tractor": 1.3,
        "Truck": 1.1,
        "Vehicle": 1,
        "Tool": 1.6,
        "Pump": 1.9,
    }

    expected_turnover_factors = {
        "Crane": 500,
        "Tractor": 300,
        "Truck": 250,
        "Vehicle": 100,
        "Tool": 20,
        "Pump": 50,
    }

    wage = Input(20)

    # UML operations – placeholders
    # look at comments in main

    @Attribute
    def age(self) -> float:
        """Age in years, derived from build_year."""
        return datetime.datetime.today().year - self.build_year

    @Attribute
    def individual_co2(self) -> float:
        """CO2 [kg] over self.hours_used."""
        if self.energy_source == "Manual":
            return 0
        fuel_type = self.energy_source.lower()
        fuel_usage = self.consumption_per_hour * self.hours_used
        result = CO2Calculator(
            energy_source=self.energy_source,
            fuel_type=fuel_type,
            fuel_usage_liters=fuel_usage,
            year=self.build_year,
        )
        return result

    @Attribute
    def individual_nox(self) -> float:
        """NOx [g] over self.hours_used using AUB method by default."""
        if self.emission_class == "Manual":
            return 0
        fuel_usage = self.consumption_per_hour * self.hours_used
        result = NOxCalculator(
            energy_source=self.energy_source,
            emission_class=self.emission_class,
            fuel_liters=fuel_usage,
            engine_hours=self.hours_used,
        )
        return result

    @Attribute
    def individual_cost(self) -> float:
        """Total mission cost for this machine over self.hours_used."""
        hours_used = self.hours_used
        # A factor to account for extra maintenance, inefficiency,
        # extra emissions, reliability, etc.
        wear_factor = self.individual_depreciation

        # Check if vehicle is carrying any additional mass
        try:
            content_mass = self.contents.mass
            try:
                # Check if vehicle was carrying a trailer that
                # is carrying additional mass
                trailer_content_mass = self.contents.contents[0].mass
            except Exception:
                trailer_content_mass = 0
            loading_factor = (
                self.mass + content_mass + trailer_content_mass
            ) / self.mass
        except Exception:
            loading_factor = 1

        # Operating costs: fuel, predicted maintenance and wages
        operating_cost = (
            self.consumption_per_hour
            * hours_used
            * self.energy_source_cost[self.energy_source]
            * loading_factor
            * wear_factor
        )
        operating_cost += self.wage * self.hours_used

        # Opportunity costs: missed turnover and scarcity value
        opportunity_cost = (
            self.expected_turnover_factors[self.machine_type]
            * self.hours_used
        )
        # Make the simplification that the scarcity of a machine
        # scales with 1 / sqrt(number of available machines)
        scarcity_factor = 1 / np.sqrt(self.number_of_this_type)
        opportunity_cost *= scarcity_factor

        # Check if machine is a truck carrying another vehicle,
        # which also has associated opportunity costs
        try:
            if self.contents is not None:
                if self.contents.contents != []:
                    truck_content_opportunity_cost = (
                        self.expected_turnover_factors[
                            self.contents.contents[0].machine_type
                        ]
                        * self.hours_used
                    )
                else:
                    truck_content_opportunity_cost = 0
            else:
                truck_content_opportunity_cost = 0
        except Exception:
            truck_content_opportunity_cost = 0

        return (
            operating_cost
            + opportunity_cost
            + truck_content_opportunity_cost
        )

    @Attribute
    def individual_depreciation(self) -> float:
        """Wear factor based on usage over machine age."""
        # Normalize hours spent by the machine as a base decay_factor
        total_hours = self.age * 365 * 24
        if total_hours == 0:
            total_hours = 1  # Fail-safe, difference is negligible

        operating_hours = total_hours * self.operating_fraction / 24
        idle_hours = total_hours * self.idle_fraction / 24
        stationary_hours = (
            total_hours - operating_hours - idle_hours
        )

        decay_factor = (
            8760
            * (
                self.w_operating * operating_hours
                + self.w_idle * idle_hours
                + self.w_stationary * stationary_hours
            )
            / total_hours
        )

        # Alter the decay factor based on machine worth, energy_source
        # and machine_type
        decay_factor *= (1 + 0.01 * self.worth / 1000000)
        decay_factor *= self.energy_source_factors[self.energy_source]
        decay_factor *= self.machine_type_factors[type(self).__name__]

        wear_factor = np.exp(decay_factor * self.age)
        return wear_factor


class Vehicle(Machine):
    """
    Description:
        Superclass for self-propelled machines (Tractor, Truck, Crane,
        Forklift).

    UML attributes:
        - vehicle_id: string
        - wheelbase: float
        - wheelbase_track: float
        - number_of_axles: float
    """

    vehicle_id: str = Input("")

    # Turning parameters for turning radius during depot arranging
    max_steering_angle: float = Input(20.0)
    color = Input("Yellow")

    @Input
    def wheelbase(self):
        return self.overall_dimensions[0]

    @Input
    def wheelbase_track(self):
        return self.overall_dimensions[1]

    @Input
    def number_of_axles(self):
        if self.machine_type == "Truck":
            try:
                if self.contents is not None:
                    return 3
                else:
                    return 2
            except Exception:
                return 2
        else:
            return 2

    @Input
    def wheelbase_rear(self):
        if self.number_of_axles > 2:
            return self.contents[0].overall_dimensions[0]
        else:
            return 0

    @Input
    def dimensions(self):
        return self.overall_dimensions

    @Input
    def dimensions_rear(self):
        if self.number_of_axles > 2:
            return self.contents[0].overall_dimensions
        else:
            return 0

    @Attribute
    def turn_radius(self):
        max_steering_angle = self.max_steering_angle * np.pi / 180

        # 2-axle vehicles (cars)
        # Using the low-speed Ackerman model
        if self.number_of_axles <= 2:
            rear_turning_radius = (
                self.wheelbase / np.tan(max_steering_angle)
            )
            outer_steering_angle = np.arctan(
                self.wheelbase
                / (rear_turning_radius + self.wheelbase_track)
            )
            max_turning_radius = (
                rear_turning_radius + self.wheelbase_track
            ) / np.cos(outer_steering_angle)

            overhang = np.sqrt(
                ((self.dimensions[0] - self.wheelbase) / 2) ** 2
                + (
                    (self.dimensions[1] - self.wheelbase_track) / 2
                )
                ** 2
            )

            max_turning_radius += overhang

        # 3-axle vehicles (trucks)
        # Low-speed non-Ackerman with articulation
        elif self.number_of_axles >= 3:
            center_turning_radius = (
                self.wheelbase / np.tan(max_steering_angle)
            )
            outer_front_steering_angle = np.arctan(
                self.wheelbase
                / (center_turning_radius + self.wheelbase_track)
            )
            max_front_turning_radius = (
                center_turning_radius + self.wheelbase_track
            ) / np.cos(outer_front_steering_angle)

            overhang_front = np.sqrt(
                ((self.dimensions[0] - self.wheelbase) / 2) ** 2
                + (
                    (self.dimensions[1] - self.wheelbase_track) / 2
                )
                ** 2
            )
            max_front_turning_radius += overhang_front

            max_center_turning_radius = (
                center_turning_radius + self.wheelbase_track
            )

            overhang_center = (
                self.dimensions[1] - self.wheelbase_track
            ) / 2
            max_center_turning_radius += overhang_center

            if self.wheelbase_rear > center_turning_radius:
                # Truck trailer is longer then its turning radius:
                # the rear of the trailer will not move and
                # the turning radius is therefore 0
                rear_turning_radius = 0
            else:
                rear_turning_radius = np.sqrt(
                    center_turning_radius**2
                    - self.wheelbase_rear**2
                )

            max_rear_turning_radius = (
                rear_turning_radius + self.wheelbase_track
            )

            overhang_rear = np.sqrt(
                ((self.dimensions_rear[0] - self.wheelbase) / 2) ** 2
                + (
                    (self.dimensions_rear[1] - self.wheelbase_track)
                    / 2
                )
                ** 2
            )
            max_rear_turning_radius += overhang_rear

            max_turning_radius = max(
                max_front_turning_radius,
                max_center_turning_radius,
                max_rear_turning_radius,
            )
        else:
            # Can optionally also implement more axles on the rear
            # of the trailer
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

    bounding_box: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))
    max_loading_weight: float = Input(0.0)
    contents: object = Input(None)  # Trailer


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
    vehicle_attachable: bool = Input(False)
    color = Input("Blue")
    upright_only: bool = Input(False)


class Pump(Tool):
    """
    Description:
        Pump or similar stationary tool.

    UML attributes:
        - energy_source: diesel (default)
    """

    # UML: energy_source: diesel (default)
    energy_source: str = Input("Diesel")


class Trailer(Base):
    """
    Description:
        Non‑powered trailer asset.

    Notes:
        - NOT a Machine: no individual emissions, NOX, cost, maintenance.
        - Only used as capacity / geometry in transport & packing.
    """

    # Identifier for reporting / debug
    trailer_id: str = Input("")

    # Internal usable cargo volume [L, W, H] in meters
    carrying_bounding_box: Tuple[float, float, float] = Input(
        (0.0, 0.0, 0.0)
    )
    overall_dimensions = carrying_bounding_box

    # Maximum additional load [kg] it may carry (excluding its own
    # structural mass)
    max_loading_weight: float = Input(0.0)

    # True if fully covered (box), False if flatbed / open
    has_ceiling: bool = Input(True)

    mass = Input(0.0)

    # Simple location if you still want to park them in depots / on sites
    # (you could also omit this if you only care about capacity)
    gps_location: Tuple[float, float] = Input((0.0, 0.0))

    # Only used for truck + tractor combinations
    total_length = Input(0)

    # Logical content (IDs, Machine references, or your packing Items)
    contents: List[object] = Input([None])


if __name__ == "__main__":
    from parapy.gui import display

    app = Vehicle()
    display(app)

