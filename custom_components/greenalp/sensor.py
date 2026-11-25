"""GreenAlp diagnostic and period consumption sensors."""

from datetime import datetime, time, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval

from .normalization import DAY, PARIS, period_total

PERIODS = ("yesterday", "week", "month")
DIAGNOSTICS = ("last_sync", "last_data", "data_age", "connection", "error")


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()

    @callback
    def add_meters():
        new = set(coordinator.meters) - known
        known.update(new)
        async_add_entities(
            GreenAlpSensor(coordinator, key, meter) for meter in sorted(new) for key in PERIODS
        )

    entry.async_on_unload(async_dispatcher_connect(hass, coordinator.signal, add_meters))
    async_add_entities(GreenAlpSensor(coordinator, key) for key in DIAGNOSTICS)
    add_meters()


class GreenAlpSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, meter=None):
        self.coordinator = coordinator
        self.key = key
        self.meter = meter
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{meter or 'account'}_{key}"
        if meter:
            self._attr_name = {
                "yesterday": "GreenAlp Veille",
                "week": "GreenAlp Semaine",
                "month": "GreenAlp Mois",
            }[key] + f" {meter[:8]}"
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
        }[self.key]
        return start, yesterday

    @property
    def extra_state_attributes(self):
        if not self.meter:
            return None
        start, end = self._bounds()
        readings = self.coordinator.readings.get(self.meter, {})
        expected = max(0, (end - start).days + 1)
        available = sum(start <= day <= end for day in readings)
        return {"expected_days": expected, "available_days": available,
                "missing_days": expected - available}

    @property
    def native_value(self):
        coordinator = self.coordinator
        if self.meter:
            start, end = self._bounds()
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
