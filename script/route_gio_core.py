import klayout.db as db
import sys
sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/tech/python")
import pya
from cells import tr_1um

# updated to the reassembled top-level GDS that embeds the NEW OSS_FRAME_GIO
# cell (rebuilt from the user's edited FRAME/TR-1um_frame_25x25.gds), same
# instance transform as before (GIO at 0,0 / core at -810000,-190000 nm).
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/tr_1um_i2c_slave_async_newgio.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/tr_1um_i2c_slave_async_routed.gds"
TOP_CELL = "tr_1um_i2c_slave_async"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
M1_WIRE_W = 1.8   # matches DR['M1.W1'].min
M2_WIRE_W = 3.4   # matches via_1 pad size, well above DR['M2.W1'].min=3.0
PAD = 3.4
LANE_R0 = 847.0
LANE_PITCH = 6.0   # matches route_channels_nrow_fm.py's TRACK_PITCH=5.4 rationale
                   # (via-pad clearance); 6.0 gives via-pad-to-via-pad clearance
                   # 6.0-3.4=2.6um (> M1.S1=1.4, > M2.S1=2.0) with margin.
NEAR_R = 913.0     # v2: was 918.0 -- too close. GIO has thin M1/M2 slivers
                   # (per-pin approach-lead remnants, NOT part of the big
                   # OBS blob) sitting right at radius 920.0, confirmed via
                   # full-layout M1.S1/M2.S1 space_check (17+1 violations at
                   # exactly this radius with a 0.3um gap to our via pads).
                   # 913.0 leaves >=1.4um M1.S1/2.0um M2.S1 clearance even
                   # after the via_1 pad's own 1.7um half-width.
# (No PAD_LEAD_W constant needed: all connections now land on proper
# M1PIN/M2PIN-marked pins, not on real wire-bond pad flash metal, so the
# PDK's M2P.PE/M1P.PE 40um-lead-out-width rule never applies here.)

