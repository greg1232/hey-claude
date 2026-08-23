"""Start the Claude Speaker.

    ./start.sh                 start it in the background, logging to speaker.log
    ./start.sh --foreground    run it here instead, printing to this terminal
    ./start.sh --text          type questions instead of speaking them
    ./start.sh --stop          stop the one that's running
    ./start.sh --status        say whether it's running, and where its log is
    ./start.sh --install-only  build the environment and stop (deploy.py uses this)

The first run takes a couple of minutes: it builds a private Python folder
and downloads the speech models. After that it starts in seconds.

Runs on the system Python and only the standard library, because its first
job is to build the virtualenv that everything else needs.
"""

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
PYTHON = VENV / "bin" / "python"
STAMP = VENV / ".installed"
LOG = HERE / "speaker.log"
PIDFILE = HERE / "speaker.pid"

KEY_URL = "https://console.anthropic.com/settings/keys"
SERVICE = "claude-speaker"


def managed_by_systemd() -> bool:
    """Is systemd looking after the speaker on this machine?

    If it is, this script must keep its hands off. Starting a second one
    here would fight it for the microphone, and stopping one by killing the
    process leaves systemd thinking it exited cleanly — enabled, inactive,
    and not coming back until the next reboot. Which is exactly what
    happened the first time ./deploy.sh --service was used.
    """
    if not Path("/run/systemd/system").exists():
        return False
    state = subprocess.run(["systemctl", "is-enabled", SERVICE],
                           capture_output=True, text=True).stdout.strip()
    return state in ("enabled", "enabled-runtime", "static", "linked")


def systemd_hint(action: str) -> int:
    active = subprocess.run(["systemctl", "is-active", SERVICE],
                            capture_output=True, text=True).stdout.strip()
    print(f"systemd is looking after the speaker (currently {active}).")
    print(f"Use it, or the two will fight over the microphone:\n")
    print(f"    sudo systemctl {action} {SERVICE}")
    print(f"    journalctl -u {SERVICE} -f")
    return 1


def speaker_pid() -> int | None:
    """The running speaker's pid, or None."""
    if PIDFILE.is_file():
        try:
            pid = int(PIDFILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    # No pidfile, or a stale one — it may have been started by systemd or by
    # hand. The bracket keeps pgrep from matching this process.
    found = subprocess.run(["pgrep", "-f", r"[s]rc/main\.py"],
                           capture_output=True, text=True)
    lines = [line for line in found.stdout.split() if line.isdigit()]
    return int(lines[0]) if lines else None


def stop() -> int:
    if managed_by_systemd():
        return systemd_hint("stop")
    pid = speaker_pid()
    if pid is None:
        PIDFILE.unlink(missing_ok=True)
        print("Not running.")
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.25)
    else:
        print(f"Wouldn't stop, so making it: pid {pid}")
        os.kill(pid, signal.SIGKILL)
    PIDFILE.unlink(missing_ok=True)
    print("Stopped.")
    return 0


def status() -> int:
    if managed_by_systemd():
        active = subprocess.run(["systemctl", "is-active", SERVICE],
                                capture_output=True, text=True).stdout.strip()
        pid = speaker_pid()
        print(f"Looked after by systemd: {active}"
              + (f", pid {pid}" if pid else ""))
        print(f"  log:  journalctl -u {SERVICE} -f")
        print(f"  stop: sudo systemctl stop {SERVICE}")
        return 0
    pid = speaker_pid()
    if pid is None:
        print("Not running.")
    else:
        print(f"Running as pid {pid}.")
        print(f"  log:  {LOG}")
        print("  stop: ./start.sh --stop")
    return 0


