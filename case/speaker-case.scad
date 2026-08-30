// A case for the speaker, in two printed parts.
//
//     ./case/build.sh            base.3mf and lid.3mf, ready for Bambu Studio
//     ./case/build.sh --preview  PNGs of each part and of the assembly
//
// What it holds
// -------------
// A Raspberry Pi 4 lying flat in the bottom, and the reSpeaker XVF3800
// 4-mic array as a ceiling above it, microphones and LEDs facing up. The
// whole thing is a puck that stands on the speaker: 122 mm across and
// 43 mm tall, which is close enough to an Echo Dot that nobody asks what
// it is.
//
// Every number below that describes the array was taken from Seeed's own
// 2D mechanical drawing rather than from a ruler, except where a comment
// says otherwise. The board is 100 mm across; the four microphones sit on
// a 66 mm square whose centre is 1 mm below the centre of the board, which
// is the sort of detail that is invisible until four holes don't line up.
//
// What it deliberately does not do
// --------------------------------
// It does not screw to the array's mounting holes. The drawing dimensions
// them in a way I could not read without guessing, and a guess here costs
// a print. Instead the board rests on four shelves and is clamped at its
// rim by the lid, which needs only the outside diameter — a number the
// drawing states outright.
//
// It does not sit flat on the speaker either. It stands on four rubber
// feet, and that gap is not decoration: it is where the cooling air gets
// in, and it is what stops the cabinet's own vibration being conducted
// straight into the microphones. The echo canceller on the XVF3800 is
// good at sound that arrives through the air and has nothing at all to
// say about sound that arrives through the furniture.

part = "assembly";          // "base", "lid", "assembly"
$fn  = 96;

/* ---- the printer and the plastic ------------------------------------ */

FIT   = 0.4;   // clearance between parts, PLA on a P1S
WALL  = 2.4;   // six perimeters at 0.4 mm
FLOOR = 2.0;

/* ---- reSpeaker XVF3800 4-Mic Array v1.1 ----------------------------- */
// Seeed 2D drawing: respeaker_xvf3800_2d_mechanical_drawing.pdf

BOARD_D  = 100.0;   // stated on the drawing as the board outline
BOARD_T  = 1.2;     // stated
LED_R    = 32.0;    // measured off the drawing at 600 dpi, 10 LEDs agreeing
LED_N    = 12;
LED_A0   = 15;      // first LED at 15 degrees, then every 30
MIC_DX   = 33.0;    // half of the stated 66.00 mm mic square
MIC_TOP  = 32.0;    // stated: 66.00 overall, 34.00 below the board centre
MIC_BOT  = -34.0;

// Height of whatever stands on each face of the array. The drawing gives
// 5.66 on one side and about 6.2 overall on the other. The tall things on
// the microphone face are all at the very edge — the USB-C socket and the
// headphone jack — so the lid can come down close over the middle, which
// is what keeps the microphone ports short.
UNDER_ARRAY = 6.5;
LID_GAP     = 4.0;  // lid underside above the array's top face

/* ---- Raspberry Pi 4B ------------------------------------------------ */

PI        = [85, 56];
PI_T      = 1.4;
PI_TALL   = 17.5;   // USB-A shells, the tallest thing on the board
PI_HOLES  = [58, 49];
// The mounting holes are not centred on the board: they sit 3.5 mm in
// from three edges, which puts their centre 10 mm off the board's.
PI_HOLE_OFF = -10;
PI_STANDOFF = 5.0;
PI_PILOT    = 2.4;  // M2.5 self-tapping

/* ---- the case ------------------------------------------------------- */

// 140, not 122. At 122 the case was a right-angle-plug case and I had not
// said so: a Pi's USB-C power socket sits 34.5 mm off the centre line, so
// its plug had 19.4 mm before it met the wall and needed 26, and the USB-A
// carrying the array's lead had 14.1 and needed 20. Nine more millimetres
// of radius buys 30.1 and 23.1, and every plug goes in straight.
CASE_D  = 140;
LID_T   = 2.5;
FOOT_D  = 10;       // stick-on silicone bumpers
FOOT_H  = 1.2;
// The opening is centred on where the plugs actually come out, which is
// not where the case's own axis is. The power plug meets the wall at 239
// degrees, micro-HDMI at 252, and the array's own sockets sit between 250
// and 295. So: 230 to 302.
REAR      = 266;
REAR_WIDE = 72;
SCREW_R = 65.0;     // four M3 down through the lid into the columns

// Where the columns stand. Not evenly spaced: the one that used to be at
// 225 lay across the path the power plug takes to the wall, so it moved to
// 200. The others were already clear.
COLS = [45, 135, 200, 315];

