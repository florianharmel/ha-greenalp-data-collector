"""GreenAlp integration. The client and parser can be imported without HA."""


async def async_setup_entry(hass, entry):
    from .coordinator import Coordinator

    coordinator = entry.runtime_data = Coordinator(hass, entry)
    entry.async_on_unload(coordinator.close)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "button"])
    coordinator.schedule(0)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, ["sensor", "button"])


async def _async_update_options(hass, entry):
    entry.runtime_data.update_interval()
