"""Calls the firmware's first-time setup actions through Home Assistant's own esphome services (esphome.<node>_<action>)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

CONF_DEVICE_NAME = "device_name"  # the ESPHome node name, kept in the esphome config entry's data


class ActionUnavailable(HomeAssistantError):
    """The device has no such action (older firmware), or is not an ESPHome device."""


def entry_ids(dev) -> set[str]:
    """Config entries a device belongs to (a device has a single config entry from 2026.11)."""
    entry_id = getattr(dev, "config_entry_id", None)
    return {entry_id} if entry_id else set(dev.config_entries)


def service_name(hass: HomeAssistant, dev, action: str) -> str | None:
    """The esphome service for a device's action: the node name with '-' as '_', then the action name."""
    for entry_id in entry_ids(dev):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == "esphome" and entry.data.get(CONF_DEVICE_NAME):
            return f"{entry.data[CONF_DEVICE_NAME].replace('-', '_')}_{action}"
    return None


async def async_call_action(hass: HomeAssistant, dev, action: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a firmware action and return its response. Raises ActionUnavailable when the firmware does not have it, and
    HomeAssistantError when the device refuses or does not answer."""
    name = service_name(hass, dev, action)
    if name is None or not hass.services.has_service("esphome", name):
        raise ActionUnavailable(f"The device has no {action} action.")
    response = await hass.services.async_call("esphome", name, data or {}, blocking=True, return_response=True)
    return response or {}


ADS_NAME, DS_NAME = "ads1115 address", "ds2482 address"


def satellites(hass: HomeAssistant, hub_dev) -> list[dict[str, Any]]:
    """The satellites on a board: its child devices that have the two address selects the firmware adds. Each is
    {"label", "ads_entity", "ds_entity", "ads", "ds"} with the current options, ordered by name."""
    devs, ents = dr.async_get(hass), er.async_get(hass)
    # 2026.11 keeps child devices in their own collection and links them with parent_device_id. Earlier versions keep them with
    # the other devices and link them with via_device_id.
    if hasattr(devs, "child_devices"):
        children = [c for c in devs.child_devices if c.parent_device_id == hub_dev.id]
    else:  # pragma: no cover
        children = [c for c in devs.devices.values() if c.via_device_id == hub_dev.id]
    out = []
    for child in children:
        found = {}
        for ent in er.async_entries_for_device(ents, child.id):
            name = (ent.original_name or ent.name or "").lower()
            if ent.domain == "select" and name in (ADS_NAME, DS_NAME):
                found[name] = ent.entity_id
        if len(found) == 2:
            state = lambda eid: (hass.states.get(eid).state if hass.states.get(eid) else None)  # noqa: E731
            out.append({"label": child.name_by_user or child.name or child.id,
                        "ads_entity": found[ADS_NAME], "ds_entity": found[DS_NAME],
                        "ads": state(found[ADS_NAME]), "ds": state(found[DS_NAME])})
    return sorted(out, key=lambda s: s["label"])


def power_cycle_entity(hass: HomeAssistant, hub_dev) -> str | None:
    """The hub's Power Cycle Board button, which applies a changed satellite address at once."""
    for ent in er.async_entries_for_device(er.async_get(hass), hub_dev.id):
        if ent.domain == "button" and (ent.original_name or ent.name or "").lower() == "power cycle board" and not ent.disabled:
            return ent.entity_id
    return None


def find_entity(hass: HomeAssistant, hub_dev, domain: str, name: str) -> str | None:
    """The entity id of a board's entity of one domain with one name (lower case, as the board names it), if it is enabled."""
    for ent in er.async_entries_for_device(er.async_get(hass), hub_dev.id):
        if ent.domain == domain and not ent.disabled and (ent.original_name or ent.name or "").lower() == name:
            return ent.entity_id
    return None
