"""Say the wake word a few times and see what the model actually scores.

The companion to test_silence.py. That one asks "does it fire when nobody
is talking"; this one asks "does it fire when somebody is", which is the
half you notice when you're stood in front of it saying "hey Claude" for
the fourth time.

    python train/test_wake.py models/hey_claude.onnx --times 6

Say the wake word when it tells you to, then stay quiet. It reports the
best score for each attempt, and what threshold would have caught them all.

Worth running on the machine the speaker actually lives on, through the
microphone it actually uses. A wake word that scores 0.99 on the laptop
that trained it can score much lower through a different microphone in a
different room, and the number that matters is the one you get here.
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="path to the .onnx wake word")
    parser.add_argument("--times", type=int, default=6,
                        help="how many attempts to ask for")
    parser.add_argument("--listen", type=float, default=3.0,
                        help="seconds to listen for each attempt")
    args = parser.parse_args()

    import audio_in
    import config
    from openwakeword.model import Model
    import openwakeword.utils

    openwakeword.utils.download_models(model_names=[])
    print(f"Loading {args.model} ...")
    model = Model(wakeword_models=[args.model], inference_framework="onnx")

    best_per_try = []
    with audio_in.Microphone() as mic:
        print(f"\nSay the wake word {args.times} times, once per prompt.\n")
        for attempt in range(1, args.times + 1):
            mic.flush()
            model.reset()
            print(f"  {attempt}/{args.times}  say it now... ", end="", flush=True)

            best, loudest = 0.0, 0.0
            deadline = time.monotonic() + args.listen
            while time.monotonic() < deadline:
                chunk = mic.read(timeout=1.0)
                if chunk is None:
                    continue
                loudest = max(loudest, audio_in.loudness(chunk))
                best = max(best, max(model.predict(chunk).values()))

            best_per_try.append(best)
            heard = "silent" if loudest < 200 else f"level {loudest:.0f}"
            print(f"score {best:.3f}   ({heard})")
            time.sleep(0.4)

    scores = np.array(best_per_try)
    print(f"\n  best   {scores.max():.3f}")
    print(f"  median {np.median(scores):.3f}")
    print(f"  worst  {scores.min():.3f}")

    threshold = config.WAKE_THRESHOLD
    caught = int((scores >= threshold).sum())
    print(f"\n  At WAKE_THRESHOLD={threshold}, {caught} of {len(scores)} "
          f"would have woken it.")

    if caught == len(scores):
        print("  Every attempt worked. Leave the threshold alone.")
        return 0

    # A threshold has to sit below the worst attempt to catch them all, with
    # a little room, since the next attempt won't score exactly like these.
    suggested = max(0.05, round(scores.min() * 0.7, 2))
    print(f"\n  To catch all {len(scores)}, WAKE_THRESHOLD needs to be about "
          f"{suggested} or lower.")
    print("  Check that against a quiet room before trusting it:")
    print(f"      python train/test_silence.py {args.model} "
          f"--seconds 180 --threshold {suggested}")
    print("  Lowering the threshold trades missed wakes for false ones, and")
    print("  the only way to know the price is to measure both.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
