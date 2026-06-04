import requests

BASE_URL = "https://api.deepdigital.org/v2"  # adjust to your real base
USERNAME = "testing@fleets-online.com"
PASSWORD = "WTuXQ8ZsK9#mT4qZ"


# ----------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------
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
        # Wrap any external error in a clear, domain‑specific message
        raise RuntimeError(
            "External error while contacting DeepDigital emissions API for authentication. "
            "Please contact Fleets-Online."
        ) from exc


def _get_auth_headers() -> dict:
    return {"Authorization": f"Bearer {_get_access_token()}"}


# ----------------------------------------------------------------------
# CO2 CALCULATOR
# ----------------------------------------------------------------------
def CO2Calculator(
    *,
    energy_source: str,
    fuel_type: str,
    fuel_usage_liters: float,
    year: int,
) -> float:
    """Return CO2 [kg] for given fuel usage.

    - If energy_source is Electric -> 0.0 (assume zero tailpipe CO2).
    - Otherwise calls /emission-calculators/fuel-co2.
    """
    if energy_source.strip().lower() == "electric":
        return 0.0

    headers = _get_auth_headers()

    try:
        resp = requests.post(
            f"{BASE_URL}/emission-calculators/fuel-co2",
            headers=headers,
            json={
                "fuelType": fuel_type,                  # e.g. "diesel"
                "fuelUsage": float(fuel_usage_liters),  # liters
                "year": int(year),
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data["co2Kg"])  # API returns co2Kg
    except requests.RequestException as exc:
        raise RuntimeError(
            "External error while contacting DeepDigital CO₂ calculator. "
            "Please contact Fleets-Online."
        ) from exc


# ----------------------------------------------------------------------
# NOX CALCULATOR (UB only)
# ----------------------------------------------------------------------
def NOxCalculator(
    *,
    energy_source: str,
    emission_class_version: str,
    fuel_liters: float | None = None,
    engine_hours: float | None = None,
) -> float:
    """Return NOx [grams] using UB method only.

    - If energy_source is Electric -> 0.0.
    - Otherwise, calls /emission-calculators/ub with:
      emissionClassVersion, fuelLiters, engineHours
    """
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
        raise RuntimeError(
            "External error while contacting DeepDigital NOx calculator. "
            "Please contact Fleets-Online."
        ) from exc
