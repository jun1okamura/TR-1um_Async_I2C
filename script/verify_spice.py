import re, os
from collections import defaultdict

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"
SPICE_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/schematic/i2c_slave_async_net.spice"

# ---------- ground truth from i2c_slave_async_net.v (same as gen_schematic.py) ----------
def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                x1, y1, x2, y2, name, direction = m.groups()
                pins[name] = direction
    return pins

celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
sym_pins = {ct: parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

src = open(NET_FILE).read()
port_width = {}
for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
    kind, _, msb, lsb, name = m.groups()
    port_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
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
    if m: return [f"{m.group(1)}[{m.group(2)}]"]
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

def canon(expr):
    return find(expr)

# expected[(inst,pin)] = canonical net id (root string, doesn't need to be pretty)
expected = {}
for typ, name, conns in instances:
    for pin, expr in conns.items():
        d = sym_pins[typ].get(pin)
        expected[(name, pin)] = canon(expr)

print("ground-truth instances:", len(instances))
print("ground-truth (inst,pin) pairs:", len(expected))

# ---------- parse SPICE file ----------
spice = open(SPICE_FILE).read()

subckt_order = {}
for m in re.finditer(r'^\.subckt\s+(\S+)\s+(.+)$', spice, re.M):
    name, pins = m.groups()
    subckt_order[name] = pins.split()

# top-level instance block: between the commented top subckt header and the matching **.ends
top_start = spice.index("**.subckt i2c_slave_async_net")
top_end = spice.index("**.ends", top_start)
top_block = spice[top_start:top_end]

actual = {}
inst_lines = 0
for line in top_block.splitlines():
    line = line.strip()
    if not line or line.startswith('*'):
        continue
    toks = line.split()
    instname = toks[0]
    celltype = toks[-1]
    nets = toks[1:-1]
    order = subckt_order.get(celltype)
    if order is None:
        print("WARNING: no subckt decl found for", celltype)
        continue
    if len(order) != len(nets):
        print("WARNING: pin count mismatch", instname, celltype, len(order), len(nets))
        continue
    inst_lines += 1
    for pinname, net in zip(order, nets):
        actual[(instname, pinname)] = net

print("spice instance lines:", inst_lines)
print("spice (inst,pin) pairs:", len(actual))

# ---------- compare key sets ----------
missing_in_spice = set(expected) - set(actual)
extra_in_spice = set(actual) - set(expected)
print("keys in ground-truth but missing from spice parse:", len(missing_in_spice))
print("keys in spice parse but not in ground-truth:", len(extra_in_spice))
if missing_in_spice:
    print("  sample missing:", list(missing_in_spice)[:10])
if extra_in_spice:
    print("  sample extra:", list(extra_in_spice)[:10])

common = set(expected) & set(actual)

# build partitions restricted to common keys
exp_groups = defaultdict(set)
act_groups = defaultdict(set)
for k in common:
    exp_groups[expected[k]].add(k)
    act_groups[actual[k]].add(k)

# For each expected group, check all its members share exactly one actual net,
# and that actual net's group doesn't contain anything outside this expected group.
errors = []
checked_exp_roots = set()
for k in common:
    er = expected[k]
    if er in checked_exp_roots:
        continue
    checked_exp_roots.add(er)
    members = exp_groups[er]
    act_nets_seen = {actual[m] for m in members}
    if len(act_nets_seen) > 1:
        errors.append(("SPLIT", er, members, act_nets_seen))
    else:
        an = next(iter(act_nets_seen))
        if act_groups[an] != members:
            extra_members = act_groups[an] - members
            errors.append(("MERGE", er, members, extra_members))

print("\n=== equivalence-class comparison ===")
print("expected distinct nets (among common keys):", len(exp_groups))
print("actual distinct nets (among common keys):", len(act_groups))
print("mismatched groups:", len(errors))
for kind, er, members, extra in errors[:30]:
    print(f"  [{kind}] canon={er!r} members={sorted(members)[:6]}{'...' if len(members)>6 else ''} extra/other={sorted(extra)[:6]}")

if not errors and not missing_in_spice and not extra_in_spice:
    print("\nRESULT: PERFECT MATCH - spice connectivity == verilog netlist connectivity")
else:
    print("\nRESULT: MISMATCHES FOUND (see above)")
