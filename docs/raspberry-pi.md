# Putting it on a Raspberry Pi

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
