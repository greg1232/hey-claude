"""Put the Claude Speaker on a Raspberry Pi.

    ./deploy.sh normal@192.168.4.95   name the Pi (remembered afterwards)
    ./deploy.sh                       deploy again to the same Pi
    ./deploy.sh --run                 deploy, then start it and watch
    ./deploy.sh --service             deploy, and start it on every boot

Safe to run as many times as you like: it only re-does the parts that
changed. The first run takes several minutes, mostly downloading Python
packages onto the Pi; later runs take seconds.

Your API key travels over the SSH connection and lands in a file only you
can read. It is never printed, and never committed — .env is in .gitignore
on both machines.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE_DIR = "claude-speaker"        # relative to the Pi user's home
TARGET_FILE = HERE / ".deploy-target"  # so you only name the Pi once

# Everything the speaker needs and nothing it doesn't: no git history, no
# virtualenv built for a different CPU, no training data, and no .env —
# that one goes separately, with tighter permissions. Logs and the pidfile
# are excluded because --delete removes whatever isn't here, and wiping the
# log on every deploy throws away the record of what you were investigating.
EXCLUDE = (".git/", ".venv/", ".env", ".deploy-target", "__pycache__/",
           "*.pyc", "voices/", "state/", "train/data/", "train/voices/",
           "train/hey_claude/", "train/room/", "*.png", "*.log*", "*.pid",
           ".DS_Store")

APT_PACKAGES = ("python3-venv", "libportaudio2", "libsndfile1", "espeak-ng",
                "alsa-utils")

# The Pi is a different machine, so a few settings can't come across as they
# are: the microphone name is the laptop's, and the voice is a macOS one.
# Everything else — your key, your town, the wake word — carries over.
PI_ONLY = ("INPUT_DEVICE", "OUTPUT_DEVICE", "OUTPUT_VOLUME", "VOICE",
           "PIPER_VOICE", "WHISPER_MODEL", "WAKE_MODEL", "WAKE_THRESHOLD",
           "WAKE_STRIDE_SECONDS")

PI_SETTINGS = """
# ---- Added by deploy.sh, because this is the Pi and not the laptop ----

# The Pi speaks with Piper, not the macOS `say` command.
# Listen to the choices at https://rhasspy.github.io/piper-samples/
# Keep to a "medium" voice: measured on a Pi 4, medium needs 0.32 seconds
# of compute per second of speech, but "high" needs 2.0 — slower than
# talking, so the speaker would fall behind itself.
PIPER_VOICE=en_GB-alan-medium

# Which microphone and which speaker.
#   python src/audio_in.py --devices     lists microphones
#   python src/tts.py --devices          lists speakers
#
# OUTPUT_DEVICE is set rather than left empty on purpose. A Pi's ALSA
# default is the first HDMI port, and opening it with no monitor plugged in
# fails outright ("audio open error: Unknown error 524") — so the speaker
# would start up and then not be able to say a word. Playing through the
# microphone array is better still when the speakers are wired that way:
# the XVF3800 cancels its own output in hardware.
INPUT_DEVICE=
OUTPUT_DEVICE=Array

# This array arrives about 20 dB down, which sounds like a broken speaker
# rather than a quiet one. Turn it down here if it's too loud at night;
# leave it blank to not touch the system mixer at all.
OUTPUT_VOLUME=100

# The wake word, and how sure it has to be. The right threshold depends on
# the microphone and the room, so measure yours on the Pi itself:
#     python train/test_wake.py --times 6
#     python train/test_silence.py --seconds 600
WAKE_MODEL=hey_claude_whisper.npz
WAKE_THRESHOLD=0.99

# How often the Whisper wake word looks, in seconds. About 42% of one core
# at 0.4 on a Pi 4. Raise it to spend less, and be noticed a little later.
WAKE_STRIDE_SECONDS=0.4

