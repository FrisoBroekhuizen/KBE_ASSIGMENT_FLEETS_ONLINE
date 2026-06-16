from typing import List, Tuple
import copy
import math

import numpy as np

import Routing
from assets import Vehicle, Tool
from Warning import generate_warning
from TrailerArrangement import (
    pack_single_trailer,
    pack_items_into_trailers,
    item_from_machine,
    TrailerAdapter,
)


# --- Global helper: create a fresh Truck instance for each leg ---
def clone_truck_for_leg(truck, *, contents=None, gps_location=None):
    """Create a new Truck instance with the same specs as `truck`,
    but with possibly different contents / gps_location.
    This is used such that the truck is empty before it picks up the
    machine, and is filled for the second part of the route.
    """
    cls = type(truck)
    return cls(
        gps_location=(
            gps_location
            if gps_location is not None
            else truck.gps_location
        ),
        overall_dimensions=truck.overall_dimensions,
        mass=truck.mass,
        consumption_per_hour=truck.consumption_per_hour,
        worth=truck.worth,
        build_year=truck.build_year,
        machine_id=truck.machine_id,
        machine_type=getattr(truck, "machine_type", "Truck"),
        energy_source=getattr(truck, "energy_source", None),
        contents=contents,
    )


# 1) Matrix construction -------------------------------------------------------
def construct_matrix(app) -> Tuple[np.ndarray, list]:
    """Standalone version of MissionStrategyApp.constructMatrix()."""
    matrix_size = 1 + len(app.depots) + len(app.road_parked)
    objects = [app.work_job]
    objects.extend(app.depots)
    objects.extend(app.road_parked)

    matrix = np.zeros((matrix_size, matrix_size), dtype=object)
    for i in range(matrix_size):
        for j in range(i + 1):
            matrix[i][j] = [objects[i], objects[j]]
    return matrix, objects


# 2) Filter matrix -------------------------------------------------------------
def filter_matrix(app, matrix):
    """Standalone version of MissionStrategyApp.filterMatrix()."""
    truckIndexes = []
    directRoutes = []
    needed_machine = app.needed_machinery

    for i in range(0, matrix.shape[0]):
        for j in range(i + 1):
            if i == j and i != 0:  # diagonal except worksite
                if type(matrix[i][j][0]).__name__ == "Depot":
                    if not (
                            needed_machine
                            in matrix[i][j][0].available_machine_types
                            and "Truck" in matrix[i][j][0].available_machine_types
                    ):
                        matrix[i][j] = 0
                else:
                    matrix[i][j] = 0
            elif i == j and i == 0:
                matrix[i][j] = 0

            if j == 0 and i != 0:  # direct routes to worksite
                obj = matrix[i][j][0]
                if type(obj).__name__ == "Depot":
                    if needed_machine in obj.available_machine_types:
                        directRoutes.append([i, 0])
                elif obj.machine_type == needed_machine:
                    directRoutes.append([i, 0])

                if type(obj).__name__ == "Depot":
                    if "Truck" in obj.available_machine_types:
                        truckIndexes.append(i)
                elif obj.machine_type == "Truck":
                    truckIndexes.append(i)

            if matrix[i][j] != 0:  # routes not towards work site
                obj_i, obj_j = matrix[i][j]

                # Delete if Truck -> other Truck
                if (
                        type(obj_i).__name__ == type(obj_j).__name__
                        and type(obj_i).__name__ == "Truck"
                ):
                    matrix[i][j] = 0

                # Delete road-side Truck <-> WorkJob without needed machine
                elif (
                        type(obj_i).__name__ == "Truck"
                        and type(obj_j).__name__ == "WorkJob"
                ) or (
                        type(obj_j).__name__ == "Truck"
                        and type(obj_i).__name__ == "WorkJob"
                ):
                    if type(obj_i).__name__ == "Truck":
                        if obj_i.contents is not None:
                            if needed_machine not in [
                                c.machine_type
                                for c in obj_i.contents.contents
                                if c is not None
                            ]:
                                matrix[i][j] = 0
                        else:
                            matrix[i][j] = 0
                    elif type(obj_j).__name__ == "Truck":
                        if obj_j.contents is not None:
                            if needed_machine not in [
                                c.machine_type
                                for c in obj_j.contents.contents
                                if c is not None
                            ]:
                                matrix[i][j] = 0
                        else:
                            matrix[i][j] = 0

                # Delete depot if needed machine & Truck not in depot
                elif type(obj_i).__name__ == "Depot":
                    if (
                            needed_machine
                            not in obj_i.available_machine_types
                            and "Truck" not in obj_i.available_machine_types
                    ):
                        matrix[i][j] = 0
                    elif type(obj_j).__name__ == "Depot":
                        if (
                                needed_machine
                                not in obj_j.available_machine_types
                                and "Truck"
                                not in obj_j.available_machine_types
                        ):
                            matrix[i][j] = 0
                    elif needed_machine not in obj_i.available_machine_types:
                        if type(obj_j).__name__ == "WorkJob":
                            matrix[i][j] = 0
                        elif obj_j.machine_type != needed_machine:
                            matrix[i][j] = 0

                elif type(obj_j).__name__ == "Depot":
                    if (
                            needed_machine
                            not in obj_j.available_machine_types
                            and "Truck" not in obj_j.available_machine_types
                    ):
                        matrix[i][j] = 0
                    elif type(obj_i).__name__ == "Depot":
                        if (
                                needed_machine
                                not in obj_i.available_machine_types
                                and "Truck"
                                not in obj_i.available_machine_types
                        ):
                            matrix[i][j] = 0
                    elif needed_machine not in obj_j.available_machine_types:
                        if type(obj_i).__name__ == "WorkJob":
                            matrix[i][j] = 0
                        elif obj_i.machine_type != needed_machine:
                            matrix[i][j] = 0

            if matrix[i][j] != 0:
                if i > 1 + len(app.depots):
                    obj_i, obj_j = matrix[i][j]
                    if (
                            type(obj_i).__name__ not in (needed_machine, "Truck")
                            and type(obj_j).__name__
                            not in (needed_machine, "Truck")
                    ):
                        matrix[i][j] = 0
    return matrix, truckIndexes, directRoutes


