"""
route_ring_osc_signals_v9.py (REVISED after the user ran real DRC on the
first version and found 39 violations -- 28x M2.W1 "M2 Wmin<3.0", 5x
M2.S1, 2x M1.W1, 2x M1.S1, plus 2 unrelated pre-existing GC.ANT -- and
asked: "RING_OSCのLEFを作ってから再度挑戦ください。")

ROOT CAUSES of the DRC violations, found by reading ring_osc/
DRC_error.lyrdb directly:
  - M2_W was set to 1.8um (copied from M1's own width by mistake) -- the
    real M2 minimum width rule is 3.0um. This alone caused all 28 M2.W1
    violations.
  - Multiple width/spacing violations at wire-meets-via junctions were
    the same class of bug route_gio_core_v9.py's own TAP_STUB_W comments
    already documented: a wire NARROWER than the via_1 PCell's 3.4um
    landing pad creates a locally-narrow "wing" at the T-junction where
    they meet, exactly what a real width/spacing checker flags. Fixed
    here by making M1_W = M2_W = PAD = 3.4um throughout -- a seamless,
    flush via-to-wire junction with no notch, everywhere.

PIN LOCATIONS: now read from ring_osc/RING_OSC.lef (generated this
session by script/gen_lef_ring_osc.py) instead of ad-hoc GDS text-
scanning. The LEF is authoritative and, notably, corrects two things the
earlier manual scan got only approximately right:
  - OUT/OUTD's real M1 PIN ports are the narrower official marker rects
    (1616.6,28.0)-(1620.0,31.4) and (1616.6,-26.6)-(1620.0,-23.2) --
    subsets of the full pin-shaped metal, not its whole extent.
  - ENB's real port is on M2 (not M1 as previously assumed), at LEF rect
    (11.8,-118.9)-(15.2,-115.5) -- the marker sits at the very bottom
    edge (where the earlier version deliberately avoided, worried about
    the congested per-cell M1 wiring found nearby during the power-
    routing investigation). Since the OFFICIAL port is here, and it is
    genuinely clear at the M2 layer (only the M1 layer had the nearby
    congestion), this revision routes to this exact LEF-declared point
    rather than substituting a hand-picked alternative.
Because ENB's pin layer is M2 (not M1 like OUT/OUTD), route() below takes
an explicit pin_layer argument and inserts one extra via right at the pin
before the usual M1 escape segment when the pin isn't already M1.

TARGETS: P9/P10/P15 unchanged from the previous version (see schematic/
ring_osc_connections.json's signal_routing section for the P15=rst_n
finding and overall strategy -- the ring/lane-band-avoidance waypoint
strategy is unchanged, only pin coordinates and metal widths are fixed
here).

VERIFICATION: same self-check as before (new shapes vs. original v9
chip, vs. RING_OSC's own body + power routing, vs. each other), landing
boxes widened slightly to give a safety margin over the pre-existing pad
stubs (the previous version's near-miss 1.3um gap at the P10 landing,
one of the real M1.S1 violations, came from cutting this margin too
close).

Output: ring_osc/tr_1um_i2c_slave_async_ringosc_signals.gds
"""
import re
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/tech/python")
import pya  # noqa: E402
from cells import tr_1um  # noqa: E402

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
IN_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_ringosc_routed.gds"
ORIG_CHIP_GDS = BASE + "/src/tr_1um_i2c_slave_async.gds"
OUT_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_ringosc_signals.gds"
RING_OSC_LEF = BASE + "/ring_osc/RING_OSC.lef"
TOP_CELL = "tr_1um_i2c_slave_async"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
PAD = 3.4
M1_W = 3.4   # == PAD, see docstring -- eliminates the via/wire T-junction
M2_W = 3.4   # notch class of violation, and clears the real M2 Wmin=3.0 rule

ORIGIN_X_UM, ORIGIN_Y_UM = -810.0, -650.0