# A Pi 4 is much slower than a laptop at speech recognition, so use the
# small model. Change it to base.en if it mishears too often and you don't
# mind waiting longer.
WHISPER_MODEL=tiny.en
"""

# A user service, not a system one, so deploying never needs a password.
# systemctl --user needs no sudo, and `loginctl enable-linger` — which the
# user can also run for themselves — is what makes it start at boot without
# anyone logging in. The speaker has no reason to be root: it needs the
# audio group, which the user is already in, and PipeWire is running in
# their session anyway.
#
# Restart=always rather than on-failure, because at boot the network may
# not be up yet and the first question would fail. Retrying costs nothing.
SERVICE = """[Unit]
Description=Claude Speaker

[Service]
Type=simple
WorkingDirectory=%h/{dir}
ExecStart=%h/{dir}/.venv/bin/python src/main.py
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

UNIT_PATH = ".config/systemd/user/claude-speaker.service"


def step(message: str) -> None:
    print(f"\n==> {message}")


def indent(text: str) -> None:
    for line in text.rstrip().splitlines():
        print(f"    {line}")


class Pi:
    """The Raspberry Pi at the other end of an SSH connection."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.user = target.split("@")[0]

    def run(self, command: str, tty: bool = False, check: bool = True,
            quiet: bool = False) -> subprocess.CompletedProcess:
        """Run a command on the Pi. `tty` lets sudo ask for a password."""
        argv = ["ssh"] + (["-t"] if tty else []) + [self.target, command]
        if quiet:
            return subprocess.run(argv, check=check, capture_output=True,
                                  text=True)
        return subprocess.run(argv, check=check)

    def output(self, command: str) -> str:
        return self.run(command, check=False, quiet=True).stdout.strip()

    def reachable(self) -> bool:
        return subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
             self.target, "true"], capture_output=True).returncode == 0

    def send(self, local: Path, remote: str) -> None:
        subprocess.run(["scp", "-q", str(local), f"{self.target}:{remote}"],
                       check=True)

    def python(self, script: str) -> str:
        """Run a Python snippet inside the speaker's virtualenv.

        Shows what went wrong if it fails. Swallowing the error here once
        cost an afternoon: a stray apostrophe made the remote script a
        syntax error, and the step just printed nothing at all.
        """
        done = self.run(
            f"cd ~/{REMOTE_DIR} && .venv/bin/python - <<'PYTHON'\n"
            f"import sys; sys.path.insert(0, 'src')\n{script}\nPYTHON",
            check=False, quiet=True)
        if done.returncode != 0:
            noise = ("ALSA lib", "jack server", "Cannot connect", "JackShm",
                     "Expression", "Unknown PCM")
            real = [line for line in done.stderr.splitlines()
                    if line.strip() and not any(n in line for n in noise)]
            return (done.stdout.strip() + "\n"
                    + "\n".join(real[-6:])).strip()
        return done.stdout.strip()


def local_env() -> Path:
    """The .env to send, checked before we go near the network."""
    env = HERE / ".env"
    if not env.is_file():
        raise SystemExit(
            "There's no .env file here, so there's no API key to send.\n"
            "Make one first:  cp .env.example .env")
    # Read it without printing it, so the key never shows up on screen.
    if not re.search(r"^\s*ANTHROPIC_API_KEY=.+", env.read_text(), re.M):
        raise SystemExit(
            "ANTHROPIC_API_KEY is empty in .env — the Pi would have "
            "nothing to use.")
    return env


def settings_for_pi() -> str:
    """The laptop's settings, with the machine-specific ones replaced.

    Write a .env.pi by hand and that gets sent instead, untouched.
    """
    by_hand = HERE / ".env.pi"
    if by_hand.is_file():
        print("    using .env.pi")
        return by_hand.read_text()
    keep = [line for line in local_env().read_text().splitlines()
            if not any(re.match(rf"\s*{name}=", line) for name in PI_ONLY)]
    return "\n".join(keep) + "\n" + PI_SETTINGS


def resolve_target(named: str | None) -> str:
    if named:
        TARGET_FILE.write_text(named + "\n")
        return named
    if TARGET_FILE.is_file():
        return TARGET_FILE.read_text().strip()
    raise SystemExit(
        "Which Pi? Give it a user and address, for example:\n\n"
        "    ./deploy.sh normal@192.168.4.95")


def install_packages(pi: Pi) -> None:
    """sounddevice needs PortAudio; espeak-ng is the fallback voice."""
    missing = pi.output(
        "for p in " + " ".join(APT_PACKAGES) + "; do "
        "dpkg -s $p >/dev/null 2>&1 || printf '%s ' $p; done")
    if not missing:
        indent("already installed")
        return
    indent(f"installing: {missing}")
    pi.run(f"sudo apt-get update -qq && sudo apt-get install -y -qq {missing}",
           tty=True)


# The LED ring is driven over raw USB, and the array's USB node belongs to
# root. This hands it to the plugdev group, which the Pi's own user is
# already in — so the speaker can light its own lights without being root,
# the same bargain as the systemd user service.
UDEV_RULE = ('SUBSYSTEM=="usb", ATTR{idVendor}=="2886", '
             'ATTR{idProduct}=="001a", MODE="0660", GROUP="plugdev"')
UDEV_PATH = "/etc/udev/rules.d/60-respeaker.rules"


def leds_allowed(pi: Pi) -> bool:
    return pi.output(f"cat {UDEV_PATH} 2>/dev/null").strip() == UDEV_RULE


def allow_led_access(pi: Pi, ask: bool = True) -> None:
    """Let the speaker talk to the LED ring without sudo.

    This is the one thing here that genuinely needs root once, so a deploy
    that was asked not to touch system packages says what's needed and
    leaves it rather than springing a password prompt.
    """
    if leds_allowed(pi):
        indent("already allowed")
        return

    if not ask:
        indent("not set up yet — the LED ring will stay dark")
        indent("this needs the Pi's password once:  ./deploy.sh --leds")
        return

    indent("adding a udev rule for the microphone array's LEDs")
    # Re-triggering beats asking anyone to unplug the array; without it the
    # rule only takes effect at the next boot.
    pi.run(f"echo '{UDEV_RULE}' | sudo tee {UDEV_PATH} >/dev/null"
           " && sudo udevadm control --reload-rules"
           " && sudo udevadm trigger --subsystem-match=usb"
           " --attr-match=idVendor=2886", tty=True)


def copy_code(pi: Pi) -> None:
    pi.run(f"mkdir -p ~/{REMOTE_DIR}", quiet=True)
    # Plain flags only: macOS still ships rsync 2.6.9, which doesn't know
    # --info= and friends.
    subprocess.run(
        ["rsync", "-az", "--delete"]
        + [arg for pattern in EXCLUDE for arg in ("--exclude", pattern)]
        + [f"{HERE}/", f"{pi.target}:{REMOTE_DIR}/"], check=True)
    indent("code, models/ and start.sh copied")


def send_settings(pi: Pi) -> None:
    handle, path = tempfile.mkstemp()
    try:
        os.close(handle)
        temp = Path(path)
        temp.chmod(0o600)
        temp.write_text(settings_for_pi())
        pi.send(temp, f"{REMOTE_DIR}/.env")
    finally:
        Path(path).unlink(missing_ok=True)
    pi.run(f"chmod 600 ~/{REMOTE_DIR}/.env", quiet=True)
    indent(f"sent (readable only by {pi.user})")


def prepare_audio(pi: Pi) -> None:
    """Fetch the voice and set the volume, so the first run isn't a wait."""
    indent(pi.python(
        "import config, tts\n"
        "tts.turn_up()\n"
        "print('volume: %s%% on card %s' % (config.OUTPUT_VOLUME or "
        "'left alone', tts._output_card()))\n"
        "print('voice:  %s' % (config.PIPER_VOICE if tts._piper_voice() "
        "else 'unavailable — will use espeak-ng'))"))


