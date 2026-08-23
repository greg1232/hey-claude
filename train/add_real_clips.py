"""Fold real recordings into the training clips, ready for a retrain.

A wake word trained only on synthetic speech recognises synthetic speech.
Measured here, on 80 recordings of four people through the speaker's own
microphone, the all-synthetic model scored a median of 0.001 and would have
woken 7 times out of 80. It isn't a threshold that needs lowering; the
model has simply never heard these voices.

This takes what train/record_wake.py captured and prepares it:

    python train/add_real_clips.py

  - trims the silence either side, so a real clip sits in the detection
    window the way a generated one does;
  - makes speed-shifted variants, which is real variety rather than the
    same utterance again;
  - copies them enough times to matter next to 2000 synthetic clips, since
    the trainer samples positives uniformly and 60 files among 2000 would
    barely register;
  - keeps some back, untouched, so the retrained model can be scored on
    voices it has genuinely never seen.

Then retrain, with --overwrite. Without it the trainer keeps the feature
files it built last time and never looks at the clips you just added:

    python train/train_local.py --training_config train/hey_claude.yml \\
                               --augment_clips --train_model --overwrite

openWakeWord's own augmentation adds room impulse responses and background
noise on top, so the copies don't come out identical.
"""

import argparse
import random
import shutil
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
REAL = HERE / "real" / "hey_claude"
CLIPS = HERE / "hey_claude"
RATE = 16_000

# Marks the files this script owns, so re-running replaces them instead of
# piling a second copy on top.
PREFIX = "real-"

# Speed changes shift pitch too, which is the point: it turns one person
# saying it once into several plausible people saying it.
SPEEDS = (0.85, 0.92, 1.0, 1.08, 1.15)


def load(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def save(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.astype(np.int16).tobytes())


def trim(audio: np.ndarray, margin: float = 0.12) -> np.ndarray:
    """Cut to the speech, keeping a little room either side.

    The recorder starts when you press Enter and stops when you press it
    again, so clips arrive with a second of silence around the phrase. The
    generated clips don't have that, and the model reads a fixed window.
    """
    window = 160  # 10 ms
    frames = audio[:len(audio) // window * window].reshape(-1, window)
    if frames.size == 0:
        return audio
    energy = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    loud = np.where(energy > max(energy.max() * 0.10, 60))[0]
    if len(loud) == 0:
        return audio
    pad = int(margin * RATE / window)
    start = max(0, loud[0] - pad) * window
    end = min(len(frames), loud[-1] + 1 + pad) * window
    return audio[start:end]


def at_speed(audio: np.ndarray, speed: float) -> np.ndarray:
    if speed == 1.0:
        return audio
    # Resampling to a different length and playing at 16 kHz is a speed
    # change; up = 1000, down = round(1000 * speed) keeps the ratio exact.
    resampled = resample_poly(audio.astype(np.float32), 1000, round(1000 * speed))
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copies", type=int, default=5,
                        help="times to repeat each speed variant")
    parser.add_argument("--test", type=int, default=3,
                        help="clips per person for the trainer's own test set")
    parser.add_argument("--holdout", type=int, default=3,
                        help="clips per person kept back entirely")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not REAL.is_dir() or not list(REAL.glob("*.wav")):
        raise SystemExit(
            f"No recordings in {REAL}.\n"
            "Make some first:  python train/record_wake.py --speaker you")
    for folder in (CLIPS / "positive_train", CLIPS / "positive_test"):
        if not folder.is_dir():
            raise SystemExit(
                f"{folder} doesn't exist — generate the synthetic clips "
                "first with train/generate_clips.py")

    # People are the split boundary: a model that has heard someone in
    # training will do better on them at test time, and the number that
    # matters is how it does on the person's other recordings.
    speakers: dict[str, list[Path]] = {}
    for path in sorted(REAL.glob("*.wav")):
        who = path.name.split("-")[0]
        speakers.setdefault(who, []).append(path)

    rng = random.Random(args.seed)
    for folder in (CLIPS / "positive_train", CLIPS / "positive_test"):
        for old in folder.glob(f"{PREFIX}*.wav"):
            old.unlink()

    holdout_list, written_train, written_test = [], 0, 0
    print(f"  {'person':8s} {'clips':>6s} {'train':>6s} {'test':>5s} "
          f"{'held':>5s} {'written':>8s}")

    for who, paths in speakers.items():
        shuffled = list(paths)
        rng.shuffle(shuffled)
        held = shuffled[:args.holdout]
        test = shuffled[args.holdout:args.holdout + args.test]
        train = shuffled[args.holdout + args.test:]

        holdout_list += [p.name for p in held]

        made = 0
        for path in train:
            audio = trim(load(path))
            for speed in SPEEDS:
                variant = at_speed(audio, speed)
                for copy in range(args.copies):
                    name = (f"{PREFIX}{path.stem}-s{int(speed * 100)}"
                            f"-{copy}.wav")
                    save(CLIPS / "positive_train" / name, variant)
                    made += 1
        written_train += made

        for path in test:
            save(CLIPS / "positive_test" / f"{PREFIX}{path.stem}.wav",
                 trim(load(path)))
            written_test += 1

        print(f"  {who:8s} {len(paths):6d} {len(train):6d} {len(test):5d} "
              f"{len(held):5d} {made:8d}")

    (HERE / "real" / "holdout.txt").write_text("\n".join(sorted(holdout_list)) + "\n")

    synthetic = len(list((CLIPS / "positive_train").glob("*.wav"))) - written_train
    share = 100.0 * written_train / (written_train + synthetic)
    print(f"\n  positive_train: {synthetic} synthetic + {written_train} real "
          f"({share:.0f}% real)")
    print(f"  positive_test:  +{written_test} real")
    print(f"  held back:      {len(holdout_list)} clips, listed in "
          f"train/real/holdout.txt")
    print("\n  Now retrain. --overwrite matters: without it the trainer")
    print("  reuses the features it built last time and ignores these clips.")
    print("      python train/train_local.py --training_config "
          "train/hey_claude.yml \\")
    print("                                  --augment_clips --train_model "
          "--overwrite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
