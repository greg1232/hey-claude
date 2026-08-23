"""Show what happened during training.

Reads train/history.json, written by train_local.py.

    python train/show_history.py

Loss and training recall are recorded every step, so those come at full
resolution for free. Validation is only run at a few points, because each
one puts the model over the whole false positive set.

What to look for:

  recall flat at zero      the run is too short — the schedule never got
                           anywhere. A 2000 step budget does this.
  val recall plateaus      it has converged; steps beyond that are wasted
                           and can be cut.
  train recall climbing
  while val recall falls   overfitting; the answer is fewer steps, not more.
  loss rising late         usually not a fault. max_negative_weight ramps
                           across each sequence and rises again between
                           them, so identical mistakes cost more over time.
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BARS = " ▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 60) -> str:
    """A rough shape of a series, in one line of text."""
    if not values:
        return ""
    # Average within buckets rather than sampling, so a spike between two
    # sampled points doesn't vanish.
    step = max(1, len(values) / width)
    buckets = []
    for i in range(min(width, len(values))):
        chunk = values[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]
        if chunk:
            buckets.append(sum(chunk) / len(chunk))
    low, high = min(buckets), max(buckets)
    if high == low:
        return BARS[0] * len(buckets)
    return "".join(
        BARS[min(len(BARS) - 1, int((v - low) / (high - low) * (len(BARS) - 1)))]
        for v in buckets)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=HERE / "history.json")
    args = parser.parse_args()

    if not args.file.is_file():
        raise SystemExit(
            f"No {args.file}. Train something first:\n"
            "    python train/train_local.py --training_config "
            "train/hey_claude.yml --augment_clips --train_model --overwrite")

    history = json.loads(args.file.read_text())

    print(f"\n  every step ({len(history.get('loss', []))} of them)")
    for key, label in (("loss", "loss"), ("recall", "train recall")):
        values = history.get(key)
        if values:
            print(f"    {label:14s} {sparkline(values)}  "
                  f"{values[0]:.3f} -> {values[-1]:.3f}"
                  f"   (min {min(values):.3f}, max {max(values):.3f})")

    val_recall = history.get("val_recall") or []
    if val_recall:
        steps = history.get("_val_steps") or []
        print(f"\n  at each validation point ({len(val_recall)})")
        print(f"    {'#':>3s} {'step':>7s} {'val recall':>11s} "
              f"{'fp/hr':>8s} {'accuracy':>9s}")
        for i, recall in enumerate(val_recall):
            at = f"{steps[i]:7d}" if i < len(steps) else f"{'-':>7s}"
            fp = (history.get("val_fp_per_hr") or [float('nan')] * len(val_recall))[i]
            acc = (history.get("val_accuracy") or [float('nan')] * len(val_recall))[i]
            print(f"    {i + 1:3d} {at} {recall:11.3f} {fp:8.2f} {acc:9.3f}")

        best = max(range(len(val_recall)), key=lambda i: val_recall[i])
        print(f"\n    best val recall {val_recall[best]:.3f} at point {best + 1}"
              f" of {len(val_recall)}")
        if max(val_recall) == 0:
            # Say this instead of "peaked early": with every value at zero
            # the best point is just the first one, which means nothing.
            print("    Never learned anything. The run is too short, or the "
                  "data is wrong.")
        elif best < len(val_recall) * 0.6:
            print("    It peaked early — the later steps aren't earning their "
                  "time, and may be costing accuracy.")

    selected = history.get("_selected") or []
    if selected:
        print(f"\n  {len(selected)} checkpoints kept. The trainer picks among "
              "these by recall,")
        print("  subject to a false positive target measured on the same "
              "validation data —")
        print("  so whatever it reports is a best-of, not an estimate. Use "
              "train/evaluate.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
