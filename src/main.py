"""Claude Speaker — the whole program.

You talk to it, it talks back.

    Listen  ->  Wake word  ->  Record  ->  Transcribe  ->  Claude  ->  Speak
      ^                                                                  |
      +------------------------------------------------------------------+

Run it with:
    python src/main.py            listen for the wake word (or press Enter)
    python src/main.py --text     type questions instead of speaking them
"""

import sys

import audio_in
import brain
import config
import stt
import tts
import wake
import weather


def run_voice_mode() -> None:
    """The real thing: talk to it, it talks back."""
    print("Starting up...")
    the_brain = brain.Brain()
    weather.start()  # Fetches in the background; never blocks a question.
    stt.warm_up()  # Load the speech model now so the first question is fast.
    tts.warm_up()  # ...and the voice, so the first answer is too.
    waker = wake.make_waker()

    with audio_in.Microphone() as mic:
        mic.measure_noise_floor()  # Listen for a moment before saying ready.
        # Ctrl-C is only an answer if someone is looking at a terminal. When
        # this is running in the background its output goes to a log, and
        # telling the reader to press a key there is just confusing.
        stop = ("Press Ctrl-C to stop." if sys.stdout.isatty()
                else "Stop it with ./start.sh --stop")
        print(f"\nReady — {waker.label}. {stop}\n")

        while True:
            # 1. Wait to be woken up.
            if not waker.wait_for_wake(mic):
                break

            # 2. Beep so the person knows it's listening.
            tts.beep()
            print("Listening...")

            # 3. Record until they stop talking. The cutoff is worked out
            # from the room as it sounded just now, not as it sounded when
            # the speaker was switched on — televisions get turned on.
            audio = mic.record_until_silence()

            # 4. Turn the recording into words.
            question = stt.transcribe(audio)
            if not question:
                print("(didn't catch that)")
                tts.speak("Sorry, I didn't catch that.")
                continue
            print(f"You: {question}")

            # 5. Ask Claude, then say the answer out loud.
            answer = the_brain.ask(question)
            print(f"Claude: {answer}\n")
            tts.speak(answer)


def run_text_mode() -> None:
    """Type questions instead of speaking them. Handy for testing."""
    the_brain = brain.Brain()
    print("Type a question (or press Enter to quit).\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break

        answer = the_brain.ask(question)
        print(f"Claude: {answer}\n")
        tts.speak(answer)


def main() -> None:
    text_mode = "--text" in sys.argv

    try:
        if text_mode:
            run_text_mode()
        else:
            run_voice_mode()
    except KeyboardInterrupt:
        pass  # Ctrl-C is a normal way to stop.

    print("\nBye!")


if __name__ == "__main__":
    main()
