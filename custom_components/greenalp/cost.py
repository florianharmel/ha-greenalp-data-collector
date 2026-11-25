"""Effective-dated electricity estimates, independent of Home Assistant."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .normalization import DAY, statistic_start

CONF_TARIFFS = "tariffs"
PRICE = "price_per_kwh"
SUBSCRIPTION = "monthly_subscription"
EFFECTIVE = "effective_from"
RETROACTIVE = "allow_retroactive"
COST_PARTS = ("consumption", "subscription", "total")
CENT = Decimal("0.01")
MICRO_EURO = Decimal("0.000001")


class RetroactiveTariffError(ValueError):
    """A tariff change requires explicit historical authorization."""


def _amount(raw, precision):
    value = Decimal(str(raw).strip().replace(",", "."))
    if not value.is_finite() or not 0 <= value <= 1_000_000:
        raise ValueError("Invalid tariff amount")
    return str(value.quantize(precision, rounding=ROUND_HALF_UP))


def update_tariffs(saved, effective, price, subscription, today, allow_retroactive):
    """Insert or replace one effective date, leaving other rates intact."""
    try:
        day = date.fromisoformat(effective)
        if day < date(1970, 1, 2):
            raise ValueError("Unsupported effective date")
        rate = {
            EFFECTIVE: day.isoformat(),
            PRICE: _amount(price, MICRO_EURO),
            SUBSCRIPTION: _amount(subscription, CENT),
        }
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid tariff") from None
    if rate in saved:
        return saved
    if saved and day < today and not allow_retroactive:
        raise RetroactiveTariffError
    return sorted(
        [item for item in saved if item[EFFECTIVE] != rate[EFFECTIVE]] + [rate],
        key=lambda item: item[EFFECTIVE],
    )


@dataclass(frozen=True)
class FixedTariff:
    effective: date
    price: Decimal
    subscription: Decimal

    @classmethod
    def from_options(cls, item):
        return cls(date.fromisoformat(item[EFFECTIVE]), Decimal(item[PRICE]), Decimal(item[SUBSCRIPTION]))

    def daily_cost(self, day, kwh):
        days = monthrange(day.year, day.month)[1]
        # Differences of rounded month-to-date shares sum to the exact monthly charge.
        subscription = (self.subscription * day.day / days).quantize(CENT, rounding=ROUND_HALF_UP) - (
            self.subscription * (day.day - 1) / days
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        consumption = None
        if kwh is not None or self.price == 0:
            consumption = ((kwh or Decimal(0)) * self.price).quantize(
                MICRO_EURO, rounding=ROUND_HALF_UP,
            )
        return consumption, subscription


def estimate_costs(readings, tariffs, today):
    """Build daily estimates for completed days covered by a tariff."""
    series = {part: {} for part in COST_PARTS}
    if not tariffs:
        return series
    for index, tariff in enumerate(tariffs):
        end = min(today, tariffs[index + 1].effective) if index + 1 < len(tariffs) else today
        day = tariff.effective
        while day < end:
            consumption, subscription = tariff.daily_cost(day, readings.get(day))
            series["subscription"][day] = subscription
            if consumption is not None:
                series["consumption"][day] = consumption
                series["total"][day] = consumption + subscription
            day += DAY
    return series


def cost_statistics(series, part):
    """Produce cumulative EUR points from known charges on each covered day."""
    subscription = series["subscription"]
    if not subscription:
        return []
    first = min(subscription)
    points = [{"start": statistic_start(first - DAY), "state": None, "sum": 0.0}]
    total = Decimal(0)
    for day, fee in subscription.items():
        value = series[part].get(day)
        if value is not None:
            total += value
        elif part == "total":
            total += fee
        points.append({"start": statistic_start(day),
                       "state": float(value) if value is not None else None, "sum": float(total)})
    return points
