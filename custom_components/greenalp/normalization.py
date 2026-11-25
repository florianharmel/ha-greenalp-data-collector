"""Daily GreenAlp CSV and cumulative Recorder values."""

import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
from zoneinfo import ZoneInfo

from .client import DataError

PARIS = ZoneInfo("Europe/Paris")
DAY = timedelta(days=1)
CONSUMPTION = " - Consommation (kWh)"
INDEX = " - Index (kWh)"


def parse_export(payload):
    """Return daily kWh by electricity meter, keyed by a stable digest."""
    try:
        rows = csv.reader(StringIO(payload.decode("utf-8-sig"), newline=""), delimiter=";", strict=True)
        header = next(rows, [])
        if not header or header[0] != "Date":
            raise DataError("Missing CSV date column")
        columns = {}
        for column, name in enumerate(header[1:], 1):
            if not name.endswith(CONSUMPTION):
                continue
            meter = name.removesuffix(CONSUMPTION)
            if meter + INDEX not in header or "elec" not in meter.casefold().split():
                continue
            key = sha256(meter.split()[0].encode()).hexdigest()[:24]
            if key in columns:
                raise DataError("Ambiguous electricity meter")
            columns[key] = column
        if not columns:
            raise DataError("No supported electricity meter columns")

        result = {key: {} for key in columns}
        for row in rows:
            if len(row) != len(header):
                raise DataError("Unexpected CSV row width")
            day = date.fromisoformat(row[0])
            if day.isoformat() != row[0]:
                raise DataError("Unexpected CSV date format")
            for key, column in columns.items():
                raw = row[column].strip()
                value = Decimal(raw.replace(",", ".")) if raw else None
                if value is not None and (not value.is_finite() or value < 0):
                    raise DataError("Invalid daily energy")
                previous = result[key].get(day)
                if previous is not None and value is not None and previous != value:
                    raise DataError("Conflicting daily readings")
                if previous is None:
                    result[key][day] = value
        return result
    except (ValueError, csv.Error, InvalidOperation):
        raise DataError("Invalid GreenAlp CSV") from None


def statistic_start(day):
    """Use the last hour of the local consumption day."""
    midnight = datetime.combine(day + DAY, time.min, PARIS)
    return midnight.astimezone(timezone.utc) - timedelta(hours=1)


def rebuild_statistics(incoming, history, today, full=False):
    """Merge valid readings and rebuild sums from a stable previous anchor."""
    valid = {day: value for day, value in incoming.items() if day < today and value is not None}
    if not valid:
        return []
    measured = [day for day, (state, _) in history.items() if state is not None]
    if full or not measured:
        first = min(valid)
    else:
        first = min(today - 7 * DAY, max(measured) + DAY)
    affected = {day: state for day, (state, _) in history.items() if day >= first and state is not None}
    affected.update({day: value for day, value in valid.items() if day >= first})
    if not affected:
        return []
    earliest = min(affected)
    anchors = [day for day in history if day < earliest]
    affected.update({day: state for day, (state, _) in history.items()
                     if day >= earliest and state is None and day not in affected})
    rows = []
    total = history[max(anchors)][1] if anchors else Decimal(0)
    if not anchors:
        rows.append({"start": statistic_start(earliest - DAY), "state": None, "sum": 0.0})
    for day, value in sorted(affected.items()):
        if value is not None:
            total += value
        rows.append({"start": statistic_start(day), "state": float(value) if value is not None else None,
                     "sum": float(total)})
    return rows


def period_total(readings, start, end):
    """Sum a complete inclusive period, with an explicit missing result."""
    total = Decimal(0)
    while start <= end:
        value = readings.get(start)
        if value is None:
            return None
        total += value
        start += DAY
    return total
