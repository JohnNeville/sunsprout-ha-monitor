<p align="center"><img src="assets/logo_color.svg" alt="SunSprout" width="160"></p>

# SunSprout Monitor for Home Assistant

[![Open your Home Assistant instance and open a repository inside the Home Assistant Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JohnNeville&repository=sunsprout-ha-monitor&category=integration)

SunSprout Monitor looks after your [SunSprout](https://github.com/JohnNeville/SunSprout-firmware) solar and battery boards. It does two things:

- **Guides you through the first-time setup** of a new board: the cell chemistry, capacity, charge current and thermistors, and the I2C addresses of any satellites, checked before the board ever charges.
- **Watches for problems** the board can only write to its log (a wrong chemistry table, a missing thermistor, a stuck charger, a pack that is not charging and more) and shows them as **Repairs** in Home Assistant, each clearing by itself when the problem goes away.

It does not add devices of its own. It reads the boards you already have in Home Assistant through the ESPHome integration, and only changes anything when you confirm a setup.

## What you need

- **Home Assistant 2026.11 or newer.**
- One or more **SunSprout boards**, running the [SunSprout firmware](https://github.com/JohnNeville/SunSprout-firmware) and already added to Home Assistant through the ESPHome integration.
- For the **guided setup**, SunSprout firmware **release v2026.11.19.13 or newer**, which has the first-time setup actions (`get_setup_info`, `setup_battery` and `scan_i2c`). The cell charge voltage needs a firmware release that has the **Cell Charge Voltage** setting; with older firmware the guide leaves that question out. Boards on older firmware still get every check, without the setup steps.

## Installation

### Install from the Marketplace

Home Assistant 2026.11 includes the Marketplace. SunSprout Monitor is a community project, so you add it from its link ([how custom repositories work](https://www.home-assistant.io/integrations/marketplace/#custom-repositories)):

1. Go to **Settings** > **Marketplace**. The first time, read the warning and accept it. The Marketplace cannot install anything until you do.
2. Select **Add from link** in the upper-right corner. If you have not connected GitHub yet, the Marketplace asks you to.
3. Under **GitHub link**, enter `https://github.com/JohnNeville/sunsprout-ha-monitor` and select **Add**. If it asks for the type, choose **Integration**.
4. Open **SunSprout Monitor** in the list, select **Install**, then **Install** again.
5. If Home Assistant asks for a restart (a repair under **Settings** > **System** > **Repairs** reminds you), restart it.
6. Continue with [Set up the integration](#set-up-the-integration).

### Install with a My Home Assistant link

1. Select this link: [![Open your Home Assistant instance and open a repository inside the Home Assistant Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JohnNeville&repository=sunsprout-ha-monitor&category=integration)
2. Select **Install**, and restart Home Assistant if it asks.
3. Continue with [Set up the integration](#set-up-the-integration).

### Install by hand

Copy the `custom_components/sunsprout_monitor` folder of this repository into the `custom_components` folder of your Home Assistant configuration folder (create it if it is not there), then restart Home Assistant.

## Set up the integration

1. Go to **Settings** > **Devices & services** > **Add integration** and choose **SunSprout Monitor**.
2. It asks for the lowest and highest temperature your cells may be charged at, for each cell family. The defaults are Li-ion 0 to 45 °C and LiFePO4 0 to 50 °C. Take the real limits from your cell's data sheet.
3. Select **Submit**.

There is only one SunSprout Monitor for the whole Home Assistant. It finds every SunSprout board on its own (an ESPHome device that has the **Charger Fault** and **Battery Level** entities), now and when you add more later. A board is matched to a cell family by its **Cell Chemistry**, or by the gauge's chemistry ID when that is "custom". Chemistries other than Li-ion and LiFePO4 are not checked.

To change anything later, select **Configure** on the integration:

| Option | What it does |
|---|---|
| **Set up a board's battery** | The guided setup below, to do again or to change the cell |
| **Set up a board's satellites** | Only the satellite addresses |
| **Charge temperature windows** | The limits from step 2 |

## First-time battery setup

A new board starts with safe defaults (a 6000 mAh LiFePO4 cell) and **charging off**. When SunSprout Monitor sees a board whose setup has not been done, it raises a Repair, **Battery setup not completed**. Select **Fix**, or use **Configure** > **Set up a board's battery**, and the guide:

1. Asks for the **cell chemistry** (LiFePO4 or Li-ion), **capacity**, **energy** (leave 0 to have it worked out), the **cell charge voltage**, the **default charge current** and which **thermistors** are fitted.
2. Checks them: the ranges, a charge current that is high for the capacity, an energy that does not fit the chemistry, a charge voltage above what the chemistry allows, a board with no thermistor (no over- or under-temperature protection), and whether the fuel gauge's chemistry table matches the cell you chose.
3. Shows exactly what will be written and waits for you to confirm.
4. Writes the settings to the charger and the fuel gauge, reads them back, and records that the setup is done.

The **cell charge voltage** is the most each cell is charged to, and it is what protects the cell. Leave it at 0 to use the standard for the chemistry (3.65 V for LiFePO4, 4.20 V for Li-ion). If your cell's data sheet gives a **lower** limit (a 3.60 V LiFePO4 cell, for example), enter it. It can never be set **higher** than the standard, and the board and its charger refuse a higher value, so a typing mistake cannot overcharge a cell. A lower value is always the safe direction, so it is accepted (down to 3.35 V), with a warning when it is more than 0.30 V under the standard, because the cell then stores much less energy.

**It never turns charging on.** When you are ready, turn on **Enable Charging** on the board yourself.

A **chemistry table that does not match** your cell is only a warning, because loading the table into the fuel gauge is a separate step you do yourself (with bqStudio). A LiFePO4 cell needs a table with an ID of `0x04xx` for the gauge's LiFePO4 learning mode to turn on.

### It remembers

The board keeps its own record of the setup, so removing and installing SunSprout Monitor again does not ask you to repeat it. If a newer firmware adds setup items, you get **Battery setup has new options**, and **Fix** opens the guide with your current values filled in. Settings you change by hand afterwards raise nothing.

### Satellites

If the board has [SunSprout Satellites](https://github.com/JohnNeville/SunSprout-firmware#devices) (they appear as child devices with an **ADS1115 Address** and a **DS2482 Address** setting), the guide goes on to ask for each satellite's I2C addresses. They have to match the jumpers on the satellite, and two satellites cannot use the same address.

The board **scans its I2C bus first** and the guide offers only the addresses that answered, so a chip that is not there cannot be chosen. An answer at an address does not say which chip it is. A satellite's present setting always stays in the list, marked "not detected" when nothing answers there, which is a good sign the jumpers and the setting disagree. If the scan cannot run (older firmware, or the board's user 3V3 rail is off) every address is listed and a note says why.

The board only reads the addresses when it starts, so the guide offers to power cycle it (the board's **Power Cycle Board** button) or lets you do it later.

## What it checks

Each check runs once a minute for every board. Where a time is given, the problem has to last that long before the Repair appears. Each Repair clears by itself when the condition does, and you can **Ignore** one you do not want to see.

**Setup and fuel gauge**

| Repair | When it appears |
|---|---|
| Battery setup not completed | The board has no recorded setup |
| Battery setup has new options | The firmware has setup items added since the recorded setup |
| Fuel gauge chemistry does not match the selected cell | A Li-ion table under LiFePO4, or a LiFePO4 table under Li-ion |
| Fuel gauge LiFePO4 learning mode is off | Cell Chemistry is LiFePO4 and the gauge's table is LiFePO4 but not `0x04xx` (for example TI's `0x4221`) |
| Fuel gauge chemistry is not supported | The gauge's table is primary, titanate, lead acid, NiMH or otherwise not lithium-ion |
| Fuel gauge setup | The fuel gauge driver reports a setup problem |
| Gauge has not learned the pack | The gauge still reports "not learned" after 5 or more cycles |
| Capacity reads low | Battery Health under 80 % for 30 min |
| Gauge missed the end of charge | The charge ended but the gauge is not full and reads under 95 %, for 30 min |
| Voltage mismatch | Charger and gauge voltages differ by more than 150 mV for 30 min |

**Temperature**

| Repair | When it appears |
|---|---|
| Temperature probe fault | **TS Enable** expects a thermistor but the charger reads "Cold" |
| TS sensor not populated | An enabled thermistor reads below -30 °C or above 100 °C for 5 min |
| Temperature readings disagree | The charger's and gauge's thermistors differ by more than 5 °C for 30 min (thermistors turned off in TS Enable, or flagged as not fitted, are ignored) |
| Temperature outside the charge window | While charging, outside the window you chose for the cell family, or above 60 °C at any time, for 10 min |

**Charger and solar input**

| Repair | When it appears |
|---|---|
| Charger fault | Charger Fault is anything but OK, for 10 min |
| Charger watchdog expired | The charger's watchdog is expired for 5 min (it resets the charger's settings) |
| Registers keep changing | The charger's registers are corrected again and again (the two that flip themselves at dawn and dusk are not counted) |
| Charging switched off for a long time | Enable Charging has been off for 24 h |
| Solar input rejected | The charger reports a poor source |
| HIZ stuck | The charger is in HIZ with a panel connected for 10 min |
| Pack discharging with the panel live | The panel reads 8 V or more, charging is on, but the pack is discharging by more than 20 mA, for 60 min |
| Bright light but no solar input | 20 000 lx or more and no solar input, for 30 min |

**Connection**

| Repair | When it appears |
|---|---|
| Device unavailable | No data from the board for over an hour |

A sensor named **Open problems** counts all open Repairs and lists them by board in its attributes.

## Updating and removing

Updates appear under **Settings** > **Updates**, like Home Assistant's own, once a release is published. Restart Home Assistant after updating.

To remove it, first delete the integration under **Settings** > **Devices & services**, then uninstall it from **Settings** > **Marketplace** (select **Delete and uninstall** to do both at once). Your boards and their settings are not touched.

## Troubleshooting

**The integration finds no board, or the setup guide says "No SunSprout boards were found".** The board has to be added through the ESPHome integration, be online, and have the **Charger Fault** and **Battery Level** entities enabled.

**There is no "Battery setup not completed" Repair.** The board's firmware does not have the setup actions yet (update it), or the setup was already done. Select **Configure** > **Set up a board's battery** to run it again anyway.

**The chemistry check says nothing for my board.** The check needs the gauge's chemistry ID. SunSprout Monitor asks the board for it. A board on older firmware needs its **Gauge Chemistry ID** entity enabled, which is off by default.

**The setup says the board did not accept it.** The message from the board is shown. The usual cause is a value out of range or the board restarting; try again after a minute.

**Something looks wrong.** Look in **Settings** > **System** > **Logs** for `sunsprout_monitor`, and [open an issue](https://github.com/JohnNeville/sunsprout-ha-monitor/issues) with the log lines and your board's firmware version.

## License

[MIT](LICENSE).

## For developers

The checks are plain functions in `custom_components/sunsprout_monitor/rules.py` and the setup checks in `battery_setup.py`, neither of which imports Home Assistant, so they test without it:

```
uv run --no-project --with pytest python -m pytest tests
```

The integration talks to a board only through its ESPHome actions (`esphome.<device>_get_setup_info`, `_setup_battery`, `_scan_i2c`) and its normal entities. The actions are defined in [SunSprout-firmware](https://github.com/JohnNeville/SunSprout-firmware) (`devices/factory.yaml`).
