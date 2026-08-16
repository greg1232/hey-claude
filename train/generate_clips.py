"""Make the training clips locally, on this laptop.

openWakeWord's own trainer generates its clips with `piper-sample-generator`,
which needs `piper-phonemize` — and that has no build at all for macOS on
Apple Silicon. This script does the same job with `piper-tts`, which does
work here, so the whole thing runs on the Mac with no GPU and no Colab.

It writes four folders of 16 kHz mono .wav clips, exactly where
openWakeWord's trainer looks for them:

    <out>/positive_train/   thousands of voices saying "hey claude"
    <out>/positive_test/    more of the same, held back for scoring
    <out>/negative_train/   voices saying similar-but-wrong phrases
    <out>/negative_test/    more of those, held back

Every clip varies the speaker, the speed, and the amount of expression, so
the model hears the phrase many different ways instead of one voice over
and over.

    python train/generate_clips.py --phrase "hey claude" --out train/clips

Run with --count 50 first to check it sounds right, then again with the
real number.
"""

import argparse
import os
import random
import sys
import uuid
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

TARGET_RATE = 16_000  # What openWakeWord works in.

# Spread across several corpora, not just several speakers. A model trained
# on one voice collection learns that collection's particular sound and then
# misses real speech that doesn't match it — an early attempt at this scored
# 100% on held-back Piper clips but woke for only one of five macOS `say`
# voices. Different corpora were recorded and vocoded differently, and that
# is the variety that matters.
#
# The percentages are measured pass rates for "hey claude": how often
# --verify agrees the voice really said it. Some Piper voices sit near zero
# (en_US-l2arctic 0%, en_GB-aru 0%, en_US-arctic 8%,
# en_GB-northern_english_male 12%) and are deliberately absent, because they
# burn many synthesis attempts per usable clip. Measure a new one with
# train/voice_audit.py before adding it here.
DEFAULT_VOICES = [
    "en_US-libritts_r-medium",      # ~904 speakers, 92%
    "en_GB-vctk-medium",            # 109 speakers, British, 52%
    "en_GB-semaine-medium",         # 4 speakers, 76%
    "en_US-ryan-high",              # 100%
    "en_GB-alba-medium",            # 96%
    "en_US-amy-medium",             # 92%
    "en_GB-cori-medium",            # 84%
    "en_US-hfc_male-medium",        # 80%
    "en_US-lessac-medium",          # 76%
    "en_US-hfc_female-medium",      # 72%
    "en_US-kristin-medium",         # 72%
]

# Wrong phrases that sound close to the real one. Teaching the model to say
# "no" to these is what stops it waking up on ordinary conversation.
#
# The vowel is what matters. "Claude" and "Clyde" differ in exactly one
# sound, and a first attempt at this model fired on "hey clyde" at 0.999 —
# just as hard as on the real phrase. So this list leans heavily on the
# neighbouring vowels rather than spreading evenly over unrelated words.
DEFAULT_NEGATIVES = [
    # The dangerous ones: "hey" plus a near-miss of "claude".
    #
    # Nothing here may be a homophone of the wake word. "clawed" sounds
    # exactly like "Claude", so it is deliberately absent — see
    # drop_homophones(), which enforces this.
    "hey clyde", "hey cloud", "hey claire", "hey chloe", "hey claudia",
    "hey glaude", "hey claus", "hey close", "hey clay", "hey cod",
    "hey caught", "hey cool", "hey call", "hey clued", "hey glide",
    "hey slide", "hey plowed", "hey crowd", "hey proud", "hey allowed",
    "hey aloud", "hey applaud", "hey flawed", "hey gnawed", "hey thawed",
    "hey sawed", "hey lord", "hey chord", "hey cord", "hey clouds",
    "hey glad", "hey clad", "hey cloth", "hey club", "hey clock",
    "hey code", "hey card", "hey guard", "hey clip", "hey cliff",
    # The same near-misses without "hey", so the model doesn't learn that
    # "hey" alone is the trigger.
    "a cloud", "play loud", "okay cloud", "make it loud", "say cloud",
    "the crowd", "how loud", "way out", "grey cloud", "the clouds are grey",
    "she applauded loudly", "that was a loud noise", "clyde went home",
    "out loud", "so proud", "get out", "no doubt", "big crowd",
    "storm clouds", "black cloud", "loud and clear", "cloudy today",
]


