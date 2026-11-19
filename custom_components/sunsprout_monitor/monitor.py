"""Finds SunSprout boards among ESPHome devices and keeps Repairs issues in step."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN, FIXABLE_KEYS, KEY_ENTITIES, SETUP_INFO_MAX_AGE_HOURS, UNAVAILABLE_MINUTES
from .device_actions import ActionUnavailable, async_call_action, entry_ids
from .rules import Problem, check, hold_problems, windows_from_options

_LOGGER = logging.getLogger(__name__)


class Monitor:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._raised: set[str] = set()
        self.problems: dict[str, list[Problem]] = {}  # device name -> problems
        self._since: dict[str, datetime] = {}  # "<device id>_<problem key>" -> when the condition first showed
        # What each board last said to get_setup_info (setup state, gauge chemistry ID, cell settings). A board whose firmware
        # has no such action is stored as {"setup_state": "unsupported"}.
        self.setup_info: dict[str, dict] = {}
        self._info_at: dict[str, datetime] = {}  # device id -> when the board was last asked
        self._signature: dict[str, tuple] = {}  # device id -> (reachable, Cell Chemistry) when last evaluated
        self._asking: set[str] = set()

    def _boards(self):
        """Yield (device, {lower name: State}) for ESPHome devices that look like SunSprout."""
        devs, ents = dr.async_get(self.hass), er.async_get(self.hass)
        esphome_entries = {e.entry_id for e in self.hass.config_entries.async_entries("esphome")}
        for dev in devs.devices:
            if not esphome_entries & entry_ids(dev):
                continue
            by_name = {}
            for ent in er.async_entries_for_device(ents, dev.id):
                name = (ent.original_name or ent.name or "").lower()
                st = self.hass.states.get(ent.entity_id)
                if name and st is not None:
                    by_name[name] = st
            if all(k.lower() in by_name for k in KEY_ENTITIES):
                yield dev, by_name

    def board_devices(self) -> list[tuple[str, str]]:
        """(device id, label) of each SunSprout board found, for the setup flow's pick list."""
        return [(dev.id, dev.name_by_user or dev.name or dev.id) for dev, _ in self._boards()]

    async def async_refresh_setup_info(self, dev_id: str) -> None:
        """Ask a board for its setup state and gauge chemistry ID, then re-evaluate. Read only on the board."""
        if dev_id in self._asking:
            return
        dev = dr.async_get(self.hass).async_get(dev_id)
        if dev is None:
            return
        self._asking.add(dev_id)
        self._info_at[dev_id] = dt_util.utcnow()
        try:
            self.setup_info[dev_id] = await async_call_action(self.hass, dev, "get_setup_info")
        except ActionUnavailable:
            # Not there yet is common right after a start or a reconnect, before the board's actions are registered, so it is
            # asked again on the next pass (a local lookup, no traffic) and not left for a day.
            self.setup_info.setdefault(dev_id, {"setup_state": "unsupported"})
            self._info_at.pop(dev_id, None)
        except HomeAssistantError as err:  # the board did not answer; try again in a few minutes
            _LOGGER.debug("get_setup_info failed for %s: %s", dev_id, err)
            self._info_at[dev_id] = dt_util.utcnow() - timedelta(hours=SETUP_INFO_MAX_AGE_HOURS) + timedelta(minutes=5)
        finally:
            self._asking.discard(dev_id)
        self.evaluate()

    def _ask_when_due(self, dev, by_name: dict, now: datetime) -> None:
        """Ask for the setup info at start, when the board reconnects, when Cell Chemistry changes, and once a day."""
        states = {n: s.state for n, s in by_name.items()}
        reachable = states.get("charger fault") not in (STATE_UNAVAILABLE, STATE_UNKNOWN, None)
        signature = (reachable, states.get("cell chemistry"))
        changed = self._signature.get(dev.id) != signature
        self._signature[dev.id] = signature
        if not reachable:
            return
        last = self._info_at.get(dev.id)
        # A reconnect between two evaluations leaves no trace in the signature, but it does move Charger Fault's last change
        # (its state goes unavailable and back), so a change since the last ask counts too.
        if last is not None and by_name["charger fault"].last_changed > last:
            changed = True
        if last is None or changed or now - last > timedelta(hours=SETUP_INFO_MAX_AGE_HOURS):
            self.hass.async_create_task(self.async_refresh_setup_info(dev.id))

    @callback
    def evaluate(self, _now=None) -> None:
        now = dt_util.utcnow()
        wanted: set[str] = set()
        self.problems = {}
        windows = windows_from_options(self.entry.options)
        seen = 0
        for dev, by_name in self._boards():
            seen += 1
            label = dev.name_by_user or dev.name or dev.id
            states = {n: s.state for n, s in by_name.items()}
            self._ask_when_due(dev, by_name, now)
            info = self.setup_info.get(dev.id) or {}
            # Gauge Chemistry ID is disabled by default, so its value comes from the board's own answer unless it is enabled
            if "gauge chemistry id" not in states and info.get("gauge_chemistry_id") is not None:
                states["gauge chemistry id"] = str(info["gauge_chemistry_id"])
            ages = {n: (now - s.last_changed).total_seconds() / 60 for n, s in by_name.items()}
            units = {n: s.attributes.get("unit_of_measurement") for n, s in by_name.items()}
            found = hold_problems(self._since, dev.id, check(states, ages, units, windows), now)
            # The board keeps its own record of the first-time setup, so reinstalling this integration does not ask again.
            # "modified" (values edited by hand after the setup) is not a problem.
            if info.get("setup_state") == "unset":
                found.append(Problem("setup_unset", "the battery has not been set up yet"))
            elif info.get("setup_state") == "outdated":
                found.append(Problem("setup_outdated", "this firmware added setup options that have not been set"))
            gone = [s for s in by_name.values() if s.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)]
            if len(gone) == len(by_name) and all(
                    (now - s.last_changed) > timedelta(minutes=UNAVAILABLE_MINUTES) for s in gone):
                found = [Problem("unavailable", f"no data for over {UNAVAILABLE_MINUTES} min")]
            self.problems[label] = found
            for p in found:
                iid = f"{dev.id}_{p.key}"
                wanted.add(iid)
                fixable = p.key in FIXABLE_KEYS
                ir.async_create_issue(
                    self.hass, DOMAIN, iid, is_fixable=fixable, severity=ir.IssueSeverity.WARNING,
                    data={"device_id": dev.id} if fixable else None,
                    translation_key=p.key,
                    translation_placeholders={"device": label, "detail": p.detail})
        stale = self._raised - wanted
        if seen:
            # Issues left in the registry by an earlier run (restart, renamed or removed check) are not in _raised.
            # Skipped while no board is visible so a slow start does not wipe dismissed ("ignored") issues.
            stale |= {iid for (dom, iid) in ir.async_get(self.hass).issues if dom == DOMAIN} - wanted
        for iid in stale:
            ir.async_delete_issue(self.hass, DOMAIN, iid)
        self._raised = wanted
