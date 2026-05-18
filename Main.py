# from _future_ import annotations

import os
from typing import List, Tuple, Optional

from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter

from machine import *

maindir = os.path.dirname(__file__)

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

    @Attribute
    def all_jobs(self) -> List[Base]:
        return [*self.transport_jobs, *self.work_jobs]

    @Attribute
    def number_of_machines_in_fleet(self) -> int:
        return len(self.fleet.machines) if self.fleet else 0

    # UML operation – placeholder
    def EvaluateCostFunction(self) -> float:
        """Placeholder for multi-objective cost/emission/time function."""
        raise NotImplementedError

    # -- Export geometry function --

    # ------------------------------

    # -- Actions / Buttons --

    @action(button_label="Generate Strategies")
    def generate_strategies(self):
        raise NotImplementedError

    @action(button_label="Export Results")
    def export_results(self):
        # Export JSON results
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
    fleet: Optional["Fleet"] = Input(None)

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
    assigned_tools: List["Tool"] = Input([])
    assigned_machines: List["Machine"] = Input([])

    # Dotted UML link “Get Fleet”
    fleet: Optional["Fleet"] = Input(None)

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

if __name__ == "__main__":
    from parapy.gui import display

    fleet = Fleet(location="NL", budget=1_000_000, machines=[])
    app = MissionStrategyApp(
        needed_tools="shovels, pumps",
        needed_machinery="tractors, trucks",
        site_location="Some worksite",
        fleet=fleet,
        show_in_tree=True,  # optional Input if you add it later
    )

    display(app)