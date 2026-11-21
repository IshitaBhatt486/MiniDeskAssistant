#!/usr/bin/env bash
# Copy run_prototype/ from your laptop to the Raspberry Pi (and optionally install + start it).
# Lives in tools/ (20 Nov 2026), not run_prototype/scripts/: it only runs on the laptop, so the Pi doesn't need it.
# Runs in Git Bash on Windows, or any Linux/macOS shell. Needs only ssh, tar and sha256sum (no rsync).
#
#   tools/deploy.sh pi@deskbot.local                 send only new/changed files, delete removed ones, install only
#                                                      missing Python packages (keeps .venv, models/, data/, outputs/)
#   tools/deploy.sh pi@deskbot.local --full          replace all the code like before 21 Nov 2026 (keeps .venv, models/, data/)
#   tools/deploy.sh pi@deskbot.local --clean         delete ~/deskbot on the Pi first, then copy (fresh install)
#   tools/deploy.sh pi@deskbot.local --wipe-home     DELETE EVERY normal file/folder in the Pi user's home
#                                                      first (shows the list, asks you to type WIPE). Hidden
#                                                      files (.ssh, .bashrc, .config ...) are kept so you
#                                                      can still log in.
#   ... --install      run scripts/setup.sh on the Pi afterwards (asks for the Pi's sudo password)
#   ... --no-packages  don't check for missing Python packages
#   ... --service      install + start the systemd service (starts on boot)
#   ... --dir NAME     folder in the Pi user's home (default: deskbot)
#
# Tip: run `ssh-copy-id pi@deskbot.local` once, so you aren't asked for the password 3 times.
set -euo pipefail
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"   # absolute: --help reads it after the cd below
ROOT="$(cd "$(dirname "$SELF")/../run_prototype" && pwd)"
cd "$ROOT"

HOST="${1:-}"
[ -z "$HOST" ] || [ "${HOST#-}" != "$HOST" ] && { sed -n '2,19p' "$SELF"; exit 2; }
shift
CLEAN=0; FULL=0; PACKAGES=1; WIPE=0; INSTALL=0; SERVICE=0; DIR=deskbot
while [ $# -gt 0 ]; do
  case "$1" in
    --clean) CLEAN=1 ;;
    --full) FULL=1 ;;
    --no-packages) PACKAGES=0 ;;
    --wipe-home) WIPE=1; CLEAN=1 ;;
    --install) INSTALL=1 ;;
    --service) SERVICE=1 ;;
    --dir) DIR="$2"; shift ;;
    -h|--help) sed -n '2,19p' "$SELF"; exit 0 ;;
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

# Every file deploy manages: the project minus .venv, .git, caches, models, datasets and local data (same list on both
# sides, so nothing excluded here is ever sent, compared or deleted on the Pi). Prints "<sha256> <sep><path>" lines.
FIND_FILES='find . \( -path ./.venv -o -path ./.git -o -name __pycache__ -o -path ./models -o -path ./bench_data -o -path ./bench_results -o -path ./e2e_results -o -path ./outputs -o -path ./digital_twin/results -o -path ./data -o -path ./secrets.env -o -path "./robot_shell_settings*.json" \) -prune -o -type f ! -name "*.pyc" -print0 | xargs -0 -r sha256sum'
WORK="$(mktemp -d 2>/dev/null || { mkdir -p "${TMPDIR:-/tmp}/deskbot-$$"; echo "${TMPDIR:-/tmp}/deskbot-$$"; })"
trap 'rm -rf "$WORK"' EXIT

if [ "$CLEAN" = 1 ] || [ "$FULL" = 1 ]; then
  step "Clearing the old code on the Pi"
  # --clean: everything in ~/DIR. --full: the code only (keeps .venv, models/, data/, secrets.env), like deploy did before 21 Nov 2026.
  ssh "$HOST" "set -e
    sudo -n systemctl stop deskbot 2>/dev/null || true
    mkdir -p ~/$DIR && cd ~/$DIR
    if [ $CLEAN = 1 ]; then find . -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    else find . -mindepth 1 -maxdepth 1 ! -name .venv ! -name models ! -name data ! -name secrets.env -exec rm -rf {} +; fi"
fi

