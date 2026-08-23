"""Timers and alarms — the only part of the speaker that talks first.

Everything else here answers a question. A timer interrupts, and that makes
it the awkward one: it goes off on its own thread, minutes after anybody
asked for it, quite possibly while somebody is in the middle of asking
something else.

Two locks keep that from turning into a mess:

  the turn lock   held by main.py for a whole question-and-answer. A timer
                  that comes due in the middle waits for the answer to
                  finish rather than talking over it — or worse, ringing
                  into the microphone while the question is being recorded,
                  where it lands in the recording and Whisper transcribes
                  the chime as a word.

  the state lock  guards the list itself, because the ringing thread and
                  the answering thread both touch it.

Alarms outlive a reboot; timers don't. Somebody setting a seven o'clock
alarm means it, and a Pi that lost power at four in the morning shouldn't
quietly drop it. A ten minute timer, on the other hand, is about something
happening right now, and an hour later it's just confusing.

    python src/timers.py        set a five second timer and wait for it
"""

import json
import sys
import threading
import time
from datetime import date as date_type
from datetime import datetime, timedelta

import config

# Where alarms are kept between runs. Deliberately outside the code, so
# deploying doesn't overwrite them and git never sees them.
STATE_FILE = config.PROJECT_ROOT / "state" / "alarms.json"

# Enough for a kitchen; few enough that "cancel everything" is never scary.
MAX_PENDING = 12

# Held by main.py for the length of a turn. A ring waits for it.
turn = threading.RLock()

_lock = threading.Lock()
_pending: list[dict] = []
_next_id = 1
_announce = None
_thread: threading.Thread | None = None


# --- setting them -----------------------------------------------------------


def add_timer(seconds: int, label: str = "") -> str:
    """Start a countdown. Returns what to tell the person."""
    if seconds < 1:
        return "That's not long enough to time."
    if seconds > 24 * 3600:
        return "That's too long for a timer — try an alarm instead."

    when = time.time() + seconds
    spoken = label or say_length(seconds)
    error = _add({"kind": "timer", "label": label, "at": when,
                  "spoken": spoken})
    if error:
        return error
    return (f"Timer set for {say_length(seconds)}"
            + (f", called {label}" if label else "")
            + f". It goes off at {say_clock(when)}.")


def add_alarm(clock: str, on_date: str = "", label: str = "") -> str:
    """Set an alarm for a wall-clock time. Returns what to tell the person."""
    try:
        wanted = datetime.strptime(clock.strip(), "%H:%M").time()
    except ValueError:
        return f"I couldn't understand the time {clock!r}. Use 24-hour HH:MM."

    today = datetime.now().astimezone()
    if on_date:
        try:
            day = date_type.fromisoformat(on_date.strip())
        except ValueError:
            return f"I couldn't understand the date {on_date!r}."
        moment = datetime.combine(day, wanted).astimezone()
    else:
        # No date given means the next time that clock time comes round,
        # which is tomorrow if it has already gone past today.
        moment = datetime.combine(today.date(), wanted).astimezone()
        if moment <= today:
            moment += timedelta(days=1)

    if moment <= today:
        return "That time has already gone past."

    error = _add({"kind": "alarm", "label": label, "at": moment.timestamp(),
                  "spoken": label or "alarm"})
    if error:
        return error
    return f"Alarm set for {say_clock(moment.timestamp(), with_day=True)}."


def _add(item: dict) -> str:
    """Put one timer or alarm on the list. Returns an error, or empty."""
    global _next_id
    with _lock:
        if len(_pending) >= MAX_PENDING:
            return (f"There are already {MAX_PENDING} timers and alarms set. "
                    "Cancel one first.")
        item["id"] = _next_id
        _next_id += 1
        _pending.append(item)
        _save()
    return ""


# --- asking about them ------------------------------------------------------


def listing() -> str:
    """Everything set right now, phrased for reading aloud."""
    with _lock:
        items = sorted(_pending, key=lambda item: item["at"])

    if not items:
        return "Nothing is set."

    lines = []
    for item in items:
        name = item["label"] or item["spoken"]
        if item["kind"] == "timer":
            left = max(0, int(item["at"] - time.time()))
            lines.append(f"{name}: {say_length(left)} left")
        else:
            lines.append(f"{name}: goes off at "
                         f"{say_clock(item['at'], with_day=True)}")
    return "; ".join(lines)


