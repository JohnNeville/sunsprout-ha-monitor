from datetime import datetime, timedelta

from custom_components.sunsprout_monitor.rules import check, hold_problems, windows_from_options


def keys(*a, **k):
    return {p.key for p in check(*a, **k)}


def one(key, *a, **k):
    return next(p for p in check(*a, **k) if p.key == key)


def test_clean():
    assert keys({"cell chemistry": "LiFePO4", "gauge chemistry id": "1059.0", "charger fault": "OK"}) == set()


def test_chem_mismatch():
    assert keys({"cell chemistry": "LiFePO4", "gauge chemistry id": "263"}) == {"chem_mismatch"}
    assert keys({"cell chemistry": "Li-ion", "gauge chemistry id": "263"}) == set()


def test_lifepo4_chem_id_ranges():
    life = {"cell chemistry": "LiFePO4"}
    # 0x04xx is the range that turns LiFePO4 relax mode on (0x0423 = 1059); 0x0495 has a blank label in TI's DB but a LiFePO4 profile
    for cid in (0x0400, 0x0423, 0x0495, 0x04FF):
        assert keys({**life, "gauge chemistry id": str(cid)}) == set(), hex(cid)
    # TI's own LiFePO4 families run, but not with relax mode: a warning, not a mismatch
    for cid in (0x4100, 0x4221, 0x4299):
        assert keys({**life, "gauge chemistry id": str(cid)}) == {"chem_no_relax"}, hex(cid)
    assert "0x4221" in one("chem_no_relax", {**life, "gauge chemistry id": "16929"}).detail
    # a Li-ion table under LiFePO4, in either direction, is a mismatch
    assert keys({**life, "gauge chemistry id": str(0x0107)}) == {"chem_mismatch"}
    assert keys({"cell chemistry": "Li-ion", "gauge chemistry id": str(0x0423)}) == {"chem_mismatch"}
    assert keys({"cell chemistry": "Li-ion", "gauge chemistry id": str(0x4221)}) == {"chem_mismatch"}
    # 0x0470 is High Voltage Phosphate, not LiFePO4, despite the 0x04 high byte
    assert keys({**life, "gauge chemistry id": str(0x0470)}) == {"chem_unsupported"}
    # primary, titanate, lead acid and NiMH tables are not supported by this charger
    for cid in (0x0600, 0x0700, 0x0800, 0x6100):
        assert keys({"cell chemistry": "Li-ion", "gauge chemistry id": str(cid)}) == {"chem_unsupported"}, hex(cid)


def test_classify_chem_id():
    from custom_components.sunsprout_monitor.rules import classify_chem_id
    assert classify_chem_id(0x0107) == "liion"
    assert classify_chem_id(0x2044) == "liion"
    assert classify_chem_id(2044) == "liion"  # kept legacy reading
    assert classify_chem_id(0x0423) == "lifepo4_relax"
    assert classify_chem_id(0x4221) == "lifepo4_other"
    assert classify_chem_id(0x0505) == "other"  # 0x05 mixes primary cells with Li-ion
    assert classify_chem_id(0x0470) == "other"


def test_unknown_chem_not_flagged():
    assert keys({"cell chemistry": "Li-ion 4.35", "gauge chemistry id": "999"}) == set()


def test_ts_no_probe():
    assert keys({"ts enable": "Both", "ts status": "Cold"}) == {"ts_no_probe"}
    assert keys({"ts enable": "Both", "ts status": "Cool"}) == set()
    assert keys({"ts enable": "None", "ts status": "Ignored"}) == set()


def test_gauge_setup_and_poor_source():
    assert keys({"gauge setup problem": "on", "gauge setup status": "x"}) == {"gauge_setup"}
    assert keys({"poor source detected": "on"}) == {"poor_source"}
    assert keys({"gauge setup problem": "off", "poor source detected": "off"}) == set()


def test_hiz_needs_duration():
    s = {"charger hiz mode": "on", "solar input present": "on"}
    assert keys(s, {"charger hiz mode": 3}) == set()
    assert keys(s, {"charger hiz mode": 12}) == {"hiz_stuck"}