# 3) Route matrix --------------------------------------------------------------
def route_matrix(filteredMatrix):
    """Standalone version of MissionStrategyApp.routeMatrix()."""
    routeMatrix = np.zeros(
        (filteredMatrix.shape[0], filteredMatrix.shape[1]),
        dtype=object,
    )

    for i in range(filteredMatrix.shape[0]):
        for j in range(i + 1):
            if filteredMatrix[i][j] != 0:
                if i == j:
                    routeMatrix[i][j] = 0
                else:
                    routeDuration, route_distance, _ = Routing.ComputeRoute(
                        filteredMatrix[i][j][0].gps_location,
                        filteredMatrix[i][j][1].gps_location,
                        machine_type="Truck",
                    )
                    routeMatrix[i][j] = [routeDuration, route_distance]
            else:
                routeMatrix[i][j] = 1000000000
    return routeMatrix


# 4) Truck routes (viable mission routes) --------------------------------------
def viable_mission_generator(
        app,
        routeMatrix,
        filteredMatrix,
        objects,
        truckIndexes,
        directRoutes,
):
    """Standalone version of MissionStrategyApp.viableMissionGenerator()."""
    max_worksite_machines = app.jobAnalyzer()
    possibleMachines = []
    for m in app.fleet.available_machines:
        if m.machine_type == app.needed_machinery:
            possibleMachines.append(m)
    max_number_of_machines = min(
        max_worksite_machines, len(possibleMachines)
    )
    max_number_of_machines = 1  # current logic

    needed_machine = app.needed_machinery
    truckRoutes = []
    for direct_route in directRoutes:
        tractor_i = direct_route[0]
        shortest_distance = 1000000000
        closest_truck_index = 0
        for truck_index in truckIndexes:
            if (
                    routeMatrix[tractor_i][truck_index] != 0
                    and routeMatrix[tractor_i][truck_index] != 1000000000
            ):
                distance = routeMatrix[tractor_i][truck_index][1]
            elif routeMatrix[tractor_i][truck_index] == 1000000000:
                distance = 1000000000
            else:
                distance = 0
            if distance < shortest_distance:
                closest_truck_index = truck_index
                shortest_distance = distance

        truckRoutes.append(
            [[closest_truck_index, tractor_i], [tractor_i, 0]]
        )
    return truckRoutes


