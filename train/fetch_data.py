"""Download the training data, but only about a gigabyte of it.

The full negative-features file openWakeWord trains against is 17.3 GB. It
doesn't have to be: it's a plain .npy of 5,625,000 windows, and the server
supports range requests, so we can fetch the first slice of it and repair
the header to say how many windows we actually took. What you get is a
smaller but completely valid file.

This script gathers three things into train/data/:

  validation_set_features.npy   176 MB, downloaded whole — used to measure
                                the false-alarm rate
  mit_rirs/                     ~270 real room recordings, so the model
                                hears the phrase with echo
  background_clips/             noise and babble, generated here rather
                                than downloaded
  openwakeword_features_...npy  a slice of the big file, sized to fit
                                whatever budget is left

    python train/fetch_data.py --budget-gb 1
"""

import argparse
import struct
import sys
from pathlib import Path

import numpy as np
import requests

DATA = Path(__file__).resolve().parent / "data"
FEATURES_REPO = "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main"
RIR_REPO = "https://huggingface.co/datasets/davidscripka/MIT_environmental_impulse_responses/resolve/main"
BIG_FILE = "openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
VALIDATION_FILE = "validation_set_features.npy"


def human(n: int) -> str:
    return f"{n / 1e6:.0f} MB" if n < 1e9 else f"{n / 1e9:.2f} GB"


def download(url: str, dest: Path, byte_range: tuple[int, int] | None = None) -> None:
    """Download a file, optionally only the first chunk of it."""
    headers = {}
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"

    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        next_report = 10
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total and 100 * done / total >= next_report:
                    print(f"    {next_report}% ({human(done)})")
                    next_report += 10
        print(f"    done — {human(done)}")


def read_npy_header(url: str) -> tuple[dict, int, int]:
    """Peek at a remote .npy's header without downloading the whole thing.

    Returns (header dict, header length, total file size).
    """
    r = requests.get(url, headers={"Range": "bytes=0-255"}, timeout=60)
    r.raise_for_status()
    data = r.content
    if data[:6] != b"\x93NUMPY":
        raise SystemExit(f"{url} doesn't look like a .npy file")

    header_len = struct.unpack("<H", data[8:10])[0]
    header = eval(data[10:10 + header_len].decode())  # numpy writes a plain dict literal
    total = int(r.headers["content-range"].split("/")[1])
    return header, header_len, total


