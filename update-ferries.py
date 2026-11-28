
import csv
import io
import json
import zipfile
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
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
        print(f"DIAGNOSTIC: {filename} missing from GTFS archive")
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

    print(f"DIAGNOSTIC: Halifax local time: {now.isoformat()}")

    req = urllib.request.Request(
        GTFS_URL,
        headers={"User-Agent": "HalifaxFerryBoard/1.0"}
    )

    with urllib.request.urlopen(req, timeout=45) as response:
        raw = response.read()

    print(
        f"DIAGNOSTIC: Downloaded GTFS archive ({len(raw)} bytes)"
    )

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        routes = read_csv_from_zip(zf, "routes.txt")
        trips = read_csv_from_zip(zf, "trips.txt")
        stop_times = read_csv_from_zip(zf, "stop_times.txt")
        calendar = read_csv_from_zip(zf, "calendar.txt")
        exceptions = read_csv_from_zip(zf, "calendar_dates.txt")
        stops = read_csv_from_zip(zf, "stops.txt")

    print("DIAGNOSTIC: Row counts:", json.dumps({
        "routes": len(routes),
        "trips": len(trips),
        "stop_times": len(stop_times),
        "calendar": len(calendar),
        "calendar_dates": len(exceptions),
        "stops": len(stops)
    }))

    ferry_candidates = [
        r for r in routes
        if "fer" in (
            r.get("route_short_name", "") + " " +
            r.get("route_long_name", "")
        ).lower()
        or r.get("route_type") == "4"
    ]

    print("DIAGNOSTIC: Ferry route candidates:", json.dumps([
        {
            k: r.get(k)
            for k in (
                "route_id",
                "route_short_name",
                "route_long_name",
                "route_type"
            )
        }
        for r in ferry_candidates[:30]
    ]))

    print("DIAGNOSTIC: Configured terminal IDs:", json.dumps({
        "Halifax": HALIFAX,
        "Alderney": ALDERNEY,
        "Woodside": WOODSIDE
    }))

    print("DIAGNOSTIC: Terminal stop candidates:", json.dumps([
        {
            k: s.get(k)
            for k in ("stop_id", "stop_name", "parent_station")
        }
        for s in stops
        if any(
            x in s.get("stop_name", "").lower()
            for x in ("ferry", "alderney", "woodside")
        )
    ][:40]))

    ferry_routes = {
        r["route_id"]: r["route_short_name"]
        for r in routes
        if r.get("route_short_name") in (
            ALDERNEY_ROUTE,
            WOODSIDE_ROUTE
        )
    }

    print(
        "DIAGNOSTIC: Matched configured ferry routes:",
        json.dumps(ferry_routes)
    )

    if set(ferry_routes.values()) != {
        ALDERNEY_ROUTE,
        WOODSIDE_ROUTE
    }:
        raise RuntimeError(
            "Expected both ferry routes in GTFS; "
            "see route diagnostics above"
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

    print(
        f"DIAGNOSTIC: Ferry trips found: {len(trips_by_id)}; "
        f"with stop times: {len(stops_by_trip)}"
    )

    print(
        "DIAGNOSTIC: Stop IDs used by ferry trips:",
        json.dumps(
            Counter(
                s["stop_id"]
                for rows in stops_by_trip.values()
                for s in rows
            ).most_common(25)
        )
    )

    departures = {
        key: [] for key in DIRECTIONS
    }

    active_trip_count = 0
    matched_terminal_trip_count = 0

    for day_offset in (-1, 0, 1, 2):
        service_date = now.date() + timedelta(
            days=day_offset
        )

        active = active_service_ids(
            calendar,
            exceptions,
            service_date
        )

        day_active_trips = 0

        for trip_id, (service_id, route) in trips_by_id.items():
            if service_id not in active:
                continue

            day_active_trips += 1
            active_trip_count += 1

            trip_stops = sorted(
                stops_by_trip.get(trip_id, []),
                key=lambda row: int(row["stop_sequence"])
            )

            stop_ids = [
                row["stop_id"] for row in trip_stops
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

            matched_terminal_trip_count += 1

            h_index = stop_ids.index(HALIFAX)
            d_index = stop_ids.index(destination)

            if h_index < d_index:
                key = (
                    "halifax_alderney"
                    if route == ALDERNEY_ROUTE
                    else "halifax_woodside"
                )
                origin = trip_stops[h_index]
            else:
                key = (
                    "alderney_halifax"
                    if route == ALDERNEY_ROUTE
                    else "woodside_halifax"
                )
                origin = trip_stops[d_index]

            dt = gtfs_datetime(
                service_date,
                origin["departure_time"]
            )

            if dt >= now:
                departures[key].append(dt)

        print(
            f"DIAGNOSTIC: {service_date}: "
            f"active service IDs={len(active)}, "
            f"active ferry trips={day_active_trips}"
        )

    print(
        "DIAGNOSTIC: Active ferry trips across dates="
        f"{active_trip_count}; matching configured terminal IDs="
        f"{matched_terminal_trip_count}"
    )

    print(
        "DIAGNOSTIC: Future departure counts:",
        json.dumps({
            k: len(v)
            for k, v in departures.items()
        })
    )

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

    if not any(departures.values()):
        raise RuntimeError(
            "No upcoming ferry departures found in any direction. "
            "Existing ferries.json was NOT overwritten. "
            "Review DIAGNOSTIC lines."
        )

    Path(OUTPUT_FILE).write_text(
        json.dumps(output, indent=2) + "\n",
        encoding="utf-8"
    )

    print("RESULT:", json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
