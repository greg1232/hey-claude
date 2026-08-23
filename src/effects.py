"""Sound effects — real recordings, fetched when somebody asks for one.

    "hey claude, what does a bullfrog say"
    "hey claude, play the sound of a train whistle"

Unlike the background sounds in sounds.py, these can't be made from filtered
noise. A bullfrog is a bullfrog. So they are looked up, downloaded, cached
on disk, and played — and the second bullfrog is instant.

Where they come from
--------------------
Freesound, if you have a key. It is the good one: six hundred thousand
Creative Commons recordings, searchable, with ratings and durations to sort
by. A key is free from https://freesound.org/apiv2/apply/ and goes in .env
as FREESOUND_API_KEY.

Wikimedia Commons otherwise, which needs no key and no account. It works,
but its search is not built for this and the ranking shows it: "cow moo"
returns a 1922 jazz record called Atlanta Rag by Cow Cow Davenport, and
half the hits for any animal are dictionary pronunciations of the word.
Hence FALSE_FRIENDS below, which is not elegant and is entirely necessary.

Playing it
----------
Through the same arbitration as everything else: the microphone array is
one device, so this takes the speaker lock and steps the background sounds
aside, and sets `speaking` so the wake word can't hear the bullfrog and
wake up for it.

    python src/effects.py bullfrog       look one up and play it
    python src/effects.py --list         what's already cached
"""

import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

import config
import tools

CACHE = config.PROJECT_ROOT / "state" / "effects"

# Wikimedia asks for a real one, and returns 403 without it.
AGENT = ("ClaudeSpeaker/1.0 (a family voice assistant; "
         "https://github.com/greg1232/hey-claude)")

COMMONS = "https://commons.wikimedia.org/w/api.php"
FREESOUND = "https://freesound.org/apiv2/search/text/"

# Longer than this and it isn't a sound effect, it's a recording of
# something. Kept short deliberately: a child asked a question.
LONGEST = 12.0

# Titles that match the search but aren't the thing. Commons is full of
# spoken-dictionary files — "En-us-elephant.ogg" is a person saying the
# word "elephant" — and of music whose title happens to contain an animal.
# Words that shouldn't count towards matching a title, because almost any
# recording of an animal could be described with them.
VAGUE = {"sound", "sounds", "noise", "noises", "call", "calling", "a", "an",
         "the", "of", "effect"}

FALSE_FRIENDS = re.compile(
    r"^(?:[a-z]{2}(?:-[a-z]{2})?)-|^LL-Q|\(eng\)|pronunciation|"
    r"\bsong\b|\brag\b|\bsymphony\b|\bsonata\b|\bopus\b|\bband\b|"
    r"\bmusic\b|\binterview\b|\bspeech\b|\bpodcast\b|\baudiobook\b",
    re.IGNORECASE)


@tools.tool(
    "Play a short real recording of a sound: an animal, a vehicle, an "
    "instrument, a natural noise. Use this whenever somebody asks what "
    "something sounds like, or asks you to play the sound of something — "
    "'what does a bullfrog say', 'play a train whistle'. Answer in words "
    "as well, briefly, because the recording might not be found. Don't use "
    "it for background noise to sleep to; that's play_sound.",
    properties={
        "search": {
            "type": "string",
            "description": "What to look for, as you'd search for a "
                           "recording of it: 'bullfrog croaking', 'steam "
                           "train whistle', 'owl hooting'. Two or three "
                           "words, no punctuation.",
        },
    },
    required=["search"],
    says="play real recordings of sounds like animals when asked what "
         "something sounds like",
)
def play_effect(search: str) -> str:
    search = " ".join(search.strip().lower().split())[:60]
    if not search:
        return "I need to know what to look for."

    try:
        audio, rate, title, cached = fetch(search)
    except Exception as error:
        print(f"[effects] {type(error).__name__}: {error}")
        return "I couldn't reach the sound library just now."

    if audio is None:
        return (f"I couldn't find a recording of {search}. "
                "Say what it sounds like in words instead.")

    import tts
    tts.play_clip(audio, rate)
    where = "from what I had saved" if cached else "found online"
    return f"Played a recording called {title!r}, {where}."


