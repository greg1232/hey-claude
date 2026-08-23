# Tools — how the speaker does things

A tool is a Python function Claude can call. `src/tools.py` is only the
framework: collect, describe, run. It knows nothing about timers or rain,
and adding a capability doesn't touch it.

## Adding one

A tool lives in the module that implements it, next to the code it drives.
Two things are needed — the function, and its name in `FEATURES`.

```python
import tools

@tools.tool(
    "Turn the kitchen light on or off.",
    properties={"on": {"type": "boolean", "description": "on or off"}},
    required=["on"],
    says="turn the kitchen light on and off",
)
def set_kitchen_light(on: bool) -> str:
    ...
    return "The kitchen light is on."
```

```python
# src/tools.py
FEATURES = ("timers", "weather", "sounds", "effects", "books", "music",
            "search", "enroll", "kitchen")
```

That is all of it. The API description, the round trip, and the line in the
system prompt telling Claude the speaker can do it all follow.

`says` is what the speaker tells Claude it can do, in the words a person
would use. It is generated from the tools rather than written into the
prompt, because the prompt used to insist there were no timers on the day
timers were added.

## Three rules

**Return a sentence, not a data structure.** Claude reads it and rephrases
it for speaking, so plain English costs nothing and saves a translation
step where things get lost.

**Never raise.** A tool that throws would take the whole answer down with
it. `run()` turns any exception into a sentence saying so, and Claude
passes that on. A broken timer should cost you a timer, not the speaker.

**Be quick.** Everything here happens while somebody stands there waiting.

## A fourth rule, learned the hard way

**Don't ask the caller for something it cannot know.**

`music_volume` originally took a percentage and nothing else. Asked to
"turn it down a bit", Claude had no number to give — and answered *"Turned
it down for you"* having turned nothing down. That is exactly the failure
the system prompt spends a paragraph forbidding, and the cause was the
tool's shape, not the prompt. It takes `up`, `down`, `mute` or a number
now.

A tool that can only be called with something the caller cannot know
invites being talked around.

## Find, then play

Anything that reaches into a library is split in two: `find_book` and
`play_book`, `find_effect` and `play_effect`, `find_music` and
`play_music`. The finder returns candidates and does not choose; Claude
picks by number, or refuses to pick.

Refusing is the case that matters. Asked what a fire engine sounds like and
shown five engines and no siren, saying so and describing it in words is a
better answer than playing a bus.

This came from playing the first result and getting a 1922 jazz record
called *Atlanta Rag* by Cow Cow Davenport when somebody asked what a cow
says.

**Hand over a long list.** Thirty names cost a fraction of a second of
tokens, and picking the real fire engine out of thirty is exactly what
Claude is good at. Three separate bugs came from filtering or sorting
before Claude saw anything:

| what the code did | what it cost |
|---|---|
| required a whole search word in the title | dropped `WWS Fireenginesiren.ogg`, which has no spaces in its name |
| tried fallback words longest first | tried "engine" before "siren", matched a bus, stopped |
| sorted Freesound by rating | returned highly-rated coins and popcorn for "bowling" |

Rank if you like. Don't filter.

## Server-side tools

Web search has no function to run: it happens inside the API, between the
question going out and the answer coming back. `src/search.py` is the whole
feature — it registers a builder that returns a spec, or `None` when the
feature is switched off.

```python
tools.server_tool(spec, says="search the web for things you don't know")
```

## Things that hold the speaker

The microphone array plays and listens through one piece of hardware. Rain
and books close the sound device and reopen it around anything that needs
to talk; music doesn't have to, because PipeWire mixes it and it can simply
duck.

Both register the same way, so every `with sounds.paused():` already in the
code — in `tts.speak`, in the beep, around each turn — quiets them without
knowing they exist:

```python
sounds.also_pause(hold, carry_on)
```

## Seeing what's registered

```
python src/tools.py
```

Prints every tool, its description, and the line Claude is told about what
the speaker can do.

## When there is no tool

The most useful thing that happens to this project is a child asking for
something the speaker cannot do. It is a feature request from the only
person whose opinion counts, in his own words, at the moment he wanted it —
and those used to vanish into "sorry, I can't do that yet".

`make_a_wish` writes them down. On the laptop:

```
./wishes.sh
```

Repeats are folded together and counted, loosely enough that "keep score in
a card game" and "keeping the score for a game" are one wish rather than
two. A thing asked for five times is five times as interesting.

Two things the speaker has to say, not one: that it can't do it *and* that
it has written it down. A child told a flat no stops asking, and asking is
the useful part. That instruction lives in `brain.py`, because the first
version had it only in the tool description and Claude refused the bedroom
light politely without writing anything down.

## Why the speaker doesn't build its own tools

It could. This file is close to a specification a machine can meet, and it
is: given a paragraph and told to read this document, Claude Code wrote
`src/scores.py` — four tools, `says` line, state persisted, a name added to
`FEATURES` — in a sandbox, on the first try, and it worked.

What stops it being wired up is the television. It reaches the speaker's
transcript about fifty times an hour, and every one of those is a sentence
somebody else wrote being read aloud to a machine. The path from "something
was said in this room" to "code was written and run" has to be broken by
something a broadcast cannot cross, and the only reliable such thing is a
person reading a diff.

So the speaker's entire power here is to write a line to a file. Everything
that can execute lives somewhere it cannot reach.
