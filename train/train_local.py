"""Run openWakeWord's trainer on this Mac.

openWakeWord's trainer doesn't start on a modern macOS Python without two
small fixes. This wrapper applies them and then hands over to the real
trainer, so you get the genuine training code rather than a reimplementation
of it.

The two fixes:

1. `acoustics` (used for one line — generating coloured noise) imports
   `scipy.special.sph_harm`, which scipy removed in 1.17. We point that
   name at its replacement. The function it's needed for is never called;
   it just has to exist for the import to succeed.

2. The trainer imports piper-sample-generator at startup regardless of
   which stage you asked for, and that can't be installed on Apple
   Silicon. `train/stub/` satisfies the import — see the note in there.

Usage (from the project root):

    python train/train_local.py --training_config train/hey_claude.yml \
                                --augment_clips --train_model

Never pass --generate_clips: make the clips with train/generate_clips.py
instead.

**Pass --overwrite whenever the clips have changed.** --augment_clips only
rebuilds the feature files if they aren't already there, so adding or
removing clips otherwise does nothing at all: it trains on the features
from last time and prints entirely believable numbers for a model that
never saw your new data. The only sign is one line, easy to miss:

    Openwakeword features already exist, skipping data augmentation
    and feature generation

    python train/train_local.py --training_config train/hey_claude.yml \
                                --augment_clips --train_model --overwrite
"""

import collections
import json
import logging
import pathlib
import sys


def patch_scipy() -> None:
    """Give `acoustics` the scipy function it expects."""
    import scipy.special

    if hasattr(scipy.special, "sph_harm"):
        return  # Old scipy — nothing to do.

    if not hasattr(scipy.special, "sph_harm_y"):
        raise SystemExit(
            "This scipy has neither sph_harm nor sph_harm_y, so the "
            "`acoustics` package can't be imported. Try: pip install 'scipy<1.17'"
        )

    # Same maths, new name and argument order. Only ever imported, not used.
    def sph_harm(m, n, theta, phi):
        return scipy.special.sph_harm_y(n, m, phi, theta)

    scipy.special.sph_harm = sph_harm


def patch_torchaudio() -> None:
    """Put back `torchaudio.info`, which torchaudio 2.11 removed.

    `torch_audiomentations` (used to mix background noise into the clips)
    still calls it, and only wants the frame count and sample rate. Reading
    the wav header with the standard library gives exactly that.
    """
    import torchaudio

    if hasattr(torchaudio, "info"):
        return  # Older torchaudio — nothing to do.

    import wave
    from dataclasses import dataclass

    @dataclass
    class AudioMetaData:
        num_frames: int
        sample_rate: int
        num_channels: int = 1

    def info(path, *args, **kwargs):
        with wave.open(str(path), "rb") as w:
            return AudioMetaData(
                num_frames=w.getnframes(),
                sample_rate=w.getframerate(),
                num_channels=w.getnchannels(),
            )

    torchaudio.info = info


def patch_dataloader() -> None:
    """Load training batches in this process instead of worker processes.

    The trainer asks PyTorch for background worker processes. On Linux those
    are forked and inherit everything; on macOS they're spawned, which means
    the dataset class has to be pickled — and it can't be, because it's
    defined inside the trainer's own __main__:

        PicklingError: Can't pickle <class '__main__.IterDataset'>

    Loading in-process avoids that. The batches come from a memory-mapped
    file, so there's little to gain from workers here anyway.
    """
    import torch.utils.data

    original = torch.utils.data.DataLoader

    class SingleProcessDataLoader(original):
        def __init__(self, *args, **kwargs):
            kwargs["num_workers"] = 0
            kwargs.pop("prefetch_factor", None)  # Only valid with workers.
            super().__init__(*args, **kwargs)

    torch.utils.data.DataLoader = SingleProcessDataLoader


def patch_onnx_export() -> None:
    """Keep the model's weights inside the .onnx file.

    torch 2.13 defaults to `external_data=True`, which writes the weights to
    a separate `model.onnx.data` file sitting next to the model. The .onnx
    on its own is then a ~15 KB shell, and loading it fails with:

        External data path does not exist: "hey_claude.onnx.data"

    A wake word should be one self-contained file you can copy into
    models/, so we turn that off.
    """
    import torch

    original = torch.onnx.export

    def export(*args, **kwargs):
        kwargs["external_data"] = False
        return original(*args, **kwargs)

    torch.onnx.export = export


