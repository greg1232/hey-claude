# A case for the speaker

A printed puck that stands on top of the speaker: the Raspberry Pi lying in
the bottom, the reSpeaker XVF3800 array as a ceiling above it with its
microphones and lights facing up. **122 mm across, 43 mm tall** — an Echo
Dot is 100 by 43, so it is in the right family.

    ./case/build.sh              base.3mf and lid.3mf
    ./case/build.sh --preview    ...and PNGs to look at first

Two parts, no supports, no AMS. Open `case/speaker-case.scad` to change
anything; every dimension is named at the top of the file.

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
0.3 mm, and the other two are hidden under the module footprint at the top
of the board.

The mic square being 1 mm off centre is the sort of thing that is invisible
until four holes don't line up. The drawing states 66.00 overall and 34.00
from the board's centre line to the lower pair, which leaves 32.00 above.

## What you need besides the plastic

- 4 × M3 × 12 self-tapping screws (the countersinks in the lid take a pan
  or button head up to 6 mm across)
- 4 × M2.5 × 6 self-tapping screws for the Pi
- 4 × Ø10 mm stick-on silicone feet, about 2 mm thick
- A short USB-C to USB-A lead for the array, **right-angle at the array
  end**. There is 8.6 mm between the board's edge and the wall, which a
  straight plug will not fit into.
- A 3.5 mm lead from the array to the speaker, right-angle likewise

## Printing

P1S, PLA, 0.4 mm nozzle, 0.2 mm layers. Both parts are exported already
standing the way they should print, so drop them on the plate as they come.

- **base** — 3 walls, 15% gyroid, no supports. Prints floor-down.
- **lid** — 3 walls, 15%, no supports. Prints **face down**: the top surface
  is laid straight onto the plate, which is the best finish the printer can
  give it, and every window widens as it rises at 22° from vertical, so
  nothing needs holding up.

Nothing in either part bridges more than 4 mm.

## Assembly

1. Four silicone feet into the recesses in the underside of the base.
2. Pi into the base on its four standoffs, ports facing the rear opening,
   M2.5 screws.
3. Plug the array's USB-C lead in and route it to a Pi USB port. Plug the
   3.5 mm lead in and feed it out of the rear opening.
4. Drop the array into the base, microphones and LEDs facing up, sockets
   towards the rear opening. It sits on four shelves and is located by the
   four columns.
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
that path. If the wake word gets noticeably worse when music is loud,
that is the first thing to suspect, and softer feet are the first thing to
try.

## What to check on the first print

Three numbers were chosen from a drawing rather than from the board in
front of you. None of them will break the print, but all three are worth a
look before you screw it together.

- **`LID_GAP` (4.0 mm)** — how far the lid floats above the array's top
  face. The drawing shows about 5.7 mm of components on one side, but on
  this board the tall things are all at the very edge: the USB-C socket and
  the headphone jack. If the lid fouls something in the middle, raise it.
  Every millimetre here also lengthens the path over the microphones, so
  do not raise it further than you must.
- **The rear opening (50° wide)** — the array's sockets sit right at the
  rim of the board and have to come out through it. If yours land somewhere
  else on the edge, rotate the board, or widen `REAR_WIDE`.
- **`UNDER_ARRAY` (6.5 mm)** — clearance under the board for whatever is
  on its underside.

## Two things this deliberately does not do

**It does not use the array's mounting holes.** The drawing dimensions them
in a way I could not read without guessing, and a guess there costs a
print. The board rests on four shelves and is located by four columns,
which needs only the outside diameter — a number the drawing states
outright.

**Nothing presses down on the board.** The first draft had a ring on the
lid to clamp the rim. Then the microphone positions came out of the drawing
at a radius of 46 to 47 mm, which is exactly where that ring was, sitting
squarely on all four microphones. If the board ever rattles, a pad of foam
on the underside of the lid is a better answer than a ring drawn over parts
I cannot see.
