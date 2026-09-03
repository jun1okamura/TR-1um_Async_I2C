"""
finalize_chip_v10.py (design_notes.md 108.56, user instruction: "DRC は
クリーンです。コア下のPTECTを外して、RING_OSCとロゴも埋め込んで完成
させてください。DRC/LVSに進みます。")

Builds on layout/step10/v10_top_routed.gds (core+GIO placed at V9's exact
offset, 20 signal nets + VDD/VSS routed via an optimally-reassigned GIO
pad map, 108.55 -- user confirmed real KLayout DRC clean) to produce the
complete V10 chip, mirroring V9's own RING_OSC/logo integration
(design_notes.md 103.5-103.15):

  1. Removes the PTECT keepout box (layer 63/1) entirely -- V9's own
     precedent (103.15) was the user deleting this locally once RING_OSC
     was confirmed to fit; done here directly in the script instead.
  2. Places ring_osc/RING_OSC.gds at origin (-810,-650), r0/no mirror --
     IDENTICAL to script/place_ring_osc.py's placement, verbatim, since
     this placement only depends on the core's BOTTOM edge (chip Y=-140.0,
     unchanged between V9 and V10 -- same CORE_OFFSET, same native bbox
     bottom=0 for both cores).
  3. Extends the core's TAP0/TAP3 (end-column) VDD/VSS M2 straps down to
     RING_OSC's own internal power mesh -- IDENTICAL to
     script/route_ring_osc_power_v9.py, verbatim (same TAP X centerlines,
     same CORE_BOTTOM_Y=-140.0, same STRAP_EXTEND_TARGET_Y=-545.0 -- none
     of these depend on core height).
  4. Routes RING_OSC's 3 signal pins:
       - OUT -> OUT10 (620,-921.7) and OUTD -> OUT9 (180,-921.7): these
         are the GIO frame's own dedicated driver-input pins (frame-fixed,
         core-independent) -- IDENTICAL waypoints to
         script/route_ring_osc_signals_v9.py, verbatim.
       - ENB -> rst_n: V9 tied ENB directly onto the rst_n/P15 net's own
         M1 pad-stub near the TOP edge (rst_n's V9 GIO pad). V10's
         optimal pad reassignment (108.55) moved rst_n to a DIFFERENT
         physical GIO pad, on the RIGHT edge (921.7,270.0) instead of TOP
         -- so the merge target moved too. Design INTENT is unchanged
         (ENB tracks the chip reset signal, wherever it is physically
         bonded out) -- this script re-derives a fresh path from RING_OSC's
         ENB pin (still at the same abs location, -796.5,-767.2, since
         RING_OSC's own placement is unchanged) around the outside of the
         die (through the same clear notch technique as OUT/OUTD/V9's own
         ENB: die edge at 816.3, DIS_R ring at 838.3-841.7, staying at
         X=822/Y=-855 to clear both) up the right-side corridor to merge
         onto rst_n's own final M1 approach segment near (870-913,270).
         Every new segment was checked via direct klayout.db overlap
         query against v10_top_routed.gds's real M1/M2 geometry BEFORE
         being committed here (see design_notes.md 108.56) -- all clear
         except the intended rst_n merge itself.
  5. Embeds the OPENSUSI_LOGO cell (same digitized artwork/grid/pitch as
     V9's -- ring_osc/tr_1um_i2c_slave_async_reassigned_logodots.gds --
     reused VERBATIM by copying the cell + its exact instance transform,
     rather than re-digitizing from the source PNG, since the placement
     envelope (RING_OSC top edge -525.2, core bottom edge -140.0-8.7=
     -148.7 clearance) is identical between V9 and V10 -- both quantities
     are core-height-independent).

Output: layout/step10/v10_chip_final.gds (draft -- real DRC/LVS still
needed from the user per this project's established convention; this
script's own verification is a klayout.db self-check only, same
methodology as 108.55/V9's own RING_OSC integration rounds).
"""
import re
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/tech/python")
import pya  # noqa: E402
from cells import tr_1um  # noqa: E402

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
IN_GDS = BASE + "/layout/step10/v10_top_routed.gds"
RING_OSC_GDS = BASE + "/ring_osc/RING_OSC.gds"
RING_OSC_LEF = BASE + "/ring_osc/RING_OSC.lef"
LOGO_SRC_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_reassigned_logodots.gds"
OUT_GDS = BASE + "/layout/step10/v10_chip_final.gds"