def patch_metrics(points: int = 0) -> None:
    # Each measurement runs the model over the whole false positive set, so
    # this is the dial between knowing what happened and finishing quickly.
    # EVAL_POINTS=8 is enough to check the plumbing works.
    """Measure across the whole run, and say so as it goes.

    openWakeWord validates only over the last quarter of a run:

        val_steps = np.linspace(steps - int(steps*0.25), steps, 20)

    So a 50,000 step run measures nothing until step 37,500, and there's no
    way to tell whether it converged at step 3,000 or was still climbing at
    the end. It also builds a `history` of loss, recall and false positive
    rate as it goes, and drops it when the process exits.

    This spreads validation over the whole run, prints each measurement on
    its own line so it can be followed live, and writes the history to
    train/history.json.

    Validation costs real time — each point runs the model over the whole
    false positive validation set — so this trades some training speed for
    knowing what happened.
    """
    import os

    import numpy as np
    from openwakeword import train as owt

    points = points or int(os.environ.get("EVAL_POINTS", "40"))
    train_model = owt.Model.train_model
    auto_train = owt.Model.auto_train
    init = owt.Model.__init__
    state = {"n": 0, "seq": 1, "steps": None}

    def report(history) -> None:
        state["n"] += 1
        steps = state.get("steps")
        # Which step this is, so the numbers form a curve rather than a list.
        where = (f"step {steps[state['n'] - 1]:>6d}"
                 if steps is not None and state["n"] <= len(steps)
                 else f"eval {state['n']:>3d}")

        # Only what's actually being recorded. auto_train never passes
        # positive_test_clips to train_model, so that metric stays empty and
        # printing it just puts a column of nan on the screen.
        parts = []
        for label, key, fmt in (("loss", "loss", "8.4f"),
                                ("train recall", "recall", "5.3f"),
                                ("val recall", "val_recall", "5.3f"),
                                ("fp/hr", "val_fp_per_hr", "7.2f"),
                                ("test recall", "positive_test_clips_recall",
                                 "5.3f")):
            values = history.get(key)
            if values:
                parts.append(f"{label} {values[-1]:{fmt}}")

        # A leading newline, because tqdm leaves a progress bar sitting on
        # the current line with a carriage return. Without it these land on
        # top of each other and `tail -f` never shows them.
        print(f"\n  [{state['seq']}/{where}]  " + "  ".join(parts), flush=True)

    class Watched(list):
        """A list that says something when the interesting one is appended."""

        def __init__(self, key, history):
            super().__init__()
            self._key, self._history = key, history

        def append(self, value):
            super().append(value)
            # val_n_fp is written last in the validation block, so by the
            # time it lands every other number for this step is in.
            if self._key == "val_n_fp":
                report(self._history)

    class History(collections.defaultdict):
        def __missing__(self, key):
            self[key] = Watched(key, self)
            return self[key]

    def with_history(self, *args, **kwargs):
        init(self, *args, **kwargs)
        self.history = History()

    def wide_validation(self, X, max_steps, warmup_steps, hold_steps, **kw):
        kw["val_steps"] = np.unique(
            np.linspace(max(1, int(max_steps) // points), int(max_steps),
                        points).astype(np.int64))
        # auto_train runs three sequences with different learning rates and
        # negative weights, so the step counter restarts each time and the
        # curves have to be read per sequence.
        state["seq"] = state.get("seq", 0) + 1 if state["steps"] is not None else 1
        state["n"] = 0
        state["steps"] = kw["val_steps"]
        print(f"\n  sequence {state['seq']}: {int(max_steps)} steps, "
              f"measuring at {len(kw['val_steps'])} points "
              f"(warmup {int(warmup_steps)}, hold {int(hold_steps)})",
              flush=True)
        return train_model(self, X, max_steps, warmup_steps, hold_steps, **kw)

    def keep_history(self, *args, **kwargs):
        try:
            return auto_train(self, *args, **kwargs)
        finally:
            out = pathlib.Path("train") / "history.json"
            record = {k: [float(v) for v in vs] for k, vs in self.history.items()}
            # Which checkpoint was chosen and why. Worth keeping alongside
            # the curves: the recall it reports is selected using the same
            # validation data, so it flatters itself.
            record["_selected"] = [{k: float(v) for k, v in score.items()}
                                   for score in self.best_model_scores]
            record["_val_steps"] = ([int(v) for v in state["steps"]]
                                    if state["steps"] is not None else [])
            out.write_text(json.dumps(record, indent=1))
            print(f"\n  wrote training curves to {out}", flush=True)

    owt.Model.__init__ = with_history
    owt.Model.train_model = wide_validation
    owt.Model.auto_train = keep_history


# openWakeWord keeps the last batch of predictions around to compute recall
# and false positives with — but keeps them still attached to the autograd
# graph, and only lets go when a batch large enough to trigger backward()
# comes along:
#
#     if predictions.shape[0] >= 128:
#         accumulated_predictions = predictions
#     if accumulated_samples < 128:
#         accumulated_predictions = torch.cat((accumulated_predictions,
#                                              predictions))
#
# Every step whose hard-example batch falls under 128 chains another whole
# computation graph onto that tensor. Measured here: 15.6 GB resident,
# 7.6 GB compressed and 13.7 GB of swap on a 16 GB machine, and a peak
# footprint of 29.7 GB. It's far worse for the rnn, which unrolls sixteen
# timesteps per graph, and worse again with a small batch, because a small
# batch mines fewer hard examples and so takes the accumulating branch more
# often.
#
# They're only ever read for metrics, so detaching them changes no maths.
LEAK_FIXES = (
    ("                    accumulated_predictions = predictions\n",
     "                    accumulated_predictions = predictions.detach()\n"),
    ("                    accumulated_predictions = torch.cat("
     "(accumulated_predictions, predictions))\n",
     "                    accumulated_predictions = torch.cat("
     "(accumulated_predictions, predictions.detach()))\n"),
)


def run_trainer() -> None:
    """Run openWakeWord's trainer, patched, in its own namespace.

    runpy.run_module() would re-execute the module source into a fresh
    namespace, building a second Model class that our patches never touched
    — they'd be silently ignored. Instead the source is split at its
    __main__ block: the definitions are patched and executed first, then the
    metrics instrumentation is applied to the class that produces, and only
    then is the __main__ block run in that same namespace.

    The block is indented under `if __name__ == '__main__':`. Wrapping it in
    `if True:` keeps that indentation valid; dedenting it would not, because
    some of its lines sit at column zero inside multi-line strings.
    """
    from openwakeword import train as owt

    source = pathlib.Path(owt.__file__).read_text()
    marker = "if __name__ == '__main__':"
    if marker not in source:
        raise SystemExit(
            "openWakeWord's trainer doesn't look the way this expects "
            f"(no {marker!r} in {owt.__file__}). It may have been updated.")

    head, body = source.split(marker, 1)

    for wrong, right in LEAK_FIXES:
        if wrong not in head:
            raise SystemExit(
                "openWakeWord's training loop has changed and the memory fix "
                "no longer applies. Check whether it's still needed:\n"
                f"    {wrong.strip()}")
        head = head.replace(wrong, right)

    exec(compile(head, owt.__file__, "exec"), owt.__dict__)
    patch_metrics()
    exec(compile("if True:" + body, owt.__file__, "exec"), owt.__dict__)


def main() -> None:
    if "--generate_clips" in sys.argv:
        raise SystemExit(
            "Don't use --generate_clips on a Mac — it needs piper-sample-generator,\n"
            "which can't be installed on Apple Silicon.\n\n"
            "Make the clips first:\n"
            "    python train/generate_clips.py --phrase 'hey claude' --verify\n\n"
            "then run this again with --augment_clips --train_model"
        )

    # openWakeWord reports recall, false-positive rate, and which checkpoint
    # it picked through logging.info. Without this those never print, and
    # tuning the model turns into guesswork.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    patch_scipy()
    patch_torchaudio()
    patch_dataloader()
    patch_onnx_export()

    # Hand over to openWakeWord's own trainer, which reads sys.argv itself.
    sys.argv[0] = "openwakeword.train"
    try:
        run_trainer()
    except ModuleNotFoundError as missing:
        # After saving the .onnx model, the trainer also tries to convert it
        # to TensorFlow Lite. That needs tensorflow + onnx_tf, which don't
        # install on Python 3.14 — and we don't want tflite anyway, because
        # this project loads the .onnx directly. Anything else is a real error.
        if missing.name not in ("onnx_tf", "tensorflow", "tflite_runtime"):
            raise
        print(
            f"\nSkipped the optional TensorFlow Lite conversion "
            f"(no '{missing.name}' on this machine).\n"
            "That's fine — the speaker uses the .onnx file."
        )


if __name__ == "__main__":
    main()
