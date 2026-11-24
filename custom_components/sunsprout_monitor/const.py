"""Constants for SunSprout Monitor."""

DOMAIN = "sunsprout_monitor"

# Entity names (as the ESPHome device registers them, without the device prefix)
# that identify a SunSprout board.
KEY_ENTITIES = ("Charger Fault", "Battery Level")  # both are enabled by default; Gauge Chemistry ID is not

# Gauge Chemistry ID. The 16-bit value is TI's four-digit chemistry ID read as hex digits: LiFePO4 "0423" is 0x0423 (1059).
# Families are taken from the ID's high byte, from the chemistry list in TI's bqStudio. The tables themselves are not copied.
# LiFePO4 relax mode: the G1 gauge firmware 0x0016 only enables it when LFPRelax is set AND the ID's high byte is exactly 0x04
# (measured on SunSprout hardware; TI does not document this). A LiFePO4 pack can therefore run one of TI's 0x42xx tables
# (for example 0x4221) with its ID word changed to 0x04xx (for example 0x0423).
LIFEPO4_RELAX_HIGH_BYTE = 0x04
# TI's other LiFePO4 families (0x4221 is "LiFePO4/carbon, 3.6V"). They run, but without relax mode on FW 0x0016.
LIFEPO4_OTHER_HIGH_BYTES = frozenset({0x41, 0x42})
# IDs inside 0x04xx that are not LiFePO4: 0x0470 is "High Voltage Phosphate/carbon" (Vqdis about 1.1 V).
NOT_LIFEPO4_IDS = frozenset({0x0470})
# Li-ion families. 0x05 is left out: it mixes primary Li/MnO2 with Li-ion variants. 0x06 to 0x08 and 0x61 are primary cells,
# titanate, lead acid and NiMH.
LIION_HIGH_BYTES = frozenset(
    {0x01, 0x02, 0x03, 0x09}
    | set(range(0x11, 0x1A)) | set(range(0x20, 0x2A)) | set(range(0x31, 0x3A))
    | set(range(0x51, 0x5A)) | set(range(0x70, 0x7A)) | set(range(0x81, 0x86))
)
# Kept from the earlier table: 2044 as a decimal reading was treated as the Samsung 25R. TI's own "2044" is 0x2044 (8260,
# "NiCoMn/carbon"), which the high byte above already covers, so this may be a hex/decimal slip. Left so nothing changes.
LEGACY_LIION_IDS = frozenset({2044})

# How often the board is asked for its setup state and gauge chemistry ID (also asked when it reconnects or Cell Chemistry changes)
SETUP_INFO_MAX_AGE_HOURS = 24

# Issues with a Fix button, and the flow each one opens. "setup" is the battery setup guide (the cause is a cell setting); the
# others change one setting on the board after you confirm it.
FIX_FLOWS = {
    "setup_unset": "setup",
    "setup_outdated": "setup",
    "gauge_setup": "setup",
    "no_end_of_charge": "setup",
    "chem_mismatch": "setup",
    "charging_off": "enable_charging",
    "ts_unpopulated": "thermistors",
    "ts_no_probe": "thermistors",
    "hiz_stuck": "hiz",
}
FIXABLE_KEYS = tuple(FIX_FLOWS)

# The board entities the fix flows change, by their name on the board (lower case).
ENABLE_CHARGING_NAME = "enable charging"
HIZ_NAME = "charger hiz mode"
TS_ENABLE_NAME = "ts enable"

HIZ_STUCK_MINUTES = 10
REGISTER_CORRECTIONS_LIMIT = 10
UNEXPECTED_CORRECTIONS_LIMIT = 3
UNAVAILABLE_MINUTES = 60

# Typical charge window per cell family, in C: (lowest, highest). Cells differ, so these are defaults; a chemistry
# that is not listed is not checked. Above HARD_MAX_TEMPERATURE_C the pack is flagged whether or not it is charging.
CHARGE_TEMPERATURE_C = {"li-ion": (0.0, 45.0), "lifepo4": (0.0, 50.0)}
HARD_MAX_TEMPERATURE_C = 60.0

# Setup asks for the window per family; the answers are stored in the entry's options under these keys.
WINDOW_OPTION_KEYS = {"li-ion": ("li_ion_low_c", "li_ion_high_c"), "lifepo4": ("lifepo4_low_c", "lifepo4_high_c")}

# Registers that flip themselves overnight and at dawn, so seeing them corrected is expected.
SELF_FLIPPING_REGISTERS = ("EN_MPPT", "EN_HIZ")

DISCHARGING_WITH_PANEL_MINUTES = 60
CHARGER_FAULT_MINUTES = 10
CHARGING_OFF_HOURS = 24
LEARNING_MIN_CYCLES = 5
HEALTH_LOW_PERCENT = 80
END_OF_CHARGE_MINUTES = 30
TEMPERATURE_DISAGREE_C = 5.0
# An enabled TS input reading outside this range is an empty or shorted thermistor input, not a real pack temperature.
TS_PLAUSIBLE_C = (-30.0, 100.0)
TS_UNPOPULATED_MINUTES = 5
VOLTAGE_DISAGREE_V = 0.150
DARK_PANEL_LUX = 20000
PANEL_LIVE_VOLTS = 8.0
