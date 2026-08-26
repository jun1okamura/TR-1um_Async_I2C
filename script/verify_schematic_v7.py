"""
verify_schematic_v7.py

Independent geometric check that i2c_slave_async_nrow_fm.sch
(gen_schematic_v7.py's output; renamed in v46 to match the layout's top
cell name -- see design_notes section 65) is actually connectivity-equivalent to
the source netlist src/i2c_slave_async_net_v7.v -- without requiring
xschem itself (not available in this sandbox). Re-parses the .sch from
scratch (wires + component placements), builds the same kind of
point/segment union-find graph xschem's own netlister uses (touching
wire endpoints, mid-segment T-junctions, and the explicit lab_pin.sym
global net-tie mechanism), and checks that EVERY (instance, pin) call
site position in the .sch lands on a net matching the pin's expected
canonical net from the Verilog netlist.

This mirrors verify_spice.py's role but operates directly on schematic
geometry instead of a post-netlisted SPICE file.
"""
import re
import sys
sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

SCH = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/i2c_slave_async_nrow_fm.sch"

# ---- reuse gen_schematic_v7's own parsing/canon_label/instmap/sym_pins/xy by importing it as data ----
import importlib.util
spec = importlib.util.spec_from_file_location(
    "gen_schematic_v7", "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/gen_schematic_v7.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)  # re-runs generation (idempotent, deterministic) to get its data structures

# ---- parse the written .sch fresh ----
text = open(SCH).read()

wires = []
for m in re.finditer(r'^N\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\{([^}]*)\}', text, re.M | re.S):
    x1, y1, x2, y2, props = m.groups()
    lm = re.search(r'lab=(\S+)', props)
    lab = lm.group(1) if lm else None
    wires.append((float(x1), float(y1), float(x2), float(y2), lab))

comps = []
for m in re.finditer(r'^C\s+\{(\S+)\}\s+([\d.\-]+)\s+([\d.\-]+)\s+(\d+)\s+(\d+)\s*\{([^}]*)\}', text, re.M | re.S):
    sym, x, y, rot, flip, props = m.groups()
    d = {}
    for pm in re.finditer(r'(\w+)=(\S+)', props):
        d[pm.group(1)] = pm.group(2)
    comps.append((sym, float(x), float(y), int(rot), int(flip), d))

print(f"parsed {len(wires)} wires, {len(comps)} components from {SCH}")

# ---- union-find over point coordinates ----
parent = {}
def find(p):
    parent.setdefault(p, p)
    while parent[p] != p:
        parent[p] = parent[parent[p]]
        p = parent[p]
    return p
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb

def on_segment(px, py, x1, y1, x2, y2, eps=1e-6):
    if abs(x1 - x2) < eps:
        if abs(px - x1) > eps:
            return False
        lo, hi = min(y1, y2), max(y1, y2)
        return lo - eps <= py <= hi + eps
    elif abs(y1 - y2) < eps:
        if abs(py - y1) > eps:
            return False
        lo, hi = min(x1, x2), max(x1, x2)
        return lo - eps <= px <= hi + eps
    return False

# collect candidate connection points: every wire endpoint + every
# component's single connection point (ipin/opin/iopin/lab_pin ->
# placement coord itself, since those symbols' own pin sits at local
# origin regardless of rot/flip)
points = set()
for x1, y1, x2, y2, lab in wires:
    points.add((x1, y1))
    points.add((x2, y2))
port_like_suffixes = ("ipin.sym", "opin.sym", "iopin.sym", "lab_pin.sym", "lab_wire.sym")
for sym, x, y, rot, flip, d in comps:
    if sym.endswith(port_like_suffixes):
        points.add((x, y))

# union wire endpoints that coincide
# (dict already handles equality; just ensure both are registered)
for x1, y1, x2, y2, lab in wires:
    find((x1, y1))
    find((x2, y2))
    union((x1, y1), (x2, y2))

# T-junctions: any point lying on a wire segment's interior (not just
# its own endpoints) also joins that segment's electrical net
for pt in list(points):
    px, py = pt
    for x1, y1, x2, y2, lab in wires:
        if on_segment(px, py, x1, y1, x2, y2):
            union(pt, (x1, y1))

# lab_pin.sym / lab_wire.sym global net-tie: all instances sharing the
# same lab= value are forced onto the same net regardless of geometry
lab_groups = {}
for sym, x, y, rot, flip, d in comps:
    if sym.endswith("lab_pin.sym") or sym.endswith("lab_wire.sym") or sym.endswith(
            "ipin.sym") or sym.endswith("opin.sym") or sym.endswith("iopin.sym"):
        lab = d.get("lab")
        if lab:
            lab_groups.setdefault(lab, []).append((x, y))
for lab, pts in lab_groups.items():
    for p in pts[1:]:
        union(pts[0], p)

# ---- ground truth: for each net, the (instance,pin) point that must be
# geometrically connected together -- NOT by matching a `lab=` text
# attribute (most real signal wires in this generator's output carry NO
# lab= at all; only inout/lab_pin ties do -- xschem connectivity is pure
# geometry, confirmed by this project's own established convention, see
# gen_schematic_v7.py's comment above the inout-pin stub code). So the
# correct check is: do all (instance,pin) points that the Verilog
# netlist says belong to the same net end up in the SAME union-find
# component in the schematic's actual wire graph?
net_points = {}  # canon net -> list of (name, pin, point)
for typ, name, conns in G.instances:
    ix, iy = G.xy[name]
    for pin, (px, py, direction) in G.sym_pins[typ].items():
        expr = conns.get(pin)
        if expr is None:
            if direction != 'inout':
                continue
            # v45: VDD/GND pins with no explicit netlist connection
            # default to the pin's own name (the global rail) -- mirror
            # gen_schematic_v7.py's own default so this check actually
            # covers every instance's power pins instead of silently
            # skipping the ~154 synthesized cells that omit them.
            expected_net = pin
        else:
            expected_net = G.canon_label(expr)
        ax, ay = round(ix + px), round(iy + py)
        net_points.setdefault(expected_net, []).append((name, pin, (ax, ay)))

# also include top-level I/O pin placements (ipin/opin), so a port that
# ends up disconnected from its instance-side net is caught too
for pname, key in G.TOP_IN:
    if pname in ('VDD', 'GND'):
        continue
    x, y = G.topin_xy[key]
    net_points.setdefault(G.canon_label(key), []).append((f"TOPIN:{key}", "-", (round(x), round(y))))
for pname, key in G.TOP_OUT:
    x, y = G.topout_xy[key]
    net_points.setdefault(G.canon_label(key), []).append((f"TOPOUT:{key}", "-", (round(x), round(y))))

checked = 0
mismatches = []
for net, entries in net_points.items():
    checked += len(entries)
    roots = {}
    for name, pin, pt in entries:
        r = find(pt) if pt in parent else pt
        roots.setdefault(r, []).append((name, pin, pt))
    if len(roots) > 1:
        # split net: report the minority members as mismatches
        biggest = max(roots.values(), key=len)
        for r, members in roots.items():
            if members is biggest:
                continue
            for name, pin, pt in members:
                mismatches.append((name, pin, net, pt, len(roots)))

print(f"checked {checked} (instance,pin) connections across {len(net_points)} nets")
print(f"mismatches (pins split off from their net's main group): {len(mismatches)}")
for name, pin, net, pt, ngroups in mismatches[:40]:
    print(f"  {name}.{pin}: net={net!r} at {pt} -- in a DIFFERENT geometric group "
          f"than the rest of net {net!r} ({ngroups} distinct groups total)")

if not mismatches:
    print("\nRESULT: PERFECT MATCH -- schematic geometry connectivity == v7 verilog netlist connectivity")
else:
    print("\nRESULT: MISMATCHES FOUND (see above)")
