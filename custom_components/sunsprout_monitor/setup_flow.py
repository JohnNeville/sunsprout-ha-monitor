"""The "Set up battery" steps, shared by the options flow (pick any board) and the repair flow (one board)."""

from __future__ import annotations

from typing import Any

try:  # Home Assistant 2026.11 replaced voluptuous with probatio
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    NumberSelector, SelectOptionDict, NumberSelectorConfig, NumberSelectorMode, SelectSelector, SelectSelectorConfig, SelectSelectorMode)

from .device_actions import ActionUnavailable, async_call_action, power_cycle_entity, satellites
from .battery_setup import (
    ADS_ADDRESSES, CAPACITY_RANGE_MAH, CHARGE_CURRENT_RANGE_MA, CHEMISTRIES, DEFAULT_MAX_CHARGE_TEMP_C, DS_ADDRESSES, ENERGY_RANGE_MWH,
    MAX_CHARGE_TEMP_RANGE_C, TERMINATION_RANGE_MA, TERMINATION_STEP_MA, THERMISTORS, address_choices, auto_termination_ma,
    check_satellite_addresses, check_setup, default_energy_mwh, parse_found_addresses, standard_cell_voltage_mv)


def _box(low, high, step, unit):
    return NumberSelector(NumberSelectorConfig(min=low, max=high, step=step, mode=NumberSelectorMode.BOX, unit_of_measurement=unit))


def _choice(options):
    return SelectSelector(SelectSelectorConfig(options=list(options), mode=SelectSelectorMode.DROPDOWN))


