
import csv
import io
import zipfile
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2

STATIC_URL = "https://gtfs.halifax.ca/static/google_transit.zip"
GPS_URL = "https://gtfs.halifax.ca/realtime/Vehicle/VehiclePositions.pb"

def download(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "HalifaxFerryBoard/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()

def main():
    print("HALIFAX FERRY GPS - DETAILED TEST")
    print("--------------------------------")

    static_data = download(STATIC_URL)

    with zipfile.ZipFile(io.BytesIO(static_data)) as archive:
        routes = list(csv.DictReader(
            io.TextIOWrapper(
                archive.open("routes.txt"),
                encoding="utf-8-sig"
            )
        ))

        trips = list(csv.DictReader(
            io.TextIOWrapper(
                archive.open("trips.txt"),
                encoding="utf-8-sig"
            )
        ))

    ferry_routes = {
        route["route_id"]: route.get("route_long_name", "")
        for route in routes
        if route.get("route_type") == "4"
    }

    trip_routes = {
        trip["trip_id"]: trip["route_id"]
        for trip in trips
    }

    print("Known ferry routes:", ferry_routes)

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(download(GPS_URL))

    if feed.header.timestamp:
        timestamp = datetime.fromtimestamp(
            feed.header.timestamp, timezone.utc
        )
        print("Feed timestamp (UTC):", timestamp.isoformat())

    total = 0
    with_positions = 0
    missing_routes = 0
    ferry_matches = []
    route_counts = Counter()
    examples = []

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue

        total += 1
        vehicle = entity.vehicle

        if not vehicle.HasField("position"):
            continue

        with_positions += 1

        trip_id = vehicle.trip.trip_id
        route_id = vehicle.trip.route_id

        if not route_id:
            route_id = trip_routes.get(trip_id, "")

        route_counts[route_id or "(missing)"] += 1

        label = vehicle.vehicle.label or vehicle.vehicle.id
        latitude = vehicle.position.latitude
        longitude = vehicle.position.longitude

        if not route_id:
            missing_routes += 1

        record = {
            "label": label,
            "route": route_id,
            "trip": trip_id,
            "latitude": latitude,
            "longitude": longitude
        }

        if route_id in ferry_routes:
            ferry_matches.append(record)

        # Inspect a small sample without exposing
        # every vehicle's exact location.
        if len(examples) < 10:
            examples.append(record)

    print("\nGPS SUMMARY")
    print("Total vehicle records:", total)
    print("Vehicles with coordinates:", with_positions)
    print("Vehicles missing route IDs:", missing_routes)
    print("Ferry GPS matches:", len(ferry_matches))

    print("\nROUTE COUNTS")
    for route_id, count in route_counts.most_common(15):
        print(route_id, ":", count)

    print("\nFERRY MATCHES")
    if ferry_matches:
        for vehicle in ferry_matches:
            print(vehicle)
    else:
        print("No identified ferry positions.")

    print("\nSAMPLE VEHICLE RECORDS")
    for vehicle in examples:
        print(vehicle)

    print("\nTEST COMPLETE")
    print("No television files were changed.")

if __name__ == "__main__":
    main()
