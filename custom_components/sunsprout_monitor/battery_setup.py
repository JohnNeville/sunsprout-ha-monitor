"""First-time battery setup: the values to ask for and the checks on them. No Home Assistant imports, so they unit test cleanly."""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import classify_chem_id

CHEMISTRIES = ("LiFePO4", "Li-ion")
THERMISTORS = ("Both", "Charger Only", "Gauge Only", "None")
NOMINAL_CELL_VOLTS = {"LiFePO4": 3.2, "Li-ion": 3.7}

# The charge voltage limit per cell is what protects the cell. The chemistry sets the standard one, and a cell whose data sheet gives
# a lower limit can use it, down to this far under the standard. It can never be higher: the firmware and the charger driver
# refuse that too, so a mistake here cannot overcharge a cell.
STANDARD_CELL_VOLTAGE_MV = {"LiFePO4": 3650, "Li-ion": 4200}
CELL_VOLTAGE_MAX_DROP_MV = 300

CAPACITY_RANGE_MAH = (100, 20000)
ENERGY_RANGE_MWH = (100, 32767)
CHARGE_CURRENT_RANGE_MA = (100, 2000)

# Charge current above this fraction of the capacity is unusual enough to ask the user to check the cell's data sheet.
UNUSUAL_C_RATE = {"LiFePO4": 0.5, "Li-ion": 1.0}
# A stored energy this far from capacity x nominal voltage is probably a mistake (the datasheet value can differ somewhat).
ENERGY_TOLERANCE = 0.2

# A satellite's chips take their I2C address from jumpers: the ADS1115 (soil moisture) from its ADDR pin, the DS2482 (soil
# temperature 1-Wire bridge) from AD0 and AD1. These are the options of the two selects the firmware puts on each satellite.
ADS_ADDRESSES = ("0x48", "0x49", "0x4A", "0x4B")
DS_ADDRESSES = ("0x18", "0x19", "0x1A", "0x1B")


def standard_cell_voltage_mv(chemistry: str) -> int:
    """The per-cell charge voltage limit the chemistry sets, in mV."""
    return STANDARD_CELL_VOLTAGE_MV.get(chemistry, STANDARD_CELL_VOLTAGE_MV["Li-ion"])


def default_energy_mwh(chemistry: str, capacity_mah: float) -> int:
    """Capacity x nominal cell voltage, capped at the 16-bit field the gauge stores it in."""
    return int(min(ENERGY_RANGE_MWH[1], round(capacity_mah * NOMINAL_CELL_VOLTS.get(chemistry, 3.7))))


@dataclass
class SetupCheck:
    errors: dict[str, str] = field(default_factory=dict)  # field name -> translation key; setup cannot go on
    warnings: list[str] = field(default_factory=list)  # shown on the confirm step; setup can still go on


def _range_error(value, low_high) -> bool:
    return value is None or not (low_high[0] <= value <= low_high[1])


