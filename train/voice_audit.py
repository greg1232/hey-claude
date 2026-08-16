"""Check how clearly each Piper voice says the wake phrase.

Not every Piper voice can say every phrase. Some produce audio that Whisper
can't recognise as the phrase at all — those cost several synthesis attempts
per usable clip and contribute almost nothing, so it's worth knowing before
starting a long generation run rather than after.

Measured for "hey claude": en_US-l2arctic 0%, en_GB-aru 0%, en_US-arctic 8%,
en_GB-northern_english_male 12% — against 92% for en_US-libritts_r.

    python train/voice_audit.py                       # audit the defaults
    python train/voice_audit.py --voices en_US-joe-medium en_GB-alan-medium

Anything below about 50% is usually not worth including.
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_clips import (  # noqa: E402
    DEFAULT_VOICES, load_voices, make_checker, synthesize,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase", default="hey claude")
    parser.add_argument("--voices", nargs="+", default=DEFAULT_VOICES,
                        help="voices to check (default: the ones "
                             "generate_clips.py uses)")
    parser.add_argument("--count", type=int, default=25,
                        help="clips to try per voice")
    parser.add_argument("--voice-dir", default="train/voices")
    args = parser.parse_args()

    checker = make_checker(args.phrase, "base.en", quiet=True)
    print(f"Phrase: {args.phrase!r}, {args.count} clips per voice\n")
    print(f"{'voice':36s} {'speakers':>8s} {'says it clearly':>16s}")

    results = []
    for name in args.voices:
        voice = load_voices([name], Path(args.voice_dir), quiet=True)[0]
        rng = random.Random(0)
        ok = sum(checker(synthesize(voice, args.phrase, rng))
                 for _ in range(args.count))
        pct = 100 * ok // args.count
        results.append((name, pct))
        print(f"{name:36s} {voice.config.num_speakers:8d} "
              f"{ok:3d}/{args.count} ({pct:3d}%)")

    weak = [n for n, p in results if p < 50]
    if weak:
        print(f"\nBelow 50%, probably not worth the time: {', '.join(weak)}")


if __name__ == "__main__":
    sys.exit(main())
