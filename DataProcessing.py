import requests
import json
import numpy as np
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
from Warning import generate_warning
from Depot import Depot

def GetFleetsOnlineData(app):
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

    # Types: Aanhanger licht, Aanhanger zwaar, Kranen, Tractor, Vrachtwagens
    # Note: Fleets-Online uses Dutch names, the above types translate to:
    # Trailer Light, Trailer Heavy, Cranes, Tractor, Trucks
    assets = []
    assets.append(
        requests.get(
            f"{base_url}/equipment",
            headers=headers,
            params={
                "pageSize": 1000,
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
                "pageSize": 1000,
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
                "pageSize": 1000,
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
                "pageSize": 1000,
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
                "pageSize": 1000,
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
        try:
            if poi["orientation"] == None:
                orientation = 0
            else:
                orientation = poi["orientation"]
        except:
            orientation = 0
        # Check if the location address and shapeData is defined
        if poi["address"] is not None and poi["shapeData"] is not None:
            # For the time being to put all FleetsOnline assets
            # in the depot
            poi["address"]["lat"] = app.standard_location[0]
            poi["address"]["lon"] = app.standard_location[1]
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
                        "lat": app.standard_location[0],
                        "lon": app.standard_location[1],
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
                            "lat": app.standard_location[0],
                            "lon": app.standard_location[1],
                        },
                        "overall_dimensions": standard_dimensions[
                            asset["type"]["name"]
                        ],
                        "color": "yellow",
                        "is_available": "True"
                    }
                )
            else:
                if asset["kwh"] is None:
                    engine_power = 50
                else:
                    engine_power = asset["kwh"]
                data.append(
                    {
                        "type": "asset",
                        "id": asset["name"],
                        "name": asset["type"]["name"],
                        "build_year": asset["buildYear"],
                        "gps_location": {
                            "lat": app.standard_location[0],
                            "lon": app.standard_location[1],
                        },
                        "overall_dimensions": standard_dimensions[
                            asset["type"]["name"]
                        ],
                        "color": "yellow",
                        "fuel_type": asset["fuelType"]["name"],
                        "emission_class_version": "StageIIIB",
                        # Common emission class for heavy machinery, standard input as our Fleets-Online data does not have emission_class assigned
                        "consumption_per_hour": cons,
                        "engine_power": engine_power,
                        "is_available": "True"
                    }
                )

    # Write FleetsOnline data to FleetsOnlineData.json file
    with open("FleetsOnlineData.json", "w") as f:
        json.dump(data, f, indent=4)

    return pois, assets

def ReadData(app, use_fleets_data, workjob, fleet):
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

                app.depots.append(depot)

            # ---------------- Work site ----------------
            elif app.worksite_name in l["name"]:
                if l["gps_location"] is None:
                    print("One of the worksites has no location data")
                    workjob.gps_location = (
                        app.standard_locations["Breda"][0],
                        app.standard_locations["Breda"][1],
                    )
                else:
                    workjob.gps_location = (
                        l["gps_location"]["lat"],
                        l["gps_location"]["lon"],
                    )

                workjob.needed_machine = app.needed_machinery
                workjob.man_hours = app.man_hours
                workjob.name = l["name"]

                app.work_job = workjob
                app.gps_location = workjob.gps_location

                # Use only L, W from overall_dimensions; ignore height
                # for site area
                dims = l.get(
                    "overall_dimensions",
                    [100.0, 100.0, 0.0],
                )
                app.site_dimensions = (
                    float(dims[0]),
                    float(dims[1]),
                )

                # Orientation is optional; default to 0 if not in JSON
                app.orientation = float(l.get("orientation", 0.0))

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

            try:
                if l["is_available"] == "True":
                    m.is_available = True
                else:
                    m.is_available = False
            except:
                m.is_available = True

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
                fleet.trailers.append(m)
                if not np.all(m.overall_dimensions):
                    generate_warning(
                        "Warning: Dimension(s) missing",
                        f"Add the (non-zero) dimensions in x, y and z for trailer {m.trailer_id}.",
                    )
            else:
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
                m.engine_power = l["engine_power"]
                m.build_year = l["build_year"]
                if m.build_year is None:
                    m.build_year = 2026
                if m.color is None:
                    m.color = "Yellow"
                fleet.machines.append(m)
                fleet.number_of_machines_per_type[m.machine_type] += 1
                if not np.all(m.overall_dimensions):
                    generate_warning(
                        "Warning: Dimension(s) missing",
                        f"Add the (non-zero) dimensions in x, y and z for machine {m.machine_id}.",
                    )
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


