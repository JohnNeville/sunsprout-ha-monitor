"""Fix flows for the setup issues: the "Fix" button opens the battery setup for that board."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .setup_flow import BatterySetupMixin


class BatterySetupRepairFlow(BatterySetupMixin, RepairsFlow):
    def __init__(self, hass: HomeAssistant, device_id: str) -> None:
        self.hass = hass
        self._dev_id = device_id
        self._values: dict[str, Any] = {}
        self._warnings: list[str] = []
        # One monitor per config entry, and the integration allows a single entry
        self._monitor = next(iter(hass.data[DOMAIN].values()))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_battery_values()

    def _battery_finish(self) -> FlowResult:
        return self.async_create_entry(data={})


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None) -> RepairsFlow:
    return BatterySetupRepairFlow(hass, str((data or {}).get("device_id")))
