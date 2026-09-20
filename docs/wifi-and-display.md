# Wi-Fi it can remember, and a screen you can plug in

**This is a plan, not a description.** Nothing below is built yet. When it
is, it belongs in [dashboard.md](dashboard.md) and this file should be
deleted — a plan kept after the thing exists is how `docs/design.md` ended
up claiming Spotify was out of scope.

Two features that look separate and are not. The speaker knows one Wi-Fi
network. If that network changes, the dashboard is unreachable, and the
dashboard is where you would fix the Wi-Fi. A screen you can plug in is the
way out of that loop.

## Where it stands today

Measured on the Pi, not assumed:

| | |
|---|---|
| Networks it knows | **one** — `netplan-wlan0-solus`, autoconnect, priority 0 |
| `join_wifi()` | joins a network **that is in range right now** |
| Saved networks | not listed, not removable, not addable in advance |
| polkit | already grants **every** `org.freedesktop.NetworkManager.*` action to `netdev` |
| Compositor | labwc, under lightdm |
| Browser | `/usr/bin/chromium` (and firefox) |
| Displays | two micro-HDMI, both currently `disconnected` |
| Memory free | 2911 MB of 3795 |
| Desktop already costs | 216 MB, with no display attached |

Two of those matter more than the rest. **The permission work is already
done** — `deploy.py` installs a polkit rule covering the whole
NetworkManager action family, so adding and deleting connections needs no
new privileges, only new code. And **the desktop is already running** with
nothing plugged in, so a screen costs a browser, not a graphical stack.

## Part one: networks it can remember

### What you should be able to do

- See every network it has saved, and which one it is on.
- **Add one it cannot currently see.** This is the whole point. Typing in
  the network at the grandparents' house before you drive there is the
  difference between a speaker you can move and one you cannot.
- Add a hidden network, by name.
- Forget one.
- Join a visible one now — which already works, and stays.

### The commands behind each

Everything is `nmcli`, and all of it is already permitted:

    list     nmcli -t -f NAME,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show
    save     nmcli connection add type wifi con-name <name> ssid <name> \
                 wifi-sec.key-mgmt wpa-psk wifi-sec.psk <password>
    hidden   ...and 802-11-wireless.hidden yes
    forget   nmcli connection delete <name>
    join     nmcli device wifi connect <name> password <password>   (exists)

`nmcli connection add` is the one that does not exist yet and is the reason
for the feature: unlike `device wifi connect`, it does not need the network
to be in range.

### The shape of it

`GET /api/wifi` grows a `saved` list beside the `networks` it can see:

```json
"saved": [
  { "name": "solus", "priority": 0, "autoconnect": true, "current": true },
  { "name": "grandma", "priority": 0, "autoconnect": true, "current": false }
]
```

`POST /api/wifi` takes an `action`, defaulting to `join` so nothing that
works today stops working:

| action | does |
|---|---|
| `join` | connect now, and save (today's behaviour) |
| `save` | save for later, do not connect, no need to be in range |
| `forget` | delete the saved network |

### Three rules it has to keep

**Never send a password back.** nmcli will hand over stored secrets if
asked. Nothing in `GET /api/wifi` may ever ask. The page shows names, not
credentials, and there is no "reveal" — if somebody has forgotten the
password, they can retype it.

**Refuse to forget the network you are on**, unless another saved network
is in range to fall back to. Deleting the connection currently carrying the
request is a way to make the speaker unreachable from the page that did it.

**Say plainly that this is a home-network tool.** The dashboard has no
password, so a Wi-Fi password typed into it crosses the LAN in the clear
and anyone who can reach the Pi can add a network to it. That is already
true of joining, and it is the same bargain as the rest of the page — but
adding *stored credentials* is the first thing here that outlives the
moment, so it should be said out loud rather than left implied.

## Part two: a screen you can plug in

Plug a monitor into either micro-HDMI and the dashboard should be on it,
full screen, with no desktop, no browser chrome and no cursor.

### How it should start

Chromium in kiosk mode on the labwc session:

    chromium --kiosk --ozone-platform=wayland \
             --app=http://localhost:8080 \
             --no-first-run --disable-session-crashed-bubble --disable-infobars

The flags after `--app` are not decoration: without them the first thing a
plugged-in screen shows is a first-run dialog or a "Chromium didn't shut
down properly" bar, which is a worse first impression than a black screen.

### Only when something is plugged in

The obvious build starts it with the session and leaves it running. That
costs a few hundred megabytes and some processor for ever, on ten speakers
of which perhaps one will ever have a screen — and the wake word is already
using **87% of a core**.

So watch instead. The kernel already says:

    $ cat /sys/class/drm/card1-HDMI-A-1/status
    disconnected

A small service polling that every few seconds, starting chromium on
`connected` and stopping it on `disconnected`, is a dozen lines and is
trivially debuggable. udev emits DRM change events and would avoid the
poll, but routing a udev event into a user service is more machinery than
reading a file, and this file is the truth either way.

Whichever of the two ports is live is the one to open on.

### What needs checking rather than assuming

- **Blanking.** Nothing obviously runs an idle daemon on this image, so the
  screen may simply never blank — or lightdm may have its own opinion.
  Worth measuring before writing code to prevent something that does not
  happen.
- **The cursor.** With no mouse attached a pointer parked in the middle of
  the screen looks broken. labwc may hide it on its own; if not, that is a
  compositor setting, not a chromium flag.
- **Which output labwc picks** when both ports are populated.

### It is worth checking the page still reads

The dashboard already sets `width=device-width`, caps at `52rem` and lays
its tiles out with `auto-fit`, so it should survive a small screen without
changes. Should is not measured — look at it on the actual monitor before
declaring it done.

## Why these are one feature

The recovery story is the reason to build both:

    the network changes
        -> the speaker cannot join it
        -> the dashboard is unreachable over the network
        -> plug in a screen
        -> the dashboard is there
        -> type the new network in
        -> it joins, and remembers

That last leg needs a keyboard, and a keyboard needs a USB port. The case
has a doorway at 0° for exactly this — it exists "so Ethernet and the four
USB ports stay reachable without taking the lid off". It was drawn for a
different reason and it turns out to be the thing that makes this work.

A touchscreen would do the same job with an on-screen keyboard, and is
probably the nicer answer for a speaker on a shelf. It is not required and
should not be assumed.

## Deliberately not in this

- **No password on the dashboard.** Adding one is a real discussion about
  where the password lives and what happens when it is forgotten. It is not
  this feature, and this feature does not make the case for it any weaker.
- **No captive portal or access-point mode.** The usual way to solve
  first-time Wi-Fi is for the device to become an access point you join
  from a phone. It is a much larger build, and a screen and a keyboard
  solve the same problem with parts already in the house.
- **No purpose-built screen layout.** The plugged-in display shows the
  dashboard as it already is. A calmer face for a shelf — the time, a
  timer, what is playing — is a good idea and a separate one.
