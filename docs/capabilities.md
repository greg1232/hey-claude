# What the speaker can do

Everything here is a tool Claude can call. It is given the list with every
question, picks one if the question needs it, and we run it and hand the
result back; the person hears one answer and never sees the round trip.

For how that works and how to add another, see [tools.md](tools.md).

## What it can do

Ask it anything and it answers. Four things it can also *do*, rather than
just talk about:

```
"hey claude set a timer for ten minutes"
"hey claude wake me up at seven"
"hey claude what timers do I have"
"hey claude what's the weather on Thursday"
"hey claude who won the game last night"        <- searches the web
"hey claude play rain until the morning"
```

Each of those is a tool. Claude is given the list with every question,
picks one if the question needs it, and we run it and hand back the result;
the person hears one answer and never sees the round trip.

`src/tools.py` is only the framework — collect, describe, run. A tool lives
next to the code it drives: `timers.py` owns the timer tools, `sounds.py`
owns the ones that play rain. Adding a capability is a module and a name in
`FEATURES`; the line in the system prompt telling Claude what the speaker
can do is generated from the tools, so it can't fall out of step with what
is actually registered.

Two things worth knowing:

**Timers ring on their own thread**, which makes them the only part of the
speaker that talks first. A timer that comes due while somebody is asking
something waits for the answer to finish. It has to: the microphone array
is one device, and a chime during the recording gets transcribed as a word
in the middle of the question.

**A finished timer rings for thirty seconds**, and says the wake word is
how you stop it. The ringing is broken into short beeps with two and a half
second gaps, and the gaps are the point: while the speaker is playing,
incoming audio is thrown away so it can't hear itself, so a timer that rang
solidly for half a minute would be deaf for the whole of it. Catching the
wake word in a gap isn't guaranteed — the wake word wants a two second
window and only the tail of each gap is clear. The hard guarantee is the
other end: it always stops itself after `RING_SECONDS`.

**Alarms survive a reboot, timers don't.** Somebody who sets a seven
o'clock alarm means it. A ten minute timer is about something happening
right now, and an hour later it's just confusing.

### The LED ring

The array has twelve LEDs round it, and they say what the speaker is doing:

| | |
|---|---|
| dark | waiting for the wake word |
| blue | listening to your question |
| blue, breathing | thinking about it |
| green | talking back |
| red, fast | a timer is going off |

Sound can't do this job on its own. The beep says it woke up, but it can't
keep saying it's *still* listening, and it can't say anything at all while
you're talking — which is exactly when you want to know.

`src/lights.py` speaks the array's USB protocol directly: a vendor control
transfer, request 0, wValue the command, wIndex the resource. The whole LED
interface is five commands, which is a lot less than Seeed's 1.8 MB
`xvf_host` binary or their 400-line script. The firmware runs the
animations itself, so a breathing ring costs one USB message rather than a
thread here redrawing it.

The array's USB node belongs to root, so this needs a udev rule to work
without sudo — `./deploy.sh` installs one (the same bargain as the systemd
user service: hand the thing to a group the user is already in, rather than
becoming root). Without the rule you get one "Access denied" line and the
lights stay off; everything else works. That's the rule for this whole
file, in fact. A voice assistant should not stop working because a light
didn't.

```
LEDS=off
LED_BRIGHTNESS=40
```

### Background sounds

```
"hey claude play rain"
"hey claude put the ocean on for an hour"
"hey claude stop"
```

Rain, ocean, fireplace, fan, and white, pink and brown noise — up to 24
hours. **Nothing here is a recording.** Every sound is made as it plays,
from filtered noise, which is the right answer on a Pi for three reasons:
no files to download or license, no memory to hold them in, and no seam. A
looped recording ticks every time it comes round, and a child lying awake
listening for the tick will find it.

Two things had to be solved to make this work at all.

**The array plays and listens through one piece of hardware**, and allows
exactly one stream at a time — so eight hours of rain would otherwise be
eight hours of a speaker that can't answer. Everything that makes a noise
wraps itself in `sounds.paused()`, which closes the stream and reopens it
afterwards, carrying on mid-sound because the filter state is kept. The
count is kept too, so a beep inside an answer inside a turn nests safely.

**Audio arriving while the speaker talks is normally thrown away**, or it
wakes itself up. That rule can't apply here or the speaker would be deaf
all night, so the ambience deliberately doesn't set `tts.speaking` — the
wake word runs on a microphone that can hear the rain. It works because the
array cancels its own output in hardware. Measured on the Pi:

```
                  mic level (median RMS)   highest wake score in 30s
nothing playing              1454                    0.93
rain playing                  664                    0.84     (fires at 0.99)
```

So the rain doesn't trip the wake word, and the room is still audible
through it. Whether it's audible *enough* to catch "hey claude" from across
a bedroom is the part only a person can test.

```
SOUND_VOLUME=0.30
SOUND_HOURS=8
```

### Books

```
"hey claude, read me Treasure Island"
"hey claude, next chapter"
"hey claude, stop"
       ...the next evening...
"hey claude, read me Treasure Island"    -> carries on from chapter five
```

**LibriVox first.** Twenty thousand public-domain books read aloud by human
volunteers, free, no key. For a bedtime story that beats Piper outright — a
real voice for two hours instead of a very good two-sentence voice stretched
over a chapter — and it costs the Pi no synthesis at all. Chapters arrive
pre-split with titles and durations, so "next chapter" is an index lookup.
Measured on the Pi: 0.99x realtime, with the following chapter fetched
while the current one plays so the joins are silent.

**Gutenberg second**, for anything nobody has recorded, read by Piper.

Getting at Gutenberg is the awkward part, and worth writing down because
the obvious routes are all dead:

