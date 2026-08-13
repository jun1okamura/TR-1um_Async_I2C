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

MARK = 6.0


def top_level_ports():
    src = open(NET_FILE).read()
    ports = set()
    for m in re.finditer(r'^\s*(input|output)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        _kind, _, msb, lsb, name = m.groups()
        if msb:
            for i in range(int(lsb), int(msb) + 1):
                ports.add(f"{name}[{i}]")
        else:
            ports.add(name)
    return ports


def rebuild_net_pins():
    """Same construction as route_channels_nrow_fm.py's net_pins dict."""
    placement = json.load(open(PLACEMENT_JSON))
    rows = placement["rows"]
    row_h = placement["row_height"]
    n_rows = len(rows)
    # CH_HEIGHTS must match route_channels_nrow_fm.py / gen_placement_gds_nrow_fm.py
    CH_HEIGHTS = [90.0, 180.0, 220.0, 224.0, 100.0]
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


def main():
    net_pins = rebuild_net_pins()
    ports = top_level_ports()
    stub_nets = {n: p for n, p in net_pins.items() if len(p) < 2}
    print(f"{len(net_pins)} nets total, {len(stub_nets)} stub (unrouted, <2 M2 pins) nets")
    stub_port = {n: p for n, p in stub_nets.items() if n in ports}
    stub_nonport = {n: p for n, p in stub_nets.items() if n not in ports}
    print(f"  {len(stub_port)} are top-level module ports (expected: other end is off-chip)")
    print(f"  {len(stub_nonport)} are NOT ports (genuinely suspicious, worth a closer look)")

    pin_map = json.load(open(PIN_MAP_JSON))

    layout = db.Layout()
    layout.read(IN_GDS)
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

    def um(v):
        return int(round(v / dbu))

    def mark(x, y, label, layer_idx):
        box = db.Box(um(x - MARK / 2), um(y - MARK / 2), um(x + MARK / 2), um(y + MARK / 2))
        top.shapes(layer_idx).insert(box)
        t = db.Text(label, db.Trans(um(x), um(y + MARK)))
        t.size = um(2.0)
        top.shapes(layer_idx).insert(t)

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

    layout.write(OUT_GDS)
    print("\nwrote", OUT_GDS)
    print(f"layers: {ERR_SHORT_GEOM}=shorted metal geometry, {ERR_SHORT_PIN}=pins of implicated nets, "
          f"{ERR_UNCONNECTED_PIN}=unconnected (stub) pins (label PORT:=expected top-level port, "
          f"OPEN:=not a port, worth investigating)")

    txt_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/err_report_nrow_fm_details.txt"
    with open(txt_path, "w") as f:
        f.write(f"=== {len(conflicts)} SHORT(S) SUSPECTED ===\n")
        for netA, pinA, netB, pinB in conflicts:
            f.write(f"net={netA} {pinA[0]}.{pinA[1]} ({pinA[2]:.2f},{pinA[3]:.2f})  <->  "
                    f"net={netB} {pinB[0]}.{pinB[1]} ({pinB[2]:.2f},{pinB[3]:.2f})\n")
        f.write(f"\n=== {len(stub_nets)} UNCONNECTED (stub) PIN(S) ===\n")
        f.write(f"-- {len(stub_port)} are top-level ports (expected, not a defect) --\n")
        for net, pads in sorted(stub_port.items()):
            for r, instname, pinname, cx, cy in pads:
                f.write(f"  PORT net={net} {instname}.{pinname} ({cx:.2f},{cy:.2f})\n")
        f.write(f"-- {len(stub_nonport)} are NOT ports (worth investigating) --\n")
        for net, pads in sorted(stub_nonport.items()):
            for r, instname, pinname, cx, cy in pads:
                f.write(f"  OPEN net={net} {instname}.{pinname} ({cx:.2f},{cy:.2f})\n")
    print("wrote", txt_path)


if __name__ == "__main__":
    main()
