# When something goes wrong

## It can't hear me

**Recording is silent, or it never wakes up.** Almost always the wrong
microphone:

```bash
python src/audio_in.py --devices
```

Set `INPUT_DEVICE` in `.env` to the right one. On macOS, a virtual device
(BlackHole, Loopback, Zoom) records what the computer is *playing* rather
than what you are saying, and is often the default.

**On the Pi, check the hardware before the code:**

```bash
ssh you@your-pi arecord -l
```

No capture devices means nothing is reaching the Pi at all — a USB mic
should appear in `lsusb`. Then try recording from it directly:

```bash
ssh you@your-pi 'arecord -D plughw:3,0 -f S16_LE -r 16000 -c 2 -d 3 /tmp/c.wav; ls -l /tmp/c.wav'
```

Three seconds should be about 192 KB. **44 bytes and `read error:
Input/output error` means the device enumerates but won't stream** — which
on a Pi 4 is usually the socket. Move the array from a black USB 2 port to a
blue USB 3 one. Try this first, because every software symptom looks the
same as this hardware one.

**It hears me but ignores me.** Lower `WAKE_THRESHOLD` to 0.3, or set
`WAKE_MODE=key` and press Enter while you sort it out. If it misses one
person in particular, the real fix is "hey Claude, learn my voice" — see
[wake-word.md](wake-word.md).

## It wakes up when nobody said anything

Measure it before turning dials:

```bash
python train/test_silence.py models/hey_claude_whisper.npz --seconds 180
```

If that **fails**, the model never learned what a quiet room is and needs
retraining with more negative data. Raising `WAKE_THRESHOLD` only hides it.

If it **passes**, something in the room is setting it off. Label thirty
clips with `./label.sh` and let the nightly retraining use them; that is
what the whole learning loop is for. Lowering `WAKE_FALSE_BUDGET` moves the
line the next time it fits.

## It cuts me off mid-sentence

`SILENCE_SECONDS=1.5` gives you more silence before it stops listening.
`MIN_RECORD_SECONDS` guards against a slow start; `PRE_ROLL_SECONDS` (0.5)
is how much audio from before the recording starts is kept, so running
straight from the wake word into the question doesn't lose the first word.

## Sound problems

**Too quiet, even with everything turned up.** Check what the device is
actually set to:

```bash
ssh you@your-pi 'amixer -c 3 contents | grep -A3 "Playback Volume"'
```

USB audio often ships attenuated, and on the Pi there are *two* gain stages
— the array's own and PipeWire's. `OUTPUT_VOLUME=100` sets both at every
startup; if you have set it blank, this is why it is quiet. See
[raspberry-pi.md](raspberry-pi.md).

**Silent, or talking out of the wrong socket.**

```bash
python src/tts.py --devices
```

Then set `OUTPUT_DEVICE`. ALSA puts the HDMI outputs first, so the default
is often a monitor with no speakers.

**It talks too fast, or the voice grates.** `SPEECH_RATE=150` to slow down.
On a Mac `say -v '?'` lists every voice, then set `VOICE`. On the Pi set
`PIPER_VOICE` from
[rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/)
— and keep to a *medium* voice, because a *high* one synthesises slower than
it speaks.

**Long pauses between sentences, or it falls behind itself.** You are on a
`high` Piper voice. Switch to `medium`.

## Setup problems

**"No API key found."** You skipped step 2 — `cp .env.example .env` and
paste your key in.

**A setting seems to be ignored.** Print what it will actually use:

```bash
python src/config.py
```

`.env` overrides the defaults and a typo in a name is silent. Note that two
training settings — `WAKE_FIT_C` and `WAKE_FALSE_BUDGET` — are read by
`train/relearn.py` and will not appear here.

**A capability is missing.** One feature module that fails to import doesn't
take the others down; it prints `[tools] <name> unavailable:` at startup.
Check with `python src/tools.py`, which lists what actually registered.

**Music doesn't play.** Spotify Premium is required — librespot cannot play
on a free account at all. Check the service with
`systemctl --user status librespot`.

**The dashboard isn't there.** It is on port 8080 unless `DASHBOARD_PORT`
says otherwise, and `DASHBOARD=off` disables it. If it failed to start the
speaker carries on without it by design, so look in
`journalctl --user-unit=claude-speaker`.