# 5) Full mission generation (public entry) ------------------------------------
def generate_missions(
        app,
        MissionCls,
        TransportJobCls,
        VehicleCls,
        TrailerCls,
) -> List:
    """Top-level mission generator."""

    def _can_trailer_carry(trailer, machine) -> bool:
        """Return True if `truck` (possibly with Trailer in contents)
        can carry `machine` based on simple bbox + weight checks."""
        m_dims = sorted(machine.overall_dimensions)
        t_dims = sorted(trailer.overall_dimensions)
        if any(md > td for md, td in zip(m_dims, t_dims)):
            return False
        if trailer.max_loading_weight and trailer.max_loading_weight > 0:
            if machine.mass > trailer.max_loading_weight:
                return False
        return True

    def _can_truck_carry(truck, machine) -> bool:
        """Return True if `truck` (possibly with Trailer in contents)
        can carry `machine` based on simple bbox + weight checks."""
        trailer = getattr(truck, "contents", None)
        if isinstance(trailer, TrailerCls):
            m_dims = sorted(machine.overall_dimensions)
            t_dims = sorted(trailer.overall_dimensions)
            if any(md > td for md, td in zip(m_dims, t_dims)):
                return False
            if trailer.max_loading_weight and trailer.max_loading_weight > 0:
                if machine.mass > trailer.max_loading_weight:
                    return False
        return True

    preliminary_matrix, objects = construct_matrix(app)
    filtered_matrix, truck_indexes, direct_routes = filter_matrix(
        app, preliminary_matrix
    )
    route_mat = route_matrix(filtered_matrix)
    app.route_matrix = route_mat
    app.route_objects = objects

    truck_routes = viable_mission_generator(
        app,
        route_mat,
        filtered_matrix,
        objects,
        truck_indexes,
        direct_routes,
    )
    mission_list: List = []

    # 1) direct routes: depot / machine straight to work site
    for direct_route in direct_routes:
        i, j = direct_route
        obj = filtered_matrix[i][j][0]

        if type(obj).__name__ == "Depot":
            for machine in obj.machines:
                if (
                        machine.machine_type
                        == app.needed_machinery
                        and isinstance(machine, VehicleCls)
                ):
                    transport_job = TransportJobCls(
                        transporting_vehicle=machine,
                        route_distance=route_mat[i][j][1],
                        begin_location_gps=machine.gps_location,
                        end_location_gps=app.gps_location,
                    )
                    work_job = copy.copy(app.work_job)
                    work_job.assigned_vehicles = [machine]
                    work_job.assigned_tools = []
                    mission = MissionCls(
                        transport_jobs=[transport_job],
                        work_jobs=[work_job],
                        machines=[machine],
                    )
                    mission_list.append(mission)

        elif (
                obj.machine_type == app.needed_machinery
                and isinstance(obj, VehicleCls)
        ):
            transport_job = TransportJobCls(
                transporting_vehicle=obj,
                route_distance=route_mat[i][j][1],
                begin_location_gps=obj.gps_location,
                end_location_gps=app.gps_location,
            )
            work_job = copy.copy(app.work_job)
            work_job.assigned_vehicles = [obj]
            work_job.assigned_tools = []
            mission = MissionCls(
                transport_jobs=[transport_job],
                work_jobs=[work_job],
                machines=[obj],
            )
            mission_list.append(mission)

    objects = [app.work_job]
    objects.extend(app.depots)
    objects.extend(app.road_parked)

    # 2) routes that require a truck to go via a depot / road‑parked machine
    for truck_route in truck_routes:
        idx_truck_origin = truck_route[0][0]
        idx_machine_location = truck_route[0][1]
        idx_worksite_from_machine = truck_route[1][1]

        origin_obj = objects[idx_truck_origin]
        object_with_needed_machine = objects[idx_machine_location]
        needed_type = app.needed_machinery

        # ---- CASE A: needed machine is in a depot ----
        if type(object_with_needed_machine).__name__ == "Depot":
            depot_with_machines = object_with_needed_machine

            for machine in depot_with_machines.machines:
                if machine.machine_type != needed_type:
                    continue

                feasible_trucks: List = []
                feasible_trailers: List = []

                for m in object_with_needed_machine.trailers:
                    if _can_trailer_carry(m, machine):
                        feasible_trailers.append(m)

                if type(origin_obj).__name__ == "Depot":
                    for m in origin_obj.trailers:
                        if _can_trailer_carry(m, machine):
                            feasible_trailers.append(m)
                    for m in origin_obj.machines:
                        if m.machine_type == "Truck":
                            feasible_trucks.append(m)
                else:
                    if (
                            origin_obj.machine_type == "Truck"
                            and _can_truck_carry(origin_obj, machine)
                    ):
                        feasible_trucks.append(origin_obj)

                if not feasible_trucks:
                    continue

                feasible_trucks.sort(
                    key=lambda t: (
                        getattr(t, "energy_source", "Diesel")
                        != "Electric",
                        t.consumption_per_hour,
                    )
                )
                best_truck_for_machine = feasible_trucks[0]

                if best_truck_for_machine.contents is not None:
                    if _can_truck_carry(
                            best_truck_for_machine.contents,
                            machine,
                    ):
                        feasible_trailers.append(
                            best_truck_for_machine.contents
                        )

                # DO NOT MUTATE THE DEPOT TRAILER - CLONE IT
                if feasible_trailers:
                    base_trailer = feasible_trailers[0]
                    best_trailer_for_machine = TrailerCls(
                        contents=[machine],
                        overall_dimensions=base_trailer.overall_dimensions,
                        trailer_id=getattr(base_trailer, "trailer_id", "standard_issue_trailer"),
                        color=getattr(base_trailer, "color", "Orange"),
                        gps_location=machine.gps_location,
                        max_loading_weight=getattr(base_trailer, "max_loading_weight", 0.0),
                        has_ceiling=getattr(base_trailer, "has_ceiling", True)
                    )
                else:
                    print(
                        "No trailer present in the depot(s); using a "
                        "standard issue trailer instead!"
                    )
                    best_trailer_for_machine = TrailerCls(
                        contents=[machine],
                        overall_dimensions=[
                            15,
                            machine.overall_dimensions[0] * 1.1,
                            machine.overall_dimensions[0] * 1.1,
                        ],
                        trailer_id="standard_issue_trailer",
                        color="Orange",
                        gps_location=best_truck_for_machine.gps_location,
                    )

                empty_truck = clone_truck_for_leg(
                    best_truck_for_machine,
                    contents=best_truck_for_machine.contents,
                    gps_location=best_truck_for_machine.gps_location,
                )
                if idx_machine_location < idx_truck_origin:
                    print(
                        "Warning: the index order of this truck route falls in the upper triangle; flipped the indices")
                    temp = idx_machine_location
                    idx_machine_location = idx_truck_origin
                    idx_truck_origin = temp
                route_distance = route_mat[idx_machine_location][idx_truck_origin]
                if route_distance != 0:
                    route_distance = route_distance[1]
                transport_job_toDepot = TransportJobCls(
                    transporting_vehicle=empty_truck,
                    route_distance=route_distance,
                    begin_location_gps=empty_truck.gps_location,
                    end_location_gps=machine.gps_location,
                )

                loaded_truck = clone_truck_for_leg(
                    best_truck_for_machine,
                    contents=best_trailer_for_machine,
                    gps_location=machine.gps_location,
                )
                transport_job_toWorksite = TransportJobCls(
                    transporting_vehicle=loaded_truck,
                    route_distance=route_mat[truck_route[1][0]][idx_worksite_from_machine][1],
                    begin_location_gps=loaded_truck.gps_location,
                    end_location_gps=app.gps_location,
                )

                work_job = copy.copy(app.work_job)
                if isinstance(machine, VehicleCls):
                    work_job.assigned_vehicles = [machine]
                    work_job.assigned_tools = []
                else:
                    work_job.assigned_tools = [machine]
                    work_job.assigned_vehicles = []

                mission = MissionCls(
                    transport_jobs=[transport_job_toDepot, transport_job_toWorksite],
                    work_jobs=[work_job],
                    machines=[machine],
                )
                mission_list.append(mission)

        # ---- CASE B: needed machine is road‑parked (not in depot) ----
        else:
            machine = object_with_needed_machine
            if machine.machine_type != needed_type:
                continue

            feasible_trucks: List = []
            feasible_trailers: List = []

            if type(origin_obj).__name__ == "Depot":
                for m in origin_obj.trailers:
                    if _can_trailer_carry(m, machine):
                        feasible_trailers.append(m)
                for m in origin_obj.machines:
                    if m.machine_type == "Truck":
                        feasible_trucks.append(m)
            else:
                if (
                        origin_obj.machine_type == "Truck"
                        and _can_truck_carry(origin_obj, machine)
                ):
                    feasible_trucks.append(origin_obj)

                base_trailer = getattr(origin_obj, "contents", None)
                if base_trailer is not None and _can_trailer_carry(
                        base_trailer,
                        machine,
                ):
                    feasible_trailers.append(base_trailer)

            if not feasible_trucks:
                continue

            feasible_trucks.sort(
                key=lambda t: (
                    getattr(t, "energy_source", "Diesel") != "Electric",
                    getattr(t, "consumption_per_hour", float("inf")),
                )
            )

            best_truck_for_machine = feasible_trucks[0]

            if feasible_trailers:
                base_trailer = feasible_trailers[0]
                base_dims = list(
                    getattr(
                        base_trailer,
                        "overall_dimensions",
                        (
                            15.0,
                            machine.overall_dimensions[1] * 1.1,
                            machine.overall_dimensions[2] * 1.1,
                        ),
                    )
                )
                base_id = getattr(base_trailer, "trailer_id", "standard_issue_trailer")
                base_color = getattr(base_trailer, "color", "Orange")
                base_has_ceiling = bool(getattr(base_trailer, "has_ceiling", True))
                base_max_load = float(getattr(base_trailer, "max_loading_weight", 0.0))
            else:
                base_dims = [
                    15.0,
                    machine.overall_dimensions[1] * 1.1,
                    machine.overall_dimensions[2] * 1.1,
                ]
                base_id = "standard_issue_trailer"
                base_color = "Orange"
                base_has_ceiling = True
                base_max_load = 0.0

            empty_trailer = TrailerCls(
                contents=[],
                overall_dimensions=base_dims,
                trailer_id=base_id,
                color=base_color,
                gps_location=best_truck_for_machine.gps_location,
                max_loading_weight=base_max_load,
                has_ceiling=base_has_ceiling,
            )

            empty_truck = clone_truck_for_leg(
                best_truck_for_machine,
                contents=empty_trailer,
                gps_location=best_truck_for_machine.gps_location,
            )

            if idx_machine_location < idx_truck_origin:
                temp = idx_machine_location
                idx_machine_location = idx_truck_origin
                idx_truck_origin = temp
            if route_mat[idx_machine_location][idx_truck_origin] == 0:
                route_distance = 0
            else:
                route_distance = route_mat[idx_machine_location][idx_truck_origin][1]

            transport_job_toDepot = TransportJobCls(
                transporting_vehicle=empty_truck,
                route_distance=route_distance,
                begin_location_gps=empty_truck.gps_location,
                end_location_gps=machine.gps_location,
            )

            loaded_trailer = TrailerCls(
                contents=[machine],
                overall_dimensions=base_dims,
                trailer_id=base_id,
                color=base_color,
                gps_location=machine.gps_location,
                max_loading_weight=base_max_load,
                has_ceiling=base_has_ceiling,
            )

            loaded_truck = clone_truck_for_leg(
                best_truck_for_machine,
                contents=loaded_trailer,
                gps_location=machine.gps_location,
            )

            if route_mat[truck_route[1][0]][idx_worksite_from_machine] == 0:
                route_distance = 0
            else:
                route_distance = route_mat[truck_route[1][0]][idx_worksite_from_machine][1]

            transport_job_toWorksite = TransportJobCls(
                transporting_vehicle=loaded_truck,
                route_distance=route_distance,
                begin_location_gps=loaded_truck.gps_location,
                end_location_gps=app.gps_location,
            )

            work_job = copy.copy(app.work_job)
            work_job.assigned_vehicles = [machine]
            work_job.assigned_tools = []
            mission = MissionCls(
                transport_jobs=[transport_job_toDepot, transport_job_toWorksite],
                work_jobs=[work_job],
                machines=[machine],
            )
            mission_list.append(mission)

    print("=== DEBUG: generate_missions summary ===")
    from collections import Counter
    c = Counter()
    for m in mission_list:
        if not m.machines:
            continue
        mach = m.machines[0]
        key = (type(mach).__name__, getattr(mach, "machine_id", None))
        kind = "direct" if len(m.transport_jobs) == 1 else "truck+trailer"
        c[(key, kind)] += 1

    for (mach_info, kind), n in c.items():
        (cls_name, mid) = mach_info
        print(f"  {cls_name} {mid}: {kind} missions = {n}")

    print("=== END DEBUG generate_missions summary ===")

    return mission_list