// Heights, stacked from the bench up.
Z_PI      = FLOOR + PI_STANDOFF;
Z_PI_TOP  = Z_PI + PI_T + PI_TALL;
Z_BOARD   = Z_PI_TOP + 2.5 + UNDER_ARRAY;
Z_TOP     = Z_BOARD + BOARD_T;          // top face of the array
Z_SEAM    = Z_TOP;                      // base ends, lid begins
Z_LID     = Z_TOP + LID_GAP;            // lid underside
H         = Z_LID + LID_T;              // overall

R_OUT = CASE_D / 2;
R_IN  = R_OUT - WALL;

/* ---- helpers -------------------------------------------------------- */

// A pie slice, for windows and for the gaps in rings.
module sector(r, h, from, to) {
    step = 15;
    n = max(1, ceil((to - from) / step));
    for (i = [0 : n - 1])
        rotate([0, 0, from + i * (to - from) / n])
            linear_extrude(h)
                polygon([[0, 0],
                         [r, 0],
                         [r * cos((to - from) / n), r * sin((to - from) / n)]]);
}

module led_positions()
    for (i = [0 : LED_N - 1])
        rotate([0, 0, LED_A0 + i * 360 / LED_N]) translate([LED_R, 0, 0]) children();

module mic_positions()
    for (p = [[MIC_DX, MIC_TOP], [-MIC_DX, MIC_TOP],
              [MIC_DX, MIC_BOT], [-MIC_DX, MIC_BOT]])
        translate([p[0], p[1], 0]) children();

module pi_hole_positions()
    for (x = [-1, 1], y = [-1, 1])
        translate([PI_HOLE_OFF + x * PI_HOLES[0] / 2, y * PI_HOLES[1] / 2, 0])
            children();

// A ring of vertical slots through the wall. One slot per angle, cut from
// the outside in — a bar through the middle would quietly cut the far side
// of the case as well, including the parts meant to be left whole.
module wall_slots(z0, z1, count, width, skip_from, skip_to) {
    for (i = [0 : count - 1]) {
        a = i * 360 / count;
        if (!(a >= skip_from && a <= skip_to))
            rotate([0, 0, a])
                translate([R_IN - 1, -width / 2, z0])
                    cube([WALL + 2, width, z1 - z0]);
    }
}

// Cool air comes in under the feet and up through here. The pattern is
// held clear of the Pi's standoffs: a standoff printed over the edge of a
// slot has nothing to stand on.
module floor_vents() {
    difference() {
        for (i = [0 : 11]) rotate([0, 0, i * 30])
            for (r = [14 : 9 : R_IN - 10])
                translate([r, 0, FLOOR / 2])
                    cube([5, 3, FLOOR + 2], center = true);
        pi_hole_positions() translate([0, 0, -1]) cylinder(d = 13, h = FLOOR + 3);
    }
}

/* ---- the base ------------------------------------------------------- */

module base() {
    difference() {
        union() {
            // Shell.
            difference() {
                cylinder(r = R_OUT, h = Z_SEAM);
                translate([0, 0, FLOOR]) cylinder(r = R_IN, h = H);
            }
            // Four columns against the wall. The inner step carries the
            // array; the outer part carries the lid and takes its screw.
            // Both start well outboard of the Pi, which occupies the middle
            // of the case up to Z_PI_TOP.
            for (a = COLS) rotate([0, 0, a]) {
                translate([BOARD_D / 2 - 6, -3, 0])
                    cube([R_IN - BOARD_D / 2 + 6, 6, Z_BOARD]);
                translate([BOARD_D / 2 + 0.5, -4.5, 0])
                    cube([R_IN - BOARD_D / 2 - 0.5, 9, Z_LID]);
            }
            // Standoffs for the Pi.
            pi_hole_positions()
                cylinder(d = 6, h = Z_PI);
        }

        // The columns stop at the lid.
        translate([0, 0, Z_LID]) cylinder(r = R_OUT + 1, h = H);

        // The array drops into a shallow recess so it cannot slide.
        translate([0, 0, Z_BOARD]) cylinder(r = BOARD_D / 2 + FIT, h = H);

        // Screw pilots, down through the columns.
        for (a = COLS)
            rotate([0, 0, a]) translate([SCREW_R, 0, Z_LID - 14])
                cylinder(d = 2.5, h = 16);

        // Pi mounting pilots.
        pi_hole_positions() translate([0, 0, FLOOR])
            cylinder(d = PI_PILOT, h = Z_PI);

        // The rear opening. It serves the Pi's port edge low down and the
        // array's own sockets at the top, which stand at the very rim of
        // the board and have to get out somehow.
        //
        // It runs right up to the rim of the base rather than stopping
        // short of it. A window with a wall above it would need the printer
        // to bridge fifty millimetres across its top, unsupported, and a
        // sagging lintel is a worse thing to own than a taller doorway.
        translate([0, 0, 5]) rotate([0, 0, REAR - REAR_WIDE / 2])
            sector(R_OUT + 1, Z_SEAM - 5 + 0.01, 0, REAR_WIDE);

        // Side and floor venting. A Pi 4 running the wake word all day is
        // a 5 W heater, and PLA gives up at about 60 C.
        wall_slots(8, 24, 28, 3.5, 225, 305);
        wall_slots(Z_PI_TOP + 1, Z_SEAM - 1.5, 28, 3.5, 225, 305);
        floor_vents();

        // Feet.
        for (a = [45, 135, 225, 315])
            rotate([0, 0, a]) translate([R_OUT - 14, 0, -0.01])
                cylinder(d = FOOT_D, h = FOOT_H);
    }
}

