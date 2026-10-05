"""Make an SD card that boots into a speaker you can reach.

    ./card.sh bedroom            prepare the card that's plugged in
    ./card.sh bedroom --password hunter2
    ./card.sh --find             what new Pi turned up on the network

Flash Raspberry Pi OS onto a card however you like — Imager, dd, anything —
then run this with the card in the laptop. It writes the three files the Pi
needs to come up with a name, a user, a key and a network, and tells you
what the password is. Boot it, and `--find` will tell you where it landed.

Why not just use Raspberry Pi Imager's settings
-----------------------------------------------
Because they are not part of the image. Imager writes `custom.toml` *and*
adds `init=/usr/lib/raspberrypi-sys-mods/firstboot` to cmdline.txt, and the
hook is what reads the file. Flash the same image any other way and the
hook is absent, so `custom.toml` sits there being ignored for ever.

That was worth four trips to the card to learn, so it is written down here:

  custom.toml      ignored unless something invokes it. Not used.
  init=            do not. On this image
                   /usr/lib/raspberrypi-sys-mods/firstboot does not exist,
                   so the kernel comes up with no init and the Pi never
                   boots at all — silently, if it has no monitor.
  userconf.txt     works. A systemd service reads it and makes the user.
  ssh              works. Consumed on boot, so write it every time.
  systemd.run=     works, and is safe: it runs a script as a unit rather
                   than replacing init, so a broken script costs you the
                   script and not the machine.

And the one that is easy to get wrong: at `kernel-command-line.target`,
*NetworkManager is not running yet*. A firstrun script that calls nmcli
gets "NetworkManager is not running" for every line. So this one writes
configuration files instead, which need no daemon, and lets the reboot
pick them up.
"""

import argparse
import getpass
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET_FILE = HERE / ".deploy-target"

WORDS = ("amber harbour lantern meadow pebble thicket willow cinder tandem "
         "quartz bramble kettle marlin saffron drift copper").split()


def say(message: str) -> None:
    print(message)


def boot_partition() -> Path:
    """The one mounted Raspberry Pi boot partition, or an explanation."""
    seen = [p for p in Path("/Volumes").iterdir()
            if (p / "cmdline.txt").is_file() and (p / "config.txt").is_file()]
    if not seen:
        raise SystemExit(
            "No Raspberry Pi card is mounted.\n\n"
            "Flash Raspberry Pi OS onto one, put it in this laptop, and wait\n"
            "for a volume called bootfs to appear.")
    if len(seen) > 1:
        raise SystemExit("More than one card is mounted:\n  " +
                         "\n  ".join(str(p) for p in seen) +
                         "\n\nEject all but the one you mean.")
    return seen[0]


def a_password() -> str:
    return "-".join(secrets.choice(WORDS) for _ in range(3)) + \
        f"-{secrets.randbelow(90) + 10}"


def hashed(password: str) -> str:
    done = subprocess.run(["openssl", "passwd", "-6", password],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit("openssl couldn't hash the password:\n" + done.stderr)
    return done.stdout.strip()


def my_key() -> str:
    """This laptop's public key, so the new Pi trusts it from first boot.

    Imager would do this through custom.toml, which does not work here, so
    the firstrun script writes authorized_keys itself. Without it the first
    thing you do with a new speaker is type a password at ssh-copy-id.
    """
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        key = Path.home() / ".ssh" / name
        if key.is_file():
            return key.read_text().strip()
    raise SystemExit(
        "No SSH key at ~/.ssh/id_ed25519.pub.\n"
        "Make one with:  ssh-keygen -t ed25519")


def wifi_from_a_working_pi() -> tuple[str, str] | None:
    """Borrow the network from a speaker that is already on it.

    NetworkManager keeps the derived 64-character key rather than the
    passphrase, which is all this needs: a .nmconnection takes either.
    """
    if not TARGET_FILE.is_file():
        return None
    target = TARGET_FILE.read_text().strip()
    # `connection show --active` only knows about the connection's own
    # columns, so the wireless settings need a second call naming it — and
    # -s, or nmcli hands back an empty psk without saying why.
    ask = (
        'n=$(nmcli -t -f NAME,TYPE connection show --active '
        '| awk -F: \'$2 ~ /wireless/ {print $1; exit}\'); '
        '[ -n "$n" ] || exit 1; '
        'nmcli -t -g 802-11-wireless.ssid connection show "$n"; '
        'nmcli -s -t -g 802-11-wireless-security.psk connection show "$n"')
    try:
        done = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o",
                               "BatchMode=yes", target, ask],
                              capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if len(lines) < 2 or not lines[1]:
        return None
    return lines[0], lines[1]


