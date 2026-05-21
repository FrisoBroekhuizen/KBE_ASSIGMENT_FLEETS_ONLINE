# from _future_ import annotations
import math
import os
from typing import List, Tuple, Optional

from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter

from machine import *

import Routing

maindir = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# Top-level application
# ---------------------------------------------------------------------------

class MissionStrategyApp(Base):
    """
        Description: The top-level class that uses the fleet, jobs and the mission profiles to
                     create the final strategy.
        Inputs: - JSON file of the fleet with its availability, location, etc...
                - Mission preferences (Strict deadlines or not)
        Outputs: - The chosen strategy, with the specific vehicles that will do their action at
                   specified jobs at a certain time.
                 - Arrangement geometry in 2D (depots) and 3D (storage)
                 - The routes of the final strategy
                 - Visualization output of the arrangement
                 - PDF summary of the chosen strategy
        To Do's: - make preference interface (action with standard preference with easy names such as greedy or hurry)
                 also the option to define own preferences and normalize within function.
                 - If time: combine multiple work jobs into one mission.
                 - Maximum vehicles in worksite is area worksite divided by area vehicle times a factor"""

    # Mission attributes
    needed_tools: str = Input("")
    needed_machinery: str = Input("")
    site_dimensions: Tuple[float, float] = Input((0.0, 0.0)) # overall_dimensions: array[x', y'], always a rectangle, in its own reference system
    site_location: Tuple[float, float, float] = Input((0.0, 0.0, 0.0)) # [x', y' and north-rotation]

    # Aggregations / associations
    mission_preferences: List[float] = Input([1.0, 1.0, 1.0])  # List of weights for the different optimalisation goals
    strict_deadline: bool = Input(False)
    # Aggregations / associations
    fleet: Optional["Fleet"] = Input(None)
    depots: List["Depot"] = Input([])
    transport_jobs: List["TransportJob"] = Input([])
    work_jobs: List["WorkJob"] = Input([])


    def JSONReader(self):
        """"TODO:IF NOT GPS location provided: print 'no locations of machine X provided,, machine will be ignored for future analysis' """
        raise NotImplementedError
    @Attribute
    def all_jobs(self) -> List[Base]:
        # Later done to put jobs next to each other for time planning and mission generation
        return [*self.transport_jobs, *self.work_jobs]

    @Attribute
    def number_of_machines_in_fleet(self) -> int:
        # Later done to sum the machines for strategy evaluation
        return len(self.fleet.machines) if self.fleet else 0

    @Part
    def TransportJob(self):
        return TransportJob()

    # Define (normalized) preferences function
    @action()
    def NormalizePreferences(self) -> List[float]:
        """Normalize mission_preferences:
        - Negative values => 0 (user really doesn't want that objective)
        - Non-negative values are scaled so sum == 1
        - If all are <= 0, fall back to equal weights.
        """
        prefs = [float(p) for p in self.mission_preferences]
        if not prefs:
            return []

        # Clamp negatives to 0 (completely unwanted)
        clamped = [p if p > 0.0 else 0.0 for p in prefs]

        total = sum(clamped)

        if total > 0.0:
            normalized = [p / total for p in clamped]
        else:
            # all preferences <= 0 -> no clear preference,
            # fall back to equal weights
            n = len(prefs)
            normalized = [1.0 / n] * n

        self.mission_preferences = normalized
        return normalized

    @action()
    def Planner(self):
        for work_job in self.work_jobs:
            print(work_job)

    def MissionIterator(self) -> None:
        # Function that iterates over all the different possible strategies. In order to achieve a specific mission,
        # the possible combinations of transport and work jobs are generated here. These are then used in
        # EvaluateCostFunction, which uses the MissionIterator with the normalized mission preferences.
        # A viability check is also performed. (Such as cancelling machines that are too far anyway)

        # To do: think about how to apply this.
        # Idea: Can maybe use nearest-neighbour method to start searching from the most close-by truck
        # Include deadline logic to skip useless vehicles
        # If strict deadlines boolean true, only strategies that can manage this deadline are considered.

        # To do: Also tries to do the arranging of vehicles and containers, if this turns out to be too computationally
        # expensive, a rough estimate can be made with maximal dimensions and volume logic, and the actual arranging is
        # done in a final visualization function, in order to get the most efficient loading.
        # Idea: start with one container (with the max volume check), and keep adding trucks until it fits, to ensure
        # minimal truck usage.
        raise NotImplementedError

    # UML operation – placeholder
    def EvaluateCostFunction(self) -> float:
        # Function that evaluates the cost function for each viable generated strategy, together with the normalized
        # mission preferences. This function evaluates the cost function for each mission 'block' (matrix multiplication?)
        # which results in a single scalar value. The lowest value and corresponding strategy is picked.
        # This acts as our robust optimizer

        raise NotImplementedError

    def ContainerVisualization(self):
        raise NotImplementedError

    # -- Export geometry function --

    # With the final chosen strategy, arrangement is conducted for the depots and containers. Vehicles are only
    # 2D [x, y] and tools can also be stacked in 3D [x, y, z] in boxes. A new Python file will perform the 2D and
    # 3D arrangement logic.
    # To do: work out, also include arrangement logic and rules (turn radius, path widths, stacking logic, ...)

    # ------------------------------

    # -- Actions / Buttons --

    @action(button_label="Generate Strategies")
    def generate_strategies(self):
        raise NotImplementedError

    @action(button_label="Export Results")
    def export_results(self):
        # Export JSON results
        raise NotImplementedError

    # Define (normalized) preferences function

# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class TransportJob(Base):
    """
    Description: Job representing the transport of a vehicle from its initial position to a target location.
    Inputs: - Locations of the specific vehicles
            - Vehicle specific work hours at the site (locations).
    Outputs: - Valhalla outputs
    To Do's: - Think about if a vehicle is more efficient to drive to the depot, or if the vehicle should be picked up
             from its starting location by a truck from the depot.
             - Look at outputs of Valhalla and inputs needed for tools
    """

    volume: float = Input(0.0)
    weight: float = Input(0.0)

    begin_location_gps: Tuple[float, float] = Input((0.0, 0.0))
    end_location_gps: Tuple[float, float] = Input((0.0, 0.0))

    routeDuration: float = Input(0.0)
    routeDistance: float = Input(0.0)

    needed_machinery: Machine = Input([])
    transporting_vehicle: Machine = Input(needed_machinery) # Almost always the needed_machinery, unless the needed_machinery is being transported by a truck or tractor

    max_speeds = {"Truck":80,
                  "Tractor":40,
                  "Crane":45,
                  "Excavator":40,
                  "Vehicle":100}

    # Dotted UML link “Get Fleet”: reference to the fleet used for this job
    fleet: Optional["Fleet"] = Input(None)

    # As long as Valhalla is not used, if a route is planned for a tractor, we will determine the routeDuration
    # using the computed routeDistance and an average speed for a tractor.
    @Attribute
    def Route(self) -> List[float]:
        self.routeDuration, self.routeDistance = Routing.ComputeRoute(self.begin_location_gps, self.end_location_gps, type(self.needed_machinery).__name__)
        return[self.routeDuration, self.routeDistance]


    # Using travel times from Valhalla together with work hours to determine total mission time with margins, idle times,
    # downtimes, maintenance, ..., which can be used later in the cost function evaluation
    @Attribute
    def TimeKeeper(self) -> float:
        routeDistance = self.Route[1] / 1000 # Route distance in km

        if str(type(self.needed_machinery).__name__) == "Truck" or str(type(self.needed_machinery).__name__) == "Vehicle":
            routeDuration = self.Route[0]
        else:
            max_speed = self.max_speeds[str(type(self.needed_machinery).__name__)] * 0.8 # Factor for not always driving at the maximum speeds due to rural roads, traffic, etc.
            routeDuration = routeDistance / max_speed * 3600
        return routeDuration

    # Using age and type of vehicle, a Pareto distribution can be used to predict if maintenance is required.
    # Expected inputs: decay factor (vehicle specific), age of vehicle and hours the vehicle is used.
    # Maintenance threshold is placed in the Pareto distribution for maintenance
    def MaintenancePredictor(self):
        raise NotImplementedError

    # Talk to Arjan -> External tool
    def CalculateNOX(self) -> float:
        raise NotImplementedError

    # Talk to Arjan -> External tool
    def CalculateCO2(self) -> float:
        raise NotImplementedError

    # Talk to Arjan, depends on work hours, employees, machinery, historical data
    def CalculateCost(self) -> float:
        raise NotImplementedError


