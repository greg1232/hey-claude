"""Wake word built on Whisper's encoder.

The alternative to openWakeWord, and on this data a much better one.

openWakeWord runs a mel filterbank into a frozen 0.33M parameter CNN from
2020, and you train a small head on its output. Measured on the Pi that CNN
is 91% of the compute, the head is 1%, and the head is the only part that
can be trained. On real recordings of real people in a real room it reached
59% recall at 127 false wakes an hour, and nothing done to the head moved
it — the features underneath simply don't separate the classes.

Whisper's tiny encoder does. Same recordings, a logistic regression on its
output: about 90% recall with no measurable false wakes, tested on people
it had never heard. It costs 131 ms per two second window on a Pi 4 against
openWakeWord's 13 ms per 80 ms chunk — 0.26x realtime against 0.16x, which
the Pi can afford.

Train one with train/train_whisper_wake.py, then set in .env:

    WAKE_MODEL=hey_claude_whisper.npz
"""

import time
from pathlib import Path

import numpy as np

import config




class WhisperWakeDetector:
    """Wake up when the wake word is heard, using Whisper's encoder."""

    def __init__(self, model_path: Path) -> None:
        weights = np.load(model_path)
        self._mean = weights["mean"]
        self._scale = weights["scale"]
        self._coef = weights["coef"]
        self._intercept = float(weights["intercept"])
        self._keep = int(weights["keep_frames"])
        self._window = float(weights["window_seconds"])
        whisper_model = str(weights["whisper_model"])

        print(f"Loading the wake word from {model_path.name} "
              f"(whisper {whisper_model})...")
        from faster_whisper import WhisperModel

        # One thread. The wake word runs forever in the background and
        # shouldn't take the whole machine from Whisper and the voice, which
        # need it in bursts. Measured on a Pi 4: 131 ms a window on one
        # thread, 85 ms on four — not worth three extra cores.
        self._whisper = WhisperModel(whisper_model, device="cpu",
                                     compute_type="int8", cpu_threads=1)
        self._features = self._whisper.feature_extractor
        self._samples = int(self._window * config.SAMPLE_RATE)
        self._buffer = np.zeros(self._samples, dtype=np.int16)

        phrase = model_path.stem.split("_whisper")[0].split("-")[0]
        self.label = f"say '{phrase.replace('_', ' ')}'"

    def score(self, audio: np.ndarray) -> float:
        """How much the last two seconds sound like the wake word."""
        mel = self._features(audio.astype(np.float32) / 32768.0)
        mel = mel[..., :self._features.nb_max_frames]
        encoded = np.array(self._whisper.encode(mel))[0][:self._keep]
        vector = np.concatenate([encoded.mean(0), encoded.max(0)])
        standardised = (vector - self._mean) / self._scale
        return float(1.0 / (1.0 + np.exp(-(standardised @ self._coef
                                           + self._intercept))))

    def push(self, chunk: np.ndarray) -> None:
        """Add audio to the rolling window, oldest falling off the front."""
        self._buffer = np.concatenate([self._buffer, chunk])[-self._samples:]

    def wait_for_wake(self, mic) -> bool:
        """Block until the wake word is heard. Returns False on Ctrl-C."""
        self._buffer[:] = 0
        mic.flush()
        next_look = time.monotonic() + config.WAKE_STRIDE_SECONDS

        while True:
            chunk = mic.read(timeout=1.0)
            if chunk is None:
                continue
            self.push(chunk)

            now = time.monotonic()
            if now < next_look:
                continue
            next_look = now + config.WAKE_STRIDE_SECONDS

            if self.score(self._buffer) >= config.WAKE_THRESHOLD:
                self._buffer[:] = 0
                return True


def find_model(name: str) -> Path | None:
    """Find a Whisper wake word file, or None if this isn't one."""
    if not name.endswith(".npz"):
        return None
    for path in (Path(name), config.PROJECT_ROOT / name,
                 config.PROJECT_ROOT / "models" / name):
        if path.is_file():
            return path.resolve()
    raise SystemExit(
        f"Can't find the wake word model {name!r}.\n"
        "Train one with:  python train/train_whisper_wake.py")
