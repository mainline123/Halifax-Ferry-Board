
import csv
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

GTFS_URL = "https://gtfs.halifax.ca/static/google_transit.zip"
OUTPUT_FILE = "ferries.json"
TZ = ZoneInfo("America/Halifax")

HALIFAX = "1073"
ALDERNEY = "1074"
WOODSIDE = "1075"

DIRECTIONS = (
    "halifax_alderney",
    "alderney_halifax",
    "halifax_woodside",
    "woodside_halifax"
)

# Official published Alderney weekday schedule.
# Times are departure times in 24-hour format.

ALDERNEY_TO_HALIFAX_WEEKDAY = (
    ["06:30", "07:00"]
    + [f"{h:02d}:{m:02d}"
       for h in range(7, 20)
       for m in (15, 30, 45, 0)
       if not (h == 7 and m == 0)]
    + [
        "20:00", "20:30", "21:00", "21:30",
        "22:00", "22:30", "23:00", "23:30"
    ]
)

HALIFAX_TO_ALDERNEY_WEEKDAY = (
    ["06:45", "07:15"]
    + [f"{h:02d}:{m:02d}"
       for h in range(7, 20)
       for m in (30, 45, 0, 15)
       if not (h == 7 and m == 15)]
    + [
        "20:00", "20:15", "20:45",
        "21:15", "21:45", "22:15",
        "22:45", "23:15", "23:45"
    ]
)

# Weekend Alderney service, every 30 minutes.

ALDERNEY_TO_HALIFAX_WEEKEND = [
    f"{minute // 60:02d}:{minute % 60:02d}"
    for minute in range(6 * 60 + 30, 23 * 60 + 31, 30)
]

HALIFAX_TO_ALDERNEY_WEEKEND = [
    f"{minute // 60:02d}:{minute % 60:02d}"
    for minute in range(6 * 60 + 45, 23 * 60 + 46, 30)
]

# Woodside: official Monday-Friday departures.

WOODSIDE_TO_HALIFAX = [
    "06:37", "06:52", "07:07", "07:22",
    "07:37", "07:52", "08:07", "08:22",
    "08:37", "08:52", "09:07", "09:22",
    "09:37", "10:07", "10:37",
    "11:07", "11:37", "12:07", "12:37",
    "13:07", "13:37", "14:07", "14:37",
    "14:52", "15:07", "15:22", "15:37",
    "15:52", "16:07", "16:22", "16:37",
    "16:52", "17:07", "17:22", "17:37",
    "17:52", "18:07", "18:37",
    "19:07", "19:37", "20:07", "20:37"
]

HALIFAX_TO_WOODSIDE = [
    "06:52", "07:07", "07:22", "07:37",
    "07:52", "08:07", "08:22", "08:37",
    "08:52", "09:07", "09:22", "09:37",
    "09:52", "10:22", "10:52",
    "11:22", "11:52", "12:22", "12:52",
    "13:22", "13:52", "14:22", "14:52",
    "15:07", "15:22", "15:37", "15:52",
    "16:07", "16:22", "16:37", "16:52",
    "17:07", "17:22", "17:37", "17:52",
    "18:07", "18:22", "18:52",
    "19:22", "19:52", "20:22", "20:52"
]


