
import csv
import io
import zipfile
import urllib.request
from google.transit import gtfs_realtime_pb2

STATIC_URL = "https://gtfs.halifax.ca/static/google_transit.zip"
GPS_URL = "https://gtfs.halifax.ca/realtime/Vehicle/VehiclePositions.pb"

def download(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "HalifaxFerryBoard/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()

def main():
    print("Checking Halifax Transit ferry GPS...")

    static_data = download(STATIC_URL)
    with zipfile.ZipFile(io.BytesIO(static_data)) as archive:
        routes = list(csv.DictReader(
            io.TextIOWrapper(archive.open("routes.txt"), encoding="utf-8-sig")
        ))
        trips = list(csv.DictReader(
            io.TextIOWrapper(archive.open("trips.txt"), encoding="utf-8-sig")
        ))

    ferry_routes = {
        r["route_id"]: r.get("route_long_name", r.get("route_short_name", ""))
        for r in routes
        if r.get("route_type") == "4"
    }

    ferry_trips = {
        t["trip_id"]: t["route_id"]
        for t in trips if t["route_id"] in ferry_routes
    }

    print("Ferry routes:", ferry_routes)

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(download(GPS_URL))

    found = 0
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        if not vehicle.HasField("position"):
            continue

        route_id = vehicle.trip.route_id
        if not route_id:
            route_id = ferry_trips.get(vehicle.trip.trip_id, "")

        if route_id not in ferry_routes:
            continue

        found += 1
        print("Ferry:", vehicle.vehicle.label or vehicle.vehicle.id)
        print("Route:", ferry_routes[route_id])
        print("Latitude:", vehicle.position.latitude)
        print("Longitude:", vehicle.position.longitude)

    if found == 0:
        print("No ferry GPS positions found in this snapshot.")
    else:
        print("Ferry GPS positions found:", found)

if __name__ == "__main__":
    main()
