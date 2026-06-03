# from _future_ import annotations
import math
import os
from typing import List, Tuple, Optional
import os
import sys
import subprocess
import datetime
import time
from parapy.gui import display
from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter
from parapy.core.validate import OneOf, all_is_number

from TestFunctions.TestLevel3.TimeKeeperTest import transport_job
from assets import *
# from DepotArrangement import *
from Depot import Depot
from MapMaker import MapMaker
import Routing
from TrailerArrangement import Item, TrailerPackingVisualization, item_from_machine, TrailerAdapter

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

    # TODO: UPDATE ONCE WE HAVE THE EXAMPLE JSON FILE!!

    possible_machinery = ["Crane", "Truck", "Vehicle", "Tool", "Tractor", "Machine", "Pump"]

    # Mission attributes
    needed_tools: str = Input("")
    needed_machinery: str = Input("")
    site_dimensions: Tuple[float, float] = Input((0.0, 0.0)) # overall_dimensions: array[x', y'], always a rectangle, in its own reference system
    gps_location: Tuple[float, float, float] = Input((0.0, 0.0, 0.0)) # [x', y' and north-rotation]
    start_time = Input(datetime.datetime(2026, 5, 27, 8, 0))

    road_parked = []

    # Aggregations / associations
    mission_preferences: List[float] = Input([1.0, 1.0, 1.0], validator=all_is_number)  # List of weights for the different optimalisation goals
    strict_deadline: bool = Input(False)

    # Aggregations / associations
    fleet: Optional["Fleet"] = Input(None)
    machines: List[Machine] = Input([])
    depots: List[Depot] = Input([])

    work_job = Input()

    def JSONReader(self):
        """"TODO:IF NOT GPS location provided: print 'no locations of machine X provided,, machine will be ignored for future analysis' """

        # Loop through assets
        asset_location = (0.0, 0.0)
        gps_check = Routing.gps_checker(asset_location)
        if gps_check == 2: generate_warning("Warning: Coordinate outside of intended region", "The provided coordinate(s) fall outside of the intended region. A bigger map of western Europe is used. For a clearer resolution, add a local map with corner coordinates in Routing.py.")
        elif gps_check == 3: generate_warning("Warning: Coordinate outside of intended region", "The provided coordinate(s) fall outside of available western Europe map. To use this route, add your own map for visibility with corner coordinates in Routing.py.")
        elif gps_check == 4: generate_warning("Warning: Coordinates not specified", "The coordinates are not specified. As such, the vehicle with GPS location (0.0, 0.0) will not be used. Please add vehicle coordinates or the coordinates of the depot where it is stored.")

        asset_overall_dimensions = (0.0, 0.0, 0.0)
        if np.any(asset_overall_dimensions == 0): generate_warning("Warning: Dimension(s) missing", "Add the (non-zero) dimensions in x, y and z.")

        # Loop through work jobs
        workjob_needed_machinery = "Bulldozer"
        if not workjob_needed_machinery in self.possible_machinery: generate_warning("Warning: Machinery cannot be read", "The selected machinery type can not be read, check for a typo or add this machine to the machinery types list. If doubts about the application, contact us.")


    @Attribute
    def all_jobs(self) -> List[Base]:
        # Later done to put jobs next to each other for time planning and mission generation
        return [*self.transport_jobs, *self.work_jobs]

    @Attribute
    def number_of_machines_in_fleet(self) -> int:
        # Later done to sum the machines for strategy evaluation
        return len(self.fleet.machines) if self.fleet else 0

    # Optional: declare these as Inputs so you can inspect them in the GUI
    mission_time: float = Input(0.0)
    mission_scalar: float = Input(0.0)

    normalized_cost: float = Input(0.0)
    normalized_time: float = Input(0.0)
    normalized_emissions: float = Input(0.0)

    winning_mission: Optional["MissionStrategyApp"] = Input(None)

    # --- existing methods like NormalizePreferences(), etc. ---

    @action
    def MissionIterator(self) -> "MissionStrategyApp":
        tic = time.perf_counter()
        """Top-level mission loop:
        1) Generate candidate missions
        2) Evaluate raw metrics per mission
        3) Normalize & pick mission with lowest scalar cost
        """
        # 0) Ensure preferences are normalized before evaluation
        self.NormalizePreferences()

        self.road_parked = self.AllocateMachines()

        # 1) MissionGenerator: generate all candidate missions
        all_generated_missions = self._mission_generator()
        exit()
        if not all_generated_missions:
            raise RuntimeError("MissionGenerator produced no missions to evaluate.")

        # 2) MissionEvaluator: compute raw totals per mission
        self._mission_evaluator(all_generated_missions)

        # 3) MissionPicker: normalize, compute scalar, pick best
        winning_mission = self._mission_picker(all_generated_missions)

        # Store and return for convenience
        self.winning_mission = winning_mission

        toc = time.perf_counter()
        print(f"Took {toc - tic:0.4f} seconds")
        return winning_mission

    # ------------------------------------------------------------------
    # 1) MissionGenerator
    # ------------------------------------------------------------------
    def _mission_generator(self) -> List["Mission"]:
        """Generate candidate missions (combinations of vehicles, transport
        jobs and work jobs).

        TODO:
        - Implement combinatorial search over fleet / jobs:
          * choose which trucks/tractors/etc. to assign
          * build different sequences of transport_jobs and work_jobs
          * apply feasibility filters (distance, deadlines, availability)
        - For now, we just evaluate the current mission as a single candidate.
        """
        # Placeholder: evaluate only the current configuration as 1 mission

        PreliminaryMatrix, objects = self.constructMatrix()
        filteredMatrix = self.filterMatrix(PreliminaryMatrix)
        routeMatrix = self.routeMatrix(filteredMatrix)
        print(filteredMatrix)
        viableMissions = self.viableMissionGenerator(routeMatrix, filteredMatrix, objects)


        mission_list = []

        mission = Mission(transport_jobs=[], work_jobs=[])

        return mission_list

    def jobAnalyzer(self):
        # TODO: Find better way to determine area_factor
        area_factor = 0.2
        job_machines_areas = []
        for m in self.machines:
            if m.machine_type == self.work_job.needed_machines:
                job_machines_areas.append(m.overall_dimensions[0] * m.overall_dimensions[1])

        job_area = self.site_dimensions[0] * self.site_dimensions[1]
        average_job_machine_area = np.mean(job_machines_areas)

        max_number_of_machines = area_factor * job_area / average_job_machine_area

        return max(1, max_number_of_machines)

    # Construct Matrix
    def constructMatrix(self):
        matrix_size = 1 + len(self.depots) + len(self.road_parked) # 1 Worksite + depots + road-side parked machines
        # locations = [self.site_location]
        objects = [self.work_job]
        objects.extend(self.depots)
        objects.extend(self.road_parked)
        # for depot in self.depots:
        #     locations.append(depot.location)
        # for machine in self.road_parked:
        #     locations.append(machine.gps_location)

        matrix = np.zeros((matrix_size, matrix_size), dtype=object)
        for i in range(matrix_size):
            for j in range(i):
                matrix[i][j] = [objects[i], objects[j]]
        return matrix, objects

    def filterMatrix(self, matrix):
        # TODO: ADD LOGIC SUCH THAT ONLY ONE TYPE OF MACHINE IS REQUIRED FOR EACH WORK_JOB, AND THE USER DECIDES IF STUFF IS DONE IN PARALLEL OR SERIES
        needed_machine = self.work_job.needed_machines
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[0] - 1):
                if matrix[i][j] != 0:
                    # Delete if Truck -> Truck
                    if type(matrix[i][j][0]).__name__ == type(matrix[i][j][1]).__name__ and type(matrix[i][j][0]).__name__ == "Truck":
                        matrix[i][j] = 0
                    # Delete if road-side Truck -> WorkJob
                    elif (type(matrix[i][j][0]).__name__ == "Truck" and type(matrix[i][j][1]).__name__ == "WorkJob") or (type(matrix[i][j][1]).__name__ == "Truck" and type(matrix[i][j][0]).__name__ == "WorkJob"):
                        if type(matrix[i][j][0]).__name__ == "Truck":
                            if matrix[i][j][0].contents != None:
                                if not needed_machine in [c.machine_type for c in matrix[i][j][0].contents.contents]:
                                    matrix[i][j] = 0
                            else: matrix[i][j] = 0
                        elif type(matrix[i][j][1]).__name__ == "Truck":
                            if matrix[i][j][1].contents != None:
                                if not needed_machine in [c.machine_type for c in matrix[i][j][0].contents.contents]:
                                    matrix[i][j] = 0
                            else: matrix[i][j] = 0
                    # Delete depot if needed machine not in Depot
                    elif type(matrix[i][j][0]).__name__ == "Depot":
                        if not needed_machine in matrix[i][j][0].available_machine_types:
                            matrix[i][j] = 0
                    # Delete depot if needed machine not in Depot
                    if matrix[i][j] != 0:
                        if type(matrix[i][j][1]).__name__ == "Depot":
                            if not needed_machine in matrix[i][j][1].available_machine_types:
                                matrix[i][j] = 0
                if matrix[i][j] != 0:
                    if i > 1 + len(self.depots):
                        # Delete if road parked machine not needed
                        if (type(matrix[i][j][0]).__name__ != needed_machine and type(matrix[i][j][0]).__name__ != "Truck") or (type(matrix[i][j][1]).__name__ != needed_machine and type(matrix[i][j][0]).__name__ != "Truck"):
                            matrix[i][j] = 0
        return matrix

    def routeMatrix(self, filteredMatrix):
        routeMatrix = np.zeros((filteredMatrix.shape[0], filteredMatrix.shape[1]), dtype=object)

        for i in range(filteredMatrix.shape[0]):
            for j in range(filteredMatrix.shape[1] - 1):
                if filteredMatrix[i][j] != 0:
                    routeDuration, routeDistance, _ = Routing.ComputeRoute(filteredMatrix[i][j][0].gps_location, filteredMatrix[i][j][1].gps_location,
                                         machine_type="Truck")
                    routeMatrix[i][j] = [routeDuration, routeDistance]
        return

    def viableMissionGenerator(self, routeMatrix, filteredMatrix, objects):
        max_worksite_machines = self.jobAnalyzer()
        possibleMachines = []
        for m in self.machines:
            if m.machine_type == self.needed_machinery:
                possibleMachines.append(m)
        max_number_of_machines = min(max_worksite_machines, len(possibleMachines))
        max_number_of_machines = 2

        # Get truck locations
        # truck_locations = []
        # for object in objects:
        #     if type(object).__name__ == "Depot":
        #         if "Truck" in object.available_machine_types:
        #             truck_locations.append(object)

        # Logic for now: only use 1 machine, or when deadline is set use the minimal amount of machines that will meet the deadlines
        # for n in range(2, max_number_of_machines + 1):
        possibleMissions = []
        needed_machine = self.work_job.needed_machines
        possibleRoutes = []
        for i in range(1, filteredMatrix.shape[0]):
            for j in range(1, filteredMatrix.shape[0] - 1):
                if filteredMatrix[i][j] != 0:
                    # Needed machine directly to work site ('direct route')
                    if type(filteredMatrix[i][j][0]).__name__ == "Depot":
                        if needed_machine in filteredMatrix[i][j][0].available_machine_types:
                             possibleRoutes.append([i, 1])
                    elif type(filteredMatrix[i][j][1]).__name__ == "Depot":
                        if needed_machine in filteredMatrix[i][j][1].available_machine_types:
                             possibleRoutes.append([i, 1])
                    elif filteredMatrix[i][j][0].machine_type == needed_machine:
                        possibleRoutes.append([i, 1])
                    elif filteredMatrix[i][j][1].machine_type == needed_machine:
                        possibleRoutes.append([i, 1])
        print(possibleRoutes)

        return possibleMissions


    # ------------------------------------------------------------------
    # 2) MissionEvaluator
    # ------------------------------------------------------------------
    def _mission_evaluator(self, missions: List["MissionStrategyApp"]) -> None:
        """For each mission, sum maintenance, NOx, CO2, cost and time over all
        its transport and work jobs."""
        for m in missions:
            total_mission_NOx = 0.0
            total_mission_CO2 = 0.0
            total_mission_cost = 0.0
            total_mission_time = 0.0

            transport_jobs = m.transport_jobs
            work_jobs = m.work_jobs

            # Transport jobs: assume TimeKeeper is mission time contribution
            for transport_job in transport_jobs:
                total_mission_NOx += transport_job.job_NOx
                total_mission_CO2 += transport_job.job_CO2
                total_mission_cost += transport_job.job_cost
                total_mission_time += transport_job.TimeKeeper  # assume consistent unit

            # Work jobs: job_* are per tool/vehicle lists, TimeKeeper is duration
            for work_job in work_jobs:
                total_mission_NOx += sum(work_job.job_NOx)
                total_mission_CO2 += sum(work_job.job_CO2)
                total_mission_cost += sum(work_job.job_cost)
                total_mission_time += work_job.TimeKeeper

            m.mission_NOx = total_mission_NOx
            m.mission_CO2 = total_mission_CO2
            m.mission_cost = total_mission_cost
            m.mission_time = total_mission_time

    # ------------------------------------------------------------------
    # 3) MissionPicker
    # ------------------------------------------------------------------
    def _mission_picker(self, missions: List["MissionStrategyApp"]) -> "MissionStrategyApp":
        """Normalize cost/time/emissions across missions, evaluate scalar
        score for each mission and return the best one."""
        # Collect raw values across all missions
        costs = [m.mission_cost for m in missions]
        times = [m.mission_time for m in missions]
        CO2s = [m.mission_CO2 for m in missions]
        NOxs = [m.mission_NOx for m in missions]

        min_cost, max_cost = min(costs), max(costs)
        min_time, max_time = min(times), max(times)
        min_CO2, max_CO2 = min(CO2s), max(CO2s)
        min_NOx, max_NOx = min(NOxs), max(NOxs)

        alpha = 0.25  # weight CO2 vs NOx inside "emissions" metric

        for m in missions:
            # Normalized cost
            m.normalized_cost = ((m.mission_cost - min_cost) / (max_cost - min_cost)
                if (max_cost - min_cost) != 0 else 0.0)

            # Normalized time
            m.normalized_time = ((m.mission_time - min_time) / (max_time - min_time)
                if (max_time - min_time) != 0 else 0.0)

            # Normalized emissions (CO2 + NOx combined)
            norm_CO2 = ((m.mission_CO2 - min_CO2) / (max_CO2 - min_CO2)
                if (max_CO2 - min_CO2) != 0 else 0.0)
            norm_NOx = ((m.mission_NOx - min_NOx) / (max_NOx - min_NOx)
                if (max_NOx - min_NOx) != 0 else 0.0)
            m.normalized_emissions = alpha * norm_CO2 + (1.0 - alpha) * norm_NOx

            # Scalar cost function for this mission
            m.mission_scalar = m.EvaluateCostFunction()

        # Pick the mission with the lowest scalar score
        winning_mission = min(missions, key=lambda mm: mm.mission_scalar)
        return winning_mission

    # Define (normalized) preferences function
    @action()
    def NormalizePreferences(self) -> List[float]:
        """Normalize mission_preferences:
        - Negative values => 0 (user really doesn't want that objective)
        - Non-negative values are scaled so sum == 1
        - If all are <= 0, fall back to equal weights.
        - Cost, Emmisions , Time
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

    # Function that builds the final mission planning
    @action()
    def Planner(self):
        timelines = []
        for work_job in self.work_jobs:
            for vehicle in work_job.assigned_vehicles:
                timelines.append([vehicle.machine_id, self.start_time])
        timelines = np.array(timelines)
        # print("Starting point timeline:")
        # print(timelines)
        for transport_job in self.transport_jobs:
            vehicle = transport_job.transporting_vehicle
            try:
                index = np.where(timelines[:, 0] == vehicle.machine_id)[0][0]
            except:
                continue
                # print("No index could be found for this vehicle: " + str(vehicle.machine_id))
            if type(vehicle).__name__ == "Truck":
                trailer = vehicle.contents
                if trailer != None:
                    for item in trailer.contents:
                        if item != None:
                            try:
                                index_content = np.where(timelines[:, 0] == item.machine_id)[0][0]
                                timelines[index_content][1] += datetime.timedelta(minutes=transport_job.TimeKeeper)
                            except:
                                continue
                                # print("No index could be found for the vehicle " + str(
                            #     item.machine_id) + " inside trailer " + str(trailer.trailer_id))
            timelines[index][1] += datetime.timedelta(minutes=transport_job.TimeKeeper)
            vehicle.total_hours_used += transport_job.TimeKeeper / 60
        # print("Timeline after transport jobs:")
        # print(timelines)
        for work_job in self.work_jobs:
            vehicles = work_job.assigned_vehicles
            for vehicle in vehicles:
                try:
                    index = np.where(timelines[:, 0] == vehicle.machine_id)[0][0]
                except:
                    continue
                    # print("No index could be found for this vehicle: " + str(vehicle.machine_id))
                timelines[index][1] += datetime.timedelta(hours=(work_job.man_hours / len(vehicles)))
                vehicle.total_hours_used = work_job.man_hours / len(vehicles)
            # print("Timeline after work jobs:")
            print(timelines)
    # ------------------------------------------------------------------
    # Cost function
    # ------------------------------------------------------------------
    def EvaluateCostFunction(self) -> float:
        """Dot product of normalized preferences and normalized objectives."""
        w_cost, w_time, w_emissions = self.mission_preferences
        return (w_cost * self.normalized_cost + w_time * self.normalized_time + w_emissions * self.normalized_emissions)

    def PackagedVisualization(self):
        """Return the ParaPy model to visualize the packing. It visualizes the trailers, together with the packed tools, and vehicles
        * attachable + upright_only: solid purple .
        * if only upright_only (nonturnable): very light/baby blue
        * if only vehicle_attachable: pink
        * other tools: random blue shades
        * if vehicles: shades of yellow."""
        return TrailerPackingVisualization(
            items=self.items_to_pack,
            trailers=self.trailers,
        )


    # -- Export geometry function --

    # With the final chosen strategy, arrangement is conducted for the depots and containers. Vehicles are only
    # 2D [x, y] and tools can also be stacked in 3D [x, y, z] in boxes. A new Python file will perform the 2D and
    # 3D arrangement logic.
    # To do: work out, also include arrangement logic and rules (turn radius, path widths, stacking logic, ...)

    # ---------------------------------------------------------------------------------------------------------------------------
    # --- ACTIONS / BUTTONS --
    # --------------------------------------------------------------------------------------------------------------------------
    @action(button_label="Generate Strategies")
    def generate_strategies(self):
        raise NotImplementedError

    @action(button_label="Export Results")
    def export_results(self):
        # Export JSON results
        raise NotImplementedError

    @action(button_label="Trailer Arrangements")
    def trailer_arrangement(self):
        """Open a ParaPy viewer window with the trailer packing visualization
        for this mission.

        Relies on:
            - self.items_to_pack: List[Item]
            - self.trailers: list of trailer-like objects
              (each with carrying_bounding_box and has_ceiling).
        """
        # Basic sanity checks, helpful during development
        if not hasattr(self, "items_to_pack"):
            raise RuntimeError(
                "MissionStrategyApp has no 'items_to_pack' attribute. "
                "Define it as an Input or Attribute that returns List[Item].")
        if not hasattr(self, "trailers"):
            raise RuntimeError(
                "MissionStrategyApp has no 'trailers' attribute. "
                "Define it as an Input or Attribute that returns a list of trailers.")
        # Build the visualization model using your helper
        viz_model = self.PackagedVisualization()
        # Open in a new ParaPy window
        display(viz_model)

    def AllocateMachines(self):
        machines = self.machines
        road_parked = []
        for depot in self.depots:
            depot.machines = machines
            _, road_parked = depot.DepotMachineAllocation()
            machines = road_parked
        return road_parked

    # TODO: Need to only take the machines that are allocated to this depot, but that can only be done once the fleet reader is set up.
    @action(button_label="DepotMaker")
    def DepotMaker(self):
        depots = []
        current_y = 0
        for i, d in enumerate(self.depots):
            d.location=(0, current_y)
            current_y += 10 + d.overall_dimensions[1]
            depots.append(d)
        display(depots)

    @action(button_label="MapMaker")
    def MapMaker(self):
        """
        Open a map showing:
        - all transport job routes,
        - all depots as black cubes,
        - all work sites as purple cubes.
        """

        # --- build route list: (start, end, machine_type) ---
        routes = []
        for job in self.transport_jobs:
            start = job.begin_location_gps
            end = job.end_location_gps
            machine_type = type(job.transporting_vehicle).__name__
            routes.append((start, end, machine_type))

        # --- depot GPS points ---
        depot_points: List[Tuple[float, float]] = []
        for dep in self.depots:
            try:
                depot_points.append(dep.gps_location)
            except AttributeError:
                print(f"[MapMaker] Depot {dep} has no 'location_gps' attribute; skipping.")

        # --- work site GPS points (one per work job) ---
        worksite_points: List[Tuple[float, float]] = [
            wj.gps_location for wj in self.work_jobs
        ]

        # Instantiate map object
        map_obj = MapMaker(
            routes=routes,
            depots=depot_points,
            work_sites=worksite_points,
        )

        # Display in a separate ParaPy viewer window
        from parapy.gui import display
        display(map_obj)
    # Define (normalized) preferences function
    @Attribute
    def trailers(self) -> List[object]:
        job_trailers: List[object] = []
        for job in self.transport_jobs:
            veh = job.transporting_vehicle
            trailer_obj = getattr(veh, "contents", None)
            if trailer_obj is not None:
                name = f"{veh.machine_id}_trailer"
                job_trailers.append(TrailerAdapter(trailer_obj, name))
        return job_trailers

    @Attribute
    def items_to_pack(self) -> List[Item]:
        items: List[Item] = []
        for job in self.transport_jobs:
            veh = job.transporting_vehicle
            trailer_obj = getattr(veh, "contents", None)
            if trailer_obj is None:
                continue
            for machine in getattr(trailer_obj, "contents", []):
                if machine != None:
                    items.append(item_from_machine(machine))
        return items

class Mission(Base):
    transport_jobs: List["TransportJob"] = Input([])
    work_jobs: List["WorkJob"] = Input([])

    mission_NOx = Input(0.0)
    mission_CO2 = Input(0.0)
    mission_cost = Input(0.0)

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
        self.routeDuration, self.routeDistance, _ = Routing.ComputeRoute(self.begin_location_gps, self.end_location_gps, type(self.needed_machinery).__name__)
        return[self.routeDuration, self.routeDistance]

    # Using travel times from Valhalla together with work hours to determine total mission time with margins, idle times,
    # downtimes, maintenance, ..., which can be used later in the cost function evaluation
    @Attribute
    def TimeKeeper(self) -> float:
        routeDistance = self.Route[1] / 1000 # Route distance in km

        if str(type(self.transporting_vehicle).__name__) == "Truck" or str(type(self.transporting_vehicle).__name__) == "Vehicle":
            routeDuration = self.Route[0]
        else:
            max_speed = self.max_speeds[str(type(self.transporting_vehicle).__name__)] * 0.8 # Factor for not always driving at the maximum speeds due to rural roads, traffic, etc.
            routeDuration = routeDistance / max_speed * 3600
        routeDuration = round(routeDuration/60)
        return routeDuration

    # Using age and type of vehicle, a Pareto distribution can be used to predict if maintenance is required.
    # Expected inputs: decay factor (vehicle specific), age of vehicle and hours the vehicle is used.
    # Maintenance threshold is placed in the Pareto distribution for maintenance
    # @Attribute
    # def job_maintenance(self):
    #     maintenance = self.transporting_vehicle.CalculateIndividualMaintenance()
    #     return maintenance

    # Talk to Arjan -> External tool
    @Attribute
    def job_NOx(self) -> float:
        NOx = self.transporting_vehicle.individualNOX
        return NOx

    # Talk to Arjan -> External tool
    @Attribute
    def job_CO2(self) -> float:
        CO2 = self.transporting_vehicle.individualCO2
        return CO2

    # Talk to Arjan, depends on work hours, employees, machinery, historical data
    @Attribute
    def job_cost(self) -> float:
        self.transporting_vehicle.hours_used = self.TimeKeeper / 60
        cost = self.transporting_vehicle.individualCost
        return cost

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
    gps_location: Tuple[float, float] = Input((0.0, 0.0))
    deadline: str = Input("")

    # List specifying which type of machinery is required, order is not important
    needed_tools: str = Input("")
    needed_vehicles: str = Input("")
    needed_machines = needed_vehicles
    # needed_machines = [needed_tools, needed_vehicles]

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
    # @Attribute
    # def job_maintenance(self):
    #     maintenance_list = []
    #     for tool in self.assigned_tools:
    #         maintenance = tool.CalculateIndividualMaintenance()
    #         maintenance_list.append(maintenance)
    #     for vehicle in self.assigned_vehicles:
    #         maintenance = vehicle.CalculateIndividualMaintenance()
    #         maintenance_list.append(maintenance)
    #
    #     return maintenance_list

    # Talk to Arjan -> External tool
    @Attribute
    def job_NOx(self) -> float:
        NOx_list = []
        for tool in self.assigned_tools:
            NOx = tool.individualNOX
            NOx_list.append(NOx)
        for vehicle in self.assigned_vehicles:
            NOx = vehicle.individualNOX
            NOx_list.append(NOx)

        return NOx_list

    # Talk to Arjan -> External tool
    @Attribute
    def job_CO2(self) -> float:
        CO2_list = []
        for tool in self.assigned_tools:
            CO2 = tool.individualCO2
            CO2_list.append(CO2)
        for vehicle in self.assigned_vehicles:
            CO2 = vehicle.individualCO2
            CO2_list.append(CO2)

        return CO2_list

    # Talk to Arjan, depends on work hours, employees, machinery, historical data
    @Attribute
    def job_cost(self) -> float:
        cost_list = []
        for tool in self.assigned_tools:
            tool.hours_used = self.man_hours / len(self.assigned_tools)
            cost = tool.individualCost
            cost_list.append(cost)
        for vehicle in self.assigned_vehicles:
            vehicle.hours_used = self.man_hours / len(self.assigned_vehicles)
            cost = vehicle.individualCost
            cost_list.append(cost)

        return cost_list
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
    trailers: List["Trailer"] = Input([])

def generate_warning(warning_header, msg):
    """Generate a warning dialog box, wait for user confirmation and close it.

    Parameters
    ----------
    warning_header : str
        String shown in the window header.
    msg : str
        String shown in the body of the message window

    Returns
    -------
    None.

    """
    # tkinter is a built-in GUI library in Python
    from tkinter import Tk, messagebox

    # initialization
    window = Tk()
    window.withdraw()

    # generates message box and waits for user to close it
    messagebox.showwarning(warning_header, msg)

    # close the message window, terminate the associated process
    window.deiconify()
    window.destroy()
    window.quit()

if __name__ == "__main__":
    from parapy.gui import display

    # Trailer 1: shorter but higher; mixed cargo
    trailer1 = Trailer(
        overall_dimensions=[4.5, 2.5, 3.5],  # L, W, H
        mass=2500,
        contents=[
            # Big tractor, floor-only, will behave as vehicle
            Tractor(
                overall_dimensions=[4.5, 2.4, 3],
                mass=16000,
                consumption_per_hour=18,
                worth=2500000,
                age=5,
                machine_id="Tractor_A",
            ),
            # Medium tractor
            Tractor(
                overall_dimensions=[4.0, 2.2, 2.8],
                mass=14000,
                consumption_per_hour=16,
                worth=2200000,
                age=8,
                machine_id="Tractor_B",
            ),
            # Generic tool as cargo, more cubic
            Tool(
                overall_dimensions=[2.0, 1.8, 1.6],
                mass=3000,
                consumption_per_hour=5,
                worth=80000,
                age=3,
                machine_id="Tool_A",
            ),
        ],
    )

    # Trailer 2: longer but a bit lower; several smaller tools & a compact tractor
    trailer2 = Trailer(
        overall_dimensions=[14, 2.6, 3.0],
        mass=2800,
        contents=[
            # Compact tractor
            Tractor(
                overall_dimensions=[3.5, 2.1, 2.6],
                mass=12000,
                consumption_per_hour=14,
                worth=1800000,
                age=4,
                machine_id="Tractor_C",
            ),
            # Three tools with different proportions so rotations matter
            Tool(
                overall_dimensions=[3.0, 1.5, 1.2],  # long & flat
                mass=2500,
                consumption_per_hour=4,
                worth=60000,
                age=6,
                machine_id="Tool_B",
            ),
            Tool(
                overall_dimensions=[1.8, 1.8, 2.0],  # more cube-like
                mass=2200,
                consumption_per_hour=3,
                worth=55000,
                age=2,
                machine_id="Tool_C",
            ),
            Tool(
                overall_dimensions=[2.2, 1.0, 1.8],  # tall & narrow
                mass=2000,
                consumption_per_hour=3,
                worth=50000,
                age=1,
                machine_id="Tool_D",
            ),
        ],
    )

    # app = MissionStrategyApp(site_location=(51.416232, 5.507185, 0), transport_jobs=[TransportJob(
    #     needed_machinery=[Tractor(gps_location=(51.584217, 5.101924), overall_dimensions=[4,2, 2.5], mass=15000, consumption_per_hour=15, worth=2000000,
    #                                            machine_id="Tractor_in_trailer")],
    #     transporting_vehicle=Truck(gps_location=(51.584217, 5.101924), overall_dimensions=[4, 2, 3.5], consumption_per_hour=30, mass=10000, worth=500000,
    #                                age=1, machine_id="Truck_1",
    #                                contents=trailer1),
    #     begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         needed_machinery=[Pump(machine_id="Pump_1", gps_location=(51.584217, 5.101924), vehicle_attachable=True, overall_dimensions=[2, 2, 2]), Pump(machine_id="Pump_2", gps_location=(51.584217, 5.101924), vehicle_attachable=True, overall_dimensions=[1.5, 1.5, 1.5]), Tool(machine_id="Tool_1", gps_location=(51.584217, 5.101924), vehicle_attachable=True, overall_dimensions=[4,1.5,1.5]), Tool(machine_id="Tool_2", gps_location=(51.584217, 5.101924), vehicle_attachable=True, overall_dimensions=[3,2,2]), Tool(machine_id="Tool_3", gps_location=(51.584217, 5.101924), vehicle_attachable=False, overall_dimensions=[5,5,2])],
    #         transporting_vehicle=Truck(gps_location=(51.584217, 5.101924), overall_dimensions=[4, 2, 3.5], consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_1",
    #                                    contents=Trailer(overall_dimensions=[12, 2, 3], mass=2000, contents=[
    #                                        Tractor(overall_dimensions=[3,2,3], mass=15000, consumption_per_hour=15, worth=2000000,
    #                                                machine_id="Tractor_in_trailer")])),
    #         begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.720407, 5.269097), overall_dimensions=[4, 2, 3.5],
    #                                    consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_4",
    #                                    contents=trailer2),
    #         begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.584217, 5.101924), overall_dimensions=[4, 2, 3.5], consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_5",
    #                                    contents=Trailer(overall_dimensions=[16, 2, 3], mass=2000)),
    #         begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.584217, 5.101924), overall_dimensions=[4, 2, 3.5],
    #                                    consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_7",
    #                                    contents=Trailer(overall_dimensions=[14, 2, 3], mass=2000)),
    #         begin_location_gps=[51.625882, 4.768424], end_location_gps=[51.584217, 5.101924]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.584217, 5.101924), overall_dimensions=[4, 2, 3.5], consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_7",
    #                                    contents=Trailer(overall_dimensions=[14, 2, 3], mass=2000)),
    #         begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.584217, 5.101924), overall_dimensions=[4, 2, 3.5], consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_8",
    #                                    contents=Trailer(overall_dimensions=[16, 2, 3], mass=2000)),
    #         begin_location_gps=[51.720407, 5.269097], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.720407, 5.269097), overall_dimensions=[4, 2, 3.5],
    #                                    consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_9",
    #                                    contents=Trailer(overall_dimensions=[14, 2, 3], mass=2000)),
    #         begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Truck(gps_location=(51.720407, 5.269097), overall_dimensions=[4, 2, 3.5],
    #                                    consumption_per_hour=30, mass=10000,
    #                                    worth=500000,
    #                                    age=1, machine_id="Truck_10",
    #                                    contents=Trailer(overall_dimensions=[16, 2, 3], mass=2000)),
    #         begin_location_gps=[51.584217, 5.101924], end_location_gps=[51.416232, 5.507185]),
    #                                                                                  TransportJob(
    #                                                                                      transporting_vehicle=Tractor(
    #                                                                                          gps_location=(51.584217, 5.101924),
    #                                                                                          overall_dimensions=[4, 3,
    #                                                                                                              3],
    #                                                                                          consumption_per_hour=15,
    #                                                                                          worth=1000000, age=30,
    #                                                                                          machine_id="Tractor_1"),
    #                                                                                      begin_location_gps=[51.584217,
    #                                                                                                          5.101924],
    #                                                                                      end_location_gps=[51.416232,
    #                                                                                                        5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Tractor(
    #             gps_location=(51.519917, 4.774090),
    #             overall_dimensions=[6, 4,
    #                                 4],
    #             consumption_per_hour=15,
    #             worth=1000000, age=30,
    #             machine_id="Crane_1"),
    #         begin_location_gps=[51.584217,
    #                             5.101924],
    #         end_location_gps=[51.416232,
    #                           5.507185]),
    #     TransportJob(
    #         transporting_vehicle=Crane(
    #             gps_location=(51.584217, 5.101924),
    #             overall_dimensions=[6, 4,
    #                                 4],
    #             consumption_per_hour=15,
    #             worth=1000000, age=30,
    #             machine_id="Crane_1"),
    #         begin_location_gps=[51.584217,
    #                             5.101924],
    #         end_location_gps=[51.416232,
    #                           5.507185]),
    #                                                                                  TransportJob(
    #                                                                                      transporting_vehicle=Truck(
    #                                                                                          gps_location=(51.584217, 5.101924),
    #                                                                                          overall_dimensions=[4, 2,
    #                                                                                                              2],
    #                                                                                          consumption_per_hour=30,
    #                                                                                          mass=10000, worth=500000,
    #                                                                                          age=10,
    #                                                                                          machine_id="Truck_2"),
    #                                                                                      begin_location_gps=[51.587863,
    #                                                                                                          5.099568],
    #                                                                                      end_location_gps=[51.416232,
    #                                                                                                        5.507185])],
    #                          work_jobs=[WorkJob(location=(51.416232, 5.507185), assigned_vehicles=[
    #                              Truck(mass=10000, consumption_per_hour=30, worth=500000, age=2, machine_id="Truck_1"),
    #                              Truck(mass=10000, consumption_per_hour=30, worth=500000, age=2, machine_id="Truck_2"),
    #                              Tractor(mass=10000, consumption_per_hour=15, worth=1000000, age=30,
    #                                      machine_id="Tractor_1"),
    #                              Tractor(mass=15000, consumption_per_hour=15, worth=2000000, age=30,
    #                                      machine_id="Tractor_in_trailer")], man_hours=20)],
    #                          depots=[Depot(location=(51.586911, 5.101759)),
    #                                  Depot(location=(51.720407, 5.269097))])k

    # app2 = MissionStrategyApp(work_job = WorkJob(needed_vehicles = "Tractor", gps_location=(51.416232, 5.507185)),
    #                           depots=[Depot(gps_location=(51.584217, 5.101924)), Depot(gps_location=(51.720407, 5.269097))],
    #                           gps_location = (51.416232, 5.507185),
    #                           machines=[Tractor(gps_location=(51.624520, 4.769122), machine_type = "Tractor"), Truck(gps_location=(51.720407, 5.269097), machine_type = "Truck", contents=Trailer(contents=[Tractor(machine_type = "Tractor", gps_location=(51.720407, 5.269097))])), Crane(gps_location=(51.720407, 5.269097), machine_type="Crane"), Crane(gps_location=(51.586911, 5.101759), machine_type="Crane")])

    # app3 = MissionStrategyApp(work_job = WorkJob())

    app4 = MissionStrategyApp(work_job = WorkJob(needed_vehicles = "Tractor", gps_location=(51.416232, 5.507185)),
                              depots=[Depot(gps_location=(51.584217, 5.101924)), Depot(gps_location=(51.720407, 5.269097)), Depot(gps_location=(50, 4))],
                              gps_location = (51.416232, 5.507185),
                              machines=[Truck(gps_location=(50, 4.5), machine_type="Truck"),
                                        Crane(gps_location=(51.584217, 5.101924), machine_type="Crane"),
                                        Tractor(gps_location=(50, 3), machine_type="Tractor"),
                                        Tractor(gps_location=(51.720407, 5.269097), machine_type="Tractor"),
                                        Tractor(gps_location=(50,4), machine_type="Tractor"),
                                        Truck(gps_location=(49, 4), machine_type="Truck")])

    display(app4)