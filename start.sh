#!/bin/bash
#
# Start the Claude Speaker.
#
#   ./start.sh                 say the wake word, then ask your question
#   ./start.sh --text          type questions instead of speaking them
#   ./start.sh --install-only  build the environment and stop (deploy.sh uses this)
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

  # The wake word, on Linux. It has to go in by hand and without its
  # dependencies, because openWakeWord insists on tflite-runtime there and
  # there's no build of that for recent Pythons on Arm. We don't use it —
  # wake.py loads the ONNX build — and the packages it really needs are in
  # requirements.txt. Without --no-deps, pip refuses to install anything at
  # all on a Raspberry Pi.
  if [ "$(uname -s)" = "Linux" ]; then
    "$VENV/bin/pip" install --quiet --no-deps 'openwakeword>=0.6.0'
  fi

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
# deploy.sh stops here: it only wants the environment built, not a speaker
# listening at the far end of an SSH connection.
for arg in "$@"; do
  if [ "$arg" = "--install-only" ]; then
    echo "Ready."
    exit 0
  fi
done

echo
exec "$PYTHON" src/main.py "$@"
