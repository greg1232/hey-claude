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
# Sonnet, not Opus. Measured on this laptop, answering the kind of question
# a kid asks out loud: Opus 2.85s, Sonnet 1.52s, Haiku 0.87s — and all three
# gave the same answers. Claude is about two thirds of the silence between
# a question and a reply, so this is the cheapest speed there is.
# Set CLAUDE_MODEL in .env to change it.
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-5")

# How many past turns to remember. One turn is a question plus an answer.
HISTORY_TURNS = int(_get("HISTORY_TURNS", "10"))

# Roughly where the speaker is, in whatever form you'd say out loud —
# "Palo Alto, California". The time zone already narrows this down, but a
# town makes questions like "how long until it gets dark" answerable.
# Leave it empty if you'd rather not tell it.
LOCATION = _get("LOCATION", "")

# What to call the people it talks to, e.g. "Tejas and his family". Only
# used to make it sound less like a stranger. Empty is fine.
HOUSEHOLD = _get("HOUSEHOLD", "")

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