def deadline_restricted_mission_generator(
        app,
        missions: List,
        deadline_total_hours: float,
) -> List:
    """Build a deadline-feasible mission and stitch spatial gaps."""
    if not missions or deadline_total_hours <= 0.0:
        return missions

    work_job = app.work_job
    required_man_hours = float(work_job.man_hours)
    if required_man_hours <= 0.0:
        return missions

    needed_type = app.needed_machinery

    minimal_needed_machines = max(1, int(math.ceil(required_man_hours / deadline_total_hours)))
    max_on_site_raw = app.jobAnalyzer()
    max_on_site = max(1, int(math.floor(max_on_site_raw)))

    best_for_machine = {}
    for mission in missions:
        if not getattr(mission, "machines", None):
            continue

        machine = mission.machines[0]
        if not isinstance(machine, (Vehicle, Tool)) or machine.machine_type != needed_type:
            continue

        travel_minutes = sum(tj.routeDuration for tj in getattr(mission, "transport_jobs", []))
        travel_hours = travel_minutes / 60.0

        prev = best_for_machine.get(machine)
        if (prev is None) or (travel_hours < prev[0]):
            best_for_machine[machine] = (travel_hours, mission)

    candidates = [
        (machine, travel_h, mission)
        for machine, (travel_h, mission) in best_for_machine.items()
    ]

    if not candidates:
        return missions

    candidates.sort(key=lambda tup: tup[1])
    available = len(candidates)

    base_X = min(minimal_needed_machines, max_on_site, available)
    if base_X < 1:
        base_X = 1

    N = base_X

    def total_machine_hours(num: int) -> float:
        total = 0.0
        for k in range(num):
            _, travel_h, _ = candidates[k]
            eff = max(deadline_total_hours - travel_h, 0.0)
            total += eff
        return total

    while N <= available and total_machine_hours(N) < required_man_hours:
        N += 1

    if N > available:
        N = available

    selected = candidates[:N]
    sum_eff = total_machine_hours(N)
    print(
        f"Required man_hours: {required_man_hours}, "
        f"effective-hours from selected: {sum_eff}"
    )

    # 5) Combine selected machines into a single mission and stitch gaps
    raw_combined_transport_jobs = []
    combined_machines = []

    for machine, _, mission in selected:
        raw_combined_transport_jobs.extend(mission.transport_jobs)
        combined_machines.append(machine)

    MissionCls = type(missions[0])
    TransportJobCls = type(raw_combined_transport_jobs[0]) if raw_combined_transport_jobs else None

    # Identify and insert spatial returns (e.g. driving empty from worksite to depot)
    combined_transport_jobs = []
    for job in raw_combined_transport_jobs:
        if not combined_transport_jobs:
            combined_transport_jobs.append(job)
            continue

        prev_job = combined_transport_jobs[-1]
        prev_veh = prev_job.transporting_vehicle
        curr_veh = job.transporting_vehicle

        prev_id = getattr(prev_veh, "machine_id", None)
        curr_id = getattr(curr_veh, "machine_id", None)

        if prev_id and curr_id and prev_id == curr_id and getattr(prev_veh, "machine_type", "") == "Truck":
            gap_start = prev_job.end_location_gps
            gap_end = job.begin_location_gps

            # Check for substantial gap (> 1e-5 degrees ~ 1 meter)
            if abs(gap_start[0] - gap_end[0]) > 1e-5 or abs(gap_start[1] - gap_end[1]) > 1e-5:
                dist = Routing.HaversineDistance(gap_start[0], gap_start[1], gap_end[0], gap_end[1]) * 1.3
                empty_truck = clone_truck_for_leg(curr_veh, contents=None, gps_location=gap_start)
                bridge_job = TransportJobCls(
                    transporting_vehicle=empty_truck,
                    route_distance=dist,
                    begin_location_gps=gap_start,
                    end_location_gps=gap_end
                )
                combined_transport_jobs.append(bridge_job)

        combined_transport_jobs.append(job)

    work_job_copy = copy.copy(work_job)
    vehicles = [m for m in combined_machines if isinstance(m, Vehicle)]
    tools = [m for m in combined_machines if isinstance(m, Tool)]
    work_job_copy.assigned_vehicles = vehicles
    work_job_copy.assigned_tools = tools

    combined_mission = MissionCls(
        transport_jobs=combined_transport_jobs,
        work_jobs=[work_job_copy],
        machines=combined_machines,
    )

    return [combined_mission]


