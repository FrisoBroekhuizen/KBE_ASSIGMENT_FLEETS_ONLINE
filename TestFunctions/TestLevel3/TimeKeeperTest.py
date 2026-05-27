import datetime
import numpy as np

class Vehicle():
    age = 1

class Truck():
    age = 2

class Tractor():
    age = 3

class WorkJob():
    assigned_vehicles = [Vehicle(), Vehicle(), Vehicle(), Vehicle()]
    man_hours = 10

class TransportJob():
    transporting_vehicle = Vehicle()
    routeDuration = 2

class TransportJob2():
    transporting_vehicle = Tractor()
    routeDuration = 4

work_jobs = [WorkJob(), WorkJob()]
transport_jobs = [TransportJob(), TransportJob2()]

current_time = datetime.datetime(hour=8, minute=0, day=28, month=5, year=2026)

# for work_job in work_jobs:
    # sorted_vehicles = sorted(work_job.assigned_vehicles, key=lambda assigned_vehicle: type(assigned_vehicle).__name__)

transported_vehicles = []

for transport_job in transport_jobs:
    transported_vehicles.append([transport_job.transporting_vehicle.age, transport_job.routeDuration])
transported_vehicles = np.array(transported_vehicles)

for work_job in work_jobs:
    number_of_machines_assigned = len(work_job.assigned_vehicles)
    if work_job.assigned_vehicles[0].age in transported_vehicles[:, 0]:
        current_time += datetime.timedelta(hours=transport_job.routeDuration)
        time_per_machine = work_job.man_hours / number_of_machines_assigned
        current_time += datetime.timedelta(hours=time_per_machine)

if __name__ == "__main__":
    print(current_time)