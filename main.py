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
    item_from_machine,
    TrailerAdapter,
    pack_items_into_trailers,
    pack_single_trailer,
)

from Warning import generate_warning
import Routing
from assets import (
    Fleet,
    Machine,
    Trailer,
    Tractor,
    Crane,
    Truck,
    Tool,
    Pump,
    Vehicle,
    allocate_trailers_to_road_trucks,
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
    # Optional: extra tools to be shipped as "goods" to the work site.
    # List of tool machine_id strings, all of which must be located in the same depot.
    goods_to_pack_ids: List[str] = Input(
        [],
        widget=PyField(),
        label="Tool IDs to pack (machine_id list, e.g. ['T1', 'T2'])",
    )
#TODO: ADD VALIDATOR FOR GOODS TO PAK IDS
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
    fleet = Input(Fleet())

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
        self.fleet.machines = []
        self.fleet.trailers = []

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
        ReadData(self, use_fleets_data, work_job, self.fleet)

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

            After the winning mission is selected, optional extra "goods to pack"
            (tools specified via goods_to_pack_ids) are shipped from their depot
            to the work site by dedicated truck+trailer transport jobs. These
            extra transports do NOT influence mission selection yet; they are
            simply appended to the winning mission.
        """
        print("=== DEBUG: current machines ===")
        print("Total machines:", len(self.fleet.available_machines))
        for m in self.fleet.available_machines:
            print(type(m).__name__, getattr(m, "machine_id", None))

        self.work_job.needed_machine = self.needed_machinery
        self.work_job.man_hours = self.man_hours

        if self.fleet.number_of_machines_per_type[self.needed_machinery] == 0:
            generate_warning(
                "No machines available",
                f"The chosen needed machinery type {self.needed_machinery} "
                "is not present in the provided fleet. Please ensure the "
                "right vehicle type is chosen and the fleet data JSON file "
                "is complete.",
            )
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

        # Allocate nearby road-parked trailers to road-parked trucks
        # (uses 100 m threshold by default,  change max_distance_m if needed/desired)
        allocate_trailers_to_road_trucks(self, max_distance_m=100.0)

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
        print("=== DEBUG: missions after deadline filter ===")
        for i, m in enumerate(self.all_generated_missions):
            if not m.machines:
                continue
            mach = m.machines[0]
            print(
                f"  Mission {i}: machine={type(mach).__name__} {getattr(mach, 'machine_id', None)}, "
                f"legs={len(m.transport_jobs)}"
            )
            for j, tj in enumerate(m.transport_jobs):
                v = tj.transporting_vehicle
                tr = getattr(v, "contents", None)

                inner_ids = [
                    getattr(x, "machine_id", None)
                    for x in (getattr(tr, "contents", []) or [])
                    if x is not None
                ]
                print(
                    f"    leg {j}: veh={type(v).__name__} {getattr(v, 'machine_id', None)}, "
                    f"trailer={getattr(tr, 'trailer_id', None) if tr else None}, "
                    f"inner={inner_ids}, route_dist={tj.route_distance}"
                )
        print("=== END DEBUG missions after deadline filter ===")


        # 2) MissionEvaluator: compute raw totals per mission
        self._mission_evaluator(self.all_generated_missions)

        # 3) MissionPicker: normalize, compute scalar, pick best
        winning_mission = self._mission_picker(self.all_generated_missions)

        toc = time.perf_counter()
        print(f"Took {toc - tic:0.4f} seconds")

        self.winning_mission = winning_mission
        print("=== DEBUG: winning mission transport jobs ===")
        for j, tj in enumerate(self.winning_mission.transport_jobs):
            v = tj.transporting_vehicle
            tr = getattr(v, "contents", None)
            inner = getattr(tr, "contents", None) if tr is not None else None
            inner_ids = [
                getattr(m, "machine_id", None) for m in (inner or []) if m is not None
            ]
            print(
                f"  job {j}: veh={type(v).__name__} {getattr(v, 'machine_id', None)}, "
                f"trailer={getattr(tr, 'trailer_id', None) if tr else None}, "
                f"inner={inner_ids}, "
                f"begin={tj.begin_location_gps}, end={tj.end_location_gps}, "
                f"dist={tj.route_distance}"
            )
        print("=== END DEBUG winning mission transport jobs ===")


        # 4) OPTIONAL: append extra truck+trailer transports
        #     for "goods to pack" (tools). This does NOT influence
        #     mission selection; it just adds extra transport jobs
        #     to the chosen winning_mission.
        self._add_goods_transport_to_winning_mission()

        return self.winning_mission

    def _add_goods_transport_to_winning_mission(self) -> None:
        """Post-process the chosen winning mission by adding extra transport
        jobs for user-specified 'goods to pack'.

        Behavior:
        - goods_to_pack_ids: list of tool machine_id strings.
        - All these tools must be located in the SAME depot (in its .machines list).
        - Normal (default) mode:
            * Tools are converted into packing Items and packed into the minimum
              number of trailers using pack_items_into_trailers(), with trailers
              sorted from largest to smallest.
            * Extra trailers are then pulled from that depot to the work site.
              If there are fewer trucks than trailers, a single truck will shuttle
              back-and-forth to move the remaining trailers.
            * Trailer.contents is set to the packed tools for trailer_arrangement.

        - JOINT mode:
            * Only if:
                - at least one needed machine (self.needed_machinery) in the
                  winning mission comes from the same depot that holds all
                  requested tools, AND
                - that machine is already transported from that depot to the
                  work site by a Truck + Trailer in the winning mission.
            * Then we:
                - Pack that needed machine + the requested tools together into
                  the trailer that is already used in the mission, using
                  pack_single_trailer() on that trailer dimensions.
                - Tools that do not fit in that first trailer are then packed
                  into extra trailers (if any) with pack_items_into_trailers()
                  as before.
                - No NEW transport job is created for the primary trailer:
                  its existing mission job is reused, and we only update
                  trailer.contents to include the co-packed tools.
        """
        # ------------------------------------------------------------------
        # Basic guards
        # ------------------------------------------------------------------
        if self.winning_mission is None:
            return
        if not self.goods_to_pack_ids:
            return
        if self.work_job is None:
            generate_warning(
                "Goods-to-pack error",
                "No work job is defined, so the destination for "
                "goods-to-pack cannot be determined.",
            )
            return

        # ------------------------------------------------------------------
        # 1) Collect tool objects per depot
        # ------------------------------------------------------------------
        requested_ids = set(str(x) for x in self.goods_to_pack_ids)
        candidate_depots = []
        depot_tools_map = {}

        for dep in self.depots:
            tools_here = [
                m
                for m in dep.machines
                if getattr(m, "machine_type", None) == "Tool"
                   and getattr(m, "machine_id", None) in requested_ids
            ]
            ids_here = {m.machine_id for m in tools_here}
            depot_tools_map[dep] = tools_here

            if requested_ids.issubset(ids_here):
                candidate_depots.append(dep)

        if not candidate_depots:
            generate_warning(
                "Goods-to-pack error",
                "None of the depots contains ALL requested tool IDs.\n"
                "Please check 'goods_to_pack_ids' and the fleet data.",
            )
            return
        if len(candidate_depots) > 1:
            generate_warning(
                "Goods-to-pack warning",
                "Multiple depots contain all requested tools. "
                "Using the first one found; please verify your data.",
            )

        depot = candidate_depots[0]
        tools_to_ship = depot_tools_map[depot]
        tools_to_ship.sort(key=lambda t: t.machine_id)

        print(
            f"[GoodsToPack] Using depot '{getattr(depot, 'name', None)}' "
            f"with tools {[t.machine_id for t in tools_to_ship]}"
        )

        # ------------------------------------------------------------------
        # 2) Trailers and trucks at this depot
        # ------------------------------------------------------------------
        depot_trailers = list(depot.trailers)
        if not depot_trailers:
            generate_warning(
                "Goods-to-pack error",
                f"Depot '{getattr(depot, 'name', None)}' has no trailers "
                "available to carry the requested tools.",
            )
            return

        depot_trucks = [
            m
            for m in depot.machines
            if getattr(m, "machine_type", None) == "Truck"
        ]
        if not depot_trucks:
            generate_warning(
                "Goods-to-pack error",
                f"Depot '{getattr(depot, 'name', None)}' has no trucks "
                "available to pull trailers for goods-to-pack.",
            )
            return

        # Sort trailers from large to small (by volume)
        def trailer_volume(tr):
            try:
                L, W, H = tr.carrying_bounding_box
            except Exception:
                L, W, H = getattr(tr, "overall_dimensions", (0.0, 0.0, 0.0))
            return float(L) * float(W) * float(H)

        sorted_trailers = sorted(
            depot_trailers,
            key=trailer_volume,
            reverse=True,
        )

        # ------------------------------------------------------------------
        # 3) Detect JOINT mode: Truck+Trailer already moving needed machine
        # ------------------------------------------------------------------
        joint_possible = False
        primary_record = None
        needed_type = getattr(self, "needed_machinery", None)
        worksite_gps = self.gps_location

        if needed_type:
            co_ship_records = []
            for tj in self.winning_mission.transport_jobs:
                v = tj.transporting_vehicle
                if getattr(v, "machine_type", None) != "Truck":
                    continue
                trailer_obj = getattr(v, "contents", None)
                if trailer_obj is None or not hasattr(trailer_obj, "contents"):
                    continue
                inner = getattr(trailer_obj, "contents", []) or []
                for m in inner:
                    if (
                            m is not None
                            and getattr(m, "machine_type", None) == needed_type
                            and m in depot.machines
                            and tj.begin_location_gps == depot.gps_location
                            and tj.end_location_gps == worksite_gps
                    ):
                        co_ship_records.append(
                            {
                                "machine": m,
                                "transport_job": tj,
                                "truck": v,
                                "trailer": trailer_obj,
                            }
                        )

            # Deduplicate by machine object
            dedup = {}
            for rec in co_ship_records:
                dedup[id(rec["machine"])] = rec
            co_ship_records = list(dedup.values())

            if co_ship_records:
                primary_record = co_ship_records[0]
                joint_possible = True

        # ------------------------------------------------------------------
        # 4) If JOINT possible, try co-pack primary trailer
        # ------------------------------------------------------------------
        if joint_possible and primary_record is not None:
            primary_machine = primary_record["machine"]
            primary_trailer = primary_record["trailer"]

            try:
                Lp, Wp, Hp = getattr(
                    primary_trailer,
                    "overall_dimensions",
                    (0.0, 0.0, 0.0),
                )
                Lp = float(Lp)
                Wp = float(Wp)
                Hp = float(Hp)
            except Exception:
                print(
                    "[GoodsToPack] WARNING: primary trailer has invalid "
                    "overall_dimensions; falling back to separate tool packing."
                )
                joint_possible = False

        if joint_possible and primary_record is not None:
            primary_machine_item = item_from_machine(
                primary_machine,
                item_type_hint="vehicle",
            )
            tool_items = [
                item_from_machine(tool, item_type_hint="tool")
                for tool in tools_to_ship
            ]

            placements_primary, veh_unplaced, tools_unplaced = pack_single_trailer(
                vehicles=[primary_machine_item],
                tools=tool_items,
                L=Lp,
                W=Wp,
                H=Hp,
            )

            if veh_unplaced:
                print(
                    "[GoodsToPack] WARNING: needed machine did not fit in "
                    "the primary trailer for joint packing; falling back "
                    "to separate tool packing."
                )
                joint_possible = False
            else:
                primary_cargo_sources = [p.item.source for p in placements_primary]
                primary_trailer.contents = primary_cargo_sources

                remaining_tool_items = tools_unplaced
                remaining_tools = [it.source for it in remaining_tool_items]

                print(
                    f"[GoodsToPack] Joint packing: primary trailer "
                    f"{getattr(primary_trailer, 'trailer_id', None)} now carries "
                    f"{[getattr(x, 'machine_id', None) for x in primary_cargo_sources]}."
                )

                if not remaining_tools:
                    print(
                        "[GoodsToPack] All goods-to-pack tools were placed in the "
                        "existing mission trailer; no extra transports added."
                    )
                    return

                tools_to_ship = remaining_tools
                sorted_trailers_for_extras = [
                    tr for tr in sorted_trailers if tr is not primary_trailer
                ]
        else:
            sorted_trailers_for_extras = sorted_trailers

        # ------------------------------------------------------------------
        # 5) Pack remaining tools into extra trailers
        # ------------------------------------------------------------------
        if not tools_to_ship:
            return
        if not sorted_trailers_for_extras:
            generate_warning(
                "Goods-to-pack error",
                f"Depot '{getattr(depot, 'name', None)}' has no remaining "
                "trailers available for the goods-to-pack.",
            )
            return

        items = [
            item_from_machine(tool, item_type_hint="tool")
            for tool in tools_to_ship
        ]

        adapters = [
            TrailerAdapter(
                tr,
                trailer_id=tr.trailer_id or f"depot_trailer_{i}",
            )
            for i, tr in enumerate(sorted_trailers_for_extras)
        ]

        try:
            placements_per_trailer = pack_items_into_trailers(
                all_items=items,
                trailers=adapters,
            )
        except RuntimeError as exc:
            generate_warning(
                "Goods-to-pack packing error",
                f"Failed to pack requested tools into trailers:\n{exc}",
            )
            return

        used_indices = [
            idx for idx, placed in enumerate(placements_per_trailer) if placed
        ]
        if not used_indices:
            generate_warning(
                "Goods-to-pack error",
                "Packing algorithm did not place any tools into trailers. "
                "Please verify dimensions and tool IDs.",
            )
            return

        used_trailers = []
        for idx in used_indices:
            real_trailer = sorted_trailers_for_extras[idx]
            placed_items_here = placements_per_trailer[idx]
            cargo_machines = [p.item.source for p in placed_items_here]
            real_trailer.contents = cargo_machines
            used_trailers.append(real_trailer)

            print(
                f"[GoodsToPack] Extra trailer "
                f"{getattr(real_trailer, 'trailer_id', None)} "
                f"carries tools {[m.machine_id for m in cargo_machines]}"
            )

        if not used_trailers:
            return

        # ------------------------------------------------------------------
        # 6) Determine depot->worksite distance once (route_matrix reuse)
        # ------------------------------------------------------------------
        worksite_gps = self.gps_location
        depot_gps = depot.gps_location

        distance_m = 0.0
        rm = getattr(self, "route_matrix", None)
        objs = getattr(self, "route_objects", None)

        if rm is not None and objs:
            try:
                depot_idx = None
                for idx, obj in enumerate(objs):
                    if obj is depot:
                        depot_idx = idx
                        break

                if depot_idx is None:
                    print(
                        "[GoodsToPack] WARNING: current depot not found in "
                        "route_objects; falling back to Haversine distance."
                    )
                else:
                    cell = rm[depot_idx][0]
                    if cell == 0 or cell == 1000000000:
                        print(
                            "[GoodsToPack] WARNING: route_matrix entry "
                            f"[{depot_idx}][0] is degenerate ({cell}); "
                            "falling back to Haversine distance."
                        )
                    else:
                        _, distance_m = cell
            except Exception as exc:
                print(
                    "[GoodsToPack] WARNING: failed to read route_matrix, "
                    f"falling back to Haversine distance: {exc}"
                )
                distance_m = 0.0

        if distance_m <= 0.0:
            distance_m = Routing.HaversineDistance(
                depot_gps[0],
                depot_gps[1],
                worksite_gps[0],
                worksite_gps[1],
            ) * 1.3

        # ------------------------------------------------------------------
        # 7) Build TransportJobs with limited trucks and shuttling
        # ------------------------------------------------------------------
        extra_jobs = []

        if not depot_trucks:
            generate_warning(
                "Goods-to-pack error",
                f"Depot '{getattr(depot, 'name', None)}' has no trucks "
                "available to pull trailers for goods-to-pack.",
            )
            return

        # Helper to instantiate distinct topological states for ParaPy evaluation
        def clone_truck_state(source_truck, contents, gps_location):
            cls = type(source_truck)
            return cls(
                gps_location=gps_location,
                overall_dimensions=source_truck.overall_dimensions,
                mass=source_truck.mass,
                consumption_per_hour=source_truck.consumption_per_hour,
                worth=source_truck.worth,
                build_year=source_truck.build_year,
                machine_id=source_truck.machine_id,
                machine_type=getattr(source_truck, "machine_type", "Truck"),
                energy_source=getattr(source_truck, "energy_source", None),
                contents=contents,
            )

        # 7a) Isolate trucks already executing the primary joint mission
        busy_truck_ids = set()
        if joint_possible and primary_record is not None:
            busy_truck_ids.add(getattr(primary_record["truck"], "machine_id", None))

        free_trucks = [t for t in depot_trucks if getattr(t, "machine_id", None) not in busy_truck_ids]
        busy_trucks = [t for t in depot_trucks if getattr(t, "machine_id", None) in busy_truck_ids]

        # 7b) First wave: Free trucks transport extra trailers directly (Depot -> Worksite)
        num_free = len(free_trucks)
        first_wave_trailers = used_trailers[:num_free]
        remaining_trailers = used_trailers[num_free:]

        for trailer, truck in zip(first_wave_trailers, free_trucks):
            cloned_truck = clone_truck_state(truck, contents=trailer, gps_location=depot_gps)

            job = TransportJob(
                transporting_vehicle=cloned_truck,
                route_distance=float(distance_m),
                begin_location_gps=depot_gps,
                end_location_gps=worksite_gps,
            )
            extra_jobs.append(job)

        # 7c) Shuttling remaining trailers using sequential round-trips
        if remaining_trailers:
            # Determine the optimal shuttle truck.
            # Prefer a busy truck (already at worksite, needs to drive back empty first).
            if busy_trucks:
                shuttle_base = busy_trucks[0]
            else:
                shuttle_base = free_trucks[0]

            for trailer in remaining_trailers:
                # Leg 1: Worksite -> Depot (Truck EMPTY)
                empty_truck = clone_truck_state(shuttle_base, contents=None, gps_location=worksite_gps)
                back_job = TransportJob(
                    transporting_vehicle=empty_truck,
                    route_distance=float(distance_m),
                    begin_location_gps=worksite_gps,
                    end_location_gps=depot_gps,
                )
                extra_jobs.append(back_job)

                # Leg 2: Depot -> Worksite (Truck WITH next trailer)
                loaded_truck = clone_truck_state(shuttle_base, contents=trailer, gps_location=depot_gps)
                forth_job = TransportJob(
                    transporting_vehicle=loaded_truck,
                    route_distance=float(distance_m),
                    begin_location_gps=depot_gps,
                    end_location_gps=worksite_gps,
                )
                extra_jobs.append(forth_job)

            print(
                f"[GoodsToPack] Shuttled {len(remaining_trailers)} extra "
                f"trailer(s) from depot '{getattr(depot, 'name', None)}' "
                f"to worksite using truck {getattr(shuttle_base, 'machine_id', None)}."
            )

        if not extra_jobs:
            return

        print(
            f"[GoodsToPack] Added {len(extra_jobs)} extra transport jobs "
            "for goods-to-pack (including shuttle trips)."
        )

        old_jobs = list(self.winning_mission.transport_jobs)
        self.winning_mission.transport_jobs = old_jobs + extra_jobs

        # # ------------------------------------------------------------------
        # # 7) Build TransportJobs with limited trucks and shuttling
        # # ------------------------------------------------------------------
        # extra_jobs = []
        # num_trailers = len(used_trailers)
        # num_trucks = len(depot_trucks)
        #
        # if num_trucks <= 0:
        #     generate_warning(
        #         "Goods-to-pack error",
        #         f"Depot '{getattr(depot, 'name', None)}' has no trucks "
        #         "available to pull trailers for goods-to-pack.",
        #     )
        #     return
        #
        # # 7a) First wave: up to one trailer per available truck
        # first_wave_trailers = used_trailers[:num_trucks]
        # first_wave_trucks = depot_trucks[: len(first_wave_trailers)]
        #
        # for trailer, truck in zip(first_wave_trailers, first_wave_trucks):
        #     truck.contents = trailer
        #     truck.gps_location = depot_gps
        #
        #     job = TransportJob(
        #         transporting_vehicle=truck,
        #         route_distance=float(distance_m),
        #         begin_location_gps=depot_gps,
        #         end_location_gps=worksite_gps,
        #     )
        #     extra_jobs.append(job)
        #
        # # 7b) Remaining trailers (if any): shuttle with a single truck
        # remaining_trailers = used_trailers[num_trucks:]
        #
        # if remaining_trailers:
        #     shuttle_truck = depot_trucks[0]
        #
        #     # For each remaining trailer: EMPTY back to depot, then LOADED forth
        #     for trailer in remaining_trailers:
        #         # back: worksite -> depot (truck EMPTY)
        #         shuttle_truck.contents = None
        #         shuttle_truck.gps_location = worksite_gps
        #
        #         back_job = TransportJob(
        #             transporting_vehicle=shuttle_truck,
        #             route_distance=float(distance_m),
        #             begin_location_gps=worksite_gps,
        #             end_location_gps=depot_gps,
        #         )
        #         extra_jobs.append(back_job)
        #
        #         # forth: depot -> worksite (truck WITH next trailer)
        #         shuttle_truck.contents = trailer
        #         shuttle_truck.gps_location = depot_gps
        #
        #         forth_job = TransportJob(
        #             transporting_vehicle=shuttle_truck,
        #             route_distance=float(distance_m),
        #             begin_location_gps=depot_gps,
        #             end_location_gps=worksite_gps,
        #         )
        #         extra_jobs.append(forth_job)
        #
        #     print(
        #         f"[GoodsToPack] Shuttled {len(remaining_trailers)} extra "
        #         f"trailer(s) from depot '{getattr(depot, 'name', None)}' "
        #         f"to worksite using "
        #         f"truck {getattr(shuttle_truck, 'machine_id', None)}."
        #     )
        #
        # if not extra_jobs:
        #     return
        #
        # print(
        #     f"[GoodsToPack] Added {len(extra_jobs)} extra transport jobs "
        #     "for goods-to-pack (including any shuttle trips)."
        # )
        #
        # old_jobs = list(self.winning_mission.transport_jobs)
        # self.winning_mission.transport_jobs = old_jobs + extra_jobs

    def jobAnalyzer(self):
        """
        Determine the maximum number of machines that can work on a work
        site, based on the machine movement area and the site area, to not have
        an overcrowded work site.
        """
        area_factor = 0.1
        job_machines_areas = []

        for m in self.fleet.available_machines:
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
        """Visualize all trailers with cargo in the winning mission, laid out
        next to each other, using per-trailer optimal packing and real
        dimensions/colors with back-references to the actual assets.
        """
        if self.winning_mission is None:
            generate_warning(
                "Trailer arrangement",
                "No winning mission is available. Generate a strategy first.",
            )
            return

        # Collect trailers and their contents from winning_mission
        trailer_list: List[Trailer] = []
        cargo_per_trailer: List[List[object]] = []
        seen = set()

        for job in self.winning_mission.transport_jobs:
            veh = job.transporting_vehicle
            trailer_obj = getattr(veh, "contents", None)
            if trailer_obj is None:
                continue

            contents = getattr(trailer_obj, "contents", []) or []
            if not contents:
                continue  # skip empty trailers

            tid = getattr(trailer_obj, "trailer_id", None)
            key = tid if tid not in (None, "") else id(trailer_obj)
            if key in seen:
                continue
            seen.add(key)

            trailer_list.append(trailer_obj)
            cargo_per_trailer.append(list(contents))

        if not trailer_list:
            generate_warning(
                "Trailer arrangement",
                "No trailers with cargo were found in the winning mission.",
            )
            return

        # Build and display packed arrangement view
        from TrailerArrangement import WinningMissionTrailerPacking

        view = WinningMissionTrailerPacking(
            trailers=trailer_list,
            cargo_per_trailer=cargo_per_trailer,
        )
        display(view, mainloop=False)

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
        assets_list.extend(self.fleet.available_machines)
        assets_list.extend(self.fleet.available_trailers)

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


    @Part(parse=False)
    def Fleet(self):
        return self.fleet

    @Part
    def new_vehicle(self):
        # Creates an instance of Machine of which the attributes can be filled-in in the GUI, such that it can then be exported into the custom data JSON
        return Machine(machine_id="New Vehicle", is_available=True)

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
                "consumption_per_hour": m.consumption_per_hour,
                "is_available": str(m.is_available)
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
                        "is_available": str(trailer.is_available)
                    }
                )
        else:
            for asset in self.fleet.trailers:
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
                        "is_available": str(asset.is_available)
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
                        "engine_power": asset.engine_power,
                        "is_available": str(asset.is_available)
                    }
                )
        else:
            for asset in self.fleet.available_machines:
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
                        "engine_power": asset.engine_power,
                        "is_available": str(asset.is_available)
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
        "Tractor": 10,
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

    name: str = Input("")
    man_hours: float = Input(0.0)
    gps_location: Tuple[float, float] = Input((0.0, 0.0))

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
