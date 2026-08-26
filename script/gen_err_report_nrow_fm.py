"""
gen_err_report_nrow_fm.py

Review copy of the routed nrow_fm GDS with non-fab ERR layers marking
the two known-outstanding issue classes (per design_notes.md 38.6):

  - (253,0) ERR_SHORT_GEOM: the actual merged M1/M2/V1 polygon(s) of
    every connectivity component that verify_connectivity_nrow_fm.py's
    Union-Find found shared by more than one net (i.e. the literal
    shorted wire). This is the most direct "here is the short" marker.
  - (253,1) ERR_SHORT_PIN: a marker + net-name label at every pin of
    every net implicated in a short (both sides of each conflicting
    pair), so the two full nets can be traced visually in KLayout.
  - (253,2) ERR_UNCONNECTED_PIN: a marker + net-name label at every
    "stub" net's single pin -- a net with fewer than 2 real M2 pins in
    the placement, which route_channels_nrow_fm.py's pass 1/2 loops
    never touch at all (no via, no wire). Nets that ARE top-level
    module ports (rst_n, scl, sda_in, tx_data[*], ...) are expected to
    have only one internal pin (the other "pin" is the chip I/O pad,
    outside this layout's scope) and are marked with a separate label
    prefix "PORT:" so they are visually distinguishable from stub nets
    that are NOT ports (genuinely suspicious -- 24 of the 31 stubs).
  - (253,3) ERR_SHORT_POINT: the exact overlap polygon(s) where two
    shorted nets' M2 stub/M1 trunk geometry physically coincides,
    reconstructed net-by-net (not from the merged GDS region, which
    can no longer tell the two nets apart once they've physically
    touched).
  - (253,4) ERR_FORCE_JOG: the M1 run + both via_1 endpoints of every
    jog route_channels_nrow_fm.py's FORCE_JOG_NETS pass actually
    inserted (design_notes 38.13), labeled JOG-FROM:/JOG-TO:net:
    inst.pin -- lets jog placement be visually cross-checked against
    the (253,3) overlaps that remain.

Ground truth:
  - Shorts: re-run of verify_connectivity_nrow_fm.py's algorithm, kept
    in-process so both sides of every conflicting pair are available
    (the standalone script only prints one side).
  - Unconnected pins: net_pins rebuilt from placement_nrow_fm.json with
    the exact same logic route_channels_nrow_fm.py uses, filtered to
    nets with <2 M2 pins (route_channels_nrow_fm.py's `stub_nets`).

Usage:
    python3 gen_err_report_nrow_fm.py
"""
import json
import re
import sys
from collections import defaultdict

import klayout.db as db

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm.json"
PIN_MAP_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
NET_SHAPES_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/net_shapes_nrow_fm.json"
FORCE_JOG_EVENTS_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/force_jog_events_nrow_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_with_err.gds"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"
TOP_CELL = "i2c_slave_async_nrow_fm"

M1_LAYER = (13, 0)
V1_LAYER = (19, 0)
M2_LAYER = (20, 0)

ERR_SHORT_GEOM = (253, 0)
ERR_SHORT_PIN = (253, 1)
ERR_UNCONNECTED_PIN = (253, 2)
ERR_SHORT_POINT = (253, 3)
ERR_FORCE_JOG = (253, 4)

MARK = 6.0

# must match route_channels_nrow_fm.py
PAD_HALF = 3.4 / 2.0
M1_TRUNK_HALF = 1.8 / 2.0


