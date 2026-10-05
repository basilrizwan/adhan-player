#!/bin/bash
# One-shot bootstrap: install git if needed and pull the public repo.
# Run on an existing Pi:
#   curl -sL https://raw.githubusercontent.com/basilrizwan/adhan-player/main/scripts/bootstrap-update.sh | bash

set -euo pipefail
ROOT="${ADHAN_HOME:-$HOME/adhan-player}"
if [ ! -d "$ROOT" ]; then
  echo "No $ROOT — cloning..."
  sudo apt-get install -y git python3-venv >/dev/null
  git clone https://github.com/basilrizwan/adhan-player.git "$ROOT"
  cd "$ROOT"
  ./setup.sh
  exit 0
fi
cd "$ROOT"
if ! command -v git >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y git
fi
chmod +x scripts/update.sh 2>/dev/null || true
if [ -x scripts/update.sh ]; then
  bash scripts/update.sh --force
else
  curl -sL https://raw.githubusercontent.com/basilrizwan/adhan-player/main/scripts/update.sh -o /tmp/adhan-update.sh
  bash /tmp/adhan-update.sh --force
fi
echo "Done. Open http://adhan.local:8080"
