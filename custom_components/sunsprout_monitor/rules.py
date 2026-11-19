"""Pure checks on a SunSprout board. No Home Assistant imports, so they unit test cleanly."""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    CHARGE_TEMPERATURE_C,
    CHARGER_FAULT_MINUTES,
    CHARGING_OFF_HOURS,
    LEGACY_LIION_IDS,
    LIFEPO4_OTHER_HIGH_BYTES,
    LIFEPO4_RELAX_HIGH_BYTE,
    LIION_HIGH_BYTES,
    NOT_LIFEPO4_IDS,
    DARK_PANEL_LUX,
    DISCHARGING_WITH_PANEL_MINUTES,
    END_OF_CHARGE_MINUTES,
    HARD_MAX_TEMPERATURE_C,
    HEALTH_LOW_PERCENT,
    HIZ_STUCK_MINUTES,
    LEARNING_MIN_CYCLES,
    PANEL_LIVE_VOLTS,
    REGISTER_CORRECTIONS_LIMIT,
    SELF_FLIPPING_REGISTERS,
    TEMPERATURE_DISAGREE_C,
    TS_PLAUSIBLE_C,
    TS_UNPOPULATED_MINUTES,
    UNEXPECTED_CORRECTIONS_LIMIT,
    VOLTAGE_DISAGREE_V,
    WINDOW_OPTION_KEYS,
)


@dataclass(frozen=True)
class Problem:
    key: str
    detail: str
    after_min: int = 0  # the condition has to hold this long before the issue is raised


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hold_problems(since: dict, dev_id: str, found: list[Problem], now) -> list[Problem]:
    """Keep the problems whose condition has lasted at least their after_min, and forget the ones that cleared.

    since maps "<device id>_<problem key>" to when the condition first showed, and is updated in place."""
    active = {f"{dev_id}_{p.key}" for p in found}
    for k in [k for k in since if k.startswith(f"{dev_id}_") and k not in active]:
        del since[k]
    held = []
    for p in found:
        first = since.setdefault(f"{dev_id}_{p.key}", now)
        if (now - first).total_seconds() / 60 >= p.after_min:
            held.append(p)
    return held


def windows_from_options(options) -> dict[str, tuple[float, float]]:
    """Charge temperature window per cell family from the entry's options, with the defaults for any that are missing."""
    out = {}
    for family, (low_key, high_key) in WINDOW_OPTION_KEYS.items():
        low, high = CHARGE_TEMPERATURE_C[family]
        out[family] = (float(options.get(low_key, low)), float(options.get(high_key, high)))
    return out


def _celsius(states, units, name):
    """Temperature entity -> C, whatever unit Home Assistant shows it in."""
    v = _num(states.get(name))
    if v is None:
        return None
    return (v - 32) * 5 / 9 if "F" in (units.get(name) or "") else v


def classify_chem_id(cid) -> str:
    """What a gauge chemistry ID is: 'lifepo4_relax' (0x04xx, the only range that switches the G1 FW 0x0016 LiFePO4 relax mode
    on), 'lifepo4_other' (TI's 0x41xx and 0x42xx LiFePO4 tables), 'liion', or 'other' (primary, titanate, lead acid, NiMH, mixed
    or unknown IDs)."""
    n = int(cid)
    high = n >> 8
    if n in NOT_LIFEPO4_IDS:
        return "other"
    if high == LIFEPO4_RELAX_HIGH_BYTE:
        return "lifepo4_relax"
    if high in LIFEPO4_OTHER_HIGH_BYTES:
        return "lifepo4_other"
    if high in LIION_HIGH_BYTES or n in LEGACY_LIION_IDS:
        return "liion"
    return "other"


def _family(states) -> str | None:
    """'li-ion' or 'lifepo4' from Cell Chemistry, else from the gauge's chemistry ID."""
    chem = states.get("cell chemistry", "").lower().replace(" ", "").replace("-", "")
    if chem in ("liion", "lifepo4"):
        return "li-ion" if chem == "liion" else "lifepo4"
    cid = _num(states.get("gauge chemistry id"))
    if cid is not None:
        kind = classify_chem_id(cid)
        if kind.startswith("lifepo4"):
            return "lifepo4"
        if kind == "liion":
            return "li-ion"
    return None


def _ts_inputs(states) -> tuple[bool | None, bool | None]:
    """(charger TS enabled, gauge TS enabled) from the TS Enable select; None when it is not known."""
    ts = states.get("ts enable", "").lower().replace(" ", "")
    table = {"both": (True, True), "chargeronly": (True, False), "gaugeonly": (False, True), "none": (False, False)}
    return table.get(ts, (None, None))


