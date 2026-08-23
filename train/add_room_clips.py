"""Add recorded room sound to the negatives, ready for a retrain.

The partner to add_real_clips.py. That one taught the model four voices;
this one teaches it what their room sounds like when nobody is talking.

Both halves turned out to be necessary. Training on real voices took real
recall from 9% to 80%, and simultaneously took false wakes on the actual
microphone to about 180 an hour — because the model had learned what these
people sound like without ever hearing the room they say it in. Borrowed
validation audio said 0.53 an hour and was wrong by a factor of 340.

    python train/record_room.py --minutes 10     # on the speaker
    python train/add_room_clips.py               # here
    python train/train_local.py --training_config train/hey_claude.yml \\
                                --augment_clips --train_model --overwrite

--overwrite matters. Without it the trainer keeps the features it built
last time and never looks at anything added here.
"""

import argparse
import random
import shutil
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOM = HERE / "room"
CLIPS = HERE / "hey_claude"
PREFIX = "room-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-share", type=float, default=0.2,
                        help="fraction held back for the trainer's test set")
    parser.add_argument("--holdout-share", type=float, default=0.2,
                        help="fraction kept out of training entirely, for "
                             "measuring false wakes honestly")
    parser.add_argument("--share", type=float, default=0.35,
                        help="what fraction of the negatives should be room "
                             "audio; copies are made to reach it")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    clips = sorted(ROOM.glob("*.wav"))
    if not clips:
        raise SystemExit(
            f"No room recordings in {ROOM}.\n"
            "Record some on the speaker first:\n"
            "    python train/record_room.py --minutes 10")

    train_dir = CLIPS / "negative_train"
    test_dir = CLIPS / "negative_test"
    for folder in (train_dir, test_dir):
        if not folder.is_dir():
            raise SystemExit(f"{folder} doesn't exist — generate the "
                             "synthetic clips first")
        for old in folder.glob(f"{PREFIX}*.wav"):
            old.unlink()

    rng = random.Random(args.seed)
    shuffled = list(clips)
    rng.shuffle(shuffled)

    # Three ways, not two. The trainer selects checkpoints against its own
    # test set, so a false-wake rate measured there is a best-of statistic.
    # The holdout is never trained on and never selected against, which
    # makes it the only room audio whose number means anything.
    n_hold = int(len(shuffled) * args.holdout_share)
    n_test = int(len(shuffled) * args.test_share)
    holdout = shuffled[:n_hold]
    test = shuffled[n_hold:n_hold + n_test]
    train = shuffled[n_hold + n_test:]

    # Ten minutes of room gives a few hundred clips against 7600 existing
    # negatives — about 3%, and openWakeWord draws only 50 of these per
    # batch against 1024 generic ones, so room audio would turn up once or
    # twice a batch and teach the model nothing. Copies fix the share;
    # openWakeWord's augmentation adds different room impulse responses and
    # noise to each, so they don't come back identical.
    other = len(list(train_dir.glob("*.wav")))
    copies = 1
    if train and 0 < args.share < 1:
        wanted = args.share * other / (1 - args.share)
        copies = max(1, round(wanted / len(train)))

    for path in train:
        for n in range(copies):
            shutil.copyfile(path, train_dir / f"{PREFIX}{n}-{path.name}")
    for path in test:
        shutil.copyfile(path, test_dir / f"{PREFIX}{path.name}")

    (ROOM / "holdout.txt").write_text(
        "\n".join(sorted(p.name for p in holdout)) + "\n")

    levels = []
    for path in shuffled[:200]:
        with wave.open(str(path)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        levels.append(float(np.sqrt((audio.astype(np.float64) ** 2).mean())))
    level = np.array(levels) if levels else np.zeros(1)

    written = len(train) * copies
    existing_train = len(list(train_dir.glob("*.wav"))) - written
    seconds = sum(
        wave.open(str(p)).getnframes() / 16000 for p in shuffled[:len(shuffled)])
    print(f"  {len(clips)} room clips ({seconds / 60:.1f} minutes)")
    print(f"  level: {level.mean():.0f} RMS average, {level.max():.0f} peak")
    share = 100.0 * written / max(1, written + existing_train)
    print(f"  negative_train: {existing_train} existing + {written} room "
          f"({len(train)} unique x {copies}, {share:.0f}%)")
    print(f"  negative_test:  +{len(test)} room")
    print(f"  held back:      {len(holdout)} clips, listed in "
          f"train/room/holdout.txt")
    print("\n  Now retrain, with --overwrite:")
    print("      python train/train_local.py --training_config "
          "train/hey_claude.yml \\")
    print("                                  --augment_clips --train_model "
          "--overwrite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
