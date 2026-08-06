"""
route_all_channels.py

Orchestrates channel routing for the new 5-row/6-channel physical structure
(design_notes.md section 26): every row boundary is now a real M1 channel
(no more zero-gap pairs), so this script:

  1. Derives the 6 channels (2 dedicated end-margins + 4 shared/inter-row)
     directly from gen_gds_placement.py's PHYSICAL_ROWS -- no hardcoded
     phys_row_index/channel_bottom_y/channel_height constants to keep in
     sync by hand any more.
  2. Classifies every net by which row(s) it touches:
       - 1 row  -> "row-only": split roughly evenly between that row's TWO
         candidate channels (every row now touches 2 channels, one on each
         side) so the same net isn't routed twice.
       - 2 ADJACENT rows -> routed via their shared channel. This is new:
         previously (zero-gap-pair era) cross-row nets had no channel to
         route through at all and were never actually routed (only
         minimized via placement -- see design_notes.md section 24/25's
         "pending: cross-row net routing" note). Now that every adjacent
         pair has a real channel, this finally gets solved for adjacent
         pairs.
       - non-adjacent or 3+ rows -> "multi-hop": still unhandled (would
         need to be routed through more than one channel in series) --
         reported at the end, not routed.
  3. Calls route_channel.route_row_channel() for the 2 end channels and
     route_channel_shared.route_shared_channel() for the 4 inter-row
     channels, each with an explicit allowed_nets set so nothing is
     double-routed.

Usage:
    python3 script/route_all_channels.py
"""
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS  # noqa: E402
from gen_gds_placement import PHYSICAL_ROWS  # noqa: E402
import route_channel as rc  # noqa: E402
import route_channel_shared as rcs  # noqa: E402

ROW_HEIGHT = rc.ROW_HEIGHT
NET_FILE = rc.NET_FILE
STDCELL_DIR = rc.STDCELL_DIR
OUT_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout"
PINMAP_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs"


def _parse_nets():
    """Minimal netlist parse (instance -> pins, canonicalized via assign
    aliasing) -- just enough to classify nets by which row(s) they touch.
    Duplicates route_channel.py's parsing logic (same precedent as
    route_channel_shared.py already duplicating it) since it's only used
    here for classification, not for anchor/geometry computation."""
    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: rc.parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

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

    net_pins = defaultdict(list)
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':  # VDD/GND
                continue
            net_pins[canon(expr)].append((name, typ, pin))
    return net_pins


def derive_channels():
    """Scan PHYSICAL_ROWS for runs of None (filler-only physical rows) and
    return a list of dicts: bottom_y, height, lower (row idx or None),
    upper (row idx or None). lower=None means this is the bottom margin
    (only `upper` touches it); upper=None means the top margin."""
    channels = []
    cur_none_start = None
    prev_row = None
    n = len(PHYSICAL_ROWS)
    for i, e in enumerate(PHYSICAL_ROWS):
        if e is None:
            if cur_none_start is None:
                cur_none_start = i
        else:
            if cur_none_start is not None:
                cnt = i - cur_none_start
                channels.append(dict(bottom_y=cur_none_start * ROW_HEIGHT, height=cnt * ROW_HEIGHT,
                                      lower=prev_row, upper=e))
                cur_none_start = None
            prev_row = e
    if cur_none_start is not None:
        cnt = n - cur_none_start
        channels.append(dict(bottom_y=cur_none_start * ROW_HEIGHT, height=cnt * ROW_HEIGHT,
                              lower=prev_row, upper=None))
    return channels


def channel_name(c):
    lo = c["lower"] if c["lower"] is not None else "bm"
    hi = c["upper"] if c["upper"] is not None else "tm"
    return f"ch{lo}_{hi}"


