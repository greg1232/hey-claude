"""Copy what the speaker has learned off the Pi, and keep every version.

    ./backup.sh              fetch from the Pi and upload
    ./backup.sh --local      fetch only, upload nothing
    ./backup.sh --dry        say what would happen

Everything the speaker has learned for itself lives on one SD card in
`state/`, which git ignores. That is: every wake-word firing with the 768
numbers it was scored on, the recordings behind them, the labels — the
machine's and yours — and the model fitted from all of it. An SD card in
an always-on Pi is not a place to keep the only copy of anything.

Why Hugging Face rather than a folder
-------------------------------------
A dataset repo there is a git repository with large-file storage behind
it, so each backup is a commit. That answers storage and versioning at
once: you can see what changed between two nights, and go back to the data
a particular model was fitted on rather than guessing.

It also fixes something quietly wrong. The Pi keeps only the most recent
few hundred recordings — a rotating cap, so every new firing deletes an
old one — and the audio behind labels you have already given is being
thrown away. Uploaded, the archive keeps them all; the Pi goes on holding
only what it needs.

Private, by default
-------------------
This is not the same as the recordings in `train/real/`. Those are four
people who sat down and said "hey Claude" into a microphone on purpose.
This is two-second windows of a living room, caught whenever the detector
fired — dozens an hour with a television on — and it contains whatever was
being said in that room by whoever was in it. Nobody chose to record most
of it.

So the repository is created private, and `--public` is a thing you have to
type. Your call, your house; but it should be a decision rather than a
default.
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET_FILE = HERE / ".deploy-target"
REMOTE = "claude-speaker/state"
LOCAL = HERE / "state" / "backup"
REPO = "claude-speaker-room"

# What is worth keeping, and what is not. Books and sound effects are
# downloaded copies of other people's files and can always be fetched
# again; the wake log cannot.
KEEP = ("wakes", "enrolled", "wishes.jsonl", "alarms.json",
        "hey_claude_whisper.npz", "hey_claude_whisper.npz.previous")


def target() -> str:
    if not TARGET_FILE.is_file():
        raise SystemExit(
            "I don't know which Pi to ask. Deploy once first:\n\n"
            "    ./deploy.sh normal@192.168.4.95")
    return TARGET_FILE.read_text().strip()


def fetch(pi: str, dry: bool) -> None:
    """Copy the worth-keeping parts of state/ down from the Pi."""
    LOCAL.mkdir(parents=True, exist_ok=True)
    # Plain flags only. macOS still ships rsync 2.6.9, which doesn't know
    # --info= — the same thing deploy.py has a comment about, and the same
    # mistake made twice.
    args = ["rsync", "-avz"]
    if dry:
        args.append("--dry-run")
    for name in KEEP:
        args += ["--include", name, "--include", f"{name}/**"]
    args += ["--exclude", "*", f"{pi}:{REMOTE}/", f"{LOCAL}/"]

    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"Couldn't fetch:\n{done.stderr.strip()}")
    noise = ("receiving", "sending", "building", "sent ", "total size",
             "./", "wrote ")
    new = [line for line in done.stdout.splitlines()
           if line.strip() and not line.startswith(noise)
           and not line.endswith("/")]
    print(f"  {len(new)} file{'s' if len(new) != 1 else ''} "
          f"{'would come' if dry else 'came'} down")


def describe() -> dict:
    """Read the log, and write a metadata table beside the recordings.

    The table is what makes this a dataset rather than a pile of files:
    Hugging Face's viewer reads metadata.csv and lines each row up with
    its audio, so the whole thing is browsable in a page.
    """
    index = LOCAL / "wakes" / "wakes.jsonl"
    if not index.exists():
        return {}

    rows: dict[int, dict] = {}
    for line in index.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "n" in row:
            rows.setdefault(row["n"], {}).update(row)

    counted = {"firings": 0, "near": 0, "labelled": 0, "by a person": 0,
               "with audio": 0}
    table = []
    for number, row in sorted(rows.items()):
        clip = LOCAL / "wakes" / "audio" / f"{number:06d}.wav"
        counted["near" if row.get("near") else "firings"] += 1
        counted["labelled"] += "label" in row
        counted["by a person"] += row.get("by") == "person"
        counted["with audio"] += clip.exists()
        table.append({
            "file_name": f"wakes/audio/{number:06d}.wav" if clip.exists() else "",
            "n": number,
            "at": row.get("at", ""),
            "score": row.get("score", ""),
            "near_miss": int(bool(row.get("near"))),
            "repeated": int(bool(row.get("repeated"))),
            "label": row.get("label", ""),
            "labelled_by": row.get("by", "machine" if "label" in row else ""),
            "heard_next": row.get("heard", ""),
            "window_said": row.get("window", ""),
        })

    with open(LOCAL / "metadata.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    return counted


def readme(counted: dict) -> None:
    (LOCAL / "README.md").write_text(f"""---
