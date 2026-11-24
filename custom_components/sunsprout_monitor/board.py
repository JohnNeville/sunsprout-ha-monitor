"""The monitor device of each SunSprout board, and its entities.

Every board found among the ESPHome devices gets a "monitor" device that is connected via the ESPHome device (Home Assistant shows
it as "connected via" the board and lists it with it), with the board's open problems, a problem flag and the recorded setup state. The same problems are
raised as Repairs; the entities are for tracking them on a dashboard or in automations."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN

SIGNAL_BOARD_UPDATE = f"{DOMAIN}_board_update"
SETUP_STATES = ("complete", "unset", "outdated", "modified", "unsupported", "unknown")


class BoardEntity:
    """Shared by the board's entities: the monitor device, and a refresh whenever the monitor has evaluated."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, monitor, dev_id: str, key: str) -> None:
        self._mon = monitor
        self._dev_id = dev_id
        self._attr_unique_id = f"{DOMAIN}_{dev_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, dev_id)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_BOARD_UPDATE, self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()

    def _problems(self):
        return self._mon.problems_by_device.get(self._dev_id, [])


def problem_titles(problems) -> list[str]:
    return [f"{p.key}: {p.detail}" for p in problems]
