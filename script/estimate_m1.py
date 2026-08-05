"""
Rough M1 horizontal-routing channel-density estimate for
Layout/i2c_slave_async_layout.gds, using the actual placed cell positions
and the real netlist connectivity.

Model (stated explicitly since this is an estimate, not a real router):
  - Only signal nets are counted (VDD/GND are on dedicated per-row M1 rails,
    already accounted for in the placement -- not part of this estimate).
  - For each row, and each net that has >=1 pin in that row, the net's
    "local span" in that row = [min_x, max_x] over the placed x-centers of
    its member instances THAT ARE IN THAT ROW (single-pin-in-row nets get a
    degenerate zero-width span -- a short stub down to the nearest M2
    column, not a long horizontal run).
  - Required parallel M1 tracks for a row = the classic channel-routing
    density: max, over all x, of the number of net-spans covering x. This
    is a textbook LOWER BOUND on real track count (an ideal, obstacle-free
    router could do it in this many tracks); an actual 2-layer router with
    limited dogleg freedom will need at least this many, likely somewhat
    more.
"""
import sys
sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from plan_placement import compute_rows, _parse_netlist, _canon_fn, NROWS, ROW_WIDTH_UM

rows, cell_width, row_height = compute_rows()

# Reconstruct each instance's absolute placed x-center exactly as
# gen_gds_placement.py does (mirrored/odd rows are placed in reversed order).
inst_pos = {}  # name -> (row_idx, x_center_um)
for r in range(NROWS):
    row = rows[r]
    mirrored = (r % 2 == 1)
    seq = list(reversed(row)) if mirrored else row
    cursor_x = 0.0
    for name, typ, w in seq:
        cx = cursor_x + w / 2.0
        inst_pos[name] = (r, cx)
        cursor_x += w

sym_pins, width_of, instances, assigns = _parse_netlist()
find, parent = _canon_fn(width_of, instances, assigns)

# net -> {row_idx: [x, x, ...]}
net_row_members = {}
total_signal_nets = set()
for typ, name, conns in instances:
    for pin, expr in conns.items():
        d = sym_pins[typ].get(pin)
        if d == 'inout':  # VDD/GND
            continue
        net = find(expr)
        total_signal_nets.add(net)
        r, x = inst_pos[name]
        net_row_members.setdefault(net, {}).setdefault(r, []).append(x)

print(f"total signal nets (excl. VDD/GND): {len(total_signal_nets)}")

M1_MIN_PITCH = 1.8 + 1.4  # um, DRC minimum (M1.W1 width 1.8 + M1.S1 space 1.4)
PRACTICAL_PITCH = 4.0     # um, rough practical pitch incl. via landing margin

grand_total_um_min = 0.0
grand_total_um_practical = 0.0
for r in range(NROWS):
    spans = []
    for net, rowmap in net_row_members.items():
        if r not in rowmap:
            continue
        xs = rowmap[r]
        spans.append((min(xs), max(xs)))

    # sweep-line max overlap count
    events = []
    for x0, x1 in spans:
        events.append((x0, 1))
        events.append((x1, -1))
    events.sort(key=lambda e: (e[0], -e[1]))  # opens before closes at same x
    cur = 0
    peak = 0
    for _x, delta in events:
        cur += delta
        peak = max(peak, cur)

    row_w = sum(w for _n, _t, w in rows[r])
    ch_min = peak * M1_MIN_PITCH
    ch_prac = peak * PRACTICAL_PITCH
    grand_total_um_min += ch_min
    grand_total_um_practical += ch_prac
    print(f"row {r}: {len(spans)} nets, peak simultaneous horizontal spans (min M1 tracks) = {peak}"
          f"  -> channel height >= {ch_min:.1f} um (DRC min pitch), ~{ch_prac:.1f} um (practical pitch)"
          f"   [row width used {row_w:.1f}/{ROW_WIDTH_UM} um, row band height {row_height} um]")

print()
print(f"sum over all rows: >= {grand_total_um_min:.1f} um (DRC min), ~{grand_total_um_practical:.1f} um (practical)")
print(f"current total core height: {NROWS * row_height:.1f} um")
