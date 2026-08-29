#!/usr/bin/env python3
"""
add_hiz_vss_ties_v9.py -- restore the 6 schematic-mandated VDD/VSS ties
that v9's power-routing rewrite dropped, per design_notes.md 83.x/84.x.

Root cause (confirmed this session via direct inspection of
src/tr_1um_i2c_slave_async.extracted after the src/LVS_error.lvsdb
re-run): OSS_FRAME_GIO's HIZ2/HIZ7/HIZ15 (schematic-mandated tie to
VDD) and HIZ9/HIZ10/OUT13 (tie to VSS) are genuinely FLOATING in v9's
actual routed GDS -- confirmed via the .extracted subckt's own instance
lines (e.g. "X$10 P2 VDD OUT2 HIZ2 VSS OSS_ESD_5V_DIO") showing HIZ2 as
a purely-internal net that never crosses the OSS_FRAME_GIO cell
boundary. script/route_gio_core_v9.py's own docstring (lines 327-330)
records that an earlier revision's power-bus rewrite explicitly
dropped these 6 ties, having (incorrectly) concluded HIZ*/OUT* pins
were "unrelated to power". v7's actual routing (script/route_gio_core.py,
VDD_HIZ2/VDD_HIZ7/VDD_HIZ15/VSS_HIZ9/VSS_HIZ10/VSS_OUT13 entries) DID
include these ties, which is why v7's chip-level LVS passed cleanly
while v9's doesn't -- this was NOT related to the TOP PIN work (82/83).

Each tie was routed by hand this session using klayout.db.LayoutToNetlist
to (1) find each pin's own real M1/M2 pin-stub geometry, (2) find the
nearest genuinely-VDD or genuinely-VSS-net metal (net-identity verified
via shapes_of_net, NOT just proximity -- this area is dense with
similarly-shaped neighboring nets, notably an unrelated large OUT2-like
M1 obstruction near HIZ2/HIZ7/HIZ15's natural path), and (3) a small
grid-based BFS pathfinder to find a route whose full length, GROWN by
the DRC clearance (M1 space>=1.4um / M2 space>=2.0um), has ZERO
intersection with any OTHER net's shapes in the area -- verified
programmatically, not just eyeballed.

HIZ2/HIZ7/HIZ15 -> VDD: both endpoints on different layers (HIZ pin
stub is M2 with a via down to M1 already inside the OSS_ESD_5V_DIO
cell; the nearest real VDD metal in this specific area turned out to
be M1-only, not M2), so the tie is drawn entirely on M1: a short
horizontal jog away from the crowded area directly above the pin (an
unrelated M1 net -- almost certainly OUT2's own internal routing --
blocks the direct straight-line path), then a vertical run up (or down,
for HIZ7) into the confirmed VDD M1 shape.

HIZ9/HIZ10/OUT13 -> VSS: these already sit in a deliberate ~2.6-3.0um
DRC clearance notch cut into VSS's own M2 ring (evidently intended for
exactly this kind of tie-in), so each fix is just a small M2 patch
bridging the notch, overlapping both the pin's own stub and the VSS
ring with margin.

Every one of the 6 new shapes below was verified this session (see
design_notes.md 84.x) via db.LayoutToNetlist: zero overlap with any
OTHER net's geometry even after growing by the full DRC clearance, AND
solid (non-edge-only) overlap with both its own pin net and its VDD/VSS
target net.
"""
import klayout.db as db

IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/tr_1um_i2c_slave_async.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/tr_1um_i2c_slave_async_hiz_ties.gds"
TOP_CELL = "tr_1um_i2c_slave_async"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)

# Each entry: (label, layer, (x0,y0,x1,y1)) in um, top-cell absolute coords.
# NOTE: seg1/seg2 in each L-shaped VDD tie deliberately OVERLAP by a full
# 1.8um at the corner (rather than just touching edge-to-edge) -- an
# edge-touching L-bend leaves a "pinched" inside corner whose local
# width, once merged with the neighboring pin geometry, dips below the
# M1 W>=1.8 minimum (found via drc_check_nrow_fm.py: 6 width violations,
# one per corner, on the first version of this script that used
# touching-only corners). The overlapping-square corner used below was
# verified to have zero standalone width violations.
NEW_SHAPES = [
    # ---- HIZ2 -> VDD (M1, L-shaped jog around an unrelated M1 obstruction) ----
    ("HIZ2->VDD seg1 (horiz)", M1_LAYER, (-581.7, 923.1, -559.1, 924.9)),
    ("HIZ2->VDD seg2 (vert)",  M1_LAYER, (-560.9, 923.1, -559.1, 936.0)),
    # ---- HIZ7 -> VDD (mirror of HIZ2 in Y) ----
    ("HIZ7->VDD seg1 (horiz)", M1_LAYER, (-581.7, -924.9, -559.1, -923.1)),
    ("HIZ7->VDD seg2 (vert)",  M1_LAYER, (-560.9, -936.0, -559.1, -923.1)),
    # ---- HIZ15 -> VDD (mirror of HIZ2 in X) ----
    ("HIZ15->VDD seg1 (horiz)", M1_LAYER, (559.1, 923.1, 581.7, 924.9)),
    ("HIZ15->VDD seg2 (vert)",  M1_LAYER, (559.1, 923.1, 560.9, 936.0)),
    # ---- HIZ9 -> VSS (M2 patch bridging the design's own clearance notch) ----
    ("HIZ9->VSS patch", M2_LAYER, (221.0, -923.4, 225.0, -920.0)),
    # ---- HIZ10 -> VSS (mirror of HIZ9 in X) ----
    ("HIZ10->VSS patch", M2_LAYER, (581.0, -923.4, 585.0, -920.0)),
    # ---- OUT13 -> VSS (M2 patch, horizontal notch on the RIGHT edge) ----
    ("OUT13->VSS patch", M2_LAYER, (922.5, 178.3, 927.0, 181.7)),
]


def main():
    ly = db.Layout()
    ly.read(IN_GDS)
    dbu = ly.dbu
    top = ly.cell(TOP_CELL)

    layer_idx = {M1_LAYER: ly.layer(*M1_LAYER), M2_LAYER: ly.layer(*M2_LAYER)}

    for label, layer, (x0, y0, x1, y1) in NEW_SHAPES:
        li = layer_idx[layer]
        box = db.Box(int(round(x0 / dbu)), int(round(y0 / dbu)),
                      int(round(x1 / dbu)), int(round(y1 / dbu)))
        top.shapes(li).insert(box)
        print(f"added {label}: layer {layer} box ({x0},{y0})-({x1},{y1})")

    ly.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")
    print(f"added {len(NEW_SHAPES)} new shapes")


if __name__ == "__main__":
    main()