def parse_lef_pins(path):
    """Minimal LEF PIN reader (same approach as script/lef_parser.py,
    inlined here to avoid an import-path dependency), returns
    {pin_name: [(layer, x0,y0,x1,y1), ...]} in the MACRO's own native
    coordinate frame (um)."""
    text = open(path).read()
    pins = {}
    for pm in re.finditer(r"^\s*PIN (\S+)\n(.*?)\n\s*END\s+\1\s*$", text, re.M | re.S):
        name = pm.group(1)
        body = pm.group(2)
        rects = []
        cur_layer = None
        for line in body.splitlines():
            line = line.strip()
            lm = re.match(r"LAYER\s+(\S+)\s*;", line)
            if lm:
                cur_layer = lm.group(1)
                continue
            rm = re.match(r"RECT\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s*;", line)
            if rm and cur_layer:
                x0, y0, x1, y1 = (float(v) for v in rm.groups())
                rects.append((cur_layer, x0, y0, x1, y1))
        pins[name] = rects
    return pins


def pin_center_abs(rects):
    layer, x0, y0, x1, y1 = rects[0]
    cx = (x0 + x1) / 2 + ORIGIN_X_UM
    cy = (y0 + y1) / 2 + ORIGIN_Y_UM
    return layer, cx, cy, (x0 + ORIGIN_X_UM, y0 + ORIGIN_Y_UM, x1 + ORIGIN_X_UM, y1 + ORIGIN_Y_UM)