def fetch(search: str):
    """Get the audio for `search`, from disk if it's been asked for before.

    Everything is cached under the words that were asked for, not the file
    that was found, so the second bullfrog is instant and offline.
    """
    import soundfile as sf

    saved = CACHE / f"{_slug(search)}.wav"
    if saved.exists():
        audio, rate = sf.read(saved, dtype="float32")
        return audio, rate, saved.stem.replace("-", " "), True

    for title, url in candidates(search):
        try:
            raw = _get(url, binary=True)
            audio, rate = sf.read(io.BytesIO(raw), dtype="float32",
                                  always_2d=True)
        except Exception as error:
            print(f"[effects] skipping {title}: {type(error).__name__}")
            continue

        audio = audio.mean(axis=1)  # Down to mono; the array is one channel.
        if len(audio) / rate > LONGEST:
            audio = audio[:int(LONGEST * rate)]
        peak = float(np.abs(audio).max())
        if peak < 0.01:
            continue  # Silence, or near enough.
        # Recordings arrive at wildly different levels — one measured 0.28
        # peak — and a sound effect that can't be heard is no use.
        audio = audio * (0.9 / peak)

        CACHE.mkdir(parents=True, exist_ok=True)
        sf.write(saved, audio, rate)
        return audio, rate, title, False

    return None, 0, "", False


def candidates(search: str):
    """Things worth trying, best first.

    Falls back through simpler searches, because the exact phrase often
    finds nothing while a word of it finds the right thing. "bullfrog
    croaking" returns nothing on Commons; "bullfrog" returns nothing;
    "croaking" returns frogs croaking in a pipe in Thailand, which is
    exactly what a child asking what a bullfrog says wants to hear.
    """
    for term in _attempts(search):
        if config.FREESOUND_KEY:
            found = from_freesound(term)
            if found:
                return found
        found = from_commons(term)
        if found:
            return found
    return []


def _attempts(search: str) -> list[str]:
    """The whole phrase, then its words, most specific first."""
    words = [w for w in search.split() if w not in VAGUE]
    # Longest first: "croaking" is a better search than "a", and generally
    # the longer word in a two word phrase is the more particular one.
    singles = sorted(set(words), key=len, reverse=True)
    return [search] + [w for w in singles if w != search]


def from_freesound(search: str):
    """The good source, if there's a key for it."""
    query = urllib.parse.urlencode({
        "query": search,
        "filter": f"duration:[0.3 TO {LONGEST}]",
        "sort": "rating_desc",
        "fields": "name,previews,avg_rating,num_ratings",
        "page_size": "8",
        "token": config.FREESOUND_KEY,
    })
    try:
        found = json.loads(_get(f"{FREESOUND}?{query}"))
    except Exception as error:
        print(f"[effects] freesound: {type(error).__name__}: {error}")
        return []

    out = []
    for hit in found.get("results", []):
        preview = (hit.get("previews") or {}).get("preview-hq-mp3")
        if preview:
            out.append((hit.get("name", search), preview))
    return out


def from_commons(search: str):
    """The one that needs no key, with the junk filtered out."""
    query = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:audio {search}", "gsrnamespace": "6",
        "gsrlimit": "12", "prop": "imageinfo", "iiprop": "url|mime|size",
    })
    pages = json.loads(_get(f"{COMMONS}?{query}")).get(
        "query", {}).get("pages", {})

    scored = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        title = page.get("title", "")[5:]          # Drop the "File:".
        if not info.get("url") or FALSE_FRIENDS.search(title):
            continue
        # A short file is much more likely to be the sound itself than a
        # recording of an event that contains it.
        size = info.get("size", 0)
        if size > 3_000_000:
            continue
        # The title has to actually contain what was asked for. Commons
        # will happily return "What's the Matter with the Moon Tonight?"
        # for "bullfrog croaking" — it matches on the page text, not the
        # name — and without this it wins on being a small file.
        words = set(re.findall(r"[a-z]+", title.lower()))
        wanted = set(search.split()) - VAGUE
        overlap = len(words & wanted)
        if not overlap:
            continue
        scored.append((-overlap, size, title, info["url"]))

    scored.sort()
    return [(t, u) for _o, _s, t, u in scored[:6]]


def _get(url: str, binary: bool = False):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
    return raw if binary else raw.decode("utf-8", "replace")


def _slug(search: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", search.lower()).strip("-")[:50]


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    if "--list" in sys.argv:
        for path in sorted(CACHE.glob("*.wav")):
            print(f"  {path.stem.replace('-', ' ')}  "
                  f"({path.stat().st_size / 1000:.0f} kB)")
        raise SystemExit

    print(play_effect(" ".join(sys.argv[1:]) or "bullfrog"))
