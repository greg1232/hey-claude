# When something goes wrong

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
