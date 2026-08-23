"""Tools — the things the speaker can actually do, not just talk about.

Claude gets a list of these with every question. If a question needs one,
Claude asks for it by name, we run it here, hand back what happened, and
Claude turns that into a sentence to say out loud. The person hears one
answer; the round trip is invisible.

Adding a tool is one function and one decorator:

    @tool("Turn the kitchen light on or off.",
          properties={"on": {"type": "boolean", "description": "..."}},
          required=["on"])
    def set_kitchen_light(on: bool) -> str:
        ...
        return "The kitchen light is on."

Three rules for the ones that live here:

  Return a sentence, not a data structure. Claude reads it and rephrases
  it for speaking, so plain English costs nothing and saves a translation
  step where things get lost.

  Never raise. A tool that throws would take the whole answer down with
  it; run() turns any exception into a sentence saying so, and Claude
  passes that on. A broken timer should cost you a timer, not the speaker.

  Be quick. Everything here happens while somebody stands there waiting.

One tool isn't in this file at all. Web search runs on Anthropic's side:
we declare it, Claude searches, and the results never touch the Pi. See
_search_tool() at the bottom.

    python src/tools.py         list the tools and their descriptions
"""

import json
import sys

import config
import timers
import weather

_REGISTRY: dict[str, "Tool"] = {}


class Tool:
    """One thing the speaker can do."""

    def __init__(self, name, description, properties, required, run):
        self.name = name
        self.description = description
        self.properties = properties
        self.required = required
        self.run = run

    def spec(self) -> dict:
        """The shape the API wants."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
            },
        }


def tool(description: str, properties: dict | None = None, required=()):
    """Register a function as something Claude can ask for."""
    def keep(function):
        _REGISTRY[function.__name__] = Tool(
            name=function.__name__,
            description=description,
            properties=properties or {},
            required=required,
            run=function,
        )
        return function
    return keep


# --- the tools --------------------------------------------------------------


@tool(
    "Start a countdown timer. Use this whenever someone asks for a timer, "
    "or to be told when some number of minutes has passed. Work out the "
    "total number of seconds yourself: 'a minute and a half' is 90.",
    properties={
        "seconds": {
            "type": "integer",
            "description": "How long the timer runs, in seconds.",
        },
        "label": {
            "type": "string",
            "description": "What the timer is for, if they said — 'pasta', "
                           "'homework'. Leave empty if they didn't say.",
        },
    },
    required=["seconds"],
)
def set_timer(seconds: int, label: str = "") -> str:
    return timers.add_timer(int(seconds), label.strip())


@tool(
    "Set an alarm for a particular time of day. Use this for 'wake me at "
    "seven' or 'remind me at four o'clock'. Times are 24-hour. If they "
    "didn't say which day, leave the date empty and it takes the next time "
    "that clock time comes round.",
    properties={
        "time": {
            "type": "string",
            "description": "24-hour clock time, like 07:00 or 16:30.",
        },
        "date": {
            "type": "string",
            "description": "The day, as YYYY-MM-DD. Leave empty for the "
                           "next time this clock time happens.",
        },
        "label": {
            "type": "string",
            "description": "What the alarm is for, if they said.",
        },
    },
    required=["time"],
)
def set_alarm(time: str, date: str = "", label: str = "") -> str:
    return timers.add_alarm(time, date, label.strip())


@tool("List every timer and alarm that is currently set, and how long is "
      "left on each.")
def list_timers() -> str:
    return timers.listing()


@tool(
    "Cancel a timer or alarm. Pass the name if they said one, or 'all' to "
    "clear everything.",
    properties={
        "which": {
            "type": "string",
            "description": "The name of the one to cancel, or 'all'.",
        },
    },
)
def cancel_timer(which: str = "all") -> str:
    return timers.cancel(which)


@tool(
    "Look up the weather forecast for where the speaker is. Today's weather "
    "is already in your notes above, so only use this for another day, or "
    "for detail the notes don't have.",
    properties={
        "days_ahead": {
            "type": "integer",
            "description": "0 for today, 1 for tomorrow, up to 6.",
        },
    },
)
def get_weather(days_ahead: int = 0) -> str:
    return weather.forecast(int(days_ahead))


# --- running them -----------------------------------------------------------


def specs() -> list[dict]:
    """Every tool, in the form the API wants, for both kinds."""
    everything = [t.spec() for t in _REGISTRY.values()]
    search = _search_tool()
    if search is not None:
        everything.append(search)
    return everything


def run(name: str, arguments: dict) -> str:
    """Do what Claude asked for, and say what happened.

    Anything can go wrong in here and the answer still comes out — the
    person gets "I couldn't set that timer" instead of silence, which is
    the difference between a bug and a broken speaker.
    """
    found = _REGISTRY.get(name)
    if found is None:
        return f"There is no tool called {name}."

    # Drop anything the model invented that the function doesn't take,
    # rather than failing the whole call on one stray key.
    wanted = {key: value for key, value in (arguments or {}).items()
              if key in found.properties}
    try:
        return str(found.run(**wanted))
    except Exception as error:
        print(f"[tool {name} failed] {type(error).__name__}: {error}")
        return f"That didn't work — {type(error).__name__}."


def summary() -> str:
    """One line naming what the speaker can do, for the system prompt.

    Generated rather than written down, so adding a tool can't leave the
    prompt claiming the speaker still can't do it. That exact mismatch is
    why this file exists: the prompt used to insist there were no timers.
    """
    can = ["set timers", "set alarms", "look up the weather forecast"]
    if _search_tool() is not None:
        can.append("search the web for things you don't know")
    return ", ".join(can[:-1]) + ", and " + can[-1]


# --- web search, which runs on Anthropic's side -----------------------------


def _search_tool() -> dict | None:
    """Declare Claude's own web search, if it's switched on.

    This one is different in kind from the rest of the file. There's no
    function to write: the search happens inside the API, between our
    question going out and the answer coming back, so the Pi never fetches
    a page and there's no second round trip to pay for.

    It is not free, in either sense. Each search costs money, and it adds
    seconds to an answer that a kid is standing there waiting for — so the
    number of searches per question is capped low, and Claude is told in
    the system prompt to use it only when the answer really does depend on
    something recent.
    """
    if not config.WEB_SEARCH:
        return None

    spec = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": config.WEB_SEARCH_MAX,
    }
    # Where we are, so "when does the museum close" doesn't search the
    # other side of the planet. Costs nothing — the weather already asked.
    here = weather.place_hint()
    if here:
        spec["user_location"] = here
    return spec


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    for spec in specs():
        if "input_schema" in spec:
            takes = ", ".join(spec["input_schema"]["properties"]) or "nothing"
            print(f"\n{spec['name']}({takes})")
            print(f"    {spec['description']}")
        else:
            print(f"\n{spec['name']}  (runs on Anthropic's side)")
            print(f"    {json.dumps({k: v for k, v in spec.items() if k != 'name'})}")

    print(f"\nThe speaker can {summary()}.")
