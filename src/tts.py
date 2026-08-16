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
    """Play the "I'm listening" sound, and start recording straight away.

    This deliberately does not wait for the sound to finish, and does not
    set `speaking`. Both were costing the first words of every question:
    `afplay` takes 1.2-1.7 seconds to start up and play a 0.56 second
    sound, and with the microphone muted for all of it, anyone who answered
    the beep promptly had their opening words thrown away. You had to pause
    for a beat before speaking, which is exactly the wrong instinct to
    teach someone.

    The cost is that the beep itself lands at the top of the recording.
    That's fine — it's short, and Whisper ignores it. Muting matters for
    `speak()`, where the speaker really would hear itself and wake up in a
    loop; a tink is not that.
    """
    subprocess.Popen(
        ["afplay", BEEP_SOUND],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    # Step 1 of the build order: make the laptop say hello.
    beep()
    speak("Hello, I am Claude. I am your speaker.")