def check_setup(values: dict, gauge_chem_id: int | None = None) -> SetupCheck:
    """Check the values the user entered. energy_mwh 0 means "work it out from the capacity".

    gauge_chem_id is what the gauge runs now, if known. A chemistry that does not fit the entered cell chemistry is only a
    warning: loading the table is the owner's own step, and may come after this setup."""
    out = SetupCheck()
    chemistry = values.get("chemistry")
    capacity = values.get("capacity_mah")
    energy = values.get("energy_mwh") or 0
    current = values.get("charge_current_ma")
    thermistors = values.get("thermistors")
    voltage = values.get("cell_charge_voltage_mv") or 0  # 0 is the chemistry's standard

    if chemistry not in CHEMISTRIES:
        out.errors["chemistry"] = "chemistry_invalid"
    if _range_error(capacity, CAPACITY_RANGE_MAH):
        out.errors["capacity_mah"] = "capacity_invalid"
    if energy != 0 and _range_error(energy, ENERGY_RANGE_MWH):
        out.errors["energy_mwh"] = "energy_invalid"
    if _range_error(current, CHARGE_CURRENT_RANGE_MA):
        out.errors["charge_current_ma"] = "current_invalid"
    if thermistors not in THERMISTORS:
        out.errors["thermistors"] = "thermistors_invalid"
    if chemistry in CHEMISTRIES and voltage != 0:
        standard = standard_cell_voltage_mv(chemistry)
        if not standard - CELL_VOLTAGE_MAX_DROP_MV <= voltage <= standard:
            out.errors["cell_charge_voltage_mv"] = "voltage_invalid"
    if out.errors:
        return out

    limit = UNUSUAL_C_RATE[chemistry]
    if current > capacity * limit:
        out.warnings.append(
            f"A charge current of {current} mA is above {limit:g}C for a {capacity} mAh {chemistry} cell. "
            "Check the cell's data sheet for its maximum charge current.")
    if energy:
        expected = default_energy_mwh(chemistry, capacity)
        if abs(energy - expected) > ENERGY_TOLERANCE * expected:
            out.warnings.append(
                f"The energy of {energy} mWh is far from {expected} mWh ({capacity} mAh x {NOMINAL_CELL_VOLTS[chemistry]} V). "
                "Use 0 to have it worked out.")
    if voltage and voltage != standard_cell_voltage_mv(chemistry):
        out.warnings.append(
            f"The cell will be charged to {voltage / 1000:.2f} V instead of the standard "
            f"{standard_cell_voltage_mv(chemistry) / 1000:.2f} V for {chemistry}. That is safe for the cell but stores a little less energy; "
            "use the limit from the cell's data sheet.")
    if thermistors == "None":
        out.warnings.append("With no thermistor fitted the charger cannot stop charging when the pack is too hot or too cold.")
    elif thermistors == "Gauge Only":
        out.warnings.append("The charger ignores its own thermistor, so its temperature protection is off.")

    if gauge_chem_id is not None:
        kind = classify_chem_id(gauge_chem_id)
        hexid = f"0x{int(gauge_chem_id):04X}"
        if chemistry == "LiFePO4":
            if kind == "lifepo4_other":
                out.warnings.append(
                    f"The gauge runs chemistry ID {hexid}, a LiFePO4 table that does not turn on its LiFePO4 relax mode "
                    "(firmware 0x0016 needs an ID of 0x04xx), so it will learn the pack very slowly.")
            elif kind != "lifepo4_relax":
                out.warnings.append(
                    f"The gauge runs chemistry ID {hexid}, which is not a LiFePO4 table. Load a LiFePO4 table (ID 0x04xx) "
                    "before relying on the state of charge.")
        elif kind != "liion":
            out.warnings.append(
                f"The gauge runs chemistry ID {hexid}, which is not a lithium-ion table. Load a matching table before "
                "relying on the state of charge.")
    return out


def check_satellite_addresses(satellites: list[dict]) -> dict[str, str]:
    """Field errors for the addresses chosen for each satellite, keyed "sat_<index>_ads" and "sat_<index>_ds".

    Two satellites on the same bus cannot use the same ADS1115 address, or the same DS2482 address. The first satellite to use an
    address keeps it; the ones after it are flagged. The options are fixed by the firmware, so anything else is invalid."""
    errors: dict[str, str] = {}
    for kind, options in (("ads", ADS_ADDRESSES), ("ds", DS_ADDRESSES)):
        seen: set[str] = set()
        for i, sat in enumerate(satellites):
            address = sat.get(kind)
            if address not in options:
                errors[f"sat_{i}_{kind}"] = "address_invalid"
            elif address in seen:
                errors[f"sat_{i}_{kind}"] = "address_duplicate"
            else:
                seen.add(address)
    return errors


def parse_found_addresses(text) -> set[str] | None:
    """The scan answer's "found" text, such as "0x18,0x48", as a set of the addresses in the form the selects use ("0x4A").
    None when there is no answer at all (older firmware, or the scan failed): the caller then offers every address."""
    if text is None:
        return None
    out = set()
    for part in str(text).split(","):
        part = part.strip()
        if part:
            try:
                out.add(f"0x{int(part, 16):02X}")
            except ValueError:
                continue
    return out


def address_choices(options: tuple[str, ...], found: set[str] | None, current: str | None) -> list[tuple[str, str]]:
    """(value, label) for one address select. Only the addresses that answered on the bus are offered, because a chip that is
    not there cannot be configured. The address the satellite is set to now is always kept, marked when nothing answered
    there, so the form can show the present setting. With no scan answer, or nothing at all answering in this select's range,
    every option is offered unmarked, since hiding all of them would leave nothing to choose."""
    if found is None or not (found & set(options)):
        return [(o, o) for o in options]
    out = []
    for o in options:
        if o in found:
            out.append((o, o))
        elif o == current:
            out.append((o, f"{o} (not detected)"))
    return out
