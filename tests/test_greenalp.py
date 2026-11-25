import io
import unittest
from datetime import date, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

from custom_components.greenalp.client import Client, DataError, NetworkError
from custom_components.greenalp.normalization import (
    PARIS,
    parse_export,
    period_total,
    rebuild_statistics,
    statistic_start,
)

CSV = (Path(__file__).parent / "fixtures" / "export.txt").read_bytes()


def saved(points):
    return {
        point["start"].astimezone(PARIS).date(): (
            Decimal(str(point["state"])) if point["state"] is not None else None,
            Decimal(str(point["sum"])),
        )
        for point in points
    }


class NormalizationTest(unittest.TestCase):
    def setUp(self):
        self.readings = next(iter(parse_export(CSV).values()))
        self.today = date(2026, 4, 1)

    def test_zero_and_missing_are_distinct(self):
        zero, missing = date(2026, 3, 29), date(2026, 3, 30)
        self.assertEqual(period_total(self.readings, zero, zero), Decimal(0))
        self.assertIsNone(period_total(self.readings, zero, missing))

    def test_duplicate_rows(self):
        row = CSV.splitlines()[-1]
        self.assertEqual(parse_export(CSV + row + b"\n"), parse_export(CSV))
        with self.assertRaises(DataError):
            parse_export(CSV + row.replace(b"2.250", b"5") + b"\n")

    def test_clock_changes(self):
        for before, after, hours in [
            (date(2026, 3, 28), date(2026, 3, 29), 23),
            (date(2026, 10, 24), date(2026, 10, 25), 25),
        ]:
            self.assertEqual(statistic_start(after) - statistic_start(before), timedelta(hours=hours))
            self.assertEqual(statistic_start(after).astimezone(PARIS).date(), after)

    def test_idempotent_reimport_and_correction(self):
        history = saved(rebuild_statistics(self.readings, {}, self.today))
        self.assertEqual(history | saved(rebuild_statistics(self.readings, history, self.today)), history)
        day = date(2026, 3, 28)
        corrected = {**self.readings, day: self.readings[day] + Decimal(2)}
        rewritten = history | saved(rebuild_statistics(corrected, history, self.today))
        final_day = date(2026, 3, 31)
        self.assertEqual(rewritten[day][0] - history[day][0], Decimal(2))
        self.assertEqual(rewritten[final_day][0], history[final_day][0])
        self.assertEqual(rewritten[final_day][1] - history[final_day][1], Decimal(2))
        self.assertNotIn(date(2026, 3, 30), rewritten)

    def test_full_reimport_extends_history_and_preserves_later_values(self):
        early = date(2026, 3, 1)
        history = saved(rebuild_statistics(self.readings, {}, self.today))
        rebuilt = history | saved(rebuild_statistics({early: Decimal(4)}, history, self.today, True))
        self.assertEqual(rebuilt[date(2026, 3, 27)], (None, Decimal(4)))
        self.assertEqual(rebuilt[date(2026, 3, 31)][1], Decimal("7.75"))

    def test_regular_import_limits_corrections_to_window_and_handles_long_gap(self):
        history = saved(rebuild_statistics(self.readings, {}, self.today))
        later = date(2026, 5, 1)
        old = min(self.readings)
        new = date(2026, 4, 1)
        rebuilt = history | saved(rebuild_statistics({old: Decimal(99), new: Decimal(4)}, history, later))
        self.assertEqual(rebuilt[old], history[old])
        self.assertEqual(rebuilt[new][1], Decimal("7.75"))


class Response(io.BytesIO):
    status = 200

    def __init__(self, content, media_type):
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = media_type


class FakeOpener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def login():
    return Response(b'{"token":"synthetic"}', "application/json")


def export():
    return Response(CSV, "text/csv; charset=utf-8")


class ClientTest(unittest.TestCase):
    def test_bearer_and_single_relogin(self):
        rejected = HTTPError("https://example.invalid", 401, "", {}, io.BytesIO())
        opener = FakeOpener(login(), export(), rejected, login(), export())
        client = Client("synthetic", "synthetic", opener)
        self.assertEqual(client.export(), CSV)
        self.assertEqual(client.export(), CSV)
        self.assertEqual([call.get_method() for call in opener.calls], ["POST", "GET", "GET", "POST", "GET"])
        self.assertEqual(opener.calls[-1].get_header("Authorization"), "Bearer synthetic")

    def test_network_error_has_no_immediate_retry(self):
        opener = FakeOpener(URLError("synthetic"))
        with self.assertRaises(NetworkError):
            Client("synthetic", "synthetic", opener).export()
        self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