# The near-misses that actually fooled a trained model, plus the ones a
# vowel apart from the wake word. Spreading clips evenly over every negative
# gives each of these only a few dozen examples — not enough to teach a
# one-vowel distinction — so these get a much larger share. "hey clyde"
# (K-L-AY-D against Claude's K-L-AO-D) scored 0.998 before this existed.
HARD_NEGATIVES = [
    "hey clyde", "hey cloud", "hey claus", "hey clay", "hey clued",
    "hey close", "hey glaude", "hey chloe", "hey claire", "hey cod",
    "hey caught", "hey call", "hey cord", "hey clock", "hey code",
]

# How many clips each kind of negative gets, relative to the others.
HARD_SHARE = 8         # the confusable ones above
CURATED_SHARE = 3      # the rest of the hand-written list
ADVERSARIAL_SHARE = 1  # auto-generated, mostly unrelated word salad


def weight_negatives(curated: list[str], adversarial: list[str]) -> list[str]:
    """Build a pool where confusable phrases appear proportionally more.

    generate() deals texts out round-robin, so repeating an entry here is
    what gives it a bigger share of the clips.
    """
    pool: list[str] = []
    for text in curated:
        pool += [text] * (HARD_SHARE if text in HARD_NEGATIVES
                          else CURATED_SHARE)
    pool += [t for t in adversarial for _ in range(ADVERSARIAL_SHARE)]
    return pool


def phonemes(text: str) -> list[str] | None:
    """The sounds in `text`, or None if a word isn't in the dictionary."""
    import pronouncing

    out = []
    for word in text.lower().replace("'", "").split():
        options = pronouncing.phones_for_word(word)
        if not options:
            return None
        # Strip the stress digits — "AO1" and "AO0" are the same sound.
        out += [p.rstrip("012") for p in options[0].split()]
    return out


def drop_homophones(phrase: str, negatives: list[str]) -> list[str]:
    """Remove negatives that contain the wake word's exact sounds.

    "Claude" and "clawed" are both K-L-AO-D. Asking the model to treat one
    as the wake word and the other as a rejection is asking it to tell apart
    identical audio — it can't, so it sacrifices the wake word trying, and
    recall collapses. openWakeWord's own adversarial-phrase generator
    excludes homophones for this reason; a hand-written list has to do the
    same.
    """
    # Check the whole phrase, and also its last word on its own — that's the
    # distinctive part. "they clawed" doesn't match "hey claude" outright
    # (DH vs HH), but its "clawed" is still identical to "Claude".
    targets = [t for t in (phonemes(phrase), phonemes(phrase.split()[-1]))
               if t is not None]
    if not targets:
        return negatives

    def contains(sounds: list[str], target: list[str]) -> bool:
        n = len(target)
        return any(sounds[i:i + n] == target for i in range(len(sounds) - n + 1))

    kept, dropped = [], []
    for text in negatives:
        sounds = phonemes(text)
        # Unknown words can't be checked — keep them and hope.
        if sounds is None:
            kept.append(text)
            continue
        if any(contains(sounds, t) for t in targets):
            dropped.append(text)
        else:
            kept.append(text)

    if dropped:
        print(f"  dropped {len(dropped)} homophone(s) of {phrase!r}: "
              f"{', '.join(dropped)}")
    return kept


