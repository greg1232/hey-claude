#!/bin/bash
#
# Put the Claude Speaker on a Raspberry Pi.
#
#   ./deploy.sh normal@192.168.4.95   name the Pi (remembered afterwards)
#   ./deploy.sh                       deploy again to the same Pi
#   ./deploy.sh --run                 deploy, then start it and watch
#   ./deploy.sh --service             deploy, and start it on every boot
#
# Safe to run as many times as you like: it only re-does the parts that
# changed. The first run takes several minutes, mostly downloading Python
# packages onto the Pi; later runs take seconds.
#
# Your API key travels over the SSH connection and lands in a file only you
# can read. It is never printed, and never committed — .env is in
# .gitignore on both machines.

set -euo pipefail

cd "$(dirname "$0")"

REMOTE_DIR="claude-speaker"     # relative to the Pi user's home
TARGET_FILE=".deploy-target"    # remembers which Pi, so you only say it once

RUN_AFTER=false
INSTALL_SERVICE=false
SKIP_APT=false
TARGET=""

for arg in "$@"; do
  case "$arg" in
    --run)      RUN_AFTER=true ;;
    --service)  INSTALL_SERVICE=true ;;
    --no-apt)   SKIP_APT=true ;;
    -h|--help)  sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         echo "Don't know the option $arg. Try --help."; exit 1 ;;
    *)          TARGET="$arg" ;;
  esac
done

# --- 1. Which Pi? ---
# Told once, then remembered, so day-to-day it's just ./deploy.sh
if [ -z "$TARGET" ] && [ -f "$TARGET_FILE" ]; then
  TARGET="$(cat "$TARGET_FILE")"
fi
if [ -z "$TARGET" ]; then
  echo "Which Pi? Give it a user and address, for example:"
  echo
  echo "    ./deploy.sh normal@192.168.4.95"
  exit 1
fi
echo "$TARGET" > "$TARGET_FILE"
REMOTE_USER="${TARGET%@*}"
echo "Deploying to $TARGET:~/$REMOTE_DIR"

# --- 2. Check the settings file before going anywhere near the network ---
if [ ! -f .env ]; then
  echo
  echo "There's no .env file here, so there's no API key to send."
  echo "Make one first:  cp .env.example .env"
  exit 1
fi
# Read it without printing it, so the key never shows up on screen.
if ! grep -qE '^[[:space:]]*ANTHROPIC_API_KEY=.+' .env; then
  echo
  echo "ANTHROPIC_API_KEY is empty in .env — the Pi would have nothing to use."
  exit 1
fi

# --- 3. Can we reach it? ---
echo
echo "==> Checking the Pi is reachable"
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$TARGET" true 2>/dev/null; then
  echo "Can't log in to $TARGET without a password."
  echo "Set up a key once with:  ssh-copy-id $TARGET"
  exit 1
fi
ssh "$TARGET" 'echo "    $(. /etc/os-release; echo "$PRETTY_NAME") on $(uname -m), Python $(python3 -V | cut -d" " -f2)"'

# --- 4. System packages ---
# sounddevice needs PortAudio, and espeak-ng is the fallback voice for when
# Piper hasn't been set up yet. sudo will ask for the Pi's password.
if [ "$SKIP_APT" = false ]; then
  echo
  echo "==> Installing system packages (sudo may ask for the Pi's password)"
  ssh -t "$TARGET" '
    set -e
    need=""
    for p in python3-venv libportaudio2 libsndfile1 espeak-ng alsa-utils; do
      dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"
    done
    if [ -n "$need" ]; then
      echo "    installing:$need"
      sudo apt-get update -qq
      sudo apt-get install -y -qq $need
    else
      echo "    already installed"
    fi'
else
  echo
  echo "==> Skipping system packages (--no-apt)"
fi

# --- 5. Copy the code ---
# Everything the speaker needs, and nothing it doesn't: no git history, no
# virtualenv built for a different CPU, no training data, and no .env —
# that one goes separately, with tighter permissions.
#
# Logs and the pidfile are excluded too. rsync --delete removes anything at
# the far end that isn't here, and wiping the log on every deploy would
# throw away the record of whatever you were about to investigate.
echo
echo "==> Copying the code"
ssh "$TARGET" "mkdir -p ~/$REMOTE_DIR"
# Plain flags only: macOS still ships rsync 2.6.9, which doesn't know
# --info= and friends.
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude '.deploy-target' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'voices/' \
  --exclude 'train/data/' \
  --exclude 'train/voices/' \
  --exclude 'train/hey_claude/' \
  --exclude '*.png' \
  --exclude '*.log*' \
  --exclude '*.pid' \
  --exclude '.DS_Store' \
  ./ "$TARGET:$REMOTE_DIR/"
