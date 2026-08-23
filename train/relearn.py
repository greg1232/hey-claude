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
import contextlib
import fcntl
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import wake_log  # noqa: E402

MODEL = HERE.parent / "models" / "hey_claude_whisper.npz"

# Below this many labelled firings there is nothing to hold back, so the
# new model is taken on trust — it can only be the bank plus a handful.
LEAST_TO_JUDGE = 25
# How much worse a new model may be and still be taken, since these are
# small samples and being the same within noise is not a reason to refuse.
SLACK = 0.05
# What this machine learns for itself goes in state/, never in models/.
# models/ is mirrored by deploy, so a model written there would be replaced
# by the shipped one on the next deploy, taking every night of learning
# with it. src/whisper_wake.py looks in state/ first.
LEARNED = HERE.parent / "state" / "hey_claude_whisper.npz"
LOCK = HERE.parent / "state" / "relearn.lock"


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


def _worth_having(bank_X, bank_y, log_X, log_y, weight, old, say):
    """Would the new model be better, on firings it has not been shown?

    Comparing before and after on the very examples just fitted says only
    that the fit converged. It said 100% and 0% the first night, and the
    room went on waking the speaker every twenty seconds — because a model
    can memorise thirty-four clips of one evening's television and learn
    nothing about television.

    So a fifth of the logged firings are held back, the model is fitted
    without them, and both models are asked about them. That is the only
    number here that can say no.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    import config
    line = config.WAKE_THRESHOLD

    if len(log_X) < LEAST_TO_JUDGE:
        say(f"  only {len(log_X)} labelled — too few to judge, so taking it")
        return True, float("nan")

    rng = np.random.default_rng(0)
    held = rng.random(len(log_X)) < 0.2
    if not held.any() or held.all() or len(set(log_y[~held])) < 2:
        return True, float("nan")

    X = np.vstack([bank_X, log_X[~held]])
    y = np.r_[bank_y, log_y[~held]]
    w = np.r_[np.ones(len(bank_X)), np.full(int((~held).sum()), weight)]
    scaler = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=5000, C=0.1, class_weight="balanced")
    clf.fit(scaler.transform(X), y, sample_weight=w)

    real = log_y[held] == 1
    scores = {
        "before": _probability(log_X[held], old["mean"], old["scale"],
                               old["coef"], float(old["intercept"])),
        "after": _probability(log_X[held], scaler.mean_, scaler.scale_,
                              clf.coef_[0], float(clf.intercept_[0])),
    }
    got = {}
    say(f"  on {int(held.sum())} firings held back from the fitting:")
    for name, p in scores.items():
        caught = float((p[real] >= line).mean()) if real.any() else 1.0
        fired = float((p[~real] >= line).mean()) if (~real).any() else 0.0
        got[name] = (caught, fired)
        say(f"    {name:6s} catches {caught:5.0%} of the real ones, "
            f"and still fires on {fired:5.1%} of the mistakes")

    was, now = got["before"], got["after"]
    # Room to move, because these are small samples and a model that is
    # the same within noise is worth taking for the fresh data in it.
    better = now[0] >= was[0] - SLACK and now[1] <= was[1] + SLACK
    return better, now[0]


def refit(model: Path = MODEL, weight: float = 3.0, dry: bool = False,
          say=print, only_if_better: bool = False) -> str:
    """Fit a new model from the bank plus the log. Returns one line to speak.

    Called both from the command line and from src/enroll.py, which does
    this live while somebody stands there — so it prints its working
    through `say` and hands back a sentence rather than a report.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    bank_X, bank_y, who = load_bank(model.with_suffix(".bank.npz"))
    # Compare against whatever is actually running, which is the learned
    # one if this machine has already learned something.
    running = LEARNED if LEARNED.exists() else model
    log_X, log_y, _note = load_log()

    say(f"  bank: {len(bank_X)} features "
          f"({int((bank_y == 1).sum())} wake word, "
          f"{int((bank_y == 0).sum())} not)")
    say(f"  log:  {len(log_X)} labelled firings "
          f"({int((log_y == 1).sum())} real, "
          f"{int((log_y == 0).sum())} mistakes)")

    if not len(log_X):
        return "There's nothing labelled to learn from yet."

    X = np.vstack([bank_X, log_X])
    y = np.r_[bank_y, log_y]
    # Every logged example is from this room, this microphone, these
    # voices, and this television. The bank is a general model of the
    # world; the log is the actual problem. Counting the log for more is
    # the whole reason this is worth doing.
    weights = np.r_[np.ones(len(bank_X)), np.full(len(log_X), weight)]

    import time
    began = time.monotonic()
    scaler = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=5000, C=0.1, class_weight="balanced")
    clf.fit(scaler.transform(X), y, sample_weight=weights)
    say(f"  fitted {len(X)} x {X.shape[1]} in "
        f"{time.monotonic() - began:.2f}s")

    old = np.load(running)
    better, caught_after = _worth_having(
        bank_X, bank_y, log_X, log_y, weight, old, say)

    if dry:
        say("  --dry, so nothing written.")
        return "Nothing written."

    if only_if_better and not better:
        say("  not an improvement — keeping the model that's running.")
        return "I had a look and the one I have is still better."

    # Keep the one that is being replaced, so a bad night can be undone.
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    backup = LEARNED.with_suffix(".npz.previous")
    if LEARNED.exists():
        backup.write_bytes(LEARNED.read_bytes())

    np.savez(LEARNED,
             mean=scaler.mean_.astype(np.float32),
             scale=scaler.scale_.astype(np.float32),
             coef=clf.coef_[0].astype(np.float32),
             intercept=np.float32(clf.intercept_[0]),
             whisper_model=str(old["whisper_model"]),
             window_seconds=np.float32(old["window_seconds"]),
             keep_frames=np.int32(old["keep_frames"]))
    say(f"  wrote {LEARNED}")
    return (f"Learned from {len(log_X)} examples. "
            f"I now catch {caught_after:.0%} of the ones I have on file.")


