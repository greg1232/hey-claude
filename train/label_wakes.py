"""Decide which of the logged wake-word firings were real, and which weren't.

The speaker writes down every firing (src/wake_log.py). This turns that pile
into labelled training data, using three things in order of how much they
cost:

  1. What Whisper makes of the two seconds that fired.
     This is the strongest single signal and it is nearly free — the wake
     window is two seconds and the model is already on the machine. If it
     transcribes to something like "hey Claude", it was real. If it
     transcribes to "and back to you Bob", it wasn't. The wake word itself
     can't do this: it decides in 159 ms on a window with no context,
     against a full decoder run with a language model behind it.

  2. What happened next.
     Nobody said anything -> almost certainly a mistake. A question that
     got answered -> almost certainly real. The speaker works both of
     these out anyway in the course of answering, and they are already in
     the log.

  3. Claude, for the ones still in doubt.
     Given the two transcripts, the time of day and the score, in batches
     of twenty. This is the only part that costs money, and after the first
     two steps there usually isn't much left for it to do.

Nothing is thrown away and nothing is overwritten: labels are appended to
the same log, so a bad run can be relabelled and the audio is still there
to listen to.

    python train/label_wakes.py                  label everything new
    python train/label_wakes.py --no-claude      steps 1 and 2 only
    python train/label_wakes.py --show           what's labelled so far
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import wake_log  # noqa: E402

# What the wake window sounds like when it really was the wake word. Whisper
# spells it a dozen ways — "hey Claude", "Hey, Cloud", "a clod" — so this
# looks for the shape of it rather than the spelling.
SOUNDS_RIGHT = re.compile(
    r"\b(clau?de?|cloud|clod|claud|klaud)\b", re.IGNORECASE)
SOUNDS_LIKE_HEY = re.compile(r"\b(hey|hi|hay|a|ok|okay)\b", re.IGNORECASE)

BATCH = 20


def transcribe_windows(firings: list[dict], size: str) -> None:
    """Add `window` — what Whisper heard in the two seconds that fired.

    Deliberately a bigger model than the speaker runs. The Pi listens with
    tiny.en because it has to keep up in real time on a quarter of a core;
    this runs later, on a laptop, with nothing waiting on it, so it can
    afford small.en or medium.en. That difference is the whole point of
    labelling offline — the judge should be better than the thing it is
    judging, or it only teaches the model its own mistakes.

    Claude can't listen to the audio itself: the API takes text, images and
    PDFs, and rejects audio outright. Tested, not assumed. So a transcript
    is the way in, and it is worth making it a good one.
    """
    from faster_whisper import WhisperModel

    todo = [f for f in firings
            if "window" not in f and (wake_log.AUDIO / f"{f['n']:06d}.wav").exists()]
    if not todo:
        return
    print(f"Transcribing {len(todo)} wake windows with {size}...")
    model = WhisperModel(size, device="cpu", compute_type="int8")

    import wave

    import numpy as np

    for firing in todo:
        path = wake_log.AUDIO / f"{firing['n']:06d}.wav"
        with wave.open(str(path), "rb") as handle:
            raw = handle.readframes(handle.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        # beam_size 5, not the 1 the speaker uses: accuracy matters here
        # and nobody is waiting. No VAD filter — a two second window is
        # mostly silence by design, and filtering it can leave nothing.
        segments, _ = model.transcribe(audio, language="en", beam_size=5)
        firing["window"] = " ".join(s.text.strip() for s in segments).strip()
        _append({"n": firing["n"], "window": firing["window"]})


def label_locally(firing: dict) -> tuple[int | None, str]:
    """Label from evidence already on the machine. None means ask Claude."""
    window = (firing.get("window") or "").strip()
    heard = (firing.get("heard") or "").strip()

    if window and SOUNDS_RIGHT.search(window):
        return 1, "the window says Claude"

    # Somebody spoke a real question straight after, and Claude answered it.
    # Even if Whisper missed the wake word in the window, a person was
    # plainly talking to the speaker.
    if firing.get("answered") and len(heard.split()) >= 3:
        return 1, "a real question followed"

    # Nothing at all afterwards, and nothing like the word in the window.
    # This is what almost every television mistake looks like.
    if not heard and window and not SOUNDS_RIGHT.search(window):
        return 0, "no wake word, and nobody said anything"
    if not heard and not window:
        return 0, "silence either side"

    return None, ""


def ask_claude(unsure: list[dict]) -> None:
    """Label the leftovers, twenty at a time."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    import anthropic

    import config

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    print(f"Asking Claude about {len(unsure)} uncertain firings...")

    for start in range(0, len(unsure), BATCH):
        batch = unsure[start:start + BATCH]
        listing = "\n".join(
            f"{f['n']}. at {f.get('at', '?')[11:16]}, score {f.get('score')}, "
            f"the two seconds that fired sounded like "
            f"{(f.get('window') or '')!r}, and what came next was "
            f"{(f.get('heard') or '')!r}"
            for f in batch)

        message = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2000,
            system=(
                "You are labelling training data for the wake word of a "
                "voice assistant that listens for the phrase \"hey Claude\". "
                "It sits in a family living room with a television on.\n\n"
                "For each numbered firing, decide whether somebody really "
                "said the wake word to the speaker, or whether it fired by "
                "mistake on the television or on ordinary conversation.\n\n"
                "The transcripts come from a small speech model and are "
                "often wrong. \"hey Claude\" comes out as \"a cloud\", "
                "\"hey clod\", \"Hey, Claude.\" — judge it by sound, not "
                "spelling. Television gives you fragments of broadcast "
                "speech addressed to nobody in the room.\n\n"
                "Answer with one JSON array and nothing else: "
                '[{"n": 12, "real": true, "why": "short reason"}, ...]. '
                "Include every number. If you genuinely cannot tell, leave "
                "that number out rather than guessing."),
            messages=[{"role": "user", "content": listing}],
        )

        text = "".join(b.text for b in message.content if b.type == "text")
        for verdict in _json_array(text):
            number = verdict.get("n")
            if number is None or "real" not in verdict:
                continue
            _append({"n": number, "label": int(bool(verdict["real"])),
                     "why": f"claude: {verdict.get('why', '')}"[:120]})
        print(f"  labelled {min(start + BATCH, len(unsure))}"
              f"/{len(unsure)}")


