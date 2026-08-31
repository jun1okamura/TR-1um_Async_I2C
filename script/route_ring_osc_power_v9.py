"""
route_ring_osc_power_v9.py (this session, user request: "コアの両端のTAP2の
M2をそのままRING_OSCまで延伸します。RING_OSCの上下にM1(10um)でVDD/VSSをつな
ぎます。配線まで進めてください。" -- following the Y=-650 placement
confirmed via AskUserQuestion, "Y=-650のことです。")

REVISED after the user ran real KLayout DRC on the first version's
output and found shorts: "上下のM1の電源バーがショートしています。
RING_OSCの上下にM1(10um)でVDD/VSSの接続はやめます。" -- the top/bottom
M1(10um) VDD/VSS bus feature (former steps 2/3 below) has been REMOVED
entirely per this explicit instruction. Root cause, for the record (not
acted on beyond removal, since the user chose to drop the feature rather
than have it fixed): all 22 non-GC.ANT DRC violations (12x V1.S1 via-cut
spacing <1.5, 4x V1.CO via-contact spacing <1.0, 6x M2.S1 M2 spacing
<2.0) trace to this script's own multi_via() calls for the bus-to-strap
via junctions -- multi_via() offsets its 2 vias HORIZONTALLY by the
V1_CUT+MIN_VIA_SPACE pitch (3.1um), but at a narrow (3.4um-wide) TAP-type
strap with a same-polarity-spacing neighbor only 2.0um away (VDD/VSS
straps here, exactly as documented at length in route_gio_core_v9.py's
own TAP_STUB_W/multi_via_v comments for the identical situation on the
core's own TAP-to-busbar junctions), a horizontally-offset via pad pushes
part of itself past the neighbor strap's edge. route_gio_core_v9.py
avoided this at its own equivalent junctions by using multi_via_v()
(vertical offset) instead, precisely because "2 vias can't be placed
side by side there" -- this script did not follow that precedent for its
new bus-via junctions, and that omission is the actual bug. Two
unrelated "GC.ANT: GC must electrically connect to Substrate" violations
also appear in the same DRC run, at abs X~710-713, well away from any of
this script's own shapes (all of which sit at abs X~800-810) -- these
look pre-existing in RING_OSC's own native layout and are NOT part of
this routing work; left for the user's own attention separately.

STEP 2 of RING_OSC integration (step 1 = script/place_ring_osc.py). Draws
the VDD/VSS power connection between the core's own TAP2 (end-column) M2
straps and RING_OSC's pre-existing internal power mesh. As of this
revision, this connection is made ENTIRELY by the M2 strap extension
below (core TAP2 straight down into RING_OSC's own pre-existing internal
strap) -- no M1 bus, no new vias are added by this script at all.

GEOMETRIC FACTS ESTABLISHED THIS SESSION (direct klayout.db inspection of
ring_osc/RING_OSC.gds and src/tr_1um_i2c_slave_async.gds -- see chat for
full derivation):

  - The core's two END-COLUMN TAP2 macros (TAP0 at the core's left edge,
    TAP3 at its right edge) each carry TWO separate, dedicated, full-
    height M2 straps (VDD and VSS), 3.4um wide, offset ~5.4um apart --
    NOT a single shared rail. Their absolute X centerlines, already
    established by route_gio_core_v9.py's own VDD_TAP_X/VSS_TAP_X dicts:
      TAP0 (left):  VDD=-801.9   VSS=-807.3
      TAP3 (right): VDD=+807.3   VSS=+801.9
    Both straps run the core's full height, ending flush at the core's
    own bbox bottom, Y=-140.0.

  - RING_OSC.gds (native, un-placed) has the IDENTICAL dual-strap
    structure at its own two end columns, at LOCAL X so close to the
    core's that once RING_OSC is placed at the same X origin as the core
    (-810, per the user's own placement instruction), the centerlines
    match EXACTLY:
      left col:  VSS local X[1.0,4.4] (abs center -807.3, matches TAP0 VSS)
                 VDD local X[6.4,9.8] (abs center -801.9, matches TAP0 VDD)
      right col: VSS local X[1610.2,1613.6] (abs center 801.9, matches TAP3 VSS)
                 VDD local X[1615.6,1619.0] (abs center 807.3, matches TAP3 VDD)
    (Polarity of each strap confirmed via its own via_1 cuts (layer 19/0)
    down to the row power rails, cross-checked against the TXM2 "vdd"/
    "gnd" pin-label text next to each -- not guessed from symmetry.)
    Each strap already runs the FULL native height (local Y -118.9 to
    123.7, confirmed continuous via 4 slightly-overlapping segments) and
    is ALREADY tied, via pre-existing vias, into RING_OSC's own 5 row
    power rails (alternating GND/VDD/GND/VDD/GND bottom-to-top). So
    RING_OSC's entire internal power mesh only needs to be fed at these
    two end columns -- it does not need a fresh top-to-bottom rebuild.

  - (Formerly relevant to the removed top/bottom M1 bus feature, kept
    for the record: RING_OSC's bottom row (row 4, nearest the -120 edge)
    has real M1 SIGNAL wiring -- 5.1um-wide vertical jumpers, 32.4um
    pitch, local Y[-113.5,-61.7], NOT touching the GND rail -- running
    through the height band a bottom bus would have occupied. Moot now
    that no M1 bus is drawn at all, but the underlying congestion is a
    real property of RING_OSC's own layout worth remembering if a bus
    is ever reconsidered.)

Output: ring_osc/tr_1um_i2c_slave_async_ringosc_routed.gds (new file,
built from ring_osc/tr_1um_i2c_slave_async_ringosc_placed.gds -- neither
that file nor src/tr_1um_i2c_slave_async.gds is overwritten until the
user reviews this).
"""
import klayout.db as db

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
IN_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_ringosc_placed.gds"
OUT_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_ringosc_routed.gds"
TOP_CELL = "tr_1um_i2c_slave_async"

