
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

HALIFAX = "1073"
ALDERNEY = "1074"
WOODSIDE = "1075"

ALDERNEY_ROUTE = "FerD"
WOODSIDE_ROUTE = "FerW"

DIRECTIONS = (
    "halifax_alderney",
    "alderney_halifax",
    "halifax_woodside",
    "woodside_halifax"
)


def read_csv_from_zip(zf, filename):
    if filename not in zf.namelist():
        return []

    with zf.open(filename) as f:
        return list(csv.DictReader(
            io.TextIOWrapper(f, encoding="utf-8-sig")
        ))


def active_service_ids(calendar_rows, exceptions, service_date):
    day = service_date.strftime("%Y%m%d")
    weekday = service_date.strftime("%A").lower()

    active = {
        row["service_id"]
        for row in calendar_rows
        if row["start_date"] <= day <= row["end_date"]
        and row.get(weekday) == "1"
    }

    for row in exceptions:
        if row["date"] == day:
            if row["exception_type"] == "1":
                active.add(row["service_id"])
            elif row["exception_type"] == "2":
                active.discard(row["service_id"])

    return active


def gtfs_datetime(service_date, value):
    hours, minutes, seconds = map(int, value.split(":"))

    midnight = datetime(
        service_date.year,
        service_date.month,
        service_date.day,
        tzinfo=HALIFAX_TZ
    )

    return midnight + timedelta(
        hours=hours,
        minutes=minutes,
        seconds=seconds
    )


def main():
    now = datetime.now(HALIFAX_TZ)

    req = urllib.request.Request(
        GTFS_URL,
        headers={"User-Agent": "HalifaxFerryBoard/1.0"}
    )

    with urllib.request.urlopen(req, timeout=45) as response:
        raw = response.read()

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        routes = read_csv_from_zip(zf, "routes.txt")
        trips = read_csv_from_zip(zf, "trips.txt")
        stop_times = read_csv_from_zip(zf, "stop_times.txt")
        calendar = read_csv_from_zip(zf, "calendar.txt")
        exceptions = read_csv_from_zip(zf, "calendar_dates.txt")

    ferry_routes = {}

    for row in routes:
        if row.get("route_short_name") in (
            ALDERNEY_ROUTE,
            WOODSIDE_ROUTE
        ):
            ferry_routes[row["route_id"]] = row["route_short_name"]

    if set(ferry_routes.values()) != {
        ALDERNEY_ROUTE,
        WOODSIDE_ROUTE
    }:
        raise RuntimeError(
            "Expected both ferry routes in GTFS"
        )

    trips_by_id = {
        row["trip_id"]: (
            row["service_id"],
            ferry_routes[row["route_id"]]
        )
        for row in trips
        if row["route_id"] in ferry_routes
    }

    stops_by_trip = {}

    for row in stop_times:
        if row["trip_id"] in trips_by_id:
            stops_by_trip.setdefault(
                row["trip_id"], []
            ).append(row)

    departures = {
        key: [] for key in DIRECTIONS
    }

    # Include yesterday for trips after midnight.
    # Check today and the next two days.
    for day_offset in (-1, 0, 1, 2):
        service_date = now.date() + timedelta(
            days=day_offset
        )

        active = active_service_ids(
            calendar,
            exceptions,
            service_date
        )

        for trip_id, (service_id, route) in trips_by_id.items():
            if service_id not in active:
                continue

            stops = sorted(
                stops_by_trip.get(trip_id, []),
                key=lambda row: int(row["stop_sequence"])
            )

            stop_ids = [
                row["stop_id"] for row in stops
            ]

            destination = (
                ALDERNEY
                if route == ALDERNEY_ROUTE
                else WOODSIDE
            )

            if (
                HALIFAX not in stop_ids
                or destination not in stop_ids
            ):
                continue

            h_index = stop_ids.index(HALIFAX)
            d_index = stop_ids.index(destination)

            if h_index < d_index:
                key = (
                    "halifax_alderney"
                    if route == ALDERNEY_ROUTE
                    else "halifax_woodside"
                )
                origin = stops[h_index]
            else:
                key = (
                    "alderney_halifax"
                    if route == ALDERNEY_ROUTE
                    else "woodside_halifax"
                )
                origin = stops[d_index]

            dt = gtfs_datetime(
                service_date,
                origin["departure_time"]
            )

            if dt >= now:
                departures[key].append(dt)

    output = {}

    for key in DIRECTIONS:
        times = sorted(set(departures[key]))[:3]

        output[key] = [
            t.strftime("%-I:%M %p")
            for t in times
        ]

        output[key + "_iso"] = [
            t.isoformat()
            for t in times
        ]

    output["updated"] = now.strftime("%-I:%M %p")
    output["updated_iso"] = now.isoformat()
    output["source"] = (
        "Halifax Transit GTFS "
        "(scheduled, not live departures)"
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