NETS = {
 "rst_n":      (78.3,796.7,"TOP","M2",   530,921.7,"TOP","M2", None),
 "scl":        (-89.1,796.7,"TOP","M2",  -530,921.7,"TOP","M2", None),
 "sda_in":     (-56.7,796.7,"TOP","M2",  921.7,270,"RIGHT","M2", None),
 "sda_oe":     (808.5,330.4,"RIGHT","M1", 921.7,220,"RIGHT","M2", None),  # y: 190->220 (targets HIZ13, whose position moved in the new frame; this fix was missed earlier, same as HIZ3)
 "tx_data[0]": (808.5,341.2,"RIGHT","M1", 921.7,-270,"RIGHT","M2", None),
 "tx_data[1]": (808.5,335.8,"RIGHT","M1", 921.7,-530,"RIGHT","M2", None),
 "tx_data[2]": (332.1,796.7,"TOP","M2",  -921.7,-270,"LEFT","M2", None),
 "tx_data[3]": (299.7,796.7,"TOP","M2",  -921.7,-530,"LEFT","M2", None),
 "tx_data[4]": (267.3,796.7,"TOP","M2",  -921.7,270,"LEFT","M2", None),
 "tx_data[5]": (234.9,796.7,"TOP","M2",  -270,921.7,"TOP","M2", None),
 "tx_data[6]": (202.5,796.7,"TOP","M2",  -921.7,530,"LEFT","M2", None),
 "tx_data[7]": (808.5,346.6,"RIGHT","M1", 921.7,530,"RIGHT","M2", None),
 "rx_data[0]": (191.7,796.7,"TOP","M2",  921.7,-180,"RIGHT","M2", None),
 "rx_data[1]": (-808.5,438.4,"LEFT","M1", 921.7,-620,"RIGHT","M2", "CW"),
 "rx_data[2]": (-808.5,443.8,"LEFT","M1", -921.7,-180,"LEFT","M2", None),
 "rx_data[3]": (-808.5,449.2,"LEFT","M1", -921.7,-620,"LEFT","M2", None),
 "rx_data[4]": (-808.5,454.6,"LEFT","M1", -921.7,180,"LEFT","M2", None),
 "rx_data[5]": (-808.5,460.0,"LEFT","M1", -180,921.7,"TOP","M2", None),
 "rx_data[6]": (-808.5,465.4,"LEFT","M1", -921.7,620,"LEFT","M2", None),
 "rx_data[7]": (-808.5,433.0,"LEFT","M1", 921.7,620,"RIGHT","M2", None),
 # ---- VDD/VSS destinations for the (three-times-revised) new FRAME/TR-1um_
 # frame_25x25.gds. Round 1: single continuous VDD ring around the whole
 # die -- rejected ("ドーナッツで無い方が良さそうですね", 2026-08-26). Round 2:
 # ring replaced by 14 separate VDD pads + VSS kept its original 2 pads.
 # Round 3 (current): user reports the VDD/VSS labels in round 2 were
 # actually swapped by mistake -- re-scanned the frame and confirmed: the
 # single M1 pad (50,920)-(350,934) is now labeled VDD (was VSS), the 14
 # distributed M2 pads are now labeled VSS (was VDD), and the far mirror
 # pads at (200,1040)/(−200,−1040) keep their original VDD/VSS labels
 # (unchanged both rounds).
 #   VDD: M1 pad (~100,925) [was VSS's pad]
 #   VSS: nearest of the 14 distributed M2 pads, (-925,5) [was VDD's]
 # (The far mirror pads at (200,1040)/(-200,-1040) are real 100x100um
 # wire-bond pad flash, not proper M1PIN/M2PIN-marked pins -- user confirmed
 # these should NOT be used as connection points at all, see note below.)
 #
 # VDD's core bus sits on the RIGHT (x=825) but its only single-pad
 # connection is now on the TOP edge (~100,925) -- the same long,
 # shared-pool-busting RIGHT-to-TOP sweep that VSS needed in round 2. So VDD
 # (not VSS) now gets the dedicated-private-radius treatment; see
 # connect_core_to_gio_private("VDD", ...) after the main loop below.
 # VSS's bus sits on the LEFT (x=-825) and its nearest new pad, (-925,5), is
 # also on the LEFT edge -- a short, low-risk hop, so it stays as a normal
 # NETS entry like VDD's short (930,0) connection did in round 2.
 # (core-side y deliberately != pin y=5 -- using the identical y on the same
 # edge for both ends degenerates the ring path to a zero-length segment)
 "VSS":        (-825.0,100.0,"LEFT","M2",  -925.0,5.0,"LEFT","M2", None),
 # ---- additional GIO pins that are schematic-labeled VSS but were never
 # physically wired (found via user report: HIZ9, HIZ10, OUT13 were
 # floating in the routed GDS despite having net labels in
 # tr_1um_i2c_slave_async.sch). Each taps a core GND row rail on the RIGHT
 # edge (the LEFT edge's 4 GND rows are already used by the VSS left-spine
 # branches) and rides the shared lane system out to its real GIO pin,
 # exactly like the 20 signal nets above. Coordinates re-verified unchanged
 # against the new frame. (Unaffected by the VDD/VSS pad-label swap -- these
 # are named SIGNAL pins reassigned to the VSS net, not the VDD/VSS power
 # pads themselves.)
 # NOTE (2026-08-26, LVS-driven fix): "VSS_OUT2" was REMOVED here. Verified
 # against tr_1um_i2c_slave_async.spice's positional x1 (OSS_FRAME_GIO)
 # instantiation: GIO's OUT2 pin is wired to "net27", an anonymous/unused
 # top-level net (single-pin, not connected to anything else) -- NOT to
 # VSS. Confirmed by the user via LVS cross-reference (reference net
 # "NET27 (1)" unmatched, layout "VSS (7)" unmatched -- GIO/OUT2 was
 # incorrectly shorted to VSS in the layout). Full re-derivation of every
 # GIO pin's schematic-assigned signal (via x1/x2's positional argument
 # lists in tr_1um_i2c_slave_async.spice, cross-checked against the LEF's
 # real pin coordinates) confirms HIZ9/HIZ10/OUT13 (VSS) and HIZ2/HIZ7/HIZ15
 # (VDD) below are all correct as-is; OUT2 was the only mistake. GIO's OUT2
 # pin is left completely unrouted now, matching the schematic's unused/
 # no-connect intent.
 "VSS_HIZ9":   (810.0,-101.2,"RIGHT","M1", 220.0,-921.7,"BOTTOM","M2", None),
 "VSS_HIZ10":  (810.0,-101.2,"RIGHT","M1", 580.0,-921.7,"BOTTOM","M2", None),
 "VSS_OUT13":  (810.0,206.6,"RIGHT","M1",  921.7,180.0,"RIGHT","M2", None),
 # ---- VSS_SPINE / VDD_SPINE (bus exits -> the real 100x100um wire-bond pad
 # flash at (-200,-1040)/(200,1040)) have been REMOVED per user instruction
 # (2026-08-26): "実際のボンディングパッドには接続しないでください。
 # OSS_FRAME_GIOに配置したM1/M2 PINへ接続してください" -- only connect to
 # properly-placed M1PIN/M2PIN-marked pins (VDD's M1 pad, VSS's 14
 # distributed M2 pads), never to raw bond-pad flash metal that merely
 # happens to sit near an orphaned text label. The VDD/VSS 10um buses (built
 # further down) still exist and still carry current from all 4 core rows --
 # they now simply have a single exit point each (VDD's and VSS's main
 # NETS-dict connections below, both already on proper PIN markers) instead
 # of a second one aimed at the bond pad.
 # ---- HIZ pin re-tie (user re-assigned HIZ1/2/7/11/15 after the previous
 # round): HIZ2, HIZ7, HIZ15 now tie to VDD (HIZ1 and HIZ11 move to the DIS
 # chain instead, see DIS_CHAIN_POINTS below; HIZ15 leaves the DIS chain).
 # LEFT-edge VDD row taps (-810, row_y) were untouched until now -- the VSS
 # spine only taps the GND-row y-values (-101.2/206.6/471.2/698.0), which are
 # different rows than VDD's (-41.2/266.6/531.2/758.0) -- so they're free.
 "VDD_HIZ2":   (-810.0,758.0,"LEFT","M1",  -580.0,921.7,"TOP","M2", None),
 "VDD_HIZ7":   (-810.0,-41.2,"LEFT","M1",  -580.0,-921.7,"BOTTOM","M2", None),  # x: -610->-580 (new frame)
 "VDD_HIZ15":  (810.0,531.2,"RIGHT","M1",  580.0,921.7,"TOP","M2", None),
}
# VDD core-exit moved from the row tap (810,758) out to (830,758), the right
# edge of a new 10um-wide M2 bus (see VDD_* block below) that gathers all 4
# core VDD rows. cl="M2" (was "M1") because the bus is vertical -> M2 under
# this file's horizontal=M1/vertical=M2 discipline; the main loop's existing
# "via at entry if cl != first ring layer" logic then automatically drops a
# via at (830,758) to hop the M2 bus onto the M1 ring-travel segment.