def nightly(say=print) -> int:
    """Label whatever the day produced, refit, and keep it only if better.

    Run by a systemd timer on the Pi at four in the morning. Everything it
    needs is already on the machine: the vectors were computed when the
    wake word fired, and the labels come from what happened next.

    Labelling here never calls Claude. The free signals do most of the
    work — a firing followed by silence is a mistake, one followed by a
    question that got answered is real — and a nightly job that needs the
    network and costs money is a nightly job that fails quietly for a
    month.
    """
    import subprocess
    import sys as _sys

    with _only_one():
        say("Labelling what today produced...")
        # Not captured. This is the slow part — on a Pi it is seconds per
        # clip — and hiding its output made a job that was working look
        # exactly like a job that had hung.
        #
        # And no wake windows: transcribing them is the whole cost, and
        # measured against eighty real recordings tiny.en writes down the
        # wake word about one time in six. What came next does the work.
        done = subprocess.run(
            [_sys.executable, "-u", str(HERE / "label_wakes.py"),
             "--no-claude", "--windows", "0"])
        if done.returncode != 0:
            say(f"  labelling gave up ({done.returncode})")

        say("\nRefitting...")
        said = refit(say=say, only_if_better=True)
        say("\n" + said)

        if "still better" in said or "othing" in said:
            return 0

        # Only worth restarting if something was actually written.
        say("\nRestarting the speaker to pick it up...")
        subprocess.run(["systemctl", "--user", "restart", "claude-speaker"],
                       capture_output=True)
    return 0


@contextlib.contextmanager
def _only_one():
    """Refuse to run twice at once.

    Two of these overlapped and spent twenty minutes fighting each other
    and the speaker for the processor, which on four cores is felt. The
    timer fires nightly and a person can ask for it at any moment, so
    overlapping is ordinary rather than exotic.
    """
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("Already learning — leaving that one to it.")
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


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
    parser.add_argument("--nightly", action="store_true",
                        help="label, refit, keep only if better, restart. "
                             "What the timer runs at four in the morning")
    parser.add_argument("--only-if-better", action="store_true",
                        help="keep the running model unless the new one "
                             "wins on firings held back from the fitting")
    args = parser.parse_args()

    if args.nightly:
        return nightly()

    print(refit(args.model, args.weight, args.dry,
                only_if_better=args.only_if_better))
    if not args.dry:
        print("  restart the speaker to pick it up:  "
              "systemctl --user restart claude-speaker")
    return 0


def _probability(X, mean, scale, coef, intercept):
    return 1.0 / (1.0 + np.exp(-(((X - mean) / scale) @ coef + intercept)))


if __name__ == "__main__":
    raise SystemExit(main())
