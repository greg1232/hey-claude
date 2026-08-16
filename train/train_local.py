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
"""

import logging
import runpy
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
        runpy.run_module("openwakeword.train", run_name="__main__")
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
