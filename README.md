<div align="center">

<!-- LOGO PLACEHOLDER -->
<img style="margin-top: 15px; margin-bottom: -15px; margin-left: 25px" src="./.github/img/logo.svg" alt="BunnyACE" width="120" height="120" />
<h1 style="margin-top: 0">Bunny<span style="color:deepskyblue">ACE</span> </h1>

[![License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE.md)
![Status](https://img.shields.io/badge/Status-WIP-orange)
![Klipper](https://img.shields.io/badge/Klipper-Module-blue)
![Anycubic ACE](https://img.shields.io/badge/Anycubic-ACE%20Pro-8A2BE2)

<p>Driver for Anycubic Color Engine Pro (ACE) for Klipper 🐰🎨</p>
<p>Control filament feed, tool change (up to 4 channels), ACE dryer, and workflows right from Klipper/G-code.</p>

[Русская версия →](./README.ru.md)

</div>

---

## 🧭 Table of Contents
- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Update](#-update)
- [Uninstall](#-uninstall)
- [Quick Start](#-quick-start)
- [Configuration (acecfg)](#-configuration-acecfg)
- [G-code Commands](#-g-code-commands)
- [Sensors and Logic](#-sensors-and-logic)
- [Typical Workflow](#-typical-workflow)
- [Pinout and Wiring](#-pinout-and-wiring)
- [Debug and Logs](#-debug-and-logs)
- [Roadmap](#-roadmap)
- [License](#-license)
- [Authors and Contributors](#-authors-and-contributors)

## ✨ Features
- Up to 4 feed lines (gates) and tool change via G-code 🔀
- Feed Assist on ACE side
- ACE Pro dryer control: start by temperature/time and stop ♨️
- Gate mapping: color, material, recommended temperature 🎯
- Endless Spool mode (auto-switch when filament ends) ♾️
- Integration with filament sensors and Klipper macros 🧩

## 📦 Requirements
- Klipper + Moonraker
- Terminal access to the device running Klipper

## ⚙️ Installation
The script will automatically install the latest driver version.

Remove/comment any sections about your current filament runout sensor in your printer.cfg since you are going to use extruder filament sensor for runout detection.
```bash
cd ~
git clone https://github.com/BlackFrogKok/BunnyACE.git
cd BunnyACE
./install.sh
```

After installation:
- Add [include ace.cfg] to your printer.cfg.
- Moonraker will show an Update Manager entry "BunnyACE" for updates from the web UI.

Important: if you already have your own [save_variables], move variables from ace_vars.cfg into your variables file and comment out the [save_variables] block in ace.cfg.

## 🔄 Update
- Via Web UI: Moonraker Update Manager → BunnyACE

## 🗑️ Uninstall
1) Remove [include ace.cfg] from your Klipper configuration and the update section from moonraker.conf.
2) Run:
```bash
cd ~/BunnyACE
./install.sh -u
```

## 🚀 Quick Start
1) Connect ACE via USB to the Klipper host.
2) Add/verify config: `ace.cfg`. Minimum:
   - serial: path to ACE (e.g., `/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00`)
   - `extruder_sensor_pin:` filament sensor pin at the extruder
   - `toolhead_sensor_pin:` sensor pin before the cutter (if present)
   - `toolchange_retract_length:` you must specify the distance from the splitter to your printer head
   - `poop_macros` you must provide a nozzle purge macro
   - `cut_macros` you must provide a filament tip cut macro
3) Restart Klipper — the console will show a message about successful ACE connection (model and firmware).
4) Test tool change: `T0` / `T1` / `T2` / `T3` (or `ACE_CHANGE_TOOL TOOL=0..3`).

## 🛠️ Configuration (ace.cfg)
Main parameters (see full `ace.cfg` for macros):
- serial: `/dev/serial/by-id/...` — ACE identifier
- baud: `115200` — serial speed
- extruder_sensor_pin: extruder sensor pin (e.g., `!PA4`)
- toolhead_sensor_pin: sensor pin before the cutter (optional)
- feed_speed: `10–80` — base feed speed (this profile `80`; stock ACE `10–25`)
- retract_speed: `10–80` — base retract speed (default `80`)
- toolchange_retract_length: `650` mm — retract length for tool change
- toolhead_sensor_to_nozzle: `20` mm — distance from toolhead sensor to nozzle
- poop_macros: purge macro after load
- cut_macros: cut macro on unload
- max_dryer_temperature: dryer temperature limit (default `70°C`)

Templates at the end of `ace.cfg`:
- `POOP` — purge
- `CUT_TIP` — tip cut
- `_ACE_PRE_TOOLCHANGE` / `_ACE_POST_TOOLCHANGE` — pre/post toolchange macros
- `T0..T3` — shortcuts to `ACE_CHANGE_TOOL`

Variables are saved in `ace_vars.cfg` via `[save_variables]`.

## ⌨️ G-code Commands
ACE adds commands available from Klipper console/macros.

- `ACE_CHANGE_TOOL TOOL=<-1..3>` — change tool (TOOL=-1 unload filament from printer)
- `ACE_START_DRYING TEMP=<°C> DURATION=<min>` — start dryer (default 240 min; limited by `max_dryer_temperature`)
- `ACE_STOP_DRYING` — stop dryer (doesn’t turn off instantly; needs time to cool down)
- `ACE_ENABLE_FEED_ASSIST INDEX=<0..3>` — enable feed assist for a channel
- `ACE_DISABLE_FEED_ASSIST [INDEX=<0..3>]` — disable feed assist (if index not provided, last active is used)
- `ACE_FEED INDEX=<0..3> LENGTH=<mm> [SPEED=<mm/s>]` — feed filament from ACE side
- `ACE_RETRACT INDEX=<0..3> LENGTH=<mm> [SPEED=<mm/s>]` — retract filament into ACE
- `ACE_GATE_MAP GATE=<0..3> [COLOR=<hexRGB>] [TYPE=<PLA/ABS/...>] [TEMP=<°C>]` — set gate metadata
- `ACE_ENDLESS_SPOOL ENABLE=<0|1>` — enable/disable endless spool
- `ACE_DEBUG METHOD=<json_rpc_method> [PARAMS='{"k":"v"}']` — macro to test requests to ACE

## 🧲 Sensors and Logic
Two filament presence sensors are used:
- `extruder_sensor` — at the extruder (required for proper operation)
- `toolhead_sensor` — at the toolhead (optional for fine tuning up to the nozzle)

## 🧪 Typical Workflow
- Tune `POOP` and `CUT_TIP` macros for your printer.
- During printing use `T0..T3` or `ACE_CHANGE_TOOL TOOL=N`.
- For drying: `ACE_START_DRYING TEMP=55 DURATION=180`, stop — `ACE_STOP_DRYING`.

## 🔌 Pinout and Wiring
<img src="./.github/img/pinout.png" alt="drawing" width="500"/>

Important: VCC (24 V) for logic is not required — ACE powers itself. Connect via USB to a regular port.

## 🐞 Debug and Logs
- In Klipper console look for messages starting with `ACE:` — statuses/errors.
- If there’s no connection — check `serial` (/dev/serial/by-id/… or /dev/tty…) and device permissions.
- For low-level communication testing use `ACE_DEBUG`.

## 🗺️ Roadmap
- [ ] UI panel/card in Mainsail/Fluidd (dryer control, gate mapping)
- [ ] Auto-detect `serial` by ACE VID/PID
- [ ] Material presets for quick select (PLA/PETG/ABS, etc.)
- [ ] Docs for integration with popular slicer profiles
- [ ] Tests and CI for stability

## 📜 License
See [LICENSE.md](./LICENSE.md)

## 👥 Authors and Contributors
- A place for authors list and acknowledgements 🙏
- PRs are welcome! Describe changes and follow commit style.