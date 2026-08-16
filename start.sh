#!/bin/bash
#
# Start the Claude Speaker.
#
#   ./start.sh           say the wake word, then ask your question
#   ./start.sh --text    type questions instead of speaking them
#
# The first run takes a couple of minutes: it builds a private Python
# folder and downloads the speech models. After that it starts in seconds.

set -euo pipefail

# Work from the project folder, no matter where the script was run from.
cd "$(dirname "$0")"

VENV=".venv"
PYTHON="$VENV/bin/python"
STAMP="$VENV/.installed"

# --- 1. Build the private Python folder, if it isn't there yet ---
if [ ! -x "$PYTHON" ]; then
  echo "Setting up Python for the first time (this takes a minute)..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi

# --- 2. Install the packages, if they changed or were never installed ---
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "Installing the packages it needs..."
  "$VENV/bin/pip" install --quiet -r requirements.txt
  touch "$STAMP"
fi

# --- 3. Check the settings file exists ---
if [ ! -f .env ]; then
  echo
  echo "There's no .env file yet, so it doesn't know your API key."
  echo "Make one and put your key in it:"
  echo
  echo "    cp .env.example .env"
  echo
  echo "Get a key at https://console.anthropic.com/settings/keys"
  exit 1
fi

# --- 4. Check the key is actually filled in ---
# Read it without printing it, so the key never shows up on screen.
if ! grep -qE '^[[:space:]]*ANTHROPIC_API_KEY=.+' .env; then
  echo
  echo "ANTHROPIC_API_KEY is empty in .env."
  echo "Open .env and paste your key after the = sign."
  echo "Get one at https://console.anthropic.com/settings/keys"
  exit 1
fi

# --- 5. Go ---
echo
exec "$PYTHON" src/main.py "$@"