class WorkJob(Base):
    """
    Description: Each type of work job is an instance of this class, which has its own deadline and specific machinery.
    Inputs: - Specific machinery and manhours
            - Job definition
    Outputs: -
    To Do's: - Think about man hours vs machine hours, multiple people per machine?
    """

    # Can be a list if needed_machinery is also a list (when multiple machine types are used for a specific job)
    man_hours: float = Input(0.0)

    deadline: str = Input("")

    # List specifying which type of machinery is required, order is not important
    needed_tools: str = Input("")
    needed_vehicles: str = Input("")

    # Resources actually assigned to this work job - Not in UML yet, maybe in extended UML?
    # TODO: Think about if it makes sense to have different tools and vehicles for a single job, important for workhour calculations
    assigned_tools: List["Tool"] = Input([])
    assigned_vehicles: List["Vehicle"] = Input([])

    # Dotted UML link “Get Fleet”, the work job gets the individual machine attributes (its age, location, etc.) for each
    # instance of the assigned machines from the fleet to determine the individual contributions to the overall cost
    # function of each mission iteration.
    fleet: Optional["Fleet"] = Input(None)

    # Using travel times from Valhalla together with work hours to determine total mission time with margins, idle times,
    # downtimes, maintenance, ..., which can be used later in the cost function evaluation
    @Attribute
    def TimeKeeper(self):
        job_duration = self.man_hours / (len(self.assigned_tools) + len(self.assigned_vehicles))

        return job_duration

    # Using age and type of vehicle, a Pareto distribution can be used to predict if maintenance is required.
    # Expected inputs: decay factor (vehicle specific), age of vehicle and hours the vehicle is used.
    # Maintenance threshold is placed in the Pareto distribution for maintenance
    def MaintenancePredictor(self):
        raise NotImplementedError

    # Talk to Arjan -> External tool
    def CalculateNOX(self) -> float:
        raise NotImplementedError

    # Talk to Arjan -> External tool
    def CalculateCO2(self) -> float:
        raise NotImplementedError

    # Talk to Arjan, depends on work hours, employees, machinery, historical data
    def CalculateCost(self) -> float:
        raise NotImplementedError

# ---------------------------------------------------------------------------
# Fleet and locations
# ---------------------------------------------------------------------------

