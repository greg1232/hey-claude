"""Check a wake word against a quiet room. Run this before trusting a model.

This is the test that matters most for a speaker on a shelf, and the easiest
one to forget. A model can score beautifully on every phrase you throw at it
and still wake hundreds of times an hour on an empty room — because "nobody
is talking" is a kind of audio, and if it wasn't in the training data the
model's behaviour there is undefined.

That happened here. An early model scored 0.99 on ordinary room noise and
fired about 4,000 times an hour. Nothing in the clip tests showed it,
because padding clips with np.zeros is not the same as real microphone
silence — a MacBook in a quiet room sits around 1-50 RMS of preamp hiss,
mains hum and fan rumble, not digital zero.

    python train/test_silence.py models/hey_claude.onnx

Stay quiet while it runs. Anything above zero chunks over 0.5 means the
model needs more quiet-room clips in its negatives, not a higher threshold.
For a reference point, run it against openWakeWord's stock model:

    python train/test_silence.py \\
        .venv/lib/python3.14/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="path to the .onnx wake word")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--threshold", type=float, default=None,
                        help="defaults to WAKE_THRESHOLD from .env")
    args = parser.parse_args()

    import audio_in
    import config
    from openwakeword.model import Model

    threshold = args.threshold if args.threshold is not None else config.WAKE_THRESHOLD
    model = Model(wakeword_models=[str(Path(args.model).resolve())],
                  inference_framework="onnx")
    name = list(model.models.keys())[0]

    print(f"Listening for {args.seconds:.0f}s on {config.INPUT_DEVICE or 'the default mic'}.")
    print("Stay quiet — don't talk, and leave the room sounding as it normally does.\n")

    scores, levels = [], []
    with sd.InputStream(device=audio_in.find_device(config.INPUT_DEVICE),
                        channels=1, samplerate=config.SAMPLE_RATE,
                        dtype="int16", blocksize=config.BLOCK_SIZE) as stream:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            chunk, _ = stream.read(config.BLOCK_SIZE)
            chunk = chunk.reshape(-1)
            scores.append(model.predict(chunk)[name])
            levels.append(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))

    scores = np.array(scores)
    seconds = len(scores) * config.BLOCK_SIZE / config.SAMPLE_RATE
    fired = int((scores >= threshold).sum())

    print(f"room level   : {np.mean(levels):.0f} RMS average, {np.max(levels):.0f} peak")
    print(f"score        : {scores.mean():.4f} average, {scores.max():.4f} worst")
    print(f"over {threshold:<8.2f}: {fired} of {len(scores)} chunks")

    if fired:
        print(f"\nFAIL — about {fired / seconds * 3600:.0f} false wakes an hour.")
        print("The model needs quiet-room clips among its negatives:")
        print("    python train/generate_clips.py ... --silence-fraction 0.12")
        print("Raising WAKE_THRESHOLD only hides this.")
        return 1

    print(f"\nPASS — silent for {seconds:.0f}s.")
    if scores.max() > threshold / 2:
        print(f"Close, though: {scores.max():.3f} against a {threshold} threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
