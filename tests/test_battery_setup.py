from custom_components.sunsprout_monitor.battery_setup import (
    ADS_ADDRESSES, DS_ADDRESSES, address_choices, check_satellite_addresses, check_setup, default_energy_mwh, parse_found_addresses,
    standard_cell_voltage_mv)

GOOD = {"chemistry": "LiFePO4", "capacity_mah": 4000, "energy_mwh": 0, "charge_current_ma": 1000, "thermistors": "Both"}


def test_default_energy():
    assert default_energy_mwh("LiFePO4", 6000) == 19200
    assert default_energy_mwh("Li-ion", 2500) == 9250
    assert default_energy_mwh("Li-ion", 20000) == 32767  # the gauge's 16-bit field


def test_clean_setup():
    r = check_setup(GOOD, 0x0423)
    assert r.errors == {} and r.warnings == []


def test_ranges_block_the_setup():
    assert check_setup({**GOOD, "capacity_mah": 50}).errors == {"capacity_mah": "capacity_invalid"}
    assert check_setup({**GOOD, "capacity_mah": 30000}).errors == {"capacity_mah": "capacity_invalid"}
    assert check_setup({**GOOD, "energy_mwh": 50}).errors == {"energy_mwh": "energy_invalid"}
    assert check_setup({**GOOD, "charge_current_ma": 2500}).errors == {"charge_current_ma": "current_invalid"}
    assert check_setup({**GOOD, "chemistry": "NiMH"}).errors == {"chemistry": "chemistry_invalid"}
    assert check_setup({**GOOD, "thermistors": "Some"}).errors == {"thermistors": "thermistors_invalid"}


def test_chemistry_id_is_only_a_warning():
    # the owner loads the table in their own step, so the setup may come first
    for cid in (0x0107, 0x4221):
        r = check_setup(GOOD, cid)
        assert r.errors == {} and len(r.warnings) == 1, hex(cid)
    assert "relax mode" in check_setup(GOOD, 0x4221).warnings[0]
    assert "0x0107" in check_setup(GOOD, 0x0107).warnings[0]
    li = {**GOOD, "chemistry": "Li-ion", "charge_current_ma": 1000}
    assert check_setup(li, 0x0107).warnings == []
    assert len(check_setup(li, 0x0423).warnings) == 1
    assert check_setup(GOOD, None).warnings == []  # not known yet


def test_current_and_energy_and_thermistor_warnings():
    assert any("above 0.5C" in w for w in check_setup({**GOOD, "capacity_mah": 3000, "charge_current_ma": 2000}, 0x0423).warnings)
    assert check_setup({**GOOD, "chemistry": "Li-ion", "charge_current_ma": 2000, "capacity_mah": 2500}, 0x0107).warnings == []
    assert any("far from" in w for w in check_setup({**GOOD, "energy_mwh": 30000}, 0x0423).warnings)
    assert check_setup({**GOOD, "energy_mwh": 12800}, 0x0423).warnings == []  # 4000 mAh x 3.2 V
    assert any("no thermistor" in w for w in check_setup({**GOOD, "thermistors": "None"}, 0x0423).warnings)
    assert any("ignores its own thermistor" in w for w in check_setup({**GOOD, "thermistors": "Gauge Only"}, 0x0423).warnings)


def test_satellite_addresses():
    sats = [{"ads": "0x48", "ds": "0x18"}, {"ads": "0x49", "ds": "0x1A"}]
    assert check_satellite_addresses(sats) == {}
    assert check_satellite_addresses([{"ads": "0x48", "ds": "0x18"}]) == {}
    # the second satellite on the same ADS1115 or DS2482 address is the one flagged
    assert check_satellite_addresses([{"ads": "0x48", "ds": "0x18"}, {"ads": "0x48", "ds": "0x1A"}]) == {"sat_1_ads": "address_duplicate"}
    assert check_satellite_addresses([{"ads": "0x48", "ds": "0x18"}, {"ads": "0x49", "ds": "0x18"}]) == {"sat_1_ds": "address_duplicate"}
    # an ADS1115 address is not a DS2482 address and the other way round
    assert check_satellite_addresses([{"ads": "0x18", "ds": "0x48"}]) == {"sat_0_ads": "address_invalid", "sat_0_ds": "address_invalid"}
    assert check_satellite_addresses([]) == {}