def top_level_ports(net_file=NET_FILE):
    """v34 (design_notes, this session, user question re: sda_oe_r
    mislabeled OPEN): a net whose only real connection is a top-level
    OUTPUT port is, for stub-classification purposes, exactly like the
    9 nets that already get the "PORT:" label -- its "other pin" is the
    chip's off-chip I/O pad, outside this layout's scope, not a routing
    defect. But Yosys emits `assign <port> = <internal_wire>;` for a
    registered output (the DFF drives an internal wire, e.g.
    `sda_oe_r`, and the port itself is just an alias) -- the LAYOUT's
    net names are the internal wire names, which never literally match
    the bare port name this function used to look for, so those nets
    were falling through to the generic "OPEN:" (suspicious) bucket
    even though they're structurally identical to a real port net.
    Confirmed via netlist audit: `sda_oe_r` appears exactly where an
    `assign sda_oe = sda_oe_r;` connects it straight to the `output
    sda_oe` port declared above, with no other reader/driver.

    Fix: also collect every plain `wire` declaration (name -> bit
    width), then scan for simple (non-concatenation) `assign LHS =
    RHS;` statements. If LHS resolves to a port (scalar or vector,
    matching bit-for-bit), RHS is added to `ports` too -- scalar-to-
    scalar directly, vector-to-vector bit-by-bit (assuming equal
    width, which is what Yosys always emits for a straight passthrough
    assign). Concatenation/bit-slice assigns (braces or explicit `[..]`
    on either side) are deliberately left alone -- those aren't a
    simple 1:1 port alias and are out of scope here."""
    src = open(net_file).read()

    def collect_widths(kind):
        widths = {}
        for m in re.finditer(r'^\s*' + kind + r'\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
            _, msb, lsb, name = m.groups()
            widths[name] = (int(lsb), int(msb)) if msb else None
        return widths

    port_widths = collect_widths('(?:input|output)')
    wire_widths = collect_widths('wire')

    ports = set()
    for name, span in port_widths.items():
        if span is None:
            ports.add(name)
        else:
            lsb, msb = span
            for i in range(lsb, msb + 1):
                ports.add(f"{name}[{i}]")

    def width_of(name):
        if name in port_widths:
            return port_widths[name]
        if name in wire_widths:
            return wire_widths[name]
        return None  # not declared here (e.g. VDD/GND, or unknown) -- skip

    all_widths = dict(wire_widths)
    all_widths.update(port_widths)
    for m in re.finditer(r'^\s*assign\s+(\w+)\s*=\s*(\w+)\s*;\s*$', src, re.M):
        lhs, rhs = m.groups()
        if lhs not in port_widths:
            continue  # only care about assigns that alias a real port
        rhs_span = width_of(rhs)
        lhs_span = port_widths[lhs]
        if lhs_span is None:
            ports.add(rhs)
        elif rhs_span is not None and rhs_span[1] - rhs_span[0] == lhs_span[1] - lhs_span[0]:
            lsb, msb = lhs_span
            rlsb, _ = rhs_span
            for i in range(lsb, msb + 1):
                ports.add(f"{rhs}[{i - lsb + rlsb}]")
    return ports


def rebuild_net_pins(placement_json=PLACEMENT_JSON, ch_heights=None):
    """Same construction as route_channels_nrow_fm.py's net_pins dict.

    v35 (design_notes, this session, user report: (253,2) stub-pin
    markers landing inside a CHANNEL instead of a row): `ch_heights`
    used to be a value hardcoded INSIDE this function
    ([90.0, 260.0, 240.0, 224.0, 100.0], a leftover from the design's
    original TRACK_PITCH=4.0 CH_HEIGHTS, pre-dating this session's
    TRACK_PITCH=4.0->5.4 change and the resulting CH_HEIGHTS_TARGET
    resnap). `main()` already accepted a `ch_heights` argument and
    assigned it to a module-level `global CH_HEIGHTS` specifically so
    callers (like run_route_v7_from_scratch.py) could keep this in
    sync with whatever heights the actual routing run used -- but this
    function never read that global at all, since its own hardcoded
    local variable of the SAME NAME silently shadowed it. Every row's
    computed Y offset (`row_y0`) was therefore built from stale,
    pre-resnap channel heights no matter what was passed to `main()`,
    silently mis-locating every stub-net pin marker this whole session
    (confirmed via audit: tx_data[0]'s reported y=444.4 falls inside
    channel 1's real range [196.4,657.4], not inside its actual row --
    row1 is really at [657.4,722.2] under the current CH_HEIGHTS,
    but was computed as [414.8,479.6] under the stale hardcoded ones).
    Routed-net markers were NOT affected (`net_pin_locs`, used for the
    (253,1) implicated-net-pin highlight, comes from `pin_map` -- the
    router's own already-correct final positions -- not from this
    function); only (253,2) unconnected/stub-pin markers (nets with
    <2 pins, which `pin_map` never contains at all) used this stale
    path. Now `ch_heights` is a real parameter with no shadowing, and
    `main()` passes its own `ch_heights` straight through instead of
    routing it through an unused module-level global."""
    placement = json.load(open(placement_json))
    rows = placement["rows"]
    row_h = placement["row_height"]
    n_rows = len(rows)
    if ch_heights is None:
        # CH_HEIGHTS must match route_channels_nrow_fm.py / gen_placement_gds_nrow_fm.py
        ch_heights = [90.0, 260.0, 240.0, 224.0, 100.0]
    CH_HEIGHTS = ch_heights
    assert len(CH_HEIGHTS) == n_rows + 1
    row_y0 = []
    y = 0.0
    for i in range(n_rows):
        y += CH_HEIGHTS[i]
        row_y0.append(y)
        y += row_h

    net_pins = defaultdict(list)
    for r, row_insts in enumerate(rows):
        yoff = row_y0[r]
        for inst in row_insts:
            for pname, pinfo in inst["pins"].items():
                if pinfo["use"] in ("POWER", "GROUND"):
                    continue
                for layer, x0, y0, x1, y1 in pinfo["rects"]:
                    if layer != "M2":
                        continue
                    net_pins[pinfo["net"]].append(
                        (r, inst["name"], pname, (x0 + x1) / 2.0, (y0 + y1) / 2.0 + yoff))
    return net_pins


def net_region(net, pin_map, pin_center, um, net_shapes_log=None):
    """Build net's own M1/M2 region for overlap testing against another
    net's region.

    Ground truth (preferred): `net_shapes_log[net]` is a list of
    ("M1"|"M2", x0,y0,x1,y1) boxes recorded DIRECTLY by
    route_channels_nrow_fm.py at draw time (v4.1), so it captures
    every segment -- trunk, stub, AND jog/spine dogleg alike -- with
    perfect fidelity.

    Fallback (if the log is missing/stale for this net): reconstruct
    just the trunk+stub geometry from pin_map (net -> [(instname,
    pinname,via_x,via_y=track_y), ...]) + pin_center (net,instname,
    pinname) -> (pin's own x,y from placement). This misses jog/spine
    dogleg segments, so shorts routed through those won't be found.

    `um` converts a float um coordinate to database units (dbu-matched
    to the loaded layout).
    """
    region = db.Region()
    if net_shapes_log is not None and net in net_shapes_log:
        for kind, x0, y0, x1, y1 in net_shapes_log[net]:
            region.insert(db.Box(um(x0), um(y0), um(x1), um(y1)))
        return region
    boxes = []
    by_track = defaultdict(list)
    for inst, pname, vx, vy in pin_map.get(net, []):
        px, py = pin_center.get((net, inst, pname), (vx, vy))
        y0, y1 = min(py, vy), max(py, vy)
        if y1 - y0 < 1e-6:
            y1 = y0 + 1e-6
        boxes.append((vx - PAD_HALF, y0, vx + PAD_HALF, y1))
        by_track[vy].append(vx)
    for ty, xs in by_track.items():
        boxes.append((min(xs), ty - M1_TRUNK_HALF, max(xs), ty + M1_TRUNK_HALF))
    for x0, y0, x1, y1 in boxes:
        region.insert(db.Box(um(x0), um(y0), um(x1), um(y1)))
    return region


def main(placement_json=PLACEMENT_JSON, pin_map_json=PIN_MAP_JSON, net_shapes_json=NET_SHAPES_JSON,
         force_jog_events_json=FORCE_JOG_EVENTS_JSON, in_gds=IN_GDS, out_gds=OUT_GDS,
         net_file=NET_FILE, ch_heights=None, txt_path=None):
    net_pins = rebuild_net_pins(placement_json, ch_heights=ch_heights)
    pin_center = {}  # (net,instname,pinname) -> (x,y), pin's own placement coordinate
    for net, pads in net_pins.items():
        for r, instname, pname, cx, cy in pads:
            pin_center[(net, instname, pname)] = (cx, cy)
    ports = top_level_ports(net_file)
    try:
        net_shapes_log = json.load(open(net_shapes_json))
        print(f"loaded net_shapes log: {sum(len(v) for v in net_shapes_log.values())} boxes, "
              f"{len(net_shapes_log)} nets")
    except FileNotFoundError:
        net_shapes_log = None
        print("net_shapes log not found -- falling back to pin-based reconstruction for all nets")
    stub_nets = {n: p for n, p in net_pins.items() if len(p) < 2}
    print(f"{len(net_pins)} nets total, {len(stub_nets)} stub (unrouted, <2 M2 pins) nets")
    stub_port = {n: p for n, p in stub_nets.items() if n in ports}
    stub_nonport = {n: p for n, p in stub_nets.items() if n not in ports}
    print(f"  {len(stub_port)} are top-level module ports (expected: other end is off-chip)")
    print(f"  {len(stub_nonport)} are NOT ports (genuinely suspicious, worth a closer look)")

    pin_map = json.load(open(pin_map_json))

    try:
        force_jog_events = json.load(open(force_jog_events_json))
        print(f"loaded force_jog_events log: {len(force_jog_events)} jog(s)")
    except FileNotFoundError:
        force_jog_events = []
        print("force_jog_events log not found -- (253,4) layer will be empty")

    layout = db.Layout()
    layout.read(in_gds)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)

    m1_region = db.Region(top.begin_shapes_rec(m1_idx)).merged()
    m2_region = db.Region(top.begin_shapes_rec(m2_idx)).merged()
    v1_region = db.Region(top.begin_shapes_rec(v1_idx)).merged()
    m1_polys = list(m1_region.each())
    m2_polys = list(m2_region.each())
    print(f"{len(m1_polys)} M1 components, {len(m2_polys)} M2 components, {v1_region.count()} V1 vias")

    parent = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for via in v1_region.each():
        vbox = via.bbox()
        vreg = db.Region(via)
        m1_hits = [i for i, p in enumerate(m1_polys) if p.bbox().overlaps(vbox) or p.bbox().touches(vbox)]
        m1_hits = [i for i in m1_hits if vreg.interacting(db.Region(m1_polys[i])).count() > 0]
        m2_hits = [i for i, p in enumerate(m2_polys) if p.bbox().overlaps(vbox) or p.bbox().touches(vbox)]
        m2_hits = [i for i in m2_hits if vreg.interacting(db.Region(m2_polys[i])).count() > 0]
        for i in m1_hits:
            for j in m2_hits:
                union(("M1", i), ("M2", j))
        for i in m1_hits[1:]:
            union(("M1", m1_hits[0]), ("M1", i))
        for j in m2_hits[1:]:
            union(("M2", m2_hits[0]), ("M2", j))

    def locate_m1(x_um, y_um):
        xi, yi = int(round(x_um / dbu)), int(round(y_um / dbu))
        probe = db.Region(db.Box(xi - 2, yi - 2, xi + 2, yi + 2))
        for i, p in enumerate(m1_polys):
            if p.bbox().left - 5 <= xi <= p.bbox().right + 5 and p.bbox().bottom - 5 <= yi <= p.bbox().top + 5:
                if probe.interacting(db.Region(p)).count() > 0:
                    return i
        return None

    # ---------- replay verify_connectivity_nrow_fm.py, keeping both sides ----------
    root_to_net = {}
    root_to_pin = {}          # root -> (net, instname, pinname, x, y)  (the pin that FIRST claimed this root)
    conflicts = []            # (netA, pinA_info, netB, pinB_info, root)
    net_pin_locs = defaultdict(list)  # net -> [(instname, pinname, x, y), ...]  for ALL routed pins

    for net, pins in pin_map.items():
        for instname, pinname, vx, vy in pins:
            net_pin_locs[net].append((instname, pinname, vx, vy))
            idx = locate_m1(vx, vy)
            if idx is None:
                continue
            root = find(("M1", idx))
            if root in root_to_net and root_to_net[root] != net:
                conflicts.append((root_to_net[root], root_to_pin[root], net, (instname, pinname, vx, vy)))
            # match verify_connectivity_nrow_fm.py exactly: always (re)claim
            # the root for the most recently seen net, conflict or not --
            # otherwise a net with multiple pins on an already-claimed root
            # re-triggers a conflict for every one of its own pins instead
            # of just the first.
            root_to_net[root] = net
            root_to_pin[root] = (instname, pinname, vx, vy)

    print(f"\n{len(conflicts)} short(s) found (matches verify_connectivity_nrow_fm.py's count)")

    bad_roots = set()
    implicated_nets = set()
    for netA, pinA, netB, pinB in conflicts:
        implicated_nets.add(netA)
        implicated_nets.add(netB)
    # recompute bad roots (components touched by >1 implicated net) for geometry highlight
    root_nets = defaultdict(set)
    for net in implicated_nets:
        for instname, pinname, vx, vy in net_pin_locs[net]:
            idx = locate_m1(vx, vy)
            if idx is None:
                continue
            root_nets[find(("M1", idx))].add(net)
    for root, nets in root_nets.items():
        if len(nets) > 1:
            bad_roots.add(root)
    print(f"{len(bad_roots)} shared (shorted) connectivity component(s), {len(implicated_nets)} net(s) implicated")

    # ---------- draw ERR layers ----------
    err_geom_idx = layout.layer(*ERR_SHORT_GEOM)
    err_pin_idx = layout.layer(*ERR_SHORT_PIN)
    err_unconn_idx = layout.layer(*ERR_UNCONNECTED_PIN)
    err_point_idx = layout.layer(*ERR_SHORT_POINT)
    err_jog_idx = layout.layer(*ERR_FORCE_JOG)

    def um(v):
        return int(round(v / dbu))

    def mark(x, y, label, layer_idx):
        box = db.Box(um(x - MARK / 2), um(y - MARK / 2), um(x + MARK / 2), um(y + MARK / 2))
        top.shapes(layer_idx).insert(box)
        t = db.Text(label, db.Trans(um(x), um(y + MARK)))
        t.size = um(2.0)
        top.shapes(layer_idx).insert(t)

    # exact collision point per conflict: reconstruct each net's own
    # trunk+stub rectangles from pin_map/placement data (NOT the merged
    # GDS region, since once two nets' copper touches, the merged
    # region can no longer tell which polygon area belongs to which
    # net) and intersect the two nets' regions directly. This pinpoints
    # the actual X where the two M2 stubs coincide, instead of the
    # whole (potentially huge, for high-FO nets) shorted net geometry.
    collision_points = []  # (netA, netB, [(x,y,w,h), ...])
    for netA, pinA, netB, pinB in conflicts:
        regA = net_region(netA, pin_map, pin_center, um, net_shapes_log)
        regB = net_region(netB, pin_map, pin_center, um, net_shapes_log)
        overlap = regA & regB
        boxes = []
        for p in overlap.each():
            b = p.bbox()
            boxes.append((b.left * dbu, b.bottom * dbu, b.right * dbu, b.top * dbu))
            top.shapes(err_point_idx).insert(p)
        if boxes:
            cx = (boxes[0][0] + boxes[0][2]) / 2.0
            cy = (boxes[0][1] + boxes[0][3]) / 2.0
            t = db.Text(f"SHORT:{netA}<->{netB}", db.Trans(um(cx), um(cy + MARK)))
            t.size = um(2.0)
            top.shapes(err_point_idx).insert(t)
        collision_points.append((netA, netB, boxes))
    n_pinpointed = sum(1 for _, _, b in collision_points if b)
    print(f"{n_pinpointed}/{len(conflicts)} short(s) pinpointed to an exact overlap polygon "
          f"(reconstructed trunk/stub geometry vs. merged-region ambiguity for the rest)")

    # geometry highlight: copy every M1/M2 polygon belonging to a bad root
    for kind_idx, polys in (("M1", m1_polys), ("M2", m2_polys)):
        for i, p in enumerate(polys):
            if find((kind_idx, i)) in bad_roots:
                top.shapes(err_geom_idx).insert(p)

    # pin highlight: every pin of every implicated net
    for net in sorted(implicated_nets):
        for instname, pinname, vx, vy in net_pin_locs[net]:
            mark(vx, vy, f"{net}:{instname}.{pinname}", err_pin_idx)

    # unconnected pin highlight
    for net, pads in stub_nets.items():
        for r, instname, pinname, cx, cy in pads:
            prefix = "PORT:" if net in ports else "OPEN:"
            mark(cx, cy, f"{prefix}{net}:{instname}.{pinname}", err_unconn_idx)

    # FORCE_JOG_NETS jog highlight (design_notes 38.15): the M1 run +
    # both via_1 endpoints of every jog route_channels_nrow_fm.py's
    # dedicated FORCE_JOG_NETS pass actually inserted, so jog placement
    # can be visually cross-checked in KLayout against the (253,3)
    # overlap polygons that remain -- e.g. to see whether a jog landed
    # too close to the other net's own geometry, or whether some pins
    # never triggered a jog in the first place.
    for ev in force_jog_events:
        net, orig_x, clear_x, jog_y = ev["net"], ev["orig_x"], ev["clear_x"], ev["jog_y"]
        half_w = M1_TRUNK_HALF
        m1_box = db.Box(um(min(orig_x, clear_x)), um(jog_y - half_w),
                         um(max(orig_x, clear_x)), um(jog_y + half_w))
        top.shapes(err_jog_idx).insert(m1_box)
        mark(orig_x, jog_y, f"JOG-FROM:{net}:{ev['inst']}.{ev['pin']}", err_jog_idx)
        mark(clear_x, jog_y, f"JOG-TO:{net}:{ev['inst']}.{ev['pin']}", err_jog_idx)
    if force_jog_events:
        by_net = defaultdict(int)
        for ev in force_jog_events:
            by_net[ev["net"]] += 1
        print(f"FORCE_JOG_NETS jog highlight: {len(force_jog_events)} jog(s) "
              f"({dict(by_net)})")

    layout.write(out_gds)
    print("\nwrote", out_gds)
    print(f"layers: {ERR_SHORT_GEOM}=shorted metal geometry, {ERR_SHORT_PIN}=pins of implicated nets, "
          f"{ERR_UNCONNECTED_PIN}=unconnected (stub) pins (label PORT:=expected top-level port, "
          f"OPEN:=not a port, worth investigating), "
          f"{ERR_SHORT_POINT}=exact overlap polygon where the two nets' M2 stub/M1 trunk geometry "
          f"physically coincide (labeled SHORT:netA<->netB), "
          f"{ERR_FORCE_JOG}=M1 run + via_1 endpoints of every jog FORCE_JOG_NETS inserted "
          f"(labeled JOG-FROM:/JOG-TO:net:inst.pin)")

    if txt_path is None:
        txt_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/err_report_nrow_fm_details.txt"
    with open(txt_path, "w") as f:
        f.write(f"=== {len(conflicts)} SHORT(S) SUSPECTED ===\n")
        for (netA, pinA, netB, pinB), (_, _, boxes) in zip(conflicts, collision_points):
            f.write(f"net={netA} {pinA[0]}.{pinA[1]} ({pinA[2]:.2f},{pinA[3]:.2f})  <->  "
                    f"net={netB} {pinB[0]}.{pinB[1]} ({pinB[2]:.2f},{pinB[3]:.2f})\n")
            if boxes:
                for x0, y0, x1, y1 in boxes:
                    f.write(f"    overlap: X=[{x0:.2f},{x1:.2f}] Y=[{y0:.2f},{y1:.2f}]"
                            f"  (layer {ERR_SHORT_POINT} in GDS)\n")
            else:
                f.write(f"    overlap: not pinpointed by reconstructed-geometry check "
                        f"(see full blob on layer {ERR_SHORT_GEOM})\n")
        f.write(f"\n=== {len(stub_nets)} UNCONNECTED (stub) PIN(S) ===\n")
        f.write(f"-- {len(stub_port)} are top-level ports (expected, not a defect) --\n")
        for net, pads in sorted(stub_port.items()):
            for r, instname, pinname, cx, cy in pads:
                f.write(f"  PORT net={net} {instname}.{pinname} ({cx:.2f},{cy:.2f})\n")
        f.write(f"-- {len(stub_nonport)} are NOT ports (worth investigating) --\n")
        for net, pads in sorted(stub_nonport.items()):
            for r, instname, pinname, cx, cy in pads:
                f.write(f"  OPEN net={net} {instname}.{pinname} ({cx:.2f},{cy:.2f})\n")
        f.write(f"\n=== {len(force_jog_events)} FORCE_JOG_NETS JOG(S) INSERTED ===\n")
        for ev in force_jog_events:
            f.write(f"  net={ev['net']} {ev['inst']}.{ev['pin']}  "
                    f"orig_x={ev['orig_x']:.2f} -> clear_x={ev['clear_x']:.2f}  "
                    f"jog_y={ev['jog_y']:.2f}  channel={ev['channel']}  "
                    f"(layer {ERR_FORCE_JOG} in GDS)\n")
    print("wrote", txt_path)


if __name__ == "__main__":
    main()