license: other
task_categories:
- audio-classification
tags:
- keyword-spotting
- wake-word
---

# Claude Speaker — what woke it

Every time the wake word fired, and every time it nearly did, as recorded
by a reSpeaker XVF3800 array in one living room. Kept so the detector can
be retrained on its own mistakes.

Written by `backup.py` in
[greg1232/hey-claude](https://github.com/greg1232/hey-claude).
Last updated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}.

| | |
|---|---|
{chr(10).join(f'| {k} | {v} |' for k, v in counted.items())}

## What is here

- `metadata.csv` — one row per firing, lined up with its recording.
- `wakes/wakes.jsonl` — the log as the speaker writes it, append-only.
- `wakes/vectors.f16` — 768 float16 per firing, in row order. These are
  Whisper `tiny.en` encoder features, mean and max pooled over the first
  100 frames of a two second window, and they are what the model is
  actually fitted on. Free to keep: the encoder pass is what fired the
  wake word.
- `wakes/audio/` — the two seconds that fired, 16 kHz mono.
- `enrolled/` — somebody teaching it their voice by repeating the phrase.
- `hey_claude_whisper.npz` — the model fitted from all of it.

## Labels

`label` is 1 if that really was somebody saying "hey Claude". `labelled_by`
says whether a person listened to it or the machine worked it out from what
happened next. A person's answer overrides the machine's.
""")


def upload(private: bool, dry: bool) -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    who = api.whoami()["name"]
    repo = f"{who}/{REPO}"
    if dry:
        print(f"  would upload {LOCAL} to {repo} "
              f"({'private' if private else 'PUBLIC'})")
        return

    api.create_repo(repo, repo_type="dataset", private=private,
                    exist_ok=True)
    print(f"  uploading to https://huggingface.co/datasets/{repo} ...")
    api.upload_folder(
        folder_path=str(LOCAL), repo_id=repo, repo_type="dataset",
        commit_message=f"Backup {datetime.now().astimezone():%Y-%m-%d %H:%M}",
        ignore_patterns=[".*", "**/.*"])
    print(f"  done — https://huggingface.co/datasets/{repo}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--local", action="store_true",
                        help="fetch from the Pi, upload nothing")
    parser.add_argument("--dry", action="store_true",
                        help="say what would happen, do nothing")
    parser.add_argument("--public", action="store_true",
                        help="make the dataset public. Read the note at the "
                             "top of this file before you do")
    args = parser.parse_args()

    pi = target()
    print(f"Fetching from {pi}...")
    fetch(pi, args.dry)

    counted = describe()
    if counted:
        readme(counted)
        print("  " + ", ".join(f"{v} {k}" for k, v in counted.items()))
    size = sum(f.stat().st_size for f in LOCAL.rglob("*") if f.is_file())
    print(f"  {size / 1e6:.1f} MB in {LOCAL}")

    if args.local:
        return 0
    upload(not args.public, args.dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
