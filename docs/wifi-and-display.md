# Getting it onto a network, and keeping it there

**This is a plan, not a description.** Nothing below is built yet. When it
is, it belongs in [dashboard.md](dashboard.md) and this file should be
deleted — a plan kept after the thing exists is how `docs/design.md` ended
up claiming Spotify was out of scope.

Three pieces of one problem. The speaker knows one Wi-Fi network. If that
network changes, the dashboard is unreachable, and the dashboard is where
you would fix the Wi-Fi.

    remember more networks   so it can be moved without being reconfigured
    become one itself        so there is a way in when it knows none
    show a screen            so there is a way in when that fails too

## Where it stands today

Measured on the Pi, not assumed:

| | |
|---|---|
| Networks it knows | **one** — `netplan-wlan0-solus`, autoconnect, priority 0 |
| `join_wifi()` | joins a network **that is in range right now** |
| Saved networks | not listed, not removable, not addable in advance |
| NetworkManager | 1.52.1 |
| polkit | already grants **every** `org.freedesktop.NetworkManager.*` action to `netdev` |
| Radio | `WIFI-PROPERTIES.AP: yes` — it can be an access point |
| | WPA2 and CCMP, so that access point can have a password |
| `dnsmasq-shared.d` | already present, which is where a captive portal's DNS goes |
| Compositor | labwc, under lightdm |
| Browser | `/usr/bin/chromium` |
| Displays | two micro-HDMI, both `disconnected` |
| Memory free | 2911 MB of 3795 |

**The permission work is already done.** `deploy.py` installs a polkit rule
covering the whole NetworkManager action family, so saving connections,
deleting them and raising an access point all need no new privilege — only
new code.

## Part one: networks it can remember

### What you should be able to do

- See every network it has saved, and which one it is on.
- **Add one it cannot currently see.** Typing in the network at the
  grandparents' house before you drive there is the difference between a
  speaker you can move and one you cannot.
- Add a hidden network, by name.
- Forget one.
- Join a visible one now — which already works, and stays.

