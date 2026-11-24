"""SunSprout Monitor: Repairs issues and a linked monitor device for each SunSprout ESPHome board."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .monitor import Monitor

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    mon = Monitor(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = mon
    entry.async_on_unload(async_track_time_interval(hass, mon.evaluate, timedelta(minutes=1)))
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    mon.evaluate()
    return True


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Pick up changed temperature windows."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