def test_register_corrections():
    assert keys({"register corrections": "0"}) == set()
    assert keys({"register corrections": "40"}) == {"register_corrections"}


def test_register_corrections_ignore_self_flipping_registers():
    mppt = "EN_MPPT x147: REG0x15&0x01 read 0x00, wanted 0x01 (watch only)"
    assert keys({"register corrections": "372", "last register correction": mppt}) == set()
    assert keys({"register corrections": "40", "last register correction": "EN_HIZ x3: x"}) == set()
    assert keys({"register corrections": "40", "last register correction": "EN_CHG x2: x"}) == {"register_corrections"}


def test_discharging_with_panel_waits_an_hour():
    s = {"input voltage": "21.4", "battery current": "-110", "enable charging": "on", "charger hiz mode": "off"}
    assert one("discharging_with_panel", s).after_min == 60
    assert keys({**s, "battery current": "0"}) == set()
    assert keys({**s, "input voltage": "3.3"}) == set()  # dusk
    assert keys({**s, "enable charging": "off"}) == set()  # charging switched off on purpose
    assert keys({**s, "charger hiz mode": "on"}) == set()  # that is the HIZ rule's business


def test_charger_fault_and_watchdog():
    assert keys({"charger fault": "OK"}) == set()
    assert keys({"charger fault": "unavailable"}) == set()
    assert keys({"charger fault": "VBAT OVP"}) == {"charger_fault"}
    assert keys({"watchdog expired": "on"}) == {"watchdog_expired"}


def test_charging_off_for_a_day():
    assert keys({"enable charging": "off"}, {"enable charging": 600}) == set()
    assert keys({"enable charging": "off"}, {"enable charging": 25 * 60}) == {"charging_off"}
    assert keys({"enable charging": "on"}, {"enable charging": 25 * 60}) == set()


def test_gauge_not_learned_needs_cycles():
    assert keys({"gauge update status": "4", "battery cycle count": "2"}) == set()
    assert keys({"gauge update status": "4", "battery cycle count": "10"}) == {"gauge_not_learned"}
    assert keys({"gauge update status": "6", "battery cycle count": "10"}) == set()


def test_capacity_low():
    assert keys({"battery health": "95"}) == set()
    assert keys({"battery health": "23", "battery full charge capacity": "923"}) == {"capacity_low"}


def test_no_end_of_charge():
    s = {"charge status": "Charge terminated", "battery fully charged": "off", "battery level": "80"}
    assert keys(s) == {"no_end_of_charge"}
    assert keys({**s, "battery fully charged": "on"}) == set()
    assert keys({**s, "battery level": "99"}) == set()


def test_temperature_disagree_handles_fahrenheit():
    f = {"battery temperature": "102.1", "battery temperature (gauge)": "101.9"}
    u = {"battery temperature": "\u00b0F", "battery temperature (gauge)": "\u00b0F"}
    assert keys(f, units=u) == set()
    assert keys({**f, "battery temperature (gauge)": "75"}, units=u) == {"temp_disagree"}


def test_temperature_range_follows_the_chemistry():
    hot = {"battery temperature": "47", "charging": "on"}
    u = {"battery temperature": "\u00b0C"}
    assert keys({**hot, "cell chemistry": "Li-ion"}, units=u) == {"temp_range"}  # 45 C limit
    assert keys({**hot, "cell chemistry": "LiFePO4"}, units=u) == set()  # 50 C limit
    # a custom chemistry is recognised by the gauge's ID
    assert keys({**hot, "cell chemistry": "custom", "gauge chemistry id": "2044"}, units=u) == {"temp_range"}
    assert keys({**hot, "cell chemistry": "custom", "gauge chemistry id": "16929"}, units=u) == set()
    # unknown chemistry: not checked
    assert keys({**hot, "cell chemistry": "custom", "gauge chemistry id": "9"}, units=u) == set()


def test_temperature_range_cold_only_matters_while_charging():
    s = {"battery temperature": "-5", "cell chemistry": "LiFePO4"}
    assert keys(s) == set()
    assert keys({**s, "charging": "on"}) == {"temp_range"}
    assert keys({"battery temperature": "65", "cell chemistry": "LiFePO4"}) == {"temp_range"}


