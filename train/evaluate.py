"""Measure the wake word honestly, on data the model being measured never saw.

    python train/evaluate.py

Every number this project has printed so far comes from `relearn.py`, whose
job is to decide whether to promote a model — not to say how good one is.
It compares a candidate against whatever is installed, and the installed
one was fitted on everything available at the time, so it is being asked
about its own training data. That is why it keeps reporting 100% recall and
0% false wakes, which is memory rather than skill.

This answers a different question: **how well does this recipe work on
firings it has never seen?** Two ways, both leak-free.

  before learning   The shipped model, fitted only on the recorded corpus
                    in train/, scored on everything from this room. It has
                    genuinely never seen any of it. This is the baseline —
                    what you get with no learning from the room at all.

  after learning    Five-fold cross-validation. The log is cut into five;
                    a model is fitted on the bank, the machine labels, and
                    four fifths of what a person vouched for, then scored
                    on the fifth it did not see. Five models, five
                    disjoint test sets, pooled into one curve. No model is
                    ever asked about its own training data.

Ground truth is what a person can vouch for: clips somebody listened to
and labelled, and enrolment recordings, where somebody said the wake word
on purpose. The augmented copies of enrolment recordings are allowed in
training and never in a test set — scoring a model on variants of its own
training data is the thing this file exists to avoid.

The two kinds of positive are reported apart. Enrolment is deliberate,
clear and close; somebody calling across a room is not, and averaging them
hides the difference that matters.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import relearn  # noqa: E402

SHIPPED = HERE.parent / "models" / "hey_claude_whisper.npz"
LINES = (0.30, 0.50, 0.70, 0.80, 0.90, 0.95, 0.975, 0.99)
FOLDS = 5


def fit(X, y, weights):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(X)
    model = LogisticRegression(max_iter=5000, C=0.1, class_weight="balanced")
    model.fit(scaler.transform(X), y, sample_weight=weights)
    return scaler, model


def score(scaler, model, X):
    return model.predict_proba(scaler.transform(X))[:, 1]


def table(name, p, real, said, taught, mistakes, say):
    say(f"\n  {name}")
    say(f"  {'line':>6}{'catches':>9}{'false':>7}{'said to it':>12}"
        f"{'taught':>8}")
    for line in LINES:
        each = [np.mean(p[m] >= line) if m.any() else float("nan")
                for m in (real, mistakes, said, taught)]
        say(f"  {line:6.3f}{each[0]:9.0%}{each[1]:7.1%}{each[2]:12.0%}"
            f"{each[3]:8.0%}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folds", type=int, default=FOLDS)
    args = parser.parse_args()
    say = print

    bank_X, bank_y, _who = relearn.load_bank(
        SHIPPED.with_suffix(".bank.npz"))
    X, y, kind, _when = relearn.load_log()

    # What can be tested on, and what can only be trained on.
    vouched = np.isin(kind, ("person", "enrolled"))
    if not vouched.any():
        raise SystemExit("Nothing a person has vouched for yet — "
                         "run ./label.sh first.")

    real = vouched & (y == 1)
    said = (kind == "person") & (y == 1)
    taught = (kind == "enrolled") & (y == 1)
    mistakes = vouched & (y == 0)
    say(f"  ground truth: {int(real.sum())} real "
        f"({int(said.sum())} said to it, {int(taught.sum())} taught), "
        f"{int(mistakes.sum())} mistakes")
    say(f"  training material: {len(bank_X)} recorded, "
        f"{int((~vouched).sum())} logged and labelled by machine")

    # --- the baseline, which has seen none of this ------------------------
    shipped = np.load(SHIPPED)
    p = relearn._probability(X, shipped["mean"], shipped["scale"],
                             shipped["coef"], float(shipped["intercept"]))
    table("before learning — the shipped model, which has seen none of this",
          p, real, said, taught, mistakes, say)

    # --- and the recipe, cross-validated ----------------------------------
    rng = np.random.default_rng(0)
    where = np.flatnonzero(vouched)
    fold = np.zeros(len(X), dtype=int) - 1
    # Split each class separately, so every fold has some of both.
    for label in (0, 1):
        rows = where[y[where] == label]
        rows = rows[rng.permutation(len(rows))]
        fold[rows] = np.arange(len(rows)) % args.folds

    out = np.zeros(len(X))
    for number in range(args.folds):
        train = (fold != number)          # everything not in this fold,
        test = (fold == number)           # including all the machine labels
        weights = np.r_[
            np.ones(len(bank_X)),
            np.where(np.isin(kind[train], ("person", "enrolled")),
                     3.0 * relearn.BY_PERSON, 3.0)]
        scaler, model = fit(np.vstack([bank_X, X[train]]),
                            np.r_[bank_y, y[train]], weights)
        out[test] = score(scaler, model, X[test])
        say(f"    fold {number + 1}/{args.folds}: fitted on "
            f"{len(bank_X) + int(train.sum())}, tested on {int(test.sum())}")

    table(f"after learning — {args.folds}-fold, each row scored by a model "
          "that never saw it", out, real, said, taught, mistakes, say)

    say("\n  The two columns on the right are the same rows split by where "
        "they came from.")
    say("  Enrolment is deliberate and close; being called across a room "
        "is not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