# ---- VDD near-core power distribution (user request): widen the VDD wiring
# immediately outside the core to 10um, and tap all 4 core VDD row rails with
# M1 2.6um branches, instead of the single-row tap used previously.
# Bus is M2 (vertical) specifically so it can cross UNDER the M1 horizontal
# leads that sda_oe/tx_data[0]/tx_data[1]/tx_data[7]/VSS use to exit the core
# in this same x-band (810-850+) at other y -- M1/M2 crossing is a normal,
# DRC-safe crossing (no via = no short), whereas an M1 bus would have run
# directly into those M1 leads.
VDD_ROWS     = [-41.2, 266.6, 531.2, 758.0]   # assembled y of the 4 core VDD row rails
VDD_BUS_X    = 825.0     # bus center x (core right edge = 810; bus spans x 820-830)
VDD_BUS_W    = 10.0
VDD_BRANCH_W = 2.6
VDD_VIA_PAD  = 3.4       # keep at PDK Wmin so both this via and the main
                          # loop's auto entry-via (also default-sized, at
                          # x=828) fit side-by-side inside the 10um bus
                          # (820-830) with clearance to spare.
VDD_BRANCH_VIA_X = 822.0  # off-center from VDD_BUS_X=825 so the topmost row's
                          # branch-via (at y=758) doesn't crowd the entry-via
                          # the main loop drops at (828,758) -- found via DRC
                          # check: same-y siting caused M1.S1/M2.S1/M2.W1
                          # violations from the two via pads nearly touching.