def check_sound(pi: Pi) -> None:
    """The two things that go wrong in practice: no microphone, and sound
    going out of an HDMI port nobody is listening to.

    A speaker that's already running holds the microphone open, and a
    microphone array allows one stream — so it disappears from the list and
    this looks like a hardware fault. Say so rather than sending someone
    after a cable.
    """
    busy = pi.run('pgrep -f "[s]rc/main.py" >/dev/null',
                  check=False, quiet=True).returncode == 0
    indent(pi.python("""
try:
    import sounddevice as sd
except OSError as error:
    print('Sound library missing:', error)
    print('Run ./deploy.sh without --no-apt to install it.')
    raise SystemExit
import config
devices = list(sd.query_devices())
mics = [d['name'] for d in devices if d['max_input_channels'] > 0]
speakers = [d['name'] for d in devices if d['max_output_channels'] > 0]
print('microphones:', ', '.join(mics) if mics else 'NONE')
print('speakers:   ', ', '.join(speakers) if speakers else 'NONE')
if not mics and not BUSY:
    print()
    print('!! No microphone is reaching the Pi, so it can only be used with')
    print('   WAKE_MODE=key and --text. A USB mic should show up in lsusb.')
    print('   If one is listed by arecord -l but nothing records, try a')
    print('   different USB socket — a blue USB 3 port fixed it here.')
elif not mics:
    print("   (the running speaker is holding the microphone, so it")
    print("    is not listed — that is expected, not a fault)")
if config.OUTPUT_DEVICE and not any(
        config.OUTPUT_DEVICE.lower() in name.lower() for name in speakers):
    print()
    print('!! OUTPUT_DEVICE is %r, which is not in that list.'
          % config.OUTPUT_DEVICE)
""".replace("BUSY", str(busy))))


