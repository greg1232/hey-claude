"""Text to speech — makes the speaker talk.

Which voice you get depends on the machine, and it's picked automatically:

  macOS          the built-in `say` command. Nothing to install.
  Linux (Pi)     Piper, a small neural voice that runs on the Raspberry Pi
                 itself, with espeak-ng as a last resort.

Piper was chosen for the Pi because it's the only good-sounding text to
speech that comfortably runs faster than real time on four Arm cores: a
medium voice takes about a third of a second of compute per second of
speech. The bigger, more expressive models — Chatterbox and its kind — need
over three gigabytes of weights before Python has even started, which is
more memory than the Pi has, and would take minutes per sentence here.

Hear the macOS voices with:  say -v '?'
Piper's voices:              https://rhasspy.github.io/piper-samples/
"""

import shutil
import subprocess
import sys
import threading

import config

# True while the speaker is talking out loud. The microphone watches this
# so the speaker doesn't hear itself and wake itself up in a loop.
speaking = threading.Event()

MACOS = sys.platform == "darwin"

# A short built-in macOS sound, used as the "I'm listening" beep.
BEEP_SOUND = "/System/Library/Sounds/Tink.aiff"

# Where Piper voices are kept. They're about 63 MB each and downloaded on
# first use, so they live outside the repository.
VOICE_DIR = config.PROJECT_ROOT / "voices"

_voice = None  # The loaded Piper voice, kept in memory between answers.


def warm_up() -> None:
    """Get everything ready before the first question, not during it.

    Loading a Piper voice takes about five seconds on a Raspberry Pi.
    Without this it happens partway through the first thing the speaker
    ever says, which is the worst possible moment for it.
    """
    if MACOS:
        return
    turn_up()
    _piper_voice()


