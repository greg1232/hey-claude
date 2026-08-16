"""Settings, all in one place.

Everything here can be overridden in the .env file. See .env.example.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (the folder above src/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get(name: str, default: str) -> str:
    """Read a setting from .env, falling back to a default."""
    value = os.environ.get(name, "").strip()
    return value if value else default


# --- Claude ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-opus-5")

# How many past turns to remember. One turn is a question plus an answer.
HISTORY_TURNS = int(_get("HISTORY_TURNS", "10"))

# --- Voice out ---
VOICE = _get("VOICE", "Samantha")
SPEECH_RATE = int(_get("SPEECH_RATE", "180"))

# --- Microphone ---
# Which microphone to use. Leave empty for the system default, or set it to
# part of a device name ("MacBook Air Microphone") or a device number.
# List the choices with:  python src/audio_in.py --devices
#
# Worth checking: if you have BlackHole, Loopback, or a virtual meeting
# device installed, macOS may pick that as the default input — and those
# record what the computer is playing, not what you're saying.
INPUT_DEVICE = _get("INPUT_DEVICE", "")

# 16 kHz mono is what Whisper and the wake word detector both want.
SAMPLE_RATE = 16_000
# 80 ms of audio per chunk. openWakeWord likes chunks of 1280 samples.
BLOCK_SIZE = 1280

# Stop recording after this much silence (seconds).
SILENCE_SECONDS = float(_get("SILENCE_SECONDS", "1.0"))
# Always record at least this long, so a slow start doesn't cut you off.
MIN_RECORD_SECONDS = float(_get("MIN_RECORD_SECONDS", "0.7"))
# Give up after this long even if you're still talking.
MAX_RECORD_SECONDS = float(_get("MAX_RECORD_SECONDS", "20.0"))

# --- Speech to text ---
WHISPER_MODEL = _get("WHISPER_MODEL", "base.en")

# --- Wake word ---
WAKE_MODE = _get("WAKE_MODE", "auto")  # auto | openwakeword | key
WAKE_MODEL = _get("WAKE_MODEL", "hey_jarvis")
# How confident the detector has to be (0 to 1). Raise it if the speaker
# keeps waking up on its own; lower it if it ignores you.
WAKE_THRESHOLD = float(_get("WAKE_THRESHOLD", "0.5"))
