"""A stand-in for piper-sample-generator, so training runs on a Mac.

openWakeWord's trainer imports `generate_samples` at startup, before it
looks at which stage you asked for:

    sys.path.insert(0, os.path.abspath(config["piper_sample_generator_path"]))
    from generate_samples import generate_samples

That import pulls in `piper-phonemize`, which has no build for macOS on
Apple Silicon — so the trainer won't even start here, no matter which flags
you pass.

We don't need it: `train/generate_clips.py` already made the clips using
piper-tts. This file just satisfies the import. It is never called, because
we never pass --generate_clips.
"""


def generate_samples(*args, **kwargs):
    raise RuntimeError(
        "generate_samples() was called, but this is only a stub.\n"
        "Make the clips first with:\n"
        "    python train/generate_clips.py --phrase 'hey claude' --verify\n"
        "then run the trainer WITHOUT the --generate_clips flag."
    )