VDD_BRANCH_STOP_X = 823.0 # branch wire only needs to overlap its own via's
                          # pad (centered at VDD_BRANCH_VIA_X); stopping here
                          # (rather than running the wire all the way to
                          # VDD_BUS_X=825) keeps it clear of the row-758
                          # entry-via's M1 pad (found via DRC: reaching 825
                          # left only 1.3um gap, short of M1.S1's 1.4um min).

def perimeter_s(x, y, edge, R):
    if edge == "TOP":    return max(-R,min(R,x)) + R
    if edge == "RIGHT":  return 2*R + (R - max(-R,min(R,y)))
    if edge == "BOTTOM": return 4*R + (R - max(-R,min(R,x)))
    if edge == "LEFT":   return 6*R + (max(-R,min(R,y)) + R)
    raise ValueError(edge)

def s_to_xy(s, R):
    P = 8*R
    s = s % P
    if s <= 2*R: return (s-R, R)
    if s <= 4*R: return (R, R-(s-2*R))
    if s <= 6*R: return (R-(s-4*R), -R)
    return (-R, (s-6*R)-R)

def ring_waypoints(s1, s2, R, force_dir=None):
    P = 8*R
    corners = [2*R, 4*R, 6*R, 8*R]
    if force_dir is None:
        d_cw = (s2 - s1) % P; d_ccw = (s1 - s2) % P
        direction = "CW" if d_cw <= d_ccw else "CCW"
    else:
        direction = force_dir
    pts = []
    if direction == "CW":
        span = (s2 - s1) % P
        for k in corners:
            off = (k - s1) % P
            if 0 < off < span: pts.append((off, k % P))
    else:
        span = (s1 - s2) % P
        for k in corners:
            off = (s1 - k) % P
            if 0 < off < span: pts.append((off, k % P))
    pts.sort()
    return [s_to_xy(k, R) for _, k in pts]

def project_to_R(px, py, edge, R):
    if edge in ("TOP","BOTTOM"): return (px, R if edge=="TOP" else -R)
    else: return (R if edge=="RIGHT" else -R, py)

def seg_layer(a, b):
    if abs(a[1]-b[1]) < 1e-6 and abs(a[0]-b[0]) >= 1e-6: return "M1"
    if abs(a[0]-b[0]) < 1e-6 and abs(a[1]-b[1]) >= 1e-6: return "M2"
    raise ValueError(f"non-manhattan or zero-length segment {a} {b}")

# ---- lane assignment: greedy interval scheduling on the unrolled ring
# coordinate (cut at s=4625, the BOTTOM-center point -- confirmed unused by
# every net's ring path since rx_data[1] is the only bottom-adjacent case and
# it's forced via TOP to avoid PTECT). Nets whose ring-travel spans don't
# overlap can safely share one radius; this cuts required lanes from 22 down
# to ~11, keeping the whole band within the OBS-free radius budget (<920). ----
R_NOM = 880.0
CUT = 4625.0
PERI = 7400.0
def unroll(s): return (s - CUT) % PERI

