# The dashboard

```
http://192.168.4.95:8080
```

Three things a speaker with no screen cannot tell you: what it is doing
right now, whether the machine under it is healthy, and which network it is
on — the last mattering most, because getting the Wi-Fi wrong is the one
mistake that makes every other page unreachable.

## Speaker

The default. What is playing, what timers are set, what was asked in the
last few minutes and what the wake word scored for each. Buttons for the
things worth doing from a phone: stop everything, put rain on, set a five
minute timer, make it say something.

Two charts, both drawn as inline SVG — no libraries, nothing fetched:

- **When it woke, by hour** — a day of firings, so a noisy evening is
  visible as a shape rather than a number.
- **Scores, with the threshold marked** — the histogram of what the wake
  word scored, with a dashed line where it fires. If the two humps are not
  well separated by that line, that is the whole problem in one picture.

## System

Processor, temperature, memory and disk now, and each of them over the last
half hour. Which services are up. And **whether the Pi has been
under-voltage or throttled since boot**, which is the commonest fault on
this hardware and the easiest to miss: it makes a Pi slow rather than
broken, so nothing ever says so.

## Wi-Fi

Which network, how strong, what else is in range, and a box to join a
different one. Changing it needs a polkit rule, because NetworkManager
guards system connections behind a password and a password prompt is not
something a web page in a kitchen can answer. `./deploy.sh` installs one
scoped to NetworkManager actions for the `netdev` group, which the Pi's
user is already in — the same bargain as the LED rule, hand the thing to a
group rather than becoming root. Without it the page shows the network and
says it cannot change it.

## How it is built

It runs **inside the speaker**, on a daemon thread, and that is the whole
reason it can show anything interesting: what is playing, what timers
exist, what was asked a minute ago and what the wake word scored are all in
that process and nowhere else. A service beside it would have to guess from
files.

The cost is a rule: nothing here may raise into the speaker. Every handler
is wrapped, the server is threaded so one slow request cannot block
another, and if it fails to start at all the speaker carries on without it.

Standard library only — `http.server` and `/proc`. No framework, no
`psutil`, nothing from a CDN, so it works with the internet down.

**It has no password.** Anybody who can reach the Pi can see what was asked
and change the network. That is a home network decision; `DASHBOARD=off` in
`.env` turns it off, and `DASHBOARD_PORT` moves it.
