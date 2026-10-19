#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --no-deps -e "$ROOT"
mkdir -p "$HOME/.local/bin"
LINK="$HOME/.local/bin/hermes-rea-team"
if [ -e "$LINK" ] || [ -L "$LINK" ]; then
  if [ "$(readlink "$LINK" 2>/dev/null || true)" != "$ROOT/.venv/bin/hermes-rea-team" ]; then
    printf '%s\n' 'Refusing to replace an unrelated CLI executable.' >&2
    exit 1
  fi
else
  ln -s "$ROOT/.venv/bin/hermes-rea-team" "$LINK"
fi
"$LINK" status
printf '%s\n' 'CLI installed. Native Hermes plugin installation is a separate, explicit step; no gateway restart was performed.'
