# from parapy.core import Base, Input, Attribute, Part, child, action
# from parapy.exchange import STEPWriter

import numpy as np
import matplotlib.pyplot as plt
# import pytest

class Machine():
    """
    Description:
        Generic superclass for all equipment in the fleet (vehicles and tools).

    UML attributes:
        - age: float
        - prediction_tool: string
        - historical_data_file: string (e.g. path to .xlsx file)
        - worth: float
        - energy_source: string
        - mass: float
        - overall_dimensions: array [x, y, z]
        - gps_location: string
        - availability: bool

    UML operations:
        - CalculateIndividualCO2()
        - CalculateIndividualNOX()
        - CalculateIndividualCost()
    """

    age = 10 # Years
    worth = 2 # Million Euro's
    operating_fraction = 8 # Assumed data contains hours/day
    idle_fraction = 2 # Assumed data contains hours/day

    # Weights of wear caused by different ways of using the machine
    w_operating = 1e-5
    w_idle = 3e-6
    w_stationary = 5e-7

    energy_source = "Hybrid"

    energy_source_factors = {"Diesel":1.2,
                             "Gasoline":1.1,
                             "Electric":0.8,
                             "Hybrid":1.3}

    machine_type_factors = {"Crane":1.6,
                            "Tractor":1.3,
                            "Truck":1.1,
                            "Vehicle":1,
                            "Tool":1.6,
                            "Pump":1.9}


    def MaintenancePredictor(self):
        # Normalize hours spend by the machine as a base decay_factor
        total_hours = self.age * 365 * 24
        operating_hours = total_hours * self.operating_fraction / 24
        idle_hours = total_hours * self.idle_fraction / 24
        stationary_hours = total_hours - operating_hours - idle_hours

        decay_factor = 8760 * (self.w_operating * operating_hours + self.w_idle * idle_hours + self.w_stationary * stationary_hours) / total_hours

        # Alter the decay factor based on machine worth, energy_source and machine_type
        decay_factor *= (1 + 0.01 * self.worth)
        decay_factor *= self.energy_source_factors[self.energy_source]
        decay_factor *= self.machine_type_factors[type(self).__name__]

        # Used for visualizing the decay only
        prod_list = []
        for year in range(50):
            prod_list.append(np.exp(-decay_factor * year))

        plt.plot(range(50), prod_list)
        plt.show()

        productivity = np.exp(-decay_factor * self.age)
        return productivity

# Test machine types
class Vehicle(Machine):
    pass

class Pump(Vehicle):
    pass

class Truck(Vehicle):
    pass

class Crane(Vehicle):
    pass

if __name__ == "__main__":
    vehicle = Crane()
    vehicle.MaintenancePredictor()