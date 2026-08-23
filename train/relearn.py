"""Retrain the wake word on its own mistakes, in about a second.

The expensive part of training is turning audio into features: 159 ms per
two second window on a Pi, twenty minutes for the whole set. Fitting the
model on those features is nothing — measured on a Pi 4, a logistic
regression on 30,000 examples of 768 numbers takes 0.7 seconds.

So this never touches audio. It joins two piles of features that already
exist:

  the bank    everything train_whisper_wake.py embedded, saved beside the
              model as hey_claude_whisper.bank.npz.
  the log     every firing since, with the vector the detector scored it
              on. Those cost nothing at all — the encoder pass that made
              them is what fired the wake word in the first place.

Which is why this can run on the Pi itself, overnight, on data the Pi
collected, without a laptop being involved.

Label the log first:

    python train/label_wakes.py
    python train/relearn.py

    --dry     say what would change, write nothing
    --weight  how much to count a logged example against a bank one
"""

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import wake_log  # noqa: E402

MODEL = HERE.parent / "models" / "hey_claude_whisper.npz"


def load_bank(path: Path):
    if not path.exists():
        raise SystemExit(
            f"No feature bank at {path}.\n"
            "It's written by train/train_whisper_wake.py — run that once on "
            "a machine with the recordings, and deploy will carry it over.")
    saved = np.load(path, allow_pickle=True)
    return (saved["X"].astype(np.float32), saved["y"].astype(int),
            saved["who"].astype(str))


def load_log():
    """The labelled firings: their vectors, their labels, and their text."""
    firings = wake_log.read()
    vectors = wake_log.vectors()

    X, y, note = [], [], []
    for firing in firings:
        number = firing["n"]
        if "label" not in firing or not firing.get("has_vector"):
            continue
        if number >= len(vectors):
            continue
        X.append(vectors[number])
        y.append(int(firing["label"]))
        note.append(firing.get("window") or firing.get("heard") or "")
    if not X:
        return (np.zeros((0, wake_log.WIDTH), dtype=np.float32),
                np.zeros(0, dtype=int), [])
    return np.array(X, dtype=np.float32), np.array(y), note


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--dry", action="store_true",
                        help="report, write nothing")
    parser.add_argument("--weight", type=float, default=3.0,
                        help="how much one logged example counts against "
                             "one from the bank. Above 1 because the log is "
                             "this room, and the bank is everywhere")
    args = parser.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    bank_X, bank_y, who = load_bank(args.model.with_suffix(".bank.npz"))
    log_X, log_y, _note = load_log()

    print(f"  bank: {len(bank_X)} features "
          f"({int((bank_y == 1).sum())} wake word, "
          f"{int((bank_y == 0).sum())} not)")
    print(f"  log:  {len(log_X)} labelled firings "
          f"({int((log_y == 1).sum())} real, "
          f"{int((log_y == 0).sum())} mistakes)")

    if not len(log_X):
        raise SystemExit(
            "Nothing labelled in the log yet — run train/label_wakes.py.")

    X = np.vstack([bank_X, log_X])
    y = np.r_[bank_y, log_y]
    # Every logged example is from this room, this microphone, these
    # voices, and this television. The bank is a general model of the
    # world; the log is the actual problem. Counting the log for more is
    # the whole reason this is worth doing.
    weight = np.r_[np.ones(len(bank_X)), np.full(len(log_X), args.weight)]

    import time
    began = time.monotonic()
    scaler = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=5000, C=0.1, class_weight="balanced")
    clf.fit(scaler.transform(X), y, sample_weight=weight)
    print(f"\n  fitted {len(X)} x {X.shape[1]} in "
          f"{time.monotonic() - began:.2f}s")

    # Score the old model and the new one on the same logged firings — the
    # only data that is unambiguously about this room. Anything the old one
    # got wrong here is exactly what this exercise is for.
    old = np.load(args.model)
    before = _probability(log_X, old["mean"], old["scale"],
                          old["coef"], float(old["intercept"]))
    after = _probability(log_X, scaler.mean_, scaler.scale_,
                         clf.coef_[0], float(clf.intercept_[0]))

    print("\n  on the firings this speaker actually logged:")
    for name, p in (("before", before), ("after", after)):
        real = log_y == 1
        caught = float((p[real] >= 0.99).mean()) if real.any() else float("nan")
        fired = float((p[~real] >= 0.99).mean()) if (~real).any() else 0.0
        print(f"    {name:6s} catches {caught:5.0%} of the real ones, "
              f"and still fires on {fired:5.1%} of the mistakes")

    if args.dry:
        print("\n  --dry, so nothing written.")
        return 0

    # Keep the one that is being replaced, so a bad night can be undone.
    backup = args.model.with_suffix(".npz.previous")
    backup.write_bytes(args.model.read_bytes())

    np.savez(args.model,
             mean=scaler.mean_.astype(np.float32),
             scale=scaler.scale_.astype(np.float32),
             coef=clf.coef_[0].astype(np.float32),
             intercept=np.float32(clf.intercept_[0]),
             whisper_model=str(old["whisper_model"]),
             window_seconds=np.float32(old["window_seconds"]),
             keep_frames=np.int32(old["keep_frames"]))
    print(f"\n  wrote {args.model.name}, kept the old one as {backup.name}")
    print("  restart the speaker to pick it up:  "
          "systemctl --user restart claude-speaker")
    return 0


def _probability(X, mean, scale, coef, intercept):
    return 1.0 / (1.0 + np.exp(-(((X - mean) / scale) @ coef + intercept)))


if __name__ == "__main__":
    raise SystemExit(main())
