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
from parapy.core.widgets import PyField
import copy
from MissionGenerator import generate_missions
from TestFunctions.TestLevel3.TimeKeeperTest import transport_job
from assets import *
from Warning import generate_warning
# from DepotArrangement import *
from Depot import Depot
from MapMaker import MapMaker
import Routing
from TrailerArrangement import Item, TrailerPackingVisualization, item_from_machine, TrailerAdapter
import requests
import json

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

    use_FleetsOnline_data = Input(False)

    possible_machinery = ["Crane", "Truck", "Vehicle", "Tool", "Tractor", "Machine", "Pump"]

    # Mission attributes
    needed_tools: str = Input("")
    needed_machinery: str = Input("Tractor")
    man_hours = Input(50)

    standard_locations = {"Eindhoven":(51.468288, 5.421365),
                          "Tilburg":(51.591433, 5.023739),
                          "Breda":(51.585288, 4.732775),
                          "Den Bosch":(51.585288, 4.732775),
                          "Waalwijk":(51.699574, 5.046544)
                        }

    site_dimensions: Tuple[float, float] = Input((0.0, 0.0)) # overall_dimensions: array[x', y'], always a rectangle, in its own reference system
    gps_location: Tuple[float, float, float] = Input((0.0, 0.0, 0.0)) # [x', y' and north-rotation]
    start_time = Input(datetime.datetime(2026, 5, 27, 8, 0))

    # Aggregations / associations
    mission_preferences: List[float] = Input([1.0, 1.0, 1.0], validator=all_is_number)  # List of weights for the different optimalisation goals
    strict_deadline: bool = Input(False)

    number_of_machines_per_type = {"Crane":0,
                                   "Tractor":0,
                                   "Truck":0,
                                   "Tool":0,
                                   "Pump":0}

    # Aggregations / associations
    fleet: Optional["Fleet"] = Input(None)
    machines: List[Machine] = Input([])
    trailers: List[Trailer] = Input([])
    depots: List[Depot] = Input([])

    work_job = Input()

    @action
    def GetFleetData(self):
        # API Authentication Header
        BASE_URL = "https://api.v2.deepdigital.org"
        token_response = requests.post(f"{BASE_URL}/oauth/token",
                                       data={"grant_type": "password", "username": "testing@fleets-online.com",
                                             "password": "WTuXQ8ZsK9#mT4qZ"})
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        standard_dimensions = {"Vrachtwagens ": [3, 2, 2],
                               "Tractor": [3, 2.5, 3],
                               "Kranen": [4, 2, 3.5],
                               "Aanhanger licht": [10, 2, 2],
                               "Aanhanger zwaar": [18, 2.5, 2.5]}

        # API Get POIs
        response = requests.get(
            f"{BASE_URL}/pois",
            headers=headers,
            params={
                "page": 1,
                "pageSize": 50,
                # "searchTerm": "depot",
                "archived": False,
                # "poiGroupId": 7,
            },
        )
        response.raise_for_status()
        pois = response.json()["value"]

        # Types: Aanhanger licht, Aanhanger zwaar, Kranen, Tractor, Vrachtwagens,
        assets = []
        assets.append(requests.get(f"{BASE_URL}/equipment", headers=headers, params={"pageSize": 100,
                                                                                  "activeOnly": True,
                                                                                     "searchTerm": "Tractor"}).json()["value"])
        assets.append(requests.get(f"{BASE_URL}/equipment", headers=headers, params={"pageSize": 100,
                                                                                     "activeOnly": True,
                                                                                     "searchTerm": "Kranen"}).json()["value"])
        assets.append(requests.get(f"{BASE_URL}/equipment", headers=headers, params={"pageSize": 100,
                                                                                     "activeOnly": True,
                                                                                     "searchTerm": "Vrachtwagens"}).json()["value"])
        assets.append(requests.get(f"{BASE_URL}/equipment", headers=headers, params={"pageSize": 100,
                                                                                     "activeOnly": True,
                                                                                     "searchTerm": "Aanhanger licht"}).json()["value"])
        assets.append(requests.get(f"{BASE_URL}/equipment", headers=headers, params={"pageSize": 100,
                                                                                     "activeOnly": True,
                                                                                     "searchTerm": "Aanhanger zwaar"}).json()["value"])
        data = [] # Keep track of all pois and assets to write to the json file
        for poi in pois: # Loop through the available points of interest
            if poi["address"] != None and poi["shapeData"] != None: # Check if the location address and shapeData is defined
                data.append({"type":"poi", "name": poi["name"], "gps_location": {"lat":poi["address"]["lat"], "lon":poi["address"]["lon"]}, "overall_dimensions":[poi["shapeData"]["radius"], 0.5* poi["shapeData"]["radius"], 10]})
            else:
                data.append({"type":"poi", "name": poi["name"], "gps_location": {"lat": self.standard_location[0], "lon": self.standard_location[1]}, "overall_dimensions":[50, 25, 10]})
        for asset_type in assets: # Loop through the available assets
            for asset in asset_type:
                if "Aanhanger" in asset["type"]["name"]:
                    data.append({"type": "asset", "id":asset["name"], "name": asset["type"]["name"], "build_year": asset["buildYear"],"gps_location": {"lat": self.standard_location[0], "lon": self.standard_location[1]},"overall_dimensions": standard_dimensions[asset["type"]["name"]], "color": "yellow"})
                else:
                    data.append({"type":"asset", "id":asset["name"], "name": asset["type"]["name"], "build_year":asset["buildYear"], "gps_location":{"lat": self.standard_location[0], "lon": self.standard_location[1]}, "overall_dimensions":standard_dimensions[asset["type"]["name"]], "color":"yellow", "fuel_type":asset["fuelType"]["name"]})

        # Write FleetsOnline data to FleetsOnlineData.json file
        with open('FleetsOnlineData.json', 'w') as f:
            json.dump(data, f, indent=4)
        return pois, assets

    @action()
    def JSONReader(self):
        if not self.needed_machinery in self.possible_machinery:
            generate_warning("Warning: Machinery cannot be read", "The selected machinery type can not be read, check for a typo or add this machine to the machinery types list. If doubts about the application, contact us.")
            return
        elif self.man_hours <= 0:
            generate_warning("Warning: Man hours invalid", "The selected number of man hours is equal to or smaller than zero. Please choose a positive number of man hours.")
            return

        if self.use_FleetsOnline_data:
            # self.GetFleetData()
            with open('FleetsOnlineData.json', 'r') as file:
                data = json.load(file)
        else:
            with open('CustomData.json', 'r') as file:
                data = json.load(file)

        for l in data:
            if l["type"] == "poi":
                if "Garage" in l["name"]:
                    depot = Depot()
                    depot.gps_location = (l["gps_location"]["lat"], l["gps_location"]["lon"])
                    depot.overall_dimensions = l["overall_dimensions"]
                    depot.name = l["name"]
                    self.depots.append(depot)
                elif "Boomrooierij" in l["name"]:
                    workjob = WorkJob()
                    if l["gps_location"] == None:
                        print("One of the worksites has no location data")
                        workjob.gps_location = (self.standard_locations["Breda"][0], self.standard_locations["Breda"][1])
                    else:
                        workjob.gps_location = (l["gps_location"]["lat"], l["gps_location"]["lon"])
                    workjob.needed_vehicles = self.needed_machinery
                    workjob.man_hours = self.man_hours
                    self.work_job = workjob
                    self.gps_location = workjob.gps_location
            elif l["type"] == "asset":
                if l["name"] == "Tractor":
                    m = Tractor()
                    m.machine_type = "Tractor"
                elif l["name"] == "Kranen":
                    m = Crane()
                    m.machine_type = "Crane"
                elif l["name"] == "Vrachtwagens" or l["name"] == "Vrachtwagens ": # To account for issue stemming from FleetsOnline API data
                    m = Truck()
                    m.machine_type = "Truck"
                elif "Aanhanger" in l["name"]:
                    m = Trailer()
                    m.overall_dimensions = l["overall_dimensions"]
                else:
                    m = Vehicle()
                try:
                    m.overall_dimensions = l['overall_dimensions']
                except:
                    m.overall_dimensions = (2, 2, 2)
                    generate_warning("Warning: Overall dimensions not specified", f"The overall dimensions were not provided for machine {l['id']}. Standard dimensions of [2 x 2 x 2] are used instead.")
                m.color = l['color']
                m.build_year = l['build_year']
                if m.build_year < 2020: m.build_year = 2020 # A limitation of the CO2 calculator of Fleets-Online
                m.color = l['color']
                m.gps_location = (l["gps_location"]["lat"], l["gps_location"]["lon"])
                if "Aanhanger" in l["name"]:
                    m.trailer_id = l["id"]
                    self.trailers.append(m)
                else:
                    m.machine_id = l["id"]
                    if "Diesel (fossiel)" in l["fuel_type"]: m.energy_source = "diesel-(fossiel)"
                    elif "Biodiesel" in l["fuel_type"]: m.energy_source = "biodiesel-(hvo)"
                    elif "Electric" in l["fuel_type"]: m.energy_source = "Electric"
                    m.emission_class = l["emission_class_version"]
                    m.consumption_per_hour = l["consumption_per_hour"]
                    self.machines.append(m)
                    self.number_of_machines_per_type[m.machine_type] += 1
                gps_check = Routing.gps_checker([m.gps_location[0], m.gps_location[1]])
                if gps_check == 2:generate_warning("Warning: Coordinate outside of intended region", "The provided coordinate(s) fall outside of the intended region. A bigger map of western Europe is used. For a clearer resolution, add a local map with corner coordinates in Routing.py.")
                elif gps_check == 3: generate_warning("Warning: Coordinate outside of intended region", "The provided coordinate(s) fall outside of available western Europe map. To use this route, add your own map for visibility with corner coordinates in Routing.py.")
                elif gps_check == 4: generate_warning("Warning: Coordinates not specified", "The coordinates are not specified. As such, the vehicle with GPS location (0.0, 0.0) will not be used. Please add vehicle coordinates or the coordinates of the depot where it is stored.")
            else:
                generate_warning("Warning: Unknown data entry", "The provided FleetsOnlineData.json data file contains an entry of an unknown type, this entry will be ignored.")
        asset_overall_dimensions = (0.0, 0.0, 0.0)
        if np.any(asset_overall_dimensions == 0): generate_warning("Warning: Dimension(s) missing", "Add the (non-zero) dimensions in x, y and z.")


    @Attribute
    def all_jobs(self) -> List[Base]:
        # Later done to put jobs next to each other for time planning and mission generation
        return [*self.transport_jobs, *self.work_jobs]

    @Attribute
    def number_of_machines_in_fleet(self) -> int:
        # Later done to sum the machines for strategy evaluation
        return len(self.fleet.machines) if self.fleet else 0

    @Attribute
    def standard_location(self):
        return self.standard_locations["Eindhoven"]

    all_generated_missions = Input([])

    winning_mission = Input(None)

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

        # Allocate machines to depots / road-side
        self.road_parked = self.AllocateMachines()

        # 1) MissionGenerator: generate all candidate missions (external module)
        self.all_generated_missions = generate_missions(
            self,
            MissionCls=Mission,
            TransportJobCls=TransportJob,
            VehicleCls=Vehicle,
            TrailerCls=Trailer,
        )

        if not self.all_generated_missions:
            raise RuntimeError("MissionGenerator produced no missions to evaluate.")

        # 2) MissionEvaluator: compute raw totals per mission
        self._mission_evaluator(self.all_generated_missions)

        # 3) MissionPicker: normalize, compute scalar, pick best
        winning_mission = self._mission_picker(self.all_generated_missions)

        toc = time.perf_counter()
        print(f"Took {toc - tic:0.4f} seconds")

        self.winning_mission = winning_mission

        return winning_mission

    def jobAnalyzer(self):
        '''
        This function determines the maximum number of machines that can work on a work site, based on the machine
        area and the site area, to not have an overcrowded work site.
        '''
        # TODO: Find better way to determine area_factor
        area_factor = 0.2
        job_machines_areas = []
        for m in self.machines:
            if m.machine_type == self.work_job.needed_machines:
                job_machines_areas.append(m.overall_dimensions[0] * m.overall_dimensions[1])

        job_area = self.site_dimensions[0] * self.site_dimensions[1]
        average_job_machine_area = np.mean(job_machines_areas)
        if average_job_machine_area == 0: average_job_machine_area = 1

        max_number_of_machines = area_factor * job_area / average_job_machine_area

        return max(1, max_number_of_machines)

    # ------------------------------------------------------------------
    # 2) MissionEvaluator
    # ------------------------------------------------------------------
    def _mission_evaluator(self, missions: List["MissionStrategyApp"]) -> None:
        """For each mission, sum maintenance, NOx, CO2, cost and time over all
        its transport and work jobs."""
        for m in missions:
            m.work_jobs[0].assigned_vehicles = m.machines
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
                total_mission_time += transport_job.routeDuration  # assume consistent unit

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

            m.mission_preferences = self.mission_preferences

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
                                timelines[index_content][1] += datetime.timedelta(minutes=transport_job.routeDuration)
                            except:
                                continue
                                # print("No index could be found for the vehicle " + str(
                            #     item.machine_id) + " inside trailer " + str(trailer.trailer_id))
            timelines[index][1] += datetime.timedelta(minutes=transport_job.routeDuration)
            vehicle.total_hours_used += transport_job.routeDuration / 60
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

    def PackagedVisualization(self):
        """Return the ParaPy model to visualize the packing. It visualizes the trailers, together with the packed tools, and vehicles
        * attachable + upright_only: solid purple .
        * if only upright_only (nonturnable): very light/baby blue
        * if only vehicle_attachable: pink
        * other tools: random blue shades
        * if vehicles: shades of yellow."""
        return TrailerPackingVisualization(
            items=self.items_to_pack,
            trailers=self.job_trailers,
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

    @action
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
        # Build the visualization model using your helper
        viz_model = self.PackagedVisualization()
        # Open in a new ParaPy window
        display(viz_model, mainloop=False)

    def AllocateMachines(self):
        machines = self.machines
        for machine in machines:
            machine.number_of_this_type = self.number_of_machines_per_type[machine.machine_type]
        trailers = self.trailers
        road_parked = []
        for depot in self.depots:
            depot.machines = machines
            depot.trailers = trailers
            _, road_parked = depot.DepotMachineAllocation()
            machines = road_parked
        return road_parked

    # TODO: Need to only take the machines that are allocated to this depot, but that can only be done once the fleet reader is set up.
    @action(button_label="DepotMaker")
    def DepotMaker(self):
        depots = []
        current_y = 0
        road_parked = self.AllocateMachines() # road_parked unused, still trigger AllocateMachines() to compute only once for entire MissionStrategyApp
        for i, d in enumerate(self.depots):
            d.gps_location=(0, current_y)
            current_y += 10 + d.overall_dimensions[1]
            depots.append(d)
        display(depots, mainloop=False)

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
        transport_jobs = self.winning_mission.transport_jobs
        work_jobs = self.winning_mission.work_jobs
        for job in transport_jobs:
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
            wj.gps_location for wj in work_jobs
        ]

        # Instantiate map object
        map_obj = MapMaker(
            routes=routes,
            depots=depot_points,
            work_sites=worksite_points,
        )

        # Display in a separate ParaPy viewer window
        from parapy.gui import display
        display(map_obj, mainloop=False)

    @Attribute
    def job_trailers(self) -> List[object]:
        job_trailers: List[object] = []
        for job in self.winning_mission.transport_jobs:
            veh = job.transporting_vehicle
            trailer_obj = getattr(veh, "contents", None)
            if trailer_obj is not None:
                name = f"{veh.machine_id}_trailer"
                job_trailers.append(TrailerAdapter(trailer_obj, name))
        return job_trailers

    @Attribute
    def items_to_pack(self) -> List[Item]:
        items: List[Item] = []
        for job in self.winning_mission.transport_jobs:
            veh = job.transporting_vehicle
            trailer_obj = getattr(veh, "contents", None)
            if trailer_obj is None:
                continue
            for machine in getattr(trailer_obj, "contents", []):
                if machine != None:
                    items.append(item_from_machine(machine))
        return items

    @Part
    def New_Vehicle(self):
        return Machine()

    @action(button_label="Add vehicle to JSON data file", label="Add vehicle")
    def AddVehicle(self):
        m = self.New_Vehicle
        with open("CustomData.json", "r") as f:
            data = json.load(f)
        data.append(
                {"type": "asset", "id": m.machine_id, "name": m.machine_type, "build_year": m.build_year,
                 "gps_location": {"lat": m.gps_location[0], "lon": m.gps_location[1]},
                 "overall_dimensions": m.overall_dimensions, "color": m.color,
                 "fuel_type": m.energy_source})
        # except:
        #     generate_warning("Missing or invalid data", "Please ensure all data slots in the new vehicle are filled in correctly before adding it to the JSON file.")
        print(data)
        # Write FleetsOnline data to FleetsOnlineData.json file
        with open('CustomData.json', 'w') as f:
            json.dump(data, f, indent=4)