echo "    code, models/ and start.sh copied"

# --- 6. Send the settings, including the API key ---
# The Pi is a different machine, so a few settings can't come across as they
# are: the microphone name is this laptop's, and the voice is a macOS one.
# Everything else — your key, your town, the wake word — carries over.
#
# If you'd rather write the Pi's settings by hand, make a .env.pi file and
# that gets sent instead, untouched.
echo
echo "==> Sending settings and API key"
ENV_TMP="$(mktemp)"
chmod 600 "$ENV_TMP"
trap 'rm -f "$ENV_TMP"' EXIT

if [ -f .env.pi ]; then
  echo "    using .env.pi"
  cat .env.pi > "$ENV_TMP"
else
  grep -vE '^[[:space:]]*(INPUT_DEVICE|OUTPUT_DEVICE|VOICE|PIPER_VOICE|WHISPER_MODEL|WAKE_MODEL|WAKE_THRESHOLD)=' .env > "$ENV_TMP" || true
  cat >> "$ENV_TMP" <<'PIENV'

# ---- Added by deploy.sh, because this is the Pi and not the laptop ----

# The Pi speaks with Piper, not the macOS `say` command.
# Listen to the choices at https://rhasspy.github.io/piper-samples/
# Keep to a "medium" voice: measured on a Pi 4, medium needs 0.32 seconds
# of compute per second of speech, but "high" needs 2.0 — slower than
# talking, so the speaker would fall behind itself.
PIPER_VOICE=en_GB-alan-medium

# Which microphone and which speaker.
#   python src/audio_in.py --devices     lists microphones
#   python src/tts.py --devices          lists speakers
#
# OUTPUT_DEVICE is set rather than left empty on purpose. A Pi's ALSA
# default is the first HDMI port, and opening it with no monitor plugged in
# fails outright ("audio open error: Unknown error 524") — so the speaker
# would start up and then not be able to say a word.
#
# Playing through the microphone array, rather than the Pi's headphone
# jack, is worth doing when your speakers are wired that way: the XVF3800
# cancels its own output in hardware, so the array genuinely doesn't hear
# Claude talking. Set it to Headphones if your speakers are in the Pi's
# 3.5mm socket instead.
#
# INPUT_DEVICE is left empty because the array is the only microphone, so
# it's already the default.
INPUT_DEVICE=
OUTPUT_DEVICE=Array

# This array arrives about 20 dB down, which sounds like a broken speaker
# rather than a quiet one. Turn it down here if it's too loud at night;
# leave it blank to not touch the system mixer at all.
OUTPUT_VOLUME=100

# Which wake word, and how sure it has to be. These belong to the Pi
# rather than the laptop, because the right threshold depends on the
# microphone and the room — measure yours:
#     python train/evaluate.py models/<model>.onnx --sweep
WAKE_MODEL=hey_claude_whisper.npz
WAKE_THRESHOLD=0.99

# How often the Whisper wake word looks, in seconds. Costs about 42% of one
# core at 0.4 on a Pi 4. Raise it to spend less, at the cost of noticing you
# a little later.
WAKE_STRIDE_SECONDS=0.4

# A Pi 4 is much slower than a laptop at speech recognition, so use the
# small model. Change it to base.en if it mishears too often and you don't
# mind waiting longer.
WHISPER_MODEL=tiny.en
PIENV
fi

scp -q "$ENV_TMP" "$TARGET:$REMOTE_DIR/.env"
ssh "$TARGET" "chmod 600 ~/$REMOTE_DIR/.env"
rm -f "$ENV_TMP"
trap - EXIT
echo "    sent (readable only by $REMOTE_USER)"

# --- 7. Build the Python environment on the Pi ---
echo
echo "==> Installing Python packages on the Pi (slow the first time)"
# start.sh already knows how to do this, and knowing it in two places is
# how the two drift apart.
ssh "$TARGET" "cd ~/$REMOTE_DIR && ./start.sh --install-only" | sed 's/^/    /'

# --- 8. Fetch the voice and set the volume ---
# The speaker does both of these itself at every startup; doing them here
# too means the first run isn't a long silence, and any problem shows up
# now rather than when someone is stood in front of it asking a question.
echo
echo "==> Downloading the voice and setting the volume"
ssh "$TARGET" "
  cd ~/$REMOTE_DIR
  .venv/bin/python - <<'PY'
