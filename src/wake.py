"""Wake word — waits for "Hey Claude".

There are two ways to wake the speaker up, and they have the same interface,
so main.py doesn't care which one is running:

  KeyWaker         press Enter to talk. Always works, no setup.
  WakeWordDetector listen for a spoken wake word using openWakeWord,
                   which runs locally on the laptop.

Pick with WAKE_MODE in .env: auto (default), key, or openwakeword.

A note on "Hey Claude": openWakeWord ships a few pre-trained wake words
(hey_jarvis, alexa, hey_mycroft) but not "Hey Claude" — you have to train
that one yourself. See docs/training-hey-claude.md for how.

Once you have the trained file, drop it in models/ and set this in .env:

    WAKE_MODEL=hey_claude.onnx

Nothing else has to change.
"""

from pathlib import Path

import config
from audio_in import Microphone
from config import PROJECT_ROOT


class KeyWaker:
    """Wake up when the person presses Enter. No microphone needed."""

    label = "press Enter to talk"

    def wait_for_wake(self, mic: Microphone) -> bool:
        """Block until Enter is pressed. Returns False if the user quits."""
        try:
            input()
            return True
        except (EOFError, KeyboardInterrupt):
            return False


class WakeWordDetector:
    """Wake up when the wake word is spoken out loud."""

    def __init__(self) -> None:
        import openwakeword.utils
        from openwakeword.model import Model

        custom = find_custom_model(config.WAKE_MODEL)

        if custom is not None:
            # A model file you trained yourself, e.g. models/hey_claude.onnx
            print(f"Loading the wake word from {custom.name}...")
            to_load, phrase = str(custom), custom.stem
        else:
            # One of the wake words openWakeWord ships with.
            print(f"Loading the '{config.WAKE_MODEL}' wake word...")
            openwakeword.utils.download_models(model_names=[config.WAKE_MODEL])
            to_load, phrase = config.WAKE_MODEL, config.WAKE_MODEL

        # ONNX rather than the default tflite: tflite-runtime has no build
        # for recent Python versions on Apple Silicon, but ONNX comes along
        # with faster-whisper and works fine.
        self._model = Model(wakeword_models=[to_load], inference_framework="onnx")
        self.label = f"say '{phrase.replace('_', ' ')}'"

    def wait_for_wake(self, mic: Microphone) -> bool:
        """Block until the wake word is heard. Returns False on Ctrl-C."""
        # Forget anything heard before now, so an old score can't fire.
        self._model.reset()
        mic.flush()

        while True:
            chunk = mic.read(timeout=1.0)
            if chunk is None:
                continue  # Nothing arriving right now — keep waiting.

            scores = self._model.predict(chunk)
            if any(score >= config.WAKE_THRESHOLD for score in scores.values()):
                self._model.reset()
                return True


def find_custom_model(name: str) -> Path | None:
    """Find a wake word model file you trained yourself.

    Returns None if `name` is one of openWakeWord's built-in wake words
    (hey_jarvis, alexa, hey_mycroft) rather than a file.

    A name counts as a file if it ends in .onnx or .tflite. It's looked for
    as given, and inside the project's models/ folder, so both of these
    work in .env:

        WAKE_MODEL=hey_claude.onnx
        WAKE_MODEL=models/hey_claude.onnx
    """
    if not name.endswith((".onnx", ".tflite")):
        return None  # A built-in wake word name.

    candidates = [Path(name), PROJECT_ROOT / name, PROJECT_ROOT / "models" / name]
    for path in candidates:
        if path.is_file():
            return path.resolve()

    raise SystemExit(
        f"Can't find the wake word model {name!r}.\n"
        f"Looked in:\n"
        + "".join(f"    {p}\n" for p in candidates)
        + "Put the .onnx file in the models/ folder, or set WAKE_MODEL in .env\n"
        "to one of the built-in wake words: hey_jarvis, alexa, hey_mycroft"
    )


def make_waker():
    """Build the waker described by WAKE_MODE in .env."""
    mode = config.WAKE_MODE.lower()

    if mode == "key":
        return KeyWaker()

    if mode in ("auto", "openwakeword"):
        try:
            return WakeWordDetector()
        except ImportError:
            if mode == "openwakeword":
                raise SystemExit(
                    "WAKE_MODE is openwakeword but the package isn't installed.\n"
                    "Install it with:  pip install openwakeword\n"
                    "Or set WAKE_MODE=key in .env to use push-to-talk."
                )
            print("openwakeword isn't installed — using push-to-talk instead.")
            return KeyWaker()
        except Exception as error:  # A model failed to load, etc.
            if mode == "openwakeword":
                raise
            print(f"Wake word unavailable ({error}) — using push-to-talk instead.")
            return KeyWaker()

    raise SystemExit(f"WAKE_MODE must be auto, key, or openwakeword — got {mode!r}")


if __name__ == "__main__":
    # Quick check: wake up three times, then stop.
    waker = make_waker()
    print(f"Ready — {waker.label}. (Ctrl-C to stop.)")
    with Microphone() as mic:
        for _ in range(3):
            if not waker.wait_for_wake(mic):
                break
            print("Woke up!")