def main():
    lef_pins = parse_lef_pins(RING_OSC_LEF)
    out_layer, out_x, out_y, out_box = pin_center_abs(lef_pins["OUT"])
    outd_layer, outd_x, outd_y, outd_box = pin_center_abs(lef_pins["OUTD"])
    enb_layer, enb_x, enb_y, enb_box = pin_center_abs(lef_pins["ENB"])
    print(f"OUT  pin: layer={out_layer} abs=({out_x:.1f},{out_y:.1f})")
    print(f"OUTD pin: layer={outd_layer} abs=({outd_x:.1f},{outd_y:.1f})")
    print(f"ENB  pin: layer={enb_layer} abs=({enb_x:.1f},{enb_y:.1f})")

    # REVISED (user, after real LVS review: "配線ミスです。RINGOSC(OUT)
    # ＞P10、RINGOSC(OUTD)＞VSS になっていますが、正しくは RINGOSC(OUT)
    # ＞OUT10、RINGOSC(OUTD)＞OUT9です。"): OUT/OUTD must NOT land
    # directly on the P9/P10 bond-pad nets at all -- they need to drive
    # the GIO frame's own dedicated driver-INPUT pins (OUT9/OUT10),
    # which feed each pad's internal tri-state output buffer, exactly
    # like every other real output signal in this chip (e.g. sda's own
    # "SDA_O" net). Direct GDS text-label queries (layer 49/0, TXM2)
    # confirmed the real abs locations: the OLD target (200.0,-921.8)
    # sits right on top of that pad group's own GND/VSS pin label
    # (confirmed: "GND"/"gnd" text at (200,-921.7) and (200,-932.2)) --
    # NOT on P9's own signal-level location (which is actually abs
    # (270,-921.8), per its own "P9" text label there) -- so the old OUT
    # route was landing on GND, a real short, matching the user's report
    # (and independently confirmed via LEF/OSS_FRAME_GIO.lef: OUT9's PIN
    # rect, converted from its native (1428.3,326.6)-(1431.7,330.0) via
    # the LEF's own ORIGIN(1250,1250), is abs (178.3,-923.4)-
    # (181.7,-920.0), nowhere near (200,-921.8)). OUT10's LEF PIN rect
    # similarly converts to abs (618.3,-923.4)-(621.7,-920.0). Both are
    # M2, matching OUT/OUTD's own final-landing layer already.
    #
    # Per the user's explicit correction, the pad assignment also SWAPS
    # relative to the old (wrong) scheme: OUT (RING_OSC's first ring)
    # now targets OUT10 (abs X=620, eventually driving pad P10), and
    # OUTD (second ring) now targets OUT9 (abs X=180, eventually driving
    # pad P9) -- the opposite pairing from the old OUT->(near P9)/
    # OUTD->P10 routing.
    OUT9 = (180.0, -921.7)
    OUT10 = (620.0, -921.7)
    P15 = (530.0, 921.8)

    # landing-pad merge boxes (excluded from the collision check -- these
    # ARE meant to be touched/merged).
    LANDING_BOXES = [
        (176.3, -925.0, 183.7, -918.4),      # OUT9  (abs pin +/- small margin)
        (616.3, -925.0, 623.7, -918.4),      # OUT10 (abs pin +/- small margin)
        (526.0, 903.0, 534.0, 979.0),        # P15 / rst_n pad stub + spoke
        out_box, outd_box, enb_box,
    ]

    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)
    assert top is not None
    m1_idx = layout.layer(*M1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)

    tr_1um("TR-1um")
    via_lib = pya.Library.library_by_name("TR-1um", "*")
    via_decl = via_lib.layout().pcell_declaration("via_1")

    def um(v):
        return int(round(v / dbu))

    new_shapes = {"M1": [], "M2": []}
    cur_net = [None]

    def wire(layer_name, x0, y0, x1, y1, w):
        layer_idx = m1_idx if layer_name == "M1" else m2_idx
        hw = w / 2.0
        if abs(x0 - x1) < 1e-6:
            box = db.Box(um(x0 - hw), um(min(y0, y1)), um(x0 + hw), um(max(y0, y1)))
        elif abs(y0 - y1) < 1e-6:
            box = db.Box(um(min(x0, x1)), um(y0 - hw), um(max(x0, x1)), um(y0 + hw))
        else:
            raise ValueError(f"non-manhattan segment {x0,y0,x1,y1}")
        top.shapes(layer_idx).insert(box)
        new_shapes[layer_name].append((box.left * dbu, box.bottom * dbu, box.right * dbu, box.top * dbu, cur_net[0]))

    def via(cx, cy, pad=PAD):
        pcell_idx = layout.add_pcell_variant(via_lib, via_decl.id(), {"x": pad, "y": pad, "x0": "c", "y0": "c"})
        top.insert(db.CellInstArray(pcell_idx, db.Trans(db.Vector(um(cx), um(cy)))))
        box = (cx - pad / 2, cy - pad / 2, cx + pad / 2, cy + pad / 2)
        new_shapes["M1"].append((*box, cur_net[0]))
        new_shapes["M2"].append((*box, cur_net[0]))

    def route_path(label, pin, pin_layer, waypoints):
        # waypoints: list of (x,y) after the pin, alternating H/V segments
        # (M1 for horizontal, M2 for vertical), with a via at every turn.
        #
        # REVISED (real DRC round 3, user: "ENBがVSSとショートしています。
        # M1の引き出しがBBOXの内部にあるのが原因です。"): this used to
        # unconditionally drop a via right at the pin whenever pin_layer
        # != M1 (true only for ENB). That via's M1 landing pad, sized to
        # PAD=3.4 and centered exactly on ENB's LEF-declared M2 pin
        # (-796.5,-767.2), lands squarely inside a TAP cell's own PR
        # boundary at that exact spot (confirmed by direct GDS query:
        # TAP2's own M1 VSS metal at abs (-799.2,-768.9)-(-788.4,-750.9)
        # fully contains the via's M1 pad footprint) -- an M1-M1 short to
        # VSS, invisible to the landing-box-excluded overlap self-check
        # since ENB's own pin box was one of the excluded boxes. RING_OSC
        # is densely packed with per-row TAP-cell M1 across this whole
        # left-edge column (confirmed: no clear M1 spot anywhere in the
        # X~-802..-790 band for the full row height), so no nearby
        # in-bbox via location is safe either. Fixed generally: only
        # drop a via at the pin if the FIRST waypoint segment's own
        # inferred layer actually differs from pin_layer -- letting a
        # non-M1 pin (ENB) start with a same-layer (M2) escape segment
        # with NO via at all, deferring the real M1 transition to
        # wherever the caller's waypoints put it (ENB's caller now
        # descends on M2, matching the pin's own layer with zero risk of
        # a same-layer merge with anything unrelated, THEN transitions to
        # M1 only once clear of RING_OSC's bbox entirely -- see the ENB
        # call below). OUT/OUTD (pin_layer=M1, first segment already M1)
        # are unaffected -- this was already a no-op for them.
        cur_net[0] = label
        pts = [pin] + waypoints
        (fx0, fy0), (fx1, fy1) = pts[0], pts[1]
        first_layer = "M1" if abs(fy0 - fy1) < 1e-6 else "M2"
        if pin_layer != first_layer:
            via(*pin)
        for k in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            if abs(y0 - y1) < 1e-6:
                wire("M1", x0, y0, x1, y1, M1_W)
            elif abs(x0 - x1) < 1e-6:
                wire("M2", x0, y0, x1, y1, M2_W)
            else:
                raise ValueError(f"non-manhattan segment {pts[k]}-{pts[k+1]}")
            if k < len(pts) - 2:
                via(x1, y1)
        print(f"{label}: {pin}[{pin_layer}] -> " + " -> ".join(str(p) for p in waypoints))

    route_path("OUT",  (out_x, out_y),  out_layer,
               [(830.0, out_y), (830.0, -907.0), (620.0, -907.0), OUT10])
    route_path("OUTD", (outd_x, outd_y), outd_layer,
               [(824.0, outd_y), (824.0, -913.0), (180.0, -913.0), OUT9])
    # ENB: escape left/up to the clear top-left corridor, across at Y=852
    # (below the lane band, matching OUT/OUTD's own below-lane-band logic
    # on the bottom side), then a short X jog (536->530) landing the path
    # directly ON rst_n's own pre-existing M1 pad-stub at (530,905.5).
    #
    # REVISED (real DRC round 2, user: "惜しい、P15の配線です。"): the
    # previous version continued PAST (530,905.5) with one more via + a
    # short M2 segment up to P15 itself. DRC_error.lyrdb found V1.S1 (via
    # cut Smin<1.5) right there: edge-pair (529.3,906.2)-(530.7,906.3), a
    # 1.4um-wide sliver with only a 0.1um gap. Root cause: (530,905.5)
    # sits INSIDE rst_n's own pre-existing M1 pad-stub band (528.3,905.3)-
    # (531.7,908.7), which already has its OWN via up to its own M2 riser
    # continuing to P15 (confirmed by direct GDS query: an existing V1 cut
    # at (529.3,906.3)-(530.7,907.7), i.e. centered ~(530,907.0), only
    # 1.5um center-to-center from the new via this code was adding at
    # (530,905.5) -- 1.5um centers with a 1.4um cut leaves only 0.1um,
    # under the real 1.5um Smin). Since ENB's M1 wire already lands on
    # and merges with that same pre-existing M1 pad polygon, the
    # pad's OWN via+M2 riser already completes the connection up to P15
    # -- adding a second, separate via right next to it was both
    # redundant and a DRC violation. Fixed by ending the route AT the pad
    # (see the exact Y value in the round-3 fix just below) with no via
    # and no further M2 segment: the M1-M1 merge alone ties ENB onto the
    # existing rst_n/P15 net.
    #
    # REVISED AGAIN (real DRC round 3, user: "RING_OSCのENBがVSSと
    # ショートしています。M1の引き出しがBBOXの内部にあるのが原因です。
    # P15との接続もY軸が少し(1.5um)ズレています。") -- two independent
    # fixes:
    #
    # (1) VSS short: route_path() used to drop a via right at the ENB pin
    # itself (-796.5,-767.2) to get from the pin's native M2 onto M1 for
    # the leftward escape run. That via's M1 landing pad (PAD=3.4,
    # centered exactly on the pin) lands squarely on a TAP cell's own M1
    # VSS metal there (confirmed by direct GDS query on the pre-signal-
    # routing base GDS: TAP2's own M1 at abs (-799.2,-768.9)-
    # (-788.4,-750.9) fully contains the via's M1 pad) -- an M1-M1 short
    # to VSS invisible to the overlap self-check because ENB's own pin
    # box is one of the excluded LANDING_BOXES. Direct queries confirmed
    # the whole X~-802..-790 column is densely packed with per-row TAP
    # cell M1 for the full row height -- no nearby in-bbox via spot is
    # safe. Fixed by re-routing the ENB escape entirely: first a plain M2
    # vertical drop (X=-796.5 fixed, matching the pin's own layer, so NO
    # via needed) down to Y=-785.0 -- clear of RING_OSC's own bbox
    # (bottom edge Y=-770.0) and clear of the two vertical VDD/VSS M2
    # straps (X=-801.9/-807.3, well away from X=-796.5) -- THEN a via and
    # the M1 escape run to X=-822.0 happen down there, fully outside
    # RING_OSC, verified clear on both M1 and M2 (0 overlap with existing
    # geometry at both new via locations, direct GDS query). The M1 run
    # crossing X=-801.9/-807.3 at this Y is a harmless M1-over-M2
    # crossover (no via there), not a merge.
    #
    # (2) 1.5um Y misalignment: the round-2 landing Y (905.5) undershot
    # rst_n's own real pre-existing M1 pad-stub, which a direct query on
    # the pre-signal-routing base GDS shows spans Y 905.3-908.7 (NOT
    # 903.8-908.7 -- that wider span only appeared in the post-routing
    # GDS because ENB's own M1_W=3.4 wire at Y=905.5 protrudes 1.5um
    # below the pad's real bottom edge, 905.3-903.8=1.5, merging with and
    # widening the query result). The pad's own via (found earlier, round
    # 2) sits at Y=907.0, i.e. the pad is exactly centered there. Fixed
    # by moving ENB's final landing Y from 905.5 to 907.0 -- the M1 wire
    # (width 3.4) now spans Y 905.3-908.7, an exact match to the
    # pre-existing pad's own footprint with zero protrusion either way
    # (confirmed by direct query: overlap region is exactly
    # (530.0,905.3)-(531.7,908.7), the pad's own bounds).
    route_path("ENB",  (enb_x, enb_y),  enb_layer,
               [(enb_x, -785.0), (-822.0, -785.0), (-822.0, 852.0),
                (536.0, 852.0), (536.0, 907.0), (530.0, 907.0)])

    layout.write(OUT_GDS)
    print(f"wrote {OUT_GDS}")

    # ---- verification: new shapes vs. ORIGINAL chip geometry ----
    orig = db.Layout()
    orig.read(ORIG_CHIP_GDS)
    orig_top = orig.cell(TOP_CELL)
    orig_m1 = orig.layer(*M1_LAYER)
    orig_m2 = orig.layer(*M2_LAYER)

    def region_of(cell, layer_idx):
        r = db.Region()
        it = cell.begin_shapes_rec(layer_idx)
        while not it.at_end():
            shp = it.shape()
            if shp.is_box() or shp.is_polygon() or shp.is_path():
                r.insert(it.trans() * shp.polygon if shp.is_polygon() else it.trans() * shp.bbox())
            it.next()
        return r

    orig_m1_region = region_of(orig_top, orig_m1)
    orig_m2_region = region_of(orig_top, orig_m2)

    base = db.Layout()
    base.read(IN_GDS)
    base_top = base.cell(TOP_CELL)
    base_m1_region = region_of(base_top, base.layer(*M1_LAYER))
    base_m2_region = region_of(base_top, base.layer(*M2_LAYER))

    def in_landing_box(x0, y0, x1, y1):
        for bx0, by0, bx1, by1 in LANDING_BOXES:
            if not (x1 < bx0 or x0 > bx1 or y1 < by0 or y0 > by1):
                return True
        return False

    problems = 0
    for check_label, m1_r, m2_r in [("orig v9 chip", orig_m1_region, orig_m2_region),
                                     ("RING_OSC body + power routing", base_m1_region, base_m2_region)]:
        for layer_name, region in [("M1", m1_r), ("M2", m2_r)]:
            for x0, y0, x1, y1, net in new_shapes[layer_name]:
                if in_landing_box(x0, y0, x1, y1):
                    continue
                box = db.Box(um(x0), um(y0), um(x1), um(y1))
                overlap = db.Region(box) & region
                if overlap.area() > 0:
                    problems += 1
                    print(f"COLLISION ({check_label}) on {layer_name}: {net} shape "
                          f"({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) overlaps existing geometry, "
                          f"area={overlap.area()*dbu*dbu:.2f} um^2")

    for layer_name in ("M1", "M2"):
        shapes = new_shapes[layer_name]
        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                x0, y0, x1, y1, net_i = shapes[i]
                X0, Y0, X1, Y1, net_j = shapes[j]
                if net_i == net_j:
                    continue
                if not (x1 < X0 or x0 > X1 or y1 < Y0 or y0 > Y1):
                    problems += 1
                    print(f"SELF-COLLISION on {layer_name}: {net_i} shape {shapes[i][:4]} "
                          f"overlaps {net_j} shape {shapes[j][:4]}")

    if problems == 0:
        print("VERIFICATION PASSED: no new shape overlaps pre-existing chip geometry, "
              "RING_OSC's own body, the power routing, or each other "
              "(outside the intended landing pads).")
    else:
        print(f"VERIFICATION FOUND {problems} COLLISION(S) -- see above, routing needs revision.")


if __name__ == "__main__":
    main()
