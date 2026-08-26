"""
gen_schematic_v7.py

LVS prep (this session, user request: "NETから schematic を作成ください").
Adapted from gen_schematic_routed.py (levelized, orthogonally-routed
xschem schematic generator) for the CURRENT v7 netlist
(src/i2c_slave_async_net_v7.v), which gen_schematic_routed.py never
targeted (it still points at the old src/i2c_slave_async_net.v).

Per user instruction: DFFRB (renamed from DFFR) and BUFTH must reference
the schematics/symbols under LEF/ (LEF/DFFRB.sym, LEF/BUFTH.sym -- the project-specific,
already-LVS-relevant versions used elsewhere in this session's LVS work),
NOT the generic STDLIB/TR-1um_5_stdcell copies. Every other cell type
used by the v7 netlist (AND2_X1, BUF_X1, DEL1, INV_X1, MUX2, NAND2/3/4,
NOR2/3/4, OR2/3/4) comes from STDLIB/TR-1um_5_stdcell as before.

Everything else (parsing, union-find net resolution, levelizing,
barycenter column ordering, orthogonal driver->sink wire routing) is
unchanged from gen_schematic_routed.py.
"""
import json, re, os, sys
from collections import defaultdict

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
STDCELL_ABS_DIR = "/Users/okamura/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_5_stdcell"
LEF_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF"
LEF_ABS_DIR = "/Users/okamura/Dropbox/98_LSI_Design/TR-1um_Async_I2C/LEF"
LEF_OVERRIDE_TYPES = {"DFFRB", "BUFTH", "MUX2"}  # user instruction: use LEF/ sch+sym, not STDLIB's

NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net_v7.v"
# v46 (this session, user request: "schematicとLayoutのTop Cell名は
# 同じにしてください"): xschem derives a netlisted top subckt's name from
# the .sch file's own basename, so renaming this output file to match
# the LAYOUT's top cell name (TOP_CELL_NAME="i2c_slave_async_nrow_fm" in
# every P&R/DRC/connectivity script -- baked into ~80 files, far more
# invasive to rename) makes both sides' SPICE .subckt name identical
# without touching any layout tooling. Old name was
# "i2c_slave_async_net_v7_routed" (matched neither the layout's
# "i2c_slave_async_nrow_fm" nor the RTL's "i2c_slave_async").
OUT_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/i2c_slave_async_nrow_fm.sch"

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
sym_dir = {ct: STDCELL_ABS_DIR for ct in celltypes}

for ct in LEF_OVERRIDE_TYPES:
    sym_path = os.path.join(LEF_DIR, ct + ".sym")
    if os.path.exists(sym_path):
        sym_pins[ct] = parse_sym(sym_path)
        sym_dir[ct] = LEF_ABS_DIR
        print(f"using LEF override for {ct}: {sym_path} ({len(sym_pins[ct])} pins)")
    else:
        print(f"WARNING: LEF override requested for {ct} but {sym_path} not found "
              f"-- falling back to STDLIB copy if present")

# ---------- 1b. FILL2/FILL3 filler cells (this session, user request) ----------
# The gate netlist has no notion of filler cells (they carry no logic, only
# VDD/GND). STEP1 of the physical layout (gen_placement_gds_nrow_fm.py,
# reflected in the v7v2_step_1_* checkpoint GDS) inserts them for DRC
# fill/well-tie purposes. For LVS completeness the schematic needs the
# SAME instance count so a layout-vs-schematic device-count comparison
# doesn't flag them as extra devices. FILL2.sym/FILL3.sym only exist
# under LEF/ (not STDLIB) -- same override mechanism as DFFR/BUFTH.
FILL_TYPES = ["FILL2", "FILL3"]
for ct in FILL_TYPES:
    sym_path = os.path.join(LEF_DIR, ct + ".sym")
    sym_pins[ct] = parse_sym(sym_path)
    sym_dir[ct] = LEF_ABS_DIR

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm_v7_priomch.json"
_placement = json.load(open(PLACEMENT_JSON))
fill_insts = []  # (type, name)
for _row in _placement["rows"]:
    for _inst in _row:
        if _inst["type"] in FILL_TYPES:
            fill_insts.append((_inst["type"], _inst["name"]))
