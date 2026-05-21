import os

from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter

from routingpy import ORS
maindir = os.path.dirname(__file__)


def ComputeRoute(start, end, machine_type):
    coordinates = [start, end]

    client = ORS(api_key='eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImY0OThhNGEyMGQwYjRmZjE5MDdmOGU2NjQzMDY0ZGVjIiwiaCI6Im11cm11cjY0In0=')

    if machine_type == "Vehicle":
        route = client.directions(locations=coordinates, profile='driving-car')
    else:
        route = client.directions(locations=coordinates, profile='driving-hgv')

    routeDuration = route.duration
    routeDistance = route.distance

    return routeDuration, routeDistance