step "Comparing the files on the laptop with the Pi"
eval "$FIND_FILES" > "$WORK/local.txt"
ssh "$HOST" "cd ~/$DIR 2>/dev/null || exit 0; $FIND_FILES" > "$WORK/remote.txt"
# sha256sum writes "hash  path" on Linux and "hash *path" in Git Bash: the path always starts at column 67.
awk -v send="$WORK/send.txt" -v del="$WORK/delete.txt" '
  FILENAME == ARGV[1] { remote[substr($0, 67)] = substr($0, 1, 64); next }
  { p = substr($0, 67); seen[p] = 1; if (!(p in remote) || remote[p] != substr($0, 1, 64)) print p > send }
  END { for (p in remote) if (!(p in seen)) print p > del }' "$WORK/remote.txt" "$WORK/local.txt"
touch "$WORK/send.txt" "$WORK/delete.txt"
NSEND=$(wc -l < "$WORK/send.txt" | tr -d ' '); NDEL=$(wc -l < "$WORK/delete.txt" | tr -d ' ')
echo "$(wc -l < "$WORK/local.txt" | tr -d ' ') files: $NSEND new or changed, $NDEL to delete on the Pi"
if [ "$NSEND" -gt 0 ] && [ "$NSEND" -le 20 ]; then sed 's/^/  + /' "$WORK/send.txt"; fi
if [ "$NDEL" -gt 0 ] && [ "$NDEL" -le 20 ]; then sed 's/^/  - /' "$WORK/delete.txt"; fi

if [ "$NSEND" -gt 0 ] || [ "$NDEL" -gt 0 ]; then
  step "Updating $HOST:~/$DIR"
  # Delete files that are gone from the laptop (and folders left empty by that), then unpack the changed ones.
  ssh "$HOST" "set -e
    sudo -n systemctl stop deskbot 2>/dev/null || true
    mkdir -p ~/$DIR && cd ~/$DIR
    while IFS= read -r f; do rm -f -- \"\$f\"; rmdir -p --ignore-fail-on-non-empty \"\$(dirname \"\$f\")\" 2>/dev/null || true; done" < "$WORK/delete.txt"
  if [ "$NSEND" -gt 0 ]; then
    tar czf - -T "$WORK/send.txt" > "$WORK/pkg.tgz"
    # (stdout + redirect, not `tar czf C:/...`: GNU tar would read "C:" as a remote host name)
    echo "$(du -h "$WORK/pkg.tgz" | cut -f1) to send"
    ssh "$HOST" "set -e; tar xzf - -C ~/$DIR; find ~/$DIR/scripts -name '*.sh' -exec chmod +x {} +; echo unpacked into ~/$DIR" < "$WORK/pkg.tgz"
  fi
else
  echo "The Pi already has the latest code."
fi

if [ -f secrets.env ]; then
  if [ "$(sha256sum < secrets.env | cut -c1-64)" != "$(ssh "$HOST" "sha256sum < ~/$DIR/secrets.env 2>/dev/null | cut -c1-64")" ]; then
    step "Copying secrets.env (API keys) - readable only by the Pi user"
    ssh "$HOST" "umask 077; cat > ~/$DIR/secrets.env" < secrets.env
  fi
fi

if [ "$INSTALL" = 0 ] && [ "$PACKAGES" = 1 ]; then
  step "Installing missing Python packages"
  # scripts/missing_packages.py lists the requirement lines that aren't satisfied in the Pi's .venv; pip gets only those.
  ssh "$HOST" "cd ~/$DIR && bash -s" <<'EOF' || echo "Installing the missing packages failed (see above). Retry: tools/deploy.sh HOST, or run with --install"
if [ ! -x .venv/bin/python ]; then
  echo "No .venv on the Pi yet: run deploy once with --install (scripts/setup.sh)."; exit 0
fi
MISSING="$(.venv/bin/python scripts/missing_packages.py requirements*.txt)"
if [ -z "$MISSING" ]; then echo "All Python packages are already installed."; exit 0; fi
echo "Missing:" $MISSING
export TMPDIR="$HOME/.cache/pip-tmp"; mkdir -p "$TMPDIR"   # /tmp on the Pi is a small RAM disk (see setup.sh)
printf '%s\n' "$MISSING" > "$TMPDIR/deskbot-missing.txt"
.venv/bin/python -m pip install -r "$TMPDIR/deskbot-missing.txt"
EOF
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