net_interval = {}
net_dir = {}
for name, v in NETS.items():
    px,py,ce,cl,gx,gy,ge,gl,fd = v
    s1 = perimeter_s(px,py,ce,R_NOM); s2 = perimeter_s(gx,gy,ge,R_NOM)
    d_cw=(s2-s1)%PERI; d_ccw=(s1-s2)%PERI
    direction = fd if fd else ("CW" if d_cw<=d_ccw else "CCW")
    u1,u2 = unroll(s1), unroll(s2)
    net_interval[name] = (min(u1,u2), max(u1,u2))
    net_dir[name] = direction

MARGIN = 5.0
lane_last = []
lane_of = {}
for name,(lo,hi) in sorted(net_interval.items(), key=lambda kv: kv[1][0]):
    placed = False
    for i,last in enumerate(lane_last):
        if last < lo - MARGIN:
            lane_of[name] = i; lane_last[i] = hi; placed = True; break
    if not placed:
        lane_of[name] = len(lane_last); lane_last.append(hi)
print(f"lanes needed: {len(lane_last)} (was 22 with one-lane-per-net)")

# ---- DIS chain (user request): P7 "drives" HIZ3/4/5/6/12/14/15 -- a purely
# pad-to-pad local net, not tied to VDD/VSS. Daisy-chain the 8 pins in ring
# order (by unrolled angular position) so each link only spans the arc to its
# neighbor.
#
# First attempt reused the SAME 850-910 lane band as the 27 core<->GIO nets
# (sharing lane_last) -> pushed some links past the ~920um GIO obstruction
# boundary (that band was already packed to 11-12 concurrent lanes).
# Second attempt gave it a private multi-lane band at R=700-740 -- but that
# radius is INSIDE the core's own die area (core spans roughly x=-810..810),
# so the DIS wires ran straight through the core's internal standard-cell
# routing and picked up spacing violations against metal that isn't even in
# our own NET_SHAPES.
#
# Third (final) approach: a daisy chain doesn't need a multi-lane packer at
# all -- consecutive links share an endpoint and, sorted in ring order, never
# occupy overlapping arcs, so the whole chain can safely share ONE radius.
# Pick a radius genuinely outside the core (>810) and clear of the VDD bus
# (820-830) / VSS spine (-830..-820) and the primary lane band (850-910):
# the empty ~20um gap at 831-849 fits exactly one shared radius comfortably.
DIS_R = 840.0
# HIZ15 moved out to VDD (see VDD_HIZ15 above); HIZ1 and HIZ11 moved in, per
# the user's revised assignment (VDD: HIZ2/7/15, VSS: HIZ9/10 unchanged,
# DIS: HIZ1/3/4/5/6/11/12/14 driven by P7). Re-sorted by ring position.
DIS_CHAIN_POINTS = [
    ("HIZ1",  (-220.0,921.7,"TOP","M2")),
    ("HIZ14", (921.7,580.0,"RIGHT","M2")),  # y: 610->580 (new frame)
    ("HIZ12", (921.7,-220.0,"RIGHT","M2")),
    ("HIZ11", (921.7,-580.0,"RIGHT","M2")),
    ("P7",    (-530.0,-921.7,"BOTTOM","M2")),
    ("HIZ6",  (-921.7,-580.0,"LEFT","M2")),
    ("HIZ5",  (-921.7,-220.0,"LEFT","M2")),
    ("HIZ4",  (-921.7,220.0,"LEFT","M2")),
    ("HIZ3",  (-921.7,580.0,"LEFT","M2")),  # y: 610->580 (new frame; this fix was missed earlier)
]
DIS_LINKS = [(DIS_CHAIN_POINTS[i][0] + "_" + DIS_CHAIN_POINTS[i+1][0],
              DIS_CHAIN_POINTS[i][1], DIS_CHAIN_POINTS[i+1][1])
             for i in range(len(DIS_CHAIN_POINTS)-1)]

print(f"DIS chain: single shared radius R={DIS_R} for all {len(DIS_LINKS)} links")

# ---- build layout ----
layout = db.Layout()
layout.read(IN_GDS)
dbu = layout.dbu
top = layout.cell(TOP_CELL)
m1_idx = layout.layer(*M1_LAYER)
m2_idx = layout.layer(*M2_LAYER)

