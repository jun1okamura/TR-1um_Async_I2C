"""
fanout_net.py

Real gate-level fanout for src/i2c_slave_async_net.v (the Yosys-synthesized
netlist), computed per canonical net: for each net, FO = number of distinct
gate INPUT pins it drives (Union-Find-canonicalized across Yosys's many
`assign a = b;` alias lines -- both scalar and per-bit bus aliases), VDD/GND
excluded. Unlike the earlier RTL-level read-count proxy
(script/fanout_rtl.py), this is the real post-synthesis load count.

Usage: python3 script/fanout_net.py [name1 name2 ...]
  no args   -> print every canonical net with FO >= 5, sorted descending
  with args -> print FO and full sink list for exactly those net names
               (e.g. 'bit_cnt[0]' 'bit_cnt[1]' 'bit_cnt[2]' 'bit_cnt[3]')
"""
import re
import os
import sys
from collections import defaultdict

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


def main():
    celltypes = [f[:-4] for f in os.listdir(STDLIB_DIR) if f.endswith(".sym")]
    sym_pins = {ct: parse_sym(os.path.join(STDLIB_DIR, ct + ".sym")) for ct in celltypes}

    src = open(NET_FILE).read()

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

    # sinks[canonical_net] = list of "inst.pin" strings for every INPUT pin
    # connected to that net (i.e. its fanout loads). VDD/GND (inout) skipped.
    sinks = defaultdict(list)
    drivers = defaultdict(list)
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':
                continue
            net = canon(expr)
            if d == 'in':
                sinks[net].append(f"{name}.{pin}")
            elif d == 'out':
                drivers[net].append(f"{name}.{pin}")

    # also make sure every canonical net that appears anywhere is registered
    all_keys = set()
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            all_keys.add(expr)
    for k in all_keys:
        find(k)

    args = sys.argv[1:]
    if args:
        for name in args:
            net = canon(name)
            fo = len(sinks.get(net, []))
            drv = drivers.get(net, [])
            print(f"{name}  (canonical net: {net!r})")
            print(f"  driver: {drv}")
            print(f"  FO = {fo}")
            for s in sinks.get(net, []):
                print(f"    -> {s}")
            print()
    else:
        fo_by_net = {net: len(lst) for net, lst in sinks.items()}
        print(f"{'net':<10}{'FO':<6}driver")
        print("-" * 40)
        for net, fo in sorted(fo_by_net.items(), key=lambda kv: -kv[1]):
            if fo >= 5:
                drv = drivers.get(net, ["(primary input / const)"])
                print(f"{net:<10}{fo:<6}{drv}")


if __name__ == "__main__":
    main()
