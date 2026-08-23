# Claude Speaker — Design

*Source: hand-drawn design sketches (`design1.png`, `design2.png`) in the
project root.*

> **This is the original plan, kept as it was written.** It is a record of
> what was intended before any of it existed, not a description of what the
> speaker does now — several of its guesses turned out wrong, which is the
> interesting part. Notably it puts Spotify out of scope, and its list of
> files is about a third of the ones that exist today.
>
> For what the speaker actually is, start at the [README](../README.md).

## 1. What we're building

A voice-controlled speaker that you talk to and it talks back. You say a wake
phrase ("Hey Claude"), ask a question out loud, and the speaker answers out loud.

The sketch shows two steps:

```
Step 1                                    Step 2
                                                     ┌────────┐
  o    "Hey Claude"                          ( the   │        │
 /|\   ~~~~~~~~~~~~~ ))) ┌────────┐          answer  │ Claude │
 / \      (speech)       │ Claude │           is...) │        │
                         └────────┘                  └────────┘
  person speaks ────────► speaker            speaker speaks back
```

That's the whole product. Everything below is how we make those two steps work.

## 2. Requirements

From the sketch, plus what they imply:

| # | Requirement | Notes |
|---|-------------|-------|
| R1 | Written in Python | Stated in the sketch. |
| R2 | Runs on an OSX laptop | Stated in the sketch. No extra hardware — use the laptop's built-in mic and speakers. |
| R3 | Wakes on "Hey Claude" | From the speech bubble in step 1. It listens all the time but only acts after the wake phrase. |
| R4 | Answers out loud | From step 2. The reply is spoken, not printed. |
| R5 | Answers come from Claude | The box in the drawing is labeled "Claude", so the brain is the Claude API. |

Non-goals for v1: **no music / Spotify** (deferred — see §5), no phone app, no
separate hardware box, no multiple users, no remembering conversations after you
quit the program.

The whole of v1 is: talk to it, it talks back. Nothing else.

## 3. How it works

Five stages, in a loop:

```
 ┌───────────┐   audio    ┌──────────┐  "hey claude"  ┌────────────┐
 │ Microphone│ ─────────► │   Wake   │ ─────────────► │   Record   │
 │  (always  │            │  Word    │   detected     │  Question  │
 │ listening)│            │ Detector │                │  (until    │
 └───────────┘            └──────────┘                │  silence)  │
                                                      └─────┬──────┘
                                                            │ wav audio
                                                            ▼
 ┌───────────┐            ┌──────────┐                ┌────────────┐
 │  Speaker  │ ◄───────── │  Text to │ ◄───────────── │ Speech to  │
 │ (out loud)│   audio    │  Speech  │  answer text   │    Text    │
 └───────────┘            └──────────┘                └─────┬──────┘
                                ▲                           │ question text
                                │                           ▼
                                │  answer text        ┌────────────┐
                                └──────────────────── │   Claude   │
                                                      │  (+ tools) │
                                                      └────────────┘
```

1. **Listen** — the mic is always on, capturing small chunks of audio into a
   rolling buffer. Nothing is sent anywhere yet.
2. **Wake word** — a small local detector watches that buffer for "Hey Claude".
   Only local, so we're not streaming the room to the internet all day.
3. **Record the question** — once woken, play a short beep so the user knows it's
   listening, then record until they stop talking (about 1 second of silence).
4. **Understand + think** — turn the recording into text, send the text to
   Claude, get an answer back.
5. **Speak** — turn the answer text into audio and play it. Then go back to
   step 1.

## 4. The pieces

Each stage is one Python module with a small, boring interface, so any piece can
be swapped later without touching the others.

### `audio_in.py` — microphone
- Uses `sounddevice` (PortAudio) to read 16 kHz mono audio from the default input.
- Keeps a rolling buffer of the last few seconds.
- Detects end-of-speech with a simple energy threshold + silence timer, so we
  know when the user has finished their question.