tr_1um("TR-1um")
via_lib = pya.Library.library_by_name("TR-1um", "*")
via_decl = via_lib.layout().pcell_declaration("via_1")

def um(v): return int(round(v/dbu))

NET_SHAPES = {}
cur_net = [None]
def wire(layer_idx, x0,y0,x1,y1,w):
    hw = w/2.0
    if abs(x0-x1) < 1e-6:
        box = db.Box(um(x0-hw), um(min(y0,y1)), um(x0+hw), um(max(y0,y1)))
    elif abs(y0-y1) < 1e-6:
        box = db.Box(um(min(x0,x1)), um(y0-hw), um(max(x0,x1)), um(y0+hw))
    else:
        raise ValueError(f"non-manhattan segment {x0,y0,x1,y1}")
    top.shapes(layer_idx).insert(box)
    if cur_net[0]:
        L = "M1" if layer_idx==m1_idx else "M2"
        NET_SHAPES.setdefault(cur_net[0], []).append((L, box.left*dbu, box.bottom*dbu, box.right*dbu, box.top*dbu))

def via(cx, cy, pad=PAD):
    pcell_idx = layout.add_pcell_variant(via_lib, via_decl.id(), {"x": pad, "y": pad, "x0":"c","y0":"c"})
    top.insert(db.CellInstArray(pcell_idx, db.Trans(db.Vector(um(cx), um(cy)))))
    if cur_net[0]:
        hw = pad/2.0
        NET_SHAPES.setdefault(cur_net[0], []).append(("VIA", cx-hw, cy-hw, cx+hw, cy+hw))

# (VDD's core-exit X-hop widening now happens inside
# connect_core_to_gio_private()'s wide_first_w param, since VDD is no longer
# routed through this shared-pool loop -- see below.)

route_log = []
idx_map_w = {"M1": M1_WIRE_W, "M2": M2_WIRE_W}
for name,v in NETS.items():
    cur_net[0] = name
    px,py,ce,cl,gx,gy,ge,gl,fd = v
    R = LANE_R0 + lane_of[name]*LANE_PITCH
    C = project_to_R(px,py,ce,R)
    D = project_to_R(gx,gy,ge,R)
    NEAR = project_to_R(gx,gy,ge,NEAR_R)
    s1 = perimeter_s(px,py,ce,R); s2 = perimeter_s(gx,gy,ge,R)
    corners = ring_waypoints(s1,s2,R,fd)
    ring_path = [(px,py)] + [C] + corners + [D, NEAR]

    n_vias = 0
    idx_map = {"M1": m1_idx, "M2": m2_idx}
    ring_seg_layers = [seg_layer(ring_path[k], ring_path[k+1]) for k in range(len(ring_path)-1)]

    if cl != ring_seg_layers[0]:
        via(px,py); n_vias += 1

    for k in range(len(ring_path)-1):
        a, b = ring_path[k], ring_path[k+1]
        L = ring_seg_layers[k]
        wire(idx_map[L], a[0],a[1],b[0],b[1], idx_map_w[L])
        if k > 0 and ring_seg_layers[k-1] != L:
            via(a[0], a[1]); n_vias += 1

    if ring_seg_layers[-1] != gl:
        via(NEAR[0], NEAR[1]); n_vias += 1
    wire(idx_map[gl], NEAR[0],NEAR[1], gx,gy, idx_map_w[gl])

    route_log.append((name, R, lane_of[name], n_vias))

for name,R,lane,nv in route_log:
    print(f"{name:<12} lane={lane:<3} R={R:6.1f} vias={nv}")

# ---- VDD near-core power distribution: 4x M1 2.6um branches from each core
# VDD row rail (x=810) into a shared 10um M2 vertical bus (x=825), which then
# hands off (via the automatic entry-via inside connect_core_to_gio_private,
# called further below) to VDD's private-radius route to its GIO pad.
cur_net[0] = "VDD"
for ry in VDD_ROWS:
    wire(m1_idx, 810.0, ry, VDD_BRANCH_STOP_X, ry, VDD_BRANCH_W)  # M1 branch: row rail -> via
    via(VDD_BRANCH_VIA_X, ry, VDD_VIA_PAD)                  # M1 branch -> M2 bus
