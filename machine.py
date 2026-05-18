# from _future_ import annotations

from typing import List, Tuple, Optional

from parapy.core import Base, Input

# ---------------------------------------------------------------------------
# Superclass: Machine and its specializations
# ---------------------------------------------------------------------------

class Machine(Base):
    """Superclass for all machinery and tools."""

    # UML attributes
    age: float = Input(0.0)
    prediction_tool: str = Input("")
    historical_data_file: str = Input("")

    worth: float = Input(0.0)
    energy_source: str = Input("")
    mass: float = Input(0.0)

    # overall_dimensions: array[x, y, z]
    overall_dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))

    gps_location: str = Input("")

    # UML operations – placeholders
    def CalculateIndividualCO2(self) -> float:
        raise NotImplementedError

    def CalculateIndividualNOX(self) -> float:
        raise NotImplementedError

    def CalculateIndividualCost(self) -> float:
        raise NotImplementedError


class Vehicle(Machine):
    """Superclass for self-propelled machines (Tractor, Truck, etc.)."""

    vehicle_id: str = Input("")
    wheelbase: float = Input(0.0)
    wheelbase_track: float = Input(0.0)
    number_of_axles: float = Input(0.0)


class Tractor(Vehicle):
    max_loading_weight: float = Input(0.0)
    contents: object = Input(None)  # default: empty


class Bulldozer(Vehicle):
    terrain: str = Input("")
    operational_site_hours: float = Input(0.0)


class Truck(Vehicle):
    # carrying_bounding_box: array (e.g. [L, W, H] of cargo space)
    carrying_bounding_box: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))
    max_loading_weight: float = Input(0.0)
    contents: object = Input(None)  # default: empty


class Crane(Vehicle):
    is_stationary: bool = Input(False)


class Forklift(Vehicle):
    indoor_use: bool = Input(False)


class Pump(Machine):
    # UML: energy_source: diesel (default)
    energy_source: str = Input("diesel")


class Tool(Machine):
    tool_id: str = Input("")