def test_parse_found_addresses():
    assert parse_found_addresses("0x18,0x49,0x4a") == {"0x18", "0x49", "0x4A"}
    assert parse_found_addresses("") == set()
    assert parse_found_addresses(None) is None
    assert parse_found_addresses("0x48, junk ,0x1B") == {"0x48", "0x1B"}


def test_address_choices():
    found = {"0x18", "0x1A", "0x49", "0x4A"}
    assert address_choices(ADS_ADDRESSES, found, "0x49") == [("0x49", "0x49"), ("0x4A", "0x4A")]
    assert address_choices(DS_ADDRESSES, found, "0x1A") == [("0x18", "0x18"), ("0x1A", "0x1A")]
    # the present setting is kept, marked, when nothing answers there
    assert address_choices(ADS_ADDRESSES, found, "0x48") == [("0x48", "0x48 (not detected)"), ("0x49", "0x49"), ("0x4A", "0x4A")]
    # nothing answered in this range, or no answer to the scan: every address, unmarked
    assert address_choices(ADS_ADDRESSES, {"0x18"}, "0x48") == [(a, a) for a in ADS_ADDRESSES]
    assert address_choices(ADS_ADDRESSES, set(), "0x48") == [(a, a) for a in ADS_ADDRESSES]
    assert address_choices(ADS_ADDRESSES, None, "0x48") == [(a, a) for a in ADS_ADDRESSES]


def test_standard_cell_voltage():
    assert standard_cell_voltage_mv("LiFePO4") == 3650
    assert standard_cell_voltage_mv("Li-ion") == 4200


def test_cell_charge_voltage_can_only_lower_the_standard():
    life = {**GOOD, "chemistry": "LiFePO4"}
    # 0 and the standard itself are fine and raise nothing
    for mv in (0, 3650):
        r = check_setup({**life, "cell_charge_voltage_mv": mv}, 0x0423)
        assert r.errors == {} and r.warnings == [], mv
    # a lower limit, as a cell's data sheet may give, is allowed and noted
    r = check_setup({**life, "cell_charge_voltage_mv": 3600}, 0x0423)
    assert r.errors == {} and len(r.warnings) == 1 and "3.60 V instead of the standard 3.65 V" in r.warnings[0]
    # lower is the safe direction, so the lowest the firmware takes is allowed too (exactly 0.30 V under is not "more than" 0.30 V)
    r = check_setup({**life, "cell_charge_voltage_mv": 3350}, 0x0423)
    assert r.errors == {} and len(r.warnings) == 1
    li = {**GOOD, "chemistry": "Li-ion", "charge_current_ma": 1000}
    r = check_setup({**li, "cell_charge_voltage_mv": 3650}, 0x0107)  # the value an upgraded Li-ion board starts with
    assert r.errors == {} and any("much less energy" in w for w in r.warnings)
    assert check_setup({**li, "cell_charge_voltage_mv": 4200}, 0x0107).errors == {}
    assert check_setup({**li, "cell_charge_voltage_mv": 4000}, 0x0107).errors == {}
    # higher than the standard is never allowed, and neither is a value under the firmware's minimum
    for mv in (3651, 4200, 3349, 3000):
        assert check_setup({**life, "cell_charge_voltage_mv": mv}).errors == {"cell_charge_voltage_mv": "voltage_invalid"}, mv
    assert check_setup({**li, "cell_charge_voltage_mv": 4250}).errors == {"cell_charge_voltage_mv": "voltage_invalid"}
    assert check_setup({**li, "cell_charge_voltage_mv": 3300}).errors == {"cell_charge_voltage_mv": "voltage_invalid"}
    # a board without the setting just does not send it
    assert check_setup(GOOD, 0x0423).errors == {}


def test_fix_flows_have_strings():
    """Every issue with a Fix button has a fix_flow in the strings, and the flow kinds are known."""
    import json, pathlib
    from custom_components.sunsprout_monitor.const import FIX_FLOWS
    base = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "sunsprout_monitor"
    for name in ("strings.json", "translations/en.json"):
        issues = json.loads((base / name).read_text())["issues"]
        for key, kind in FIX_FLOWS.items():
            assert kind in ("setup", "enable_charging", "thermistors", "hiz"), (key, kind)
            assert "fix_flow" in issues[key], (name, key)
            assert "Fix it" in issues[key]["description"] or key in ("setup_unset", "setup_outdated"), (name, key)
