"""The sensors: how many problems are open in all, and per board how many and what state its setup is in."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval

from .board import SETUP_STATES, BoardEntity, problem_titles
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    monitor = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ProblemCount(monitor)])
    monitor.register_platform("sensor", async_add_entities)


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


class BoardProblemCount(BoardEntity, SensorEntity):
    _attr_name = "Open problems"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @classmethod
    def create(cls, monitor, dev_id):
        return cls(monitor, dev_id, "problems")

    @property
    def native_value(self) -> int:
        return len(self._problems())

    @property
    def extra_state_attributes(self) -> dict:
        return {"problems": problem_titles(self._problems())}


class BoardSetupState(BoardEntity, SensorEntity):
    """What the board says about its first-time setup: complete, unset (not done), outdated (newer options to set), modified
    (values changed by hand afterwards) or unsupported (older firmware without the setup actions)."""

    _attr_name = "Setup"
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SETUP_STATES)

    @classmethod
    def create(cls, monitor, dev_id):
        return cls(monitor, dev_id, "setup")

    @property
    def native_value(self) -> str:
        state = (self._mon.setup_info.get(self._dev_id) or {}).get("setup_state", "unknown")
        return state if state in SETUP_STATES else "unknown"
