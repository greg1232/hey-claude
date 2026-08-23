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
```

## The files

| File | What it does |
|------|--------------|
| `src/main.py` | The loop that ties everything together |
| `src/wake.py` | Waits for the wake word (or the Enter key) |
| `src/audio_in.py` | Microphone — records until you stop talking |
| `src/stt.py` | Turns the recording into words (Whisper, runs locally) |
| `src/brain.py` | Asks Claude and gets the answer |
| `src/tts.py` | Says the answer out loud (macOS `say`, or Piper on Linux) |
| `src/weather.py` | Today's forecast, so it can answer weather questions |
| `src/config.py` | Every setting, in one place |
| `train/test_silence.py` | Checks a wake word doesn't fire in a quiet room |
| `deploy.sh` | Puts the whole thing on a Raspberry Pi |

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
service — then it logs to the journal instead:

```bash
./deploy.sh --service
ssh you@your-pi journalctl -u claude-speaker -f
```

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
