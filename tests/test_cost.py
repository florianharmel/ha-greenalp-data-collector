import unittest
from datetime import date
from decimal import Decimal

from custom_components.greenalp.cost import (
    FixedTariff,
    RetroactiveTariffError,
    cost_statistics,
    estimate_costs,
    update_tariffs,
)
from custom_components.greenalp.normalization import statistic_start


class CostTest(unittest.TestCase):
    def test_calendar_months_and_independent_subscription(self):
        for year, month, next_month in [(2024, 2, 3), (2026, 2, 3), (2026, 3, 4), (2026, 4, 5)]:
            with self.subTest(year=year, month=month):
                first = date(year, month, 1)
                tariff = FixedTariff(first, Decimal("0.25"), Decimal("12.17"))
                estimates = estimate_costs({first: Decimal("0")}, [tariff], date(year, next_month, 1))
                self.assertEqual(sum(estimates["subscription"].values()), Decimal("12.17"))
                self.assertEqual(estimates["consumption"], {first: Decimal("0")})
                self.assertEqual(estimates["total"], {first: estimates["subscription"][first]})
                total = cost_statistics(estimates, "total")
                self.assertEqual(total[-1]["sum"], 12.17)
                self.assertIsNone(total[-1]["state"])

    def test_tariff_changes_and_corrections(self):
        first, second, today = date(2026, 3, 28), date(2026, 3, 29), date(2026, 3, 30)
        saved = update_tariffs([], first.isoformat(), "0,25", 0, today, False)
        with self.assertRaises(RetroactiveTariffError):
            update_tariffs(saved, first.isoformat(), "0.50", 0, today, False)
        updated = update_tariffs(saved, second.isoformat(), "0.50", 0, second, False)
        tariffs = [FixedTariff.from_options(item) for item in updated]
        daily = estimate_costs({first: Decimal(2), second: Decimal(3)}, tariffs, today)
        self.assertEqual(daily["total"], {first: Decimal("0.50"), second: Decimal("1.50")})
        corrected = estimate_costs({first: Decimal(4), second: Decimal(3)}, tariffs, today)
        self.assertEqual(corrected["total"][first], Decimal("1.00"))
        self.assertEqual(corrected["total"][second], daily["total"][second])
        self.assertEqual(cost_statistics(corrected, "total")[-1],
                         {"start": statistic_start(second), "state": 1.5, "sum": 2.5})
        replaced = update_tariffs(updated, first.isoformat(), "0.75", 0, today, True)
        self.assertEqual(len(replaced), 2)
        self.assertEqual(replaced[1], updated[1])

    def test_future_and_invalid_values(self):
        today = date(2026, 3, 29)
        self.assertEqual(estimate_costs({}, [FixedTariff(today, Decimal(0), Decimal(0))], today)["total"], {})
        for value in ("NaN", "-1", "Infinity"):
            with self.assertRaises(ValueError):
                update_tariffs([], today.isoformat(), value, 0, today, False)