def easter_sunday(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def alderney_schedule(service_date):
    easter = easter_sunday(service_date.year)

    closures = {
        date(service_date.year, 12, 25),
        date(service_date.year, 1, 1),
        easter - timedelta(days=2),
        easter
    }

    if service_date in closures:
        return [], []

    if service_date.weekday() >= 5:
        return (
            ALDERNEY_TO_HALIFAX_WEEKEND,
            HALIFAX_TO_ALDERNEY_WEEKEND
        )

    return (
        ALDERNEY_TO_HALIFAX_WEEKDAY,
        HALIFAX_TO_ALDERNEY_WEEKDAY
    )


def scheduled_departures(service_date):
    alderney_out, alderney_in = alderney_schedule(
        service_date
    )

    result = {
        "alderney_halifax": alderney_out,
        "halifax_alderney": alderney_in,
        "woodside_halifax": [],
        "halifax_woodside": []
    }

    # Woodside does not operate on weekends.
    # Holiday exceptions must be verified separately.
    if service_date.weekday() < 5:
        result["woodside_halifax"] = WOODSIDE_TO_HALIFAX
        result["halifax_woodside"] = HALIFAX_TO_WOODSIDE

    return result


def convert_time(service_date, value):
    hour, minute = map(int, value.split(":"))

    return datetime(
        service_date.year,
        service_date.month,
        service_date.day,
        hour,
        minute,
        tzinfo=TZ
    )


def read_csv(zf, filename):
    if filename not in zf.namelist():
        return []

    with zf.open(filename) as file:
        return list(csv.DictReader(
            io.TextIOWrapper(file, encoding="utf-8-sig")
        ))


def active_services(calendar, exceptions, service_date):
    day = service_date.strftime("%Y%m%d")
    weekday = service_date.strftime("%A").lower()

    active = {
        row["service_id"]
        for row in calendar
        if row.get("start_date", "") <= day
        <= row.get("end_date", "")
        and row.get(weekday) == "1"
    }

    for row in exceptions:
        if row.get("date") == day:
            if row.get("exception_type") == "1":
                active.add(row["service_id"])
            elif row.get("exception_type") == "2":
                active.discard(row["service_id"])

    return active


def get_gtfs_departures(now):
    request = urllib.request.Request(
        GTFS_URL,
        headers={"User-Agent": "HalifaxFerryBoard/3.0"}
    )

    with urllib.request.urlopen(
        request, timeout=45
    ) as response:
        raw = response.read()

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        routes = read_csv(zf, "routes.txt")
        trips = read_csv(zf, "trips.txt")
        stop_times = read_csv(zf, "stop_times.txt")
        calendar = read_csv(zf, "calendar.txt")
        exceptions = read_csv(zf, "calendar_dates.txt")

    ferry_routes = {
        row["route_id"]: row.get("route_short_name")
        for row in routes
        if row.get("route_short_name") in ("FerD", "FerW")
    }

    ferry_trips = {
        row["trip_id"]: row
        for row in trips
        if row.get("route_id") in ferry_routes
    }

    trip_stops = {}

    for row in stop_times:
        trip_id = row.get("trip_id")

        if trip_id in ferry_trips:
            trip_stops.setdefault(trip_id, []).append(row)

    departures = {
        key: [] for key in DIRECTIONS
    }

    active_trip_count = 0

    for offset in range(3):
        service_date = now.date() + timedelta(days=offset)

        active = active_services(
            calendar, exceptions, service_date
        )

        print(
            "DIAGNOSTIC:",
            service_date,
            "active service IDs:",
            len(active)
        )

        for trip_id, trip in ferry_trips.items():
            if trip["service_id"] not in active:
                continue

            active_trip_count += 1

            stops = sorted(
                trip_stops.get(trip_id, []),
                key=lambda row: int(row["stop_sequence"])
            )

            ids = [row["stop_id"] for row in stops]

            route = ferry_routes[trip["route_id"]]

            destination = (
                ALDERNEY if route == "FerD" else WOODSIDE
            )

            if HALIFAX not in ids or destination not in ids:
                continue

            h_index = ids.index(HALIFAX)
            d_index = ids.index(destination)

            if h_index < d_index:
                key = (
                    "halifax_alderney"
                    if route == "FerD"
                    else "halifax_woodside"
                )
                origin = stops[h_index]
            else:
                key = (
                    "alderney_halifax"
                    if route == "FerD"
                    else "woodside_halifax"
                )
                origin = stops[d_index]

            time_value = origin["departure_time"]

            hours, minutes, seconds = map(
                int, time_value.split(":")
            )

            departure = datetime(
                service_date.year,
                service_date.month,
                service_date.day,
                tzinfo=TZ
            ) + timedelta(
                hours=hours,
                minutes=minutes,
                seconds=seconds
            )

            if departure >= now:
                departures[key].append(departure)

    print(
        "DIAGNOSTIC: Active GTFS ferry trips:",
        active_trip_count
    )

    return departures, active_trip_count


def get_fallback_departures(now):
    departures = {
        key: [] for key in DIRECTIONS
    }

    for offset in range(3):
        service_date = now.date() + timedelta(days=offset)

        schedule = scheduled_departures(service_date)

        for key, times in schedule.items():
            for time_value in times:
                departure = convert_time(
                    service_date, time_value
                )

                if departure >= now:
                    departures[key].append(departure)

    return departures


def main():
    now = datetime.now(TZ)

    print("Halifax time:", now.isoformat())

    use_fallback = False

    try:
        departures, active_trips = get_gtfs_departures(now)

        if active_trips == 0 or not any(
            departures.values()
        ):
            print(
                "WARNING: GTFS has no active upcoming "
                "ferry departures. Using published schedules."
            )
            use_fallback = True

    except Exception as error:
        print("WARNING: GTFS unavailable:", error)
        use_fallback = True

    if use_fallback:
        departures = get_fallback_departures(now)

    if not any(departures.values()):
        raise RuntimeError(
            "No upcoming departures available. "
            "Existing ferries.json preserved."
        )

    output = {}

    for key in DIRECTIONS:
        times = sorted(set(departures[key]))[:3]

        output[key] = [
            value.strftime("%-I:%M %p")
            for value in times
        ]

        output[key + "_iso"] = [
            value.isoformat()
            for value in times
        ]

    output["updated"] = now.strftime("%-I:%M %p")
    output["updated_iso"] = now.isoformat()

    if use_fallback:
        output["source"] = (
            "Halifax Transit published schedules "
            "(fallback, not live departures)"
        )
    else:
        output["source"] = (
            "Halifax Transit GTFS "
            "(scheduled, not live departures)"
        )

    Path(OUTPUT_FILE).write_text(
        json.dumps(output, indent=2) + "\n",
        encoding="utf-8"
    )

    print("RESULT:", json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