def cancel(which: str = "all") -> str:
    """Cancel by name, by number, or everything."""
    which = which.strip().lower()
    with _lock:
        if not _pending:
            return "Nothing was set."

        if which in ("all", "everything", ""):
            count = len(_pending)
            _pending.clear()
            _save()
            return f"Cancelled all {count}."

        keep, gone = [], []
        for item in _pending:
            name = (item["label"] or item["spoken"]).lower()
            if which in name or which == str(item["id"]):
                gone.append(item)
            else:
                keep.append(item)

        if not gone:
            return f"I couldn't find one called {which!r}. Set: {listing_locked()}"
        _pending[:] = keep
        _save()

    if len(gone) == 1:
        return f"Cancelled the {gone[0]['spoken']}."
    return f"Cancelled {len(gone)} of them."


def listing_locked() -> str:
    """The names of everything set. Call with _lock already held."""
    return ", ".join(item["label"] or item["spoken"] for item in _pending)


# --- going off --------------------------------------------------------------


def start(announce) -> None:
    """Begin watching the clock. `announce` says one line out loud."""
    global _announce, _thread
    _announce = announce
    _load()
    if _thread is None:
        _thread = threading.Thread(target=_watch, daemon=True)
        _thread.start()


def _watch() -> None:
    """Check the clock forever, and ring whatever has come due.

    Half a second is close enough for a kitchen timer and cheap enough not
    to show up in the Pi's idle load, which matters — the wake word is
    already using a quarter of a core.
    """
    while True:
        time.sleep(0.5)
        now = time.time()

        with _lock:
            due = [item for item in _pending if item["at"] <= now]
            if due:
                _pending[:] = [i for i in _pending if i["at"] > now]
                _save()

        for item in due:
            _ring(item)


def _ring(item: dict) -> None:
    """Say that one timer is up, once nothing else is talking."""
    if item["kind"] == "timer":
        words = f"Your {item['spoken']} timer is done."
    elif item["label"]:
        words = f"It's {say_clock(item['at'])}. {item['label']}."
    else:
        words = f"It's {say_clock(item['at'])}. Your alarm is going off."

    # Wait for any question in flight to be finished with, so the ring
    # doesn't talk over the answer or get recorded into the next question.
    with turn:
        if _announce is not None:
            _announce(words)


# --- remembering them -------------------------------------------------------


def _save() -> None:
    """Write the alarms to disk. Call with _lock held.

    Timers are left out on purpose: see the note at the top.
    """
    alarms = [item for item in _pending if item["kind"] == "alarm"]
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(alarms, indent=2))
    except OSError as error:
        # A speaker that can't write its state is still a speaker.
        print(f"[timers] couldn't save: {error}")


def _load() -> None:
    """Read back the alarms from last time, dropping any that have passed."""
    global _next_id
    try:
        saved = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return

    now = time.time()
    with _lock:
        for item in saved:
            if item.get("kind") == "alarm" and item.get("at", 0) > now:
                item["id"] = _next_id
                _next_id += 1
                _pending.append(item)
        if _pending:
            print(f"Alarms still set: {listing_locked()}")


# --- saying times out loud --------------------------------------------------


def say_length(seconds: int) -> str:
    """90 as "a minute and a half" — near enough, in words a person uses."""
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"

    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        if rest == 30 and minutes == 1:
            return "a minute and a half"
        if rest == 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''} {rest} seconds"

    hours, minutes = divmod(minutes, 60)
    words = f"{hours} hour{'s' if hours != 1 else ''}"
    if minutes:
        words += f" {minutes} minute{'s' if minutes != 1 else ''}"
    return words


def say_clock(when: float, with_day: bool = False) -> str:
    """An epoch time as "7:05 am", or "7:05 am tomorrow"."""
    moment = datetime.fromtimestamp(when).astimezone()
    clock = moment.strftime("%I:%M %p").lstrip("0").lower()
    if not with_day:
        return clock

    days = (moment.date() - datetime.now().astimezone().date()).days
    if days == 0:
        return clock
    if days == 1:
        return f"{clock} tomorrow"
    return f"{clock} on {moment.strftime('%A')}"


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    start(lambda words: print(f"\n  *** {words} ***"))
    print(add_timer(5, "test"))
    print("Waiting...")
    time.sleep(7)