print(f"filler cells from {PLACEMENT_JSON}: "
      f"{ {t: sum(1 for ty, _ in fill_insts if ty == t) for t in FILL_TYPES} }")

# ---------- 2. parse netlist ----------
src = open(NET_FILE).read()

port_dir = {}
port_width = {}
for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
    kind, _, msb, lsb, name = m.groups()
    w = (int(msb) - int(lsb) + 1) if msb else 1
    port_width[name] = w
    port_dir[name] = kind
top_module_match = re.search(r'module\s+(\w+)\s*\(([^)]*)\)', src)
top_module_name = top_module_match.group(1)
top_ports_order = [p.strip() for p in top_module_match.group(2).split(',')]
print("top module:", top_module_name, "ports:", top_ports_order)

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
by_type = defaultdict(int)
for typ, name, conns in instances:
    by_type[typ] += 1
print("by type:", dict(by_type))

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
net_driver = {}
net_sinks = defaultdict(list)
net_driver_pin = {}
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
            if dtyp == 'DFFRB':
                # a flip-flop output is a fresh source for downstream
                # combinational depth (real hardware: that logic happens
                # on the previous clock edge)
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
for lvl in sorted(cols):
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

# place instances + VDD/GND label pins (inout pins use lab_pin.sym --
# xschem connectivity is purely geometric except for this explicit
# global net-tie mechanism).
# v44: tie directly ON the pin coordinate (no offset stub wire) -- see
# the section-8 comment below for why (real xschem LVS run found
# accidental shorts from overlapping wire geometry).
_lab_counter = [0]
for typ, name, conns in instances:
    ix, iy = xy[name]
    sym_ref = f"{sym_dir[typ]}/{typ}.sym"
    # v47 (this session): KLayout's LVS netlist reader determines SPICE
    # element type from the INSTANCE NAME's first letter (R/L/C/D/Q/M/
    # V/I/E/F/G/H/B/S/W/U/K/T/O/... are all reserved primitive-device
    # codes). Several hand-inserted instance names in the Verilog
    # netlist start with "u_" (u_del_sda, u_inv_scl, ...) -- 'u'/'U' is
    # SPICE's reserved code for a uniform-RC-line element, so KLayout's
    # reader tried to parse them as that device type instead of a
    # subcircuit call and errored ("Not a known element type: 'U'").
    # xschem's own convention (see any .sym's `template="name=x1"`) is
    # that subcircuit instance names start with 'x' -- prefix every
    # instance name with "x" on the way out so this can never collide
    # with a reserved SPICE device-type letter, regardless of what the
    # underlying Verilog/placement-JSON instance name happens to be.
    lines.append(f"C {{{sym_ref}}} {ix} {iy} 0 0 {{name=x{name}}}")
    for pin, (px, py, d) in sym_pins[typ].items():
        if d != 'inout':
            continue
        expr = conns.get(pin)
        # v45 (this session): Yosys-synthesized standard-cell instances
        # (the "_NNN_" ones, i.e. almost all 154) do NOT list .VDD()/
        # .GND() connections in the netlist at all -- only the dozen
        # hand-inserted buffer/delay/BUFTH cells (u_*) do. Previously
        # `expr is None` caused this loop to `continue`, silently
        # leaving VDD/GND FLOATING on every synthesized cell -- the
        # user's real SPICE flattening confirmed this: those pins came
        # out as isolated auto-named nets ("net1", "net2", ...) instead
        # of the shared VDD/GND rail. VDD/GND pin NAMES are the global
        # rail by convention throughout this library (every cell uses
        # exactly "VDD"/"GND"), so default to the pin's own name instead
        # of skipping when there's no explicit netlist connection.
        net = canon_label(expr) if expr is not None else pin
        ax, ay = round(ix + px), round(iy + py)
        _lab_counter[0] += 1
        lines.append(f"C {{devices/lab_pin.sym}} {ax} {ay} 0 0 {{name=l{_lab_counter[0]} lab={net}}}")

