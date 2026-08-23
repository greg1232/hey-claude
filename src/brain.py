"""The brain — sends the question to Claude and gets the answer back.

This is the only part that talks to the internet. Everything else (the
microphone, the speech recognition, the voice) runs on the laptop.
"""

from datetime import datetime
from pathlib import Path

import anthropic

import sys

import config
import weather

# This tells Claude it's a speaker, not a chat window. It matters a lot:
# without it Claude writes bullet lists and headings, which sound terrible
# when a robot voice reads them out loud.
SYSTEM_PROMPT = """You are the voice of a small speaker that sits on a desk. \
A person talks to you out loud and hears your answer read aloud by a \
computer voice.

Because everything you say is spoken, not read:
- Answer in one or two sentences. Three at the very most.
- Use plain spoken language, the way a friendly person would talk.
- Never use markdown, bullet points, numbered lists, headings, or code blocks.
- Don't use emoji, asterisks, or symbols that sound strange when read aloud.
- Write numbers and units the way you'd say them: "about twenty miles", \
not "~20mi".
- If a question is unclear, ask one short question back.

You are talking with a kid and their family, so keep it friendly and easy \
to follow. If you don't know something, just say so.

The questions come from speech recognition, so they arrive with no \
punctuation and the occasional wrong word. If something looks like a \
misheard word, guess what was meant from the sound of it rather than \
answering the wrong question."""


def _timezone_name() -> str:
    """The IANA zone if we can find it, otherwise the short abbreviation.

    "America/Los_Angeles" says more than "PDT" — it pins down roughly where
    the speaker is, which helps with questions like how long until sunset.
    """
    link = Path("/etc/localtime")
    if link.is_symlink():
        parts = Path(link.readlink()).parts
        if "zoneinfo" in parts:
            return "/".join(parts[parts.index("zoneinfo") + 1:])
    return datetime.now().astimezone().tzname() or "unknown"


def _part_of_day(hour: int) -> str:
    """How a person would describe this hour out loud."""
    if hour < 5:
        return "very early morning"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "late evening"


def _now_block() -> str:
    """Facts about right now, refreshed for every question.

    This is rebuilt per question rather than at startup, because a speaker
    on a shelf runs for hours — a clock captured when the program launched
    would be wrong by dinner time.
    """
    now = datetime.now().astimezone()
    date = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    clock = now.strftime("%I:%M %p").lstrip("0").lower()

    lines = [
        "Things you can't work out for yourself:",
        f"- Right now it is {date}, {clock} — the {_part_of_day(now.hour)}.",
        f"- The time zone here is {_timezone_name()}.",
    ]
    if config.LOCATION:
        lines.append(f"- The speaker is in {config.LOCATION}.")
    today = weather.summary()
    if today:
        lines.append(f"- Weather: {today}")
    if config.HOUSEHOLD:
        lines.append(f"- You're talking with {config.HOUSEHOLD}.")
    lines.append(
        "- Your training data stops well before today. If a question turns "
        "on recent events, say what you knew and roughly when, rather than "
        "guessing."
    )
    return "\n".join(lines)


# The speaker can only listen and talk. Without saying so, Claude agrees to
# set timers and play songs, and then nothing happens — which is worse than
# saying no, especially to a kid who's waiting for a timer that never rings.
LIMITS = """What this speaker can and can't do:
- You can only listen and talk. You have no timers, alarms, music, \
shopping, smart-home controls, phone calls, messages, calendar, or internet \
search. Today's weather is the one live thing you're given, and only when \
it appears below.
- If you're asked for one of those, say plainly that you can't do it yet, in \
one short sentence. Never say you've set, started, played, or ordered \
anything — nothing happens when you say that.
- You can still answer the question behind the request. If someone asks you \
to set a ten minute timer, tell them you can't, but you can say what time it \
will be in ten minutes.
- You remember only the last few minutes of talking, and you forget \
everything when the speaker is switched off. Don't promise to remember \
something for later."""