def check(
    states: dict[str, str],
    ages_min: dict[str, float] | None = None,
    units: dict[str, str | None] | None = None,
    windows: dict[str, tuple[float, float]] | None = None,
) -> list[Problem]:
    """states: lower-cased entity name -> state string. ages_min: minutes since last change. units: unit shown for each."""
    ages = ages_min or {}
    units = units or {}
    windows = windows or CHARGE_TEMPERATURE_C
    states = {k: v for k, v in states.items() if v not in ("unavailable", "unknown")}
    out: list[Problem] = []

    chem = states.get("cell chemistry", "").lower().replace(" ", "").replace("-", "")
    cid = _num(states.get("gauge chemistry id"))
    if chem in ("liion", "lifepo4") and cid is not None:
        kind = classify_chem_id(cid)
        label, hexid = states["cell chemistry"], f"0x{int(cid):04X}"
        if chem == "lifepo4" and kind == "lifepo4_other":
            out.append(Problem("chem_no_relax",
                f"Cell Chemistry is {label} and the gauge runs chemistry ID {hexid}, a LiFePO4 table whose ID does not turn on the gauge's LiFePO4 relax mode (firmware 0x0016 needs an ID of 0x04xx), so it will learn the pack very slowly."))
        elif chem == "lifepo4" and kind != "lifepo4_relax" or chem == "liion" and kind != "liion":
            expected = "0x04xx" if chem == "lifepo4" else "a lithium-ion ID"
            what = {"liion": "a lithium-ion table", "other": "not a lithium-ion or LiFePO4 table"}.get(kind, "a LiFePO4 table")
            out.append(Problem("chem_mismatch" if kind != "other" else "chem_unsupported",
                f"Cell Chemistry is {label} but the gauge runs chemistry ID {hexid}, {what} (expected {expected}). State of charge will be wrong; load a matching chemistry table."))

    # Which TS inputs are in use: TS Enable = Both / Charger Only / Gauge Only / None. A disabled input's reading is
    # meaningless, so it is left out of every temperature check below. An enabled one that reads far outside any real
    # pack temperature (e.g. -43 C) has no thermistor behind it: the charger then sees "cold" and refuses to charge.
    charger_ts, gauge_ts = _ts_inputs(states)
    charger_c = _celsius(states, units, "battery temperature") if charger_ts is not False else None
    gauge_c = _celsius(states, units, "battery temperature (gauge)") if gauge_ts is not False else None
    lo, hi = TS_PLAUSIBLE_C
    dead = []
    if charger_ts and charger_c is not None and not lo <= charger_c <= hi:
        dead.append(("charger", charger_c))
        charger_c = None
    if gauge_ts and gauge_c is not None and not lo <= gauge_c <= hi:
        dead.append(("gauge", gauge_c))
        gauge_c = None
    if dead:
        reads = " and ".join(f"the {who} reads {c:.1f} C" for who, c in dead)
        out.append(Problem("ts_unpopulated",
            f"TS Enable uses the {' and '.join(w for w, _ in dead)} thermistor input but {reads}, which is not a real pack "
            "temperature. The TS sensor looks missing or not connected; charging is blocked until it is fitted or TS Enable is set to None.",
            TS_UNPOPULATED_MINUTES))

    # TS Status comes from the driver's ts_status entity. "Ignored" and "Normal" are fine; a cold reading with the
    # charger's TS input enabled usually means the thermistor is missing (skipped when the reading above already says so).
    ts_status = states.get("ts status", "").lower()
    if charger_ts is not False and ts_status == "cold" and not any(w == "charger" for w, _ in dead) \
            and states.get("ts enable"):
        out.append(Problem("ts_no_probe",
            "TS Enable expects a thermistor but the charger reads Cold. Fit the probe or set TS Enable to None."))

    # Gauge setup problem flag from the bq34z100 driver (config_problem / config_status).
    if states.get("gauge setup problem") == "on":
        out.append(Problem("gauge_setup", states.get("gauge setup status", "Gauge setup differs from the YAML")))

    if states.get("poor source detected") == "on":
        out.append(Problem("poor_source",
            "The charger's poor-source test keeps failing; the panel may be too weak for it to start."))

    if (states.get("charger hiz mode") == "on" and states.get("solar input present") == "on"
            and ages.get("charger hiz mode", 0) >= HIZ_STUCK_MINUTES):
        out.append(Problem("hiz_stuck",
            f"Charger has been in HIZ for {int(ages['charger hiz mode'])} min with a panel connected."))

    # The charger flips some registers by itself (EN_MPPT and EN_HIZ at dawn and dusk). Newer firmware counts the others
    # separately; with an older one, count everything and ignore it when the latest change was one of those two.
    unexpected = _num(states.get("unexpected register corrections"))
    rc = _num(states.get("register corrections"))
    last = states.get("last register correction", "")
    register = last.split(" ", 1)[0] if last else ""
    if unexpected is not None:
        if unexpected >= UNEXPECTED_CORRECTIONS_LIMIT:
            out.append(Problem("register_corrections",
                f"Charger registers changed unexpectedly {int(unexpected)} times since boot"
                + (f"; the latest was {last}" if last else "") + "."))
    elif rc is not None and rc >= REGISTER_CORRECTIONS_LIMIT and register not in SELF_FLIPPING_REGISTERS:
        out.append(Problem("register_corrections",
            f"The firmware has seen charger registers change {int(rc)} times since boot"
            + (f"; the latest was {last}" if last else "") + "."))

    panel_volts = _num(states.get("input voltage"))
    battery_ma = _num(states.get("battery current"))
    if (panel_volts is not None and panel_volts >= PANEL_LIVE_VOLTS and battery_ma is not None and battery_ma < -20
            and states.get("enable charging") == "on" and states.get("charger hiz mode") != "on"):
        out.append(Problem("discharging_with_panel",
            f"The panel is at {panel_volts:.1f} V but the pack is discharging at {-battery_ma:.0f} mA with charging enabled.",
            DISCHARGING_WITH_PANEL_MINUTES))

    fault = states.get("charger fault", "OK")
    if fault.lower() not in ("ok", "none", ""):
        out.append(Problem("charger_fault", f"The charger reports: {fault}.", CHARGER_FAULT_MINUTES))

    if states.get("watchdog expired") == "on":
        out.append(Problem("watchdog_expired",
            "The charger's watchdog expired, which resets its settings (including the temperature limits).", 5))

    if states.get("enable charging") == "off" and ages.get("enable charging", 0) >= CHARGING_OFF_HOURS * 60:
        out.append(Problem("charging_off",
            f"Charging has been switched off for {int(ages['enable charging'] // 60)} h."))

    update_status = _num(states.get("gauge update status"))
    cycles = _num(states.get("battery cycle count"))
    if update_status == 4 and cycles is not None and cycles >= LEARNING_MIN_CYCLES:
        out.append(Problem("gauge_not_learned",
            f"The gauge has counted {int(cycles)} cycles but is still at Update Status 4 (Impedance Track on, not yet "
            "learned). Run a full discharge, rest and recharge."))

    health = _num(states.get("battery health"))
    if health is not None and health < HEALTH_LOW_PERCENT:
        fcc, qmax = states.get("battery full charge capacity"), states.get("gauge qmax")
        extra = (f" (full charge capacity {fcc} mAh" + (f", Qmax {qmax} mAh" if qmax else "") + ")") if fcc else ""
        out.append(Problem("capacity_low",
            f"Battery health reads {int(health)} %{extra}. Check the pack parameters and learning status.", 30))

    level = _num(states.get("battery level"))
    if (states.get("charge status", "").lower() == "charge terminated" and states.get("battery fully charged") == "off"
            and level is not None and level < 95):
        out.append(Problem("no_end_of_charge",
            f"The charger has terminated but the gauge reads {int(level)} % and has not flagged the pack as full.",
            END_OF_CHARGE_MINUTES))

    if charger_c is not None and gauge_c is not None and abs(charger_c - gauge_c) > TEMPERATURE_DISAGREE_C:
        out.append(Problem("temp_disagree",
            f"The charger reads {charger_c:.1f} C and the gauge {gauge_c:.1f} C; one thermistor is wrong or misplaced.", 30))

    family = _family(states)
    pack_c = charger_c if charger_c is not None else gauge_c
    if family in windows and pack_c is not None:
        low, high = windows[family]
        charging = states.get("charging") == "on"
        if pack_c > HARD_MAX_TEMPERATURE_C or (charging and not low <= pack_c <= high):
            out.append(Problem("temp_range",
                f"The pack is at {pack_c:.1f} C; the {family} charge window is {low:.0f} to {high:.0f} C"
                + (" and it is charging." if charging else f" and above {HARD_MAX_TEMPERATURE_C:.0f} C is too hot at any time."), 10))

    battery_v, gauge_v = _num(states.get("battery voltage")), _num(states.get("battery voltage (gauge)"))
    if battery_v is not None and gauge_v is not None and abs(battery_v - gauge_v) > VOLTAGE_DISAGREE_V:
        out.append(Problem("voltage_mismatch",
            f"The charger reads {battery_v:.3f} V and the gauge {gauge_v:.3f} V at the pack.", 30))

    lux = _num(states.get("roof light sensor"))
    if lux is not None and lux >= DARK_PANEL_LUX and states.get("solar input present") == "off":
        out.append(Problem("panel_dark",
            f"The light sensor reads {int(lux)} lx but the charger sees no solar input; check the panel and its cable.", 30))
    return out
