from routingpy import ORS
from pprint import pprint
import time

coords = [[8.666275, 53.737056], [10.659115, 47.568947]]

client = ORS(api_key='eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImY0OThhNGEyMGQwYjRmZjE5MDdmOGU2NjQzMDY0ZGVjIiwiaCI6Im11cm11cjY0In0=')

route = client.directions(locations=coords, profile='driving-car')

# pprint((route.geometry, route.duration, route.distance, route.raw))
print("Time taken:" + str(route.duration) + " seconds")
print("Route distance:" + str(route.distance) + " meters")

for i in range(30):
    print(client.directions(locations=coords, profile='driving-car').distance)
    time.sleep(2)