M2_LAYER = (20, 0)

# -- core TAP0/TAP3 (end-column) strap centerlines, absolute um --
# (from route_gio_core_v9.py's VDD_TAP_X / VSS_TAP_X dicts, unchanged)
LEFT_VDD_X, LEFT_VSS_X = -801.9, -807.3
RIGHT_VDD_X, RIGHT_VSS_X = 807.3, 801.9
STRAP_W = 3.4
CORE_BOTTOM_Y = -140.0     # core's own bbox bottom; its TAP straps end here

# extend down to comfortably inside RING_OSC's own topmost strap segment
# (native local Y[61.1,123.7] -> abs [-588.9,-526.3] at origin Y=-650)
STRAP_EXTEND_TARGET_Y = -545.0

# -- RING_OSC placement (must match script/place_ring_osc.py) --
ORIGIN_X_UM, ORIGIN_Y_UM = -810.0, -650.0
RING_NATIVE_BBOX = (-6.3, -120.0, 1626.3, 124.8)


def main():
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)
    assert top is not None

    m2_idx = layout.layer(*M2_LAYER)

    def um(v):
        return int(round(v / dbu))

    def wire(layer_idx, x0, y0, x1, y1, w):
        hw = w / 2.0
        if abs(x0 - x1) < 1e-6:
            box = db.Box(um(x0 - hw), um(min(y0, y1)), um(x0 + hw), um(max(y0, y1)))
        elif abs(y0 - y1) < 1e-6:
            box = db.Box(um(min(x0, x1)), um(y0 - hw), um(max(x0, x1)), um(y0 + hw))
        else:
            raise ValueError(f"non-manhattan segment {x0,y0,x1,y1}")
        top.shapes(layer_idx).insert(box)

    log = []

    # ---- extend core's 4 end-column M2 straps down to RING_OSC ----
    # (this is the ONLY routing this script does -- see docstring for why
    # the former M1 top/bottom bus steps were removed)
    for label, x in [("TAP0_VDD", LEFT_VDD_X), ("TAP0_VSS", LEFT_VSS_X),
                      ("TAP3_VDD", RIGHT_VDD_X), ("TAP3_VSS", RIGHT_VSS_X)]:
        wire(m2_idx, x, CORE_BOTTOM_Y, x, STRAP_EXTEND_TARGET_Y, STRAP_W)
        log.append(f"M2 strap extend {label}: x={x} y=[{STRAP_EXTEND_TARGET_Y},{CORE_BOTTOM_Y}]")

    for line in log:
        print(line)

    layout.write(OUT_GDS)
    print(f"wrote {OUT_GDS}")


if __name__ == "__main__":
    main()