/* ---- the lid -------------------------------------------------------- */

module lid() {
    difference() {
        union() {
            translate([0, 0, Z_LID]) cylinder(r = R_OUT, h = LID_T);
            // Skirt, down to meet the base.
            difference() {
                translate([0, 0, Z_SEAM]) cylinder(r = R_OUT, h = LID_GAP);
                translate([0, 0, Z_SEAM - 1]) cylinder(r = R_IN, h = LID_GAP + 2);
            }
            // Nothing hangs down onto the board. The first draft had a ring
            // here to clamp the rim, until the mic positions came out of the
            // drawing at a radius of 46 to 47 mm — which is where that ring
            // would have been, sitting squarely on all four microphones. The
            // board is located by the four columns and held down by its own
            // weight; if it ever rattles, a pad of foam on the lid is a
            // better answer than a ring drawn over parts I cannot see.
        }

        // Twelve windows, one per WS2812. Wider underneath than on top, so
        // each one gathers a wide cone of light and still prints without
        // support: the hole closes by 1 mm over 2.5 mm of height.
        led_positions() translate([0, 0, Z_LID - 0.01])
            cylinder(d1 = 7, d2 = 5, h = LID_T + 0.02);

        // Four microphone ports, kept wide and short. A narrow tube over a
        // MEMS microphone is a resonator; an open window is not.
        mic_positions() translate([0, 0, Z_LID - 0.01])
            cylinder(d1 = 5.5, d2 = 4.5, h = LID_T + 0.02);

        // Screws, counterbored so nothing stands proud of the top.
        for (a = COLS) rotate([0, 0, a]) {
            translate([SCREW_R, 0, Z_LID - 1]) cylinder(d = 3.4, h = LID_T + 2);
            translate([SCREW_R, 0, Z_LID + LID_T - 1.8])
                cylinder(d = 6.0, h = 2);
        }

        // The rear notch, continuing the base's opening up through the
        // skirt so a right-angle plug can get out.
        translate([0, 0, Z_SEAM - 0.01]) rotate([0, 0, REAR - REAR_WIDE / 2])
            sector(R_OUT + 1, LID_GAP + 0.02, 0, REAR_WIDE);

        // Warm air leaves at the top.
        wall_slots(Z_SEAM + 1, Z_LID - 0.6, 28, 3, 225, 305);
    }
}

/* ---- what to render ------------------------------------------------- */

module array_board() {
    color("#1a1a1a") difference() {
        translate([0, 0, Z_BOARD]) cylinder(d = BOARD_D, h = BOARD_T);
        led_positions() translate([0, 0, Z_BOARD - 1]) cylinder(d = 3, h = 4);
    }
}

module pi_board()
    color("#0a6b3d") translate([0, 0, Z_PI]) cube([PI[0], PI[1], PI_T], center = true);

module everything() {
    base();
    color("#c8c8c8", 0.55) lid();
    array_board();
    pi_board();
}

// Each part is exported standing on z = 0 the way it should be printed.
// The base goes down as it sits. The lid goes on its face: printed the
// right way up, the whole underside of its top disc would be printing over
// thin air. Upside down, the top surface is laid straight onto the plate —
// the best surface the printer can make, on the one face anybody looks at —
// and every window widens as it rises, which is an overhang of 22 degrees
// and needs nothing to hold it up.
if (part == "base") base();
else if (part == "lid") translate([0, 0, H]) rotate([180, 0, 0]) lid();
else if (part == "section") {
    // Half the puck, so the stack of heights can be checked by eye.
    difference() {
        everything();
        translate([-200, 0, -1]) cube([400, 200, 300]);
    }
}
else {
    base();
    color("#c8c8c8", 0.55) lid();
    array_board();
    pi_board();
}
