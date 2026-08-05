"""
Trace the combinational fan-in cone of a given net back to primary
inputs / register outputs (DFFR.Q), printing a readable tree.
Stops expanding at DFFR/DFFP outputs (registers) and primary inputs.
"""
import re, sys, os

STDLIB_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"

def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins

celltypes = [f[:-4] for f in os.listdir(STDLIB_DIR) if f.endswith(".sym")]
sym_pins = {ct: parse_sym(os.path.join(STDLIB_DIR, ct + ".sym")) for ct in celltypes}

src = open(NET_FILE).read()

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

assigns = {}
for m in re.finditer(r'assign\s+(.+?)\s*=\s*(.+?);', src):
    lhs, rhs = m.groups()
    lhs, rhs = lhs.strip(), rhs.strip()
    assigns[lhs] = rhs

# driver map: net -> (typ, name, conns) whose output pin equals net
driver_of = {}
for typ, name, conns in instances:
    for pin, expr in conns.items():
        d = sym_pins[typ].get(pin)
        if d == 'out':
            driver_of[expr] = (typ, name, pin, conns)

SEQ_TYPES = {"DFFR", "DFFP", "DFF"}

def trace(net, depth=0, seen=None, max_depth=8):
    if seen is None:
        seen = set()
    pad = "  " * depth
    if net in ("VDD", "GND", "1'b0", "1'b1"):
        print(f"{pad}{net} (const)")
        return
    if depth > max_depth:
        print(f"{pad}{net} ...(depth limit)")
        return
    if net in assigns:
        print(f"{pad}{net} = alias of {assigns[net]}")
        trace(assigns[net], depth, seen, max_depth)
        return
    if net in driver_of:
        typ, name, pin, conns = driver_of[net]
        print(f"{pad}{net} <- {typ} {name}.{pin}")
        if typ in SEQ_TYPES:
            print(f"{pad}  (register output, stop)")
            return
        if name in seen:
            print(f"{pad}  (already traced {name}, stop)")
            return
        seen.add(name)
        for p, e in conns.items():
            if sym_pins[typ].get(p) == 'in':
                print(f"{pad}  .{p}({e}):")
                trace(e, depth + 2, seen, max_depth)
    else:
        print(f"{pad}{net} (primary input / undriven)")

if __name__ == "__main__":
    for net in sys.argv[1:]:
        print(f"=== trace {net} ===")
        trace(net)
        print()
