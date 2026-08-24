# The wake word

The hardest part of this project, by a distance, and the part with the most
measurements attached. This is the whole story: why the obvious library
didn't work, what replaced it, where to put the threshold, an idea that
looked good and wasn't, and how the speaker learns from its own mistakes.

## About the wake word

The speaker listens for **"hey Claude"** using `models/hey_claude_whisper.npz`
— a classifier on top of Whisper's encoder. Set in `.env`:

```
WAKE_MODEL=hey_claude_whisper.npz
WAKE_THRESHOLD=0.99
```

### Why not openWakeWord

The project started with [openWakeWord](https://github.com/dscripka/openWakeWord),
and there's a trained model here for it (`models/hey_claude.onnx`, also on
the Hub as [gdiamos/hey-claude](https://huggingface.co/gdiamos/hey-claude)).
It scores 0.99 on the synthetic speech it was trained on. On real people it
scored **0.001**, and woke on 7 recordings out of 80.

Recording 80 real utterances from four people fixed that — 9% to 80% — and
broke false wakes instead: about 180 an hour on the real microphone.
Recording 40 minutes of the actual room cut that twelvefold. Widening the
head from 32 to 96 units lifted the whole curve. None of it broke the
underlying problem, which was that recall and false wakes moved together at
every threshold: the model was sliding one operating point rather than
telling two things apart.

The reason is in the shape of the thing. openWakeWord is a mel filterbank,
a **frozen 0.33M parameter CNN from 2020**, and a small head you train.
Measured on this Pi:

| stage | per 80 ms chunk | share |
|---|---|---|
| melspectrogram | 0.95 ms | 7% |
| frozen embedding CNN | 11.75 ms | **91%** |
| the head you train | 0.18 ms | **1%** |

Everything tunable is 1% of the compute. If the frozen 91% doesn't
distinguish your family saying "hey Claude" from your family saying
anything else, nothing on top can recover it — and it doesn't.

### Whisper's encoder instead

Whisper's `tiny.en` encoder was trained on a great deal more speech. Feed it
a two second window, keep the first 100 frames, mean and max pool, and put
a logistic regression on top. Same recordings, same room:

| | openWakeWord, best | **Whisper encoder** |
|---|---|---|
| recall at ~55 false wakes/hr | 42% | **84%** |
| recall at ~125 false wakes/hr | 59% | **91%** |
| cost on a Pi 4 | 0.16x realtime | 0.42x realtime |

Double the recall for two and a half times the compute, which a Pi 4 has to
spare — about 10% of the machine, leaving three cores for Whisper and the
voice. The trained part is 11 kB.

Two lessons are baked into `train/train_whisper_wake.py`, both learned the
hard way:

- **Negatives must include speech that isn't the wake word.** Trained
  against room noise alone it reached 94% recall and zero false wakes —
  by learning "somebody is talking". It fired on 86% of other spoken
  phrases.
- **Score it the way it runs.** Isolated clips gave 0 false wakes; sliding
  a window over the same audio continuously gave 391 an hour. A streaming
  detector has to be measured streaming.

### Making your own

```bash
python train/record_wake.py --speaker greg,ojas,tejas,ana --times 20
python train/record_room.py --minutes 30 --label tv
python train/train_whisper_wake.py
```

Record on the machine the speaker lives on, through its microphone. Twenty
utterances each from four people and forty minutes of room is enough. Say
it varied — closer, further, mumbled — and record the room at its noisiest,
television included. Then check it:

```bash
python train/test_wake.py models/hey_claude_whisper.npz --times 6
python train/test_silence.py models/hey_claude.onnx --seconds 180
```

**The openWakeWord models are still here** — `models/hey_claude.onnx` (also
on the Hub as [gdiamos/hey-claude](https://huggingface.co/gdiamos/hey-claude))
and `models/hey_claude-96.onnx`, the best one this project produced. Either
still loads if you set `WAKE_MODEL` to it. The pipeline that trained them —
5 GB of downloads, 80 minutes, and 2,200 lines — was removed once the
Whisper wake word beat it on every measurement. It's in the git history if
you want it back.

Other options, both in `.env`:

```
WAKE_MODEL=alexa      # openWakeWord's built-ins: hey_jarvis, alexa, hey_mycroft
WAKE_MODE=key         # skip the wake word — press Enter to talk instead
```

## Where to put the threshold

Held out entirely, the wake word catches 52% of one child's attempts, and
that number moves a lot with the threshold:

```
 threshold   recall, unseen voice   recall, known voices   room false/hr
     0.50            66%                   100%                 0.0
     0.80            55%                   100%                 0.0
     0.90            52%                    94%                 0.0
     0.99            38%                    58%                 0.0
```

It shipped at 0.99, which was throwing away nearly half the recall for
nothing measurable. It is 0.80 now. Two caveats on that table: the room
negatives were hard-mined against this same model, so `0.0/hr` is
optimistic — the real room gave about forty an hour at 0.99 — and the
"known voices" column is partly memorisation. The held-out column is the
honest one, and the shape is the point.

What makes a low threshold affordable is that a false wake is now silent.
It used to apologise out loud to an empty room; now nothing said means
nothing spoken, and television speech gets `(nothing)` back from Claude. A
false wake costs a flash of the LED ring and some CPU.

### Why there's no second-stage verifier

The obvious idea is to propose at a low threshold and confirm with a
stronger model. It doesn't work, and the way it fails is worth writing
down.

Whisper cannot transcribe the wake word at all. Against 80 real recordings
of four people saying "hey Claude":

```
tiny.en   4/80 =  5%
base.en  13/80 = 16%
```

It hears "It's hot", "Take that", "Great class", "Thank God" — all the
right rhythm and roughly the right vowels. The acoustics are fine and the
language model overrules them, because "Claude" is rare and "take that" is
common.

Biasing the decoder with `initial_prompt="Hey Claude."` takes tiny.en from
0% to 97%, and makes it three times faster. It also makes it say "Hey
Claude" on **58% of room noise and 55% of ordinary speech**. It isn't
recognising the phrase, it's repeating the prompt. `hotwords="Claude"` is
weaker in both directions, 63% on real ones, and not worth it either.

Which is a decent independent argument that the 768-number classifier is
doing real work a general speech model won't do for free.

## Teaching it your voice

```
"hey claude, I want to teach you what my voice sounds like"
"Say hey Claude about ten times while the light is purple, with a
 pause between each, and it'll go out when I've got enough."
"hey claude ... hey claude ... hey claude ..."
"Got eight. Give me a moment to learn them."
```

Nobody labels anything. The person was asked to repeat the wake word, so
every segment is the wake word by construction. That is the whole trick,
and it's the only cure for recall that doesn't involve sitting down with a
laptop and `record_wake.py`.

**The ring is the interface.** A spoken "stop when you're done" would be
recorded along with the repetitions, so the light has to carry it: purple
while listening, out when it has enough.

**It has to be able to reject rubbish**, since it is about to train on
whatever it heard. Each segment becomes the same 768 numbers the detector
scores, and anything that doesn't resemble the others is dropped — a
cough, a chair, a sibling shouting. That comparison must be made on
*standardised* vectors. Raw Whisper features share a large common
component and everything looks alike: a burst of noise scored 0.905
against real repetitions' 0.965, which is not a gap you can cut on.
Subtract the model's own mean and divide by its scale, and the same burst
falls to 0.09 against 0.62–0.81.

What it must *not* do is filter on the wake score. The repetitions worth
learning from are exactly the ones the model currently misses — two of
seven in testing scored 0.42 and 0.01 — so scoring them would keep only
what already works.

**Each repetition is then slid around the window**, six times, using the
pauses between the repetitions as room noise. The recording brings its own
backgrounds, which means this works on a machine with no room-noise
library. Measured on a voice the model had never met:

```
never met them             55% recall at threshold 0.8
8 recordings as they came  59%
8 placed at 6 offsets      64%
```

with no change in false wakes. That is the honest size of it: a few points
of recall, not a transformation. The features are frozen, and 48 new
examples against a bank of 2708 can only move a linear model so far. It
stacks with the threshold, which is the bigger lever.

Then it refits (under a second) and reloads the four small arrays without
touching the 56 MB encoder, so it takes effect while you're standing
there.

## Learning from its own mistakes

The wake word is wrong about forty times an hour with a television on, and
every one of those is a labelled training example nobody had to record. The
speaker keeps them.

```
python src/wake_log.py         what has fired, and how those turns went
python train/label_wakes.py    decide which were real
python train/relearn.py        fit a new model on them
```

**The vector is free.** When the wake word fires, the detector has just
turned two seconds of audio into 768 numbers — that encoder pass is 159 ms
on a Pi and is the entire cost of the wake word. Those numbers are what
retraining needs, so they are written down (1.5 kB) along with the audio
(64 kB, most recent 400 only, because this is an SD card).

**The label is nearly free too.** A firing followed by silence is almost
certainly a mistake; one followed by a question that got answered is almost
certainly real. The speaker works both of those out anyway while answering.

**The judge is better than the thing being judged.** `label_wakes.py`
transcribes the two seconds that fired with a *bigger* Whisper than the Pi
listens with — `small.en` against `tiny.en`, beam 5 against beam 1 — on a
laptop, with nothing waiting on it. If the window transcribes to something
that sounds like "hey Claude", it was real. Only what's left over goes to
Claude, in batches of twenty, with both transcripts and the time of day.

Claude cannot listen to the clip itself. The API takes text, images and
PDFs and rejects audio outright — tested, not assumed — so a transcript is
the way in, which is why it's worth making a good one.

**Retraining costs a second.** Not twenty minutes, because it never touches
audio: it joins the feature bank `train_whisper_wake.py` saved with the
logged vectors and fits. Measured on a Pi 4:

```
logistic regression, 30,000 x 768   0.67s
the same features from audio        159ms each, about 20 minutes
```

So the whole loop can run on the Pi, overnight, on data the Pi collected.
Logged examples are weighted above bank ones (`--weight 3`) because the
bank is a general model of the world and the log is the actual room.

`relearn.py` prints how the old and new models score on the logged firings
before writing anything, keeps the model it replaced as `.npz.previous`,
and `--dry` writes nothing at all.

```
WAKE_LOG=off
WAKE_LOG_CLIPS=400
```

## Listening to it yourself

```
./label.sh
```

Fetches the clips off the Pi, opens a page in your browser, and plays them
one at a time. **y** if that really was somebody saying the wake word, **n**
if it wasn't, **space** to hear it again. Your answers go back to the Pi and
are what the nightly retraining learns from — appended after the automatic
ones, so they win.

Nothing to install and nothing runs on the Pi: it copies the clips down,
serves them from your laptop on a free port, and appends your answers when
you stop.

When you stop, it says what you found:

```
Saved 60 answers to the Pi: 8 yes, 52 no.
  23 yes and 300 no altogether.
  8 more examples of somebody actually being heard — those are the ones
  the retraining measures recall against.
```

The yes answers are the scarce half and the number worth watching. The
first two hundred labels here were 202 no and 1 yes, which measures false
wakes perfectly and says nothing about whether the speaker hears anybody.

It picks the firings the machine could not label by itself, because those
are the ones it will be fitted on either way, then near misses somebody
repeated seconds later, which are the recall failures and cannot be found
any other way. Sixty at a time; `--all` for the lot.

**Then it shuffles them**, and mixes in about one in six clips that really
are the wake word. Sorted by kind you get a run of twenty television clips
and start answering "no" without listening, which is worse than not
labelling at all. The known ones do two jobs: they tell somebody who has
never done this what a real wake word sounds like through this array — not
obvious, since it compresses hard and a real one can be quieter than a
television — and afterwards they say whether the answers can be trusted.
They have negative numbers and are never sent to the Pi.

Two things had to be fixed before any of it worked. Clips are turned up on
the way out, because they come off the Pi at about sixteen decibels below
full scale and through laptop speakers that is indistinguishable from
nothing playing. And the first one waits for a click: browsers refuse to
play sound before you have interacted with the page, and refuse silently,
which looks exactly like a broken audio player.

## Nightly retraining, and why it can refuse

```
./relearn.sh          learn from today, now
./relearn.sh --dry    say what would change, change nothing
./relearn.sh --log    what the timer did on its own last night
```

A user systemd timer runs the same thing at four in the morning —
`Persistent=true`, so a Pi that was off does it when it next comes up
rather than losing the day. It labels with the free signals only; a nightly
job that needs the network and costs money is one that fails quietly for a
month.

**It only keeps the new model if the new model is better**, and this is not
a formality. Comparing before and after on the examples just fitted says
only that the fit converged — it said 100% and 0% the first night, and the
room went on waking the speaker every twenty seconds. A model can memorise
thirty-four clips of one evening's television and learn nothing whatever
about television.

So a fifth of the labelled firings are held back, the model is fitted
without them, and both models are asked about those. The first honest
measurement on this speaker:

```
on 67 firings held back from the fitting:
  before  catches 93% of the real ones, and still fires on  0.0% of the mistakes
  after   catches 85% of the real ones, and still fires on 42.9% of the mistakes
```

The retrained model would have been much worse, and the gate refused it.
That is the number to watch, and the reason `./label.sh` exists: the
automatic labels are good at the easy half and guess at the hard half.

## Where the data lives

One dataset version per model, and the model says which one.

```
data committed   ->  model fitted   ->  uploaded as
                     carrying that      models/2026-08-23-a1b2c3d4.npz
                     commit's sha
```

There is no backup button; `train/relearn.py` does it every time it
retrains. The data is committed *before* the fitting, so the sha names
exactly what the model was trained on rather than whatever the log looked
like once fitting finished. The sha goes inside the `.npz` as `dataset`,
and the speaker prints it at startup:

```
Loading the wake word from hey_claude_whisper.npz (whisper tiny.en)
  fitted 2026-08-23T19:20 on 1196 logged examples, dataset a1b2c3d4
```

That is the difference between "the wake word got worse last week" being
answerable and not.

It goes to a Hugging Face dataset repo, which is a git repository with
large-file storage behind it — so every retraining is a commit, and you can
go back to exactly the data behind a particular model. A `metadata.csv`
goes with it, one row per firing lined up with its recording, so the whole
thing is browsable in a page.

This also fixes something quietly wrong: the Pi keeps only the most recent
few hundred recordings, so the audio behind labels already given was being
deleted to make room. Archived, they are all kept.

**Private, and nothing here can make it public.** The recordings in
`train/real/` are four people who sat down and said "hey Claude" on
purpose. This is two second windows of a living room caught whenever the
detector fired — dozens an hour with a television on — containing whatever
was being said by whoever was in the room. Nobody chose to record most of
it.

Needs `HF_TOKEN` in `.env`, from
[huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). A
fine-grained token with write access to that one repository is enough, and
is what to use — this is a token sitting on a device in a living room.
Without it, retraining still works and simply says nothing is archived.

### What the gate judges on

Two kinds of label a person can vouch for, and they are both used:

- **Somebody listened to the clip** and said what it was (`./label.sh`).
- **Somebody said the wake word into it on purpose**, during enrolment.
  That is a positive by construction and every bit as certain.

What is *not* used for judging is the augmented copies of those enrolment
recordings — the same audio slid around the window to make more of it.
Fine to train on; scoring a model on variants of its own training data is
marking its own homework.

The two are reported apart, because enrolment is deliberate, clear and
close and spontaneous use is not:

```
after at 0.665: catches 88% of the real ones, and still fires on 14.9%
       (80% of the ones said to it, 89% of the ones taught to it)
```

If those two numbers drift far apart, that gap is the interesting thing and
should not be averaged away.

### And only on what neither model has seen

Holding examples out of the new fit is not enough on its own. The old model
was fitted on everything available at the time, so judging both on the same
set tests the new one on held-out data and the old one on its own homework.
That looked like the running model catching **100% of everything at a
threshold of 0.3**, which is not skill, it is memory.

Models carry the time they were fitted, so anything logged since is fair to
both. When there is not enough of it the older set is used and the report
says so plainly, rather than quietly producing a number that favours
whatever is already installed:

```
only 0 logged since the running model was fitted, so judging on everything
a person can vouch for — which flatters the one already trained on it
```



Somebody who sat and listened to a clip is the only ground truth here, so
that is what the promotion gate measures against — not a random slice of
everything, which was measuring agreement with the machine's own guesses
and is why the numbers swung between runs.

In practice it can only answer half the question. Labelling a day of a
television room produces almost entirely "no" — **142 of the first 143** —
which measures false wakes beautifully and says nothing about recall. So
human labels are used for the classes they cover, and machine labels fill
in the class they don't, with the report saying which was which:

```
judging on 143 firings a person listened to, plus 75 the machine
labelled to cover the other answer
```

The human half only grows, so two runs a week apart can be compared.

Getting human "yes" labels turns out to be the hard part, and for a reason
that took a while to see. Of the four hundred recordings the Pi keeps,
three hundred and twelve were near misses: the periodic sample writes one
every few minutes, which is four hundred and eighty a day into a four
hundred clip budget, and it was quietly evicting every recording of the
wake word actually firing — the only clips that can ever be labelled yes.
Those samples now keep the vector, which is what training needs, and not
the audio, which nobody was ever going to listen to.

The calibration clips can't fill the gap either: they are already known
positives, they have negative numbers, and they are deliberately never
saved. `./label.sh` says so now, having once reported them as saved.

First archive:

```
848 firings, 1304 near misses, 1826 labelled, 143 by a person, 400 with audio
```
