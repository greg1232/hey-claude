# Claude Speaker

A speaker you talk to, and it talks back.

Say the wake word, ask a question out loud, and it answers out loud. It runs
on a laptop, and properly on a Raspberry Pi with a microphone array.

```
 you ──"hey claude"──►  wake word  ──►  record  ──►  Whisper  ──►  Claude
                                                                     │
 you  ◄────── speakers ◄────── Piper ◄─────────── tools ◄────────────┘
                                                  timers, rain, books,
                                                  music, the weather…
```

Everything up to Claude runs on the machine itself: the wake word, the
speech recognition and the voice. Nothing is sent anywhere until there's a
question to ask.

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

Press Ctrl-C to stop. On the Pi it runs as a service, and `./start.sh`
starts, stops and reports on that — see
[docs/raspberry-pi.md](docs/raspberry-pi.md).

## Living with it

Five commands, all from this folder on the laptop:

```bash
./deploy.sh              # put the current code on the Pi
./start.sh --status      # (on the Pi) is it running
./wishes.sh              # what it was asked for and couldn't do
./label.sh               # listen to what woke it, and say if it was right
./relearn.sh             # teach it from today — it also runs itself at 4am
./evaluate.sh            # how good is the wake word, really
                         # and http://<the pi>:8080 for the dashboard
./evaluate.sh --compare  # which training recipe is actually better
```

`./label.sh` is the one worth a few minutes a week. It plays back the clips
that woke the speaker and you answer yes or no; those answers are what the
retraining is judged against, and they are the only ground truth the
project has. See [docs/wake-word.md](docs/wake-word.md).

## Trying one piece at a time

Each file runs on its own, which makes it easy to find what's broken:

```bash
python src/tts.py            # 1. make it talk
python src/brain.py          # 2. type a question, hear Claude answer
python src/audio_in.py       # 3. record you until you stop talking
python src/stt.py            # 4. record you and print what it heard
python src/wake.py           # 5. wake up three times, then stop
python src/config.py         #    print every setting it will actually use
python src/tools.py          #    list every tool Claude is offered
python src/sounds.py rain    #    a sound made from filtered noise
python src/effects.py owl    #    look a real recording up and play it
python src/books.py --shelf  #    the children's shelf, from 48,284 books
python src/music.py          #    what Spotify is playing, and where
python src/wake_log.py       #    what has woken it, and how those went
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
| `src/dashboard.py` | A page served from the Pi — state, metrics, Wi-Fi |
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
| `src/eggs.py` | The things it does that nobody told you about |
| `src/wishes.py` | Writes down what it was asked for and can't do |
| **Training and setup** | |
| `train/record_wake.py` | Records people saying the wake word |
| `train/record_room.py` | Records the room not saying it |
| `train/train_whisper_wake.py` | Trains the wake word |
| `train/label_wakes.py` | Decides which logged firings were real |
| `train/relearn.py` | Retrains on them, in about a second |
| `train/evaluate.py` | Measures it on firings it has never seen |
| `train/archive.py` | Commits the data, and stamps the model with it |
| `train/test_wake.py` | Checks it hears you |
| `train/test_silence.py` | Checks it doesn't fire in a quiet room |
| `train/build_book_index.py` | Builds the local index of 48,284 books |
| `train/spotify_login.py` | Signs in to Spotify once, for a token |
| **On the laptop** | |
| `deploy.py` | Puts the whole thing on a Pi (`./deploy.sh` runs it) |
| `start.py` | Starts and stops the service (`./start.sh` runs it) |
| `wishes.py` | Reads the wishes off the Pi (`./wishes.sh` runs it) |
| `label.py` | Listen to what woke it and say if it was right (`./label.sh`) |
| `relearn.py` | Make it learn from today, now (`./relearn.sh` runs it) |


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

There are also ten things it does that aren't written down here, from
Groot to Mark Rober. They're meant to be found by accident; if you need to
know, they're in `src/eggs.py`.

Each is a tool. See **[docs/capabilities.md](docs/capabilities.md)** for
what each one does and how to set the ones up that need keys.

## The documentation

| | |
|---|---|
| **[docs/capabilities.md](docs/capabilities.md)** | Everything it can do, and the settings for each |
| **[docs/tools.md](docs/tools.md)** | How tools work, and how to add one |
| **[docs/wake-word.md](docs/wake-word.md)** | Why the obvious library didn't work, and what does |
| **[docs/raspberry-pi.md](docs/raspberry-pi.md)** | Deploying, the services, the microphone array, the voice |
| **[docs/dashboard.md](docs/dashboard.md)** | The page served from the Pi |
| **[docs/troubleshooting.md](docs/troubleshooting.md)** | When something goes wrong |
| **[docs/design.md](docs/design.md)** | The original plan, kept as written |

## What's next

Not built, roughly in order of how much they'd improve an evening with it:

- **A follow-up window.** Keep listening for a few seconds after answering,
  so a conversation doesn't need the wake word every turn. The single
  biggest change to how it feels to use, and nothing stands in the way.
- **Barge-in.** Half of it exists: "I have spoken" stops it mid-sentence,
  and speech is now cut between tenth-of-a-second blocks. The other half is
  hard — with the microphone left open the speaker's own voice scores 0.991
  against a 0.95 threshold, so it interrupts *itself* on about one sentence
  in four. The fix is training data, and it's free to make: play, record,
  label every window a negative.
- **Human "yes" labels.** The learning loop works and the gate refuses bad
  models, but of 203 answers a person has given, 202 were "no" — which
  measures false wakes and says nothing about recall. Confirming a dozen
  real firings would fix that. See [docs/wake-word.md](docs/wake-word.md).
- **Memory between runs.** It forgets everything when it restarts,
  including who it is talking to.
- **Children's speech.** `tiny.en` is where small Whisper models struggle
  most, and a misheard question is indistinguishable from a dumb answer.
  Fine-tuning on children's speech is unusually well evidenced — around a
  third off the error rate — and the recordings are already in this repo.
