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
| `src/config.py` | Every setting, in one place |

Only `brain.py` uses the internet. The microphone, the wake word, and the
speech recognition all run on the laptop.

## About the wake word

The design says "Hey Claude", and that's still the goal — but openWakeWord
only ships a handful of pre-trained wake words, and "Hey Claude" isn't one
of them. Until you train it, the speaker listens for **"hey jarvis"**.

A trained one ships in `models/hey_claude.onnx` — set `WAKE_MODEL=hey_claude.onnx`
in `.env` to use it. It's also on the Hub as
[gdiamos/hey-claude](https://huggingface.co/gdiamos/hey-claude).

It wakes on "hey claude" at 0.997 and stays under 0.005 on ordinary speech.
Two things to know: it doesn't suit every voice equally (three of five test
voices wake it strongly), and "hey clyde" reaches 0.484 — under the 0.5
threshold, but the closest call by far. `hey_jarvis` is still the default
until it's been lived with for a while.

**To train your own: see [docs/training-hey-claude.md](docs/training-hey-claude.md).**
It runs entirely on this laptop — no Colab, no GPU — in about **1 GB of
downloads and an hour**, and you never have to say the phrase into a
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
Raise the confidence needed: `WAKE_THRESHOLD=0.7` in `.env`.

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
