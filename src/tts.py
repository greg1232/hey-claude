"""Text to speech — makes the laptop talk.

Uses the macOS `say` command, which is already installed, free, works
offline, and needs no setup at all.

To hear the other voices:  say -v '?'
"""

import subprocess
import threading

import config

# True while the speaker is talking out loud. The microphone watches this
# so the speaker doesn't hear itself and wake itself up in a loop.
speaking = threading.Event()

# A short built-in macOS sound, used as the "I'm listening" beep.
BEEP_SOUND = "/System/Library/Sounds/Tink.aiff"


def speak(text: str) -> None:
    """Say `text` out loud and wait until it finishes."""
    text = text.strip()
    if not text:
        return

    speaking.set()
    try:
        subprocess.run(
            ["say", "-v", config.VOICE, "-r", str(config.SPEECH_RATE), text],
            check=False,
        )
    finally:
        speaking.clear()


def beep() -> None:
    """Play a short sound so you know it started listening."""
    speaking.set()
    try:
        subprocess.run(["afplay", BEEP_SOUND], check=False)
    finally:
        speaking.clear()


if __name__ == "__main__":
    # Step 1 of the build order: make the laptop say hello.
    beep()
    speak("Hello, I am Claude. I am your speaker.")