def fetch_feature_slice(budget_bytes: int) -> None:
    """Grab as many windows of the big negative-features file as fit."""
    url = f"{FEATURES_REPO}/{BIG_FILE}"
    print(f"  checking {BIG_FILE}...")
    header, header_len, total = read_npy_header(url)

    shape = header["shape"]
    dtype = np.dtype(header["descr"])
    row_bytes = int(np.prod(shape[1:])) * dtype.itemsize
    preamble = 10 + header_len

    rows_available = shape[0]
    rows_wanted = max(1, (budget_bytes - preamble) // row_bytes)
    rows = min(rows_wanted, rows_available)

    print(f"    full file: {shape[0]:,} windows, {human(total)}")
    print(f"    taking:    {rows:,} windows, {human(preamble + rows * row_bytes)}"
          f"  ({100 * rows / rows_available:.1f}% of it)")

    dest = DATA / BIG_FILE
    download(url, dest, byte_range=(0, preamble + rows * row_bytes - 1))

    # Rewrite the header so it describes what we actually downloaded. The
    # replacement is padded to the original length so the data after it
    # stays exactly where numpy expects.
    new_header = (
        "{'descr': '%s', 'fortran_order': False, 'shape': (%d, %s), }"
        % (header["descr"], rows, ", ".join(str(d) for d in shape[1:]))
    )
    padded = new_header.ljust(header_len - 1) + "\n"
    if len(padded) != header_len:
        raise SystemExit("new header doesn't fit — file layout changed upstream")

    with open(dest, "r+b") as f:
        f.seek(10)
        f.write(padded.encode())

    check = np.load(dest, mmap_mode="r")
    print(f"    verified: loads as {check.shape} {check.dtype}")


def fetch_rirs(limit: int) -> None:
    """Download real room impulse responses."""
    out = DATA / "mit_rirs"
    out.mkdir(parents=True, exist_ok=True)
    if len(list(out.glob("*.wav"))) >= limit:
        print(f"  mit_rirs: already have {len(list(out.glob('*.wav')))} files")
        return

    listing = requests.get(
        "https://huggingface.co/api/datasets/davidscripka/MIT_environmental_impulse_responses",
        timeout=60,
    ).json()
    names = [s["rfilename"] for s in listing["siblings"]
             if s["rfilename"].endswith(".wav")][:limit]

    print(f"  mit_rirs: downloading {len(names)} room recordings...")
    for i, name in enumerate(names, 1):
        dest = out / Path(name).name
        if dest.exists():
            continue
        r = requests.get(f"{RIR_REPO}/{name}", timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        if i % 50 == 0:
            print(f"    {i}/{len(names)}")
    print(f"    done — {len(list(out.glob('*.wav')))} files")


def make_background_clips(count: int, seconds: int) -> None:
    """Create background noise locally instead of downloading gigabytes.

    Real training uses hours of music and TV. We can't afford that inside a
    1 GB budget, so we synthesise a stand-in: white, pink and brown noise,
    which covers most of what a room actually sounds like.
    """
    import wave

    out = DATA / "background_clips"
    out.mkdir(parents=True, exist_ok=True)
    if len(list(out.glob("*.wav"))) >= count:
        print(f"  background_clips: already have {len(list(out.glob('*.wav')))}")
        return

    print(f"  background_clips: generating {count} x {seconds}s of noise...")
    rng = np.random.default_rng(0)
    n = 16_000 * seconds

    for i in range(count):
        white = rng.normal(0, 1, n)
        # Pink and brown noise are white noise with the high end rolled off,
        # which is what most room noise actually sounds like.
        colour = i % 3
        if colour == 0:
            audio = white
        else:
            spectrum = np.fft.rfft(white)
            freqs = np.fft.rfftfreq(n, 1 / 16_000)
            freqs[0] = freqs[1]
            spectrum /= freqs ** (0.5 if colour == 1 else 1.0)
            audio = np.fft.irfft(spectrum, n)

        audio = audio / (np.abs(audio).max() + 1e-9) * rng.uniform(2000, 12000)
        with wave.open(str(out / f"noise{i:03d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16_000)
            w.writeframes(audio.astype(np.int16).tobytes())
    print(f"    done — {len(list(out.glob('*.wav')))} files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-gb", type=float, default=1.0,
                        help="total download budget in GB (default 1)")
    parser.add_argument("--rirs", type=int, default=270, help="how many room recordings")
    parser.add_argument("--background", type=int, default=30, help="how many noise clips")
    args = parser.parse_args()

    budget = int(args.budget_gb * 1e9)
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"Budget: {human(budget)}\n")

    print("1. Validation features (needed to measure false alarms)")
    validation = DATA / VALIDATION_FILE
    if validation.exists():
        print(f"    already downloaded ({human(validation.stat().st_size)})")
    else:
        download(f"{FEATURES_REPO}/{VALIDATION_FILE}", validation)
    spent = validation.stat().st_size

    print("\n2. Room recordings")
    fetch_rirs(args.rirs)
    spent += sum(f.stat().st_size for f in (DATA / "mit_rirs").glob("*.wav"))

    print("\n3. Background noise (made here, not downloaded)")
    make_background_clips(args.background, seconds=10)

    print(f"\n4. Negative features — {human(budget - spent)} of budget left")
    remaining = budget - spent
    if remaining < 50e6:
        raise SystemExit("Budget too small — try --budget-gb 1 or more.")
    fetch_feature_slice(remaining)

    used = sum(f.stat().st_size for f in DATA.rglob("*") if f.is_file())
    print(f"\nDone. train/data/ is {human(used)}")


if __name__ == "__main__":
    sys.exit(main())