TOP_CELL = "tr_1um_i2c_slave_async"
RING_OSC_TOP = "RING_OSC"
LOGO_CELL_NAME = "OPENSUSI_LOGO"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
PTECT_LAYER = (63, 1)
PAD = 3.4
M1_W = 3.4
M2_W = 3.4

RING_ORIGIN_X, RING_ORIGIN_Y = -810.0, -650.0

# -- power (verbatim from route_ring_osc_power_v9.py) --
LEFT_VDD_X, LEFT_VSS_X = -801.9, -807.3
RIGHT_VDD_X, RIGHT_VSS_X = 807.3, 801.9
STRAP_W = 3.4
CORE_BOTTOM_Y = -140.0
STRAP_EXTEND_TARGET_Y = -545.0

# -- OUT/OUTD/ENB targets --
OUT9 = (180.0, -921.7)
OUT10 = (620.0, -921.7)

# -- logo instance transform, copied verbatim from the V9 reference (same
# envelope, core-height-independent -- see docstring) --
LOGO_TRANS_X, LOGO_TRANS_Y = -797.5, -499.45


def parse_lef_pins(path):
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


def pin_center_abs(rects, ox, oy):
    layer, x0, y0, x1, y1 = rects[0]
    cx = (x0 + x1) / 2 + ox
    cy = (y0 + y1) / 2 + oy
    return layer, cx, cy, (x0 + ox, y0 + oy, x1 + ox, y1 + oy)


