from __future__ import annotations

import datetime
import json
import math
import os
import subprocess
import sys
import time
from typing import List, Tuple, Optional

import numpy as np
import requests
from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.core.validate import OneOf, all_is_number
from parapy.core.widgets import PyField, CheckBox, TextField
from parapy.exchange import STEPWriter
from parapy.geom import Box
from parapy.gui import display

from Depot import Depot
from MapMaker import MapMaker, FleetMapMaker
from MissionGenerator import (
    generate_missions,
    deadline_restricted_mission_generator,
)
from TestFunctions.TestLevel3.TimeKeeperTest import transport_job
from TrailerArrangement import (
    Item,
    TrailerPackingVisualization,
    item_from_machine,
    TrailerAdapter,
)
from Warning import generate_warning
import Routing
from assets import (
    Machine,
    Trailer,
    Tractor,
    Crane,
    Truck,
    Tool,
    Pump,
    Vehicle,
)
import PDFMaker

maindir = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Top-level application
# ---------------------------------------------------------------------------


class MissionStrategyApp(Base):
    """
    Description:
        The top-level class that uses the fleet, jobs and the mission
        profiles to create the final strategy.

    Inputs:
        - JSON file of the fleet with its availability, location, etc.
        - Mission preferences (Strict deadlines or not)

    Outputs:
        - The chosen strategy, with the specific vehicles that will
          do their action at specified jobs at a certain time.
        - Arrangement geometry in 2D (depots) and 3D (storage)
        - The routes of the final strategy
        - Visualization output of the arrangement
        - PDF summary of the chosen strategy

    To Do's:
        - make preference interface (action with standard preference
          with easy names such as greedy or hurry), also the option to
          define own preferences and normalize within function.
        - If time: combine multiple work jobs into one mission.
        - Maximum vehicles in worksite is area worksite divided by
          area vehicle times a factor.
    """

    # Aggregations / associations
    mission_preferences: List[float] = Input(
        [1.0, 1.0, 1.0],
        label="Mission Preferences (cost, time, emissions)",
        validator=all_is_number,
    )  # List of weights for the different optimisation goals

    possible_machinery = [
        "Crane",
        "Truck",
        "Vehicle",
        "Tool",
        "Tractor",
        "Machine",
        "Pump",
    ]
    # Mission attributes
    # needed_tools: str = Input("", widget=TextField(autocompute=True))
    needed_machinery: str = Input(
        "Tractor",
        widget=TextField(
            autocompute=True,
            background_color=lambda self: (
                "Red"
                if self.needed_machinery not in self.possible_machinery
                   and self.needed_machinery != ""
                else "White"
            ),
        ),
        label="Needed Machinery"
    )
    man_hours = Input(
        50,
        widget=PyField(
            autocompute=True,
            background_color=lambda self: (
                "Red" if self.man_hours == 0 else "White"
            ),
        ),
        label="Man Hours"
    )
    # default: no deadline restriction
    strict_deadline: bool = Input(False, widget=CheckBox(), label="Strict Deadline?")
    start_time = Input(datetime.datetime(2026, 5, 27, 8, 0), label="Start Time (yyyy, mm, dd, hrs, min)")
    # Only required / meaningful if strict_deadline is True
    deadline_time: Optional[datetime.datetime] = Input(None, label="Deadline Time (yyyy, mm, dd, hrs, min)")



    standard_locations = {
        "Eindhoven": (51.468288, 5.421365),
        "Tilburg": (51.591433, 5.023739),
        "Breda": (51.585288, 4.732775),
        "Den Bosch": (51.585288, 4.732775),
        "Waalwijk": (51.699574, 5.046544),
    }

    # overall_dimensions: array[x', y'], always a rectangle,
    # in its own reference system
    site_dimensions: Tuple[float, float] = Input((100.0, 100.0))
    orientation: float = Input(0.0)

    number_of_machines_per_type = {
        "Crane": 0,
        "Tractor": 0,
        "Truck": 0,
        "Tool": 0,
        "Pump": 0,
    }

    # Aggregations / associations
    machines: List[Machine] = Input([])
    trailers: List[Trailer] = Input([])
    depots: List[Depot] = Input([])

    work_job = Input(None)

    @Input
    def gps_location(self):
        if self.work_job is not None:
            return self.work_job.gps_location
        else:
            return (0, 0)

    @action(label="Use Fleets-Online Data", button_label="Read")
    def ReadFleetsData(self):
        self.FleetsOnlineData()
        self.ReadData(True)

    @action(label="Use Custom Data", button_label="Read")
    def ReadCustomData(self):
        self.ReadData(False)

    def FleetsOnlineData(self):
        # API Authentication Header
        base_url = "https://api.v2.deepdigital.org"
        token_response = requests.post(
            f"{base_url}/oauth/token",
            data={
                "grant_type": "password",
                "username": "testing@fleets-online.com",
                "password": "WTuXQ8ZsK9#mT4qZ",
            },
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        standard_dimensions = {
            "Vrachtwagens ": [3, 2, 2],
            "Tractor": [3, 2.5, 3],
            "Kranen": [4, 2, 3.5],
            "Aanhanger licht": [10, 2, 2],
            "Aanhanger zwaar": [18, 2.5, 2.5],
        }

        # API Get POIs
        response = requests.get(
            f"{base_url}/pois",
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
        assets.append(
            requests.get(
                f"{base_url}/equipment",
                headers=headers,
                params={
                    "pageSize": 100,
                    "activeOnly": True,
                    "searchTerm": "Tractor",
                },
            ).json()["value"]
        )
        assets.append(
            requests.get(
                f"{base_url}/equipment",
                headers=headers,
                params={
                    "pageSize": 100,
                    "activeOnly": True,
                    "searchTerm": "Kranen",
                },
            ).json()["value"]
        )
        assets.append(
            requests.get(
                f"{base_url}/equipment",
                headers=headers,
                params={
                    "pageSize": 100,
                    "activeOnly": True,
                    "searchTerm": "Vrachtwagens",
                },
            ).json()["value"]
        )
        assets.append(
            requests.get(
                f"{base_url}/equipment",
                headers=headers,
                params={
                    "pageSize": 100,
                    "activeOnly": True,
                    "searchTerm": "Aanhanger licht",
                },
            ).json()["value"]
        )
        assets.append(
            requests.get(
                f"{base_url}/equipment",
                headers=headers,
                params={
                    "pageSize": 100,
                    "activeOnly": True,
                    "searchTerm": "Aanhanger zwaar",
                },
            ).json()["value"]
        )

        # Keep track of all pois and assets to write to the json file
        data = []

        # Loop through the available points of interest
        for poi in pois:
            # -- The following can be added if Fleets-Online adds
            #    orientation to their POI data --
            # if poi["orientation"] == None: orientation = 0
            # else: orientation = poi["orientation"]
            orientation = 0
            # Check if the location address and shapeData is defined
            if poi["address"] is not None and poi["shapeData"] is not None:
                # For the time being to put all FleetsOnline assets
                # in the depot
                (
                    poi["address"]["lat"],
                    poi["address"]["lat"],
                ) = self.standard_location
                data.append(
                    {
                        "type": "poi",
                        "name": poi["name"],
                        "gps_location": {
                            "lat": poi["address"]["lat"],
                            "lon": poi["address"]["lon"],
                        },
                        "overall_dimensions": [
                            poi["shapeData"]["radius"],
                            0.5 * poi["shapeData"]["radius"],
                            10,
                        ],
                        "orientation": orientation,
                    }
                )
            else:
                data.append(
                    {
                        "type": "poi",
                        "name": poi["name"],
                        "gps_location": {
                            "lat": self.standard_location[0],
                            "lon": self.standard_location[1],
                        },
                        "overall_dimensions": [50, 25, 10],
                        "orientation": orientation,
                    }
                )

        # Loop through the available assets
        for asset_type in assets:
            for asset in asset_type:
                if asset["averageConsumption"] is None:
                    cons = 50
                else:
                    cons = asset["averageConsumption"]

                if "Aanhanger" in asset["type"]["name"]:
                    data.append(
                        {
                            "type": "asset",
                            "id": asset["name"],
                            "name": asset["type"]["name"],
                            "build_year": asset["buildYear"],
                            "gps_location": {
                                "lat": self.standard_location[0],
                                "lon": self.standard_location[1],
                            },
                            "overall_dimensions": standard_dimensions[
                                asset["type"]["name"]
                            ],
                            "color": "yellow",
                        }
                    )
                else:
                    data.append(
                        {
                            "type": "asset",
                            "id": asset["name"],
                            "name": asset["type"]["name"],
                            "build_year": asset["buildYear"],
                            "gps_location": {
                                "lat": self.standard_location[0],
                                "lon": self.standard_location[1],
                            },
                            "overall_dimensions": standard_dimensions[
                                asset["type"]["name"]
                            ],
                            "color": "yellow",
                            "fuel_type": asset["fuelType"]["name"],
                            "emission_class_version": "StageIIIB",
                            "consumption_per_hour": cons,
                        }
                    )

        # Write FleetsOnline data to FleetsOnlineData.json file
        with open("FleetsOnlineData.json", "w") as f:
            json.dump(data, f, indent=4)

        return pois, assets

    def ReadData(self, use_fleets_data: bool = False):
        # reset mutable state so we don't accumulate entries across runs
        self.depots = []
        self.machines = []
        self.trailers = []
        self.number_of_machines_per_type = {
            "Crane": 0,
            "Tractor": 0,
            "Truck": 0,
            "Tool": 0,
            "Pump": 0,
        }

        if self.needed_machinery not in self.possible_machinery:
            generate_warning(
                "Warning: Machinery cannot be read",
                "The selected machinery type can not be read, check for a "
                "typo or add this machine to the machinery types list. "
                "If doubts about the application, contact us.",
            )
            return
        elif self.man_hours <= 0:
            generate_warning(
                "Warning: Man hours invalid",
                "The selected number of man hours is equal to or smaller "
                "than zero. Please choose a positive number of man hours.",
            )
            return

        if use_fleets_data:
            with open("FleetsOnlineData.json", "r") as file:
                data = json.load(file)
        else:
            with open("CustomData.json", "r") as file:
                data = json.load(file)

        for l in data:
            if l["type"] == "poi":
                # ---------------- Depots ----------------
                if "Garage" in l["name"]:
                    depot = Depot()
                    depot.gps_location = (
                        l["gps_location"]["lat"],
                        l["gps_location"]["lon"],
                    )
                    depot.overall_dimensions = l["overall_dimensions"]
                    depot.name = l["name"]

                    # NEW: read rotation (in degrees) from JSON,
                    # default to 0.0 if missing
                    depot.rotation = float(l.get("orientation", 0.0))

                    self.depots.append(depot)

                # ---------------- Work site ----------------
                elif "Boomrooierij" in l["name"]:
                    workjob = WorkJob()
                    if l["gps_location"] is None:
                        print("One of the worksites has no location data")
                        workjob.gps_location = (
                            self.standard_locations["Breda"][0],
                            self.standard_locations["Breda"][1],
                        )
                    else:
                        workjob.gps_location = (
                            l["gps_location"]["lat"],
                            l["gps_location"]["lon"],
                        )

                    workjob.needed_vehicles = self.needed_machinery
                    workjob.man_hours = self.man_hours
                    workjob.name = l["name"]

                    self.work_job = workjob
                    self.gps_location = workjob.gps_location

                    # Use only L, W from overall_dimensions; ignore height
                    # for site area
                    dims = l.get(
                        "overall_dimensions",
                        [100.0, 100.0, 0.0],
                    )
                    self.site_dimensions = (
                        float(dims[0]),
                        float(dims[1]),
                    )

                    # Orientation is optional; default to 0 if not in JSON
                    self.orientation = float(l.get("orientation", 0.0))

            elif l["type"] == "asset":
                # --------- create correct machine/trailer type ----------
                if l["name"] == "Tractor":
                    m = Tractor()
                    m.machine_type = "Tractor"
                elif l["name"] == "Kranen":
                    m = Crane()
                    m.machine_type = "Crane"
                elif (
                    l["name"] == "Vrachtwagens"
                    or l["name"] == "Vrachtwagens "
                ):
                    m = Truck()
                    m.machine_type = "Truck"
                elif "Aanhanger" in l["name"]:
                    m = Trailer()
                    m.overall_dimensions = l["overall_dimensions"]
                elif "Tool" in l["name"]:
                    m = Tool()
                    m.machine_type = "Tool"
                elif "Pump" in l["name"]:
                    m = Pump()
                    m.machine_type = "Pump"
                else:
                    m = Vehicle()

                # --------- generic machine properties ----------
                try:
                    m.overall_dimensions = l["overall_dimensions"]
                except Exception:
                    m.overall_dimensions = (2, 2, 2)
                    generate_warning(
                        "Warning: Overall dimensions not specified",
                        f"The overall dimensions were not provided for "
                        f"machine {l['id']}. Standard dimensions of "
                        "[2 x 2 x 2] are used instead.",
                    )

                m.build_year = l["build_year"]
                if m.build_year is None:
                    m.build_year = 2026
                elif m.build_year < 2020:
                    # limitation of CO2 calculator
                    m.build_year = 2020

                m.gps_location = (
                    l["gps_location"]["lat"],
                    l["gps_location"]["lon"],
                )

                try:
                    m.color = l["color"]
                except Exception:
                    m.color = None

                if "Aanhanger" in l["name"]:
                    m.trailer_id = l["id"]
                    if m.color is None:
                        m.color = "Orange"
                    self.trailers.append(m)
                elif m.machine_type not in ["Tool", "Pump"]:
                    m.machine_id = l["id"]
                    if "Diesel (fossiel)" in l["fuel_type"]:
                        m.energy_source = "diesel-(fossiel)"
                    elif "Biodiesel" in l["fuel_type"]:
                        m.energy_source = "biodiesel-(hvo)"
                    elif "Electric" in l["fuel_type"]:
                        m.energy_source = "Electric"
                    else:
                        m.energy_source = "diesel-(fossiel)"

                    m.emission_class = l["emission_class_version"]
                    m.consumption_per_hour = l["consumption_per_hour"]
                    if m.color is None:
                        m.color = "Yellow"
                    self.machines.append(m)
                    self.number_of_machines_per_type[m.machine_type] += 1
                else:
                    m.machine_id = l["id"]
                    if m.color is None:
                        m.color = "Blue"
                    self.machines.append(m)

                gps_check = Routing.gps_checker(
                    [m.gps_location[0], m.gps_location[1]]
                )
                if gps_check == 2:
                    generate_warning(
                        "Warning: Coordinate outside of intended region",
                        "The provided coordinate(s) fall outside of the "
                        "intended region. A bigger map of western Europe "
                        "is used. For a clearer resolution, add a local "
                        "map with corner coordinates in Routing.py.",
                    )
                elif gps_check == 3:
                    generate_warning(
                        "Warning: Coordinate outside of intended region",
                        "The provided coordinate(s) fall outside of "
                        "available western Europe map. To use this route, "
                        "add your own map for visibility with corner "
                        "coordinates in Routing.py.",
                    )
                elif gps_check == 4:
                    generate_warning(
                        "Warning: Coordinates not specified",
                        "The coordinates are not specified. As such, the "
                        "vehicle with GPS location (0.0, 0.0) will not be "
                        "used. Please add vehicle coordinates or the "
                        "coordinates of the depot where it is stored.",
                    )
            else:
                generate_warning(
                    "Warning: Unknown data entry",
                    "The provided FleetsOnlineData.json data file contains "
                    "an entry of an unknown type, this entry will be "
                    "ignored.",
                )

        asset_overall_dimensions = (0.0, 0.0, 0.0)
        if np.any(asset_overall_dimensions == 0):
            generate_warning(
                "Warning: Dimension(s) missing",
                "Add the (non-zero) dimensions in x, y and z.",
            )

    @Attribute
    def standard_location(self):
        return self.standard_locations["Eindhoven"]

    all_generated_missions = Input([])
    winning_mission = Input(None)

    # --- existing methods like NormalizePreferences(), etc. ---

    @action(label="Generate Strategy", button_label="Generate")
    def MissionIterator(self) -> "MissionStrategyApp":
        print("=== DEBUG: current machines ===")
        print("Total machines:", len(self.machines))
        for m in self.machines:
            print(type(m).__name__, getattr(m, "machine_id", None))

        # --- deadline consistency check (WARNING but no abort) ---
        if self.strict_deadline and self.deadline_time is None:
            generate_warning(
                "Missing deadline",
                "You enabled 'strict_deadline', but did not specify a "
                "'deadline_time'.\n\nThe strategy will still be generated, "
                "but deadlines are ignored.\nPlease fill in 'deadline_time' "
                "if you want real deadline enforcement.",
            )
            self.strict_deadline = False

        self.work_job.man_hours = self.man_hours
        tic = time.perf_counter()

        # Top-level mission loop:
        # 1) Generate candidate missions
        # 2) Evaluate raw metrics per mission
        # 3) Normalize & pick mission with lowest scalar cost

        # Allocate machines to depots / road-side
        self.road_parked = self.AllocateMachines()

        # 1) MissionGenerator: generate all candidate missions
        self.all_generated_missions = generate_missions(
            self,
            MissionCls=Mission,
            TransportJobCls=TransportJob,
            VehicleCls=Vehicle,
            TrailerCls=Trailer,
        )

        # --- 1b) Deadline restriction (if enabled) ---
        if self.strict_deadline and self.deadline_time is not None:
            # Available total hours between start and deadline
            deadline_delta = self.deadline_time - self.start_time
            deadline_total_hours = (
                deadline_delta.total_seconds() / 3600.0
            )

            # Call special deadline-aware mission generator / filter
            self.all_generated_missions = (
                deadline_restricted_mission_generator(
                    self,
                    self.all_generated_missions,
                    deadline_total_hours,
                )
            )

        if not self.all_generated_missions:
            raise RuntimeError(
                "MissionGenerator produced no missions to evaluate."
            )

        # 2) MissionEvaluator: compute raw totals per mission
        self._mission_evaluator(self.all_generated_missions)

        # 3) MissionPicker: normalize, compute scalar, pick best
        winning_mission = self._mission_picker(self.all_generated_missions)

        toc = time.perf_counter()
        print(f"Took {toc - tic:0.4f} seconds")

        self.winning_mission = winning_mission
        return winning_mission

    def jobAnalyzer(self):
        """
        Determine the maximum number of machines that can work on a work
        site, based on the machine area and the site area, to not have
        an overcrowded work site.
        """
        area_factor = 0.1
        job_machines_areas = []

        for m in self.machines:
            if m.machine_type == self.work_job.needed_machines:
                job_machines_areas.append(np.pi * m.turn_radius**2)
                # job_machines_areas.append(
                #     m.overall_dimensions[0] * m.overall_dimensions[1]
                # )

        job_area = self.site_dimensions[0] * self.site_dimensions[1]
        average_job_machine_area = (
            np.mean(job_machines_areas) if job_machines_areas else 0.0
        )
        if average_job_machine_area == 0:
            average_job_machine_area = 1.0

        max_number_of_machines = np.floor(
            area_factor * job_area / average_job_machine_area
        )
        return max(1, max_number_of_machines)

    # ------------------------------------------------------------------
    # 2) MissionEvaluator
    # ------------------------------------------------------------------
    def _mission_evaluator(self, missions: List["MissionStrategyApp"]) -> None:
        """For each mission, sum maintenance, NOx, CO2, cost and time
        over all its transport and work jobs."""
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
                transport_job.transporting_vehicle.hours_used = (
                    transport_job.routeDuration / 60
                )
                total_mission_NOx += transport_job.job_NOx
                total_mission_CO2 += transport_job.job_CO2
                total_mission_cost += transport_job.job_cost
                # assume consistent unit
                total_mission_time += transport_job.routeDuration

            # Work jobs: job_* are per tool/vehicle lists
            for work_job in work_jobs:
                for mach in work_job.assigned_vehicles:
                    mach.hours_used = (
                        work_job.man_hours
                        / len(work_job.assigned_vehicles)
                    )
                for tool in work_job.assigned_tools:
                    tool.hours_used = (
                        work_job.man_hours
                        / len(work_job.assigned_tools)
                    )

                total_mission_NOx += sum(work_job.job_NOx)
                total_mission_CO2 += sum(work_job.job_CO2)
                total_mission_cost += sum(work_job.job_cost)
                # total_mission_time += work_job.job_duration

            m.mission_NOx = total_mission_NOx
            m.mission_CO2 = total_mission_CO2
            m.mission_cost = total_mission_cost
            m.mission_time = total_mission_time

    # ------------------------------------------------------------------
    # 3) MissionPicker
    # ------------------------------------------------------------------
    def _mission_picker(
        self, missions: List["MissionStrategyApp"]
    ) -> "MissionStrategyApp":
        """Normalize cost/time/emissions across missions, evaluate scalar
        score for each mission and return the best one."""
        # Collect raw values across all missions
        costs = [m.mission_cost for m in missions]
        times = [m.mission_time for m in missions]
        CO2s = [m.mission_CO2 for m in missions]
        NOxs = [m.mission_NOx for m in missions]

        mean_cost = np.mean(costs)
        std_cost = np.std(costs)
        mean_time = np.mean(times)
        std_time = np.std(times)
        mean_CO2 = np.mean(CO2s)
        std_CO2 = np.std(CO2s)
        mean_NOx = np.mean(NOxs)
        std_NOx = np.std(NOxs)

        alpha = 0.25  # weight CO2 vs NOx inside "emissions" metric

        for m in missions:
            # Normalized cost
            if std_cost != 0:
                m.normalized_cost = (
                    m.mission_cost - mean_cost
                ) / std_cost
            else:
                m.normalized_cost = 0

            # Normalized time
            if std_time != 0:
                m.normalized_time = (
                    m.mission_time - mean_time
                ) / std_time
            else:
                m.normalized_time = 0

            # Normalized emissions
            if std_CO2 != 0:
                norm_CO2 = (m.mission_CO2 - mean_CO2) / std_CO2
            else:
                norm_CO2 = 0

            if std_NOx != 0:
                norm_NOx = (m.mission_NOx - mean_NOx) / std_NOx
            else:
                norm_NOx = 0

            m.normalized_emissions = (
                alpha * norm_CO2 + (1.0 - alpha) * norm_NOx
            )

            m.mission_preferences = self.NormalizePreferences

            # Scalar cost function for this mission
            m.mission_scalar = m.cost_function

        # Pick the mission with the lowest scalar score
        winning_mission = min(
            missions, key=lambda mm: mm.mission_scalar
        )
        return winning_mission

    # Define (normalized) preferences function
    @Attribute
    def NormalizePreferences(self) -> List[float]:
        """Normalize mission_preferences:
        - Negative values => 0 (user really doesn't want that objective)
        - Non-negative values are scaled so sum == 1
        - If all are <= 0, fall back to equal weights.
        - Order: [cost, time, emissions]
        """
        # 1) read raw preferences as floats
        prefs = [float(p) for p in self.mission_preferences]
        if not prefs:
            # sensible fallback if user deletes the list entirely
            return [1.0, 0.0, 0.0]

        # 2) clamp negatives to 0
        clamped = [p if p > 0.0 else 0.0 for p in prefs]

        total = sum(clamped)

        # 3) normalize or fall back to equal weights
        if total > 0.0:
            return [p / total for p in clamped]
        else:
            n = len(prefs)
            normalized = [1.0 / n] * n

        return normalized

    # Function that builds the final mission planning
    @Attribute
    def timelines(self):
        timelines = []
        for transport_job in self.winning_mission.transport_jobs:
            vehicle = transport_job.transporting_vehicle
            timelines.append(
                [vehicle, self.start_time, self.start_time + datetime.timedelta(minutes=transport_job.routeDuration),
                 "transport"])
        print(timelines)
        timelines = np.array(timelines)
        for work_job in self.winning_mission.work_jobs:
            vehicles = work_job.assigned_vehicles
            for vehicle in vehicles:
                index = None
                for i, transported_vehicle in enumerate(
                    timelines[:, 0]
                ):
                    if transported_vehicle == vehicle:
                        index = i
                    else:
                        try:
                            if (
                                transported_vehicle.contents.contents[0]
                                == vehicle
                            ):
                                index = i
                        except Exception:
                            continue
                if index is None:
                    print(
                        "Warning: workjob assigned vehicle "
                        f"{vehicle.machine_id} has not been "
                        "transported there."
                    )
                timelines = np.vstack(
                    (
                        timelines,
                        np.array(
                            [
                                vehicle,
                                timelines[index][2],
                                timelines[index][2]
                                + datetime.timedelta(
                                    hours=(
                                        work_job.man_hours
                                        / len(vehicles)
                                    )
                                ),
                                "work",
                            ]
                        ),
                    )
                )
        return timelines

    # ------------------------------------------------------------------
    # Cost function
    # ------------------------------------------------------------------
    def PackagedVisualization(self):
        """Return the ParaPy model to visualize the packing. It visualizes
        the trailers, together with the packed tools, and vehicles
        * attachable + upright_only: solid purple.
        * if only upright_only (nonturnable): very light/baby blue
        * if only vehicle_attachable: pink
        * other tools: random blue shades
        * if vehicles: shades of yellow.
        """
        return TrailerPackingVisualization(
            items=self.items_to_pack,
            trailers=self.job_trailers,
        )

    # ------------------------------------------------------------------------------------------------------------------
    # --- ACTIONS / BUTTONS --
    # ------------------------------------------------------------------------------------------------------------------
    @action(label="Visualise Routes", button_label="Visualise")
    def MapMaker(self):
        """
        Open a map showing:
        - all transport job routes,
        - all depots with their actual sizes and rotation,
        - all work sites with their JSON-based site_dimensions and
          orientation,
        - and keep references to the actual Depot / WorkJob objects for
          selection.
        """

        # --- build route list: (start, end, vehicle) ---
        routes = []
        transport_jobs = self.winning_mission.transport_jobs
        work_jobs = self.winning_mission.work_jobs

        for job in transport_jobs:
            start = job.begin_location_gps
            end = job.end_location_gps
            vehicle = job.transporting_vehicle  # object, not string
            routes.append((start, end, vehicle))

        # --- depot GPS points + sizes + rotations + objects ---
        depot_points: List[Tuple[float, float]] = []
        depot_sizes: List[Tuple[float, float, float]] = []
        depot_rotations: List[float] = []
        depot_objects: List[Depot] = []

        for dep in self.depots:
            try:
                depot_points.append(dep.gps_location)
                L, W, H = dep.overall_dimensions
                depot_sizes.append(
                    (float(L) * 10, float(W) * 10, float(H) * 10)
                )
                angle = float(getattr(dep, "rotation", 0.0))
                depot_rotations.append(angle)
                depot_objects.append(dep)
            except AttributeError:
                print(
                    f"[MapMaker] Depot {dep} missing gps_location "
                    f"/ overall_dimensions; skipping."
                )
            except Exception as e:
                print(
                    "[MapMaker] Failed to read depot size/rotation "
                    f"for {dep}: {e}"
                )

        # --- work site GPS points + sizes + rotations + objects ---
        worksite_points: List[Tuple[float, float]] = [
            wj.gps_location for wj in work_jobs
        ]
        worksite_sizes: List[Tuple[float, float, float]] = []
        worksite_rotations: List[float] = []
        worksite_objects: List[WorkJob] = list(work_jobs)

        for _wj in work_jobs:
            try:
                L, W = self.site_dimensions
                L *= 10.0
                W *= 10.0
            except Exception:
                L, W = 2000.0, 2000.0  # fallback

            H = 100.0
            worksite_sizes.append((float(L), float(W), float(H)))
            worksite_rotations.append(float(self.orientation))

        # Instantiate map object with explicit sizes & rotations + object refs
        map_obj = MapMaker(
            routes=routes,
            depots=depot_points,
            depot_sizes=depot_sizes,
            depot_rotations_deg=depot_rotations,
            depot_objects=depot_objects,
            work_sites=worksite_points,
            worksite_sizes=worksite_sizes,
            worksite_rotations_deg=worksite_rotations,
            worksite_objects=worksite_objects,
        )

        display(map_obj, mainloop=False)

    @action(label="Visualise Depots", button_label="Visualise")
    def DepotMaker(self):
        depots_local = []
        current_y = 0
        # road_parked unused, still trigger AllocateMachines() to compute
        # only once for entire MissionStrategyApp
        road_parked = self.AllocateMachines()
        del road_parked

        for i, d in enumerate(self.depots):
            d.gps_location = (0, current_y)
            current_y += 10 + d.overall_dimensions[1]
            depots_local.append(d)

        display(depots_local, mainloop=False)

    @action(label="Visualise Trailer Arrangements", button_label="Visualise")
    def trailer_arrangement(self):
        """Open a ParaPy viewer window with the trailer packing
        visualization for this mission.

        Relies on:
            - self.items_to_pack: List[Item]
            - self.trailers: list of trailer-like objects
              (each with carrying_bounding_box and has_ceiling).
        """
        # Basic sanity checks, helpful during development
        if not hasattr(self, "items_to_pack"):
            raise RuntimeError(
                "MissionStrategyApp has no 'items_to_pack' attribute. "
                "Define it as an Input or Attribute that returns "
                "List[Item]."
            )

        viz_model = self.PackagedVisualization()
        display(viz_model, mainloop=False)

    def AllocateMachines(self):
        machines = self.machines
        for machine in machines:
            machine.number_of_this_type = (
                self.number_of_machines_per_type[machine.machine_type]
            )
        trailers = self.trailers
        road_parked: List[Machine] = []

        for depot in self.depots:
            depot.machines = machines
            depot.trailers = trailers
            _, road_parked = depot.DepotMachineAllocation()
            machines = road_parked

        return road_parked

    @Part(parse=False)
    def FleetOverviewMap(self):
        """
        Visualize the *initial* fleet on a map:
        - background map (MAP1 / MAP2),
        - depots with actual sizes & rotation,
        - work site(s) with JSON-based site_dimensions & orientation,
        - all machines & trailers as stacked boxes on their gps_location.

        Assets stacked:
        - if multiple objects share same gps_location (road-parked),
          they are stacked in +Z.
        - if gps_location coincides with a depot, they appear stacked on
          that depot position as well.

        Each visual element keeps a reference to the actual object:
        - depot markers -> DepotMarker.depot
        - work site markers -> WorksiteMarker.worksite
        - asset markers -> AssetMarker.asset
        """

        # --- worksite GPS points + sizes + rotations + objects ---
        worksite_points: List[Tuple[float, float]] = []
        worksite_sizes: List[Tuple[float, float, float]] = []
        worksite_rotations: List[float] = []
        worksite_objects: List[object] = []

        if self.work_job is not None:
            worksite_points.append(self.work_job.gps_location)
            worksite_objects.append(self.work_job)
        else:
            # dummy point if no work_job defined
            worksite_points.append((0.0, 0.0))
            worksite_objects.append(None)

        try:
            L, W = self.site_dimensions
            L *= 10.0
            W *= 10.0
        except Exception:
            L, W = 2000.0, 2000.0

        H = 100.0
        worksite_sizes.append((float(L), float(W), float(H)))
        worksite_rotations.append(float(self.orientation))

        # --- depot GPS points + sizes + rotations + objects ---
        depot_points: List[Tuple[float, float]] = []
        depot_sizes: List[Tuple[float, float, float]] = []
        depot_rotations: List[float] = []
        depot_objects: List[Depot] = []

        for dep in self.depots:
            try:
                depot_points.append(dep.gps_location)
                Ld, Wd, Hd = dep.overall_dimensions
                depot_sizes.append(
                    (float(Ld) * 10, float(Wd) * 10, float(Hd) * 10)
                )
                angle = float(getattr(dep, "rotation", 0.0))
                depot_rotations.append(angle)
                depot_objects.append(dep)
            except Exception as e:
                print(
                    f"[FleetOverviewMap] Failed to read depot data for "
                    f"{dep}: {e}"
                )
                # simple fallback depot
                depot_points.append(dep.gps_location)
                depot_sizes.append((2000.0, 1000.0, 500.0))
                depot_rotations.append(0.0)
                depot_objects.append(dep)

        # --- assets: initial fleet: all machines + all trailers ---
        assets_list: List[object] = []
        assets_list.extend(self.machines)
        assets_list.extend(self.trailers)

        map_obj = FleetMapMaker(
            routes=[],
            depots=depot_points,
            depot_sizes=depot_sizes,
            depot_rotations_deg=depot_rotations,
            depot_objects=depot_objects,
            work_sites=worksite_points,
            worksite_sizes=worksite_sizes,
            worksite_rotations_deg=worksite_rotations,
            worksite_objects=worksite_objects,
            assets=assets_list,
        )

        return map_obj

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
                if machine is not None:
                    items.append(item_from_machine(machine))
        return items

    @Part
    def new_vehicle(self):
        return Machine()

    @action(
        label="Export Strategy",
        button_label="Export Strategy Overview to .pdf",
    )
    def exportStrategy(self):
        PDFMaker.Export(
            self.winning_mission,
            self.start_time,
            self.timelines,
        )

    @action(
        button_label="Add Vehicle to JSON Data File",
        label="Add Vehicle",
    )
    def AddVehicle(self):
        m = self.new_vehicle
        with open("CustomData.json", "r") as f:
            data = json.load(f)
        energy_source = m.energy_source
        if "diesel-(fossiel)" == energy_source:
            fuel_type = "Diesel (fossiel)"
        elif "biodiesel-(hvo)" == energy_source:
            fuel_type = "Biodiesel"
        elif "Electric" == energy_source:
            fuel_type = "Electric"
        else:
            fuel_type = "diesel-(fossiel)"
        data.append(
            {
                "type": "asset",
                "id": m.machine_id,
                "name": m.machine_type,
                "build_year": m.build_year,
                "gps_location": {
                    "lat": m.gps_location[0],
                    "lon": m.gps_location[1],
                },
                "overall_dimensions": m.overall_dimensions,
                "color": m.color,
                "fuel_type": fuel_type,
                "emission_class_version": m.emission_class,
                "consumption_per_hour": m.consumption_per_hour
            }
        )

        print(data)

        with open("CustomData.json", "w") as f:
            json.dump(data, f, indent=4)

        generate_warning("Added machine", "Successfully added the machine to CustomData.json. Please reload the data file using the button in the property view.")

    @action(button_label="Delete the last added machine", label="Delete machine")
    def RemoveVehicle(self):
        with open("CustomData.json", "r") as f:
            data = json.load(f)

        data = data[0 : len(data) - 1]

        with open("CustomData.json", "w") as f:
            json.dump(data, f, indent=4)

        generate_warning(
            "Success",
            "The last added machine was successfully deleted from the "
            "JSON file.",
        )

    @action(button_label="Export", label="Export Fleet")
    def ExportFleet(self):
        # Keep track of all pois and assets to write to the json file
        data = []

        # Add work job
        data.append(
            {
                "type": "poi",
                "name": self.work_job.name,
                "gps_location": {
                    "lat": self.work_job.gps_location[0],
                    "lon": self.work_job.gps_location[1],
                },
                "overall_dimensions": self.site_dimensions,
                "orientation": self.orientation,
            }
        )

        # Add depots
        for depot in self.depots:
            data.append(
                {
                    "type": "poi",
                    "name": depot.name,
                    "gps_location": {
                        "lat": depot.gps_location[0],
                        "lon": depot.gps_location[1],
                    },
                    "overall_dimensions": depot.overall_dimensions,
                    "orientation": depot.rotation,
                }
            )

        # Add trailers
        for asset in self.trailers:
            data.append(
                {
                    "type": "asset",
                    "id": asset.trailer_id,
                    "name": "Aanhanger zwaar",
                    "build_year": asset.build_year,
                    "gps_location": {
                        "lat": asset.gps_location[0],
                        "lon": asset.gps_location[1],
                    },
                    "overall_dimensions": asset.overall_dimensions,
                    "color": asset.color,
                }
            )

        # Add machines
        for asset in self.machines:
            if asset.machine_type in ["Tool", "Pump"]:
                data.append(
                    {
                        "type": "asset",
                        "id": asset.machine_id,
                        "name": type(asset).__name__,
                        "build_year": asset.build_year,
                        "gps_location": {
                            "lat": asset.gps_location[0],
                            "lon": asset.gps_location[1],
                        },
                        "overall_dimensions": asset.overall_dimensions,
                        "color": asset.color,
                    }
                )
            else:
                if asset.energy_source == "diesel-(fossiel)":
                    fuel_type = "Diesel (fossiel)"
                elif asset.energy_source == "biodiesel-(hvo)":
                    fuel_type = "Biodiesel"
                elif asset.energy_source == "Electric":
                    fuel_type = "Electric"
                else:
                    fuel_type = "Diesel (fossiel)"

                if type(asset).__name__ == "Truck":
                    machine_type = "Vrachtwagens"
                elif type(asset).__name__ == "Crane":
                    machine_type = "Kranen"
                else:
                    machine_type = type(asset).__name__

                data.append(
                    {
                        "type": "asset",
                        "id": asset.machine_id,
                        "name": machine_type,
                        "build_year": asset.build_year,
                        "gps_location": {
                            "lat": asset.gps_location[0],
                            "lon": asset.gps_location[1],
                        },
                        "overall_dimensions": asset.overall_dimensions,
                        "color": asset.color,
                        "fuel_type": fuel_type,
                        "emission_class_version": asset.emission_class,
                        "consumption_per_hour": asset.consumption_per_hour,
                    }
                )

        with open("CustomData.json", "w") as f:
            json.dump(data, f, indent=4)

        generate_warning("Exported fleet", "Successfully exported the current fleet to CustomData.json.")

class Mission(Base):
    transport_jobs: List["TransportJob"] = Input([])
    work_jobs: List["WorkJob"] = Input([])
    machines: List["Machine"] = Input([])
    mission_preferences = Input([1.0, 1.0, 1.0])

    mission_NOx = Input(0.0)
    mission_CO2 = Input(0.0)
    mission_cost = Input(0.0)
    mission_time = Input(0.0)

    normalized_time = Input(0.0)
    normalized_cost = Input(0.0)
    normalized_emissions = Input(0.0)

    @Attribute
    def cost_function(self) -> float:
        """Dot product of normalized preferences and normalized objectives."""
        w_cost, w_time, w_emissions = self.mission_preferences
        return (
            w_cost * self.normalized_cost
            + w_time * self.normalized_time
            + w_emissions * self.normalized_emissions
        )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class TransportJob(Base):
    """
    Description:
        Job representing the transport of a vehicle from its initial
        position to a target location.

    Inputs:
        - Locations of the specific vehicles
        - Vehicle specific work hours at the site (locations).

    Outputs:
        - Valhalla outputs

    To Do's:
        - Think about if a vehicle is more efficient to drive to the
          depot, or if the vehicle should be picked up from its starting
          location by a truck from the depot.
        - Look at outputs of Valhalla and inputs needed for tools.
    """

    begin_location_gps: Tuple[float, float] = Input((0.0, 0.0))
    end_location_gps: Tuple[float, float] = Input((0.0, 0.0))

    route_distance: float = Input(0.0)

    needed_machinery: Machine = Input([])
    # Almost always the needed_machinery, unless the needed_machinery is
    # being transported by a truck or tractor
    transporting_vehicle: Machine = Input(needed_machinery)

    max_speeds = {
        "Truck": 80,
        "Tractor": 40,
        "Crane": 45,
        "Excavator": 40,
        "Vehicle": 100,
    }

    # Dotted UML link “Get Fleet”: reference to the fleet used for this job
    fleet: Optional["Fleet"] = Input(None)

    # Duration of the route (scaled by speed of vehicle) in minutes
    @Attribute
    def routeDuration(self) -> float:
        # Route distance in km
        route_distance = self.route_distance / 1000

        if (
            str(type(self.transporting_vehicle).__name__) == "Truck"
            or str(type(self.transporting_vehicle).__name__) == "Vehicle"
        ):
            routeDuration = (
                self.route_distance
                / 1000
                / (
                    self.max_speeds[
                        str(type(self.transporting_vehicle).__name__)
                    ]
                    * 0.8
                )
                * 3600
            )
        else:
            # Factor for not always driving at the maximum speeds due to
            # rural roads, traffic, etc.
            max_speed = (
                self.max_speeds[
                    str(type(self.transporting_vehicle).__name__)
                ]
                * 0.8
            )
            routeDuration = route_distance / max_speed * 3600

        routeDuration = round(routeDuration / 60)
        return routeDuration

    @Attribute
    def job_NOx(self) -> float:
        self.transporting_vehicle.hours_used = self.routeDuration / 60
        NOx = self.transporting_vehicle.individual_nox
        return NOx

    @Attribute
    def job_CO2(self) -> float:
        CO2 = self.transporting_vehicle.individual_co2
        return CO2

    @Attribute
    def job_cost(self) -> float:
        cost = self.transporting_vehicle.individual_cost
        return cost


class WorkJob(Base):
    """
    Description:
        Each type of work job is an instance of this class, which has
        its own deadline and specific machinery.

    Inputs:
        - Specific machinery and manhours
        - Job definition

    To Do's:
        - Think about man hours vs machine hours, multiple people per
          machine?
    """

    # Can be a list if needed_machinery is also a list (when multiple
    # machine types are used for a specific job)
    name: str = ""
    man_hours: float = Input(0.0)
    gps_location: Tuple[float, float] = Input((0.0, 0.0))
    deadline: str = Input("")

    # List specifying which type of machinery is required,
    # order is not important
    needed_tools: str = Input("")
    needed_vehicles: str = Input("")
    needed_machines = needed_vehicles
    # needed_machines = [needed_tools, needed_vehicles]

    # Resources actually assigned to this work job - Not in UML yet,
    # maybe in extended UML?
    # TODO: Think about if it makes sense to have different tools and
    # vehicles for a single job, important for workhour calculations
    assigned_tools: List["Tool"] = Input([])
    assigned_vehicles: List["Vehicle"] = Input([])

    # Dotted UML link “Get Fleet”, the work job gets the individual
    # machine attributes (its age, location, etc.) for each instance of
    # the assigned machines from the fleet to determine the individual
    # contributions to the overall cost function of each mission
    # iteration.
    fleet: Optional["Fleet"] = Input(None)

    # Using travel times from Valhalla together with work hours to
    # determine total mission time with margins, idle times, downtimes,
    # maintenance, ..., which can be used later in the cost function
    # evaluation
    @Attribute
    def job_duration(self) -> float:
        job_duration = self.man_hours / (
            len(self.assigned_tools) + len(self.assigned_vehicles)
        )
        return job_duration

    @Attribute
    def job_NOx(self) -> List[float]:
        """Per-machine NOx [g] list for this work job."""
        NOx_list: List[float] = []
        for tool in self.assigned_tools:
            tool.hours_used = self.job_duration
            NOx = tool.individual_nox
            NOx_list.append(NOx)
        for vehicle in self.assigned_vehicles:
            vehicle.hours_used = self.job_duration
            NOx = vehicle.individual_nox
            NOx_list.append(NOx)

        return NOx_list

    @Attribute
    def job_CO2(self) -> List[float]:
        """Per-machine CO₂ [kg] list for this work job."""
        CO2_list: List[float] = []
        for tool in self.assigned_tools:
            CO2 = tool.individual_co2
            CO2_list.append(CO2)
        for vehicle in self.assigned_vehicles:
            CO2 = vehicle.individual_co2
            CO2_list.append(CO2)

        return CO2_list

    @Attribute
    def job_cost(self) -> List[float]:
        """Per-machine cost list for this work job."""
        cost_list: List[float] = []
        for tool in self.assigned_tools:
            tool.hours_used = (
                self.man_hours / len(self.assigned_tools)
            )
            cost = tool.individual_cost
            cost_list.append(cost)
        for vehicle in self.assigned_vehicles:
            vehicle.hours_used = (
                self.man_hours / len(self.assigned_vehicles)
            )
            cost = vehicle.individual_cost
            cost_list.append(cost)

        return cost_list



# ---------------------------------------------------------------------------
# Fleet and locations
# ---------------------------------------------------------------------------


class Fleet(Base):
    """Collection of machines available for missions.
       If time: Can also include fleet worth and budget in order to
       suggest acquisitions for reduction of costs, emissions, ...
       If all machines are fully utilized for the mission, it can
       suggest what machines to acquire and show where to store them.
       These machines can be rented, which integrates with FleetsOnline
       system to rent machines from each other.
    """

    budget: float = Input(0.0)
    fleetWorth: float = Input(0.0)

    # Can be used for output or visualization colors. Could also be used
    # for regulations (such as different NOx emissions per sector)
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
    app = MissionStrategyApp()
    display(app)