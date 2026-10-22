#!/usr/bin/env bash
# Allow YOUR user to give the motor and sensor processes real-time priority (SCHED_FIFO) and a
# negative nice value, without running the robot as root. Run once on the Pi; log out and in again.
#
# What it changes: writes /etc/security/limits.d/deskbot.conf with
#     <you>  -  rtprio  60      (may use SCHED_FIFO/RR priorities up to 60)
#     <you>  -  nice   -10      (may lower nice down to -10)
# That is all. It does not change the kernel's RT throttling (95 % cap), so a runaway real-time
# process still can't freeze the Pi. Undo:  sudo rm /etc/security/limits.d/deskbot.conf
#
# Without this the robot still runs: motor and sensors just get normal priority on their own cores.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

if ! is_pi && [ "$(uname -s)" != "Linux" ]; then
  echo "Only needed on the Raspberry Pi (Linux). Nothing to do here."; exit 0
fi
user="${SUDO_USER:-$USER}"
conf=/etc/security/limits.d/deskbot.conf
echo "Allowing user '$user': rtprio 60, nice -10  ->  $conf (asks for your password)"
printf '# deskbot: real-time motor/sensor processes (scripts/enable-realtime.sh)\n%s - rtprio 60\n%s - nice -10\n' "$user" "$user" \
  | sudo tee "$conf" >/dev/null
echo "Done. Log out and back in (or reboot), then check:  ulimit -r   (should print 60)"
echo "Kernel RT throttling (left on): $(cat /proc/sys/kernel/sched_rt_runtime_us 2>/dev/null) us of $(cat /proc/sys/kernel/sched_rt_period_us 2>/dev/null) us"
