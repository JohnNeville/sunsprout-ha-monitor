"""Config flow: asks for the charge temperature window of each cell family."""

from __future__ import annotations

from typing import Any

try:  # Home Assistant 2026.11 replaced voluptuous with probatio
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector, NumberSelectorConfig, NumberSelectorMode, SelectOptionDict, SelectSelector, SelectSelectorConfig,
    SelectSelectorMode)

from .const import CHARGE_TEMPERATURE_C, DOMAIN, WINDOW_OPTION_KEYS
from .setup_flow import BatterySetupMixin


def _schema(current: dict[str, Any]) -> vol.Schema:
    """One box per limit, filled in with the current value or the family's default."""
    box = NumberSelector(NumberSelectorConfig(
        min=-40, max=80, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="\u00b0C"))
    fields = {}
    for family, (low_key, high_key) in WINDOW_OPTION_KEYS.items():
        low, high = CHARGE_TEMPERATURE_C[family]
        fields[vol.Required(low_key, default=current.get(low_key, low))] = box
        fields[vol.Required(high_key, default=current.get(high_key, high))] = box
    return vol.Schema(fields)


def _errors(user_input: dict[str, Any]) -> dict[str, str]:
    for low_key, high_key in WINDOW_OPTION_KEYS.values():
        if user_input[low_key] >= user_input[high_key]:
            return {"base": "window_invalid"}
    return {}


class SunSproutMonitorFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return SunSproutMonitorOptions()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _errors(user_input)
            if not errors:
                return self.async_create_entry(title="SunSprout Monitor", data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=errors)


class SunSproutMonitorOptions(BatterySetupMixin, OptionsFlow):
    """Set up a board's battery, or change the temperature windows."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._warnings: list[str] = []
        self._boards: dict[str, str] = {}

    @property
    def _monitor(self):
        return self.hass.data[DOMAIN][self.config_entry.entry_id]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["battery_pick", "satellite_pick", "windows"])

    async def async_step_battery_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._satellites_only = False
        return await self._pick_board("battery_pick", self.async_step_battery_values, user_input)

    async def async_step_satellite_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._satellites_only = True
        return await self._pick_board("satellite_pick", self.async_step_satellites, user_input)

    async def _pick_board(self, step_id: str, next_step, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        boards = dict(self._monitor.board_devices())
        if not boards:
            return self.async_abort(reason="no_boards")
        if user_input is not None:
            self._dev_id = user_input["board"]
            return await next_step()
        if len(boards) == 1:
            self._dev_id = next(iter(boards))
            return await next_step()
        # The labels are device names, so the dropdown shows ids mapped to them
        schema = vol.Schema({vol.Required("board"): SelectSelector(SelectSelectorConfig(
            options=[SelectOptionDict(value=i, label=n) for i, n in boards.items()], mode=SelectSelectorMode.DROPDOWN))})
        return self.async_show_form(step_id=step_id, data_schema=schema)

    def _battery_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_windows(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _errors(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="windows", data_schema=_schema(user_input or dict(self.config_entry.options)), errors=errors)
