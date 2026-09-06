# The dashboard

    http://192.168.4.95:8080

Three things a speaker with no screen cannot tell you: what it is doing
right now, whether the machine under it is healthy, and which network it is
on — the last mattering most, because getting the Wi-Fi wrong is the one
mistake that makes every other page unreachable.

`DASHBOARD=off` turns it off. `DASHBOARD_PORT` moves it.

## What is on it

**What it is doing.** The last twenty turns — what was asked, what was
answered, and what the wake word scored — plus timers running, what sound is
playing, and what book is being read and where it has got to.

The turns are tagged with how they ended: `answered`, `not for me` when
Claude decided the television was talking, and `woke, nobody spoke` when the
wake word fired and there was silence after it.

**How the machine is.** CPU, temperature, memory, disk, uptime, load, and
whether the Pi is throttling — charted over recent history as well as shown
as numbers. Plus whether each of the three services is up.

**Which network it is on**, and the ability to change it. This is the reason
the page can be worth its risk: a speaker on the wrong network is a speaker
you cannot reach any other way.

## What it can make the speaker do

A short list, deliberately:

| | |
|---|---|
| `stop` | stop everything — talking, reading, music, sounds, a ringing timer |
| `say` | speak a line of text, up to 200 characters |
| `sound` | start or stop a background sound |
| `volume` | set the music volume |
| `timer` | set a timer, in minutes |
| `restart` | restart the service — it answers first, then goes away |

## How it runs

Inside the speaker, on a daemon thread — not beside it. That is the whole
reason it can show anything interesting: what is playing, what timers are
set, what was asked a minute ago and what the wake word scored are all in
that process and nowhere else. A separate service would have to guess at
them from files.

The cost is a rule: **nothing here may ever raise into the speaker.** Every
handler is wrapped, the server is threaded so one slow request cannot block
another, and if the whole thing fails to start the speaker carries on
without it. The dashboard's own request log is silenced — the speaker's log
is for the speaker.

```bash
python src/dashboard.py     # serve it on its own, for development
```

## It has no password

Anybody who can reach the Pi can see what was asked in that room and change
which network it is on. **This belongs on a home network and nowhere else.**
Do not forward a port to it.