class Mission(Base):
    transport_jobs: List["TransportJob"] = Input([])
    work_jobs: List["WorkJob"] = Input([])
    machines: List["Machine"] = Input([])
    mission_preferences = Input([1.0, 1.0, 1.0])

    mission_NOx = Input(0.0)
    mission_CO2 = Input(0.0)
    mission_cost = Input(0.0)

    normalized_time = Input(0.0)
    normalized_cost = Input(0.0)
    normalized_emissions = Input(0.0)

    def EvaluateCostFunction(self) -> float:
        """Dot product of normalized preferences and normalized objectives."""
        w_cost, w_time, w_emissions = self.mission_preferences
        return (w_cost * self.normalized_cost + w_time * self.normalized_time + w_emissions * self.normalized_emissions)



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
    # @Attribute
    # def Route(self) -> List[float]:
    #     self.routeDuration, self.routeDistance, _ = Routing.ComputeRoute(self.begin_location_gps, self.end_location_gps, type(self.needed_machinery).__name__)
    #     return[self.routeDuration, self.routeDistance]

    # Using travel times from Valhalla together with work hours to determine total mission time with margins, idle times,
    # downtimes, maintenance, ..., which can be used later in the cost function evaluation

    @Attribute
    def routeDuration(self) -> float:
        routeDistance = self.routeDistance / 1000 # Route distance in km

        if str(type(self.transporting_vehicle).__name__) == "Truck" or str(type(self.transporting_vehicle).__name__) == "Vehicle":
            routeDuration = self.routeDistance / 1000 / (self.max_speeds[str(type(self.transporting_vehicle).__name__)] * 0.8) * 3600
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
        self.transporting_vehicle.hours_used = self.routeDuration / 60
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

if __name__ == "__main__":
    from parapy.gui import display

    app = MissionStrategyApp()
    display(app)