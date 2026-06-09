# EmissionsExternalTool.py

from __future__ import annotations
from Warning import generate_warning

import requests

BASE_URL = "https://api.v2.deepdigital.org"

def _get_access_token() -> str:
    try:
        resp = requests.post(
            "https://api.v2.deepdigital.org/oauth/token",
            data={
                "grant_type": "password",
                "username": "testing@fleets-online.com",
                "password": "WTuXQ8ZsK9#mT4qZ",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except requests.RequestException as exc:
        generate_warning(
            "Emissions API error",
            "External error while contacting DeepDigital emissions API for authentication.\n\n"
            "Please contact Fleets-Online.",
        )
        raise RuntimeError(
            "External error while contacting DeepDigital emissions API for authentication. "
            "Please contact Fleets-Online."
        ) from exc


def _get_auth_headers() -> dict:
    return {"Authorization": f"Bearer {_get_access_token()}"}

# Possible fuel types: benzine-(e10-blend), bio-ethanol-(100%), e85, diesel-(b7-blend), diesel-(fossiel), biodiesel-(hvo), biodiesel-(fame), gtl, cng, bio-cng, lng, bio-lng, lpg, waterstof-(grijs), waterstof-(groen), marine-diesel-oil-(mdo), heavy-fuel-oil-(hfo), kerosine-(jet-a1), HVO10, HVO20, HVO30, HVO50, HVO70, HVO100
def CO2Calculator(
    *,
    energy_source: str,
    fuel_type: str,
    fuel_usage_liters: float,
    year: int,
) -> float:
    if energy_source.strip().lower() == "electric":
        return 0.0
    headers = _get_auth_headers()

    try:
        resp = requests.post(
            f"{BASE_URL}/emission-calculators/fuel-co2",
            headers=headers,
            json={
                "fuelType": fuel_type,
                "fuelUsage": float(fuel_usage_liters),
                "year": int(year),
            },
            timeout=10.0,
        )
        if not resp.ok:
            print(resp.status_code)
            print(resp.text)

        resp.raise_for_status()
        data = resp.json()
        return float(data["co2Kg"])
    except requests.RequestException as exc:
        generate_warning(
            "Emissions API error",
            "External error while contacting DeepDigital CO₂ calculator.\n\n"
            "Please contact Fleets-Online.",
        )
        raise RuntimeError(
            "External error while contacting DeepDigital CO₂ calculator. "
            "Please contact Fleets-Online."
        ) from exc


def NOxCalculator(
    *,
    energy_source: str,
    emission_class: str,
    fuel_liters: float | None = None,
    engine_hours: float | None = None,
) -> float:
    if energy_source.strip().lower() == "electric":
        return 0.0

    headers = _get_auth_headers()

    body = {
        "emissionClassVersion": emission_class_version,
        "kwh": 250,  # required — engine power in kW
        "usesAdblue": False,
        "adblueLiters": 6.2,
    }
    if fuel_liters is not None:
        body["fuelLiters"] = float(fuel_liters)
    if engine_hours is not None:
        body["engineHours"] = float(engine_hours)

    try:
        resp = requests.post(
            f"{BASE_URL}/emission-calculators/aub",
            headers=headers,
            json=body,
            timeout=10.0,
        )
        if not resp.ok:
            print(resp.status_code)
            print(resp.text)

        resp.raise_for_status()
        data = resp.json()
        return float(data["noxGrams"])
    except requests.RequestException as exc:
        generate_warning(
            "Emissions API error",
            "External error while contacting DeepDigital NOx calculator.\n\n"
            "Please contact Fleets-Online.",
        )
        raise RuntimeError(
            "External error while contacting DeepDigital NOx calculator. "
            "Please contact Fleets-Online."
        ) from exc
