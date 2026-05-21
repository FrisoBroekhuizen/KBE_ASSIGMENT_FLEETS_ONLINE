from __future__ import annotations

from typing import Tuple

from parapy.core import Base, Input


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

    # GPS location of the machine: (latitude [deg], longitude [deg])
    gps_location: Tuple[float, float] = Input((0.0, 0.0))
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
    wheelbase_track: float = Input(0.0)
    number_of_axles: float = Input(0.0)


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
