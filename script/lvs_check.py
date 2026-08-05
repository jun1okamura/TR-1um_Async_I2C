"""
Compare OLD (pre-buffer, .bak) vs NEW (buffered) i2c_slave_async_net.v:
for every (inst,pin) NOT belonging to a newly-added buffer instance, verify
its connectivity is either UNCHANGED, or (for the 4 explicitly buffered
nets) correctly redirected to one of that net's valid branch names.

Also explicitly reports any assign-statement (not just instance-pin) that
still reads one of the 4 buffered nets RAW/unredirected -- these are gaps
my instance-pin-only redirect logic can't see.
"""
import re, os

STDLIB_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
OLD_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v.bak"
NEW_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"

BUFFERED = {
    "scl": {"scl_buf0", "scl_buf1"},
    "sda_in": {"sda_in_buf0", "sda_in_buf1"},
    "_126_": {"_126_buf0", "_126_buf1"},
    "_127_": {"_127_buf0", "_127_buf1"},
}
NEW_BUF_INST_PREFIXES = ("u_scl_buf", "u_sda_in_buf", "u__126_buf", "u__127_buf")


def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins


def load(path, sym_pins):
    src = open(path).read()
    port_width, wire_width = {}, {}
    for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        kind, _, msb, lsb, name = m.groups()
        port_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
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
    all_assigns_raw = []
    for m in re.finditer(r'assign\s+(.+?)\s*=\s*(.+?);', src):
        lhs, rhs = m.groups()
        all_assigns_raw.append((lhs.strip(), rhs.strip()))
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

    def canon(expr):
        return find(expr)

    return instances, canon, all_assigns_raw


def main():
    celltypes = [f[:-4] for f in os.listdir(STDLIB_DIR) if f.endswith(".sym")]
    sym_pins = {ct: parse_sym(os.path.join(STDLIB_DIR, ct + ".sym")) for ct in celltypes}

    old_inst, old_canon, old_assigns = load(OLD_FILE, sym_pins)
    new_inst, new_canon, new_assigns = load(NEW_FILE, sym_pins)

    old_map = {(name, pin): expr for typ, name, conns in old_inst for pin, expr in conns.items()}
    new_map = {(name, pin): expr for typ, name, conns in new_inst for pin, expr in conns.items()}

    mismatches = []
    checked = 0
    for (name, pin), old_expr in old_map.items():
        if name.startswith(NEW_BUF_INST_PREFIXES):
            continue
        if (name, pin) not in new_map:
            mismatches.append(f"MISSING in new: {name}.{pin} (was {old_expr})")
            continue
        new_expr = new_map[(name, pin)]
        old_c = old_canon(old_expr)
        new_c = new_canon(new_expr)
        checked += 1
        if old_c in BUFFERED:
            if new_c not in BUFFERED[old_c]:
                mismatches.append(f"{name}.{pin}: old={old_expr!r}(canon {old_c!r}) "
                                   f"-> new={new_expr!r}(canon {new_c!r}) NOT a valid branch {BUFFERED[old_c]}")
        else:
            if old_c != new_c:
                mismatches.append(f"{name}.{pin}: old={old_expr!r}(canon {old_c!r}) "
                                   f"-> new={new_expr!r}(canon {new_c!r}) UNEXPECTED CHANGE")

    print(f"checked {checked} (inst,pin) pairs present in both old and new (excluding new buffer insts)")
    print(f"mismatches: {len(mismatches)}")
    for m in mismatches[:50]:
        print("  ", m)

    # Now scan ALL assign statements (including concatenation ones) in NEW
    # for any RAW read of one of the 4 buffered original net names.
    print()
    print("=== assign statements in NEW file that still read a buffered net's ORIGINAL name ===")
    for lhs, rhs in new_assigns:
        for orig in BUFFERED:
            if re.search(r'\b' + re.escape(orig) + r'\b', rhs):
                print(f"  assign {lhs} = {rhs};   <-- reads raw {orig!r}")


if __name__ == "__main__":
    main()
