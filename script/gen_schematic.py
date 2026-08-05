import re, os

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
STDCELL_ABS_DIR = "/Users/okamura/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"
OUT_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/i2c_slave_async_net.sch"

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
sym_pins = {}
for ct in celltypes:
    sym_pins[ct] = parse_sym(os.path.join(STDCELL_DIR, ct + ".sym"))

# ---------- 2. parse netlist ----------
src = open(NET_FILE).read()

# module port widths
port_width = {}
for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
    kind, _, msb, lsb, name = m.groups()
    w = (int(msb) - int(lsb) + 1) if msb else 1
    port_width[name] = w
top_ports_order = []
mtop = re.search(r'module\s+i2c_slave_async\s*\(([^)]*)\)', src)
for p in mtop.group(1).split(','):
    top_ports_order.append(p.strip())

wire_width = {}
for m in re.finditer(r'^\s*wire\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
    _, msb, lsb, name = m.groups()
    w = (int(msb) - int(lsb) + 1) if msb else 1
    wire_width[name] = w

width_of = {}
width_of.update(wire_width)
width_of.update(port_width)

# instances: TYPE NAME ( .PIN(EXPR), ... );
instances = []
for m in re.finditer(r'\n\s*(\w+)\s+(\w+)\s*\(\s*(.*?)\)\s*;', src, re.S):
    typ, name, body = m.groups()
    if typ in ("input", "output", "wire", "module", "assign", "inout"):
        continue
    if typ not in sym_pins:
        continue
    conns = {}
    for pm in re.finditer(r'\.(\w+)\s*\(\s*([^()]*?)\s*\)', body):
        pin, expr = pm.groups()
        conns[pin] = expr.strip()
    instances.append((typ, name, conns))

print("instances found:", len(instances))
by_type = {}
for typ, name, conns in instances:
    by_type[typ] = by_type.get(typ, 0) + 1
print(by_type)

# assign statements for net aliasing
assigns = []
for m in re.finditer(r'assign\s+(.+?)\s*=\s*(.+?);', src):
    lhs, rhs = m.groups()
    if '{' in lhs or '{' in rhs or "'" in rhs:
        continue
    assigns.append((lhs.strip(), rhs.strip()))
print("simple assigns:", len(assigns))

# ---------- 3. union-find over net keys ----------
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
        if w > 1:
            return [f"{name}[{i}]" for i in range(w)]
        return [name]
    return None

for lhs, rhs in assigns:
    lb = expand(lhs)
    rb = expand(rhs)
    if lb is None or rb is None or len(lb) != len(rb):
        continue
    for a, b in zip(lb, rb):
        union(a, b)

TOP_PORTS = set()
for p in top_ports_order:
    w = port_width.get(p, 1)
    if w > 1:
        for i in range(w):
            TOP_PORTS.add(f"{p}[{i}]")
    else:
        TOP_PORTS.add(p)

def is_numbered(name):
    return re.match(r'^_\d+_(\[\d+\])?$', name) is not None

groups = {}
all_keys = set(TOP_PORTS)
for typ, name, conns in instances:
    for pin, expr in conns.items():
        all_keys.add(expr)
for k in all_keys:
    find(k)  # ensure registered
for k in list(parent.keys()):
    r = find(k)
    groups.setdefault(r, set()).add(k)

def canon_label(key):
    r = find(key)
    members = groups.get(r, {key})
    top = [m for m in members if m in TOP_PORTS]
    if top:
        return sorted(top)[0]
    named = [m for m in members if not is_numbered(m)]
    if named:
        return sorted(named)[0]
    return sorted(members)[0]

# ---------- 4. layout ----------
NCOLS = 12
DX, DY = 350, 300
X0, Y0 = 800, 0

lines = []
lines.append("v {xschem version=3.4.4 file_version=1.2\n}")
lines.append("G {}")
lines.append("K {}")
lines.append("V {}")
lines.append("S {}")
lines.append("E {}")

_lab_counter = [0]
def stub(px, py, ipx, ipy, netname):
    # NOTE: a bare `lab=` property on a plain wire (N ... {lab=X}) is NOT an
    # xschem net-label mechanism -- xschem connectivity is purely geometric
    # (touching wire/pin endpoints); a `lab=` attribute on a wire is not
    # read by the netlister at all. The correct way to give two otherwise
    # unconnected points the same electrical net is to terminate each one
    # with a devices/lab_pin.sym instance carrying a `lab=` property --
    # xschem explicitly documents that multiple lab_pin.sym instances
    # sharing the same `lab` value are shorted together regardless of
    # physical routing. (Confirmed empirically: an earlier version of this
    # script used bare wire `lab=` stubs and every single pin came back as
    # its own isolated net in an xschem-exported SPICE netlist.)
    ax, ay = ipx + px, ipy + py
    if abs(px) >= abs(py):
        bx, by = (ax - 20, ay) if px < 0 else (ax + 20, ay)
    else:
        bx, by = (ax, ay - 20) if py < 0 else (ax, ay + 20)
    lines.append(f"N {ax:g} {ay:g} {bx:g} {by:g} {{}}")
    _lab_counter[0] += 1
    lines.append(f"C {{devices/lab_pin.sym}} {bx:g} {by:g} 0 0 {{name=l{_lab_counter[0]} lab={netname}}}")

placed_nets_for_io = {}

# place gate/FF instances in a grid
for idx, (typ, name, conns) in enumerate(instances):
    col = idx % NCOLS
    row = idx // NCOLS
    ipx = X0 + col * DX
    ipy = Y0 + row * DY
    sym_ref = f"{STDCELL_ABS_DIR}/{typ}.sym"
    lines.append(f"C {{{sym_ref}}} {ipx} {ipy} 0 0 {{name={name}}}")
    pins = sym_pins[typ]
    for pin, (px, py, direction) in pins.items():
        expr = conns.get(pin)
        if expr is None:
            continue
        net = canon_label(expr)
        stub(px, py, ipx, ipy, net)

nrows = (len(instances) + NCOLS - 1) // NCOLS
grid_bottom = Y0 + nrows * DY

# ---------- 5. top-level I/O pins ----------
IN_PORTS = ["VDD", "GND", "rst_n", "scl", "sda_in"] + [f"tx_data[{i}]" for i in range(7, -1, -1)]
OUT_PORTS = ["sda_oe"] + [f"rx_data[{i}]" for i in range(7, -1, -1)] + ["rx_valid", "addr_match", "rw", "busy"]

LX = 0
ly = -200
for p in IN_PORTS:
    sym = "iopin" if p in ("VDD", "GND") else "ipin"
    lines.append(f"C {{devices/{sym}.sym}} {LX} {ly} 0 0 {{name=io_{re.sub(r'[^A-Za-z0-9]','_',p)} lab={p}}}")
    ly += 60

RX = X0 + NCOLS * DX + 200
ly = -200
for p in OUT_PORTS:
    lines.append(f"C {{devices/opin.sym}} {RX} {ly} 0 0 {{name=io_{re.sub(r'[^A-Za-z0-9]','_',p)} lab={p}}}")
    ly += 60

open(OUT_FILE, "w").write("\n".join(lines) + "\n")
print("wrote", OUT_FILE, "lines:", len(lines))