class BatterySetupMixin:
    """Steps battery_values, battery_confirm and battery_done. The flow that uses it sets self._monitor and self._dev_id, and
    implements _battery_finish() to end the flow."""

    _monitor: Any
    _dev_id: str | None = None
    _values: dict[str, Any]
    _warnings: list[str]
    _satellites_only = False  # True when the flow was opened for the satellites alone, so it does not talk about the battery
    _sats: list[dict[str, Any]]
    _scan: dict[str, Any] | None = None  # the board's scan_i2c answer, kept so a form shown again does not scan again

    def _label(self) -> str:
        dev = dr.async_get(self.hass).async_get(self._dev_id) if self._dev_id else None
        return (dev.name_by_user or dev.name) if dev else ""

    def _info(self) -> dict[str, Any]:
        return self._monitor.setup_info.get(self._dev_id) or {}

    def _supports_voltage(self) -> bool:
        """Only firmware that reports the cell charge voltage takes it; older firmware has no such setting."""
        return self._info().get("cell_charge_voltage_mv") is not None

    def _supports_charge_options(self) -> bool:
        """Only firmware with setup schema 3 reports the highest charging temperature and the termination current."""
        return self._info().get("max_charge_temperature_c") is not None

    def _defaults(self) -> dict[str, Any]:
        """What the board has now, so a redo or an "outdated" setup starts from the current values."""
        info = self._info()
        energy = info.get("energy_mwh") if info.get("setup_state") in ("outdated", "modified", "complete") else 0
        chemistry = info.get("chemistry", CHEMISTRIES[0])
        # 0 is "the standard for the chemistry", so a board already on the standard shows 0, and one on a lower limit shows it
        voltage = info.get("cell_charge_voltage_mv") or 0
        if voltage == standard_cell_voltage_mv(chemistry):
            voltage = 0
        capacity = info.get("capacity_mah", 6000)
        # 0 is "automatic", so a board already on the automatic current for its chemistry and capacity shows 0
        termination = info.get("termination_current_ma") or 0
        if termination == auto_termination_ma(chemistry, capacity):
            termination = 0
        return {
            "chemistry": chemistry,
            "max_charge_temperature_c": info.get("max_charge_temperature_c", DEFAULT_MAX_CHARGE_TEMP_C),
            "termination_current_ma": termination,
            "capacity_mah": capacity,
            "energy_mwh": energy or 0,
            "cell_charge_voltage": voltage / 1000,
            "charge_current_ma": info.get("charge_current_ma", 1000),
            "thermistors": info.get("thermistors", THERMISTORS[0]),
        }

    def _values_schema(self, current: dict[str, Any]):
        return vol.Schema({
            vol.Required("chemistry", default=current["chemistry"]): _choice(CHEMISTRIES),
            vol.Required("capacity_mah", default=current["capacity_mah"]): _box(*CAPACITY_RANGE_MAH, 50, "mAh"),
            vol.Required("energy_mwh", default=current["energy_mwh"]): _box(0, ENERGY_RANGE_MWH[1], 10, "mWh"),
            **({vol.Required("cell_charge_voltage", default=current["cell_charge_voltage"]): _box(0, 4.2, 0.01, "V")}
               if self._supports_voltage() else {}),
            vol.Required("charge_current_ma", default=current["charge_current_ma"]): _box(*CHARGE_CURRENT_RANGE_MA, 50, "mA"),
            vol.Required("thermistors", default=current["thermistors"]): _choice(THERMISTORS),
            **({vol.Required("max_charge_temperature_c", default=current["max_charge_temperature_c"]):
                    _box(*MAX_CHARGE_TEMP_RANGE_C, 1, "°C"),
                vol.Required("termination_current_ma", default=current["termination_current_ma"]):
                    _box(0, TERMINATION_RANGE_MA[1], TERMINATION_STEP_MA, "mA")}
               if self._supports_charge_options() else {}),
        })

    async def async_step_battery_values(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = {
                "chemistry": user_input["chemistry"],
                "capacity_mah": int(user_input["capacity_mah"]),
                "energy_mwh": int(user_input["energy_mwh"]),
                "charge_current_ma": int(user_input["charge_current_ma"]),
                "thermistors": user_input["thermistors"],
            }
            if self._supports_voltage():
                values["cell_charge_voltage_mv"] = round(user_input["cell_charge_voltage"] * 1000)
            if self._supports_charge_options():
                values["max_charge_temperature_c"] = int(user_input["max_charge_temperature_c"])
                values["termination_current_ma"] = int(user_input["termination_current_ma"])
            result = check_setup(values, self._info().get("gauge_chemistry_id"))
            if not result.errors:
                self._values, self._warnings = values, result.warnings
                return await self.async_step_battery_confirm()
            errors = {("cell_charge_voltage" if k == "cell_charge_voltage_mv" else k): v for k, v in result.errors.items()}
        return self.async_show_form(
            step_id="battery_values", data_schema=self._values_schema(user_input or self._defaults()), errors=errors,
            description_placeholders={"device": self._label()})

    @staticmethod
    def _voltage_line(v: dict[str, Any]) -> str:
        """The summary line for the charge voltage, or nothing when the board does not have that setting."""
        if "cell_charge_voltage_mv" not in v:
            return ""
        standard = standard_cell_voltage_mv(v["chemistry"])
        mv = v["cell_charge_voltage_mv"]
        if not mv or mv == standard:
            return f"- Cell charge voltage: {standard / 1000:.2f} V (the standard for {v['chemistry']})\n"
        return f"- Cell charge voltage: {mv / 1000:.2f} V (the standard is {standard / 1000:.2f} V)\n"

    @staticmethod
    def _charge_options_lines(v: dict[str, Any]) -> str:
        """The summary lines for the highest charging temperature and the termination current, or nothing for older firmware."""
        if "max_charge_temperature_c" not in v:
            return ""
        temp = v["max_charge_temperature_c"] or DEFAULT_MAX_CHARGE_TEMP_C
        ma = v["termination_current_ma"]
        auto = auto_termination_ma(v["chemistry"], v["capacity_mah"])
        return (f"\n- Highest charging temperature: {temp} °C{' (the default)' if not v['max_charge_temperature_c'] else ''}"
                f"\n- Charge termination current: {ma or auto} mA{' (automatic)' if not ma else ''}")

    def _confirm_placeholders(self, error: str = "") -> dict[str, str]:
        v = self._values
        energy = v["energy_mwh"] or default_energy_mwh(v["chemistry"], v["capacity_mah"])
        summary = (
            f"- Cell chemistry: {v['chemistry']}\n- Capacity: {v['capacity_mah']} mAh\n- Energy: {energy} mWh"
            f"{' (worked out)' if not v['energy_mwh'] else ''}\n- Default charge current: {v['charge_current_ma']} mA\n"
            f"{self._voltage_line(v)}- Thermistors fitted: {v['thermistors']}{self._charge_options_lines(v)}")
        warnings = "".join(f"\n\n**Check:** {w}" for w in self._warnings)
        return {"device": self._label(), "summary": summary, "warnings": warnings, "error": error}

    async def async_step_battery_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="battery_confirm", data_schema=vol.Schema({}), description_placeholders=self._confirm_placeholders())
        dev = dr.async_get(self.hass).async_get(self._dev_id)
        try:
            await async_call_action(self.hass, dev, "setup_battery", self._values)
        except HomeAssistantError as err:
            return self.async_show_form(
                step_id="battery_confirm", data_schema=vol.Schema({}), errors={"base": "apply_failed"},
                description_placeholders=self._confirm_placeholders(str(err)))
        await self._monitor.async_refresh_setup_info(self._dev_id)
        return await self.async_step_satellites()

    async def async_step_battery_done(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="battery_done", data_schema=vol.Schema({}), description_placeholders={"device": self._label()})
        return self._battery_finish()

    # --- Satellites: the I2C addresses of each satellite's two chips -----------------------------------------------------------
    # The firmware keeps each choice in flash and gives it to the chips at the next boot, so a change needs a power cycle.

    def _hub(self):
        return dr.async_get(self.hass).async_get(self._dev_id)

    async def async_step_satellites(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        self._sats = satellites(self.hass, self._hub())
        if not self._sats:
            return await self._satellites_next()
        if user_input is None:
            self._scan = await self._scan_user_bus()
        errors: dict[str, str] = {}
        if user_input is not None:
            chosen = [{"ads": user_input[f"sat_{i}_ads"], "ds": user_input[f"sat_{i}_ds"]} for i in range(len(self._sats))]
            errors = check_satellite_addresses(chosen)
            if not errors:
                self._changed = False
                for sat, new in zip(self._sats, chosen):
                    for kind, entity in (("ads", sat["ads_entity"]), ("ds", sat["ds_entity"])):
                        if new[kind] != sat[kind]:
                            self._changed = True
                            await self.hass.services.async_call(
                                "select", "select_option", {"entity_id": entity, "option": new[kind]}, blocking=True)
                return await self.async_step_satellites_applied() if self._changed else await self._satellites_next()
        found = parse_found_addresses(self._scan.get("found")) if self._scan else None
        fields = {}
        for i, sat in enumerate(self._sats[:4]):  # the board's user bus has room for four, and the labels cover four
            now = (user_input or {})
            for kind, options in (("ads", ADS_ADDRESSES), ("ds", DS_ADDRESSES)):
                choices = address_choices(options, found, sat[kind])
                default = now.get(f"sat_{i}_{kind}", sat[kind])
                if default not in [value for value, _ in choices]:
                    default = choices[0][0]
                fields[vol.Required(f"sat_{i}_{kind}", default=default)] = SelectSelector(SelectSelectorConfig(
                    options=[SelectOptionDict(value=v, label=label) for v, label in choices], mode=SelectSelectorMode.DROPDOWN))
        names = "".join(f"\n- Satellite {i + 1}: {sat['label']}" for i, sat in enumerate(self._sats[:4]))
        return self.async_show_form(
            step_id="satellites", data_schema=vol.Schema(fields), errors=errors,
            description_placeholders={"device": self._label(), "satellites": names, "scan_note": self._scan_note(found)})

    async def _scan_user_bus(self) -> dict[str, Any] | None:
        """Ask the board which satellite addresses answer. None when its firmware cannot scan or does not answer."""
        try:
            return await async_call_action(self.hass, self._hub(), "scan_i2c")
        except ActionUnavailable:
            return None
        except HomeAssistantError:
            return None

    def _scan_note(self, found: set[str] | None) -> str:
        """One line about what the scan found, shown above the form."""
        if found is None:
            return "\n\nThe board's firmware cannot scan its I2C bus, so every address is listed."
        if self._scan and self._scan.get("rail_on") is False:
            return ("\n\nThe board's user 3V3 rail is off, so nothing can answer. Turn it on and open this step again; "
                    "every address is listed for now.")
        if not found & (set(ADS_ADDRESSES) | set(DS_ADDRESSES)):
            return ("\n\nNo satellite chip answered on the I2C bus. Check that the satellites are plugged in and powered; "
                    "every address is listed for now.")
        return ("\n\nAnswering on the I2C bus: " + ", ".join(sorted(found)) +
                ". Only these are offered, so a chip that is not there cannot be chosen. An answer at an address does not "
                "say which chip it is.")

    async def async_step_satellites_applied(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        options = ["power_cycle", "satellites_later"] if power_cycle_entity(self.hass, self._hub()) else ["satellites_later"]
        return self.async_show_menu(step_id="satellites_applied", menu_options=options,
                                    description_placeholders={"device": self._label()})

    async def async_step_power_cycle(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entity = power_cycle_entity(self.hass, self._hub())
        if entity:
            await self.hass.services.async_call("button", "press", {"entity_id": entity}, blocking=True)
        return await self._satellites_next()

    async def async_step_satellites_later(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self._satellites_next()

    async def _satellites_next(self) -> FlowResult:
        return await (self.async_step_satellites_done() if self._satellites_only else self.async_step_battery_done())

    async def async_step_satellites_done(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="satellites_done", data_schema=vol.Schema({}), description_placeholders={"device": self._label()})
        return self._battery_finish()
