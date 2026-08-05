"""
plan_placement.py

Computes a standard-cell row placement plan for i2c_slave_async_net.v against
the real TR-1um_STDCELL.gds cell library, subject to:

  - fixed row width ROW_WIDTH_UM (core width), minimizing row count (height)
  - SCL/SDA(in/oe)/RST_N pins escape on the LEFT block edge; everything else
    (tx_data/rx_data/rx_valid/addr_match/rw/busy/VDD/GND) escapes on the
    RIGHT block edge -- cells are biased left/right by graph distance (in
    hops over the instance-adjacency graph) to whichever port group they are
    electrically closer to, to shorten the average wire length to the
    correct edge.

This module exposes compute_rows(), used directly by gen_gds_placement.py
(no intermediate pickle file -- re-running gen_gds_placement.py regenerates
this placement from source every time).

Run standalone for a text report:
    python3 script/plan_placement.py
"""
import re
import os
from collections import defaultdict, deque

import klayout.db as db

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"
GDS_LIB = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/libraries/TR-1um_STDCELL.gds"

ROW_WIDTH_UM = 1800.0
# Total cell width, measured on the real prBoundary (235/0) abutment box
# (not the padded full cell.bbox()), is ~5621um -> minimum row count at
# 1800um width is ceil(5621/1800) = 4 (was mistakenly computed as 5 rows
# when using the padded full bbox width).
NROWS = 4

# Block-boundary pin sides (see design_notes.md section 12/13).
LEFT_PORTS = {"scl", "sda_in", "rst_n", "sda_oe"}
RIGHT_PORTS = (
    {"rx_valid", "addr_match", "rw", "busy"}
    | {f"tx_data[{i}]" for i in range(8)}
    | {f"rx_data[{i}]" for i in range(8)}
)


def _parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins


PR_LAYER = (235, 0)  # prBoundary -- the real abutment/placement boundary.
# NOTE: cell.bbox() (all layers) is NOT the abutment box: it includes a
# uniform 6.3um guard-band/well-tap overhang on both left and right (meant to
# overlap into the neighboring cell when rows/columns are correctly abutted
# at the prBoundary edges), plus an asymmetric 1.3um/6.3um vertical overhang.
# VDD/GND pin labels sit exactly on the prBoundary top/bottom edge (y=55.0 /
# y=0.0), confirming prBoundary -- not the full bbox -- is the real cell
# height/width to abut against.


def _load_cell_widths():
    """Real cell widths (um) and row height (um), read from the prBoundary
    (235/0) layer of the actual GDS library -- this is the true abutment
    box, not the full (all-layer) cell.bbox()."""
    layout = db.Layout()
    layout.read(GDS_LIB)
    dbu = layout.dbu
    pr_idx = layout.layer(*PR_LAYER)
    cell_width = {}
    row_height = None
    for c in layout.each_cell():
        pr_bbox = db.Region(c.begin_shapes_rec(pr_idx)).bbox()
        if pr_bbox.width() == 0:
            continue
        cell_width[c.name] = pr_bbox.width() * dbu
        if c.name in ("INV_X1", "NOR2", "NAND2"):
            row_height = pr_bbox.height() * dbu
    return cell_width, row_height


def _parse_netlist():
    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: _parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

    src = open(NET_FILE).read()
    port_width = {}
    port_dir = {}
    for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        kind, _, msb, lsb, name = m.groups()
        port_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
        port_dir[name] = kind
    wire_width = {}
    for m in re.finditer(r'^\s*wire\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        _, msb, lsb, name = m.groups()
        wire_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
    width_of = {}
    width_of.update(wire_width)
    width_of.update(port_width)

    instances = []
    for m in re.finditer(r'\n\s*(\w+)\s+(\w+)\s*\(\s*(.*?)\)\s*;', src, re.S):
        typ, name, body = m.groups()
        if typ not in sym_pins:
            continue
        conns = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([^()]*?)\s*\)', body):
            pin, expr = pm.groups()
            conns[pin] = expr.strip()
        instances.append((typ, name, conns))

    assigns = []
    for m in re.finditer(r'assign\s+(.+?)\s*=\s*(.+?);', src):
        lhs, rhs = m.groups()
        if '{' in lhs or '{' in rhs or "'" in rhs:
            continue
        assigns.append((lhs.strip(), rhs.strip()))

    return sym_pins, width_of, instances, assigns


