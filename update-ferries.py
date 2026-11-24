import csv
import io
import json
import zipfile
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GTFS_URL = "https://gtfs.halifax.ca/static/google_transit.zip"
OUTPUT_FILE = "ferries.json"

HALIFAX_TZ = ZoneInfo("America/Halifax")

# Halifax ferry stops
HALIFAX = "1073"
ALDERNEY = "1074"
WOODSIDE = "1075"

# Halifax Transit ferry routes
ALDERNEY_ROUTE = "FerD"
WOODSIDE_ROUTE = "FerW"


def download_gtfs():
    print("Downloading Halifax Transit GTFS...")
    with urllib.request.urlopen(GTFS_URL, timeout=30) as response:
        return response.read()


def read_csv_from_zip(zf, filename):
    with zf.open(filename) as f:
        text = io.TextIOWrapper(f, encoding="utf-8-sig")
        return list(csv.DictReader(text))


def gtfs_time_to_datetime(service_date, time_string):
    hours, minutes, seconds = map(int, time_string.split(":"))

    day_offset = hours // 24
    hours = hours % 24

    dt = datetime(
        service_date.year,
        service_date.month,
        service_date.day,
        hours,
        minutes,
        seconds,
        tzinfo=HALIFAX_TZ
    )

    return dt + timedelta(days=day_offset)


def active_service_ids(calendar_rows, calendar_dates_rows, today):
    weekday = today.strftime("%A").lower()
    date_text = today.strftime("%Y%m%d")

    active = set()

    for row in calendar_rows:
        start = row["start_date"]
        end = row["end_date"]

        if start <= date_text <= end and row.get(weekday) == "1":
            active.add(row["service_id"])

    for row in calendar_dates_rows:
        if row["date"] != date_text:
            continue

        if row["exception_type"] == "1":
            active.add(row["service_id"])

        elif row["exception_type"] == "2":
            active.discard(row["service_id"])

    return active


def main():
    now = datetime.now(HALIFAX)
    today = now.date()

    data = download_gtfs()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:

        routes = read_csv_from_zip(zf, "routes.txt")
        trips = read_csv_from_zip(zf, "trips.txt")
        stop_times = read_csv_from_zip(zf, "stop_times.txt")

        calendar = (
            read_csv_from_zip(zf, "calendar.txt")
            if "calendar.txt" in zf.namelist()
            else []
        )

        calendar_dates = (
            read_csv_from_zip(zf, "calendar_dates.txt")
            if "calendar_dates.txt" in zf.namelist()
            else []
        )

    # Identify actual route IDs using route_short_name.
    ferry_route_ids = {}

    for route in routes:
        short_name = route.get("route_short_name", "")

        if short_name in (ALDERNEY_ROUTE, WOODSIDE_ROUTE):
            ferry_route_ids[short_name] = route["route_id"]

    print("Ferry routes found:", ferry_route_ids)

    active_services = active_service_ids(
        calendar,
        calendar_dates,
        today
    )

    ferry_trips = {}

    for trip in trips:
        if trip["service_id"] not in active_services:
            continue

        route_id = trip["route_id"]

        if route_id == ferry_route_ids.get(ALDERNEY_ROUTE):
            ferry_trips[trip["trip_id"]] = ALDERNEY_ROUTE

        elif route_id == ferry_route_ids.get(WOODSIDE_ROUTE):
            ferry_trips[trip["trip_id"]] = WOODSIDE_ROUTE

    # Collect stop times for ferry trips.
    trip_stops = {}

    for row in stop_times:
        trip_id = row["trip_id"]

        if trip_id not in ferry_trips:
            continue

        trip_stops.setdefault(trip_id, []).append(row)

    departures = {
        "halifax_alderney": [],
        "alderney_halifax": [],
        "halifax_woodside": [],
        "woodside_halifax": []
    }

    for trip_id, stops in trip_stops.items():

        stops.sort(key=lambda x: int(x["stop_sequence"]))

        route = ferry_trips[trip_id]

        stop_ids = [s["stop_id"] for s in stops]

        # ALDERNEY
        if route == ALDERNEY_ROUTE:

            if HALIFAX in stop_ids and ALDERNEY in stop_ids:

                h_index = stop_ids.index(HALIFAX)
                a_index = stop_ids.index(ALDERNEY)

                if h_index < a_index:
                    departure_stop = stops[h_index]
                    key = "halifax_alderney"
                else:
                    departure_stop = stops[a_index]
                    key = "alderney_halifax"

                departure_time = gtfs_time_to_datetime(
                    today,
                    departure_stop["departure_time"]
                )

                if departure_time >= now:
                    departures[key].append(departure_time)

        # WOODSIDE
        elif route == WOODSIDE_ROUTE:

            if HALIFAX in stop_ids and WOODSIDE in stop_ids:

                h_index = stop_ids.index(HALIFAX)
                w_index = stop_ids.index(WOODSIDE)

                if h_index < w_index:
                    departure_stop = stops[h_index]
                    key = "halifax_woodside"
                else:
                    departure_stop = stops[w_index]
                    key = "woodside_halifax"

                departure_time = gtfs_time_to_datetime(
                    today,
                    departure_stop["departure_time"]
                )

                if departure_time >= now:
                    departures[key].append(departure_time)

    # Sort and keep next three.
    output = {}

    for key, times in departures.items():

        times.sort()

        output[key] = [
            t.strftime("%-I:%M %p")
            for t in times[:3]
        ]

    output["updated"] = now.strftime("%-I:%M %p")
    output["source"] = "Halifax Transit GTFS"

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
