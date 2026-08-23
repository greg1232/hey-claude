"""Score a wake word on data it was never trained on.

The trainer's own numbers can't be taken at face value. It picks the
checkpoint with the best recall among those meeting a false-positive
target, measured on the validation set — and then reports that same
number. That's selection on the test set, so the recall it prints is a
best-of statistic rather than an estimate of anything.

This measures four things independently:

  held-out real   recordings of real people, split by person, that the
                  model never saw in training or in checkpoint selection.
                  The number that matters.
  all real        every real recording, for comparison. Inflated, because
                  most of these were trained on — the gap between this and
                  held-out real is how much the model memorised.
  synthetic       the generated test clips, showing whether adding real
                  speech cost anything on the voices it used to handle.
  false positives the validation features, as wakes per hour.

    python train/evaluate.py models/hey_claude.onnx
    python train/evaluate.py train/hey_claude.onnx --compare models/hey_claude.onnx

A fresh Model is built for every clip. openWakeWord is a streaming
detector and reset() does not clear its audio buffer, so a model reused
across clips carries the previous one into the next and quietly corrupts
every score after the first.
"""

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

REAL = HERE / "real" / "hey_claude"
ROOM = HERE / "room"
CLIPS = HERE / "hey_claude"
# openWakeWord's own false-positive validation set, and how long it is.
FP_FEATURES = HERE / "data" / "validation_set_features.npy"
FP_HOURS = 11.3


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def clip_score(model_path: str, audio: np.ndarray) -> float:
    from openwakeword.model import Model

    model = Model(wakeword_models=[model_path], inference_framework="onnx")
    stream = np.concatenate([np.zeros(16000, np.int16), audio,
                             np.zeros(8000, np.int16)])
    best = 0.0
    for i in range(0, len(stream) - 1280, 1280):
        best = max(best, max(model.predict(stream[i:i + 1280]).values()))
    return best


def score_clips(model_path: str, paths: list[Path]) -> np.ndarray:
    return np.array([clip_score(model_path, load_wav(p)) for p in paths])