def _canon_fn(width_of, instances, assigns):
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

    def expand(expr):
        m = re.match(r'^(\w+)\[(\d+)\]$', expr)
        if m:
            return [f"{m.group(1)}[{m.group(2)}]"]
        m = re.match(r'^(\w+)$', expr)
        if m:
            w = width_of.get(m.group(1), 1)
            return [f"{m.group(1)}[{i}]" for i in range(w)] if w > 1 else [m.group(1)]
        return None

    for lhs, rhs in assigns:
        lb, rb = expand(lhs), expand(rhs)
        if lb is None or rb is None or len(lb) != len(rb):
            continue
        for a, b in zip(lb, rb):
            union(a, b)

    all_keys = set()
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            all_keys.add(expr)
    for k in all_keys:
        find(k)

    return find, parent


def compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM, verbose=False):
    """Returns (rows, cell_width, row_height) where rows is a list of nrows
    lists of (instance_name, cell_type, width_um), left-to-right physical
    reading order within each row (row 0 = bottom, ascending upward)."""
    cell_width, row_height = _load_cell_widths()
    sym_pins, width_of, instances, assigns = _parse_netlist()
    instmap = {name: (typ, conns) for typ, name, conns in instances}
    find, parent = _canon_fn(width_of, instances, assigns)

    def canon(expr):
        return find(expr)

    net_members = defaultdict(list)
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':  # VDD/GND: not useful for L/R graph distance
                continue
            net_members[canon(expr)].append(name)

    adj = defaultdict(set)
    for net, members in net_members.items():
        members = list(set(members))
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                adj[members[i]].add(members[j])
                adj[members[j]].add(members[i])

    root_keys = defaultdict(set)
    for k in list(parent.keys()):
        root_keys[find(k)].add(k)

    left_seeds, right_seeds = set(), set()
    for net, members in net_members.items():
        keys = root_keys.get(net, {net})
        if any(k in LEFT_PORTS for k in keys):
            left_seeds.update(members)
        if any(k in RIGHT_PORTS for k in keys):
            right_seeds.update(members)

    def bfs(seeds):
        dist = {s: 0 for s in seeds}
        q = deque(seeds)
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    q.append(v)
        return dist

    dist_left = bfs(left_seeds)
    dist_right = bfs(right_seeds)
    maxd = max(list(dist_left.values()) + list(dist_right.values()) + [1])

    scores = {}
    for typ, name, conns in instances:
        dl = dist_left.get(name, maxd + 1)
        dr = dist_right.get(name, maxd + 1)
        scores[name] = dl - dr  # negative => close to LEFT seeds, positive => close to RIGHT seeds

    order = sorted(instmap.keys(), key=lambda n: (scores[n], n))

    total_w = sum(cell_width[instmap[n][0]] for n in order)
    target = total_w / nrows

    rows = [[] for _ in range(nrows)]
    row_w = [0.0] * nrows
    ri = 0
    for name in order:
        typ = instmap[name][0]
        w = cell_width[typ]
        if rows[ri] and row_w[ri] + w > target and ri < nrows - 1:
            ri += 1
        rows[ri].append((name, typ, w))
        row_w[ri] += w

    if verbose:
        print(f"row height: {row_height} um")
        print(f"total cell width: {total_w:.1f} um, target/row: {target:.1f} um")
        print(f"rows: {nrows}, core: {row_width_um} x {nrows * row_height:.1f} um\n")
        for i in range(nrows):
            direction = "L->R" if i % 2 == 0 else "R->L (mirrored)"
            print(f"--- row {i} ({direction}), used {row_w[i]:.1f}/{row_width_um} um "
                  f"({100 * row_w[i] / row_width_um:.1f}%), {len(rows[i])} cells ---")
            print("  " + " ".join(t for _n, t, _w in rows[i]))

    return rows, cell_width, row_height


if __name__ == "__main__":
    compute_rows(verbose=True)