def adversarial_texts(phrase: str, count: int) -> list[str]:
    """Ask openWakeWord for phrases that rhyme with the wake word.

    It builds these from phoneme overlap using the CMU pronouncing
    dictionary, so it finds near-misses a person wouldn't think of. The
    output is a mixed bag — some are genuine near-misses, some are unrelated
    word salad — but both are useful as "not the wake word".
    """
    # openWakeWord imports `acoustics`, which imports a scipy function that
    # was removed in scipy 1.17. Same shim as train_local.py uses.
    import scipy.special as sp
    if not hasattr(sp, "sph_harm"):
        sp.sph_harm = lambda m, n, theta, phi: sp.sph_harm_y(n, m, phi, theta)

    from openwakeword.data import generate_adversarial_texts

    texts = generate_adversarial_texts(
        phrase, count, include_partial_phrase=0.3, include_input_words=0.3
    )
    # Drop anything that is just the wake phrase again.
    unique = sorted({t for t in texts if t.strip().lower() != phrase.lower()})
    print(f"  generated {len(unique)} extra near-misses "
          f"(e.g. {', '.join(unique[:3])})")
    return unique


def load_voices(names: list[str], download_dir: Path, quiet: bool = False) -> list:
    """Load the Piper voices, downloading them the first time."""
    from piper import PiperVoice
    from piper.download_voices import download_voice

    download_dir.mkdir(parents=True, exist_ok=True)
    voices = []
    for name in names:
        path = download_dir / f"{name}.onnx"
        if not path.exists():
            print(f"  downloading voice {name} (once)...")
            download_voice(name, download_dir)
        voice = PiperVoice.load(path)
        speakers = voice.config.num_speakers
        if not quiet:
            print(f"  {name}: {speakers} speaker{'s' if speakers != 1 else ''}")
        voices.append(voice)
    return voices


