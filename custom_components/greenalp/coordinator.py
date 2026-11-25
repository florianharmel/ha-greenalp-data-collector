"""Schedule one GreenAlp synchronization at a time."""

from asyncio import sleep
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .client import AuthError, Client, DataError, NetworkError
from .const import CONF_INTERVAL, CONF_METERS, DEFAULT_INTERVAL, DOMAIN
from .cost import CONF_TARIFFS, COST_PARTS, FixedTariff, cost_statistics, estimate_costs
from .normalization import PARIS, parse_export, rebuild_statistics


class Coordinator:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.client = Client(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        self.signal = f"{DOMAIN}_{entry.entry_id}"
        self.meters = dict.fromkeys(entry.data.get(CONF_METERS, []))
        self.readings = {}
        self.costs = {}
        self._tariff_options = entry.options.get(CONF_TARIFFS, [])
        self._cost_pending = False
        self.last_sync = None
        self.status = "waiting"
        self.error = None
        self._cancel = None
        self._running = False
        self._closed = False
        self._failures = 0
        self._retry_at = 0
        self._full_pending = False

    def close(self):
        self._closed = True
        if self._cancel:
            self._cancel()
            self._cancel = None

    def schedule(self, delay):
        if self._cancel:
            self._cancel()
        if not self._closed:
            self._cancel = async_call_later(self.hass, delay, self._scheduled_refresh)

    def update_interval(self):
        tariffs = self.entry.options.get(CONF_TARIFFS, [])
        if tariffs != self._tariff_options:
            self._tariff_options = tariffs
            self._cost_pending = True
            if not self._running and not self._failures and self.status != "auth_error":
                self.schedule(0)
            return
        if not self._running and not self._failures and self.status == "connected":
            self.schedule(self.entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL) * 3600)

    async def _scheduled_refresh(self, _now):
        self._cancel = None
        if (remaining := self._retry_at - monotonic()) > 0:
            self.schedule(remaining)
            return
        await self.refresh()

    def _statistic_id(self, meter):
        return f"{DOMAIN}:electricity_{self.entry.unique_id[:12]}_{meter}"

    async def _read_history(self, recorder, meters):
        return await self._read_statistics(recorder, {meter: self._statistic_id(meter) for meter in meters})

    def _cost_statistic_id(self, meter, part):
        return f"{self._statistic_id(meter)}_cost_{part}"

    async def _read_statistics(self, recorder, ids):
        if not ids:
            return {}
        rows = await recorder.async_add_executor_job(
            statistics_during_period, self.hass, datetime(1970, 1, 1, tzinfo=timezone.utc),
            None, set(ids.values()), "hour", None, {"state", "sum"},
        )
        return {
            key: {
                datetime.fromtimestamp(row["start"], PARIS).date(): (
                    Decimal(str(row["state"])) if row.get("state") is not None else None,
                    Decimal(str(row["sum"])),
                )
                for row in rows.get(statistic_id, [])
                if row.get("sum") is not None
            }
            for key, statistic_id in ids.items()
        }

    async def refresh(self, *, full=False):
        if self._closed:
            return
        self._full_pending |= full
        if self._running or self.status == "auth_error" or monotonic() < self._retry_at:
            return
        self._running = True
        self._full_pending, full = False, self._full_pending
        if self._cancel:
            self._cancel()
            self._cancel = None
        delay = self.entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL) * 3600

        try:
            recorder = get_instance(self.hass)
            await recorder.async_block_till_done()
            if not self.readings and self.meters:
                existing = await self._read_history(recorder, self.meters)
                self.readings = {
                    meter: {day: state for day, (state, _) in rows.items() if state is not None}
                    for meter, rows in existing.items()
                }
            incoming = await self.hass.async_add_executor_job(self._fetch)
            if self._closed:
                return
            history = await self._read_history(recorder, incoming)
            if self._closed:
                return
            today = datetime.now(PARIS).date()
            submitted = {}
            for meter, readings in incoming.items():
                points = rebuild_statistics(readings, history[meter], today, full)
                points = [point for point in points if self._unpack(point) != history[meter].get(
                    point["start"].astimezone(PARIS).date()
                )]
                if points:
                    submitted[meter] = points
                    async_add_external_statistics(self.hass, {
                        "statistic_id": self._statistic_id(meter),
                        "source": DOMAIN,
                        "name": f"GreenAlp Électricité {meter[:8]}",
                        "unit_of_measurement": "kWh",
                        "unit_class": "energy",
                        "has_sum": True,
                        "mean_type": StatisticMeanType.NONE,
                    }, [{key: value for key, value in point.items() if value is not None}
                        for point in points])
            await recorder.async_block_till_done()
            if self._closed:
                return
            stored = history | await self._confirm_import(recorder, submitted)
            self.readings.update({
                meter: {day: state for day, (state, _) in rows.items() if state is not None}
                for meter, rows in stored.items()
            })
            await self._sync_costs(recorder, today)
            if self._closed:
                return
            new_meters = self.meters | dict.fromkeys(incoming)
            if new_meters != self.meters:
                self.meters = new_meters
                self.hass.config_entries.async_update_entry(
                    self.entry, data={**self.entry.data, CONF_METERS: list(self.meters)},
                )
            self.last_sync = dt_util.utcnow()
            self.status, self.error = "connected", None
            self._failures = 0
            self._retry_at = 0
        except AuthError:
            self.status, self.error = "auth_error", "authentication"
            if not self._closed:
                self.entry.async_start_reauth(self.hass)
        except NetworkError:
            self.status, self.error = "network_error", "network"
            self._failures += 1
            delay = min(delay, 60 * 2 ** min(self._failures - 1, 6))
            self._retry_at = monotonic() + delay
            self._full_pending |= full
        except DataError:
            self.status, self.error = "data_error", "data"
            self._full_pending |= full
        except Exception:
            self.status, self.error = "import_error", "recorder"
            self._full_pending |= full
        finally:
            self._running = False
            if not self._closed:
                async_dispatcher_send(self.hass, self.signal)
                if self.status != "auth_error":
                    self.schedule(0 if (self._full_pending or self._cost_pending) and not self.error else delay)

    async def _sync_costs(self, recorder, today):
        tariffs = [FixedTariff.from_options(item) for item in self._tariff_options]
        self._cost_pending = False
        if not tariffs:
            return
        estimates = {meter: estimate_costs(readings, tariffs, today)
                     for meter, readings in self.readings.items()}
        ids = {(meter, part): self._cost_statistic_id(meter, part)
               for meter in estimates for part in COST_PARTS}
        history = await self._read_statistics(recorder, ids)
        if self._closed:
            return
        labels = {"consumption": "Consommation", "subscription": "Abonnement", "total": "Total"}
        submitted = {}
        for (meter, part), statistic_id in ids.items():
            key = (meter, part)
            points = [point for point in cost_statistics(estimates[meter], part)
                      if self._unpack(point) != history[key].get(point["start"].astimezone(PARIS).date())]
            if points:
                submitted[key] = points
                async_add_external_statistics(self.hass, {
                    "statistic_id": statistic_id, "source": DOMAIN,
                    "name": f"GreenAlp Coût estimé · {labels[part]} {meter[:8]}",
                    "unit_of_measurement": "EUR", "unit_class": None,
                    "has_sum": True, "mean_type": StatisticMeanType.NONE,
                }, points)
        if submitted:
            await recorder.async_block_till_done()
            await self._confirm_import(recorder, submitted, ids)
        self.costs = estimates

    @staticmethod
    def _unpack(point):
        state = point["state"]
        return (Decimal(str(state)) if state is not None else None, Decimal(str(point["sum"])))

    async def _confirm_import(self, recorder, submitted, ids=None):
        for delay in (0, 0.1, 0.3, 1):
            if delay:
                await sleep(delay)
            if ids is None:
                stored = await self._read_history(recorder, submitted)
            else:
                stored = await self._read_statistics(recorder, {key: ids[key] for key in submitted})
            if all(
                self._unpack(point) == stored[meter].get(point["start"].astimezone(PARIS).date())
                for meter, points in submitted.items() for point in points
            ):
                return stored
        raise RuntimeError("Recorder did not persist the expected values")

    def _fetch(self):
        return parse_export(self.client.export())
