# Training a "Hey Claude" wake word — on this laptop

The speaker wakes on **"hey jarvis"** out of the box, because that's one of
the few wake words openWakeWord ships pre-trained. This is how to train
**"Hey Claude"** yourself, entirely on the MacBook. No Colab, no GPU, no
uploading anything.

You will not have to say "Hey Claude" into a microphone even once — the
training generates its own voices.

**Budget: about 1 GB downloaded, about an hour.** Measured on an M2 Air.

```bash
pip install -r train/requirements-train.txt                 # once
python train/fetch_data.py --budget-gb 1                    # ~5 min
python train/generate_clips.py --phrase "hey claude" \
       --out train/hey_claude --count 2000 --count-test 400 \
       --count-negative 6000 --count-negative-test 1200 \
       --adversarial 60 --verify --workers 6                # ~50 min
python train/train_local.py --training_config train/hey_claude.yml \
       --augment_clips --train_model                        # ~10 min
cp train/hey_claude.onnx models/                            # install it
```

Then set `WAKE_MODEL=hey_claude.onnx` in `.env`.

Nearly all of that hour is making clips, not training — training itself is
**about 8 minutes** for openWakeWord's full 50,000 steps, because the only
part being trained is a small head on a frozen audio embedding. The slow
part is `--verify`, which plays every positive clip back through Whisper;
that's why it runs across 6 processes.

The rest of this page explains each step, and the three mistakes that cost
the most time here — they're easy to repeat.

## How it works

openWakeWord's own models were built from **100% synthetic speech**. A
text-to-speech engine says the phrase thousands of times in different
voices, and those are the positive examples. Mix in a lot of *other* audio —
speech, music, noise — as negatives, and a small network learns to tell them
apart. Out comes a ~1 MB `.onnx` file that runs on the laptop.

```
 "hey claude"  ──► Piper text-to-speech ──► thousands of voices  ┐
                   (904 speakers, varied speed)                  ├─► train ─► hey_claude.onnx
 speech + music + noise ────────────────► "not the wake word"    ┘
```

## What had to be worked around

openWakeWord's trainer was written for Linux with an NVIDIA GPU. Five
things break on a Mac, and this project already handles all of them — this
list is here so the failures make sense if you hit them:

| Problem | Handled by |
|---|---|
| `piper-sample-generator` (its clip generator) needs `piper-phonemize`, which has **no build at all** for Apple Silicon | `train/generate_clips.py` makes the clips with `piper-tts` instead |
| The trainer imports that generator on startup **even when you skip that stage** | `train/stub/generate_samples.py` satisfies the import |
| `acoustics` imports `scipy.special.sph_harm`, removed in scipy 1.17 | `train_local.py` points it at `sph_harm_y` |
| `torch_audiomentations` calls `torchaudio.info`, removed in torchaudio 2.11 | `train_local.py` reads the wav header instead |
| PyTorch data workers can't be pickled on macOS (spawn, not fork) | `train_local.py` loads batches in-process |
| torch 2.13 writes model weights to a separate `.onnx.data` file | `train_local.py` forces them to stay inside the `.onnx` |

You do **not** need Colab Pro, and you do not need the community fork of the
notebook.

## Step 1 — install the training packages

Only needed while training; the speaker itself doesn't use any of them.

```bash
source .venv/bin/activate
pip install -r train/requirements-train.txt
```

About 2 GB, mostly PyTorch.

## Step 2 — make the clips (about 50 minutes)

```bash
python train/generate_clips.py --phrase "hey claude" --out train/hey_claude \
    --count 2000 --count-test 400 \
    --count-negative 6000 --count-negative-test 1200 \
    --adversarial 60 --verify --workers 6
```

This writes four folders of 16 kHz clips: the phrase for training and
testing, and sound-alikes ("hey cloud", "hey clyde", "okay cloud") that
teach the model what to ignore.

**Use `--verify`.** Some voices slur the phrase into something else — "hate
cloud", "he clogged" — and those are mislabelled data that teach the model
the wrong sound. `--verify` plays each clip back through Whisper and throws
away the ones that don't clearly say it. Measured on a sample of 20:
**15/20 usable without it, 20/20 with it.**

It's also the slow part, about 2.4 seconds a clip against 0.06 for synthesis
alone, so `--workers` splits it across processes. Only positives get checked;
a garbled negative is still a fine example of "not the wake word", which is
why 7,200 negatives cost less than 2,400 positives.

Try `--count 20` first and listen:

```bash
afplay train/hey_claude/positive_train/$(ls train/hey_claude/positive_train | head -1)
```

### Three things that go wrong here

**1. Not every Piper voice can say your phrase.** Measured pass rates for
"hey claude": `en_US-libritts_r` 92%, `en_GB-vctk` 52% — but
`en_US-l2arctic` **0%**, `en_GB-aru` **0%**, `en_US-arctic` 8%,
`en_GB-northern_english_male` 12%. A voice near zero burns dozens of
synthesis attempts per usable clip and contributes nothing. Check before
committing to a long run:

```bash
python train/voice_audit.py --voices en_US-joe-medium en_GB-alan-medium
```

**2. Never put a homophone in the negatives.** "Clawed" is `K L AO D` —
*exactly* the sounds in "Claude". Listing "hey clawed" as something to
reject asks the model to tell apart identical audio; it can't, so it wrecks
the wake word trying. Doing this dropped held-out recall from 100% to 40%
and no amount of weight tuning recovered it. `drop_homophones()` now removes
these automatically, including from the auto-generated phrases, and prints
what it dropped. The flip side: the finished model **will** wake on "he
clawed at the door", and that is not a bug you can fix.

**3. Generate both classes from the same voices.** If positives come from
eleven voices and negatives from three, the model can separate them by voice
instead of by the phrase — and it will score beautifully on your own test
data while failing on a real person.

## Step 3 — get the background data (about 1 GB)

```bash
python train/fetch_data.py --budget-gb 1
```

That one command gathers everything, staying inside the budget:

| What | Size | Where it comes from |
|---|---|---|
| Negative features | ~785 MB | A **slice** of a 17.3 GB file (see below) |
| Validation features | 177 MB | Downloaded whole — measures false alarms |
| 270 room recordings | 8.5 MB | Real MIT impulse responses |
| 30 background noise clips | 9.3 MB | Generated here, not downloaded |

**How the 17.3 GB becomes 785 MB.** The negative-features file is what
teaches the model to stay quiet during ordinary life, and it's normally a
17.3 GB download. But it's a plain `.npy` — 5,625,000 windows of `float16`
— and the server supports range requests. So `fetch_data.py` downloads only
the first slice and rewrites the file header to say how many windows it
actually took. The result is a smaller but completely valid file:
**262,626 windows, 4.7% of the original.**

Want a better model later? Raise the budget and re-run:

```bash
python train/fetch_data.py --budget-gb 5
```

Only the slice grows; the other files are skipped if already there.

**The honest trade-off:** less negative data means the model has seen less
of the world, so it's more likely to wake up on something that isn't you.
`WAKE_THRESHOLD` (step 6) is the dial for that, and a bigger budget is the
real fix if it bothers you.

## Step 4 — train (about 10 minutes)

```bash
python train/train_local.py --training_config train/hey_claude.yml \
       --augment_clips --train_model
```

Two stages: mixing the clips with room echo and noise (~2 min), then
training (~8 min).

Training is much cheaper than it sounds, because openWakeWord freezes a
pre-trained audio embedding and only fits a small network on top. Measured
here at **200–250 steps a second on CPU**, so the config uses openWakeWord's
full default of **50,000 steps**. There is no reason to cut it down.

**Never pass `--generate_clips`** — that's the stage that needs the package
which won't install. The script stops you with an explanation if you try.

Settings worth knowing, in `train/hey_claude.yml`:

| Setting | What it does |
|---|---|
| `steps` | `50000` ≈ 8 min. openWakeWord's default; leave it. |
| `max_negative_weight` | **The main dial.** See below. |
| `n_samples` | Only used when generating clips, which we don't. Ignored here. |

`max_negative_weight` trades waking reliably against staying quiet, and the
right value depends on how many negatives you made. Measured with 2,000
positives and 6,000 negatives:

| Weight | Wakes on the phrase | Stays quiet |
|---|---|---|
| 100 | all 5 test voices | poor — "hey clyde" 0.99 |
| 500 | all 5 test voices | fair — "hey cloud" 0.82 |
| 1500 | 4 of 5 test voices | good — "hey cloud" 0.22 |

Too high is not "safer": at 1500 with too *few* negatives, held-out recall
fell to 40%. If yours won't wake, lower it before adding data.

If a run crashes partway, add `--overwrite` — otherwise it sees the
half-finished feature files and skips work it still needs to do.

## The scaled-down budget, and what it costs you

The recipe above fits in **~1 GB of downloads and ~1 hour**. openWakeWord's
full recipe is more like **17 GB and several hours**. Only one real trade
remains:

| Full recipe | Here | Effect |
|---|---|---|
| 17.3 GB of negative features | 785 MB slice (4.7%) | Model has "heard" less of the world → more false wakes |

The other two savings turned out not to be worth taking. 50,000 training
steps costs 8 minutes, not hours, so there's no reason to train less. And
cutting positives to 500 was a false economy — it was the *cause* of the
worst problem here, not a saving (see below).

Want a better model? The negative slice is the thing to grow:

```bash
python train/fetch_data.py --budget-gb 5    # only the slice grows
```

Then re-run steps 2–4 with `--overwrite`.

## Step 5 — install it

```bash
cp train/hey_claude.onnx models/
```

Then in `.env`:

```
WAKE_MODEL=hey_claude.onnx
```

Run `./start.sh` and it should print
`Loading the wake word from hey_claude.onnx...`

## Step 6 — check it before trusting it

Score the model against synthesized speech instead of repeating yourself all
afternoon:

```bash
say -o /tmp/probe.aiff "hey claude"
afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/probe.aiff /tmp/probe.wav
```

Then run that file through the model in 1280-sample chunks and look at the
peak score. The built-in "hey jarvis" model scores **0.999** on this test —
that's the bar. Also check it stays near 0 on a few minutes of ordinary
conversation, which is the failure that actually annoys people.

Then tune `WAKE_THRESHOLD` in `.env`:

| Problem | Fix |
|---|---|
| Wakes up on its own | Raise it: `WAKE_THRESHOLD=0.7` |
| Doesn't wake when you say it | Lower it: `WAKE_THRESHOLD=0.3` |

If a first attempt misfires a lot, the fix is more training data or more
steps, not a lower threshold.

## What's actually been tested here

The pipeline has been run end to end on this laptop many times, and the
resulting models were scored against speech they were never trained on:
macOS `say` voices (Samantha, Daniel, Karen, Moira, Fred), five voices per
phrase, scored in 1280-sample chunks.

Where the current model stands:

| Phrase | Peak score | |
|---|---|---|
| **"hey claude"** | **0.999** on 4 of 5 voices | wakes |
| "hey cloud" | 0.221 | quiet |
| "hey jarvis" | 0.001 | quiet |
| "what is the weather today" | 0.000 | quiet |
| "can you play some music please" | 0.000 | quiet |
| "hey clyde" | 0.998 | **false wake** |
| "he clawed at the door" | 0.996 | homophone — not fixable |

Held-back clips it never trained on: **98% of positives** wake it, **12% of
negatives** falsely do.

For reference, the stock `hey_jarvis` model scored with the identical
harness gets 0.999 with a +0.969 margin. That's the bar, and this isn't
there yet.

**Two honest caveats.** Every number above comes from synthesized speech —
whether it wakes for an actual child in an actual room is untested, and
that's the only test that counts. And the false-alarm rate was measured on
clean clips, not on a TV playing in the background; the 4.7% negative-data
slice is the likeliest cause if it misfires in a real room.

### A measurement mistake worth avoiding

openWakeWord is a *streaming* detector with a rolling audio buffer, and
`reset()` does not clear it. Scoring several clips through one `Model`
object lets each clip contaminate the next, which quietly corrupts every
number you get. Build a fresh `Model` per clip, and pad each clip with about
a second of silence so the buffer fills before the phrase arrives.

Sanity-check any scoring harness against the stock `hey_jarvis` model first.
If it doesn't score ~0.999 on "hey jarvis", the harness is wrong, not the
model. Testing one voice and one near-miss is also not enough — a model that
looked fine on "hey claude" vs "hey cloud" turned out to wake for only two
of five voices and to fire on "hey clyde" just as hard as on the real
phrase.

## Why not Picovoice Porcupine?

Porcupine used to be the easy path — type a phrase into a web console, get a
`.ppn` in five minutes. Not any more:

- The **free tier was discontinued on June 30, 2026** and existing free
  AccessKeys were disabled.
- Personal-account custom wake words are **non-commercial and expire after
  30 days**.

A wake word that stops working every month is wrong for a speaker on a
shelf. The openWakeWord file keeps working forever and runs entirely on the
laptop.

## Sources

- [openWakeWord](https://github.com/dscripka/openWakeWord) — the trainer, and the 100%-synthetic-speech approach
- [openwakeword_features](https://huggingface.co/datasets/davidscripka/openwakeword_features) — the pre-computed negative features
- [Picovoice free tier discontinuation](https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744)
