"""Spotify — playing actual music, on the Pi.

    "hey claude, play Baby Shark"
    "hey claude, skip this"
    "hey claude, turn it down"
    "hey claude, stop the music"

Two halves, and they meet in the middle.

librespot runs on the Pi as a service and makes it a Spotify Connect
speaker — the same thing as a Sonos or a smart TV, as far as Spotify is
concerned. No password goes anywhere near the Pi: you pick it once in the
phone app, which is how it gets its credentials, and they are cached after
that.

This file is the other half: the Web API, which searches and says what to
play where. It never touches audio. That matters — the speaker does not
decode or resample a note of it, so an hour of music costs the Pi about as
much as an hour of silence.

Sharing the speaker
-------------------
Music and speech go through PipeWire, which mixes them, so nothing has to
be closed and reopened the way sounds.py and books.py do. But mixing is
not what you want when somebody asks a question over the top of a song —
you want the song to get quieter. So the volume is pulled down while the
speaker talks and put back afterwards, which Spotify does on its own side
in one API call.

    python src/music.py                  what's playing, and where
    python src/music.py rain on me       find it, and play it
"""

import base64
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import sounds
import tools

ACCOUNTS = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

# The most Spotify will return per search. Their documentation says 50;
# an app in development mode gets 400 "Invalid limit" above ten, which is
# not what the message suggests. Measured: 10 works, 11 does not.
MOST = 10

# How far to duck the music while the speaker is talking, as a fraction of
# whatever it was. Quiet enough to be talked over, loud enough that it
# plainly hasn't stopped.
DUCK_TO = 0.2

_lock = threading.RLock()
_token = ""
_token_until = 0.0
_offered: list[dict] = []
_ducked_from: int | None = None


def ready() -> bool:
    return bool(config.SPOTIFY_REFRESH_TOKEN and config.SPOTIFY_CLIENT_ID)


# --- talking to Spotify -----------------------------------------------------


