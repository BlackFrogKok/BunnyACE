#!/bin/sh
IS_MIPS=0
if [ "$(uname -m)" = "mips" ]; then
   IS_MIPS=1
fi

KLIPPER_HOME="${HOME}/klipper"
KLIPPER_CONFIG_HOME="${HOME}/printer_data/config"
MOONRAKER_CONFIG_DIR="${HOME}/printer_data/config"
SRCDIR="$PWD"

if [ "$IS_MIPS" -eq 1 ]; then
    KLIPPER_HOME="/usr/share/klipper"
    KLIPPER_CONFIG_HOME="/usr/data/printer_data/config"
    MOONRAKER_CONFIG_DIR="/usr/data/printer_data/config"
fi

usage(){ echo "Usage: $0 [-u]" 1>&2; exit 1; }
# Parse command line arguments
UNINSTALL=0
while getopts "uh" arg; do
   case $arg in
       u) UNINSTALL=1;;
       h) usage;;
   esac
done

verify_ready()
{
  if [ "$IS_MIPS" -ne 1 ]; then
    if [ "$EUID" -eq 0 ]; then
        echo "[ERROR] This script must not run as root. Exiting."
        exit 1
    fi
  else
    echo -e "[WARNING] This script is running on a MIPS system, so we expect it to be run as root"
  fi
}

check_folders()
{
    if [ ! -d "$KLIPPER_HOME/klippy/extras/" ]; then
        echo "[ERROR] Klipper installation not found in directory \"$KLIPPER_HOME\". Exiting"
        exit 1
    fi
    echo "Klipper installation found at $KLIPPER_HOME"

    if [ ! -d "${KLIPPER_CONFIG_HOME}/" ]; then
        echo "[ERROR] Klipper configs not found in directory \"$MOONRAKER_CONFIG_DIR\". Exiting"
        exit 1
    fi
    echo "Klipper installation found at $KLIPPER_CONFIG_HOME"

    if [ ! -f "${MOONRAKER_CONFIG_DIR}/moonraker.conf" ]; then
        echo "[ERROR] Moonraker configuration not found in directory \"$MOONRAKER_CONFIG_DIR\". Exiting"
        exit 1
    fi
    echo "Moonraker configuration found at $MOONRAKER_CONFIG_DIR"
}

link_extension()
{
    echo -n "Linking extension to Klipper... "
    ln -sf "${SRCDIR}/extras/ace.py" "${KLIPPER_HOME}/klippy/extras/ace.py"
    echo "[OK]"
}

copy_config()
{
  echo -n "Copy config file to Klipper... "
  if [ ! -f "${KLIPPER_CONFIG_HOME}/ace.cfg" ]; then
      cp "${SRCDIR}/ace.cfg" "${KLIPPER_CONFIG_HOME}"
      echo "[OK]"
  else
      echo "[SKIPPED]"
  fi
}

install_requirements()
{
    echo -n "Install requirements... "
    set -x
    pip3 install -r "${SRCDIR}/requirements.txt"
    set +x
    echo "[OK]"
}

uninstall()
{
    if [ -f "${KLIPPER_HOME}/klippy/extras/ace.py" ]; then
        echo -n "Uninstalling... "
        rm -f "${KLIPPER_HOME}/klippy/extras/ace.py"
        echo "[OK]"
        echo "You can now remove the [update_manager FrogAce] section in your moonraker.conf and delete this directory. Also remove all led_effect configurations from your Klipper configuration."
    else
        echo "ace.py not found in \"${KLIPPER_HOME}/klippy/extras/\". Is it installed?"
        echo "[FAILED]"
    fi
}

restart_moonraker()
{
    echo -n "Restarting Moonraker... "
    set +e
    /etc/init.d/S56moonraker_service restart
    sleep 1
    set -e
    echo "[OK]"
}

start_klipper() {
  echo -n "Starting Klipper... "
  set +e
  /etc/init.d/S55klipper_service start
  set -e
  echo "[OK]"
}

stop_klipper() {
  echo -n "Stopping Klipper... "
  set +e
  /etc/init.d/S55klipper_service stop
  set -e
  echo "[OK]"
}

add_updater()
{
    echo -n "Adding update manager to moonraker.conf... "
    update_section=0
    update_section=$(grep -c '\[update_manager[a-z ]* BunnyACE\]' "${MOONRAKER_CONFIG_DIR}/moonraker.conf" || true)
    if [ "$update_section" -eq 0 ]; then
        echo "\n[update_manager BunnyACE]" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "type: git_repo" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "path: ${SRCDIR}" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "primary_branch: master" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "origin: https://github.com/BlackFrogKok/BunnyACE" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "managed_services: klipper" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "\n" >> "${MOONRAKER_CONFIG_DIR}/moonraker.conf"
        echo "[OK]"
    else
        echo "[SKIPPED]"
    fi
}


verify_ready
check_folders
stop_klipper

if [ "$UNINSTALL" -ne 1 ]; then
    install_requirements
    link_extension
    copy_config
    add_updater
    restart_moonraker
else
    uninstall
fi

start_klipper
