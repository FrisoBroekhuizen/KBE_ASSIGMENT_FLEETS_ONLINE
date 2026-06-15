from typing import List, Tuple
import copy
import math

import numpy as np

import Routing
from assets import Vehicle, Tool


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

                # elif (
                #     type(obj_i).__name__ == "Truck"
                #     and type(obj_j).__name__ == "WorkJob"
                # ) or (
                #     type(obj_j).__name__ == "Truck"
                #     and type(obj_i).__name__ == "WorkJob"
                # ):
                #     if type(obj_i).__name__ == "Truck":
                #         if obj_i.contents is not None:
                #             if needed_machine not in [
                #                 c.machine_type
                #                 for c in obj_i.contents.contents
                #             ]:
                #                 matrix[i][j] = 0
                #         else:
                #             matrix[i][j] = 0
                #     elif type(obj_j).__name__ == "Truck":
                #         if obj_j.contents is not None:
                #             if needed_machine not in [
                #                 c.machine_type
                #                 for c in obj_j.contents.contents
                #             ]:
                #                 matrix[i][j] = 0
                #         else:
                #             matrix[i][j] = 0

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
    for m in app.fleet.machines:
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
    """
    Top-level mission generator.

    Parameters
    ----------
    app :
        MissionStrategyApp instance (or compatible object) that provides:
        - work_job, depots, road_parked, gps_location
        - constructMatrix(), filterMatrix(), routeMatrix(),
          viableMissionGenerator()
    MissionCls :
        Mission class to instantiate.
    TransportJobCls :
        TransportJob class to instantiate.
    VehicleCls :
        Vehicle base class (for isinstance checks).
    TrailerCls :
        Trailer class (for isinstance and construction).

    Returns
    -------
    list of MissionCls
    """

    # --- helper: can this specific truck carry this specific machine? ---
    def _can_trailer_carry(trailer, machine) -> bool:
        """Return True if `truck` (possibly with Trailer in contents)
        can carry `machine` based on simple bbox + weight checks."""

        # geometric: allow any orientation -> compare sorted dims
        m_dims = sorted(machine.overall_dimensions)
        t_dims = sorted(trailer.overall_dimensions)
        if any(md > td for md, td in zip(m_dims, t_dims)):
            return False

        # weight: if max_loading_weight > 0, enforce it
        if trailer.max_loading_weight and trailer.max_loading_weight > 0:
            if machine.mass > trailer.max_loading_weight:
                return False

        # If no trailer, treat as flatbed that can always carry
        # (adjust if needed)
        return True

    # --- helper: can this specific truck carry this specific machine? ---
    def _can_truck_carry(truck, machine) -> bool:
        """Return True if `truck` (possibly with Trailer in contents)
        can carry `machine` based on simple bbox + weight checks."""
        trailer = getattr(truck, "contents", None)

        # If there is an attached Trailer, enforce capacity:
        if isinstance(trailer, TrailerCls):
            # geometric: allow any orientation -> compare sorted dims
            m_dims = sorted(machine.overall_dimensions)
            t_dims = sorted(trailer.overall_dimensions)
            if any(md > td for md, td in zip(m_dims, t_dims)):
                return False

            # weight: if max_loading_weight > 0, enforce it
            if trailer.max_loading_weight and trailer.max_loading_weight > 0:
                if machine.mass > trailer.max_loading_weight:
                    return False

        # If no trailer, treat as flatbed that can always carry
        # (adjust if needed)
        return True

    # --- helper: create a fresh Truck instance for each leg ---
    def _clone_truck_for_leg(truck, *, contents=None, gps_location=None):
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

    preliminary_matrix, objects = construct_matrix(app)
    filtered_matrix, truck_indexes, direct_routes = filter_matrix(
        app, preliminary_matrix
    )
    route_mat = route_matrix(filtered_matrix)
    # --- NEW: store for later reuse (goods-to-pack) ---
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

    # ------------------------------------------------------------------
    # 1) direct routes: depot / machine straight to work site
    # ------------------------------------------------------------------
    for direct_route in direct_routes:
        i, j = direct_route
        obj = filtered_matrix[i][j][0]

        # If the needed vehicle is in a depot
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
                    # IMPORTANT: per-mission WorkJob copy
                    work_job = copy.copy(app.work_job)
                    work_job.assigned_vehicles = [machine]
                    work_job.assigned_tools = []
                    mission = MissionCls(
                        transport_jobs=[transport_job],
                        work_jobs=[work_job],
                        machines=[machine],
                    )
                    mission_list.append(mission)

        # If the needed vehicle is road-side parked
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

    # Rebuild objects list on same convention as constructMatrix:
    # [work_job, depots..., road_parked...]
    objects = [app.work_job]
    objects.extend(app.depots)
    objects.extend(app.road_parked)

    # ------------------------------------------------------------------
    # 2) routes that require a truck to go via a depot / road‑parked
    #    machine
    # ------------------------------------------------------------------
    for truck_route in truck_routes:
        # truck_route is
        # [[truck_origin_idx, depot_or_machine_idx],
        #  [depot_or_machine_idx, 0]]
        idx_truck_origin = truck_route[0][0]
        idx_machine_location = truck_route[0][1]
        idx_worksite_from_machine = truck_route[1][1]  # typically 0

        origin_obj = objects[idx_truck_origin]
        object_with_needed_machine = objects[idx_machine_location]
        needed_type = app.needed_machinery

        # ---- CASE A: needed machine is in a depot ----
        if type(object_with_needed_machine).__name__ == "Depot":
            depot_with_machines = object_with_needed_machine

            for machine in depot_with_machines.machines:
                if machine.machine_type != needed_type:
                    continue

                # choose feasible trucks at origin that can carry THIS
                # machine
                feasible_trucks: List = []
                feasible_trailers: List = []

                for m in object_with_needed_machine.trailers:
                    if _can_trailer_carry(m, machine):
                        feasible_trailers.append(m)

                # If the chosen truck is in a depot
                if type(origin_obj).__name__ == "Depot":
                    # Loop through all machine types
                    for m in origin_obj.trailers:
                        if _can_trailer_carry(m, machine):
                            feasible_trailers.append(m)
                    # Loop through all machine types
                    for m in origin_obj.machines:
                        if m.machine_type == "Truck":
                            feasible_trucks.append(m)
                else:
                    # origin is a single truck
                    if (
                        origin_obj.machine_type == "Truck"
                        and _can_truck_carry(origin_obj, machine)
                    ):
                        feasible_trucks.append(origin_obj)

                if not feasible_trucks:
                    # no truck+trailer at this origin that can carry this
                    # machine -> skip
                    continue

                # pick "best" truck among feasible ones (electric
                # preferred, then lowest consumption)
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

                if feasible_trailers:
                    best_trailer_for_machine = feasible_trailers[0]
                    best_trailer_for_machine.contents = [machine]
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

                # 1) leg: truck drives EMPTY from its origin to the depot
                empty_truck = _clone_truck_for_leg(
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
                route_distance = route_mat[
                    idx_machine_location
                ][idx_truck_origin]
                if route_distance != 0:
                    # depot-depot special case
                    route_distance = route_distance[1]
                transport_job_toDepot = TransportJobCls(
                    transporting_vehicle=empty_truck,
                    route_distance=route_distance,
                    begin_location_gps=empty_truck.gps_location,
                    end_location_gps=machine.gps_location,
                )

                # 2) leg: truck drives LOADED from depot to work site
                loaded_truck = _clone_truck_for_leg(
                    best_truck_for_machine,
                    contents=best_trailer_for_machine,
                    gps_location=machine.gps_location,
                )
                transport_job_toWorksite = TransportJobCls(
                    transporting_vehicle=loaded_truck,
                    route_distance=route_mat[truck_route[1][0]][
                        idx_worksite_from_machine
                    ][1],
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
                    transport_jobs=[
                        transport_job_toDepot,
                        transport_job_toWorksite,
                    ],
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

            # If truck is parked in a depot
            if type(origin_obj).__name__ == "Depot":
                # trailers go into feasible_trailers, not feasible_trucks
                for m in origin_obj.trailers:
                    if _can_trailer_carry(m, machine):
                        feasible_trailers.append(m)
                for m in origin_obj.machines:
                    if m.machine_type == "Truck":
                        feasible_trucks.append(m)
            else:  # If truck is road-side parked
                if (
                        origin_obj.machine_type == "Truck"
                        and _can_truck_carry(origin_obj, machine)
                ):
                    feasible_trucks.append(origin_obj)

                # If this road truck already has a trailer attached, consider its shape/capacity
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
                    getattr(
                        t,
                        "consumption_per_hour",
                        float("inf"),
                    ),  # extra safety
                )
            )

            best_truck_for_machine = feasible_trucks[0]

            # Choose a trailer *shape* (do NOT mutate the original object)
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
                base_id = getattr(
                    base_trailer,
                    "trailer_id",
                    "standard_issue_trailer",
                )
                base_color = getattr(base_trailer, "color", "Orange")
                base_has_ceiling = bool(
                    getattr(base_trailer, "has_ceiling", True)
                )
                base_max_load = float(
                    getattr(base_trailer, "max_loading_weight", 0.0)
                )
            else:
                print(
                    "No trailer present in the depot(s) or on the road; "
                    "using a standard issue trailer instead!"
                )
                base_dims = [
                    15.0,
                    machine.overall_dimensions[1] * 1.1,
                    machine.overall_dimensions[2] * 1.1,
                ]
                base_id = "standard_issue_trailer"
                base_color = "Orange"
                base_has_ceiling = True
                base_max_load = 0.0

            # ------------------------------------------------------------------
            # 1) leg: truck drives with an EMPTY trailer clone to the machine
            # ------------------------------------------------------------------
            empty_trailer = TrailerCls(
                contents=[],
                overall_dimensions=base_dims,
                trailer_id=base_id,
                color=base_color,
                gps_location=best_truck_for_machine.gps_location,
                max_loading_weight=base_max_load,
                has_ceiling=base_has_ceiling,
            )

            empty_truck = _clone_truck_for_leg(
                best_truck_for_machine,
                contents=empty_trailer,
                gps_location=best_truck_for_machine.gps_location,
            )

            if idx_machine_location < idx_truck_origin:
                print(
                    "Warning: the index order of this truck route falls in "
                    "the upper triangle; flipped the indices"
                )
                temp = idx_machine_location
                idx_machine_location = idx_truck_origin
                idx_truck_origin = temp
            if route_mat[idx_machine_location][idx_truck_origin] == 0:
                route_distance = 0
            else:
                route_distance = route_mat[idx_machine_location][
                    idx_truck_origin
                ][1]

            transport_job_toDepot = TransportJobCls(
                transporting_vehicle=empty_truck,
                route_distance=route_distance,
                begin_location_gps=empty_truck.gps_location,
                end_location_gps=machine.gps_location,
            )

            # ------------------------------------------------------------------
            # 2) leg: truck drives LOADED trailer clone from machine to worksite
            # ------------------------------------------------------------------
            loaded_trailer = TrailerCls(
                contents=[machine],
                overall_dimensions=base_dims,
                trailer_id=base_id,
                color=base_color,
                gps_location=machine.gps_location,
                max_loading_weight=base_max_load,
                has_ceiling=base_has_ceiling,
            )

            loaded_truck = _clone_truck_for_leg(
                best_truck_for_machine,
                contents=loaded_trailer,
                gps_location=machine.gps_location,
            )

            if (
                    route_mat[truck_route[1][0]][idx_worksite_from_machine]
                    == 0
            ):
                route_distance = 0
            else:
                route_distance = route_mat[truck_route[1][0]][
                    idx_worksite_from_machine
                ][1]

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
                transport_jobs=[
                    transport_job_toDepot,
                    transport_job_toWorksite,
                ],
                work_jobs=[work_job],
                machines=[machine],
            )
            mission_list.append(mission)

        # === DEBUG: summarize generated missions per machine ===
    print("=== DEBUG: generate_missions summary ===")
    from collections import Counter
    c = Counter()
    for m in mission_list:
        if not m.machines:
            continue
        mach = m.machines[0]
        key = (type(mach).__name__, getattr(mach, "machine_id", None))
        # distinguish direct vs truck+trailer by number of transport legs
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
    """
    Build a deadline-feasible mission by:
    1) For each candidate *machine* of the needed type (Vehicle OR Tool),
       taking the mission with the *shortest* total travel time.
       - Vehicles may have both direct and truck missions; we keep the
         shortest of these.
       - Tools only have truck missions; we just take those.
    2) Sorting these candidate machines by this shortest travel time.
    3) Determining how many machines X are *minimally* required to meet the
       man_hours within the deadline:
           ceil(man_hours / deadline_total_hours),
       then limiting this by jobAnalyzer() (site capacity).
    4) Starting with N = min(X, max_on_site, available) + 1 machines to
       compensate for travel time, and increasing N until the summed
       effective machine hours meet the required man_hours:
           eff_i = max(deadline_total_hours - travel_hours_i, 0.0)
           sum(eff_i for i in first N) >= man_hours
       or until we run out of machines.
    5) Combining those N machines (and their missions' transport jobs) into a
       single Mission.

    If no feasible combination exists (even with all candidates), we still
    return a best-effort combined mission with all candidates.
    """
    if not missions or deadline_total_hours <= 0.0:
        return missions

    work_job = app.work_job
    required_man_hours = float(work_job.man_hours)
    if required_man_hours <= 0.0:
        return missions

    needed_type = app.needed_machinery  # e.g. "Tractor"

    # --- 1) Minimal number of machines required from deadline alone ---
    minimal_needed_machines = max(
        1, int(math.ceil(required_man_hours / deadline_total_hours))
    )

    # --- 2) Max number of machines on site from area constraint ---
    max_on_site_raw = app.jobAnalyzer()  # can be float
    max_on_site = max(1, int(math.floor(max_on_site_raw)))

    # --- 3) For each machine (vehicle OR tool), pick mission with shortest
    #         travel time ---
    best_for_machine = {}  # machine -> (travel_time_hours, mission)

    for mission in missions:
        if not getattr(mission, "machines", None):
            continue

        machine = mission.machines[0]

        # Only consider machines of needed type (vehicles OR tools)
        if not isinstance(machine, (Vehicle, Tool)):
            continue
        if machine.machine_type != needed_type:
            continue

        # Travel time: sum all TransportJob.routeDuration [minutes] → hours
        travel_minutes = sum(
            tj.routeDuration for tj in getattr(
                mission,
                "transport_jobs",
                [],
            )
        )
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

    # sort by shortest travel time
    candidates.sort(key=lambda tup: tup[1])
    available = len(candidates)

    # --- 4) how many machines do we start with? ---
    base_X = min(minimal_needed_machines, max_on_site, available)
    if base_X < 1:
        base_X = 1

    # Start with the minimal required number of machines
    N = base_X

    def total_machine_hours(num: int) -> float:
        total = 0.0
        for k in range(num):
            _, travel_h, _ = candidates[k]
            eff = max(deadline_total_hours - travel_h, 0.0)
            total += eff
        return total

    # Grow N until we satisfy required_man_hours or we run out
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

    # --- DEBUG OUTPUT ---
    print("=== DEBUG: deadline candidates ===")
    for machine, travel_h, mission in candidates:
        print(
            type(machine).__name__,
            getattr(machine, "machine_id", None),
            "travel_h:",
            travel_h,
        )
    print("available:", available)
    print("N selected:", N)
    print(
        "selected machines:",
        [m.machine_id for (m, _, _) in selected],
    )

    # --- 5) Combine selected machines into a single mission ---
    combined_transport_jobs = []
    combined_machines = []

    for machine, _, mission in selected:
        combined_transport_jobs.extend(mission.transport_jobs)
        combined_machines.append(machine)

    MissionCls = type(missions[0])

    work_job_copy = copy.copy(work_job)

    # Split into vehicles vs tools for correct NOx/CO2/cost accounting
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