```
gutenberg.org book text        503 Service Unavailable
gutenberg.org pg_catalog.csv   504 Gateway Timeout, after 33s
gutendex.com                   timeout, twice
Standard Ebooks OPDS           401 Unauthorized
Hugging Face /search, /filter  500 Internal Server Error
```

So the corpus comes from Hugging Face (`sedthh/gutenberg_english`, 48,284
books, 10.7 GB) and the searching happens here. `train/build_book_index.py`
keeps a **2.4 MB** local index of every title, author and bookshelf, which
is cheap because parquet is columnar: reading just the metadata column out
of a 340 MB file takes 1.7 seconds over HTTP, and 69 seconds for all 37.
Looking a title up needs no network at all; only the book itself is
fetched, in one call, in a second or two.

Gutenberg's own `bookshelves` field is what makes "read me a story" work —
1,323 books on a children's shelf, Alice and Peter Pan and Sleepy Hollow
among them.

**The place is remembered**, written every ten seconds so a power cut costs
seconds rather than an evening, and matched loosely on the way back:
LibriVox files A Tale of Two Cities as "Tale of Two Cities", so an exact
lookup would find nothing and start the book again from the beginning.

### Music

```
"hey claude, play Baby Shark"
"hey claude, skip this one"
"hey claude, turn the music down a bit"
"hey claude, stop the music"
```

Needs **Spotify Premium**: librespot, which does the streaming on the Pi,
cannot play at all on a free account.

Two halves. `librespot` runs as a user service and makes the Pi a Spotify
Connect speaker, the same as a Sonos as far as Spotify is concerned — **no
Spotify password goes near the Pi**; you pick it once in the phone app,
which is how it gets its credentials, and they are cached after. `music.py`
is the other half: the Web API, which searches and says what to play where.
It never touches audio, so an hour of music costs the Pi about as much as
an hour of silence.

Setting it up: make a free app at
[developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
with redirect URI `http://127.0.0.1:8888/callback` (Spotify insists on
127.0.0.1, not localhost), put the id and secret in `.env`, and run
`python train/spotify_login.py` once on a machine with a browser. Then
`./deploy.sh` installs librespot, and you pick "Claude Speaker" in the
Spotify app once.

**Mixing, rather than taking turns.** Everything else here closes the sound
device and reopens it, because the array allows one stream at a time. Music
doesn't have to: `pipewire-alsa` puts PipeWire between the programs and the
hardware, so the music simply gets quieter while the speaker talks and
comes back after — Spotify does the ducking on its own side, in one call.
Installing it had a second benefit nobody was looking for: PortAudio now
offers the voice's own 22 kHz rate, so answers are no longer resampled to
the array's 16 kHz on the way out.

Two things measured rather than assumed: Spotify's search `limit` is
documented as up to 50 and an app in development mode gets 400 "Invalid
limit" above **ten**; and skipping a track answers 200 with a bare tracking
id rather than JSON, which is not an error and must not be read as one.

### Web search

Search runs on Anthropic's side, not on the Pi — Claude searches between
your question going out and the answer coming back, so there's no page
fetched here and no second round trip to pay for. It costs money per
search and adds two or three seconds, so Claude is told to use it only
when the answer really turns on something recent or local. Measured on a
question that didn't need it, 2.9 seconds; on one that did, 5.0.

Turn it off, or change the ceiling on searches per question, in `.env`:

```
WEB_SEARCH=off
WEB_SEARCH_MAX=3
```

## Weather

Set your town in `.env` and it can answer weather questions:

```
LOCATION=Palo Alto, California
```

That's all — the forecast comes from [Open-Meteo](https://open-meteo.com),
which is free and needs no account or API key. Leave `LOCATION` out and the
speaker simply doesn't know the weather; nothing is sent anywhere.

It's fetched in the background and cached for fifteen minutes, so asking
never waits on the network. If the connection is down, it says it doesn't
know rather than hanging.

The point isn't reciting a forecast — it's questions like *"should I wear a
coat?"*, which it can now actually answer.

## Easter eggs

Not written down anywhere the family can find, which is the point — see
`src/eggs.py` if you need to know.

```
"hey claude, I am Groot"            answers only in Groot, for a few turns
"hey claude, expecto patronum"      names your patronus, and plays it
"hey claude, to infinity and…"      finishes the line
"hey claude, do you want to
 build a snowman"                   answers, then offers to play the song
"hey claude, hakuna matata"         no worries — and cancels your timers
"hey claude, flip-o-rama"           a paper flutter, and two frames narrated
"hey claude, this is the way"       answers in kind, then talks like Mando
"hey claude, I have spoken"         stops it dead, mid-sentence
"hey claude, rubble on the double"  starts a timed mission, with a siren
"hey claude, teach me something"    one fact, and the real sound of it
```

Two rules, from noticing which ones are actually fun.

**The good ones do something.** "This is the way" said back is a nice
moment. "I have spoken" stopping the speaker mid-sentence is a magic word
that silences a machine, and a child will remember that for years. "Rubble
on the double" is a tidying timer with a siren on it, which is a chore
disguised as a rescue.

**They have to be findable by accident.** Nobody reads a list of easter
eggs. Somebody says a line they know, something happens, and the speaker
becomes a place where saying film lines is rewarded.

The sayable ones are data — a table in `src/eggs.py` that Claude is shown
along with everything else it knows. The doing ones are two tools,
`stop_everything` and `start_mission`, plus tools that already existed.

`stop_everything` is worth having on its own: it stops talking, reading,
music, background sound and a ringing timer, all at once. Speech is now
cut off between tenth-of-a-second blocks rather than between sentences,
because a sentence is one to three seconds and being interrupted three
seconds later is not being interrupted. Measured: stopped at 1.5s into an
answer that would have run 7.