def _json_array(text: str) -> list[dict]:
    """Pull the array out of Claude's reply, however it wrapped it."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        return json.loads(match.group(0))
    except ValueError:
        return []


def _append(row: dict) -> None:
    with open(wake_log.INDEX, "a") as handle:
        handle.write(json.dumps(row) + "\n")


def show() -> int:
    firings = wake_log.read()
    labelled = [f for f in firings if "label" in f]
    real = sum(f["label"] for f in labelled)
    print(f"{len(firings)} firings, {len(labelled)} labelled: "
          f"{real} real, {len(labelled) - real} mistakes")
    for firing in labelled[-25:]:
        mark = "REAL" if firing["label"] else "  no"
        print(f"  {mark} {firing.get('at', '')[11:19]} "
              f"{firing.get('score', 0):.3f} "
              f"window={(firing.get('window') or '')[:34]!r} "
              f"next={(firing.get('heard') or '')[:28]!r}")
        if firing.get("why"):
            print(f"       {firing['why']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--whisper", default="small.en",
                        help="which Whisper to judge the wake window with. "
                             "Bigger than the Pi's tiny.en on purpose "
                             "(default: small.en)")
    parser.add_argument("--no-claude", action="store_true",
                        help="use only the free signals, don't call the API")
    parser.add_argument("--show", action="store_true",
                        help="print what has been labelled and stop")
    args = parser.parse_args()

    if args.show:
        return show()

    firings = wake_log.read()
    if not firings:
        raise SystemExit(f"Nothing logged yet. Looked in {wake_log.WHERE}")

    todo = [f for f in firings if "label" not in f]
    print(f"{len(firings)} firings logged, {len(todo)} unlabelled")
    if not todo:
        return show()

    transcribe_windows(todo, args.whisper)

    unsure = []
    free = 0
    for firing in todo:
        label, why = label_locally(firing)
        if label is None:
            unsure.append(firing)
        else:
            _append({"n": firing["n"], "label": label, "why": why})
            free += 1
    print(f"  {free} settled without asking anyone, {len(unsure)} in doubt")

    if unsure and not args.no_claude:
        ask_claude(unsure)

    return show()


if __name__ == "__main__":
    raise SystemExit(main())
