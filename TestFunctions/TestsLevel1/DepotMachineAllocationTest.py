"""
Very simple test script for Fleet.Depot.DepotMachineAllocation.

Edit the CONFIG section below to change depot / machine locations and range,
then run this file and inspect the printed output.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Put project root on sys.path so we can import main and machine
# ---------------------------------------------------------------------------

THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))  # ../../ from this file

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from main import Fleet              # nested Depot lives here
from machine import Machine

# Convenience alias so we can just write Depot(...)
Depot = Fleet.Depot


# ---------------------------------------------------------------------------
# CONFIG: change these values when you want to test other cases
# ---------------------------------------------------------------------------

DEPOT_LOCATION = (52.0, 5.0)          # (lat, lon)

MACHINE1_LOCATION = (52.0000, 5.0000)  # exactly at depot
MACHINE2_LOCATION = (52.0005, 5.0005)  # relatively close
MACHINE3_LOCATION = (53.0, 5.0)        # far away

DEPOT_DIMENSIONS = (100.0, 50.0, 10.0)  # (L, W, H) [m]
RANGE_M = 500.0                         # extra radius around depot [m]


# ---------------------------------------------------------------------------
# Simple demo
# ---------------------------------------------------------------------------

def main():
    # Create 3 machines at the configured locations
    m1 = Machine(gps_location=MACHINE1_LOCATION, overall_dimensions=(2, 2, 2))
    m2 = Machine(gps_location=MACHINE2_LOCATION, overall_dimensions=(2, 2, 2))
    m3 = Machine(gps_location=MACHINE3_LOCATION, overall_dimensions=(2, 2, 2))

    # Create depot with these machines
    depot = Depot(
        location=DEPOT_LOCATION,
        rotation=0.0,
        overall_dimensions=DEPOT_DIMENSIONS,
        machines=[m1, m2, m3],
    )

    print("=== INPUT ===")
    print(f"Depot location: {depot.location}")
    print(f"Range_m:        {RANGE_M}")
    print("Machines before allocation:")
    for i, m in enumerate(depot.machines, start=1):
        print(f"  Machine {i}: gps_location = {m.gps_location}")

    # Call the method under test
    depot_machines, road_parked = depot.DepotMachineAllocation(range_m=RANGE_M)

    print("\n=== OUTPUT ===")
    print(depot_machines[0].gps_location)
    print(f"Number of depot machines:       {len(depot_machines)}")
    print(f"Number of road‑parked machines: {len(road_parked)}")

    print("\nMachines assigned to depot:")
    for i, m in enumerate(depot_machines, start=1):
        print(f"  Depot machine {i}: gps_location = {m.gps_location}")

    print("\nMachines road‑parked:")
    for i, m in enumerate(road_parked, start=1):
        print(f"  Road‑parked machine {i}: gps_location = {m.gps_location}")

    print("\nInternal depot.machines after call:")
    for i, m in enumerate(depot.machines, start=1):
        print(f"  depot.machines[{i}]: gps_location = {m.gps_location}")

if __name__ == "__main__":
    main()

