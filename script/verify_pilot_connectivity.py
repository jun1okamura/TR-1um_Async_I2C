"""
verify_pilot_connectivity.py

Connectivity verification for the top-margin channel pilot routing
(route_channel_pilot.py). Extracts the ACTUAL electrical connectivity from
the drawn M1/V1/M2 shapes in the routed GDS (not from our own bookkeeping)
and checks it against the intended net membership (pilot_pin_map.json,
written by route_channel_pilot.py) for all 32 row-3-internal nets:

  1. Build the merged M1 region and the merged M2 region (each split into
     individual polygons/components).
  2. For every V1 via shape, find which M1 component and which M2
     component it overlaps, and union those two components together
     (a via is the only thing that electrically joins the M1 and M2
     layers -- shapes that merely cross on different layers with no via
     are NOT connected, unlike a naive flat union would assume).
  3. For each net's each pin, locate the M1 component containing its known
     via anchor point (from pilot_pin_map.json) and map it to its final
     union-find root.
  4. PASS conditions: (a) every pin of a given net resolves to the SAME
     root as every other pin of that net, and (b) no root is shared by
     pins from two DIFFERENT nets (which would mean an unintended short).

Run after route_channel_pilot.py (which writes both the routed GDS and
pilot_pin_map.json):
    python3 script/route_channel_pilot.py
    python3 script/verify_pilot_connectivity.py
"""
import json
import klayout.db as db

GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_pilot.gds"
PIN_MAP_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/pilot_pin_map.json"

M1_LAYER = (13, 0)
V1_LAYER = (19, 0)
M2_LAYER = (20, 0)


def main():
    pin_map = json.load(open(PIN_MAP_JSON))

    layout = db.Layout()
    layout.read(GDS)
    dbu = layout.dbu
    top = layout.cell("i2c_slave_async_layout")
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)

    # Limit the scan to row3 + the channel above it (where all our routing
    # lives) for speed -- everything relevant is within y in [0, 610].
    scan = db.Box(0, 0, int(round(1800.0 / dbu)), int(round(610.0 / dbu)))

    m1_region = db.Region(top.begin_shapes_rec_touching(m1_idx, scan)).merged()
    m2_region = db.Region(top.begin_shapes_rec_touching(m2_idx, scan)).merged()
    v1_region = db.Region(top.begin_shapes_rec_touching(v1_idx, scan)).merged()

    m1_polys = list(m1_region.each())
    m2_polys = list(m2_region.each())
    print(f"{len(m1_polys)} M1 components, {len(m2_polys)} M2 components, {v1_region.count()} V1 vias (in scan area)")

    # Union-Find over ("M1", idx) / ("M2", idx) component keys.
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

    # Index M1/M2 polygons by a coarse spatial bucket for faster lookup
    # (this scan area + pin/via count is small, ~1-2k shapes, so a simple
    # per-via linear bbox-touch scan is already fast enough -- no bucketing
    # needed in practice, kept simple).
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
        # also union multiple M1 (or M2) hits under the same via together,
        # in case a via straddles two touching-but-separate polygons
        for i in m1_hits[1:]:
            union(("M1", m1_hits[0]), ("M1", i))
        for j in m2_hits[1:]:
            union(("M2", m2_hits[0]), ("M2", j))

    def locate_m1(x_um, y_um):
        xi, yi = int(round(x_um / dbu)), int(round(y_um / dbu)),
        probe = db.Region(db.Box(xi - 2, yi - 2, xi + 2, yi + 2))
        for i, p in enumerate(m1_polys):
            if p.bbox().left - 5 <= xi <= p.bbox().right + 5 and p.bbox().bottom - 5 <= yi <= p.bbox().top + 5:
                if probe.interacting(db.Region(p)).count() > 0:
                    return i
        return None

    net_roots = {}
    problems = []
    root_to_net = {}
    for net, pins in pin_map.items():
        roots_seen = set()
        for instname, pinname, vx, vy in pins:
            idx = locate_m1(vx, vy)
            if idx is None:
                problems.append(f"PIN NOT FOUND ON M1: net={net} {instname}.{pinname} at ({vx:.2f},{vy:.2f})")
                continue
            root = find(("M1", idx))
            roots_seen.add(root)
            if root in root_to_net and root_to_net[root] != net:
                problems.append(f"SHORT SUSPECTED: net={net} pin {instname}.{pinname} "
                                 f"shares a component with net={root_to_net[root]}")
            root_to_net[root] = net
        net_roots[net] = roots_seen
        if len(roots_seen) > 1:
            problems.append(f"NET SPLIT (not fully connected): net={net} resolves to {len(roots_seen)} "
                             f"separate components: {roots_seen}")

    print(f"\nChecked {len(pin_map)} nets, {sum(len(v) for v in pin_map.values())} pins total.")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S) FOUND:")
        for p in problems:
            print(" -", p)
    else:
        print("\nALL NETS FULLY CONNECTED, NO SHORTS DETECTED. Connectivity verification PASSED.")


if __name__ == "__main__":
    main()
