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

from Depot import Depot, AllocateMachines
from MapMaker import MapMaker, FleetMapMaker
from MissionGenerator import (
    generate_missions,
    deadline_restricted_mission_generator,
)
from DataProcessing import GetFleetsOnlineData, ReadData
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
        - Specify work job details

    Outputs:
        - The chosen strategy, with the specific vehicles that will
          do their action at specified jobs at a certain time.
        - Arrangement geometry for depots and trailers
        - The routes of the final strategy
        - PDF summary of the chosen strategy
        - Current fleet visualized on the map

    To Do's:
        - make preference interface (action with standard preference
          with easy names such as greedy or hurry), also the option to
          define own preferences and normalize within function.
        - If time: combine multiple work jobs into one mission.
    """

    mission_preferences: List[float] = Input(
        [1.0, 1.0, 1.0],
        label="Mission Preferences (cost, time, emissions)",
        validator=all_is_number,
    )  # List of weights for the different optimisation goals

    # Add desired new machinery types here if needed
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
        0,
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
    start_time = Input((datetime.datetime.now() + datetime.timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0), label="Start Time (yyyy, mm, dd, hrs, min)")
    # Only required / meaningful if strict_deadline is True
    deadline_time: Optional[datetime.datetime] = Input(None, label="Deadline Time (yyyy, mm, dd, hrs, min)")

    standard_locations = {
        "Eindhoven": (51.468288, 5.421365),
        "Tilburg": (51.591433, 5.023739),
        "Breda": (51.585288, 4.732775),
        "Den Bosch": (51.585288, 4.732775),
        "Waalwijk": (51.699574, 5.046544),
        "Fleets-Online offices": (51.589710, 4.836888) # This should be set to the headquarters of the company using the application
    }

    # overall_dimensions: array[x', y'], always a rectangle,
    # in its own reference system
    worksite_name: str = Input("Boomrooierij")
    site_dimensions: Tuple[float, float] = Input((100.0, 100.0))
    orientation: float = Input(0.0)

    # number_of_machines_per_type = {
    #     "Crane": 0,
    #     "Tractor": 0,
    #     "Truck": 0,
    #     "Tool": 0,
    #     "Pump": 0,
    # }

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

    # This should be the coordinates of the headquarters of the company that uses it
    @Input
    def standard_location(self):
        return self.standard_locations["Fleets-Online offices"]

    @action(label="Use Fleets-Online Data", button_label="Read")
    def ReadFleetsData(self):
        self.FleetsOnlineData()
        self.LoadData(True)

    @action(label="Use Custom Data", button_label="Read")
    def ReadCustomData(self):
        self.LoadData(False)

    def FleetsOnlineData(self):
        GetFleetsOnlineData(app)

    def LoadData(self, use_fleets_data: bool = False):
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
                "typo or add this machine to the machinery types list. (In number_of_machines_per_type in main/ReadData() and possible_machinery in main/MissionStrategyApp())"
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

        work_job = WorkJob()
        ReadData(self, use_fleets_data, work_job)

    all_generated_missions = Input([])
    winning_mission = Input(None)

    @action(label="Generate Strategy", button_label="Generate")
    def MissionIterator(self) -> "MissionStrategyApp":
        """
            Top-level mission synthesis and selection.

            This method:
            - validates inputs (needed machinery present, optional deadline),
            - allocates the current fleet to depots / road-side,
            - mission_generator: generates all feasible missions (transport + work jobs),
            - optionally filters them by a hard deadline,
            - mission_evaluator: evaluates each mission on NOx, CO₂, cost and time, and
            - mission_picker: uses the normalized, preference-weighted score to pick and store
              the best mission in self.winning_mission.
        """

        print("=== DEBUG: current machines ===")
        print("Total machines:", len(self.machines))
        for m in self.machines:
            print(type(m).__name__, getattr(m, "machine_id", None))

        self.work_job.needed_machine = self.needed_machinery
        self.work_job.man_hours = self.man_hours

        if self.number_of_machines_per_type[self.needed_machinery] == 0:
            generate_warning("No machines available", f"The chosen needed machinery type {self.needed_machinery} is not present in the provided fleet. Please ensure the right vehicle type is chosen and the fleet data JSON file is complete.")
            return

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

        tic = time.perf_counter()

        # Allocate machines to depots / road-side
        self.road_parked = AllocateMachines(self)

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
        site, based on the machine movement area and the site area, to not have
        an overcrowded work site.
        """
        area_factor = 0.1
        job_machines_areas = []

        for m in self.machines:
            if m.machine_type == self.needed_machinery:
                if m.machine_type not in ["Tool", "Pump"]:
                    job_machines_areas.append(np.pi * m.turn_radius**2)
                else:
                    job_machines_areas.append(m.overall_dimensions[0] * m.overall_dimensions[1] * 2)

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
        """For each mission, sum NOx, CO2, cost and time
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
                # total_mission_time += work_job.job_duration -> work_job duration removed due to its relatively large magnitude

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
        score for each mission and return the mission with the lowest scalar value."""
        # Collect raw values across all missions
        costs = [m.mission_cost for m in missions]
        times = [m.mission_time for m in missions]
        CO2s = [m.mission_CO2 for m in missions]
        NOxs = [m.mission_NOx for m in missions]

        # Look at informal knowledge model for the normalization method used
        mean_cost = np.mean(costs)
        std_cost = np.std(costs)
        mean_time = np.mean(times)
        std_time = np.std(times)
        mean_CO2 = np.mean(CO2s)
        std_CO2 = np.std(CO2s)
        mean_NOx = np.mean(NOxs)
        std_NOx = np.std(NOxs)

        # Look at informal knowledge model, can be changed as desired
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
            return [1.0, 0.0, 0.0] # If nothing specifically defined, the company probably wants to minimize the costs only

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
        """
        This attribute determines for each machine used in the final strategy, its time milestones (its start time, start working time and finished time)
        """
        timelines = []
        for transport_job in self.winning_mission.transport_jobs:
            vehicle = transport_job.transporting_vehicle
            timelines.append(
                [vehicle, self.start_time, self.start_time + datetime.timedelta(minutes=transport_job.routeDuration),
                 "transport"])
        timelines = np.array(timelines)
        for work_job in self.winning_mission.work_jobs:
            vehicles = work_job.assigned_vehicles
            for vehicle in vehicles:
                index = None
                print(timelines)
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
                print(index)
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
        road_parked = AllocateMachines(self)
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

        viz_model = TrailerPackingVisualization(
            items=self.items_to_pack,
            trailers=self.job_trailers,
        )
        display(viz_model, mainloop=False)

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
        # This attribute collects all trailers used in the final generated strategy
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
        # This attribute collects all items that were determined to be transported by trailer in the winning mission strategy
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
        # Creates an instance of Machine of which the attributes can be filled-in in the GUI, such that it can then be exported into the custom data JSON
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
            self.strict_deadline,
            self.deadline_time,
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
        elif "Manual" == energy_source:
            fuel_type = "Manual"
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

        with open("CustomData.json", "w") as f:
            json.dump(data, f, indent=4)

        generate_warning("Added machine", "Successfully added the machine to CustomData.json. Please reload the data file using the button in the property view.")

    @action(button_label="Delete the last added machine", label="Delete machine")
    def RemoveVehicle(self):
        # Removes the last entry in CustomData.json, which is the vehicle the user added most recently
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

    @action(button_label="Export", label="Export Full Fleet")
    def ExportAll(self):
        self.ExportFleet(False)

    @action(button_label="Export", label="Export Final Strategy Fleet")
    def ExportFinal(self):
        self.ExportFleet(True)

    def ExportFleet(self, final_mission_only=False):
        # This function exports all assets into CustomData.json if final_mission_only is equal to False
        # If instead final_mission_only is equal to true, the function only exports all assets that were used by
        # the final generated strategy to FinalMission.json

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
            if final_mission_only:
                if self.needed_machinery in depot.machines or "Truck" in depot.machines:
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
            else:
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
        if final_mission_only:
            trailers = []
            for transport_job in self.winning_mission.transport_jobs:
                if transport_job.transporting_vehicle.machine_type == "Truck":
                    try:
                        if transport_job.transporting_vehicle.contents != None:
                            if transport_job.transporting_vehicle.contents not in trailers:
                                trailers.append(transport_job.transporting_vehicle.contents)
                    except:
                        continue
            for trailer in trailers:
                data.append(
                    {
                        "type": "asset",
                        "id": trailer.trailer_id,
                        "name": "Aanhanger zwaar",
                        "gps_location": {
                            "lat": trailer.gps_location[0],
                            "lon": trailer.gps_location[1],
                        },
                        "overall_dimensions": trailer.overall_dimensions,
                        "color": trailer.color,
                    }
                )
        else:
            for asset in self.trailers:
                data.append(
                    {
                        "type": "asset",
                        "id": asset.trailer_id,
                        "name": "Aanhanger zwaar",
                        "gps_location": {
                            "lat": asset.gps_location[0],
                            "lon": asset.gps_location[1],
                        },
                        "overall_dimensions": asset.overall_dimensions,
                        "color": asset.color,
                    }
                )

        # Add machines
        if final_mission_only:
            machines = self.winning_mission.machines
            for transport_job in self.winning_mission.transport_jobs:
                if transport_job.transporting_vehicle not in machines:
                    if transport_job.transporting_vehicle.machine_type == "Truck":
                        if transport_job.transporting_vehicle.contents == None: # Only add truck once, not the truck copy used for the second leg of the mission
                            machines.append(transport_job.transporting_vehicle)
                    else:
                        machines.append(transport_job.transporting_vehicle)
            for asset in self.winning_mission.machines:
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
        else:
            for asset in self.machines:
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

        if final_mission_only:
            with open("FinalMission.json", "w") as f:
                json.dump(data, f, indent=4)
        else:
            with open("CustomData.json", "w") as f:
                json.dump(data, f, indent=4)

        if final_mission_only:
            generate_warning("Exported final fleet", "Successfully exported all entities used in the final generated mission to FinalMission.json.")
        else:
            generate_warning("Exported fleet", "Successfully exported the current fleet to CustomData.json.")