def test_voltage_mismatch():
    assert keys({"battery voltage": "3.544", "battery voltage (gauge)": "3.525"}) == set()
    assert keys({"battery voltage": "3.5", "battery voltage (gauge)": "3.2"}) == {"voltage_mismatch"}


def test_panel_dark():
    assert keys({"roof light sensor": "91000", "solar input present": "on"}) == set()
    assert keys({"roof light sensor": "91000", "solar input present": "off"}) == {"panel_dark"}
    assert keys({"roof light sensor": "50", "solar input present": "off"}) == set()


def test_hold_problems_waits_then_clears():
    from custom_components.sunsprout_monitor.rules import Problem

    since = {}
    t0 = datetime(2026, 10, 29, 12, 0)
    p = [Problem("x", "d", 60), Problem("y", "d")]
    assert [q.key for q in hold_problems(since, "dev", p, t0)] == ["y"]
    assert [q.key for q in hold_problems(since, "dev", p, t0 + timedelta(minutes=59))] == ["y"]
    assert [q.key for q in hold_problems(since, "dev", p, t0 + timedelta(minutes=60))] == ["x", "y"]
    assert hold_problems(since, "dev", [], t0 + timedelta(minutes=61)) == []
    assert since == {}
    # the clock starts again once the condition returns
    assert [q.key for q in hold_problems(since, "dev", p, t0 + timedelta(minutes=70))] == ["y"]


def test_unavailable_states_are_ignored():
    assert keys({"charger fault": "unavailable", "battery health": "unknown", "watchdog expired": "unavailable"}) == set()


def test_unexpected_corrections_counter_wins_when_present():
    mppt = "EN_MPPT x372: x (watch only)"
    # the firmware counted 372 corrections but none unexpected: fine, whatever the latest was
    assert keys({"register corrections": "372", "unexpected register corrections": "0",
                 "last register correction": mppt}) == set()
    assert keys({"register corrections": "372", "unexpected register corrections": "2"}) == set()
    assert keys({"register corrections": "372", "unexpected register corrections": "3",
                 "last register correction": "VREG x3: read 3250 mV, wanted 3600 mV"}) == {"register_corrections"}


def test_windows_from_options():
    assert windows_from_options({}) == {"li-ion": (0.0, 45.0), "lifepo4": (0.0, 50.0)}
    w = windows_from_options({"lifepo4_high_c": 40, "li_ion_low_c": 5})
    assert w == {"li-ion": (5.0, 45.0), "lifepo4": (0.0, 40.0)}


def test_temperature_window_comes_from_the_setup_answers():
    s = {"battery temperature": "44", "charging": "on", "cell chemistry": "LiFePO4"}
    assert keys(s) == set()
    assert keys(s, windows=windows_from_options({"lifepo4_high_c": 40})) == {"temp_range"}


def test_ts_unpopulated_when_enabled_input_reads_nonsense():
    s = {"ts enable": "Both", "battery temperature": "-43.4", "battery temperature (gauge)": "22", "cell chemistry": "Li-ion", "charging": "on"}
    p = one("ts_unpopulated", s)
    assert p.after_min == 5 and "charger" in p.detail
    assert keys(s) == {"ts_unpopulated"}  # no bogus temp_range / temp_disagree on the -43 C reading
    assert keys({**s, "ts status": "Cold"}) == {"ts_unpopulated"}
    assert keys({**s, "ts enable": "Gauge Only"}) == set()  # charger TS disabled, its reading ignored
    assert keys({**s, "ts enable": "None"}) == set()
    g = {"ts enable": "Gauge Only", "battery temperature (gauge)": "-273", "battery temperature": "20"}
    assert "gauge" in one("ts_unpopulated", g).detail


def test_disabled_ts_input_ignored_for_temperature_checks():
    s = {"ts enable": "Gauge Only", "battery temperature": "-43.4", "battery temperature (gauge)": "22",
         "cell chemistry": "Li-ion", "charging": "on"}
    assert keys(s) == set()
    s2 = {**s, "ts enable": "Charger Only", "battery temperature": "47"}
    assert keys(s2) == {"temp_range"}