def install_service(pi: Pi) -> bool:
    """Set it to start on boot, without ever asking for a password.

    Returns whether it's now installed.
    """
    # An older version of this installed a system service. Two managers is
    # worse than either, so say so rather than quietly running both.
    if pi.output("test -f /etc/systemd/system/claude-speaker.service "
                 "&& echo yes"):
        indent("There's an old system-wide service here from a previous\n"
               "version. Remove it, once, and this will never need sudo "
               "again:\n"
               f"    ssh -t {pi.target} 'sudo systemctl disable --now "
               "claude-speaker && sudo rm "
               "/etc/systemd/system/claude-speaker.service'")
        return False

    pi.run(f"mkdir -p ~/{Path(UNIT_PATH).parent} && "
           f"cat > ~/{UNIT_PATH} <<'UNIT'\n"
           f"{SERVICE.format(dir=REMOTE_DIR)}UNIT", quiet=True)
    # Lingering is what lets a user service run with nobody logged in.
    pi.run("loginctl enable-linger && systemctl --user daemon-reload && "
           "systemctl --user enable --now claude-speaker", quiet=True)
    indent(pi.output("systemctl --user is-active claude-speaker"))
    indent("starts on every boot, no password needed")
    return True


def service_scope(pi: Pi) -> str | None:
    """'--user', '' for a system unit, or None if there isn't one.

    Both, because this project used to install a system-wide unit. A Pi
    part way between the two has the old one and not the new, and treating
    that as unmanaged starts a second speaker beside it.
    """
    for scope in ("--user", ""):
        if pi.run(f"systemctl {scope} is-enabled --quiet claude-speaker",
                  check=False, quiet=True).returncode == 0:
            return scope
    return None


