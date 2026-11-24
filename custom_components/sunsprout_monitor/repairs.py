"""Fix flows for the issues with a Fix button. The setup issues open the battery setup guide for that board; the others change
one setting on the board after you confirm it."""

from __future__ import annotations

from typing import Any

try:  # Home Assistant 2026.11 replaced voluptuous with probatio
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .battery_setup import THERMISTORS
from .const import DOMAIN, ENABLE_CHARGING_NAME, FIX_FLOWS, HIZ_NAME, TS_ENABLE_NAME
from .device_actions import find_entity
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


class _BoardSettingFlow(RepairsFlow):
    """Changes one setting on a board. The subclass says which entity and what to do to it."""

    def __init__(self, hass: HomeAssistant, device_id: str) -> None:
        self.hass = hass
        self._dev_id = device_id

    def _board(self):
        return dr.async_get(self.hass).async_get(self._dev_id)

    def _label(self) -> str:
        dev = self._board()
        return (dev.name_by_user or dev.name) if dev else ""

    def _entity(self, domain: str, name: str) -> str | None:
        dev = self._board()
        return find_entity(self.hass, dev, domain, name) if dev else None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()


class EnableChargingFlow(_BoardSettingFlow):
    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entity = self._entity("switch", ENABLE_CHARGING_NAME)
        if entity is None:
            return self.async_abort(reason="entity_missing")
        if user_input is not None:
            await self.hass.services.async_call("switch", "turn_on", {"entity_id": entity}, blocking=True)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}), description_placeholders={"device": self._label()})


class HizFlow(_BoardSettingFlow):
    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entity = self._entity("switch", HIZ_NAME)
        if entity is None:
            return self.async_abort(reason="entity_missing")
        if user_input is not None:
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": entity}, blocking=True)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}), description_placeholders={"device": self._label()})


class ThermistorFlow(_BoardSettingFlow):
    """The TS Enable setting: which of the charger's and the fuel gauge's thermistors are fitted."""

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entity = self._entity("select", TS_ENABLE_NAME)
        if entity is None:
            return self.async_abort(reason="entity_missing")
        if user_input is not None:
            await self.hass.services.async_call(
                "select", "select_option", {"entity_id": entity, "option": user_input["thermistors"]}, blocking=True)
            return self.async_create_entry(data={})
        state = self.hass.states.get(entity)
        current = state.state if state and state.state in THERMISTORS else THERMISTORS[0]
        schema = vol.Schema({vol.Required("thermistors", default=current): SelectSelector(
            SelectSelectorConfig(options=list(THERMISTORS), mode=SelectSelectorMode.DROPDOWN))})
        return self.async_show_form(step_id="confirm", data_schema=schema, description_placeholders={"device": self._label()})


FLOWS = {"enable_charging": EnableChargingFlow, "hiz": HizFlow, "thermistors": ThermistorFlow}


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None) -> RepairsFlow:
    data = data or {}
    device_id = str(data.get("device_id"))
    kind = FIX_FLOWS.get(str(data.get("key")), "setup")
    flow = FLOWS.get(kind)
    return flow(hass, device_id) if flow else BatterySetupRepairFlow(hass, device_id)
