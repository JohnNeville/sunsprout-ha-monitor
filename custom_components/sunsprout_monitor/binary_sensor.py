"""Per board: is anything wrong."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .board import BoardEntity, problem_titles
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    hass.data[DOMAIN][entry.entry_id].register_platform("binary_sensor", async_add_entities)


class BoardProblem(BoardEntity, BinarySensorEntity):
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @classmethod
    def create(cls, monitor, dev_id):
        return cls(monitor, dev_id, "problem")

    @property
    def is_on(self) -> bool:
        return bool(self._problems())

    @property
    def extra_state_attributes(self) -> dict:
        return {"problems": problem_titles(self._problems())}
