# A case for the speaker

A printed puck that stands on top of the speaker: the Raspberry Pi lying in
the bottom, the reSpeaker XVF3800 array as a ceiling above it with its
microphones and lights facing up. **140 mm across, 43 mm tall.**

    ./case/build.sh              base.3mf and lid.3mf
    ./case/build.sh --preview    ...and PNGs to look at first

Two parts, no supports, no AMS, and no special cables. Open
`case/speaker-case.scad` to change anything; every dimension is named at the
top of the file.

## Where the numbers came from

The array's dimensions are from Seeed's own 2D mechanical drawing, not from
a ruler:

| | |
|---|---|
| Board | Ø100.0 mm, 1.2 mm thick |
| Microphones | on a 66 × 66 mm square, whose centre is **1 mm below** the centre of the board |
| LEDs | 12 × WS2812 at r = 32.0 mm, one every 30° starting at 15° |

The LED ring is the one number the drawing does not write down. It was
measured off a 600 dpi render of that drawing, scaling from the stated
Ø100 outline: ten of the twelve footprints agreed on 32.0 mm to within
0.3 mm.

The mic square being 1 mm off centre is the sort of thing that is invisible
until four holes don't line up.

## Why it is 140 mm and not 122

The first version was 122 mm, because an Echo Dot is 100 and that felt like
the right family to be in. It was, in fact, a case that demanded
right-angle plugs, and nothing said so.

A plug's clearance is not the case's radius. It is the distance from the
socket face to the wall **along the plug's own axis**, and the Pi's sockets
do not sit on the centre line — the USB-C power socket is 34.5 mm off it.

| along the plug's axis | at Ø122 | at Ø140 | a plug needs |
|---|---|---|---|
| USB-C power | 19.4 | **30.1** | ~26 |
| USB-A, the array's lead | 14.1 | **23.1** | ~20 |
| USB-A, outer pair | 11.1 | **20.5** | ~20 |
| micro-HDMI | 26.7 | 36.3 | ~22 |
| Ethernet | 11.3 | 20.7 | ~22 |

Nine more millimetres of radius is the difference between a case that needs
a bag of adapters and one that takes the leads already on the desk. The
array's own lead goes into one of the **blue USB 3.0 ports** — those are the
pair with 23.1 mm; the outer pair has 20.5 and is tighter.

Ethernet is the one thing still short, by about 1.3 mm, and there is no
opening on that side. It stays unreachable without taking the lid off. Say
the word and it is a one-line change.

## Where the wires go

Three leads. Two leave through the rear opening and one never leaves at all.

    rear opening, 230 to 302 deg, floor to rim
        in    Pi power, USB-C, straight from the adapter
        out   the array's 3.5 mm lead, to the speaker

    inside, never leaves
        the array's USB-C down to a Pi USB 3.0 port

Put the array in with **its sockets over the rear opening**, the same side
the Pi's power lead comes in.

The opening is centred on 266°, not on the case's own 270° axis, because
that is where the plugs actually arrive: the power plug crosses the wall
between 236° and 243°, micro-HDMI between 249° and 255°, and the array's
sockets sit between 250° and 295°. All three are inside 230–302.

The four columns are at **45, 135, 200 and 315°** — not evenly spaced. The
one that used to be at 225° lay directly across the path the power plug
takes to the wall. The others were already clear.

## The board can go in four ways round

The LED ring is at 15 + 30k degrees, and 90 is three times 30, so turning
the array by a quarter turn leaves all twelve windows exactly where they
were. The microphones are not so tidy — that 1 mm offset means each one
drifts 1.41 mm from its port — but the ports are 4.5 mm across at their
narrowest, so a microphone still has 0.34 mm of clearance.

Sockets over the opening is the orientation to prefer. Everything lines up
exactly.

**Which way up matters more than which way round.** The face carrying the
XMOS chip, the 2 × 12 header field and the white JST connector is the
*bottom*. The face with the twelve LEDs and the four microphone apertures
goes up, towards the lid. Upside down, the lid stands proud on the JST and
the lights and microphones are aimed into the Pi.

## What you need besides the plastic

- 4 × M3 × 12 self-tapping screws (the countersinks take a head up to 6 mm)
- 4 × M2.5 × 6 self-tapping screws for the Pi
- 4 × Ø10 mm stick-on silicone feet, about 2 mm thick
- A USB-C to USB-A lead for the array, 20 cm or so. Straight plugs are fine.
- A 3.5 mm lead from the array to the speaker

## Printing

P1S, PLA, 0.4 mm nozzle, 0.2 mm layers. Both parts are exported already
standing the way they should print, so drop them on the plate as they come.

- **base** — 3 walls, 15% gyroid, no supports. Prints floor-down.
- **lid** — 3 walls, 15%, no supports. Prints **face down**: the top surface
  is laid straight onto the plate, which is the best finish the printer can
  give it, and every window widens as it rises at 22° from vertical.

Nothing in either part bridges more than 4 mm. The rear opening runs right
up to the rim rather than stopping short of it — a window with wall above
it would need the printer to bridge seventy millimetres unsupported, and a
sagging lintel is a worse thing to own than a taller doorway.

## Assembly

1. Four silicone feet into the recesses in the underside of the base.
2. Pi into the base on its four standoffs, ports facing the rear opening,
   M2.5 screws.
3. Plug the array's lead into a blue USB 3.0 port and into the array. Plug
   the 3.5 mm lead in and feed it out of the rear opening.
4. Drop the array into the base, **microphones and LEDs facing up**,
   sockets towards the rear opening.
5. Lid on, four M3 screws down into the columns.

## The feet are not decoration

The case stands about 2 mm off the speaker, and that gap is doing two jobs.

It is where the cooling air gets in — the floor is a grid of slots, and if
the case sits flat they are all blocked. A Pi 4 running the wake word all
day is roughly a five watt heater in a closed box, and PLA starts to give
up around 60 °C. If yours runs hot, a stick-on heatsink on the SoC and
taller feet are both easier than reprinting.

The other job is mechanical. This puck stands on a loudspeaker, which is a
box built to vibrate. The XVF3800's echo canceller is very good at sound
that reaches the microphones through the air and has nothing whatever to
say about sound that reaches them through the furniture. Rubber feet break
that path. If the wake word gets noticeably worse when music is loud, that
is the first thing to suspect, and softer feet are the first thing to try.

## Two things this deliberately does not do

**It does not use the array's mounting holes.** The drawing dimensions them
in a way I could not read without guessing, and a guess there costs a
print. The board rests on four shelves and is located by four columns,
which needs only the outside diameter — a number the drawing states
outright.

**Nothing presses down on the board.** The first draft had a ring on the
lid to clamp the rim. Then the microphone positions came out of the drawing
at a radius of 46 to 47 mm, which is exactly where that ring was, sitting
squarely on all four microphones. If the board rattles, a pad of foam on
the underside of the lid is a better answer than a ring drawn over parts I
cannot see.
