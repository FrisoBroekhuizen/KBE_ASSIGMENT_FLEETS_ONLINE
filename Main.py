from _future_ import annotations

from typing import List, Tuple, Optional

from parapy.core import Base, Input


# ---------------------------------------------------------------------------
# Top-level application
# ---------------------------------------------------------------------------

class MissionStrategyApp(Base):
    """Top-level KBE app coordinating fleet, depots and jobs."""

    # UML attributes
    needed_tools: str = Input("")
    needed_machinery: str = Input("")
    site_location: str = Input("")
    deadlines: List[str] = Input([])

    # Aggregations / associations
    fleet: Optional["Fleet"] = Input(None)
    depots: List["Depot"] = Input([])
    transport_jobs: List["TransportJob"] = Input([])
    work_jobs: List["WorkJob"] = Input([])

    # UML operation – placeholder
    def EvaluateCostFunction(self) -> float:
        """Placeholder for multi-objective cost/emission/time function."""
        raise NotImplementedError

# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class TransportJob(Base):
    """Job representing transport between two GPS locations."""

    volume: float = Input(0.0)
    weight: float = Input(0.0)

    begin_location_gps: str = Input("")
    end_location_gps: str = Input("")

    needed_machinery: str = Input("")

    # Dotted UML link “Get Fleet”: reference to the fleet used for this job
    fleet: Optional[Fleet] = Input(None)

    # UML operations – placeholders
    def RoutePlanner(self):
        raise NotImplementedError

    def TimeKeeper(self):
        raise NotImplementedError

    def MaintenancePredictor(self):
        raise NotImplementedError

    def CalculateNOX(self) -> float:
        raise NotImplementedError

    def CalculateCO2(self) -> float:
        raise NotImplementedError

    def CalculateCost(self) -> float:
        raise NotImplementedError


class WorkJob(Base):
    """Job representing on-site work using machines and tools."""

    man_hours: float = Input(0.0)

    # overall_dimensions: array[x, y, z]
    overall_dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))

    needed_tools: str = Input("")
    needed_machinery: str = Input("")

    # Resources actually assigned to this work job
    assigned_tools: List[Tool] = Input([])
    assigned_machines: List[Machine] = Input([])

    # Dotted UML link “Get Fleet”
    fleet: Optional[Fleet] = Input(None)

    # UML operations – placeholders
    def TimeKeeper(self):
        raise NotImplementedError

    def MaintenancePredictor(self):
        raise NotImplementedError

    def CalculateCO2(self) -> float:
        raise NotImplementedError

    def CalculateNOX(self) -> float:
        raise NotImplementedError

    def CalculateCost(self) -> float:
        raise NotImplementedError

# ---------------------------------------------------------------------------
# Fleet and locations
# ---------------------------------------------------------------------------

class Fleet(Base):
    """Collection of machines available for missions."""

    location: str = Input("")
    budget: float = Input(0.0)
    fleetWorth: float = Input(0.0)
    sector: str = Input("")

    # Composition: a fleet has many machines
    machines: List["Machine"] = Input([])


class Depot(Base):
    """Depot with spatial dimensions and arranged machines."""

    location: str = Input("")
    # overall_dimensions: array[x, y, z]
    overall_dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))

    # Machines currently stored in this depot (not shown in UML, but natural)
    # Get locations (which depots) and dimensions of the machines
    machines: List["Machine"] = Input([])

    # UML operation – placeholder
    def DepotMachineArrangement(self):
        """Placeholder for machine arrangement / packing algorithm."""
        raise NotImplementedError


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