# FILL2/FILL3 filler cells (this session, user request: "STEP1で配置した
# 個数をschematicにも配置してください" -- match the physical layout's
# filler-cell count for LVS device-count completeness). No logic, no
# signal pins -- VDD/GND only, tied the same way every other inout pin
# is tied above. Placed in their own grid, well clear of the routed
# logic (a schematic doesn't need to mirror the physical placement,
# only the instance count + power connectivity).
#
# v44 fix: FILL2.sym/FILL3.sym's pins sit at LOCAL y=-60 (VDD) and
# y=+60 (GND) -- a full 120-unit span. The original FILL_DY=120 row
# pitch made row N's GND pin (abs y = row_y+60) land on EXACTLY the
# same point as row N+1's VDD pin (abs y = (row_y+120)-60 = row_y+60),
# directly shorting GND to VDD (reported by the user's xschem LVS run).
# Also: per the same user instruction as section 8 above, tie via a
# lab_pin.sym placed directly ON the pin (no offset stub wire) instead
# of a short connecting wire -- consistent, and one less thing to
# accidentally overlap.
FILL_COLS = 12
FILL_DX, FILL_DY = 150, 200  # > symbol extents (60 wide x 125 tall) with margin
FILL_X0 = TOPOUT_X + DX  # start one column past the rightmost real logic
FILL_Y0 = -600
for i, (typ, name) in enumerate(fill_insts):
    col = i % FILL_COLS
    row = i // FILL_COLS
    ix = FILL_X0 + col * FILL_DX
    iy = FILL_Y0 + row * FILL_DY
    sym_ref = f"{sym_dir[typ]}/{typ}.sym"
    # v47: same "x" prefix fix as the main instance loop above --
    # FILL2/FILL3 instance names from the placement JSON ("FILLPRI_0",
    # "FILL_0", ...) start with 'F', SPICE's reserved current-controlled-
    # current-source code, which would hit the exact same KLayout LVS
    # reader error once the 'U' issue was fixed.
    # Also (found while checking this fix): the placement JSON's FILL
    # names are only unique WITHIN each physical row ("FILL_0" reused in
    # every row), so 114 fillers collapse to 186... wait, to far fewer
    # than 114 unique strings once copied verbatim into one flat
    # schematic -- SPICE requires every instance name in a subckt to be
    # unique. Append the loop index `i` (already globally unique across
    # all 114 fillers) to guarantee a unique SPICE instance name.
    lines.append(f"C {{{sym_ref}}} {ix} {iy} 0 0 {{name=x{name}_{i}}}")
    for pin, (px, py, d) in sym_pins[typ].items():
        net = pin  # FILL2/FILL3 only have VDD/GND pins, both dir=inout
        ax, ay = round(ix + px), round(iy + py)
        _lab_counter[0] += 1
        lines.append(f"C {{devices/lab_pin.sym}} {ax} {ay} 0 0 {{name=l{_lab_counter[0]} lab={net}}}")
print(f"placed {len(fill_insts)} filler cell(s) (FILL2/FILL3) with VDD/GND ties")

# top-level in/out pin symbols
# v44: lab= must be the CANONICAL net name (same string net_driver/
# net_sinks/the tie loop below use), not the raw port key -- otherwise a
# topin/topout port aliased via a plain (non-concat) `assign` could end
# up with a lab string that never matches its instance-side ties.
for pname, key in TOP_IN:
    if pname in ('VDD', 'GND'):
        continue
    x, y = topin_xy[key]
    lines.append(f"C {{devices/ipin.sym}} {x} {y} 0 0 {{name=io_{re.sub(r'[^A-Za-z0-9]','_',key)} lab={canon_label(key)}}}")
for pname, key in TOP_OUT:
    x, y = topout_xy[key]
    lines.append(f"C {{devices/opin.sym}} {x} {y} 0 0 {{name=io_{re.sub(r'[^A-Za-z0-9]','_',key)} lab={canon_label(key)}}}")

# global VDD/GND source pins
lines.append(f"C {{devices/iopin.sym}} {TOPIN_X} {-260} 0 0 {{name=io_VDD lab=VDD}}")
lines.append(f"C {{devices/iopin.sym}} {TOPIN_X} {-200} 0 0 {{name=io_GND lab=GND}}")