def build_environment() -> None:
    """Make the virtualenv and install what's needed, if anything changed."""
    if not PYTHON.is_file():
        print("Setting up Python for the first time (this takes a minute)...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(VENV / "bin" / "pip"), "install", "--quiet",
                        "--upgrade", "pip"], check=True)

    requirements = HERE / "requirements.txt"
    if STAMP.is_file() and STAMP.stat().st_mtime >= requirements.stat().st_mtime:
        return

    print("Installing the packages it needs...")
    pip = str(VENV / "bin" / "pip")
    subprocess.run([pip, "install", "--quiet", "-r", str(requirements)],
                   check=True)

    # The wake word, on Linux. It goes in by hand and without its
    # dependencies, because openWakeWord insists on tflite-runtime there and
    # there's no build of that for recent Pythons on Arm. We don't use it —
    # wake.py loads the ONNX build — and the packages it really needs are
    # in requirements.txt. Without --no-deps, pip refuses to install
    # anything at all on a Raspberry Pi.
    if sys.platform.startswith("linux"):
        subprocess.run([pip, "install", "--quiet", "--no-deps",
                        "openwakeword>=0.6.0"], check=True)

    STAMP.touch()


def check_settings() -> None:
    env = HERE / ".env"
    if not env.is_file():
        raise SystemExit(
            "\nThere's no .env file yet, so it doesn't know your API key.\n"
            "Make one and put your key in it:\n\n"
            "    cp .env.example .env\n\n"
            f"Get a key at {KEY_URL}")
    # Read it without printing it, so the key never shows up on screen.
    if not re.search(r"^\s*ANTHROPIC_API_KEY=.+", env.read_text(), re.M):
        raise SystemExit(
            "\nANTHROPIC_API_KEY is empty in .env.\n"
            "Open .env and paste your key after the = sign.\n"
            f"Get one at {KEY_URL}")


def start_daemon(extra: list[str]) -> int:
    if managed_by_systemd():
        return systemd_hint("start")

    # Only one at a time. On a microphone array, playing and listening are
    # the same piece of hardware and it allows a single stream, so a second
    # speaker doesn't share the microphone — it fails, or quietly steals it.
    running = speaker_pid()
    if running is not None:
        print(f"Already running as pid {running}.")
        print("  ./start.sh --stop     stop it")
        print("  ./start.sh --status   where its log is")
        return 1

    # Keep the last run's log. When something dies at three in the morning,
    # the restart is what you notice, and it mustn't erase the reason.
    if LOG.is_file():
        LOG.replace(LOG.with_suffix(".log.1"))

    # PYTHONUNBUFFERED, because Python buffers its output when writing to a
    # file rather than a terminal. Without it the log sits empty for a long
    # time and looks exactly like a speaker that never started.
    environment = dict(os.environ, PYTHONUNBUFFERED="1")
    with open(LOG, "w") as log:
        process = subprocess.Popen(
            [str(PYTHON), "src/main.py", *extra], cwd=HERE, env=environment,
            stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
    PIDFILE.write_text(f"{process.pid}\n")

    # Don't claim success before it's earned. Starting up means loading the
    # speech model, the voice and the wake word, so give it a moment and
    # then check it's still there.
    time.sleep(3)
    if process.poll() is not None:
        PIDFILE.unlink(missing_ok=True)
        print(f"It started and then stopped. The end of {LOG.name}:\n")
        for line in LOG.read_text().splitlines()[-20:]:
            print(f"    {line}")
        return 1

    print(f"Started as pid {process.pid}. It takes about half a minute to "
          "be ready.\n")
    print(f"  watch it:  tail -f {LOG.name}")
    print("  stop it:   ./start.sh --stop")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-f", "--foreground", action="store_true")
    parser.add_argument("--text", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args()

    if args.stop:
        return stop()
    if args.status:
        return status()

    build_environment()
    check_settings()

    if args.install_only:
        print("Ready.")
        return 0

    # Typing questions is a conversation, so it has to stay in front of you.
    if args.foreground or args.text:
        print()
        os.execv(str(PYTHON),
                 [str(PYTHON), "src/main.py"] + (["--text"] if args.text else []))
    return start_daemon([])


if __name__ == "__main__":
    os.chdir(HERE)
    sys.exit(main())
