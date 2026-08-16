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

Press Ctrl-C to stop.

## Trying one piece at a time

Each file runs on its own, which makes it easy to find what's broken:

```bash
python src/tts.py            # 1. make the laptop talk
python src/brain.py          # 2. type a question, hear Claude answer
python src/audio_in.py       # 3. record you until you stop talking
python src/stt.py            # 4. record you and print what it heard
python src/wake.py           # 5. wake up three times, then stop
```

## The files

| File | What it does |
|------|--------------|
| `src/main.py` | The loop that ties everything together |
| `src/wake.py` | Waits for the wake word (or the Enter key) |
| `src/audio_in.py` | Microphone — records until you stop talking |
| `src/stt.py` | Turns the recording into words (Whisper, runs locally) |
| `src/brain.py` | Asks Claude and gets the answer |
| `src/tts.py` | Says the answer out loud (macOS `say`) |
| `src/weather.py` | Today's forecast, so it can answer weather questions |
| `src/config.py` | Every setting, in one place |
| `train/test_silence.py` | Checks a wake word doesn't fire in a quiet room |

Only `brain.py` and `weather.py` use the internet. The microphone, the wake
word, and the speech recognition all run on the laptop.

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

The design says "Hey Claude", and that's still the goal — but openWakeWord
only ships a handful of pre-trained wake words, and "Hey Claude" isn't one
of them. Until you train it, the speaker listens for **"hey jarvis"**.

A trained one ships in `models/hey_claude.onnx` — set `WAKE_MODEL=hey_claude.onnx`
in `.env` to use it. It's also on the Hub as
[gdiamos/hey-claude](https://huggingface.co/gdiamos/hey-claude).

It stays silent in an empty room — 180 seconds on a real microphone, worst
score 0.001 — and ignores ordinary speech. Two things to know: it's strict,
so say the phrase clearly (try `WAKE_THRESHOLD=0.3` if it misses you), and it
false-wakes on **"hey clyde"**.

Check it on your own microphone before trusting it:

```bash
python train/test_silence.py models/hey_claude.onnx --seconds 180
```

**To train your own: see [docs/training-hey-claude.md](docs/training-hey-claude.md).**
It runs entirely on this laptop — no Colab, no GPU — in about **5 GB of
downloads and 80 minutes**, and you never have to say the phrase into a
microphone yourself.

Other options, both in `.env`:

```
WAKE_MODEL=alexa      # built-in choices: hey_jarvis, alexa, hey_mycroft
WAKE_MODE=key         # skip the wake word — press Enter to talk instead
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

**It talks too fast, or the voice is annoying.**
`SPEECH_RATE=150` to slow down. `say -v '?'` lists every voice; set `VOICE=`
to any of them.

**"No API key found."**
You skipped step 2 — `cp .env.example .env` and paste your key in.

## What's next

Not built yet, in rough order of fun:

- Play music by voice (Spotify — see §5 of the design doc)
- Weather, timers, web search
- Remember conversations between runs
- A light that shows when it's listening
- Move it onto a Raspberry Pi so it's a real box on a shelf