def _system_prompt() -> str:
    wake = "hey Claude" if "claude" in config.WAKE_MODEL.lower() else "hey Jarvis"
    name = (
        f"People wake you by saying \"{wake}\", then asking their question. "
        "If someone asks what you're called or how to talk to you, that's the "
        "answer."
    )
    return f"{SYSTEM_PROMPT}\n\n{LIMITS}\n\n{name}\n\n{_now_block()}"


# What to say when something goes wrong. Spoken out loud, so keep it short.
TROUBLE_MESSAGE = "Sorry, I had trouble thinking about that. Try again?"

# Nice to have, but not every model accepts them. Grouped so that one
# rejected key drops only the feature it belongs to.
_OPTIONAL_FEATURES = {
    # A speaker should answer fast. Low effort keeps Claude from thinking
    # longer than a spoken question deserves.
    "low effort": {"output_config": {"effort": "low"}},
    # If a safety check declines the request, retry it on another model
    # automatically instead of going silent.
    "server-side fallback": {
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    },
}


class Brain:
    """Claude, plus a short memory of the conversation so far."""

    def __init__(self) -> None:
        if not config.ANTHROPIC_API_KEY:
            raise SystemExit(
                "No API key found.\n"
                "Copy .env.example to .env and put your key in it:\n"
                "    cp .env.example .env\n"
                "Get a key at https://console.anthropic.com/settings/keys"
            )
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        # The conversation so far, so follow-up questions like
        # "what about tomorrow?" make sense.
        self.messages: list[dict] = []
        # Not every model takes the same options — Sonnet rejects
        # `fallbacks`, Haiku rejects `effort`. Rather than keep a list of
        # which model supports what and watch it go stale, ask for the extras
        # once and drop whichever the model complains about.
        self.extras = dict(_OPTIONAL_FEATURES)

    def ask(self, question: str) -> str:
        """Send a question to Claude and return the spoken answer."""
        self.messages.append({"role": "user", "content": question})
        self._forget_old_turns()

        try:
            response = self._create()
        except anthropic.APIError as error:
            print(f"[Claude error] {error}")
            self.messages.pop()  # Don't remember a question that failed.
            return TROUBLE_MESSAGE

        answer = _text_of(response)
        if not answer:
            # Claude declined to answer, or returned nothing at all.
            self.messages.pop()
            return "Sorry, I can't help with that one."

        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def _create(self):
        """Ask Claude, dropping any option this model won't accept.

        The API rejects the whole request with a 400 naming the offending
        parameter, so we can take it out and try again. Each option is only
        lost once — after that the model runs without it.
        """
        while True:
            try:
                return self.client.beta.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=4000,
                    # Rebuilt per question so the clock is current — see
                    # _now_block().
                    system=_system_prompt(),
                    messages=self.messages,
                    **{k: v for extra in self.extras.values()
                       for k, v in extra.items()},
                )
            except anthropic.BadRequestError as error:
                unsupported = [
                    name for name, extra in self.extras.items()
                    if any(f"`{key}`" in str(error) or f"'{key}'" in str(error)
                           for key in extra)
                ]
                if not unsupported:
                    raise
                # Not worth telling the person on the sofa about — these are
                # speed and reliability extras, and the answer is the same
                # either way.
                for name in unsupported:
                    del self.extras[name]

    def _forget_old_turns(self) -> None:
        """Keep only the most recent turns, so the conversation stays small."""
        limit = config.HISTORY_TURNS * 2  # A turn is a question and an answer.
        if len(self.messages) > limit:
            self.messages = self.messages[-limit:]


def _text_of(response) -> str:
    """Pull the plain text out of Claude's response.

    The response is a list of blocks — some are thinking, some are text —
    so we collect the text ones and ignore the rest.
    """
    parts = [block.text for block in response.content if block.type == "text"]
    return " ".join(part.strip() for part in parts).strip()


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        raise SystemExit

    # Step 2 of the build order: type a question, hear Claude answer.
    import tts

    brain = Brain()
    print("Type a question (or press Enter to quit).")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        answer = brain.ask(question)
        print(f"Claude: {answer}")
        tts.speak(answer)
