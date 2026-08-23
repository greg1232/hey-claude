#!/bin/bash
#
# Start the Claude Speaker.
#
#   ./start.sh                 start it in the background, logging to speaker.log
#   ./start.sh --foreground    run it here instead, printing to this terminal
#   ./start.sh --text          type questions instead of speaking them
#   ./start.sh --stop          stop the one that's running
#   ./start.sh --status        say whether it's running, and where its log is
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
LOG="speaker.log"
PIDFILE="speaker.pid"

MODE="daemon"
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --foreground|-f) MODE="foreground" ;;
    --stop)          MODE="stop" ;;
    --status)        MODE="status" ;;
    --install-only)  MODE="install" ;;
    # Typing questions is a conversation, so it has to stay in front of you.
    --text)          MODE="foreground"; ARGS+=("$arg") ;;
    *)               ARGS+=("$arg") ;;
  esac
done


# Print the running speaker's pid, or nothing at all.
speaker_pid() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    cat "$PIDFILE"
    return
  fi
  # No pidfile, or a stale one — it may have been started by systemd or by
  # hand. The bracket keeps pgrep from matching this script's own command.
  # pgrep exits 1 when it finds nothing, which with `set -e` would end the
  # script rather than answer the question.
  pgrep -f "[s]rc/main\.py" 2>/dev/null | head -1 || true
}

# --- Stop and status don't need any of the setup below ---

if [ "$MODE" = "stop" ]; then
  pid="$(speaker_pid)"
  if [ -z "$pid" ]; then
    echo "Not running."
    rm -f "$PIDFILE"
    exit 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "Wouldn't stop, so making it: pid $pid"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  echo "Stopped."
  exit 0
fi

if [ "$MODE" = "status" ]; then
  pid="$(speaker_pid)"
  if [ -z "$pid" ]; then
    echo "Not running."
  else
    echo "Running as pid $pid."
    echo "  log:  $(pwd)/$LOG"
    echo "  stop: ./start.sh --stop"
  fi
  exit 0
fi

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

# deploy.sh stops here: it only wants the environment built, not a speaker
# listening at the far end of an SSH connection.
if [ "$MODE" = "install" ]; then
  echo "Ready."
  exit 0
fi

# --- 5. Go ---

if [ "$MODE" = "foreground" ]; then
  echo
  exec "$PYTHON" src/main.py ${ARGS+"${ARGS[@]}"}
fi

# Only one at a time. On a microphone array, playing and listening are the
# same piece of hardware and it allows a single stream, so a second speaker
# doesn't share the microphone — it fails, or quietly steals it.
existing="$(speaker_pid)"
if [ -n "$existing" ]; then
  echo "Already running as pid $existing."
  echo "  ./start.sh --stop     stop it"
  echo "  ./start.sh --status   where its log is"
  exit 1
fi

# Keep the last run's log. When something dies at three in the morning, the
# restart is what you notice, and it mustn't erase the reason.
[ -f "$LOG" ] && mv -f "$LOG" "$LOG.1"

# PYTHONUNBUFFERED, because Python buffers its output when it's writing to a
# file rather than a terminal. Without it the log sits empty for a long
# time and looks exactly like a speaker that never started.
PYTHONUNBUFFERED=1 nohup "$PYTHON" src/main.py ${ARGS+"${ARGS[@]}"} \
  > "$LOG" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$PIDFILE"

# Don't claim success before it's earned. Starting up means loading the
# speech model, the voice and the wake word, so give it a moment and then
# check it's still there.
sleep 3
if ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$PIDFILE"
  echo "It started and then stopped. The end of $LOG:"
  echo
  tail -20 "$LOG" | sed 's/^/    /'
  exit 1
fi

echo "Started as pid $pid. It takes about half a minute to be ready."
echo
echo "  watch it:  tail -f $LOG"
echo "  stop it:   ./start.sh --stop"
