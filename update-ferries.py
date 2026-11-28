
import csv
import io
import json
import re
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

GTFS_URL = "https://gtfs.halifax.ca/static/google_transit.zip"
OUTPUT_FILE = "ferries.json"
TIMEZONE = ZoneInfo("America/Halifax")

DIRECTIONS = (
    "halifax_alderney",
    "alderney_halifax",
    "halifax_woodside",
    "woodside_halifax",
)

TERMINAL_WORDS = {
    "halifax": ("halifax ferry", "halifax terminal"),
    "alderney": ("alderney",),
    "woodside": ("woodside",),
}


def read_csv(zf, filename):
    if filename not in zf.namelist():
        print("DIAGNOSTIC: Missing", filename)
        return []

    with zf.open(filename) as file:
        return list(csv.DictReader(
            io.TextIOWrapper(file, encoding="utf-8-sig")
        ))


def normalize(value):
    return re.sub(
        r"\s+", " ", (value or "").strip().lower()
    )


def terminal_name(stop_name):
    name = normalize(stop_name)

    for terminal, words in TERMINAL_WORDS.items():
        if any(word in name for word in words):
            return terminal

    return None


def active_services(calendar, exceptions, date):
    date_string = date.strftime("%Y%m%d")
    weekday = date.strftime("%A").lower()

    active = set()

    for row in calendar:
        if (
            row.get("start_date", "") <= date_string
            <= row.get("end_date", "")
            and row.get(weekday) == "1"
        ):
            active.add(row["service_id"])

    for row in exceptions:
        if row.get("date") != date_string:
            continue

        if row.get("exception_type") == "1":
            active.add(row["service_id"])
        elif row.get("exception_type") == "2":
            active.discard(row["service_id"])

    return active


def make_datetime(date, time_string):
    hours, minutes, seconds = map(
        int, time_string.split(":")
    )

    midnight = datetime(
        date.year, date.month, date.day,
        tzinfo=TIMEZONE
    )

    return midnight + timedelta(
        hours=hours,
        minutes=minutes,
        seconds=seconds
    )


def download_gtfs():
    request = urllib.request.Request(
        GTFS_URL,
        headers={
            "User-Agent": "HalifaxFerryBoard/2.0"
        }
    )

    with urllib.request.urlopen(
        request, timeout=60
    ) as response:
        data = response.read()

    print(
        "DIAGNOSTIC: Downloaded GTFS bytes:",
        len(data)
    )

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {
            name: read_csv(zf, name + ".txt")
            for name in (
                "routes",
                "trips",
                "stops",
                "stop_times",
                "calendar",
                "calendar_dates",
            )
        }