def write_wav(path: Path, audio: np.ndarray) -> None:
    """Save 16 kHz mono audio."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes(audio.astype(np.int16).tobytes())


def synthesize(voice, text: str, rng: random.Random) -> np.ndarray:
    """Say `text` once, in a randomly varied voice. Returns 16 kHz audio."""
    from piper import SynthesisConfig

    speakers = voice.config.num_speakers
    settings = SynthesisConfig(
        speaker_id=rng.randrange(speakers) if speakers > 1 else None,
        # Speed. Below 1 is faster, above 1 is slower. This is the setting
        # openWakeWord's own pipeline varies, and the main source of useful
        # variety.
        length_scale=rng.uniform(0.75, 1.25),
        # How much the voice wobbles. openWakeWord pins both of these at
        # 0.98 — turning them down makes some speakers slur the phrase into
        # something else, so only jitter them slightly.
        noise_scale=rng.uniform(0.9, 1.0),
        noise_w_scale=rng.uniform(0.9, 1.0),
    )

    chunks = [c.audio_int16_array for c in voice.synthesize(text, settings)]
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)

    # Piper voices come out at 22.05 kHz; openWakeWord wants 16 kHz.
    source_rate = voice.config.sample_rate
    if source_rate != TARGET_RATE:
        audio = resample_poly(audio.astype(np.float32), TARGET_RATE, source_rate)
        audio = np.clip(audio, -32768, 32767)

    return audio


def make_checker(phrase: str, model_name: str = "base.en", quiet: bool = False):
    """Build a function that checks a clip really says the phrase.

    Some of the ~900 libritts_r speakers are low quality and slur "hey
    claude" into "hate cloud" or "he clogged". Those are mislabelled
    training data — they teach the model the wrong sound — so it's worth
    throwing them away. We already have Whisper on this laptop, so we can
    just listen to each clip and check.

    This is the slowest part of making clips. `tiny.en` is roughly twice as
    fast as `base.en`, but mishears more often, so it throws away good
    clips and has to make replacements — which eats into the saving.
    """
    from faster_whisper import WhisperModel

    if not quiet:
        print(f"  (checking clips with Whisper {model_name})")
    # One thread per model: the parallelism comes from running several
    # worker processes, and letting each spawn threads too would oversubscribe
    # the CPU and end up slower.
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=1)

    # Match on the last word, which is the distinctive part, and allow just
    # the first few letters so "claude"/"claud" both pass.
    key = phrase.split()[-1].lower()[:4]

    def says_it(audio: np.ndarray) -> bool:
        quiet = audio.astype(np.float32) / 32768.0
        # No VAD filter: these clips are already short and tightly cropped,
        # and the filter costs more time than it saves here.
        segments, _ = model.transcribe(quiet, language="en", beam_size=1,
                                       vad_filter=False)
        heard = " ".join(s.text for s in segments).lower()
        return key in heard

    return says_it


# Set up once per worker process by _worker_init, because neither a Piper
# voice nor a Whisper model can be pickled and sent to a worker.
_WORKER: dict = {}


def _worker_init(voice_names: list[str], voice_dir: str,
                 verify_model: str | None, phrase: str) -> None:
    _WORKER["voices"] = load_voices(voice_names, Path(voice_dir), quiet=True)
    _WORKER["checker"] = (make_checker(phrase, verify_model, quiet=True)
                          if verify_model else None)


def _worker_make(job: tuple[int, list[str], str]) -> tuple[int, int]:
    """Make a batch of clips. Returns (made, rejected)."""
    seed, texts, out_dir = job
    rng = random.Random(seed)
    voices, checker = _WORKER["voices"], _WORKER["checker"]

    made = rejected = 0
    attempts = 0
    max_attempts = len(texts) * 5

    for i, text in enumerate(texts):
        while attempts < max_attempts:
            attempts += 1
            audio = synthesize(rng.choice(voices), text, rng)
            if checker is not None and not checker(audio):
                rejected += 1
                continue
            write_wav(Path(out_dir) / f"{uuid.uuid4().hex}.wav", audio)
            made += 1
            break
    return made, rejected


def generate(voice_names: list[str], voice_dir: Path, texts: list[str],
             count: int, out_dir: Path, seed: int,
             verify_model: str | None = None, workers: int = 1) -> None:
    """Fill `out_dir` with `count` clips, cycling through the phrases.

    Synthesis and the Whisper check are independent per clip, so this splits
    the work across processes. The check is by far the slow part — about
    2.4 seconds a clip against 0.06 for synthesis alone — so verified runs
    are the ones that benefit.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = len(list(out_dir.glob("*.wav")))
    if existing >= count:
        print(f"  {out_dir.name}: already has {existing} clips, skipping")
        return

    todo = count - existing
    print(f"  {out_dir.name}: making {todo} clips"
          f"{f' across {workers} processes' if workers > 1 else ''}...")

    # Deal the phrases out round-robin so every worker gets a mix.
    assignments: list[list[str]] = [[] for _ in range(workers)]
    for i in range(todo):
        assignments[i % workers].append(texts[i % len(texts)])
    jobs = [(seed + w, assignments[w], str(out_dir)) for w in range(workers)
            if assignments[w]]

    if workers == 1:
        _worker_init(voice_names, str(voice_dir), verify_model, texts[0])
        results = [_worker_make(jobs[0])]
    else:
        import multiprocessing as mp

        ctx = mp.get_context("spawn")  # macOS default; fork is unsafe here
        with ctx.Pool(workers, initializer=_worker_init,
                      initargs=(voice_names, str(voice_dir), verify_model,
                                texts[0])) as pool:
            results = pool.map(_worker_make, jobs)

    made = sum(r[0] for r in results)
    rejected = sum(r[1] for r in results)
    if rejected:
        print(f"    ({rejected} clips thrown away for not saying it clearly)")
    print(f"    made {made}")
    if made < todo:
        print(f"    WARNING: only made {made} of {todo} — is the phrase hard to say?")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase", default="hey claude", help="the wake phrase")
    parser.add_argument("--out", default="train/clips", help="where to put the clips")
    parser.add_argument("--count", type=int, default=2000, help="positive training clips")
    parser.add_argument("--count-test", type=int, default=200, help="held-back positive clips")
    # Negatives are cheap — they skip the Whisper check — and they're the
    # side that decides whether the model wakes up when it shouldn't. It's
    # usually worth making several times more of them than positives.
    parser.add_argument("--count-negative", type=int, default=None,
                        help="negative training clips (default: same as --count)")
    parser.add_argument("--count-negative-test", type=int, default=None,
                        help="held-back negative clips (default: same as --count-test)")
    parser.add_argument(
        "--adversarial",
        type=int,
        default=0,
        help="add this many auto-generated phonetic near-misses to the "
             "negatives, on top of the hand-written list",
    )
    parser.add_argument("--voices", nargs="+", default=DEFAULT_VOICES,
                        help="Piper voices to use")
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) // 2),
        help="how many processes to generate with (the Whisper check is the "
             "slow part and splits cleanly across cores)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="listen to each positive clip with Whisper and throw away the "
             "ones that don't clearly say the phrase (slower, better data)",
    )
    parser.add_argument(
        "--verify-model",
        default="base.en",
        help="Whisper model used by --verify. tiny.en is about twice as "
             "fast but rejects more good clips (default: base.en)",
    )
    args = parser.parse_args()

    out = Path(args.out)
    voice_dir = out.parent / "voices"

    # Download and check the voices once, in this process, rather than
    # letting several workers race to download the same file.
    print("Loading voices...")
    load_voices(args.voices, voice_dir)

    extra = adversarial_texts(args.phrase, args.adversarial) if args.adversarial else []
    # A negative that sounds identical to the wake word is untrainable, and
    # it drags the wake word down with it.
    curated = drop_homophones(args.phrase, list(DEFAULT_NEGATIVES))
    extra = drop_homophones(args.phrase, extra)
    distinct = len(curated) + len(extra)
    negatives = weight_negatives(curated, extra)

    n_count = args.count_negative if args.count_negative is not None else args.count
    n_test = (args.count_negative_test if args.count_negative_test is not None
              else args.count_test)

    hard = [t for t in curated if t in HARD_NEGATIVES]
    print(f"\nPhrase: {args.phrase!r}")
    print(f"Sound-alikes to reject: {distinct} "
          f"({len(hard)} confusable, {len(curated) - len(hard)} other, "
          f"{len(extra)} auto-generated)")
    print(f"Clips: {args.count}+{args.count_test} positive, "
          f"{n_count}+{n_test} negative "
          f"(~{n_count * HARD_SHARE // max(1, len(negatives))} per confusable, "
          f"~{n_count * ADVERSARIAL_SHARE // max(1, len(negatives))} per auto-generated)")
    print(f"Workers: {args.workers}\n")

    verify = args.verify_model if args.verify else None
    common = dict(voice_names=args.voices, voice_dir=voice_dir,
                  workers=args.workers)

    # Only the positive clips get checked. A negative clip that came out
    # garbled is still a fine example of "not the wake word".
    generate(texts=[args.phrase], count=args.count, seed=args.seed,
             out_dir=out / "positive_train", verify_model=verify, **common)
    generate(texts=[args.phrase], count=args.count_test, seed=args.seed + 1000,
             out_dir=out / "positive_test", verify_model=verify, **common)
    generate(texts=negatives, count=n_count, seed=args.seed + 2000,
             out_dir=out / "negative_train", **common)
    generate(texts=negatives, count=n_test, seed=args.seed + 3000,
             out_dir=out / "negative_test", **common)

    total = sum(len(list((out / d).glob("*.wav"))) for d in
                ["positive_train", "positive_test", "negative_train", "negative_test"])
    print(f"\nDone — {total} clips in {out}/")
    print("Listen to a few to check they sound right:")
    print(f"    afplay {out}/positive_train/$(ls {out}/positive_train | head -1)")


if __name__ == "__main__":
    sys.exit(main())