def main():
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)
    assert top is not None

    def um(v):
        return int(round(v / dbu))

    # ---- 1. remove PTECT ----
    ptect_idx = layout.layer(*PTECT_LAYER)
    n_ptect = sum(1 for _ in top.each_shape(ptect_idx))
    top.shapes(ptect_idx).clear()
    print(f"removed {n_ptect} PTECT shape(s) from layer {PTECT_LAYER}")

    # ---- 2. place RING_OSC ----
    layout.read(RING_OSC_GDS)
    ring_cell = layout.cell(RING_OSC_TOP)
    assert ring_cell is not None
    ring_trans = db.DCplxTrans(1.0, 0.0, False, RING_ORIGIN_X, RING_ORIGIN_Y)
    top.insert(db.DCellInstArray(ring_cell.cell_index(), ring_trans))
    rb = ring_cell.bbox()
    print(f"RING_OSC placed at ({RING_ORIGIN_X},{RING_ORIGIN_Y}) -> abs bbox "
          f"({RING_ORIGIN_X + rb.left*dbu:.1f},{RING_ORIGIN_Y + rb.bottom*dbu:.1f})-"
          f"({RING_ORIGIN_X + rb.right*dbu:.1f},{RING_ORIGIN_Y + rb.top*dbu:.1f})")

    m1_idx = layout.layer(*M1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)

    tr_1um("TR-1um")
    via_lib = pya.Library.library_by_name("TR-1um", "*")
    via_decl = via_lib.layout().pcell_declaration("via_1")

    new_shapes = []  # (layer, x0,y0,x1,y1, net) for self-verification

    def wire(layer_name, x0, y0, x1, y1, w, net):
        layer_idx = m1_idx if layer_name == "M1" else m2_idx
        hw = w / 2.0
        if abs(x0 - x1) < 1e-6:
            box = db.Box(um(x0 - hw), um(min(y0, y1)), um(x0 + hw), um(max(y0, y1)))
        elif abs(y0 - y1) < 1e-6:
            box = db.Box(um(min(x0, x1)), um(y0 - hw), um(max(x0, x1)), um(y0 + hw))
        else:
            raise ValueError(f"non-manhattan segment {x0,y0,x1,y1}")
        top.shapes(layer_idx).insert(box)
        new_shapes.append((layer_name, box.left*dbu, box.bottom*dbu, box.right*dbu, box.top*dbu, net))

    def via(cx, cy, net, pad=PAD):
        pcell_idx = layout.add_pcell_variant(via_lib, via_decl.id(), {"x": pad, "y": pad, "x0": "c", "y0": "c"})
        top.insert(db.CellInstArray(pcell_idx, db.Trans(db.Vector(um(cx), um(cy)))))
        hw = pad / 2.0
        new_shapes.append(("M1", cx-hw, cy-hw, cx+hw, cy+hw, net))
        new_shapes.append(("M2", cx-hw, cy-hw, cx+hw, cy+hw, net))

    # ---- 3. RING_OSC power (verbatim) ----
    for label, x in [("TAP0_VDD", LEFT_VDD_X), ("TAP0_VSS", LEFT_VSS_X),
                      ("TAP3_VDD", RIGHT_VDD_X), ("TAP3_VSS", RIGHT_VSS_X)]:
        wire("M2", x, CORE_BOTTOM_Y, x, STRAP_EXTEND_TARGET_Y, STRAP_W, label)
        print(f"M2 strap extend {label}: x={x} y=[{STRAP_EXTEND_TARGET_Y},{CORE_BOTTOM_Y}]")

    # ---- 4. RING_OSC signals ----
    lef_pins = parse_lef_pins(RING_OSC_LEF)
    out_layer, out_x, out_y, out_box = pin_center_abs(lef_pins["OUT"], RING_ORIGIN_X, RING_ORIGIN_Y)
    outd_layer, outd_x, outd_y, outd_box = pin_center_abs(lef_pins["OUTD"], RING_ORIGIN_X, RING_ORIGIN_Y)
    enb_layer, enb_x, enb_y, enb_box = pin_center_abs(lef_pins["ENB"], RING_ORIGIN_X, RING_ORIGIN_Y)
    print(f"OUT  pin: layer={out_layer} abs=({out_x:.1f},{out_y:.1f})")
    print(f"OUTD pin: layer={outd_layer} abs=({outd_x:.1f},{outd_y:.1f})")
    print(f"ENB  pin: layer={enb_layer} abs=({enb_x:.1f},{enb_y:.1f})")

    LANDING_BOXES = [
        (176.3, -925.0, 183.7, -918.4),   # OUT9
        (616.3, -925.0, 623.7, -918.4),   # OUT10
        (845.3, 345.3, 848.7, 400.0),     # rst_n's own lane-0 M2 climb (merge target, 108.57)
        out_box, outd_box, enb_box,
    ]

    def route_path(label, pin, pin_layer, waypoints):
        pts = [pin] + waypoints
        (fx0, fy0), (fx1, fy1) = pts[0], pts[1]
        first_layer = "M1" if abs(fy0 - fy1) < 1e-6 else "M2"
        if pin_layer != first_layer:
            via(*pin, net=label)
        for k in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            if abs(y0 - y1) < 1e-6:
                wire("M1", x0, y0, x1, y1, M1_W, label)
            elif abs(x0 - x1) < 1e-6:
                wire("M2", x0, y0, x1, y1, M2_W, label)
            else:
                raise ValueError(f"non-manhattan segment {pts[k]}-{pts[k+1]}")
            if k < len(pts) - 2:
                via(x1, y1, net=label)
        print(f"{label}: {pin}[{pin_layer}] -> " + " -> ".join(str(p) for p in waypoints))

    # OUT/OUTD: verbatim from route_ring_osc_signals_v9.py
    route_path("OUT",  (out_x, out_y),  out_layer,
               [(830.0, out_y), (830.0, -907.0), (620.0, -907.0), OUT10])
    route_path("OUTD", (outd_x, outd_y), outd_layer,
               [(824.0, outd_y), (824.0, -913.0), (180.0, -913.0), OUT9])

    # ENB: path REDESIGNED for V10 (108.57). Two earlier approaches were
    # tried and rejected:
    #  1st (108.56): bottom crossing (Y=-855) + RIGHT-side notch climb at
    #     X=822 -- rejected, no room alongside OUT(830)/OUTD(824) in the
    #     ~22um notch over their shared Y range.
    #  2nd (108.56/early 108.57): bottom crossing + LEFT-side notch climb
    #     (X=-822) + TOP crossing at a fixed Y (894, then re-picked per
    #     whatever the current lane layout's max R was). This was rejected
    #     after the pad-pairing fix (108.57) grew the layout to 12 lanes
    #     (max R=908.6): a direct klayout.db query of the TOP-LEFT corner
    #     notch (X=-838..-817) found ELEVEN separate M1 rows at Y=851.7,
    #     857.3, ..., 907.7 (5.6 apart = LANE_PITCH) -- every lane's own
    #     corner-closing segment funnels through that exact notch on its
    #     way to the LEFT edge, leaving gaps of only ~3.8um each, too
    #     narrow for a 3.4-wide wire plus 2x2.0 Smin clearance (7.4
    #     needed). No single crossing Y clears all 12 lanes AND the
    #     individual pad final-hop stubs near NEAR_R=915 at every X
    #     simultaneously -- confirmed no viable constant-Y top crossing
    #     exists band-wide once N=12 lanes are packed this tightly.
    #
    # FIXED (108.57): abandoned the top-crossing idea, and also abandoned
    # a first "climb the right notch, X=830" replacement -- systematic
    # per-X-column klayout.db sweeps (X=817..875, 2um steps, full Y=-800
    # ..847) showed the ENTIRE right-edge notch out to X~873 is packed
    # nearly continuously: DIS_R ring at X=[837,843] (all Y), rst_n's own
    # lane-0 M2 climb plus ANOTHER net sharing the same lane at
    # X=[845,849] (Y=[-530,313] then rst_n at [345.3,847], only a 32um
    # gap), and lanes 1-4's own radial climbs at X=[849,873] each
    # spanning hundreds of um of Y with no usable gap -- there is no
    # column in X=[824,873] with room for a new 3.4-wide M2 wire plus
    # 2x2.0 Smin clearance across the needed Y span. The SAME sweep found
    # X=[873,895] completely EMPTY of M2 for the full Y=[-800,847] range
    # (lanes 5+ don't reach this far down -- their own core pins aren't
    # on the right edge), confirmed clear of OUT/OUTD/TAP straps too.
    # Path: dip to the clear bottom band (Y=-785) -> go right to X=884
    # (M1, crossing DIS_R's and everything else's M2 harmlessly, verified
    # 0 conflicts) -> climb X=884 (M2, verified 0 M2 conflicts the whole
    # way) to Y=400 (within rst_n's own [345.3,847] span) -> jog LEFT to
    # X=847 (M1 at Y=400, verified 0 M1 conflicts across X=[845,884]) ->
    # via directly onto rst_n's M2 wire (X=[845.3,848.7]).
    route_path("ENB", (enb_x, enb_y), enb_layer,
               [(enb_x, -785.0), (884.0, -785.0), (884.0, 400.0),
                (847.0, 400.0)])
    # explicit via at the merge point: the last ENB segment is M1
    # (horizontal jog to X=847), but rst_n's own wire there is M2, so a
    # via is needed to actually tie the two nets together (route_path
    # only auto-vias intermediate corners, not the final waypoint).
    via(847.0, 400.0, net="ENB")

    # ---- 5. logo ----
    # NOT a plain layout.read(LOGO_SRC_GDS) here: that file's OWN top cell
    # is itself named "tr_1um_i2c_slave_async" (it's a full V9 chip, not a
    # standalone logo library) -- reading it directly into this layout,
    # which ALREADY has a cell of that exact name (this V10 chip), makes
    # klayout merge V9's entire chip content into the current top cell,
    # superimposing two independent full chip layouts at the same
    # coordinates (confirmed as the root cause of a 2100+ "violation"
    # explosion when first tried this way, design_notes.md 108.56).
    # Fixed: load the logo source into an ISOLATED Layout object and copy
    # ONLY the OPENSUSI_LOGO cell's shapes (it's a pure M2 leaf cell, no
    # sub-instances -- see script/place_opensusi_logo_dots.py's
    # build_dot_cell()) into a freshly-created cell of the same name here.
    logo_src = db.Layout()
    logo_src.read(LOGO_SRC_GDS)
    logo_src_cell = logo_src.cell(LOGO_CELL_NAME)
    assert logo_src_cell is not None
    logo_cell = layout.create_cell(LOGO_CELL_NAME)
    logo_m2 = logo_src.layer(*M2_LAYER)
    for shp in logo_src_cell.each_shape(logo_m2):
        logo_cell.shapes(m2_idx).insert(shp.polygon if shp.is_polygon() else shp.box)
    logo_trans = db.Trans(db.Vector(um(LOGO_TRANS_X), um(LOGO_TRANS_Y)))
    top.insert(db.CellInstArray(logo_cell.cell_index(), logo_trans))
    lb = logo_cell.bbox()
    print(f"OPENSUSI_LOGO placed at ({LOGO_TRANS_X},{LOGO_TRANS_Y}) -> abs bbox "
          f"({LOGO_TRANS_X + lb.left*dbu:.1f},{LOGO_TRANS_Y + lb.bottom*dbu:.1f})-"
          f"({LOGO_TRANS_X + lb.right*dbu:.1f},{LOGO_TRANS_Y + lb.top*dbu:.1f})")

    # ---- 6. top-level M2PIN/TXM2 chip pin markers (108.62) ----
    # User: "Layout のトップに M2PIN/TXTM2 が無いです。V9のときはスクリ
    # プトを通しています。確認ください。" -- confirmed via klayout.db:
    # V9's actual chip GDS (ring_osc/tr_1um_i2c_slave_async_ringosc_
    # signals.gds, the one behind V9's own successful LVS run,
    # ring_osc/LVS_error.lvsdb 08-31) has 16 TOP-CELL-DIRECT (not nested
    # inside the OSS_FRAME_GIO instance) M2PIN(49,1) boxes + TXM2(49,0)
    # text labels, one pair per real bond pad -- added by
    # script/add_top_pins_gio_v9.py, per design_notes.md 82.x/83.x. V10's
    # own pipeline (this script) never carried that step over: a direct
    # klayout.db count on v10_chip_final.gds showed ZERO top-cell-direct
    # shapes on either layer. This is the real root cause of the P9/P10
    # "No equivalent pin ... physical connection is not made to the
    # subcircuit" error (under "Circuit OSS_FRAME_GIO" in the real LVS
    # log, design_notes.md 108.61) -- NOT a top-level pin-count issue
    # (108.60's fix attempt, reverted in 108.61, addressed the wrong
    # layer of the problem entirely). Every OTHER top pin (P1-P7, P11-
    # P15, VDD, VSS) still matched despite lacking these markers too,
    # because those pins carry a real routed M1/M2 wire reaching the pad
    # from the top cell -- that wire itself is enough for flag_missing_
    # ports to recognize a top-level connection. P9/P10 are the only pads
    # with ZERO top-cell wiring of any kind (fully spare, by design -- no
    # core signal, no VDD/VSS tie, no DIS tie), so they are the only pins
    # that actually depend on this marker step to be recognized as real
    # ports at all.
    #
    # Reused VERBATIM from add_top_pins_gio_v9.py: OSS_FRAME_GIO is
    # placed at (0,0)/r0/mag1 in V10's top cell too (confirmed via
    # klayout.db.Layout.each_inst()), identical to V9 -- so the same 16
    # PO-layer-derived marker centers (independently verified against
    # each pad's real M2 pad shape when this list was first built) apply
    # unchanged to V10's physical pad positions.
    M2PIN_LAYER = (49, 1)
    TXM2_LAYER = (49, 0)
    TOP_PIN_SIZE_UM = 3.0
    TOP_PINS = [
        ("P1",  -200.0, 1040.0),
        ("P2",  -600.0, 1040.0),
        ("P3", -1040.0,  600.0),
        ("P4", -1040.0,  200.0),
        ("P5", -1040.0, -200.0),
        ("P6", -1040.0, -600.0),
        ("P7",  -600.0,-1040.0),
        ("VSS", -200.0,-1040.0),
        ("P9",   200.0,-1040.0),
        ("P10",  600.0,-1040.0),
        ("P11", 1040.0, -600.0),
        ("P12", 1040.0, -200.0),
        ("P13", 1040.0,  200.0),
        ("P14", 1040.0,  600.0),
        ("P15",  600.0, 1040.0),
        ("VDD",  200.0, 1040.0),
    ]
    m2pin_idx = layout.layer(*M2PIN_LAYER)
    txm2_idx = layout.layer(*TXM2_LAYER)
    half = TOP_PIN_SIZE_UM / 2.0
    for label, x, y in TOP_PINS:
        box = db.DBox(x - half, y - half, x + half, y + half).to_itype(dbu)
        top.shapes(m2pin_idx).insert(box)
        text = db.DText(label, x, y).to_itype(dbu)
        top.shapes(txm2_idx).insert(text)
    print(f"\nadded {len(TOP_PINS)} M2PIN({M2PIN_LAYER[0]}/{M2PIN_LAYER[1]}) boxes "
          f"+ {len(TOP_PINS)} TXM2({TXM2_LAYER[0]}/{TXM2_LAYER[1]}) labels to '{TOP_CELL}' "
          f"(top-cell-direct, matching V9's add_top_pins_gio_v9.py convention)")

    layout.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")

    import json
    json.dump(new_shapes, open(OUT_GDS.replace(".gds", "_new_shapes.json"), "w"))


if __name__ == "__main__":
    main()
