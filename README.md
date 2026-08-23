# Claude Speaker

A speaker you talk to, and it talks back.

Say the wake word, ask a question out loud, and the laptop answers out loud.
The design is in [docs/design.md](docs/design.md); this file is how to run it.

```
 you ──"hey ..."──►  wake word  ──►  record  ──►  Whisper  ──►  Claude
                                                                  │
 you  ◄────── speakers ◄────── macOS "say" ◄──────────────────────┘
```

## Setup

**1. Install the pieces** (once):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Add your API key:**

```bash
cp .env.example .env
```

Then open `.env` and paste in your key from
[console.anthropic.com](https://console.anthropic.com/settings/keys).
`.env` is in `.gitignore`, so it never gets committed.

**3. Pick the right microphone.** macOS sometimes defaults to a virtual
audio device (BlackHole, Loopback, Zoom) that records what the computer is
*playing* instead of what you're *saying*. Check which one is the default:

```bash
python src/audio_in.py --devices
```

If the one marked `<- default` isn't your real microphone, add a line to
`.env`:

```
INPUT_DEVICE=MacBook Air Microphone
```

**4. Let the terminal use the microphone.** macOS will ask the first time.
If it doesn't, turn it on under
System Settings → Privacy & Security → Microphone.

## Running it

```bash
python src/main.py           # the real thing — say the wake word
python src/main.py --text    # type questions instead of speaking them
```

Press Ctrl-C to stop. On a Raspberry Pi, use `./start.sh` instead — it runs
in the background and writes a log. See
[Putting it on a Raspberry Pi](#putting-it-on-a-raspberry-pi).

## Trying one piece at a time

Each file runs on its own, which makes it easy to find what's broken:

```bash
python src/tts.py            # 1. make the laptop talk
python src/brain.py          # 2. type a question, hear Claude answer
python src/audio_in.py       # 3. record you until you stop talking
python src/stt.py            # 4. record you and print what it heard
python src/wake.py           # 5. wake up three times, then stop
python src/config.py         #    print every setting it will actually use
```

Every script takes `--help`, including the ones in `train/`.

## The files

| File | What it does |
|------|--------------|
| `src/main.py` | The loop that ties everything together |
| `src/wake.py` | Waits for the wake word (or the Enter key) |
| `src/audio_in.py` | Microphone — records until you stop talking |
| `src/stt.py` | Turns the recording into words (Whisper, runs locally) |
| `src/brain.py` | Asks Claude and gets the answer |
| `src/tools.py` | The things it can actually do — timers, weather, search |
| `src/timers.py` | Timers and alarms, and the ringing |
| `src/lights.py` | The LED ring on the array, showing what it's doing |
| `src/sounds.py` | Rain, ocean, a fire — made as they play |
| `src/effects.py` | Real recordings — what a bullfrog sounds like |
| `src/books.py` | Reads books aloud, and remembers the place |
| `src/search.py` | Web search, which runs on Anthropic's side |
| `src/wake_log.py` | Writes down every wake-word firing, to learn from |
| `src/enroll.py` | Learns a voice from somebody repeating the wake word |
| `src/tts.py` | Says the answer out loud (macOS `say`, or Piper on Linux) |
| `src/weather.py` | Today's forecast, so it can answer weather questions |
| `src/config.py` | Every setting, in one place |
| `src/whisper_wake.py` | The wake word, on Whisper's encoder |
| `train/record_wake.py` | Records people saying the wake word |
| `train/record_room.py` | Records the room not saying it |
| `train/train_whisper_wake.py` | Trains the wake word |
| `train/build_book_index.py` | Builds the local index of 48,284 books |
| `train/label_wakes.py` | Decides which logged firings were real |
| `train/relearn.py` | Retrains on them, in about a second |
| `train/test_wake.py` | Checks it hears you |
| `train/test_silence.py` | Checks it doesn't fire in a quiet room |
| `deploy.py` | Puts the whole thing on a Raspberry Pi (`./deploy.sh` runs it) |

Only `brain.py` and `weather.py` use the internet. The microphone, the wake
word, and the speech recognition all run on the laptop.

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

## About the wake word

The speaker listens for **"hey Claude"** using `models/hey_claude_whisper.npz`
— a classifier on top of Whisper's encoder. Set in `.env`:

```
WAKE_MODEL=hey_claude_whisper.npz
WAKE_THRESHOLD=0.99
```

### Why not openWakeWord

The project started with [openWakeWord](https://github.com/dscripka/openWakeWord),
and there's a trained model here for it (`models/hey_claude.onnx`, also on
the Hub as [gdiamos/hey-claude](https://huggingface.co/gdiamos/hey-claude)).
It scores 0.99 on the synthetic speech it was trained on. On real people it
scored **0.001**, and woke on 7 recordings out of 80.

Recording 80 real utterances from four people fixed that — 9% to 80% — and
broke false wakes instead: about 180 an hour on the real microphone.
Recording 40 minutes of the actual room cut that twelvefold. Widening the
head from 32 to 96 units lifted the whole curve. None of it broke the
underlying problem, which was that recall and false wakes moved together at
every threshold: the model was sliding one operating point rather than
telling two things apart.

The reason is in the shape of the thing. openWakeWord is a mel filterbank,
a **frozen 0.33M parameter CNN from 2020**, and a small head you train.
Measured on this Pi:

| stage | per 80 ms chunk | share |
|---|---|---|
| melspectrogram | 0.95 ms | 7% |
| frozen embedding CNN | 11.75 ms | **91%** |
| the head you train | 0.18 ms | **1%** |

Everything tunable is 1% of the compute. If the frozen 91% doesn't
distinguish your family saying "hey Claude" from your family saying
anything else, nothing on top can recover it — and it doesn't.

### Whisper's encoder instead

Whisper's `tiny.en` encoder was trained on a great deal more speech. Feed it
a two second window, keep the first 100 frames, mean and max pool, and put
a logistic regression on top. Same recordings, same room:

| | openWakeWord, best | **Whisper encoder** |
|---|---|---|
| recall at ~55 false wakes/hr | 42% | **84%** |
| recall at ~125 false wakes/hr | 59% | **91%** |
| cost on a Pi 4 | 0.16x realtime | 0.42x realtime |

Double the recall for two and a half times the compute, which a Pi 4 has to
spare — about 10% of the machine, leaving three cores for Whisper and the
voice. The trained part is 11 kB.

Two lessons are baked into `train/train_whisper_wake.py`, both learned the
hard way:

- **Negatives must include speech that isn't the wake word.** Trained
  against room noise alone it reached 94% recall and zero false wakes —
  by learning "somebody is talking". It fired on 86% of other spoken
  phrases.
- **Score it the way it runs.** Isolated clips gave 0 false wakes; sliding
  a window over the same audio continuously gave 391 an hour. A streaming
  detector has to be measured streaming.

### Making your own

```bash
python train/record_wake.py --speaker greg,ojas,tejas,ana --times 20
python train/record_room.py --minutes 30 --label tv
python train/train_whisper_wake.py
```

Record on the machine the speaker lives on, through its microphone. Twenty
utterances each from four people and forty minutes of room is enough. Say
it varied — closer, further, mumbled — and record the room at its noisiest,
television included. Then check it:

```bash
python train/test_wake.py models/hey_claude_whisper.npz --times 6
python train/test_silence.py models/hey_claude.onnx --seconds 180
```

**The openWakeWord models are still here** — `models/hey_claude.onnx` (also
on the Hub as [gdiamos/hey-claude](https://huggingface.co/gdiamos/hey-claude))
and `models/hey_claude-96.onnx`, the best one this project produced. Either
still loads if you set `WAKE_MODEL` to it. The pipeline that trained them —
5 GB of downloads, 80 minutes, and 2,200 lines — was removed once the
Whisper wake word beat it on every measurement. It's in the git history if
you want it back.

Other options, both in `.env`:

```
WAKE_MODEL=alexa      # openWakeWord's built-ins: hey_jarvis, alexa, hey_mycroft
WAKE_MODE=key         # skip the wake word — press Enter to talk instead
```

## Putting it on a Raspberry Pi

A laptop is a fine place to build this, but a speaker belongs on a shelf.

```bash
./deploy.sh normal@192.168.4.95    # the first time — it remembers the address
./deploy.sh                        # every time after that
./deploy.sh --service              # ...and start it on every boot
```

It copies the code, installs what the Pi needs, sends your API key over the
SSH connection into a file only you can read, and downloads the voice. Run
it as often as you like — it only redoes what changed. The first run takes
a few minutes; later ones take seconds.

Two settings are rewritten on the way over, because the Pi isn't a Mac:

| | on the laptop | on the Pi |
|---|---|---|
| Voice | macOS `say` | Piper, `en_GB-alan-medium` |
| Speech recognition | `base.en` | `tiny.en` — a Pi 4 is slower |

Everything else — your key, your town, the wake word — carries over as is.
To write the Pi's settings by hand instead, make a `.env.pi` file and that
gets sent untouched.

### Starting it, and where it prints to

```bash
cd ~/claude-speaker
./start.sh              # start it in the background
./start.sh --status     # is it running, and where's the log
./start.sh --stop       # stop it
tail -f speaker.log     # watch what it hears and says
```

`./start.sh` returns straight away, so closing the terminal or dropping the
SSH connection doesn't take the speaker with it. Everything it prints goes
to `speaker.log` in the project folder, unbuffered, so `tail -f` shows each
question as it's asked rather than in a lump twenty minutes later. The
previous run is kept as `speaker.log.1` — when something dies overnight,
the restart is what you notice, and it mustn't erase the reason.

It won't start twice. On a microphone array, playing and listening are the
same piece of hardware and it allows a single stream, so a second speaker
doesn't share the microphone — it fails, or quietly steals it.

Two other ways to run it, both staying in your terminal:

```bash
./start.sh --foreground   # watch it directly, Ctrl-C to stop
./start.sh --text         # type questions instead of speaking them
```

`./deploy.sh` restarts a running speaker for you, so deployed code actually
takes effect. For it to come back after a power cut, install it as a
service:

```bash
./deploy.sh --service
ssh you@your-pi journalctl --user-unit=claude-speaker -f
ssh you@your-pi systemctl --user restart claude-speaker
```

It's a **user** service, not a system one, so none of this needs a
password. `systemctl --user` doesn't need root, and `loginctl
enable-linger` — which you can also run for yourself — is what makes it
start at boot with nobody logged in. The speaker has no reason to be root:
it needs the audio group, which you're already in.

The only thing that ever wants `sudo` is installing system packages on a
brand new Pi, which happens once. `./deploy.sh --no-apt` skips even that.

### The microphone array

The Pi in this project uses a **reSpeaker XVF3800 4-Mic Array**, which suits
it well: it captures at 16 kHz, which is exactly the rate the wake word and
Whisper both want, so nothing is resampled on the way in. It also does
beamforming and echo cancellation on its own chip.

It's a speaker as well as a microphone. If your speakers are wired into the
array rather than the Pi's headphone socket, use it for both:

```
INPUT_DEVICE=
OUTPUT_DEVICE=Array
```

That's worth doing — the array cancels its own output in hardware, so it
genuinely doesn't hear Claude talking.

It also arrives **turned down about 20 dB** — `PCM Playback Volume` set to
37 of 60, on a scale where 60 is 0 dB. That's quiet enough to read as a
broken speaker rather than a quiet one, and no amount of software gain
fixes it, because Piper already peaks at full scale. So the speaker sets
its own volume at every startup:

```
OUTPUT_VOLUME=100
```

It happens at startup rather than at install time because mixer levels
don't reliably survive a reboot. Turn it down if it's too much at night, or
leave it blank to not touch the system mixer at all. The catch is that it only accepts
16 kHz, and Piper's voices come out at 22.05 kHz, so `tts.py` resamples on
the way out. Two things follow from it being one piece of hardware: only
one stream can be open at a time, which is why `tts.py` closes the device
after every sound rather than leaving a player running.

### The voice on the Pi

macOS has `say` built in; Linux has nothing, so the Pi speaks with
[Piper](https://rhasspy.github.io/piper-samples/) — a small neural voice
that runs locally, like everything else here.

Measured on this Pi 4, synthesising a two-sentence answer:

| voice | compute per second of speech |
|---|---|
| `en_GB-alan-medium` | 0.31x — three times faster than real time |
| `en_US-ryan-medium` | 0.32x |
| `en_US-ryan-high` | 2.0x — slower than talking, so don't |

Stick to a **medium** voice. Loading one takes about five seconds, so it's
loaded once at startup and kept, not reloaded per answer.

The bigger expressive models — Chatterbox and its kind — can't go here at
all: over 3 GB of weights against the Pi's 3.8 GB of memory, before Python
has even started, and minutes per sentence on four Arm cores.

Pick a different one with `PIPER_VOICE` in `.env`, and choose which socket
the sound comes out of with `OUTPUT_DEVICE`:

```bash
python src/tts.py --devices     # lists the speakers it can see
```

That last one matters on a Pi: ALSA lists the HDMI outputs first, so the
default is often a monitor rather than your actual speakers.


**The pause between sentences.** Piper makes one chunk per sentence, and on
a Pi each takes about six tenths of a second to make — half as long as the
sentence lasts. Written straight to the sound device that time is dead air,
because `stream.write()` blocks until the audio has played out, so nothing
is being synthesised while anything is being said. That was the long pause
after every full stop: not the voice taking a breath, the Pi thinking.

One thread now makes the sound and another plays it, so the next sentence
is ready well before the current one ends. The silence Piper leaves at both
ends of a chunk is trimmed and replaced with a gap you choose. Measured on
the Pi, a three sentence answer:

```
write-as-you-go   4.95s
thread ahead      4.13s
```

```
SENTENCE_PAUSE=0.12
```

## Where to put the threshold

Held out entirely, the wake word catches 52% of one child's attempts, and
that number moves a lot with the threshold:

```
 threshold   recall, unseen voice   recall, known voices   room false/hr
     0.50            66%                   100%                 0.0
     0.80            55%                   100%                 0.0
     0.90            52%                    94%                 0.0
     0.99            38%                    58%                 0.0
```

It shipped at 0.99, which was throwing away nearly half the recall for
nothing measurable. It is 0.80 now. Two caveats on that table: the room
negatives were hard-mined against this same model, so `0.0/hr` is
optimistic — the real room gave about forty an hour at 0.99 — and the
"known voices" column is partly memorisation. The held-out column is the
honest one, and the shape is the point.

What makes a low threshold affordable is that a false wake is now silent.
It used to apologise out loud to an empty room; now nothing said means
nothing spoken, and television speech gets `(nothing)` back from Claude. A
false wake costs a flash of the LED ring and some CPU.

### Why there's no second-stage verifier

The obvious idea is to propose at a low threshold and confirm with a
stronger model. It doesn't work, and the way it fails is worth writing
down.

Whisper cannot transcribe the wake word at all. Against 80 real recordings
of four people saying "hey Claude":

```
tiny.en   4/80 =  5%
base.en  13/80 = 16%
```

It hears "It's hot", "Take that", "Great class", "Thank God" — all the
right rhythm and roughly the right vowels. The acoustics are fine and the
language model overrules them, because "Claude" is rare and "take that" is
common.

Biasing the decoder with `initial_prompt="Hey Claude."` takes tiny.en from
0% to 97%, and makes it three times faster. It also makes it say "Hey
Claude" on **58% of room noise and 55% of ordinary speech**. It isn't
recognising the phrase, it's repeating the prompt. `hotwords="Claude"` is
weaker in both directions, 63% on real ones, and not worth it either.

Which is a decent independent argument that the 768-number classifier is
doing real work a general speech model won't do for free.

## Teaching it your voice

```
"hey claude, I want to teach you what my voice sounds like"
"Say hey Claude about ten times while the light is purple, with a
 pause between each, and it'll go out when I've got enough."
"hey claude ... hey claude ... hey claude ..."
"Got eight. Give me a moment to learn them."
```

Nobody labels anything. The person was asked to repeat the wake word, so
every segment is the wake word by construction. That is the whole trick,
and it's the only cure for recall that doesn't involve sitting down with a
laptop and `record_wake.py`.

**The ring is the interface.** A spoken "stop when you're done" would be
recorded along with the repetitions, so the light has to carry it: purple
while listening, out when it has enough.

**It has to be able to reject rubbish**, since it is about to train on
whatever it heard. Each segment becomes the same 768 numbers the detector
scores, and anything that doesn't resemble the others is dropped — a
cough, a chair, a sibling shouting. That comparison must be made on
*standardised* vectors. Raw Whisper features share a large common
component and everything looks alike: a burst of noise scored 0.905
against real repetitions' 0.965, which is not a gap you can cut on.
Subtract the model's own mean and divide by its scale, and the same burst
falls to 0.09 against 0.62–0.81.

What it must *not* do is filter on the wake score. The repetitions worth
learning from are exactly the ones the model currently misses — two of
seven in testing scored 0.42 and 0.01 — so scoring them would keep only
what already works.

**Each repetition is then slid around the window**, six times, using the
pauses between the repetitions as room noise. The recording brings its own
backgrounds, which means this works on a machine with no room-noise
library. Measured on a voice the model had never met:

```
never met them             55% recall at threshold 0.8
8 recordings as they came  59%
8 placed at 6 offsets      64%
```

with no change in false wakes. That is the honest size of it: a few points
of recall, not a transformation. The features are frozen, and 48 new
examples against a bank of 2708 can only move a linear model so far. It
stacks with the threshold, which is the bigger lever.

Then it refits (under a second) and reloads the four small arrays without
touching the 56 MB encoder, so it takes effect while you're standing
there.

## Learning from its own mistakes

The wake word is wrong about forty times an hour with a television on, and
every one of those is a labelled training example nobody had to record. The
speaker keeps them.

```
python src/wake_log.py         what has fired, and how those turns went
python train/label_wakes.py    decide which were real
python train/relearn.py        fit a new model on them
```

**The vector is free.** When the wake word fires, the detector has just
turned two seconds of audio into 768 numbers — that encoder pass is 159 ms
on a Pi and is the entire cost of the wake word. Those numbers are what
retraining needs, so they are written down (1.5 kB) along with the audio
(64 kB, most recent 400 only, because this is an SD card).

**The label is nearly free too.** A firing followed by silence is almost
certainly a mistake; one followed by a question that got answered is almost
certainly real. The speaker works both of those out anyway while answering.

**The judge is better than the thing being judged.** `label_wakes.py`
transcribes the two seconds that fired with a *bigger* Whisper than the Pi
listens with — `small.en` against `tiny.en`, beam 5 against beam 1 — on a
laptop, with nothing waiting on it. If the window transcribes to something
that sounds like "hey Claude", it was real. Only what's left over goes to
Claude, in batches of twenty, with both transcripts and the time of day.

Claude cannot listen to the clip itself. The API takes text, images and
PDFs and rejects audio outright — tested, not assumed — so a transcript is
the way in, which is why it's worth making a good one.

**Retraining costs a second.** Not twenty minutes, because it never touches
audio: it joins the feature bank `train_whisper_wake.py` saved with the
logged vectors and fits. Measured on a Pi 4:

```
logistic regression, 30,000 x 768   0.67s
the same features from audio        159ms each, about 20 minutes
```

So the whole loop can run on the Pi, overnight, on data the Pi collected.
Logged examples are weighted above bank ones (`--weight 3`) because the
bank is a general model of the world and the log is the actual room.

`relearn.py` prints how the old and new models score on the logged firings
before writing anything, keeps the model it replaced as `.npz.previous`,
and `--dry` writes nothing at all.

```
WAKE_LOG=off
WAKE_LOG_CLIPS=400
```

## When something goes wrong

**It doesn't hear me / recording is silent.**
Almost always the wrong microphone. Run `python src/audio_in.py --devices`
and set `INPUT_DEVICE` in `.env`.

**It wakes up when nobody said anything.**
Measure it first — `python train/test_silence.py models/hey_claude.onnx
--seconds 180`. If that fails, the model never learned what a quiet room is
and needs retraining with more negative data; raising `WAKE_THRESHOLD` only
hides it. If it passes, something in the room is setting it off, and 0.7 is
a reasonable dial.

**It never wakes up.**
Lower it: `WAKE_THRESHOLD=0.3`. Or use `WAKE_MODE=key` while you sort it out.

**It cuts me off mid-sentence.**
Give yourself more silence before it stops: `SILENCE_SECONDS=1.5`.

**It's too quiet, even with everything turned up.**
Check what the device itself is set to:

```bash
ssh you@your-pi 'amixer -c 3 contents | grep -A3 "Playback Volume"'
```

USB audio often ships attenuated. `OUTPUT_VOLUME` in `.env` handles this on
every startup; if you've set it blank, this is why it's quiet.

**It talks too fast, or the voice is annoying.**
`SPEECH_RATE=150` to slow down. On a Mac, `say -v '?'` lists every voice;
set `VOICE=`. On the Pi, set `PIPER_VOICE=` — the choices are at
[rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/).

**The Pi is silent, or talks out of the wrong socket.**
`python src/tts.py --devices` lists what it can see, then set
`OUTPUT_DEVICE=Headphones` (or whichever) in `.env`. ALSA puts the HDMI
outputs first, so the default is often a monitor with no speakers.

**The Pi can't hear anything.**
Check the hardware before blaming the code:

```bash
ssh you@your-pi arecord -l
```

No capture devices means nothing is reaching the Pi at all — a USB mic
should appear in `lsusb`, and an I2S mic HAT needs a `dtoverlay=` line in
`/boot/firmware/config.txt` before it shows up.

If the microphone *is* listed, try recording from it directly:

```bash
ssh you@your-pi 'arecord -D plughw:3,0 -f S16_LE -r 16000 -c 2 -d 3 /tmp/c.wav; ls -l /tmp/c.wav'
```

Three seconds should be about 192 KB. **44 bytes and `read error:
Input/output error` means the device enumerates but won't stream** — which
on a Pi 4 is often just the socket. Moving the array from a black USB 2
port to a blue USB 3 one fixed it here, with no other change. Worth trying
before anything else, because every symptom above it looks like a software
fault and isn't.

**"No API key found."**
You skipped step 2 — `cp .env.example .env` and paste your key in.

## What's next

Not built yet, in rough order of fun:

- Play music by voice (Spotify — see §5 of the design doc)
- Weather, timers, web search
- Remember conversations between runs
- A light that shows when it's listening