wire(m2_idx, VDD_BUS_X, min(VDD_ROWS), VDD_BUS_X, max(VDD_ROWS), VDD_BUS_W)  # M2 bus
print(f"VDD bus: x={VDD_BUS_X} y=[{min(VDD_ROWS)},{max(VDD_ROWS)}] w={VDD_BUS_W}, "
      f"{len(VDD_ROWS)} branches w={VDD_BRANCH_W}")

# ---- VSS wide left-side power spine (user request): 10um M2 bus on the LEFT
# edge collecting all 4 core GND rows via 2.6um M1 branches. Its exit point
# is fed into the standard per-net ring-routing loop above via the "VSS"
# NETS entry itself (core-side point = (VSS_BUS_X, 100), a point along this
# very bus), which routes it the rest of the way to the (-925,5) M2PIN pin
# using the same lane-packing/DRC-safe machinery as every other net.
GND_ROWS      = [-101.2, 206.6, 471.2, 698.0]   # assembled y of the 4 core GND row rails
VSS_BUS_X     = -825.0
VSS_BUS_W     = 10.0
VSS_BRANCH_W  = 2.6
VSS_BRANCH_STOP_X = -823.0
VSS_BRANCH_VIA_X  = -822.0
VSS_VIA_PAD   = 3.4

cur_net[0] = "VSS"
for ry in GND_ROWS:
    wire(m1_idx, -810.0, ry, VSS_BRANCH_STOP_X, ry, VSS_BRANCH_W)  # M1 branch: row rail -> via
    via(VSS_BRANCH_VIA_X, ry, VSS_VIA_PAD)                          # M1 branch -> M2 bus
wire(m2_idx, VSS_BUS_X, min(GND_ROWS), VSS_BUS_X, max(GND_ROWS), VSS_BUS_W)  # M2 bus

print(f"VSS left spine: x={VSS_BUS_X} y=[{min(GND_ROWS)},{max(GND_ROWS)}] w={VSS_BUS_W}, "
      f"{len(GND_ROWS)} branches w={VSS_BRANCH_W}; fed into VSS ring route -> (-925,5) pin")

# ---- VDD main net (RIGHT-edge core bus -> TOP-edge pad ~100,925): routed at
# a dedicated PRIVATE radius instead of through the shared lane pool. (In
# round 2 this same private route was needed by VSS, for the same reason --
# the VDD/VSS label swap moved this long RIGHT-to-TOP sweep from VSS to
# VDD, but the geometry problem is identical, so the same fix applies.)
# VDD_PRIVATE_R=834 sits in the genuinely empty gap between the VDD/VSS
# buses (x/y up to 830) and the DIS chain's own band (DIS_R=840, whose real
# footprint -- wire + via pads -- extends to ~838.3 with the required 2.0um
# M2.S1 margin, so anything above 838 is unsafe). 834 leaves ~2.3um clear on
# both sides (2.0um min), verified via DRC + the net-to-net short check.
def connect_core_to_gio_private(name, px,py,ce,cl, gx,gy,ge,gl, R, fd=None, wide_first_w=None, wide_last_w=None):
    cur_net[0] = name
    idx_map = {"M1": m1_idx, "M2": m2_idx}
    C = project_to_R(px,py,ce,R)
    D = project_to_R(gx,gy,ge,R)
    NEAR = project_to_R(gx,gy,ge,NEAR_R)
    s1 = perimeter_s(px,py,ce,R); s2 = perimeter_s(gx,gy,ge,R)
    corners = ring_waypoints(s1,s2,R,fd)
    ring_path = [(px,py), C] + corners + [D, NEAR]
    ring_seg_layers = [seg_layer(ring_path[k], ring_path[k+1]) for k in range(len(ring_path)-1)]

    n_vias = 0
    if cl != ring_seg_layers[0]:
        via(px,py); n_vias += 1
    for k in range(len(ring_path)-1):
        a, b = ring_path[k], ring_path[k+1]
        L = ring_seg_layers[k]
        # only the FIRST segment (the short, purely-local core-exit hop) may
        # be widened -- widening any later segment risks colliding with
        # shared-pool neighbor lanes that pass through the same territory,
        # exactly as found earlier for VDD's old long route.
        w = wide_first_w if (wide_first_w and k == 0) else idx_map_w[L]
        wire(idx_map[L], a[0],a[1],b[0],b[1], w)
        if k > 0 and ring_seg_layers[k-1] != L:
            via(a[0], a[1]); n_vias += 1
    if ring_seg_layers[-1] != gl:
        via(NEAR[0], NEAR[1]); n_vias += 1
    wire(idx_map[gl], NEAR[0],NEAR[1], gx,gy, wide_last_w if wide_last_w else idx_map_w[gl])
    return n_vias