### The commands behind each

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
  { "name": "solus",   "priority": 0, "autoconnect": true, "current": true },
  { "name": "grandma", "priority": 0, "autoconnect": true, "current": false }
]
```

`POST /api/wifi` takes an `action`, defaulting to `join` so nothing that
works today stops working: `join` connects now and saves, `save` stores it
for later without needing to be in range, `forget` deletes it.

### Three rules it has to keep

**Never send a password back.** nmcli will hand over stored secrets if
asked. Nothing in `GET /api/wifi` may ever ask. The page shows names, not
credentials, and there is no "reveal" — somebody who has forgotten the
password can retype it.

**Refuse to forget the network you are on**, unless another saved network
is in range to fall back to. Deleting the connection currently carrying the
request is a way to make the speaker unreachable from the page that did it.

**Say plainly that this is a home-network tool.** The dashboard has no
password, so a Wi-Fi password typed into it crosses the LAN in the clear.
That is already true of joining, but stored credentials are the first thing
here that outlives the moment, so it should be said rather than implied.

## Part two: an access point, when it knows nowhere to go

An earlier draft of this file dismissed this as "a much larger build". That
was wrong, and measuring it is what showed it: the radio reports
`AP: yes`, NetworkManager is 1.52.1, and raising an access point is

    nmcli device wifi hotspot ifname wlan0 ssid "Claude Speaker" password "..."

which also brings up DHCP by itself, because the profile it creates is
`ipv4.method shared`. That is the whole access point. The work is not in
raising it. **The work is in deciding when to raise it and when to stop**,
and that deserves more care than the feature it enables.

### The part that is actually hard

There is one radio. An access point is not a second network alongside the
house — it is instead of it. While the AP is up the speaker has no
internet, so Claude cannot answer, the weather is stale and music will not
play. **This is a repair mode, and every rule below exists to make sure it
is a short one.**

    router reboots
        -> speaker loses the network for ninety seconds
        -> speaker raises an access point
        -> router comes back
        -> speaker is not on it, and is not looking

That is the failure to design against, and it is worse than the problem
being solved: a speaker that deserts a working network is harder to live
with than one that occasionally needs setting up.

So:

**Wait before raising it.** Several minutes of no connection, not several
seconds. A router reboot must pass without the speaker noticing.

**Not while Ethernet is up.** If `eth0` is carrying traffic there is
nothing wrong and nothing to fix.

**Give up on it.** If nobody joins the access point within, say, fifteen
minutes, tear it down and go back to looking for known networks — then try
again later. An unattended speaker must end up back on the house network on
its own once the house network returns.

**Drop it the moment a network is saved.** The portal's job is done when it
has credentials; it should stop being an access point and go and use them,
and say whether that worked.

### Telling somebody it has happened

This is where the speaker has an advantage over every headless box that has
ever needed its Wi-Fi setting up: **it can talk, and it has twelve LEDs.**

It should say so, out loud, in the room:

> I can't get onto the network. I've made one of my own called Claude
> Speaker — join it and I'll show you how to fix me.

And light the ring in a colour used for nothing else, so the state is
visible from the doorway. `lights.py` already has named states — this is
one more.

That also answers the question an access point otherwise raises: **where
does its password come from?** It cannot be open. An open access point lets
any passer-by reach a page with no password on it that can change your
Wi-Fi and read what was said in the room. So it has WPA2 — and the speaker
reads the password out when it announces itself, and shows it on a plugged
in screen if there is one. Nothing is printed on the bottom of anything,
and nothing has to be remembered.

### The captive portal part

The access point on its own works if you know to browse to `10.42.0.1`.
Nobody knows that. The portal is what makes it usable, and it is also what
stops phones abandoning the network: **iOS and Android both notice an
access point with no internet and offer to leave it**, unless it identifies
itself as a portal, in which case they open it instead.

Two pieces:

**Wildcard DNS**, so every name resolves to the speaker. NetworkManager
runs dnsmasq for shared connections and reads extra config from a directory
that already exists:

    /etc/NetworkManager/dnsmasq-shared.d/  ->  address=/#/10.42.0.1

**Something answering on port 80** that redirects to the dashboard, so the
probe each OS makes (`captive.apple.com`, `connectivitycheck.gstatic.com`
and the rest) comes back as a redirect rather than the success text it
expects, which is the signal that pops up the sign-in sheet.

Port 80 is the one real obstacle: the dashboard runs as an ordinary user on
8080 and low ports need privilege. The options are a sysctl
(`net.ipv4.ip_unprivileged_port_start=80`), an nftables redirect from 80 to
8080, or `CAP_NET_BIND_SERVICE` on the service. The sysctl is one line in
`deploy.py` and fits the pattern already used for the LED ring and for
polkit — grant one narrow thing once, with a comment saying why — at the
cost of letting any process on the Pi bind a low port. On a single-purpose
speaker that is a fair trade, but it is a trade and should be written down
where somebody can disagree with it.

## Part three: a screen you can plug in

With an access point, this is no longer the way out of the lock-out loop —
a phone is, and everybody has one. **This is now a diagnostic**: the thing
you reach for when the access point itself did not come up, or when you
want to watch what the speaker is doing without another machine.

That is a real demotion and worth being honest about. It was the headline
in the first draft of this plan and it should not be built first.

Plug a monitor into either micro-HDMI and the dashboard should be on it,
full screen, with no desktop, no browser chrome and no cursor:

    chromium --kiosk --ozone-platform=wayland \
             --app=http://localhost:8080 \
             --no-first-run --disable-session-crashed-bubble --disable-infobars

The flags after `--app` are not decoration: without them the first thing a
plugged-in screen shows is a first-run dialog or a "Chromium didn't shut
down properly" bar.

**Only when something is plugged in.** The obvious build starts it with the
session and leaves it running, which costs a few hundred megabytes for ever
on ten speakers of which perhaps one will have a screen — and the wake word
already takes 87% of a core. The kernel already says:

    $ cat /sys/class/drm/card1-HDMI-A-1/status
    disconnected

A small service polling that, starting chromium on `connected` and stopping
it on `disconnected`, is a dozen lines and is trivially debuggable.

### What needs checking rather than assuming

- **Blanking.** Nothing obviously runs an idle daemon on this image, so the
  screen may never blank — or lightdm may have its own opinion.
- **The cursor.** With no mouse attached, a pointer parked mid-screen looks
  broken. That is a compositor setting, not a chromium flag.
- **Which output labwc picks** when both ports are populated.
- **That the page still reads.** It sets `width=device-width`, caps at
  `52rem` and lays tiles out with `auto-fit`, so it should survive a small
  screen unchanged. Should is not measured.

## What order to build them in

1. **Saved networks.** Useful on its own, no new privileges, no way to
   strand the speaker. It also makes the other two worth having, because
   there is somewhere for credentials to go.
2. **The access point and portal.** The real answer to the lock-out loop.
   Build the give-up rules in the same commit as the raise — not after.
3. **The screen.** A diagnostic, and the one that can wait.

## Deliberately not in this

- **No password on the dashboard.** Adding one is a real discussion about
  where the password lives and what happens when it is forgotten. The
  access point makes that discussion slightly more pressing, not less, and
  it is still a separate one.
- **No AP and station at the same time.** `iw` is not installed so the
  radio's concurrency was not measured, and brcmfmac's support for it is
  known to be uneven. Mutually exclusive is the honest design.
- **No purpose-built screen layout.** A calmer face for a shelf — the time,
  a timer, what is playing — is a good idea and a separate one.