def _access() -> str:
    """A usable access token, refreshed when it goes stale.

    They last an hour, which is shorter than an evening, so this is not an
    optimisation — a speaker that stopped working after an hour would be a
    puzzling thing to debug.
    """
    global _token, _token_until
    with _lock:
        if _token and time.monotonic() < _token_until:
            return _token

        secret = base64.b64encode(
            f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}"
            .encode()).decode()
        request = urllib.request.Request(
            ACCOUNTS,
            data=urllib.parse.urlencode({
                "grant_type": "refresh_token",
                "refresh_token": config.SPOTIFY_REFRESH_TOKEN}).encode(),
            headers={"Authorization": f"Basic {secret}",
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(request, timeout=20) as response:
            got = json.load(response)
        _token = got["access_token"]
        # A minute early, so a call never starts on a token that expires
        # while it's in flight.
        _token_until = time.monotonic() + int(got.get("expires_in", 3600)) - 60
        return _token


def _call(method: str, path: str, body: dict | None = None):
    """One Web API call. Returns the reply, or {} when there's no body."""
    request = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_access()}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        # Not everything answers with JSON. Skipping a track comes back 200
        # with a bare tracking id in the body, which is not an error and
        # must not be treated as one.
        return {}


def _speaker_id() -> str | None:
    """The Pi's own Spotify device, by the name librespot advertises."""
    wanted = config.SPOTIFY_DEVICE.strip().lower()
    for device in _call("GET", "/me/player/devices").get("devices", []):
        if device["name"].strip().lower() == wanted:
            return device["id"]
    return None


# --- getting out of the way -------------------------------------------------


def duck() -> None:
    """Pull the music down while the speaker talks."""
    global _ducked_from
    if not ready():
        return
    try:
        with _lock:
            if _ducked_from is not None:
                return  # Already down; a beep inside an answer must not
                        # take the ducked volume for the real one.
            now = _call("GET", "/me/player")
            if not now or not now.get("is_playing"):
                return
            was = (now.get("device") or {}).get("volume_percent")
            if was is None:
                return
            _ducked_from = was
        _call("PUT", f"/me/player/volume?volume_percent={int(was * DUCK_TO)}")
    except Exception as error:
        print(f"[music] couldn't duck: {type(error).__name__}")


def unduck() -> None:
    """Put it back."""
    global _ducked_from
    if not ready():
        return
    with _lock:
        was, _ducked_from = _ducked_from, None
    if was is None:
        return
    try:
        _call("PUT", f"/me/player/volume?volume_percent={int(was)}")
    except Exception as error:
        print(f"[music] couldn't put the volume back: {type(error).__name__}")


sounds.also_pause(duck, unduck)


# --- what Claude can ask for ------------------------------------------------


@tools.tool(
    "Search Spotify for music. This does NOT play anything — it hands back "
    "what Spotify has, and you choose.\n\n"
    "Read the results before picking. A song title match is very often the "
    "wrong recording: a children's song has dozens of versions by different "
    "people, and there are karaoke tracks, covers, remixes and lullaby "
    "renditions of almost everything. Prefer the well known recording — "
    "usually the most popular — unless they asked for something else. When "
    "somebody asks for an artist or a kind of music rather than a song, "
    "search for that and pick an album or playlist.\n\n"
    "When one is clearly right, call play_music with its number straight "
    "away. Ask only when you genuinely cannot tell which they meant.",
    properties={
        "search": {
            "type": "string",
            "description": "What to search Spotify for: a song, an artist, "
                           "an album, or a kind of music.",
        },
        "kind": {
            "type": "string",
            "description": "track, album, or playlist. Use track for a "
                           "named song, playlist for a mood or an activity.",
        },
    },
    required=["search"],
    says="play music from Spotify",
)
def find_music(search: str, kind: str = "track") -> str:
    global _offered
    if not ready():
        return "Spotify isn't set up on this speaker."
    kind = kind if kind in ("track", "album", "playlist") else "track"

    try:
        found = _call("GET", "/search?" + urllib.parse.urlencode(
            {"q": search, "type": kind, "limit": str(MOST)}))
    except Exception as error:
        print(f"[music] search failed: {type(error).__name__}: {error}")
        return "I couldn't reach Spotify just now."

    items = [i for i in found.get(kind + "s", {}).get("items", []) if i]
    _offered = items
    if not items:
        return f"Spotify has nothing for {search}."

    lines = []
    for number, item in enumerate(items, 1):
        who = ", ".join(a["name"] for a in item.get("artists", []))
        if kind == "playlist":
            who = (item.get("owner") or {}).get("display_name", "")
            extra = f"{(item.get('tracks') or {}).get('total', 0)} tracks"
        elif kind == "album":
            extra = (f"{item.get('total_tracks', 0)} tracks, "
                     f"{(item.get('release_date') or '')[:4]}")
        else:
            seconds = item.get("duration_ms", 0) // 1000
            extra = (f"{seconds // 60}:{seconds % 60:02d}, "
                     f"popularity {item.get('popularity', 0)}")
        lines.append(f"{number}. {item.get('name', '?')}"
                     + (f" — {who}" if who else "") + f" ({extra})")
    return ("Choose one and call play_music with its number:\n"
            + "\n".join(lines))


@tools.tool(
    "Play one of the things find_music offered, by its number, on this "
    "speaker.",
    properties={
        "number": {
            "type": "integer",
            "description": "Which one, counting from 1.",
        },
    },
    required=["number"],
)
def play_music(number: int) -> str:
    if not _offered:
        return "Search for something first with find_music."
    if not 1 <= int(number) <= len(_offered):
        return f"There were only {len(_offered)} to choose from."

    chosen = _offered[int(number) - 1]
    try:
        device = _speaker_id()
        if device is None:
            return ("This speaker isn't showing up in Spotify. Open Spotify "
                    "on a phone and pick "
                    f"{config.SPOTIFY_DEVICE} once, and it will stay.")

        where = f"/me/player/play?device_id={device}"
        if chosen["type"] == "track":
            _call("PUT", where, {"uris": [chosen["uri"]]})
        else:
            _call("PUT", where, {"context_uri": chosen["uri"]})
    except Exception as error:
        print(f"[music] {type(error).__name__}: {error}")
        return "Spotify wouldn't start that. Is the Premium account free?"

    who = ", ".join(a["name"] for a in chosen.get("artists", []))
    return f"Playing {chosen['name']}" + (f" by {who}" if who else "") + "."


@tools.tool("Stop, pause, or start the music again. Use for 'stop the "
            "music', 'pause', 'carry on'.",
            properties={"what": {
                "type": "string",
                "description": "'pause' or 'play'.",
            }},
            required=["what"])
def pause_music(what: str) -> str:
    try:
        if what.strip().lower().startswith(("play", "resume", "carry", "un")):
            _call("PUT", "/me/player/play")
            return "Music going again."
        _call("PUT", "/me/player/pause")
        return "Music paused."
    except Exception as error:
        print(f"[music] {type(error).__name__}: {error}")
        return "Nothing is playing."


@tools.tool("Skip to the next song, or back to the one before.",
            properties={"which": {
                "type": "string",
                "description": "'next' or 'back'.",
            }},
            required=["which"])
def skip_music(which: str) -> str:
    try:
        if which.strip().lower().startswith(("back", "prev", "last")):
            _call("POST", "/me/player/previous")
            return "Went back one."
        _call("POST", "/me/player/next")
        time.sleep(0.6)   # Give Spotify a moment to load the next one.
        return f"Skipped. Now playing {now_playing()}."
    except Exception as error:
        print(f"[music] {type(error).__name__}: {error}")
        return "Nothing is playing."


# How much "a bit louder" moves it.
STEP = 15


@tools.tool(
    "Change how loud the music is. Only the music — it does not change how "
    "loud you are. Say 'up' or 'down' for a step, or give a number from 0 "
    "to 100 if they asked for one.",
    properties={"level": {
        "type": "string",
        "description": "'up', 'down', 'mute', or a number from 0 to 100.",
    }},
    required=["level"])
def music_volume(level: str) -> str:
    """Louder, quieter, or a number.

    It used to take a percentage and nothing else, which meant that asked
    to "turn it down a bit" Claude had no number to give and said it had
    turned the music down without turning anything down. A tool that can
    only be called with something the caller cannot know is a tool that
    invites being talked around.
    """
    global _ducked_from
    said = str(level).strip().lower()
    try:
        with _lock:
            # If it's ducked right now, the real volume is the one being
            # held for afterwards, not the quiet one Spotify reports.
            current = _ducked_from
        if current is None:
            now = _call("GET", "/me/player")
            current = (now.get("device") or {}).get("volume_percent", 50)

        if said.startswith(("up", "loud", "high", "more")):
            wanted = current + STEP
        elif said.startswith(("down", "quiet", "low", "soft", "less")):
            wanted = current - STEP
        elif said.startswith(("mute", "silen", "off")):
            wanted = 0
        else:
            digits = "".join(c for c in said if c.isdigit())
            if not digits:
                return f"I didn't understand {level!r}."
            wanted = int(digits)
        wanted = max(0, min(100, wanted))

        with _lock:
            if _ducked_from is not None:
                # Change what it comes back to, or the answer being spoken
                # right now would undo what was just asked for.
                _ducked_from = wanted
                return f"Music at {wanted} percent."
        _call("PUT", f"/me/player/volume?volume_percent={wanted}")
    except Exception as error:
        print(f"[music] {type(error).__name__}: {error}")
        return "I couldn't change the volume."
    return f"Music at {wanted} percent."


@tools.tool("Say what music is playing.")
def what_music() -> str:
    playing = now_playing()
    return f"Playing {playing}." if playing else "No music playing."


def now_playing() -> str:
    try:
        now = _call("GET", "/me/player")
    except Exception:
        return ""
    if not now or not now.get("item"):
        return ""
    item = now["item"]
    who = ", ".join(a["name"] for a in item.get("artists", []))
    return f"{item.get('name','?')}" + (f" by {who}" if who else "")


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    if not ready():
        raise SystemExit("Spotify isn't set up — see train/spotify_login.py")

    if len(sys.argv) > 1:
        print(find_music(" ".join(sys.argv[1:])))
        print(play_music(1))
    else:
        for device in _call("GET", "/me/player/devices").get("devices", []):
            mark = " <- this Pi" if device["name"] == config.SPOTIFY_DEVICE else ""
            print(f"  {device['name'][:28]:30} {device['type']:12} "
                  f"active={device['is_active']}{mark}")
        print(f"  now: {now_playing() or 'nothing'}")