VDD_PRIVATE_R = 834.0
nv = connect_core_to_gio_private("VDD", 828.0,758.0,"RIGHT","M2",
                                  100.0,925.0,"TOP","M1", VDD_PRIVATE_R,
                                  wide_first_w=10.0)
print(f"VDD (private) R={VDD_PRIVATE_R} vias={nv}")

# (VDD_SPINE removed -- see NETS comment above; it targeted the real
# (200,1040) bond-pad flash, which the user asked not to connect to.)

# ---- DIS chain drawing: unlike the NETS-dict nets above (one core-side point
# that's free to route, one real GIO pin needing NEAR_R tapering), every DIS
# link has TWO real GIO pins, so both ends need the native-layer taper.
def connect_gio_to_gio(name, A, B, R):
    Ax,Ay,Ae,Al = A
    Bx,By,Be,Bl = B
    cur_net[0] = name
    idx_map = {"M1": m1_idx, "M2": m2_idx}
    NEAR_A = project_to_R(Ax,Ay,Ae,NEAR_R)
    NEAR_B = project_to_R(Bx,By,Be,NEAR_R)
    C = project_to_R(Ax,Ay,Ae,R)
    D = project_to_R(Bx,By,Be,R)
    s1 = perimeter_s(Ax,Ay,Ae,R); s2 = perimeter_s(Bx,By,Be,R)
    corners = ring_waypoints(s1,s2,R,None)
    ring_path = [NEAR_A, C] + corners + [D, NEAR_B]
    ring_seg_layers = [seg_layer(ring_path[k], ring_path[k+1]) for k in range(len(ring_path)-1)]

    n_vias = 0
    wire(idx_map[Al], Ax,Ay, NEAR_A[0],NEAR_A[1], idx_map_w[Al])  # pin A -> NEAR_A, native layer
    if Al != ring_seg_layers[0]:
        via(NEAR_A[0], NEAR_A[1]); n_vias += 1

    for k in range(len(ring_path)-1):
        a, b = ring_path[k], ring_path[k+1]
        L = ring_seg_layers[k]
        wire(idx_map[L], a[0],a[1],b[0],b[1], idx_map_w[L])
        if k > 0 and ring_seg_layers[k-1] != L:
            via(a[0], a[1]); n_vias += 1

    if ring_seg_layers[-1] != Bl:
        via(NEAR_B[0], NEAR_B[1]); n_vias += 1
    wire(idx_map[Bl], NEAR_B[0],NEAR_B[1], Bx,By, idx_map_w[Bl])  # NEAR_B -> pin B, native layer
    return n_vias

for name, A, B in DIS_LINKS:
    nv = connect_gio_to_gio(name, A, B, DIS_R)
    print(f"{name:<14} R={DIS_R:6.1f} vias={nv}")

import json
with open(OUT_GDS.replace(".gds", "_net_shapes.json"), "w") as f:
    json.dump(NET_SHAPES, f)

layout.write(OUT_GDS)
print("\nwrote", OUT_GDS)