class Fleet(Base):
    """Collection of machines available for missions.
       If time: Can also include fleet worth and budget in order to suggest acquisitions for reduction of costs, emissions, ...
       If all machines are fully utilized for the misison, it can suggest what machines to acquire and show where to store them.
       These machines can be rented, which integrates with FleetsOnline system to rent machines from each other. """
    budget: float = Input(0.0)
    fleetWorth: float = Input(0.0)

    # Can be used for output or visualization colors. Could also be used for regulations (such as different NOx emissions per sector)
    sector: str = Input("")

    # Composition: a fleet has many machines
    pumps: List["Pump"] = Input([])
    tools: List["Tool"] = Input([])
    tractors: List["Tractor"] = Input([])
    cranes: List["Crane"] = Input([])
    trucks: List["Truck"] = Input([])
    vehicles: List["Vehicle"] = Input([])

    class Depot(Base):
        """Depot with spatial dimensions and arranged machines.
        Center provided of rectangle, rotation of long side where 0 deg is horizontal """
        # Center of the depot in GPS coordinates (lat, lon)
        location: Tuple[float, float] = Input((0.0, 0.0))
        rotation: float = Input(0.0)  # 0 deg is long side horizontal
        # overall_dimensions: (long side, short side, height) in meters
        overall_dimensions: Tuple[float, float, float] = Input((0.0, 0.0, 0.0))
        # Machines currently relevant for this depot (you can fill this from Fleet)
        machines: List["Machine"] = Input([])
        # ------------------------------------------------------------------ #
        # Helper: distance in meters between two GPS points
        # ------------------------------------------------------------------ #
        def HaversineDistance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            """Great-circle distance between two GPS points in meters."""
            R = 6371000.0  # Earth radius [m]
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = (math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2) # https://en.wikipedia.org/wiki/Great-circle_distance
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)) # Angle at the center of the Earth between both
            return R * c
        # ------------------------------------------------------------------ #
        # Main function you need to implement
        # ------------------------------------------------------------------ #
        def DepotMachineAllocation(self, range_m: float = 500.0) -> Tuple[List["Machine"], List["Machine"]]:
            """Function looks at the depot location and any machine with a gps
            location within a certain radius (defined as 'range_m') gets
            assigned to within this depot. The remaining machines are 'road_parked'.

            range_m : Distance (m) outside the depot footprint at which machines still belong to this depot."""
            depot_lat, depot_lon = self.location
            # depot_radius = sqrt(L^2 + W^2) / 2  (from center to corner)
            long_side, short_side, _ = self.overall_dimensions
            depot_radius = 0.5 * math.sqrt(long_side**2 + short_side**2)
            critical_proximity = range_m + depot_radius

            depot_machines: List[Machine] = []
            road_parked_machines: List[Machine] = []

            for machine in self.machines:
                # Assume gps_location = (lat, lon)
                mach_lat, mach_lon = machine.gps_location

                distance = self.HaversineDistance(mach_lat, mach_lon, depot_lat, depot_lon)
                # if Machine - Depot location < critical_proximity: MachineLocation = depotLocation
                if distance <= critical_proximity:
                    machine.gps_location = (depot_lat, depot_lon)
                    depot_machines.append(machine)
                else:
                    road_parked_machines.append(machine)

            # keep only assigned machines in the depot list
            self.machines = depot_machines

            # depot_machines: Depot list/array with their machines
            # road_parked_machines: machines not assigned to depots
            return depot_machines, road_parked_machines

        @Attribute
        def contents(self) -> List["Machine"]:
            """Machines currently stored in this depot."""
            return self.machines

    def DepotMachineArrangement(self):
        """ This function is a Python file on its own, that uses an available algorithm to arrange the vehicle bounding
            boxes using the path width and turning radius in a 2D clever arrangement.
            TODO: Turn radius is already known per machine, the straight distance a vehicle needs to travel in a depot
            is computed in a loop, where a vehicle makes the turn around this turn radius from 0 to 90 degrees.
            If the block intersects with the neighbouring vehicle box, the amount the vehicle travels straight
            is increased by a small delta x, which will be used for the final path width."""
        raise NotImplementedError

if __name__ == "__main__":
    from parapy.gui import display

    # fleet = Fleet(location="NL", budget=1_000_000, machines=[])
    # app = MissionStrategyApp(
    #     needed_tools="shovels, pumps",
    #     needed_machinery="tractors, trucks",
    #     site_location="Some worksite",
    #     fleet=fleet,
    #     show_in_tree=True,  # optional Input if you add it later
    # )

    app = MissionStrategyApp()
    display(app)