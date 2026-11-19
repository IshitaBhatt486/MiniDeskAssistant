#!/usr/bin/env bash
# Copy this project from your laptop to the Raspberry Pi (and optionally install + start it).
# Runs in Git Bash on Windows, or any Linux/macOS shell. Needs only ssh + tar (no rsync).
#
#   scripts/deploy.sh pi@deskbot.local                 update the code (keeps the Pi's .venv, models/, data/)
#   scripts/deploy.sh pi@deskbot.local --clean         delete ~/deskbot on the Pi first, then copy (fresh install)
#   scripts/deploy.sh pi@deskbot.local --wipe-home     DELETE EVERY normal file/folder in the Pi user's home
#                                                      first (shows the list, asks you to type WIPE). Hidden
#                                                      files (.ssh, .bashrc, .config ...) are kept so you
#                                                      can still log in.
#   ... --install      run scripts/setup.sh on the Pi afterwards (asks for the Pi's sudo password)
#   ... --service      install + start the systemd service (starts on boot)
#   ... --dir NAME     folder in the Pi user's home (default: deskbot)
#
# Tip: run `ssh-copy-id pi@deskbot.local` once, so you aren't asked for the password 3 times.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${1:-}"
[ -z "$HOST" ] || [ "${HOST#-}" != "$HOST" ] && { sed -n '2,19p' "$0"; exit 2; }
shift
CLEAN=0; WIPE=0; INSTALL=0; SERVICE=0; DIR=deskbot
while [ $# -gt 0 ]; do
  case "$1" in
    --clean) CLEAN=1 ;;
    --wipe-home) WIPE=1; CLEAN=1 ;;
    --install) INSTALL=1 ;;
    --service) SERVICE=1 ;;
    --dir) DIR="$2"; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done
case "$DIR" in ""|/*|*..*|.) echo "--dir must be a plain folder name inside the home directory"; exit 2 ;; esac

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "Checking the connection to $HOST"
ssh -o ConnectTimeout=8 "$HOST" 'echo "connected to $(hostname) ($(uname -m)), home $HOME"'

if [ "$WIPE" = 1 ]; then
  step "These files and folders in the Pi's home directory will be DELETED:"
  ssh "$HOST" 'cd ~ && ls -1A | grep -v "^\." || echo "(nothing)"'
  printf '\nType WIPE to delete them all, anything else to cancel: '
  read -r answer
  [ "$answer" = "WIPE" ] || { echo "Cancelled. Nothing was deleted."; exit 1; }
  ssh "$HOST" 'sudo systemctl stop deskbot 2>/dev/null || true; cd ~ && find . -mindepth 1 -maxdepth 1 ! -name ".*" -exec rm -rf {} +; echo "home cleaned"'
fi

step "Packing the project (without .venv, caches, models, datasets, local data)"
PKG="$(mktemp -t deskbot-XXXXXX.tgz 2>/dev/null || echo "${TMPDIR:-/tmp}/deskbot-$$.tgz")"
trap 'rm -f "$PKG"' EXIT
tar czf - \
  --exclude=./.venv --exclude=./.git --exclude='*/__pycache__' --exclude='*.pyc' \
  --exclude=./models --exclude=./bench_data --exclude=./bench_results --exclude=./e2e_results --exclude=./outputs --exclude=./digital_twin/results \
  --exclude=./data --exclude=./secrets.env --exclude='./robot_shell_settings*.json' . > "$PKG"
# (stdout + redirect, not `tar czf C:/...`: GNU tar would read "C:" as a remote host name)
echo "$(du -h "$PKG" | cut -f1) to send"

step "Copying to $HOST:~/$DIR"
# One ssh call: stop the service, clear the old code (keeping .venv/models/data unless --clean), unpack.
ssh "$HOST" "set -e
  sudo -n systemctl stop deskbot 2>/dev/null || true
  mkdir -p ~/$DIR
  cd ~/$DIR
  if [ $CLEAN = 1 ]; then
    find . -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  else
    find . -mindepth 1 -maxdepth 1 ! -name .venv ! -name models ! -name data ! -name secrets.env -exec rm -rf {} +
  fi
  tar xzf - -C ~/$DIR
  find ~/$DIR/scripts -name '*.sh' -exec chmod +x {} +
  echo unpacked into ~/$DIR" < "$PKG"

if [ -f secrets.env ]; then
  step "Copying secrets.env (API keys) - readable only by the Pi user"
  ssh "$HOST" "umask 077; cat > ~/$DIR/secrets.env" < secrets.env
fi

if [ "$INSTALL" = 1 ]; then
  step "Installing on the Pi (scripts/setup.sh)"
  ssh -t "$HOST" "cd ~/$DIR && bash scripts/setup.sh"
fi
if [ "$SERVICE" = 1 ]; then
  step "Installing the systemd service"
  ssh -t "$HOST" "cd ~/$DIR && bash scripts/install-service.sh install"
fi

cat <<EOF

Done. On the Pi:
  ssh $HOST
  cd ~/$DIR
  bash scripts/setup.sh                  (first time only)
  bash scripts/assistant.sh              (start; Ctrl+C stops)
  bash scripts/install-service.sh install  (start automatically on boot)
Then open http://${HOST#*@}:8000  (remote: /remote, microphone: https://${HOST#*@}:8443/remote)
EOF