def restart_if_running(pi: Pi) -> None:
    """Copying files onto the Pi doesn't change what's already running.

    Asks whether systemd is *enabled* rather than active. A service that's
    enabled but stopped still owns the speaker — starting a loose one
    beside it means two processes competing for a microphone that allows
    one, and the loose one disappears at the next reboot.
    """
    scope = service_scope(pi)
    if scope is not None:
        step("Restarting the service so it picks this up")
        sudo = "" if scope == "--user" else "sudo "
        if pi.run(f"{sudo}systemctl {scope} restart claude-speaker",
                  tty=bool(sudo), check=False, quiet=not sudo).returncode != 0:
            indent("couldn't restart it — the code is on the Pi but the "
                   "running speaker is\nstill the old one. Finish with:\n"
                   f"    ssh -t {pi.target} '{sudo}systemctl {scope} restart "
                   "claude-speaker'")
            return
        indent(pi.output(f"systemctl {scope} is-active claude-speaker"))
    elif pi.run('pgrep -f "[s]rc/main.py" >/dev/null',
                check=False, quiet=True).returncode == 0:
        step("Restarting the speaker so it picks this up")
        indent(pi.output(f"cd ~/{REMOTE_DIR} && ./start.sh --stop && ./start.sh"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?",
                        help="user@address of the Pi; remembered afterwards")
    parser.add_argument("--run", action="store_true",
                        help="start it afterwards and watch")
    parser.add_argument("--service", action="store_true",
                        help="start it on every boot")
    parser.add_argument("--leds", action="store_true",
                        help="only add the udev rule that lets the speaker "
                             "drive the array's LED ring (asks for the Pi's "
                             "password, once)")
    parser.add_argument("--no-apt", action="store_true",
                        help="skip system packages")
    args = parser.parse_args()

    local_env()  # Fail before touching the network if the key is missing.
    pi = Pi(resolve_target(args.target))
    print(f"Deploying to {pi.target}:~/{REMOTE_DIR}")

    step("Checking the Pi is reachable")
    if not pi.reachable():
        raise SystemExit(
            f"Can't log in to {pi.target} without a password.\n"
            f"Set up a key once with:  ssh-copy-id {pi.target}")
    indent(pi.output(
        'echo "$(. /etc/os-release; echo "$PRETTY_NAME") on $(uname -m), '
        'Python $(python3 -V | cut -d" " -f2)"'))

    if args.leds:
        step("Letting the speaker drive the array's LED ring")
        allow_led_access(pi)
        step("Restarting the service so it picks this up")
        restart_if_running(pi)
        return

    if args.no_apt:
        step("Skipping system packages (--no-apt)")
        step("Checking the speaker can drive the array's LED ring")
        allow_led_access(pi, ask=False)
    else:
        step("Installing system packages (sudo may ask for the Pi's password)")
        install_packages(pi)

        step("Letting the speaker drive the array's LED ring")
        allow_led_access(pi)

    step("Copying the code")
    copy_code(pi)

    step("Sending settings and API key")
    send_settings(pi)

    step("Installing Python packages on the Pi (slow the first time)")
    # start.sh already knows how to do this, and knowing it in two places is
    # how the two drift apart.
    indent(pi.output(f"cd ~/{REMOTE_DIR} && ./start.sh --install-only"))

    step("Downloading the voice and setting the volume")
    prepare_audio(pi)

    step("Checking the sound hardware")
    check_sound(pi)

    running_as_service = service_scope(pi) is not None
    if args.service:
        step("Setting it to start on boot")
        running_as_service = install_service(pi) or running_as_service
    else:
        restart_if_running(pi)

    print("\nDeployed.\n")
    if running_as_service:
        print("systemd is looking after it, and starts it on every boot.\n")
        print(f"  Watch it:     ssh {pi.target} journalctl --user-unit=claude-speaker -f")
        print(f"  Restart it:   ssh {pi.target} systemctl --user restart claude-speaker")
        print(f"  Stop it:      ssh {pi.target} systemctl --user stop claude-speaker")
        print(f"  Type instead: ssh -t {pi.target} 'cd {REMOTE_DIR} && "
              "systemctl --user stop claude-speaker && ./start.sh --text'")
    else:
        print(f"  Start it:     ssh {pi.target} 'cd {REMOTE_DIR} && ./start.sh'")
        print(f"  Watch it:     ssh {pi.target} 'tail -f {REMOTE_DIR}/speaker.log'")
        print(f"  Stop it:      ssh {pi.target} 'cd {REMOTE_DIR} && ./start.sh --stop'")
        print(f"  Type instead: ssh -t {pi.target} 'cd {REMOTE_DIR} && ./start.sh --text'")
        print("  On every boot: ./deploy.sh --service")

    if args.run:
        step("Starting it (Ctrl-C to stop)")
        os.execvp("ssh", ["ssh", "-t", pi.target,
                          f"cd {REMOTE_DIR} && ./start.sh --foreground"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