def main():
    now = datetime.now(TIMEZONE)

    print(
        "DIAGNOSTIC: Halifax time:",
        now.isoformat()
    )

    data = download_gtfs()

    routes = data["routes"]
    trips = data["trips"]
    stops = data["stops"]
    stop_times = data["stop_times"]
    calendar = data["calendar"]
    exceptions = data["calendar_dates"]

    print("DIAGNOSTIC: GTFS row counts:", {
        key: len(value)
        for key, value in data.items()
    })

    stop_names = {
        row["stop_id"]: row.get("stop_name", "")
        for row in stops
    }

    parent_stations = {
        row["stop_id"]: row.get("parent_station", "")
        for row in stops
    }

    stop_terminals = {}

    for stop_id, name in stop_names.items():
        terminal = terminal_name(name)

        if not terminal:
            parent = parent_stations.get(stop_id)

            if parent:
                terminal = terminal_name(
                    stop_names.get(parent, "")
                )

        if terminal:
            stop_terminals[stop_id] = terminal

    print(
        "DIAGNOSTIC: Identified terminal stops:",
        json.dumps(stop_terminals)
    )

    route_info = {
        row["route_id"]: row
        for row in routes
    }

    ferry_route_ids = set()

    for route_id, row in route_info.items():
        short = normalize(
            row.get("route_short_name")
        )
        long_name = normalize(
            row.get("route_long_name")
        )

        if (
            row.get("route_type") == "4"
            or "ferry" in long_name
            or short in ("ferd", "ferw")
            or "alderney" in long_name
            or "woodside" in long_name
        ):
            ferry_route_ids.add(route_id)

    print(
        "DIAGNOSTIC: Ferry route candidates:",
        json.dumps([
            {
                "route_id": route_id,
                "short": route_info[route_id].get(
                    "route_short_name"
                ),
                "long": route_info[route_id].get(
                    "route_long_name"
                ),
            }
            for route_id in sorted(ferry_route_ids)
        ])
    )

    if not ferry_route_ids:
        raise RuntimeError(
            "No ferry routes found in GTFS. "
            "Existing JSON preserved."
        )

    ferry_trips = {
        row["trip_id"]: row
        for row in trips
        if row.get("route_id") in ferry_route_ids
    }

    trip_stops = defaultdict(list)

    for row in stop_times:
        trip_id = row.get("trip_id")

        if trip_id in ferry_trips:
            trip_stops[trip_id].append(row)

    print(
        "DIAGNOSTIC: Ferry trips:",
        len(ferry_trips)
    )

    print(
        "DIAGNOSTIC: Ferry stop ID counts:",
        Counter(
            row.get("stop_id")
            for rows in trip_stops.values()
            for row in rows
        ).most_common(20)
    )

    departures = {
        key: [] for key in DIRECTIONS
    }

    matched_trips = 0
    active_trips = 0

    for offset in (-1, 0, 1, 2):
        service_date = now.date() + timedelta(
            days=offset
        )

        active = active_services(
            calendar, exceptions, service_date
        )

        print(
            "DIAGNOSTIC: Date:",
            service_date,
            "active services:",
            len(active)
        )

        for trip_id, trip in ferry_trips.items():
            if trip.get("service_id") not in active:
                continue

            active_trips += 1

            rows = sorted(
                trip_stops.get(trip_id, []),
                key=lambda row: int(
                    row.get("stop_sequence", 0)
                )
            )

            terminal_stops = []

            for row in rows:
                terminal = stop_terminals.get(
                    row.get("stop_id")
                )

                if terminal:
                    terminal_stops.append(
                        (terminal, row)
                    )

            if len(terminal_stops) < 2:
                continue

            origin_name, origin_row = (
                terminal_stops[0]
            )

            destination_name, _ = (
                terminal_stops[-1]
            )

            if origin_name == destination_name:
                continue

            key = (
                origin_name + "_" + destination_name
            )

            if key not in departures:
                continue

            matched_trips += 1

            departure_string = origin_row.get(
                "departure_time"
            ) or origin_row.get("arrival_time")

            if not departure_string:
                continue

            departure = make_datetime(
                service_date, departure_string
            )

            if departure >= now:
                departures[key].append(departure)

    print(
        "DIAGNOSTIC: Active trips:",
        active_trips
    )

    print(
        "DIAGNOSTIC: Matched terminal trips:",
        matched_trips
    )

    print(
        "DIAGNOSTIC: Future departure counts:",
        {
            key: len(value)
            for key, value in departures.items()
        }
    )

    if not any(departures.values()):
        raise RuntimeError(
            "No future ferry departures were found. "
            "Check diagnostic output. "
            "Existing ferries.json was not overwritten."
        )

    output = {}

    for key in DIRECTIONS:
        times = sorted(
            set(departures[key])
        )[:3]

        output[key] = [
            value.strftime("%-I:%M %p")
            for value in times
        ]

        output[key + "_iso"] = [
            value.isoformat()
            for value in times
        ]

    output["updated"] = now.strftime(
        "%-I:%M %p"
    )

    output["updated_iso"] = now.isoformat()

    output["source"] = (
        "Halifax Transit GTFS "
        "(scheduled, not live departures)"
    )

    Path(OUTPUT_FILE).write_text(
        json.dumps(output, indent=2) + "\n",
        encoding="utf-8"
    )

    print(
        "RESULT:",
        json.dumps(output, indent=2)
    )


if __name__ == "__main__":
    main()
