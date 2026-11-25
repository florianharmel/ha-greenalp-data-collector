"""Manual GreenAlp synchronization controls."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(GreenAlpButton(entry.runtime_data, full) for full in (False, True))


class GreenAlpButton(ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(self, coordinator, full):
        self.coordinator = coordinator
        self.full = full
        self._attr_translation_key = "resync" if full else "sync"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self._attr_translation_key}"

    async def async_press(self):
        await self.coordinator.refresh(full=self.full)
