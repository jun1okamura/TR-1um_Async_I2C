import re, os, sys
from collections import defaultdict

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
STDCELL_ABS_DIR = "/Users/okamura/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"
OUT_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/i2c_slave_async_net_routed.sch"

sys.setrecursionlimit(10000)

# ---------- 1. parse stdcell symbol pin coordinates ----------
def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                x1, y1, x2, y2, name, direction = m.groups()
                cx = (float(x1) + float(x2)) / 2
                cy = (float(y1) + float(y2)) / 2
                pins[name] = (cx, cy, direction)
    return pins

celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
sym_pins = {ct: parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

# ---------- 2. parse netlist ----------
src = open(NET_FILE).read()

port_dir = {}
port_width = {}
for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
    kind, _, msb, lsb, name = m.groups()
    w = (int(msb) - int(lsb) + 1) if msb else 1
    port_width[name] = w
    port_dir[name] = kind
top_ports_order = [p.strip() for p in re.search(r'module\s+i2c_slave_async\s*\(([^)]*)\)', src).group(1).split(',')]

wire_width = {}
for m in re.finditer(r'^\s*wire\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
    _, msb, lsb, name = m.groups()
    w = (int(msb) - int(lsb) + 1) if msb else 1
    wire_width[name] = w
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
instmap = {name: (typ, conns) for typ, name, conns in instances}
print("instances:", len(instances))

assigns = []
for m in re.finditer(r'assign\s+(.+?)\s*=\s*(.+?);', src):
    lhs, rhs = m.groups()
    if '{' in lhs or '{' in rhs or "'" in rhs:
        continue
    assigns.append((lhs.strip(), rhs.strip()))

# ---------- 3. union-find ----------
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
        name = m.group(1)
        w = width_of.get(name, 1)
        return [f"{name}[{i}]" for i in range(w)] if w > 1 else [name]
    return None

for lhs, rhs in assigns:
    lb, rb = expand(lhs), expand(rhs)
    if lb is None or rb is None or len(lb) != len(rb):
        continue
    for a, b in zip(lb, rb):
        union(a, b)

TOP_IN, TOP_OUT = [], []
for p in top_ports_order:
    w = port_width.get(p, 1)
    keys = [f"{p}[{i}]" for i in range(w)] if w > 1 else [p]
    (TOP_IN if port_dir[p] in ("input",) else TOP_OUT).extend((p, k) for k in keys)

TOP_IN_KEYS = {k for _, k in TOP_IN}
TOP_OUT_KEYS = {k for _, k in TOP_OUT}

def is_numbered(name):
    return re.match(r'^_\d+_(\[\d+\])?$', name) is not None

all_keys = set(TOP_IN_KEYS) | set(TOP_OUT_KEYS)
for typ, name, conns in instances:
    for pin, expr in conns.items():
        all_keys.add(expr)
for k in all_keys:
    find(k)
groups = defaultdict(set)
for k in list(parent.keys()):
    groups[find(k)].add(k)

def canon_label(key):
    members = groups.get(find(key), {key})
    top = [m for m in members if m in TOP_IN_KEYS or m in TOP_OUT_KEYS]
    if top:
        return sorted(top)[0]
    named = [m for m in members if not is_numbered(m)]
    if named:
        return sorted(named)[0]
    return sorted(members)[0]

# ---------- 4. build net driver/sink map (excluding VDD/GND) ----------
net_driver = {}          # canon net -> ('inst', name) or ('topin', portkey)
net_sinks = defaultdict(list)   # canon net -> [('inst', name), ...] / [('topout', portkey)]
net_driver_pin = {}       # canon net -> (kind, name, pin)  (full info for routing)
net_sink_pins = defaultdict(list)

for typ, name, conns in instances:
    for pin, (px, py, d) in sym_pins[typ].items():
        expr = conns.get(pin)
        if expr is None or d == 'inout':
            continue
        net = canon_label(expr)
        if d == 'out':
            net_driver[net] = ('inst', name)
            net_driver_pin[net] = ('inst', name, pin)
        elif d == 'in':
            net_sinks[net].append(('inst', name))
            net_sink_pins[net].append(('inst', name, pin))

for pname, key in TOP_IN:
    if pname in ('VDD', 'GND'):
        continue
    net = canon_label(key)
    net_driver[net] = ('topin', key)
    net_driver_pin[net] = ('topin', key, None)
for pname, key in TOP_OUT:
    net = canon_label(key)
    net_sinks[net].append(('topout', key))
    net_sink_pins[net].append(('topout', key, None))

# ---------- 5. levelize (longest path, cycle-safe) ----------
IN_PROGRESS = -999
level_of = {}
def compute_level(name):
    cur = level_of.get(name)
    if cur is not None and cur != IN_PROGRESS:
        return cur
    level_of[name] = IN_PROGRESS
    typ, conns = instmap[name]
    maxlvl = -1
    for pin, (px, py, d) in sym_pins[typ].items():
        if d != 'in':
            continue
        expr = conns.get(pin)
        if expr is None:
            continue
        net = canon_label(expr)
        drv = net_driver.get(net)
        if drv is None:
            continue
        if drv[0] == 'topin':
            lvl = 0
        else:
            dname = drv[1]
            dtyp = instmap[dname][0]
            if dtyp == 'DFFR':
                # a flip-flop output is a fresh source for downstream
                # combinational depth -- do NOT accumulate its own
                # D-input logic depth into fanout nodes (that logic
                # happens in the *previous* clock edge in real hardware).
                lvl = 0
            else:
                if level_of.get(dname) == IN_PROGRESS:
                    continue
                lvl = compute_level(dname)
        maxlvl = max(maxlvl, lvl)
    result = maxlvl + 1
    level_of[name] = result
    return result

for name in instmap:
    compute_level(name)

maxlevel = max(level_of.values())
print("max level:", maxlevel)
cols = defaultdict(list)
for name, lvl in level_of.items():
    cols[lvl].append(name)
for lvl in cols:
    print(" level", lvl, ":", len(cols[lvl]))

# predecessors / successors (instance-only) for barycenter ordering
preds = defaultdict(set)
succs = defaultdict(set)
for typ, name, conns in instances:
    for pin, (px, py, d) in sym_pins[typ].items():
        expr = conns.get(pin)
        if expr is None or d == 'inout':
            continue
        net = canon_label(expr)
        if d == 'in':
            drv = net_driver.get(net)
            if drv and drv[0] == 'inst':
                preds[name].add(drv[1])
        elif d == 'out':
            for sk in net_sinks.get(net, []):
                if sk[0] == 'inst':
                    succs[name].add(sk[1])

order = {}
for lvl in sorted(cols):
    for i, name in enumerate(sorted(cols[lvl])):
        order[name] = i

def reorder_column(names, ref):
    scored = []
    for n in names:
        rs = [order[r] for r in ref(n) if r in order]
        scored.append((sum(rs) / len(rs) if rs else order[n], n))
    scored.sort(key=lambda t: t[0])
    for i, (_, n) in enumerate(scored):
        order[n] = i

for it in range(4):
    if it % 2 == 0:
        for lvl in sorted(cols):
            reorder_column(cols[lvl], lambda n: preds[n])
    else:
        for lvl in sorted(cols, reverse=True):
            reorder_column(cols[lvl], lambda n: succs[n])

# ---------- 6. coordinates ----------
DX, DY = 550, 190
X0 = 900

xy = {}
for lvl in sorted(cols):
    names = sorted(cols[lvl], key=lambda n: order[n])
    for row, name in enumerate(names):
        xy[name] = (X0 + lvl * DX, row * DY)

def sym_bbox_pins(typ):
    return sym_pins[typ]

def abs_pin(name, pin):
    typ, conns = instmap[name]
    px, py, d = sym_pins[typ][pin]
    ix, iy = xy[name]
    return ix + px, iy + py, d

# top port placement: order by avg row of what they connect to
topin_order = []
for pname, key in TOP_IN:
    if pname in ('VDD', 'GND'):
        continue
    net = canon_label(key)
    sinks = [s for s in net_sinks.get(net, []) if s[0] == 'inst']
    rows = [order[s[1]] for s in sinks if s[1] in order]
    topin_order.append((sum(rows) / len(rows) if rows else 999, key))
topin_order.sort()

topout_order = []
for pname, key in TOP_OUT:
    net = canon_label(key)
    drv = net_driver.get(net)
    r = order[drv[1]] if drv and drv[0] == 'inst' and drv[1] in order else 999
    topout_order.append((r, key))
topout_order.sort()

TOPIN_X = X0 - DX
maxrow_level0 = max((len(cols.get(0, [1])), 1))
topin_xy = {}
for i, (_, key) in enumerate(topin_order):
    topin_xy[key] = (TOPIN_X, i * DY)

TOPOUT_X = X0 + (maxlevel + 1) * DX
topout_xy = {}
for i, (_, key) in enumerate(topout_order):
    topout_xy[key] = (TOPOUT_X, i * DY)

# ---------- 7. emit schematic ----------
lines = []
lines.append("v {xschem version=3.4.4 file_version=1.2\n}")
lines.append("G {}")
lines.append("K {}")
lines.append("V {}")
lines.append("S {}")
lines.append("E {}")

def add_wire(x1, y1, x2, y2, lab=None):
    x1, y1, x2, y2 = round(x1), round(y1), round(x2), round(y2)
    if lab:
        lines.append(f"N {x1} {y1} {x2} {y2} {{\nlab={lab}}}")
    else:
        lines.append(f"N {x1} {y1} {x2} {y2} {{}}")

# place instances + VDD/GND label pins
# NOTE: a bare `lab=` property on a plain wire is NOT an xschem net-label
# mechanism (xschem connectivity is purely geometric -- touching wire/pin
# endpoints; `lab=` on a wire is not read by the netlister at all). This
# was confirmed empirically: an earlier version of this script used bare
# wire `lab=` stubs for power pins and an xschem-exported SPICE netlist
# showed every pin as its own isolated net. The correct mechanism is a
# devices/lab_pin.sym instance -- xschem documents that multiple
# lab_pin.sym instances sharing the same `lab` value are shorted together
# regardless of physical routing. (Signal nets below are NOT affected by
# this bug -- they are connected via real, physically-touching routed wire
# segments, which is xschem's normal/primary connectivity mechanism.)
_lab_counter = [0]
for typ, name, conns in instances:
    ix, iy = xy[name]
    sym_ref = f"{STDCELL_ABS_DIR}/{typ}.sym"
    lines.append(f"C {{{sym_ref}}} {ix} {iy} 0 0 {{name={name}}}")
    for pin, (px, py, d) in sym_pins[typ].items():
        if d != 'inout':
            continue
        expr = conns.get(pin)
        if expr is None:
            continue
        net = canon_label(expr)
        ax, ay = ix + px, iy + py
        if abs(px) >= abs(py):
            bx, by = (ax - 15, ay) if px < 0 else (ax + 15, ay)
        else:
            bx, by = (ax, ay - 15) if py < 0 else (ax, ay + 15)
        add_wire(ax, ay, bx, by)
        _lab_counter[0] += 1
        lines.append(f"C {{devices/lab_pin.sym}} {bx:g} {by:g} 0 0 {{name=l{_lab_counter[0]} lab={net}}}")

# top-level in/out pin symbols
for pname, key in TOP_IN:
    if pname in ('VDD', 'GND'):
        continue
    x, y = topin_xy[key]
    lines.append(f"C {{devices/ipin.sym}} {x} {y} 0 0 {{name=io_{re.sub(r'[^A-Za-z0-9]','_',key)} lab={key}}}")
for pname, key in TOP_OUT:
    x, y = topout_xy[key]
    lines.append(f"C {{devices/opin.sym}} {x} {y} 0 0 {{name=io_{re.sub(r'[^A-Za-z0-9]','_',key)} lab={key}}}")

# global VDD/GND source pins (top-left corner, label-only, matches per-cell label stubs above)
lines.append(f"C {{devices/iopin.sym}} {TOPIN_X} {-260} 0 0 {{name=io_VDD lab=VDD}}")
lines.append(f"C {{devices/iopin.sym}} {TOPIN_X} {-200} 0 0 {{name=io_GND lab=GND}}")

# ---------- 8. route signal nets (orthogonal, driver -> each sink) ----------
def pin_xy(kind, name, pin):
    if kind == 'inst':
        return abs_pin(name, pin)[:2]
    elif kind == 'topin':
        return topin_xy[name]
    elif kind == 'topout':
        return topout_xy[name]

all_nets = set(net_driver.keys()) | set(net_sinks.keys())
lane = 0
for net in sorted(all_nets):
    drv = net_driver.get(net)
    sinks = net_sinks.get(net, [])
    if drv is None or not sinks:
        continue
    if drv[0] == 'inst':
        dx, dy = abs_pin(drv[1], 'Y' if 'Y' in instmap[drv[1]][1] else None) if False else (None, None)
    # get actual driver point
    if drv[0] == 'inst':
        typ, conns = instmap[drv[1]]
        outpin = [p for p, (px, py, d) in sym_pins[typ].items() if d == 'out' and conns.get(p) is not None]
        if not outpin:
            continue
        dx, dy = abs_pin(drv[1], outpin[0])[:2]
    else:
        dx, dy = topin_xy[drv[1]]

    for i, sk in enumerate(sinks):
        if sk[0] == 'inst':
            typ, conns = instmap[sk[1]]
            inpins = [p for p, (px, py, d) in sym_pins[typ].items() if d == 'in' and conns.get(p) == net or (d == 'in' and canon_label(conns.get(p, '')) == net)]
            # find exact pin whose connection canonicalizes to this net
            target_pin = None
            for p, (px, py, d) in sym_pins[typ].items():
                if d != 'in':
                    continue
                expr = conns.get(p)
                if expr is not None and canon_label(expr) == net:
                    target_pin = p
                    break
            if target_pin is None:
                continue
            sx, sy = abs_pin(sk[1], target_pin)[:2]
        else:
            sx, sy = topout_xy[sk[1]]

        lane = (lane + 1) % 7
        off = (lane - 3) * 12
        bendx = dx + max(20, (sx - dx) / 2) + off
        add_wire(dx, dy, bendx, dy)
        add_wire(bendx, dy, bendx, sy)
        add_wire(bendx, sy, sx, sy)

open(OUT_FILE, "w").write("\n".join(lines) + "\n")
print("wrote", OUT_FILE, "lines:", len(lines))