def main():
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)
    phys_of_row = {}
    for i, e in enumerate(PHYSICAL_ROWS):
        if e is not None:
            phys_of_row[e] = i

    row_of = {}
    for i, row in enumerate(rows):
        for n, t, w in row:
            row_of[n] = i

    net_pins = _parse_nets()
    net_rows = {}
    for net, pins in net_pins.items():
        rs = set(row_of[p[0]] for p in pins if p[0] in row_of)
        net_rows[net] = rs

    row_only_nets = defaultdict(list)
    adjacent_pair_nets = defaultdict(list)
    multi_hop_nets = []
    for net, rs in net_rows.items():
        if len(rs) == 0:
            continue
        elif len(rs) == 1:
            row_only_nets[next(iter(rs))].append(net)
        elif len(rs) == 2:
            a, b = sorted(rs)
            if b == a + 1:
                adjacent_pair_nets[(a, b)].append(net)
            else:
                multi_hop_nets.append((net, rs))
        else:
            multi_hop_nets.append((net, rs))

    total_nets = sum(len(v) for v in row_only_nets.values()) + \
        sum(len(v) for v in adjacent_pair_nets.values()) + len(multi_hop_nets)
    print(f"net classification: {sum(len(v) for v in row_only_nets.values())} row-only, "
          f"{sum(len(v) for v in adjacent_pair_nets.values())} adjacent-pair, "
          f"{len(multi_hop_nets)} multi-hop (unrouted), {total_nets} total")

    channels = derive_channels()
    print(f"{len(channels)} channels derived from PHYSICAL_ROWS:")
    for c in channels:
        print(f"  {channel_name(c)}: y=[{c['bottom_y']:.1f},{c['bottom_y']+c['height']:.1f}] "
              f"({c['height']:.1f}um), lower={c['lower']}, upper={c['upper']}")

    touches = defaultdict(list)  # row_idx -> [(channel_dict, escape_dir_for_this_row), ...]
    for c in channels:
        if c["lower"] is not None:
            touches[c["lower"]].append((c, "up"))
        if c["upper"] is not None:
            touches[c["upper"]].append((c, "down"))

    channel_allowed = defaultdict(set)  # id(channel) -> set of net names
    for row_idx, nets in row_only_nets.items():
        cands = touches[row_idx]
        if len(cands) == 1:
            for net in nets:
                channel_allowed[id(cands[0][0])].add(net)
            continue
        # Group row-only nets that share an INSTANCE before alternating
        # between this row's two candidate channels -- splitting plain
        # net-by-net (round robin) can send two different pins of the SAME
        # cell to two DIFFERENT channels (one routed via the channel below,
        # the other via the channel above); since the two channels are
        # routed independently, neither one's obstruction scan ever
        # considers the other pin even though they sit only a few um apart
        # on the same cell, and a residual M2 spacing violation results
        # (design_notes.md section 28.2). Keeping every net that touches a
        # given instance together in one channel eliminates this class.
        uf = {}

        def find(k):
            uf.setdefault(k, k)
            while uf[k] != k:
                uf[k] = uf[uf[k]]
                k = uf[k]
            return k

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                uf[ra] = rb

        inst_to_nets = defaultdict(list)
        for net in nets:
            for inst in set(p[0] for p in net_pins[net]):
                inst_to_nets[inst].append(net)
        for inst, ns in inst_to_nets.items():
            for i in range(1, len(ns)):
                union(ns[0], ns[i])

        groups = defaultdict(list)
        for net in nets:
            groups[find(net)].append(net)
        # Balance by NET COUNT, not group count: same-instance grouping can
        # collapse many nets into a few groups via transitive union (e.g. a
        # 45-net row collapsing into 5 groups with one 37-net group), so a
        # simple round-robin over group INDEX can dump the vast majority of
        # a row's nets into just one of its two candidate channels while
        # the other sits nearly empty (observed: row4 -> ch3_4 got 41 nets,
        # ch4_tm got only 4, out of 45 total -- design_notes.md section 30).
        # Greedy balance instead: process groups largest-first, always
        # assign the whole group to whichever candidate channel currently
        # has the smaller net count so far.
        cand_load = [0] * len(cands)
        for key in sorted(groups.keys(), key=lambda k: -len(groups[k])):
            ci = min(range(len(cands)), key=lambda i: cand_load[i])
            c, _dir = cands[ci]
            for net in groups[key]:
                channel_allowed[id(c)].add(net)
            cand_load[ci] += len(groups[key])

    for (a, b), nets in adjacent_pair_nets.items():
        for c in channels:
            if c["lower"] == a and c["upper"] == b:
                channel_allowed[id(c)].update(nets)
                break

    accum_gds = rc.IN_GDS  # pristine placement-only base; chained across channels below
    for c in channels:
        allowed = channel_allowed.get(id(c), set())
        name = channel_name(c)
        print(f"\n=== channel {name}: {len(allowed)} nets assigned ===")
        if not allowed:
            print("  (nothing to route, skipping -- carrying forward previous accumulated GDS)")
            continue
        out_gds = f"{OUT_DIR}/i2c_slave_async_layout_routed_{name}.gds"
        pin_map_json = f"{PINMAP_DIR}/{name}_pin_map.json"
        # Sequential accumulation (design_notes.md section 26.8): each
        # channel reads the PREVIOUS channel's output (not the pristine
        # base) as its input, so its obstruction-avoidance scan can see
        # whatever a sibling channel touching the same row already routed.
        # channels is in bottom-to-top physical order (derive_channels()
        # scans PHYSICAL_ROWS top-to-bottom... no, bottom-to-top, index 0 =
        # bottom), matching the chain direction.
        in_gds = accum_gds
        # mirrored must match gen_gds_placement.py's own (phys_idx % 2 ==
        # 1) alternating mirror, now applied to every physical row
        # (design_notes.md section 27) -- no longer hardcoded False.
        if c["lower"] is None:
            row_idx = c["upper"]
            pri = phys_of_row[row_idx]
            rc.route_row_channel(
                logical_row_idx=row_idx, phys_row_index=pri, mirrored=(pri % 2 == 1),
                channel_bottom_y=c["bottom_y"], channel_height=c["height"], escape_dir="down",
                out_gds=out_gds, pin_map_json=pin_map_json, allowed_nets=allowed, in_gds=in_gds)
        elif c["upper"] is None:
            row_idx = c["lower"]
            pri = phys_of_row[row_idx]
            rc.route_row_channel(
                logical_row_idx=row_idx, phys_row_index=pri, mirrored=(pri % 2 == 1),
                channel_bottom_y=c["bottom_y"], channel_height=c["height"], escape_dir="up",
                out_gds=out_gds, pin_map_json=pin_map_json, allowed_nets=allowed, in_gds=in_gds)
        else:
            pri_lo = phys_of_row[c["lower"]]
            pri_hi = phys_of_row[c["upper"]]
            row_cfgs = [
                dict(logical_row_idx=c["lower"], phys_row_index=pri_lo,
                     mirrored=(pri_lo % 2 == 1), escape_dir="up"),
                dict(logical_row_idx=c["upper"], phys_row_index=pri_hi,
                     mirrored=(pri_hi % 2 == 1), escape_dir="down"),
            ]
            rcs.route_shared_channel(
                row_cfgs=row_cfgs, channel_bottom_y=c["bottom_y"], channel_height=c["height"],
                out_gds=out_gds, pin_map_json=pin_map_json, allowed_nets=allowed, in_gds=in_gds)
        accum_gds = out_gds

    final_gds = f"{OUT_DIR}/i2c_slave_async_layout_routed_all.gds"
    if accum_gds != final_gds:
        import shutil
        shutil.copyfile(accum_gds, final_gds)
    print(f"\nfinal merged (all 6 channels accumulated in sequence): {final_gds}")

    if multi_hop_nets:
        print(f"\n{len(multi_hop_nets)} multi-hop net(s) NOT routed (span non-adjacent or 3+ rows):")
        for net, rs in multi_hop_nets:
            print(f"  - net={net} rows={sorted(rs)}")


if __name__ == "__main__":
    main()
