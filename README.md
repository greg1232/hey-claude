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
| `src/whisper_wake.py` | The wake word itself, on Whisper's encoder |
| `src/wake_log.py` | Writes down every firing, to learn from |
| `src/audio_in.py` | Microphone — records until you stop talking |
| `src/stt.py` | Turns the recording into words (Whisper, locally) |
| `src/brain.py` | Asks Claude, and runs the tools it asks for |
| `src/tts.py` | Says the answer out loud (macOS `say`, or Piper) |
| `src/lights.py` | The LED ring on the array |
| `src/config.py` | Every setting, in one place |
| **Tools** | |
| `src/tools.py` | The framework: collect, describe, run |
| `src/timers.py` | Timers and alarms, and the ringing |
| `src/weather.py` | The forecast |
| `src/sounds.py` | Rain, ocean, a fire — made as they play |
| `src/effects.py` | Real recordings — what a bullfrog sounds like |
| `src/books.py` | Reads books aloud, and remembers the place |
| `src/music.py` | Spotify — search, play, skip, volume |
| `src/search.py` | Web search, which runs on Anthropic's side |
| `src/enroll.py` | Learns a voice from somebody repeating the wake word |
| `src/wishes.py` | Writes down what it was asked for and can't do |
| **Training and setup** | |
| `train/record_wake.py` | Records people saying the wake word |
| `train/record_room.py` | Records the room not saying it |
| `train/train_whisper_wake.py` | Trains the wake word |
| `train/label_wakes.py` | Decides which logged firings were real |
| `train/relearn.py` | Retrains on them, in about a second |
| `train/test_wake.py` | Checks it hears you |
| `train/test_silence.py` | Checks it doesn't fire in a quiet room |
| `train/build_book_index.py` | Builds the local index of 48,284 books |
| `train/spotify_login.py` | Signs in to Spotify once, for a token |
| `deploy.py` | Puts the whole thing on a Pi (`./deploy.sh` runs it) |
| `wishes.py` | Reads the wishes off the Pi (`./wishes.sh` runs it) |
| `label.py` | Listen to what woke it and say if it was right (`./label.sh`) |
| `relearn.py` | Make it learn from today, now (`./relearn.sh` runs it) |
| `backup.py` | Copies what it has learned off the Pi (`./backup.sh`) |

Only `brain.py`, `weather.py`, `effects.py`, `books.py` and `music.py` use
the internet. The microphone, the wake word, the speech recognition and the
voice all run on the machine itself.

## What it can do

```
"hey claude, why is the sky blue"
"hey claude, set a timer for ten minutes"
"hey claude, wake me up at seven"
"hey claude, what's the weather on Thursday"
"hey claude, who won the game last night"      <- searches the web
"hey claude, play rain until the morning"
"hey claude, what does a bullfrog say"
"hey claude, read me Treasure Island"
"hey claude, play Baby Shark"
"hey claude, learn my voice"
"hey claude, can you keep score for our game"    <- writes down a wish
```

Each is a tool. See **[docs/capabilities.md](docs/capabilities.md)** for
what each one does and how to set the ones up that need keys.

## The documentation

| | |
|---|---|
| **[docs/capabilities.md](docs/capabilities.md)** | Everything it can do, and the settings for each |
| **[docs/tools.md](docs/tools.md)** | How tools work, and how to add one |
| **[docs/wake-word.md](docs/wake-word.md)** | Why the obvious library didn't work, and what does |
| **[docs/raspberry-pi.md](docs/raspberry-pi.md)** | Deploying, the services, the microphone array, the voice |
| **[docs/troubleshooting.md](docs/troubleshooting.md)** | When something goes wrong |
| **[docs/design.md](docs/design.md)** | The original plan, kept as written |

## What's next

Not built, roughly in order of how much they'd improve an evening with it:

- **A follow-up window.** Keep listening for a few seconds after answering,
  so a conversation doesn't need the wake word every turn. The single
  biggest change to how it feels to use.
- **Barge-in.** You can't interrupt it mid-answer: incoming audio is thrown
  away while it talks. Unusually, this speaker *could* — the array cancels
  its own output in hardware, which is the same trick that lets the wake
  word be heard over rain.
- **More nights of wake-word data.** The learning loop works and one night
  of negatives is not enough to generalise; see
  [docs/wake-word.md](docs/wake-word.md).
- **Memory between runs.** It forgets everything when it restarts,
  including who it is talking to.
- **Children's speech.** `tiny.en` is where small Whisper models struggle
  most, and a misheard question is indistinguishable from a dumb answer.
