"""GreenAlp diagnostic and period consumption sensors."""

from datetime import datetime, time, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval

from .cost import CONF_TARIFFS
from .normalization import DAY, PARIS, period_total

PERIODS = ("yesterday", "week", "month")
COST_PERIODS = (*PERIODS, "year")
PERIOD_LABELS = {"yesterday": "Veille", "week": "Semaine", "month": "Mois", "year": "Année"}
DIAGNOSTICS = ("last_sync", "last_data", "data_age", "connection", "error")


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()
    priced = set()

    @callback
    def add_meters():
        new = set(coordinator.meters) - known
        known.update(new)
        async_add_entities(
            GreenAlpSensor(coordinator, key, meter) for meter in sorted(new) for key in PERIODS
        )
        if entry.options.get(CONF_TARIFFS):
            new_cost = set(coordinator.meters) - priced
            priced.update(new_cost)
            async_add_entities(
                GreenAlpSensor(coordinator, key, meter, cost=True)
                for meter in sorted(new_cost) for key in COST_PERIODS
            )

    entry.async_on_unload(async_dispatcher_connect(hass, coordinator.signal, add_meters))
    async_add_entities(GreenAlpSensor(coordinator, key) for key in DIAGNOSTICS)
    add_meters()


class GreenAlpSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, meter=None, *, cost=False):
        self.coordinator = coordinator
        self.key = key
        self.meter = meter
        self.cost = cost
        self._attr_translation_key = key
        suffix = f"cost_{key}" if cost else key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{meter or 'account'}_{suffix}"
        if cost:
            self._attr_name = f"GreenAlp Coût estimé {PERIOD_LABELS[key]} {meter[:8]}"
            self._attr_native_unit_of_measurement = "EUR"
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_suggested_display_precision = 2
        elif meter:
            self._attr_name = f"GreenAlp {PERIOD_LABELS[key]} {meter[:8]}"
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_device_class = SensorDeviceClass.ENERGY
        else:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            if key in ("last_sync", "last_data"):
                self._attr_device_class = SensorDeviceClass.TIMESTAMP
            if key == "data_age":
                self._attr_device_class = SensorDeviceClass.DURATION
                self._attr_native_unit_of_measurement = UnitOfTime.HOURS

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(
            self.hass, self.coordinator.signal, self.async_write_ha_state,
        ))
        if self.meter or self.key == "data_age":
            self.async_on_remove(async_track_time_interval(
                self.hass, self._update_time, timedelta(minutes=5),
            ))

    @callback
    def _update_time(self, _now):
        self.async_write_ha_state()

    def _bounds(self):
        today = datetime.now(PARIS).date()
        yesterday = today - DAY
        start = {
            "yesterday": yesterday,
            "week": today - timedelta(days=today.weekday()),
            "month": today.replace(day=1),
            "year": today.replace(month=1, day=1),
        }[self.key]
        return start, yesterday

    @property
    def extra_state_attributes(self):
        if not self.meter:
            return None
        start, end = self._bounds()
        if self.cost:
            return self._cost_attributes(start, end)
        readings = self.coordinator.readings.get(self.meter, {})
        expected = max(0, (end - start).days + 1)
        available = sum(start <= day <= end for day in readings)
        return {"expected_days": expected, "available_days": available,
                "missing_days": expected - available}

    def _cost_attributes(self, start, end):
        series = self.coordinator.costs.get(self.meter)
        attributes = {"estimated": True, "billed": False}
        if not series or not series["subscription"]:
            return attributes
        start = max(start, min(series["subscription"]))
        covered = max(0, (end - start).days + 1)
        attributes["covered_days"] = covered
        attributes["missing_days"] = covered - sum(start <= day <= end for day in series["total"])
        for part, days in series.items():
            total = period_total(days, start, end) if covered else None
            attributes[f"{part}_eur"] = float(total) if total is not None else None
        return attributes

    @property
    def native_value(self):
        coordinator = self.coordinator
        if self.meter:
            start, end = self._bounds()
            if self.cost:
                return self._cost_attributes(start, end).get("total_eur")
            if end < start:
                return None
            total = period_total(coordinator.readings.get(self.meter, {}), start, end)
            return float(total) if total is not None else None
        if self.key == "last_sync":
            return coordinator.last_sync
        if self.key == "connection":
            return coordinator.status
        if self.key == "error":
            return coordinator.error or "none"
        latest = max((day for days in coordinator.readings.values() for day in days), default=None)
        if latest is None:
            return None
        end = datetime.combine(latest + DAY, time.min, PARIS).astimezone(timezone.utc)
        if self.key == "last_data":
            return end
        return round(max(0, (datetime.now(timezone.utc) - end).total_seconds()) / 3600, 1)