def turn_up() -> None:
    """Set the speaker's own volume to OUTPUT_VOLUME.

    USB audio devices often arrive attenuated. The reSpeaker array came set
    to 37 of 60, on a scale where 60 is 0 dB and 0 is -60 dB — about 20 dB
    down, which sounds like a fault rather than a setting. Nothing can be
    gained in software to make up for it: Piper already peaks at full scale,
    so the only headroom is here.

    This runs at every startup rather than once when the speaker is
    installed, because mixer levels don't reliably survive a reboot — and a
    speaker that goes quiet every time the power blinks is worse than one
    that was never loud.
    """
    if MACOS or not config.OUTPUT_VOLUME.strip():
        return

    card = _output_card()
    if card is None:
        return

    level = config.OUTPUT_VOLUME.strip().rstrip("%") + "%"
    try:
        contents = subprocess.run(
            ["amixer", "-c", card, "contents"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return  # No amixer, or no such card. Not worth failing over.

    for block in contents.split("numid=")[1:]:
        if "Playback Volume" not in block:
            continue
        subprocess.run(
            ["amixer", "-c", card, "cset", "numid=" + block.split(",")[0], level],
            capture_output=True, check=False,
        )


def _output_card() -> str | None:
    """The ALSA card number behind OUTPUT_DEVICE, for amixer to talk to.

    PortAudio's device numbers and ALSA's card numbers are different things,
    so this reads `aplay -l` rather than reusing find_output_device().
    """
    import re

    try:
        listing = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None

    wanted = config.OUTPUT_DEVICE.strip().lower()
    for line in listing.splitlines():
        match = re.match(r"card (\d+):", line)
        if match and (not wanted or wanted in line.lower()):
            return match.group(1)
    return None


def speak(text: str) -> None:
    """Say `text` out loud and wait until it finishes."""
    text = text.strip()
    if not text:
        return

    speaking.set()
    try:
        if MACOS:
            _say_macos(text)
        else:
            _say_linux(text)
    finally:
        speaking.clear()


def beep() -> None:
    """Play the "I'm listening" sound, and start recording straight away.

    This deliberately does not wait for the sound to finish, and does not
    set `speaking`. Both were costing the first words of every question:
    the player takes 1.2-1.7 seconds to start up and play a 0.56 second
    sound, and with the microphone muted for all of it, anyone who answered
    the beep promptly had their opening words thrown away. You had to pause
    for a beat before speaking, which is exactly the wrong instinct to
    teach someone.

    The cost is that the beep itself lands at the top of the recording.
    That's fine — it's short, and Whisper ignores it. Muting matters for
    `speak()`, where the speaker really would hear itself and wake up in a
    loop; a tink is not that.
    """
    if MACOS:
        subprocess.Popen(
            ["afplay", BEEP_SOUND],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    # There's no stock sound file to rely on, so make the tone ourselves.
    import numpy as np

    device = find_output_device(config.OUTPUT_DEVICE)
    # Make the tone at whatever rate this speaker wants, rather than making
    # it at one rate and converting — a sine wave costs nothing to generate.
    rate = playable_rate(device, 22_050)
    t = np.arange(int(rate * 0.12)) / rate
    tone = 0.25 * np.sin(2 * np.pi * 880 * t)
    # Fade both ends, or it clicks.
    fade = np.minimum(np.minimum(t, t[-1] - t) * 60, 1.0)
    _play(device, rate, (tone * fade * 32767).astype(np.int16))


def _play(device, rate: int, audio) -> None:
    """Play one lump of audio, and give the speaker back afterwards.

    Opening and closing the device around every sound is deliberate. When
    the speaker is a microphone array, playing and listening are the same
    piece of hardware and it allows exactly one stream at a time — anything
    left open in the background makes the next thing to talk fail with
    "Device unavailable". `sounddevice.play()` does exactly that: it keeps
    its stream open after the sound has finished, so the beep would silence
    every answer that followed it.
    """
    import numpy as np
    import sounddevice as sd

    with sd.OutputStream(samplerate=rate, channels=1, dtype="int16",
                         device=device) as stream:
        stream.write(np.ascontiguousarray(audio))


# --- macOS -----------------------------------------------------------------


def _say_macos(text: str) -> None:
    subprocess.run(
        ["say", "-v", config.VOICE, "-r", str(config.SPEECH_RATE), text],
        check=False,
    )


# --- Linux -----------------------------------------------------------------


def _say_linux(text: str) -> None:
    """Speak with Piper, falling back to espeak-ng if it isn't available."""
    voice = _piper_voice()
    if voice is None:
        _say_espeak(text)
        return

    import numpy as np
    import sounddevice as sd
    from piper import SynthesisConfig

    # Piper's speed dial is a stretch factor, not words per minute: below 1
    # is faster, above 1 is slower. A Piper voice at 1.0 reads at roughly
    # 175 words a minute, so this keeps SPEECH_RATE meaning the same thing
    # on both machines.
    settings = SynthesisConfig(length_scale=175 / config.SPEECH_RATE)

    device = find_output_device(config.OUTPUT_DEVICE)
    native = voice.config.sample_rate
    rate = playable_rate(device, native)

    # Piper hands back one chunk per sentence, so writing them out as they
    # arrive means the speaker starts talking before the whole answer has
    # been synthesised.
    with sd.OutputStream(samplerate=rate, channels=1, dtype="int16",
                         device=device) as stream:
        for chunk in voice.synthesize(text, settings):
            stream.write(_at_rate(chunk.audio_int16_array, native, rate))


def playable_rate(device, native: int) -> int:
    """The rate to play at: the voice's own, or the speaker's if it insists.

    Most speakers take whatever you give them. A microphone array does not
    — the reSpeaker XVF3800 runs everything at 16 kHz, and Piper's voices
    come out at 22.05 kHz, so handing it the voice's own rate fails outright
    with "Invalid sample rate" and nothing is ever said.
    """
    import sounddevice as sd

    try:
        sd.check_output_settings(device=device, samplerate=native,
                                 channels=1, dtype="int16")
        return native
    except Exception:
        return int(sd.query_devices(device)["default_samplerate"])


def _at_rate(audio, native: int, rate: int):
    """Resample a chunk, if the speaker won't take the voice's own rate.

    This runs per sentence rather than over the whole answer, which costs a
    little quality at the joins — each chunk is filtered on its own. Piper
    breaks at sentence ends, where there's near silence anyway, and doing it
    this way keeps the speaker talking while the rest is still being made.
    """
    import numpy as np

    if rate == native:
        return np.ascontiguousarray(audio)

    from scipy.signal import resample_poly

    resampled = resample_poly(audio.astype(np.float32), rate, native)
    return np.ascontiguousarray(
        np.clip(resampled, -32768, 32767).astype(np.int16))


def _piper_voice():
    """Load the Piper voice once and keep it, or None if it can't be had.

    Loading takes a second or two on a Pi, which would be noticeable on
    every single answer, so it stays in memory for the life of the program.
    """
    global _voice
    if _voice is not None:
        return _voice

    try:
        from piper import PiperVoice
    except ImportError:
        return None

    path = VOICE_DIR / f"{config.PIPER_VOICE}.onnx"
    if not path.exists():
        try:
            from piper.download_voices import download_voice

            print(f"Downloading the {config.PIPER_VOICE} voice (once)...")
            VOICE_DIR.mkdir(parents=True, exist_ok=True)
            download_voice(config.PIPER_VOICE, VOICE_DIR)
        except Exception as error:
            print(f"Couldn't download the voice ({error}) — using espeak-ng.")
            return None

    _voice = PiperVoice.load(path)
    return _voice


def _say_espeak(text: str) -> None:
    """The plain robotic fallback. Always available, never nice."""
    if shutil.which("espeak-ng") is None:
        print(f"[no voice installed, so this went unsaid] {text}")
        return
    subprocess.run(
        ["espeak-ng", "-v", "en-us", "-s", str(config.SPEECH_RATE), text],
        check=False,
    )


def find_output_device(wanted: str) -> int | None:
    """Turn the OUTPUT_DEVICE setting into a device number.

    Accepts a number, part of a name, or an empty string for the system
    default. Worth setting on a Raspberry Pi: ALSA lists the HDMI outputs
    first, so the default is often a monitor rather than your speakers.
    """
    wanted = wanted.strip()
    if not wanted:
        return None
    if wanted.isdigit():
        return int(wanted)

    import sounddevice as sd

    for number, device in enumerate(sd.query_devices()):
        if device["max_output_channels"] > 0 and wanted.lower() in device["name"].lower():
            return number

    raise SystemExit(
        f"No speaker matching {wanted!r}.\n"
        "See the list with:  python src/tts.py --devices"
    )


def list_devices() -> None:
    """Print every speaker this machine can see."""
    import sounddevice as sd

    default_output = sd.default.device[1]
    print("Speakers this machine can see:\n")
    for number, device in enumerate(sd.query_devices()):
        if device["max_output_channels"] <= 0:
            continue
        marker = " <- default" if number == default_output else ""
        print(f"  {number}: {device['name']}{marker}")
    print("\nSet one in .env, for example:  OUTPUT_DEVICE=Headphones")


if __name__ == "__main__":
    if "--devices" in sys.argv:
        list_devices()
        raise SystemExit

    # Step 1 of the build order: make the speaker say hello.
    beep()
    speak("Hello, I am Claude. I am your speaker.")
