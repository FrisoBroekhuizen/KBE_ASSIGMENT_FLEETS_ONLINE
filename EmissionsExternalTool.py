# EmissionsExternalTool.py

from __future__ import annotations
from Warning import generate_warning

import requests

BASE_URL = "https://api.deepdigital.org/v2"
USERNAME = "testing@fleets-online.com"
PASSWORD = "WTuXQ8ZsK9#mT4qZ"


def _get_access_token() -> str:
    try:
        resp = requests.post(
            f"{BASE_URL}/oauth/token",
            data={
                "grant_type": "password",
                "username": USERNAME,
                "password": PASSWORD,
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
    emission_class_version: str,
    fuel_liters: float | None = None,
    engine_hours: float | None = None,
) -> float:
    if energy_source.strip().lower() == "electric":
        return 0.0

    headers = _get_auth_headers()

    body = {
        "emissionClassVersion": emission_class_version,
    }
    if fuel_liters is not None:
        body["fuelLiters"] = float(fuel_liters)
    if engine_hours is not None:
        body["engineHours"] = float(engine_hours)

    try:
        resp = requests.post(
            f"{BASE_URL}/emission-calculators/ub",
            headers=headers,
            json=body,
            timeout=10.0,
        )
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
