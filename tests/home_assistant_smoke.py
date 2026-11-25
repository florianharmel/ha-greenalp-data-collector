"""Run against Home Assistant Core 2026.11.3 and a temporary Recorder."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.energy.validate import async_validate
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import async_list_statistic_ids
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry


async def main():
    with TemporaryDirectory() as config:
        Path(config, "custom_components").symlink_to("/integration", target_is_directory=True)
        hass = HomeAssistant(config)
        loader.async_setup(hass)
        assert await async_from_config_dict({"recorder": {}}, hass)
        await hass.async_start()
        try:
            from custom_components.greenalp.client import AuthError, Client, NetworkError

            fixture = Path(__file__).with_name("fixtures").joinpath("export.txt").read_bytes()
            with patch.object(Client, "login"), patch.object(Client, "export", return_value=fixture):
                flow = await hass.config_entries.flow.async_init("greenalp", context={"source": "user"})
                assert flow["type"] == "form"
                result = await hass.config_entries.flow.async_configure(
                    flow["flow_id"], {"username": "synthetic", "password": "synthetic"},
                )
                assert result["type"] == "create_entry"
                entry = result["result"]
                coordinator = entry.runtime_data
                async with asyncio.timeout(20):
                    while coordinator.status == "waiting":
                        await asyncio.sleep(0.02)
                assert coordinator.status == "connected", coordinator.error
                meter = next(iter(coordinator.meters))
                recorder = get_instance(hass)
                history = await coordinator._read_history(recorder, [meter])
                assert len(history[meter]) == 4
                await hass.async_block_till_done()
                entities = entity_registry.async_entries_for_config_entry(
                    entity_registry.async_get(hass), entry.entry_id,
                )
                assert sum(entity.domain == "button" for entity in entities) == 2
                assert sum(entity.domain == "sensor" for entity in entities) == 8
                options = await hass.config_entries.options.async_init(entry.entry_id)
                assert options["type"] == "form"
                priced = await hass.config_entries.options.async_configure(options["flow_id"], {
                    "interval_hours": 6, "price_per_kwh": 0.25,
                    "monthly_subscription": 31, "effective_from": "2026-03-28",
                })
                assert priced["type"] == "create_entry"
                async with asyncio.timeout(20):
                    while not coordinator.costs:
                        await asyncio.sleep(0.02)
                await hass.async_block_till_done()
                entities = entity_registry.async_entries_for_config_entry(
                    entity_registry.async_get(hass), entry.entry_id,
                )
                assert sum(entity.domain == "sensor" for entity in entities) == 12
                cost_id = coordinator._cost_statistic_id(meter, "total")
                costs = await coordinator._read_statistics(recorder, {"total": cost_id})
                assert costs["total"][date(2026, 3, 28)] == (Decimal("1.375"), Decimal("1.375"))
                assert costs["total"][date(2026, 3, 30)][0] is None
                stats = await async_list_statistic_ids(hass, {cost_id})
                assert stats[0]["statistics_unit_of_measurement"] == "EUR"
                assert stats[0]["has_sum"]
                manager = await async_get_manager(hass)
                await manager.async_update({"energy_sources": [{
                    "type": "grid", "stat_energy_from": coordinator._statistic_id(meter),
                    "stat_cost": cost_id,
                }]})
                validation = await async_validate(hass)
                assert validation.as_dict()["energy_sources"] == [[]]

                await coordinator.refresh(full=True)
                assert await coordinator._read_history(recorder, [meter]) == history
                assert await coordinator._read_statistics(recorder, {"total": cost_id}) == costs

                corrected = fixture.replace(b"1.500;100", b"3.500;100")
                with patch.object(Client, "export", return_value=corrected):
                    await coordinator.refresh(full=True)
                changed = (await coordinator._read_history(recorder, [meter]))[meter]
                old = history[meter]
                assert changed[date(2026, 3, 28)] == (Decimal("3.5"), Decimal("3.5")), (
                    coordinator.status, coordinator.error, changed,
                )
                assert changed[date(2026, 3, 31)][0] == old[date(2026, 3, 31)][0]
                assert changed[date(2026, 3, 31)][1] - old[date(2026, 3, 31)][1] == 2
                corrected_cost = (await coordinator._read_statistics(recorder, {"total": cost_id}))["total"]
                assert corrected_cost[date(2026, 3, 28)][0] == Decimal("1.875")
                assert corrected_cost[date(2026, 3, 31)][0] == costs["total"][date(2026, 3, 31)][0]
                assert corrected_cost[max(corrected_cost)][1] - costs["total"][max(corrected_cost)][1] == Decimal("0.5")
                future = date.today() + timedelta(days=2)
                options = await hass.config_entries.options.async_init(entry.entry_id)
                tariff = {"interval_hours": 6, "price_per_kwh": 0.50, "effective_from": "2026-03-28"}
                denied = await hass.config_entries.options.async_configure(options["flow_id"], tariff)
                assert denied["errors"]["base"] == "retroactive_tariff"
                tariff["effective_from"] = future.isoformat()
                with patch.object(Client, "export", return_value=corrected):
                    result = await hass.config_entries.options.async_configure(options["flow_id"], tariff)
                    assert result["type"] == "create_entry"
                    async with asyncio.timeout(20):
                        while coordinator._running or coordinator._cost_pending:
                            await asyncio.sleep(0.02)
                assert (await coordinator._read_statistics(recorder, {"total": cost_id}))["total"] == corrected_cost

                options = await hass.config_entries.options.async_init(entry.entry_id)
                tariff.update(effective_from="2026-03-28", monthly_subscription=31, allow_retroactive=True)
                with patch.object(Client, "export", return_value=corrected):
                    result = await hass.config_entries.options.async_configure(options["flow_id"], tariff)
                    assert result["type"] == "create_entry"
                    async with asyncio.timeout(20):
                        while coordinator._running or coordinator._cost_pending:
                            await asyncio.sleep(0.02)
                retroactive = (await coordinator._read_statistics(recorder, {"total": cost_id}))["total"]
                assert retroactive[date(2026, 3, 28)] == (Decimal("2.75"), Decimal("2.75"))

                with patch.object(Client, "export", side_effect=NetworkError()) as failed:
                    await coordinator.refresh()
                    await coordinator.refresh()
                    assert failed.call_count == 1
                assert coordinator.status == "network_error"
                assert (await coordinator._read_history(recorder, [meter]))[meter] == changed
                with (
                    patch("custom_components.greenalp.coordinator.monotonic",
                          return_value=coordinator._retry_at + 1),
                    patch.object(Client, "export", side_effect=AuthError()) as rejected,
                ):
                    await coordinator.refresh()
                    await coordinator.refresh()
                    assert rejected.call_count == 1
                assert coordinator.status == "auth_error"
                assert (await coordinator._read_history(recorder, [meter]))[meter] == changed
            assert await hass.config_entries.async_unload(entry.entry_id)
            print("Config Flow, Recorder, Énergie, corrections et conservation testés.")
        finally:
            await hass.async_stop()


if __name__ == "__main__":
    asyncio.run(main())
