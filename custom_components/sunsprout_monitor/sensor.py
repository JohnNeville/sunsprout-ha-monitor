"""One summary sensor: how many SunSprout problems are open."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ProblemCount(hass.data[DOMAIN][entry.entry_id])])


class ProblemCount(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Open problems"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_should_poll = False

    def __init__(self, monitor) -> None:
        self._mon = monitor
        self._attr_unique_id = f"{DOMAIN}_problem_count"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_track_time_interval(
            self.hass, self._refresh, timedelta(minutes=1)))

    @callback
    def _refresh(self, _now) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return sum(len(p) for p in self._mon.problems.values())

    @property
    def extra_state_attributes(self) -> dict:
        return {dev: [f"{p.key}: {p.detail}" for p in ps] for dev, ps in self._mon.problems.items() if ps}
