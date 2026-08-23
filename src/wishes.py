"""Wishes — things the speaker was asked for and cannot do.

    "hey claude, can you keep score for our game?"
    "I can't do that yet, but I've written it down."

Then, on the laptop:

    ./wishes.sh

A child asking for something the speaker cannot do is the most useful thing
that happens to this project. It is a feature request from the only person
whose opinion counts, phrased in his own words, at the moment he wanted it.
Those used to vanish into "sorry, I can't do that yet".

Deliberately the smallest possible thing
----------------------------------------
This writes a line to a file. That is all it does, and that is the point.

The obvious next step is for the speaker to build its own tools — and the
architecture is ready for it: `docs/tools.md` says adding a capability is a
module and a name in FEATURES, which is a specification a machine can meet.
Claude Code can already do it; it wrote src/scores.py in a sandbox against
these conventions on the first try.

What stops that being wired straight up is the television. It reaches the
transcript about fifty times an hour, and every one of those is a sentence
somebody else wrote being read to a machine. The path from "the television
said something" to "code was written and run" has to be broken by something
a broadcast cannot cross, and the only reliable such thing is a person
reading a diff. So the speaker's whole power here is to write down a wish;
everything that can execute lives somewhere it cannot reach.

    python src/wishes.py          what's been wished for
    python src/wishes.py --clear  forget them
"""

import json
import re
import sys
import threading
import time
from datetime import datetime

import config
import tools

WHERE = config.PROJECT_ROOT / "state" / "wishes.jsonl"

# Enough to hold a month of a child's imagination, few enough that a
# television repeating itself all night can't fill the card.
MOST = 500
# And no more than this many in an hour, for the same reason.
PER_HOUR = 20

_lock = threading.Lock()
_recent: list[float] = []


@tools.tool(
    "Write down something this speaker cannot do, so it might be built "
    "later. Use it when somebody asks for a capability that doesn't exist "
    "— keeping score in a game, sending a message, controlling a light, "
    "anything there is no tool for.\n\n"
    "Say plainly that you can't do it yet AND that you've written it down, "
    "in one short sentence. Both halves matter: a child who is told no "
    "stops asking, and asking is the useful part.\n\n"
    "Don't use it for things you can already do, for things that are "
    "impossible for any speaker, or for a question that simply needs "
    "answering. One wish per request, described as the thing to build "
    "rather than as the sentence they said.",
    properties={
        "wish": {
            "type": "string",
            "description": "What the speaker should be able to do, said "
                           "plainly: 'keep score in a card game', 'send a "
                           "message to a friend's parent'.",
        },
        "asked": {
            "type": "string",
            "description": "What they actually said, as near as you heard "
                           "it. Their words are worth keeping.",
        },
        "who": {
            "type": "string",
            "description": "Who asked, if you know. Leave empty if not.",
        },
    },
    required=["wish"],
    says="write down things it can't do yet, so they can be built",
)
def make_a_wish(wish: str, asked: str = "", who: str = "") -> str:
    wish = " ".join(wish.strip().split())[:200]
    if not wish:
        return "I'm not sure what to write down."

    with _lock:
        now = time.monotonic()
        _recent[:] = [t for t in _recent if now - t < 3600]
        if len(_recent) >= PER_HOUR:
            # Almost certainly the television, not a person.
            print("[wishes] too many this hour — not writing it down")
            return "I can't do that yet."
        _recent.append(now)

        try:
            WHERE.parent.mkdir(parents=True, exist_ok=True)
            with open(WHERE, "a") as handle:
                handle.write(json.dumps({
                    "at": datetime.now().astimezone().isoformat(
                        timespec="seconds"),
                    "wish": wish,
                    "asked": " ".join(asked.strip().split())[:200],
                    "who": "".join(c for c in who.strip().lower()
                                   if c.isalnum())[:20],
                }) + "\n")
            _trim()
        except Exception as error:
            print(f"[wishes] {type(error).__name__}: {error}")
            return "I can't do that yet."

    return "I can't do that yet, but I've written it down."


def read(text: str | None = None) -> list[dict]:
    """Every wish, most-asked first, with repeats folded together.

    A thing asked for five times is five times as interesting as a thing
    asked for once, and folding them here means the count survives however
    differently it was worded each time.
    """
    if text is None:
        if not WHERE.exists():
            return []
        text = WHERE.read_text()

    groups: list[dict] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # A half-written line from a power cut.
        words = _words(row.get("wish", ""))
        if not words:
            continue

        found = next((g for g in groups if _alike(g["words"], words)), None)
        if found is None:
            groups.append({
                "wish": row.get("wish", ""),
                "words": words,
                "first": row.get("at", ""),
                "last": row.get("at", ""),
                "times": 1,
                "askeds": [row["asked"]] if row.get("asked") else [],
                "whos": [row["who"]] if row.get("who") else [],
            })
            continue

        found["times"] += 1
        found["last"] = row.get("at", found["last"])
        found["words"] |= words
        for field in ("asked", "who"):
            if row.get(field) and row[field] not in found[field + "s"]:
                found[field + "s"].append(row[field])

    return sorted(groups, key=lambda w: (-w["times"], w["last"]))


# Words that carry no meaning in a wish, so they shouldn't make two wishes
# look different from each other.
SMALL = {"a", "an", "the", "to", "of", "for", "in", "on", "at", "it", "is",
         "be", "able", "can", "could", "should", "would", "my", "our",
         "your", "and", "or", "with", "that", "this", "some", "please"}


def _words(wish: str) -> set[str]:
    """The meaningful words of a wish, roughly stemmed.

    Roughly is the operative word. "keep score in a card game" and
    "keeping the score for a game" are plainly the same request and were
    landing in different groups, because an exact set of words says they
    share only two. Chopping the common endings gets keep/keeping and
    game/games together, which is as much grammar as this needs.
    """
    out = set()
    for word in re.findall(r"[a-z]+", wish.lower()):
        if word in SMALL or len(word) < 3:
            continue
        for ending in ("ing", "ers", "er", "ies", "es", "ed", "s"):
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[:-len(ending)]
                break
        out.add(word)
    return out


def _alike(one: set[str], other: set[str]) -> bool:
    """Whether two wishes are the same wish, said differently.

    Half the words in common. Loose enough to fold "keep score in a card
    game" into "keeping the score for a game", tight enough to keep
    "send a message to a friend" out of it.
    """
    if not one or not other:
        return False
    return len(one & other) / len(one | other) >= 0.4


def _trim() -> None:
    """Keep the file from growing without bound. Call with _lock held."""
    lines = WHERE.read_text().splitlines()
    if len(lines) > MOST:
        WHERE.write_text("\n".join(lines[-MOST:]) + "\n")


def show(wishes: list[dict]) -> str:
    """The wishes, laid out to be read by a person."""
    lines = []
    for wish in wishes:
        who = ", ".join(wish["whos"]) or "somebody"
        lines.append(f"\n  {wish['wish']}")
        lines.append(f"    asked {wish['times']}x by {who}, "
                     f"last {wish['last'][:16].replace('T', ' ')}")
        for said in wish["askeds"][:3]:
            lines.append(f"      \"{said}\"")
    return "\n".join(lines)


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    if "--clear" in sys.argv:
        WHERE.unlink(missing_ok=True)
        print("Forgotten.")
        raise SystemExit

    wishes = read()
    if not wishes:
        raise SystemExit(f"Nothing wished for yet. Looked in {WHERE}")
    print(show(wishes))
