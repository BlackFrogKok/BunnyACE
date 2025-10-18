#!/bin/sh
IS_MIPS=0
if [ "$(uname -m)" = "mips" ]; then
   IS_MIPS=1
fi

KLIPPER_HOME="${HOME}/klipper"
KLIPPER_ENV="${HOME}/klippy-env"
KLIPPER_CONFIG_HOME="${HOME}/printer_data/config"
MOONRAKER_CONFIG_DIR="${HOME}/printer_data/config"
SRCDIR="$PWD"


if [ "$IS_MIPS" -eq 1 ]; then
    KLIPPER_HOME="/usr/share/klipper"
    KLIPPER_ENV="/usr/share/klippy-env"
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
  echo -n "[WARNING] If you have custom [save_variables], you must place the ace_vars.cfg data in your vars file and comment out [save_variables] in ace.cfg"
  if [ ! -f "${KLIPPER_CONFIG_HOME}/ace.cfg" ]; then
      cat "${SRCDIR}/ace.cfg" | sed -e "s|{config_path}|${KLIPPER_CONFIG_HOME}|g" > ace.cfg.tmp
      mv ace.cfg.tmp "${KLIPPER_CONFIG_HOME}/ace.cfg"
      cp ace_vars.cfg "${KLIPPER_CONFIG_HOME}/ace_vars.cfg"
      echo "[OK]"
  else
      echo "[SKIPPED]"
  fi
}

install_requirements()
{
    echo -n "Install requirements... "
    "${KLIPPER_ENV}/bin/pip" install -r "${SRCDIR}/requirements.txt"
    echo "[OK]"
}

uninstall()
{
    if [ -f "${KLIPPER_HOME}/klippy/extras/ace.py" ]; then
        echo -n "Uninstalling... "
        rm -f "${KLIPPER_HOME}/klippy/extras/ace.py"
        echo "[OK]"
        echo "You can now remove the [update_manager BunnyAce] section in your moonraker.conf and delete this directory. Also remove all led_effect configurations from your Klipper configuration."
    else
        echo "ace.py not found in \"${KLIPPER_HOME}/klippy/extras/\". Is it installed?"
        echo "[FAILED]"
    fi
}

restart_moonraker()
{
    echo -n "Restarting Moonraker... "
    sudo systemctl restart moonraker
    sleep 1
    echo "[OK]"
}

start_moonraker() {
  echo -n "Starting Moonraker... "
  /etc/init.d/S56moonraker_service start
  sleep 1
  echo "[OK]"
}

stop_moonraker() {
  echo -n "Stopping Moonraker... "
  /etc/init.d/S56moonraker_service stop
  sleep 1
  echo "[OK]"
}

start_klipper() {
  echo -n "Starting Klipper... "
  if [ "$IS_MIPS" -eq 1 ]; then
    /etc/init.d/S55klipper_service start
  else
    sudo systemctl start klipper
  fi
  echo "[OK]"
}


stop_klipper() {
  echo -n "Stopping Klipper... "
  if [ "$IS_MIPS" -eq 1 ]; then
    /etc/init.d/S55klipper_service stop
  else
    sudo systemctl stop klipper
  fi
  echo "[OK]"
}

add_updater()
{
    echo -n "Adding update manager to moonraker.conf... "
    update_section=0
    update_section=$(grep -c '\[update_manager[a-z ]* BunnyACE\]' "${MOONRAKER_CONFIG_DIR}/moonraker.conf" || true)
    if [ "$update_section" -eq 0 ]; then
        echo "\n" >> ${MOONRAKER_CONFIG_DIR}/moonraker.conf
        while read -r line; do
            echo "${line}" >> ${MOONRAKER_CONFIG_DIR}/moonraker.conf
        done < "${SRCDIR}/templates/moonraker_update.txt"
        echo "\n" >> ${MOONRAKER_CONFIG_DIR}/moonraker.conf
        echo "[OK]"

        if [ "$IS_MIPS" -eq 1 ]; then
          stop_moonraker
          start_moonraker
        else
          restart_moonraker
        fi
    else
        echo "[SKIPPED]"
    fi

}


verify_ready
check_folders
stop_klipper

if [ "$UNINSTALL" -ne 1 ]; then
    link_extension
    copy_config
    add_updater
else
    uninstall
fi

start_klipper
