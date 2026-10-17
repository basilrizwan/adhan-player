#!/bin/bash
# Update Adhan Player from the public GitHub repo.
# Preserves config.json, cache/, and everything under audio/.
# config.json is gitignored; the stash also covers checkouts made before it was
# untracked (git deletes it when moving past that commit).
#
# Usage:
#   ./scripts/update.sh           # fetch + apply if behind
#   ./scripts/update.sh --check   # report only
#   ./scripts/update.sh --force   # apply even if already up to date (reinstall deps)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPO_URL="${ADHAN_UPDATE_URL:-https://github.com/basilrizwan/adhan-player.git}"
BRANCH="${ADHAN_UPDATE_BRANCH:-main}"
CHECK_ONLY=0
FORCE=0
RESTART=1

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    --no-restart) RESTART=0 ;;
  esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ "${ADHAN_UNATTENDED:-0}" = "1" ] && [ "$FORCE" -eq 0 ]; then
  if [ -f "$ROOT/config.json" ]; then
    SKIP=$(python3 - <<'PY'
import json
from pathlib import Path
p = Path("config.json")
try:
    c = json.loads(p.read_text())
except Exception:
    raise SystemExit(0)
print("1" if c.get("auto_update", True) is False else "0")
PY
)
    if [ "$SKIP" = "1" ]; then
      log "auto_update is false; skipping unattended update"
      exit 0
    fi
  fi
fi

if ! command -v git >/dev/null 2>&1; then
  log "ERROR: git is not installed (apt install git)"
  exit 1
fi

# --- ensure this directory is a git checkout of the public repo ---
if [ ! -d "$ROOT/.git" ]; then
  if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "NOT_GIT (first update will clone $REPO_URL)"
    exit 2
  fi
  log "No .git yet (SD-card copy). Initializing from $REPO_URL ..."
  git init
  git remote add origin "$REPO_URL" 2>/dev/null || git remote set-url origin "$REPO_URL"
fi

git remote set-url origin "$REPO_URL" >/dev/null 2>&1 || true

if [ "$CHECK_ONLY" -eq 1 ]; then
  git fetch origin "$BRANCH"
  LOCAL="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  REMOTE="$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo unknown)"
  log "local  $LOCAL"
  log "remote $REMOTE"
  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "UP_TO_DATE $LOCAL"
    exit 0
  fi
  echo "UPDATE_AVAILABLE $LOCAL -> $REMOTE"
  exit 2
fi

# User-owned state: settings plus every recording under audio/. The user's copy
# always wins over the repo's, so an update never replaces a chosen adhan, dua
# clip, or Kahf file. New files the repo adds still arrive.
STASH="$ROOT/cache/.update-stash"
# Present only while the tree is reset but not yet restored. If a run dies in
# that window, the stash is the only good copy and the next run must restore it
# rather than re-stash the reset files over it.
MARKER="$STASH/.reset-in-progress"

stash_user_files() {
  rm -rf "$STASH"
  mkdir -p "$STASH"
  [ -e "$ROOT/config.json" ] && cp -a "$ROOT/config.json" "$STASH/config.json"
  [ -d "$ROOT/audio" ] && cp -a "$ROOT/audio" "$STASH/audio"
  return 0
}

restore_user_files() {
  if [ -e "$STASH/config.json" ]; then
    cp -a "$STASH/config.json" "$ROOT/config.json"
    log "Restored config.json"
  fi
  if [ -d "$STASH/audio" ]; then
    mkdir -p "$ROOT/audio"
    cp -a "$STASH/audio/." "$ROOT/audio/"
    log "Restored audio/"
  fi
  rm -rf "$STASH"
}

if [ -f "$MARKER" ]; then
  log "Previous update was interrupted; restoring saved user files first"
  restore_user_files
fi

# First-time: fetch + checkout (SD copy → git tree)
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  stash_user_files
  touch "$MARKER"
  git fetch --depth=1 origin "$BRANCH"
  git checkout -f -B "$BRANCH" "origin/$BRANCH"
  log "Git checkout created on $BRANCH"
fi

git fetch origin "$BRANCH"

LOCAL="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
REMOTE="$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo unknown)"
log "local  $LOCAL"
log "remote $REMOTE"

if [ "$LOCAL" = "$REMOTE" ] && [ "$FORCE" -eq 0 ]; then
  log "Already up to date."
  # The first-time checkout above may have overwritten user files.
  [ -f "$MARKER" ] && restore_user_files
  exit 0
fi

[ -f "$MARKER" ] || stash_user_files
touch "$MARKER"

log "Resetting to origin/$BRANCH ..."
git reset --hard "origin/$BRANCH"
git clean -fd -e cache -e venv -e audio

restore_user_files

# Dependencies
if [ -x "$ROOT/venv/bin/pip" ]; then
  log "Updating Python dependencies..."
  "$ROOT/venv/bin/pip" install -q -r "$ROOT/requirements.txt" || \
    "$ROOT/venv/bin/pip" install -r "$ROOT/requirements.txt"
fi

chmod +x "$ROOT/scripts/"*.sh "$ROOT/setup.sh" "$ROOT/prepare-sd.sh" 2>/dev/null || true

NEW="$(git rev-parse --short HEAD)"
log "Updated to $NEW"

if [ "$RESTART" -eq 1 ] && command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet adhan-player 2>/dev/null; then
    log "Restarting adhan-player..."
    # Delay so HTTP callers get a response first
    nohup bash -c 'sleep 2; sudo -n systemctl restart adhan-player' >/dev/null 2>&1 &
  fi
fi

echo "UPDATED $NEW"
exit 0