def add_goods_transport_to_winning_mission(app, TransportJobCls) -> None:
    """Post-process the chosen winning mission by adding extra transport
    jobs for user-specified 'goods to pack'.
    """
    if app.winning_mission is None:
        return
    if not app.goods_to_pack_ids:
        return
    if app.work_job is None:
        generate_warning(
            "Goods-to-pack error",
            "No work job is defined, so the destination for "
            "goods-to-pack cannot be determined.",
        )
        return

    requested_ids = set(str(x) for x in app.goods_to_pack_ids)
    candidate_depots = []
    depot_tools_map = {}

    for dep in app.depots:
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

    joint_possible = False
    primary_record = None
    needed_type = getattr(app, "needed_machinery", None)
    worksite_gps = app.gps_location

    if needed_type:
        co_ship_records = []
        for tj in app.winning_mission.transport_jobs:
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

        dedup = {}
        for rec in co_ship_records:
            dedup[id(rec["machine"])] = rec
        co_ship_records = list(dedup.values())

        if co_ship_records:
            primary_record = co_ship_records[0]
            joint_possible = True

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

            if not remaining_tools:
                return

            tools_to_ship = remaining_tools
            sorted_trailers_for_extras = [
                tr for tr in sorted_trailers if tr is not primary_trailer
            ]
    else:
        sorted_trailers_for_extras = sorted_trailers

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

    if not used_trailers:
        return

    worksite_gps = app.gps_location
    depot_gps = depot.gps_location

    distance_m = 0.0
    rm = getattr(app, "route_matrix", None)
    objs = getattr(app, "route_objects", None)

    if rm is not None and objs:
        try:
            depot_idx = None
            for idx, obj in enumerate(objs):
                if obj is depot:
                    depot_idx = idx
                    break

            if depot_idx is not None:
                cell = rm[depot_idx][0]
                if cell not in (0, 1000000000):
                    _, distance_m = cell
        except Exception:
            distance_m = 0.0

    if distance_m <= 0.0:
        distance_m = Routing.HaversineDistance(
            depot_gps[0],
            depot_gps[1],
            worksite_gps[0],
            worksite_gps[1],
        ) * 1.3

    extra_jobs = []

    if not depot_trucks:
        generate_warning(
            "Goods-to-pack error",
            f"Depot '{getattr(depot, 'name', None)}' has no trucks "
            "available to pull trailers for goods-to-pack.",
        )
        return

    busy_truck_ids = set()
    if joint_possible and primary_record is not None:
        busy_truck_ids.add(getattr(primary_record["truck"], "machine_id", None))

    free_trucks = [t for t in depot_trucks if getattr(t, "machine_id", None) not in busy_truck_ids]
    busy_trucks = [t for t in depot_trucks if getattr(t, "machine_id", None) in busy_truck_ids]

    num_free = len(free_trucks)
    first_wave_trailers = used_trailers[:num_free]
    remaining_trailers = used_trailers[num_free:]

    for trailer, truck in zip(first_wave_trailers, free_trucks):
        cloned_truck = clone_truck_for_leg(truck, contents=trailer, gps_location=depot_gps)
        job = TransportJobCls(
            transporting_vehicle=cloned_truck,
            route_distance=float(distance_m),
            begin_location_gps=depot_gps,
            end_location_gps=worksite_gps,
        )
        extra_jobs.append(job)

    if remaining_trailers:
        if busy_trucks:
            shuttle_base = busy_trucks[0]
        else:
            shuttle_base = free_trucks[0]

        for trailer in remaining_trailers:
            empty_truck = clone_truck_for_leg(shuttle_base, contents=None, gps_location=worksite_gps)
            back_job = TransportJobCls(
                transporting_vehicle=empty_truck,
                route_distance=float(distance_m),
                begin_location_gps=worksite_gps,
                end_location_gps=depot_gps,
            )
            extra_jobs.append(back_job)

            loaded_truck = clone_truck_for_leg(shuttle_base, contents=trailer, gps_location=depot_gps)
            forth_job = TransportJobCls(
                transporting_vehicle=loaded_truck,
                route_distance=float(distance_m),
                begin_location_gps=depot_gps,
                end_location_gps=worksite_gps,
            )
            extra_jobs.append(forth_job)

    if not extra_jobs:
        return

    old_jobs = list(app.winning_mission.transport_jobs)
    app.winning_mission.transport_jobs = old_jobs + extra_jobs



