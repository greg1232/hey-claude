"""The brain — sends the question to Claude and gets the answer back.

This is the only part that talks to the internet. Everything else (the
microphone, the speech recognition, the voice) runs on the laptop.
"""

import anthropic

import config

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
to follow. If you don't know something, just say so."""

# What to say when something goes wrong. Spoken out loud, so keep it short.
TROUBLE_MESSAGE = "Sorry, I had trouble thinking about that. Try again?"


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

    def ask(self, question: str) -> str:
        """Send a question to Claude and return the spoken answer."""
        self.messages.append({"role": "user", "content": question})
        self._forget_old_turns()

        try:
            response = self.client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=self.messages,
                # A speaker should answer fast. Low effort keeps Claude from
                # thinking longer than a spoken question deserves.
                output_config={"effort": "low"},
                # If a safety check declines the request, retry it on another
                # model automatically instead of going silent.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
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
