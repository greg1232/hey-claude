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

# Let Claude search the web when a question turns on something recent.
# The search runs on Anthropic's side, not on the Pi, so it costs no local
# compute — but it does cost money per search and adds a few seconds to the
# answer. Set WEB_SEARCH=off in .env to turn it off.
WEB_SEARCH = _get("WEB_SEARCH", "on").lower() not in ("off", "0", "false", "no")

# Searches allowed per question. A speaker should answer, not research;
# this is the ceiling on both the wait and the bill.
WEB_SEARCH_MAX = int(_get("WEB_SEARCH_MAX", "3"))

# Roughly where the speaker is, in whatever form you'd say out loud —
# "Palo Alto, California". The time zone already narrows this down, but a
# town makes questions like "how long until it gets dark" answerable.
# Leave it empty if you'd rather not tell it.
LOCATION = _get("LOCATION", "")

# What to call the people it talks to, e.g. "Tejas and his family". Only
# used to make it sound less like a stranger. Empty is fine.
HOUSEHOLD = _get("HOUSEHOLD", "")

# --- Voice out ---
# The macOS voice, used by the `say` command. See them all with: say -v '?'
VOICE = _get("VOICE", "Samantha")

# The Piper voice, used on Linux — that's what the Raspberry Pi speaks with.
# Listen to them all at https://rhasspy.github.io/piper-samples/
#
# Stick to a "medium" voice on a Pi 4. Measured on this one, synthesising a
# two sentence answer: medium takes 0.32 seconds per second of speech, so it
# talks three times faster than it can be listened to; "high" takes 2.0
# seconds per second, so the speaker falls behind its own sentences.
PIPER_VOICE = _get("PIPER_VOICE", "en_GB-alan-medium")

# How fast to talk, in words per minute. Means the same thing on both
# machines — tts.py converts it for Piper.
SPEECH_RATE = int(_get("SPEECH_RATE", "180"))

# The gap between sentences, in seconds. Piper's own is about a fifth of a
# second once the silence it leaves at both ends is added up, which sounds
# slow read aloud. Trimmed and replaced with this, so the spacing is a
# choice. Linux only — macOS `say` does its own pacing.
SENTENCE_PAUSE = float(_get("SENTENCE_PAUSE", "0.12"))

# How loud, as a percentage. USB speakers often arrive attenuated — the
# reSpeaker array came set about 20 dB down, quiet enough that you reach for
# the volume knob and find it already at maximum — so the speaker turns
# itself up at startup. Lower it if it's too much at night; set it to
# nothing at all to leave the system mixer alone.
OUTPUT_VOLUME = _get("OUTPUT_VOLUME", "100")

# Which speaker to play out of. Leave empty for the system default, or set
# part of a device name or a device number.
# List them with:  python src/tts.py --devices
#
# Worth setting on a Raspberry Pi: ALSA lists the HDMI outputs first, so the
# default is often a monitor with no speakers rather than the real ones.
OUTPUT_DEVICE = _get("OUTPUT_DEVICE", "")

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

# How much audio from just before recording starts to keep, so running
# straight from the wake word into the question doesn't lose the first word.
# Raise it if the start of questions still gets clipped.
PRE_ROLL_SECONDS = float(_get("PRE_ROLL_SECONDS", "0.5"))
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

# How often a Whisper-based wake word looks, in seconds. It reads a two
# second window, and the phrase is under one, so the phrase falls inside
# several consecutive windows and doesn't have to be caught first time.
# Shorter costs proportionally more compute for slightly less delay.
# Ignored by openWakeWord models, which score every 80 ms chunk.
WAKE_STRIDE_SECONDS = float(_get("WAKE_STRIDE_SECONDS", "0.4"))

# Write down every time the wake word fires, and how the turn went, so the
# mistakes can be learned from. About 1.5 kB per firing, plus the audio.
WAKE_LOG = _get("WAKE_LOG", "on").lower() not in ("off", "0", "false", "no")

# How many recordings of firings to keep. The 768 numbers are kept forever
# — they're what retraining needs — but the audio is 64 kB a time on an SD
# card, so only the most recent are held on to.
WAKE_LOG_CLIPS = int(_get("WAKE_LOG_CLIPS", "400"))

# Also write down windows that came close but didn't fire — the times
# somebody said it and nothing happened. Logging only what fires teaches
# the speaker nothing about the half of the problem it is worse at.
WAKE_NEAR = float(_get("WAKE_NEAR", "0.5"))

# How far back to look for near misses when a wake word does fire. Long
# enough to catch somebody saying it twice, short enough that the room
# before it isn't swept up.
WAKE_NEAR_SECONDS = float(_get("WAKE_NEAR_SECONDS", "15"))

# And a slow trickle of near misses that were never followed by success,
# because whoever it was gave up. Seconds between samples.
WAKE_NEAR_EVERY = float(_get("WAKE_NEAR_EVERY", "180"))


# --- Timers ---
# How long a finished timer keeps ringing if nobody says anything. It beeps
# in bursts with gaps to listen in, so you can stop it by saying the wake
# word; this is the backstop for when nobody is in the room.
RING_SECONDS = float(_get("RING_SECONDS", "30"))


# --- The LED ring on the microphone array ---
# Shows what the speaker is doing: blue for listening, green for talking,
# red when a timer goes off. Set LEDS=off if you'd rather it stayed dark.
LEDS = _get("LEDS", "on").lower() not in ("off", "0", "false", "no")

# Out of 255. The ring is genuinely bright — this is a lamp on a shelf in
# the evening, not a status light in a server room.
LED_BRIGHTNESS = int(_get("LED_BRIGHTNESS", "40"))


# --- Background sounds ---
# How loud rain, ocean and the rest play, from 0 to 1. Quiet on purpose:
# this is something to fall asleep to, and the microphone has to hear you
# over it.
SOUND_VOLUME = float(_get("SOUND_VOLUME", "0.30"))

# How long they play if nobody says. Hours.
SOUND_HOURS = float(_get("SOUND_HOURS", "8"))

# A key for Freesound, which is by far the better place to look up a
# recording of a bullfrog. Free, from https://freesound.org/apiv2/apply/.
# Without one it falls back to Wikimedia Commons, which needs no account
# and is noticeably worse at this.
FREESOUND_KEY = _get("FREESOUND_API_KEY", "")


if __name__ == "__main__":
    # Print what the speaker will actually use, which is not always what you
    # think you set — .env overrides these, and a typo in a name is silent.
    import sys

    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    print(f"Settings, as read from {PROJECT_ROOT / '.env'}:\n")
    for name, value in sorted(globals().items()):
        if name.isupper() and isinstance(value, (str, int, float)):
            # Never print the key, only whether there is one.
            if "API_KEY" in name:
                value = f"<{len(str(value))} characters>" if value else "<not set>"
            print(f"  {name:22s} {value!r}")