FIRSTRUN = """#!/bin/bash
# Written by card.py. Runs once, very early, as a systemd unit.
#
# NetworkManager is not running at this point in the boot, so everything
# here writes a file rather than calling a command. Files need no daemon.
exec > /boot/firmware/debug.txt 2>&1
set -x
date -u

mkdir -p /etc/NetworkManager/system-connections
cat > /etc/NetworkManager/system-connections/{ssid}.nmconnection <<'CONN'
[connection]
id={ssid}
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=10

[wifi]
mode=infrastructure
ssid={ssid}

[wifi-security]
key-mgmt=wpa-psk
psk={psk}

[ipv4]
method=auto

[ipv6]
method=auto
CONN
# NetworkManager ignores a connection file that anyone else can read.
chown root:root /etc/NetworkManager/system-connections/{ssid}.nmconnection
chmod 600 /etc/NetworkManager/system-connections/{ssid}.nmconnection

echo {name} > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\\t{name}/" /etc/hosts || true

# The key, because custom.toml's authorized_keys never runs on this image.
install -d -m 700 -o {user} -g {user} /home/{user}/.ssh
cat > /home/{user}/.ssh/authorized_keys <<'KEY'
{key}
KEY
chown {user}:{user} /home/{user}/.ssh/authorized_keys
chmod 600 /home/{user}/.ssh/authorized_keys

rfkill unblock wifi || true
raspi-config nonint do_wifi_country {country} || true
systemctl enable NetworkManager ssh || true

# What we found, in case it still does not come up.
ls -l /usr/sbin/NetworkManager /usr/bin/nmcli
ls /sys/class/net/
ls -l /etc/NetworkManager/system-connections/

cp /boot/firmware/cmdline.txt.backup /boot/firmware/cmdline.txt
sync
echo DONE
"""

RUN_HOOK = ("systemd.run=/boot/firmware/firstrun.sh "
            "systemd.run_success_action=reboot "
            "systemd.unit=kernel-command-line.target")


def prepare(boot: Path, name: str, user: str, password: str,
            ssid: str, psk: str, country: str) -> None:
    # cmdline.txt has to stay a single line, and the script puts this copy
    # back at the end so it only ever runs once.
    cmdline = boot / "cmdline.txt"
    backup = boot / "cmdline.txt.backup"
    if not backup.is_file():
        shutil.copy2(cmdline, backup)
    line = backup.read_text().strip()
    if "init=" in line:
        raise SystemExit(
            f"{backup} already has an init= hook in it. That is the thing\n"
            "that stops this image booting — take it out before going on.")
    cmdline.write_text(line + " " + RUN_HOOK + "\n")

    (boot / "userconf.txt").write_text(f"{user}:{hashed(password)}\n")
    os.chmod(boot / "userconf.txt", 0o600)
    (boot / "ssh").touch()          # consumed on boot, so written every time

    script = boot / "firstrun.sh"
    script.write_text(FIRSTRUN.format(name=name, user=user, ssid=ssid,
                                      psk=psk, key=my_key(), country=country))
    os.chmod(script, 0o755)

    # custom.toml would be read by nothing here, and leaving one around
    # invites the next person to believe it did something.
    stale = boot / "custom.toml"
    if stale.is_file():
        stale.unlink()


def find(known: set[str]) -> None:
    """Which Pi just turned up.

    By scanning, not by asking for <name>.local: mDNS does not resolve on
    every network and did not on the one this was written for, which cost
    an hour of believing a working Pi was a dead one.
    """
    import concurrent.futures
    import socket

    def open22(ip: str) -> str | None:
        try:
            with socket.create_connection((ip, 22), timeout=1):
                return ip
        except OSError:
            return None

    here = [f"192.168.{net}.{host}" for net in (4, 5) for host in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=256) as pool:
        up = [ip for ip in pool.map(open22, here) if ip]
    fresh = [ip for ip in up if ip not in known]
    say("  hosts with ssh: " + (", ".join(up) or "none"))
    if fresh:
        say("  new since you last looked: " + ", ".join(fresh))
    else:
        say("  nothing new. Give it a minute — it writes its config, then "
            "reboots.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare an SD card for a new speaker.")
    parser.add_argument("name", nargs="?",
                        help="what to call it — bedroom, kitchen")
    parser.add_argument("--user", default="normal")
    parser.add_argument("--password", default="")
    parser.add_argument("--ssid", default="")
    parser.add_argument("--psk", default="")
    parser.add_argument("--country", default="US")
    parser.add_argument("--find", action="store_true",
                        help="scan for a Pi that has just booted")
    args = parser.parse_args()

    if args.find:
        known = set()
        if TARGET_FILE.is_file():
            known.add(TARGET_FILE.read_text().strip().split("@")[-1])
        find(known)
        return 0

    if not args.name:
        parser.error("what should it be called? e.g. ./card.sh bedroom")

    boot = boot_partition()
    say(f"  card      {boot}")

    ssid, psk = args.ssid, args.psk
    if not ssid:
        borrowed = wifi_from_a_working_pi()
        if borrowed:
            ssid, psk = borrowed
            say(f"  network   {ssid}, borrowed from the speaker you already "
                "have")
        else:
            ssid = input("  Wi-Fi name: ").strip()
            psk = getpass.getpass("  Wi-Fi password: ").strip()
    if not ssid or not psk:
        raise SystemExit("Need a network to put it on.")

    password = args.password or a_password()
    prepare(boot, args.name, args.user, password, ssid, psk, args.country)

    say(f"  name      {args.name}")
    say(f"  user      {args.user}")
    say(f"  password  {password}")
    say(f"  key       ~/.ssh added, so ssh works without one")
    say("")
    say("  Written. Eject the card, put it in the Pi and power it up.")
    say("  It writes its config, reboots once, and joins the network —")
    say("  about two minutes. Then:")
    say("")
    say("      ./card.sh --find")
    say(f"      ./deploy.sh {args.user}@<the address it found>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