import sys
sys.path.insert(0, 'src')
import config, tts
tts.turn_up()
card = tts._output_card()
print('    volume: %s%% on card %s' % (config.OUTPUT_VOLUME or 'left alone', card))
if tts._piper_voice() is None:
    print('    could not load a Piper voice — it will use espeak-ng')
    sys.exit(0)
print('    voice:  %s ready' % config.PIPER_VOICE)
PY"

# --- 9. What can it actually hear and speak through? ---
# This is the step that catches the two things that go wrong in practice:
# no microphone plugged in, and sound coming out of an HDMI port nobody is
# listening to. Better to say so here than to leave it for someone standing
# in front of a silent box.
echo
echo "==> Checking the sound hardware"
ssh "$TARGET" "cd ~/$REMOTE_DIR && .venv/bin/python - <<'PY'
import sys
sys.path.insert(0, 'src')
try:
    import sounddevice as sd
except OSError as error:
    print('    Sound library missing:', error)
    print('    Run ./deploy.sh without --no-apt to install it.')
    raise SystemExit
import config
devices = list(sd.query_devices())
mics = [d['name'] for d in devices if d['max_input_channels'] > 0]
speakers = [d['name'] for d in devices if d['max_output_channels'] > 0]
print('    microphones:', ', '.join(mics) if mics else 'NONE')
print('    speakers:   ', ', '.join(speakers) if speakers else 'NONE')
if not mics:
    print()
    print('    !! No microphone is reaching the Pi, so it can only be used with')
    print('       WAKE_MODE=key and --text. A USB mic should show up in lsusb;')
    print('       an I2S mic HAT needs a dtoverlay= line in')
    print('       /boot/firmware/config.txt before it appears at all.')
if config.OUTPUT_DEVICE and not any(
        config.OUTPUT_DEVICE.lower() in name.lower() for name in speakers):
    print()
    print(f'    !! OUTPUT_DEVICE is {config.OUTPUT_DEVICE!r}, which is not in that list.')
PY" || true

# --- 10. Start on boot, if asked ---
if [ "$INSTALL_SERVICE" = true ]; then
  echo
  echo "==> Setting it to start on boot"
  ssh -t "$TARGET" "
    set -e
    sudo tee /etc/systemd/system/claude-speaker.service >/dev/null <<UNIT
[Unit]
Description=Claude Speaker
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$REMOTE_USER
WorkingDirectory=/home/$REMOTE_USER/$REMOTE_DIR
ExecStart=/home/$REMOTE_USER/$REMOTE_DIR/.venv/bin/python src/main.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable --now claude-speaker
    sleep 2
    systemctl is-active claude-speaker | sed 's/^/    /'"
fi

# --- 11. Put the new code into service ---
# Copying files onto the Pi doesn't change what's already running. Without
# this, a deploy looks like it worked and the speaker carries on with the
# old code until someone notices.
if [ "$INSTALL_SERVICE" = false ]; then
  echo
  if ssh "$TARGET" 'systemctl is-active --quiet claude-speaker' 2>/dev/null; then
    echo "==> Restarting the service so it picks this up"
    ssh -t "$TARGET" 'sudo systemctl restart claude-speaker' && echo "    restarted"
  elif ssh "$TARGET" 'pgrep -f "[s]rc/main.py" >/dev/null' 2>/dev/null; then
    echo "==> Restarting the speaker so it picks this up"
    ssh "$TARGET" "cd ~/$REMOTE_DIR && ./start.sh --stop && ./start.sh" \
      | sed 's/^/    /'
  fi
fi

# --- Done ---
echo
echo "Deployed."
echo
if [ "$INSTALL_SERVICE" = true ]; then
  echo "It's running now and will start again on every boot."
  echo
  echo "  Watch it:     ssh $TARGET journalctl -u claude-speaker -f"
  echo "  Stop it:      ssh $TARGET sudo systemctl stop claude-speaker"
  echo "  Restart it:   ssh $TARGET sudo systemctl restart claude-speaker"
else
  echo "  Start it:     ssh $TARGET 'cd $REMOTE_DIR && ./start.sh'"
  echo "  Watch it:     ssh $TARGET 'tail -f $REMOTE_DIR/speaker.log'"
  echo "  Stop it:      ssh $TARGET 'cd $REMOTE_DIR && ./start.sh --stop'"
  echo "  Type instead: ssh -t $TARGET 'cd $REMOTE_DIR && ./start.sh --text'"
  echo "  On every boot: ./deploy.sh --service"
fi

if [ "$RUN_AFTER" = true ]; then
  echo
  echo "==> Starting it (Ctrl-C to stop)"
  exec ssh -t "$TARGET" "cd $REMOTE_DIR && ./start.sh"
fi
