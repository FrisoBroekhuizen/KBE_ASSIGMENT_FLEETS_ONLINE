from routingpy import ORS
from pprint import pprint

coords = [[4.37621, 52.00334], [4.43178, 51.93681]]

client = ORS(api_key='eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImY0OThhNGEyMGQwYjRmZjE5MDdmOGU2NjQzMDY0ZGVjIiwiaCI6Im11cm11cjY0In0=')

route = client.directions(locations=coords, profile='driving-hgv')

# pprint((route.geometry, route.duration, route.distance, route.raw))
print("Time taken:" + str(route.duration) + " seconds")
print("Route distance:" + str(route.distance) + " meters")