# ---------- 8. tie all signal nets via net labels (no routed wires) ----------
# v44 (this session): the previous version drew explicit orthogonal
# 3-segment bend wires from driver to every sink, cycling through only 7
# lane offsets GLOBALLY across ~600 connections (`lane`/`off` above).
# Loading the result into real xschem (user's LVS run) found dozens of
# false shorts between UNRELATED nets (e.g. "rst_n - tx_data[0]",
# "GND - VDD" for the FILL block) -- xschem merges two wire segments
# that are collinear and overlapping into one net even when they belong
# to logically different nets, and with only 7 discrete offsets shared
# across the whole design, collisions were common.
#
# Per user instruction ("無理にワイヤーを引かずにネットラベルで繋いで
# ください"), replace ALL routed wires with direct point-ties: a
# lab_pin.sym placed exactly ON each pin's own absolute coordinate. A
# symbol's pin sits at that exact point regardless of net; placing the
# label there (not offset to the side by a stub wire) makes the label
# and the pin coincide directly, joining them onto the `lab` net with no
# wire geometry at all -- so there is nothing left that can accidentally
# overlap another net's geometry.
all_nets = set(net_driver.keys()) | set(net_sinks.keys())

def tie_inst_pin(name, pin, net):
    ax, ay = abs_pin(name, pin)[:2]
    ax, ay = round(ax), round(ay)
    _lab_counter[0] += 1
    lines.append(f"C {{devices/lab_pin.sym}} {ax} {ay} 0 0 {{name=l{_lab_counter[0]} lab={net}}}")

for net in sorted(all_nets):
    drv = net_driver.get(net)
    sinks = net_sinks.get(net, [])
    # v51 (design_notes 71, user request: compare schematic-SPICE vs a
    # Verilog-derived SPICE): previously `not sinks` also skipped the
    # DRIVER tie, leaving the driver pin with NO lab_pin at all whenever
    # a net has zero sinks. This happens for ~23 DFFR.QB outputs Yosys
    # marks `unused_bits` (Q is used, QB never read anywhere) -- the
    # Verilog netlist still explicitly names them (e.g. `.QB(_128_)`),
    # but the schematic left that pin unlabeled, so xschem's own
    # netlister invented anonymous "net1".."net23" names for them on
    # export -- confirmed via a from-scratch Verilog-vs-schematic SPICE
    # connection diff (net_shapes_log/pin_map style cross-check, but for
    # the schematic instead of the layout). Electrically harmless (a
    # single-pin net has no other connection to mismatch either way),
    # but it means the exported netlist doesn't actually carry the RTL's
    # own net names for these pins, and would show up as a spurious
    # "extra net" if ever compared name-for-name against a reference.
    # A driver with no sinks should still get exactly one tie (on the
    # driver pin itself), giving it its true canonical name instead of
    # leaving it to be auto-numbered.
    if drv is None:
        continue
    if drv[0] == 'inst':
        # v43 (this session, LVS prep): a cell can have MORE THAN ONE
        # 'out' pin (e.g. DFFR's Q and QB are BOTH dir=out, and Yosys
        # commonly wires both even when only one is used downstream --
        # see e.g. "_262_ DFFR (.Q(bit_cnt[0]), .QB(_133_[0]), ...)").
        # Grabbing "any" connected out-pin (outpin[0], old behavior) can
        # silently pick the WRONG one (QB's physical location) as the
        # tie point. Must match the SPECIFIC pin whose own connection
        # resolves to exactly this net, mirroring the sink-side lookup.
        typ, conns = instmap[drv[1]]
        driver_pin = None
        for p, (px, py, d) in sym_pins[typ].items():
            if d != 'out':
                continue
            expr = conns.get(p)
            if expr is not None and canon_label(expr) == net:
                driver_pin = p
                break
        if driver_pin is not None:
            tie_inst_pin(drv[1], driver_pin, net)
    # topin drivers already carry lab=canon_label(key) on their ipin.sym
    # (section 7 above) -- no extra tie needed there.

    for sk in sinks:
        if sk[0] != 'inst':
            continue  # topout sinks already carry lab=canon_label(key) on their opin.sym
        typ, conns = instmap[sk[1]]
        target_pin = None
        for p, (px, py, d) in sym_pins[typ].items():
            if d != 'in':
                continue
            expr = conns.get(p)
            if expr is not None and canon_label(expr) == net:
                target_pin = p
                break
        if target_pin is not None:
            tie_inst_pin(sk[1], target_pin, net)

open(OUT_FILE, "w").write("\n".join(lines) + "\n")
print("wrote", OUT_FILE, "lines:", len(lines))