### `wake.py` — wake word detector
- v1: [openWakeWord](https://github.com/dscripka/openWakeWord) or Picovoice
  Porcupine with a custom "Hey Claude" keyword. Both run locally on CPU.
- Interface: `wake.wait_for_wake()` blocks until the phrase is heard.
- Fallback if custom wake words turn out to be a hassle: press the spacebar to
  talk. Same interface, so the rest of the program doesn't care.

### `stt.py` — speech to text
- v1: `faster-whisper` running the `base.en` model locally. On Apple Silicon
  this transcribes a short question in well under a second and costs nothing.
- Interface: `stt.transcribe(audio) -> str`

### `brain.py` — Claude
- Calls the Claude API with the Anthropic Python SDK.
- Keeps a short conversation history (last ~10 turns) so follow-up questions
  like "what about tomorrow?" work.
- System prompt tells Claude it's a **speaker**: answer in one or two sentences,
  plain spoken language, no markdown, no bullet lists, no code blocks — because
  everything it writes is going to be read out loud.
- v1 is question-in, answer-out. No tools yet. Later this module grows a tool
  loop (see §5), and that's the only file that has to change.
- Interface: `brain.ask(question: str) -> str`

### `tts.py` — text to speech
- v1: the built-in macOS `say` command via `subprocess`. Zero setup, zero cost,
  works offline, and it's already on the laptop (R2).
- Upgrade path if the voice sounds too robotic: ElevenLabs or OpenAI TTS behind
  the same interface.
- Interface: `tts.speak(text: str)`
- While speaking, the mic input is ignored so the speaker doesn't hear itself
  and wake itself up.

### `main.py` — the loop
```python
while True:
    wake.wait_for_wake()
    tts.beep()
    audio = audio_in.record_until_silence()
    question = stt.transcribe(audio)
    answer = brain.ask(question)
    tts.speak(answer)
```

That's the whole program. Everything else is behind those five calls.

## 5. Spotify — answered, but not in v1

> **Deferred.** The sketch asks how this connects to Spotify. Here's the answer,
> written down so it isn't lost — but we are **not building it first**. Get the
> speaker talking (§7 steps 1–4), then come back to this. Nothing in v1 blocks
> it: adding music later means adding one file and a tool loop in `brain.py`,
> with no changes to the mic, wake word, transcription, or voice.

**Spotify has a Web API, and Claude can call it through a tool.**

The trick is that Claude doesn't play music itself. We give Claude a list of
*tools* it's allowed to use. When you say "play Bad Bunny", Claude doesn't answer
with words — it answers with "call the `play_music` tool with artist=Bad Bunny".
Our Python code sees that, calls Spotify, and the music starts.

```
 "play some Bad Bunny"
         │
         ▼
   ┌──────────┐   "use tool: play_music(artist='Bad Bunny')"
   │  Claude  │ ──────────────────────────┐
   └──────────┘                           ▼
         ▲                        ┌───────────────┐   HTTPS    ┌─────────┐
         │  "started playing"     │ spotify.py    │ ─────────► │ Spotify │
         └─────────────────────── │ (spotipy lib) │ ◄───────── │ Web API │
                                  └───────────────┘            └─────────┘
                                                                    │
                                                                    ▼
                                                          music plays in the
                                                          Spotify app on the
                                                          laptop
```

**What's needed:**

1. A free Spotify developer app at <https://developer.spotify.com/dashboard>,
   which gives a Client ID and Client Secret.
2. The `spotipy` Python library, which handles the OAuth login. The first run
   opens a browser to log in to Spotify once; after that the token is cached to
   disk and refreshed automatically.
3. The **playback control endpoints** (play/pause/skip/volume/search) require a
   **Spotify Premium account** — this is a Spotify rule, not something we can
   code around. Search and "what's playing" work on free accounts.
4. The Spotify desktop app should be open on the laptop, since the Web API
   controls an existing player rather than playing audio itself.

**Tools we'd expose to Claude:**

| Tool | What it does |
|------|--------------|
| `play_music(query)` | Search for a song/artist/album and start playing it |
| `pause_music()` | Pause |
| `resume_music()` | Resume |
| `skip_song()` | Next track |
| `set_volume(percent)` | Change volume 0–100 |
| `whats_playing()` | Return the current track and artist |

The same pattern adds anything else: a `get_weather` tool, a `set_timer` tool, a
`search_web` tool. Each one is a Python function plus a short description of when
to use it. Whichever we build first, the mechanism is identical — so it's worth
picking whichever is most fun rather than assuming music has to be the one.

## 6. Project layout

```
claude-speaker-tejas/
├── docs/
│   └── design.md          ← this file
├── design1.png            ← the sketches
├── design2.png
├── src/
│   ├── main.py            ← the loop
│   ├── audio_in.py        ← microphone
│   ├── wake.py            ← "Hey Claude" detector
│   ├── stt.py             ← speech → text
│   ├── brain.py           ← Claude
│   └── tts.py             ← text → speech
├── .env                   ← API keys (never committed)
└── requirements.txt
```

`.env` holds `ANTHROPIC_API_KEY` — that's the only key v1 needs. It goes in
`.gitignore` on day one.

Later, tools live in a `src/tools/` directory (`spotify.py` and friends). Not
created yet.

## 7. Build order

Each step is something you can run and hear working before starting the next.

| Step | Build | You can... |
|------|-------|-----------|
| 1 | `tts.py` | Make the laptop say "hello, I am Claude" |
| 2 | `brain.py` + `main.py`, typing questions | Type a question, hear Claude answer |
| 3 | `audio_in.py` + `stt.py`, spacebar to talk | Hold space, ask out loud, hear the answer |
| 4 | `wake.py` | Say "Hey Claude" — no keyboard at all. **This is the drawing.** |

**Step 4 is done.** That's the whole sketch working, and it's a good place to
stop, use it for a while, and see what's annoying about it.

Tools — Spotify, weather, timers — come after that, as step 5+. See §5.

## 8. Things to watch out for

- **It hears itself.** When the speaker talks, the mic picks it up and it can
  wake itself in a loop. Fix: mute the input while `tts.speak()` is running.
- **macOS permissions.** The terminal needs Microphone access under
  System Settings → Privacy & Security → Microphone, or recording silently
  returns zeros.
- **Wake word false alarms.** "Hey Claude" is a short phrase and similar sounds
  will trigger it. If it's annoying, raise the detector's confidence threshold.
- **Silence detection is fussy.** A fixed energy threshold misbehaves in a noisy
  room. If it cuts people off, raise the silence timeout to 1.5s and add a
  minimum recording length.
- **Latency budget.** Target under 3 seconds from end-of-question to first word
  of the answer: ~0.5s transcribe, ~1–2s Claude, ~0.3s speech. If Claude is the
  slow part, stream the response and start speaking the first sentence while the
  rest is still arriving.
- **Cost.** Whisper and `say` are free/local. Only the Claude API calls cost
  money, and short spoken questions are small requests.
- **Privacy.** The wake word runs locally and audio only leaves the laptop after
  "Hey Claude" is heard. Worth keeping that property as the design changes.

## 9. Ideas for later

- **Spotify** — play music by voice (§5 has the full answer already worked out).
- Remember conversations between runs (save history to a file).
- More tools: weather, timers, calendar, web search.
- A light or sound that shows when it's listening vs. thinking.
- Move it off the laptop onto a Raspberry Pi so it's a real box you can put on
  a shelf — which is what the drawing actually shows.