def false_positives_per_hour(model_path: str, threshold: float) -> float | None:
    """Wakes per hour on openWakeWord's validation audio.

    This runs the wake head over precomputed features rather than audio, so
    it's fast — but it's the same data the trainer selects checkpoints on,
    which is why it's reported alongside the real-microphone silence test
    rather than instead of it.
    """
    if not FP_FEATURES.is_file():
        return None
    import onnxruntime as ort

    features = np.load(FP_FEATURES, mmap_mode="r")
    session = ort.InferenceSession(model_path,
                                   providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    shape = session.get_inputs()[0].shape
    window = shape[1] if isinstance(shape[1], int) else 16

    # The exported model fixes its batch dimension at 1, so windows go
    # through one at a time. That sounds slow and isn't: the wake head is
    # tiny, about 8 microseconds a window, so the whole validation set takes
    # a few seconds and there's no reason to subsample it.
    wakes = 0
    for start in range(0, len(features) - window):
        block = np.array(features[start:start + window],
                         dtype=np.float32)[None, :, :]
        if session.run(None, {name: block})[0][0][0] >= threshold:
            wakes += 1
    return wakes / FP_HOURS


def report(model_path: str, threshold: float) -> dict:
    holdout_file = HERE / "real" / "holdout.txt"
    held_names = set()
    if holdout_file.is_file():
        held_names = {n.strip() for n in holdout_file.read_text().split() if n.strip()}

    all_real = sorted(REAL.glob("*.wav")) if REAL.is_dir() else []
    held = [p for p in all_real if p.name in held_names]
    synthetic = sorted((CLIPS / "positive_test").glob("*.wav"))
    # The real clips copied into positive_test aren't synthetic.
    synthetic = [p for p in synthetic if not p.name.startswith("real-")]

    print(f"\n  {Path(model_path).name}   (threshold {threshold})")
    print(f"  {'set':16s} {'n':>4s} {'median':>7s} {'wake rate':>10s}")

    # Every real clip is scored once and the results reused, because
    # building a fresh Model per clip is the slow part.
    by_clip = {p: s for p, s in zip(all_real, score_clips(model_path, all_real))}

    results = {}
    for label, paths in (("held-out real", held),
                         ("all real", all_real),
                         ("synthetic", synthetic[:100])):
        if not paths:
            print(f"  {label:16s}    -        -          -")
            continue
        scores = (np.array([by_clip[p] for p in paths]) if paths[0] in by_clip
                  else score_clips(model_path, paths))
        rate = float((scores >= threshold).mean())
        results[label] = rate
        print(f"  {label:16s} {len(paths):4d} {np.median(scores):7.3f} "
              f"{rate:9.0%}")

    # Per person, because an average hides a person it can't hear at all.
    if all_real:
        print(f"\n  {'person':10s} {'n':>4s} {'median':>7s} {'wake rate':>10s}")
        for who in sorted({p.name.split("-")[0] for p in all_real}):
            scores = np.array([by_clip[p] for p in all_real
                               if p.name.startswith(f"{who}-")])
            print(f"  {who:10s} {len(scores):4d} {np.median(scores):7.3f} "
                  f"{float((scores >= threshold).mean()):9.0%}")

    fp = false_positives_per_hour(model_path, threshold)
    if fp is not None:
        print(f"\n  false positives: {fp:.2f} per hour on the validation set")
        results["fp_per_hour"] = fp
    return results


def room_wake_rate(model_path: str, thresholds: list[float]) -> dict | None:
    """False wakes per hour on held-out recordings of the real room.

    This replaces measuring against openWakeWord's validation features,
    which turned out to predict nothing useful. That corpus said 0.53 false
    wakes an hour for a model that produced about 180 an hour on the actual
    device — wrong by a factor of 340, because the array's automatic gain
    makes "silence" through it loud, busy audio that looks nothing like
    somebody else's recordings.

    The clips are streamed in 80 ms chunks through one continuous model,
    exactly as wake.py does it, rather than scored one at a time. A wake
    word is a streaming detector and its buffer carries across chunks;
    scoring clips in isolation measures something the device never does.
    """
    holdout_file = ROOM / "holdout.txt"
    if not holdout_file.is_file():
        return None
    names = {n.strip() for n in holdout_file.read_text().split() if n.strip()}
    paths = sorted(p for p in ROOM.glob("*.wav") if p.name in names)
    if not paths:
        return None

    from openwakeword.model import Model

    model = Model(wakeword_models=[model_path], inference_framework="onnx")
    scores, chunks = [], 0
    for path in paths:
        audio = load_wav(path)
        for i in range(0, len(audio) - 1280, 1280):
            scores.append(max(model.predict(audio[i:i + 1280]).values()))
            chunks += 1
    scores = np.array(scores)
    hours = chunks * 1280 / 16000 / 3600
    return {t: float((scores >= t).sum()) / hours for t in thresholds}


def sweep(model_path: str) -> None:
    """Recall against false wakes, across every threshold.

    One number at one threshold hides the choice being made. A model can
    look unusable at 0.5 and be fine at 0.9 — and after training on real
    speech the scores sit near 1.0, so there's room to move that nobody had
    when real clips were scoring 0.001.

    Everything is scored once and then compared against each threshold, so
    the whole curve costs no more than a single evaluation.
    """
    # Fine-grained at the top, because that's where a usable wake word
    # actually lives: everything below 0.99 has been far too trigger-happy
    # on real room audio, so the interesting choices are all in the last
    # half a percent.
    thresholds = [0.5, 0.9, 0.95, 0.98, 0.99, 0.995, 0.997, 0.998,
                  0.999, 0.9995]

    all_real = sorted(REAL.glob("*.wav")) if REAL.is_dir() else []
    if not all_real:
        print("  no real recordings to sweep against")
        return
    clip = score_clips(model_path, all_real)
    room = room_wake_rate(model_path, thresholds)

    print(f"\n  {Path(model_path).name} — where to set WAKE_THRESHOLD")
    if room is None:
        print("  (no held-out room audio — record some with "
              "train/record_room.py)")
    print(f"  {'threshold':>9s} {'real recall':>12s} {'room wakes/hr':>15s}")
    for t in thresholds:
        rate = f"{room[t]:15.2f}" if room else f"{'-':>15s}"
        print(f"  {t:9.3f} {float((clip >= t).mean()):11.0%} {rate}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("--sweep", action="store_true",
                        help="show recall against false wakes at every threshold")
    parser.add_argument("--compare", default=None,
                        help="a second model to score the same way")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    import openwakeword.utils
    openwakeword.utils.download_models(model_names=[])

    if args.sweep:
        sweep(args.model)
        if args.compare:
            sweep(args.compare)
        return 0

    report(args.model, args.threshold)
    if args.compare:
        report(args.compare, args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
