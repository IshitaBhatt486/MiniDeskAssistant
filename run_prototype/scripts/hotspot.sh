#!/usr/bin/env bash
# Make the Raspberry Pi its own Wi-Fi hotspot, so any phone/laptop can join it and open the dashboard.
# Uses NetworkManager (Raspberry Pi OS Bookworm and later). The dashboard is then at http://10.42.0.1:8000
# (remote: /remote, microphone: https://10.42.0.1:8443/remote).
#
#   scripts/hotspot.sh on [--ssid NAME] [--password PASS]   start the hotspot now
#   scripts/hotspot.sh off                                   stop it (the Pi rejoins your normal Wi-Fi)
#   scripts/hotspot.sh fallback                              start it automatically at boot ONLY when no
#                                                            known Wi-Fi is in range (good for demos)
#   scripts/hotspot.sh nofallback                            undo "fallback"
#   scripts/hotspot.sh status
#
# IMPORTANT: the Pi has one Wi-Fi radio. While the hotspot is on, it is NOT connected to your Wi-Fi, so it
# has no internet unless Ethernet is plugged in: the AI brain, cloud speech-to-text and the weather then
# stop working, and the robot says so and falls back to its offline mode. Alternative with internet:
# turn on your PHONE's hotspot and put the Pi on it as a normal client (sudo nmtui) - then everyone on
# the phone's hotspot can open the dashboard too.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CON=deskbot-hotspot
IFACE="${IFACE:-wlan0}"
CRED="$HOME/.deskbot-hotspot"     # SSID + password are kept here (mode 600) so they stay the same

command -v nmcli >/dev/null || { echo "nmcli not found: this needs NetworkManager (Raspberry Pi OS Bookworm or later)."; exit 1; }

ACTION="${1:-status}"; shift || true
SSID=""; PASS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --ssid) SSID="$2"; shift ;;
    --password) PASS="$2"; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done

load_or_create() {
  if [ -f "$CRED" ]; then . "$CRED"; fi
  SSID="${SSID:-${HOTSPOT_SSID:-DeskBot-$(tr -d ':' < /sys/class/net/$IFACE/address | tail -c 5 | tr a-f A-F)}}"
  PASS="${PASS:-${HOTSPOT_PASS:-$(tr -dc 'a-km-z2-9' < /dev/urandom | head -c 10)}}"
  [ ${#PASS} -ge 8 ] || { echo "The password must be at least 8 characters."; exit 2; }
  (umask 077; printf 'HOTSPOT_SSID=%q\nHOTSPOT_PASS=%q\n' "$SSID" "$PASS" > "$CRED")
}

ensure_connection() {
  load_or_create
  sudo nmcli connection delete "$CON" >/dev/null 2>&1 || true
  # WPA2 (RSN + CCMP) works on every phone; "shared" = the Pi hands out addresses (DHCP) and is 10.42.0.1
  sudo nmcli connection add type wifi ifname "$IFACE" con-name "$CON" autoconnect no ssid "$SSID" \
    802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared ipv6.method ignore \
    wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.psk "$PASS" >/dev/null
}

show() {
  echo "Hotspot:  $SSID"
  echo "Password: $PASS"
  echo "Then open http://10.42.0.1:8000/remote  (microphone: https://10.42.0.1:8443/remote)"
}

case "$ACTION" in
  on)
    ensure_connection
    echo "Starting the hotspot - SSH over Wi-Fi drops now if that's how you're connected."
    sudo nmcli connection up "$CON" >/dev/null
    show
    ;;
  off)
    sudo nmcli connection down "$CON" >/dev/null 2>&1 || true
    echo "Hotspot off. NetworkManager reconnects to your known Wi-Fi by itself (give it ~10 s)."
    ;;
  fallback)
    ensure_connection
    # every normal Wi-Fi profile has priority 0; the hotspot gets -10, so it only starts when none is in range
    sudo nmcli connection modify "$CON" connection.autoconnect yes connection.autoconnect-priority -10
    echo "At boot the Pi joins your Wi-Fi if it's in range, otherwise it becomes this hotspot:"
    show
    echo "(Once the hotspot is up the radio can't scan, so it only switches back to your Wi-Fi after"
    echo " 'scripts/hotspot.sh off' or a reboot.)"
    ;;
  nofallback)
    sudo nmcli connection modify "$CON" connection.autoconnect no 2>/dev/null || true
    echo "The hotspot no longer starts by itself."
    ;;
  status)
    nmcli -t -f NAME,DEVICE,STATE connection show --active | sed 's/^/active: /'
    if nmcli -t -f NAME connection show --active | grep -qx "$CON"; then
      load_or_create; echo; show
    else
      echo "Hotspot is off. Dashboard: http://$(hostname).local:8000"
    fi
    ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