class Mission(Base):
    """
    Container for a single candidate mission with evaluated metrics.

    Holds transport/work jobs, the assigned machines, raw mission totals
    (cost, time, CO₂, NOx), their normalized counterparts, and a
    user-weighted scalar score via cost_function.
    """

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
        Single vehicle transport from an origin to a destination.

        Represents moving one machine between two GPS coordinates with a
        specific route distance found using the ORS API. Based on the
        transporting vehicle type and distance, it computes via Routing.py:
        - routeDuration: travel time [minutes],
        - job_NOx: NOx emissions for this trip,
        - job_CO2: CO₂ emissions for this trip,
        - job_cost: operational cost for this trip.
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
        - Specific machinery, man hours and worksite location
    """

    name: str = ""
    man_hours: float = Input(0.0)
    gps_location: Tuple[float, float] = Input((0.0, 0.0))
    deadline: str = Input("")

    # List specifying which type of machinery is required,
    # order is not important
    needed_machine: str = Input("")

    assigned_tools: List["Tool"] = Input([])
    assigned_vehicles: List["Vehicle"] = Input([])

    # Dotted UML link “Get Fleet”, the work job gets the individual
    # machine attributes (its age, location, etc.) for each instance of
    # the assigned machines from the fleet to determine the individual
    # contributions to the overall cost function of each mission
    # iteration.
    fleet: Optional["Fleet"] = Input(None)

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
    # Instantiates the root object and starts the Parapy GUI
    app = MissionStrategyApp()
    display(app)