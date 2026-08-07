"""
plan_placement.py

Computes a standard-cell row placement plan for i2c_slave_async_net.v against
the real TR-1um_STDCELL.gds cell library, subject to:

  - fixed row width ROW_WIDTH_UM (core width), minimizing row count (height)
  - SCL/SDA(in/oe)/RST_N pins escape on the LEFT block edge; everything else
    (tx_data/rx_data/rx_valid/addr_match/rw/busy/VDD/GND) escapes on the
    RIGHT block edge -- cells are biased left/right by graph distance (in
    hops over the instance-adjacency graph) to whichever port group they are
    electrically closer to, to shorten the average wire length to the
    correct edge.

This module exposes compute_rows(), used directly by gen_gds_placement.py
(no intermediate pickle file -- re-running gen_gds_placement.py regenerates
this placement from source every time).

Run standalone for a text report:
    python3 script/plan_placement.py
"""
import re
import os
import random
from collections import defaultdict, deque

import klayout.db as db

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"
GDS_LIB = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/libraries/TR-1um_STDCELL.gds"

ROW_WIDTH_UM = 1800.0
# Total cell width, measured on the real prBoundary (235/0) abutment box
# (not the padded full cell.bbox()), is ~5621um -> minimum row count at
# 1800um width is ceil(5621/1800) = 4. Since design_notes.md section 26,
# NROWS=5 is used instead: the physical structure was changed from
# "2-row zero-gap mirrored stacks sharing a rail" (4 rows, 2 hard
# no-channel boundaries) to "channel + 1 unmirrored row + channel"
# repeated 5x (every row boundary is now a real M1 channel, no more
# zero-gap boundaries at all) -- this trades a bit of extra row-count
# margin (5621/5=1124um/row vs 5621/4=1405um/row, more filler slack) for
# eliminating the hard-to-route zero-gap case entirely.
#
# A single-row (NROWS=1, ROW_WIDTH_UM=6600) variant was tried as a
# diagnostic experiment (design_notes.md section 34.2) to isolate the FO=1
# clustering effect from multi-row/multi-hop routing entirely -- see git
# history for that configuration. Not adopted for production: a
# 6600x1375um single-row die is an impractical aspect ratio. NROWS=5 /
# ROW_WIDTH_UM=1800 remains the production configuration.
NROWS = 5

# FO=1 driver/receiver clustering (design_notes.md section 34): a net with
# exactly one output-direction instance pin and exactly one input-direction
# instance pin is a simple point-to-point connection. Such pairs are fused
# into a single FM-partition node so the two cells are FORCED onto the same
# row and placed contiguously (left-right adjacent) within it, instead of
# merely being biased toward proximity by the existing L/R BFS-distance
# score. Chains (a cell that is simultaneously the receiver of one FO=1 net
# and the driver of another) grow the cluster transitively; capped at
# FO1_CLUSTER_CAP members to avoid the same "one giant group swallows
# everything" failure mode seen with the unbounded Union-Find net-grouping
# in section 30.
FO1_CLUSTER_CAP = 4

# Block-boundary pin sides (see design_notes.md section 12/13).
LEFT_PORTS = {"scl", "sda_in", "rst_n", "sda_oe"}
RIGHT_PORTS = (
    {"rx_valid", "addr_match", "rw", "busy"}
    | {f"tx_data[{i}]" for i in range(8)}
    | {f"rx_data[{i}]" for i in range(8)}
)


def _parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins


PR_LAYER = (235, 0)  # prBoundary -- the real abutment/placement boundary.
# NOTE: cell.bbox() (all layers) is NOT the abutment box: it includes a
# uniform 6.3um guard-band/well-tap overhang on both left and right (meant to
# overlap into the neighboring cell when rows/columns are correctly abutted
# at the prBoundary edges), plus an asymmetric 1.3um/6.3um vertical overhang.
# VDD/GND pin labels sit exactly on the prBoundary top/bottom edge (y=55.0 /
# y=0.0), confirming prBoundary -- not the full bbox -- is the real cell
# height/width to abut against.


def _load_cell_widths():
    """Real cell widths (um) and row height (um), read from the prBoundary
    (235/0) layer of the actual GDS library -- this is the true abutment
    box, not the full (all-layer) cell.bbox()."""
    layout = db.Layout()
    layout.read(GDS_LIB)
    dbu = layout.dbu
    pr_idx = layout.layer(*PR_LAYER)
    cell_width = {}
    row_height = None
    for c in layout.each_cell():
        pr_bbox = db.Region(c.begin_shapes_rec(pr_idx)).bbox()
        if pr_bbox.width() == 0:
            continue
        cell_width[c.name] = pr_bbox.width() * dbu
        if c.name in ("INV_X1", "NOR2", "NAND2"):
            row_height = pr_bbox.height() * dbu
    return cell_width, row_height


def _parse_netlist():
    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: _parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

    src = open(NET_FILE).read()
    port_width = {}
    port_dir = {}
    for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        kind, _, msb, lsb, name = m.groups()
        port_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
        port_dir[name] = kind
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

    return sym_pins, width_of, instances, assigns


def _canon_fn(width_of, instances, assigns):
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

    all_keys = set()
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            all_keys.add(expr)
    for k in all_keys:
        find(k)

    return find, parent


def _fm_bipartition(node_ids, nets_touching, node_weight, capacity_a, capacity_b,
                     seed_partition=None, passes=20, rng=None):
    """Fiduccia-Mattheyses 2-way balanced hypergraph min-cut partition.
    nets_touching: dict net_id -> list of node_ids (restricted to node_ids).
    Returns (dict node_id -> 'A'/'B', cut_net_count). See design_notes.md
    section 24 for why this replaced the old 1D L/R-score chop: minimizing
    the NUMBER OF NETS CUT across rows (not minimizing physical distance)
    turned out to matter far more once row0<->row1 and row2<->row3 (the
    zero-gap, no-channel row-pair boundaries) were found to have a very
    high routing failure rate (route_cross_row.py, ~50% of pins) compared
    to an in-channel net."""
    rng = rng or random.Random(42)
    # sorted(), NOT list(): plain Python sets iterate in an order that
    # depends on string hash randomization (a different, random seed every
    # process by default), so two separate invocations of compute_rows()
    # (e.g. gen_gds_placement.py's call vs. a later script re-importing and
    # calling compute_rows() again to look up which instances are in which
    # row) could silently produce DIFFERENT partitions even with the same
    # rng seed -- found when route_channel.py's fresh compute_rows() call
    # no longer agreed with what gen_gds_placement.py had actually written
    # to the placement GDS. Sorting makes the node visit order (and hence
    # every FM tie-break, which consumes from the shared rng in that order)
    # fully deterministic across processes.
    nodes = sorted(node_ids)
    node_nets = defaultdict(list)
    for net, members in nets_touching.items():
        for n in members:
            node_nets[n].append(net)

    if seed_partition is not None:
        part = dict(seed_partition)
    else:
        order = sorted(nodes, key=lambda n: -node_weight[n])
        part = {}
        wa = wb = 0.0
        for n in order:
            if wa <= wb and wa + node_weight[n] <= capacity_a:
                part[n] = 'A'
                wa += node_weight[n]
            elif wb + node_weight[n] <= capacity_b:
                part[n] = 'B'
                wb += node_weight[n]
            else:
                part[n] = 'A'
                wa += node_weight[n]

    def cut_count(p):
        c = 0
        for net, members in nets_touching.items():
            if len(set(p[m] for m in members)) > 1:
                c += 1
        return c

    def weights(p):
        wa = sum(node_weight[n] for n in nodes if p[n] == 'A')
        wb = sum(node_weight[n] for n in nodes if p[n] == 'B')
        return wa, wb

    best_part = dict(part)
    best_cut = cut_count(part)

    for _pass in range(passes):
        locked = set()
        wa, wb = weights(part)
        trace = []
        cur = dict(part)
        cur_cut = cut_count(cur)

        for _step in range(len(nodes)):
            free = [n for n in nodes if n not in locked]
            if not free:
                break
            best_gain = None
            best_n = None
            for n in free:
                side = cur[n]
                other = 'B' if side == 'A' else 'A'
                nw = node_weight[n]
                if side == 'A':
                    new_wa, new_wb = wa - nw, wb + nw
                else:
                    new_wa, new_wb = wa + nw, wb - nw
                if new_wa > capacity_a or new_wb > capacity_b:
                    continue
                gain = 0
                for net in node_nets[n]:
                    members = nets_touching[net]
                    sides_before = defaultdict(int)
                    for m in members:
                        sides_before[cur[m]] += 1
                    was_cut = len(sides_before) > 1
                    sides_after = dict(sides_before)
                    sides_after[side] -= 1
                    if sides_after[side] == 0:
                        del sides_after[side]
                    sides_after[other] = sides_after.get(other, 0) + 1
                    is_cut = len(sides_after) > 1
                    if was_cut and not is_cut:
                        gain += 1
                    elif not was_cut and is_cut:
                        gain -= 1
                if best_gain is None or gain > best_gain or (gain == best_gain and rng.random() < 0.3):
                    best_gain = gain
                    best_n = n
            if best_n is None:
                break
            n = best_n
            side = cur[n]
            other = 'B' if side == 'A' else 'A'
            cur[n] = other
            nw = node_weight[n]
            if side == 'A':
                wa, wb = wa - nw, wb + nw
            else:
                wa, wb = wa + nw, wb - nw
            locked.add(n)
            cur_cut += -best_gain if best_gain is not None else 0
            trace.append((n, cur_cut))

        running_cut = cut_count(part)
        best_prefix_cut = running_cut
        best_prefix_idx = -1
        p2 = dict(part)
        for i, (n, _cc) in enumerate(trace):
            p2[n] = 'B' if p2[n] == 'A' else 'A'
            c = cut_count(p2)
            if c < best_prefix_cut:
                best_prefix_cut = c
                best_prefix_idx = i
        if best_prefix_idx == -1:
            break
        p3 = dict(part)
        for i in range(best_prefix_idx + 1):
            n = trace[i][0]
            p3[n] = 'B' if p3[n] == 'A' else 'A'
        part = p3
        c = cut_count(part)
        if c < best_cut:
            best_cut = c
            best_part = dict(part)

    return best_part, best_cut


def _build_fo1_pairs(net_dir_members):
    """net_dir_members: canon net -> list of (instance_name, direction).
    Returns a list of (driver_name, receiver_name) for every net that has
    exactly one 'out' member and exactly one 'in' member (a true simple
    point-to-point connection -- nets with 0 or >1 driver instances, e.g.
    those driven directly by a top-level input port with no internal driver
    cell, or fanout>1 nets, are left alone)."""
    pairs = []
    for net, dm in net_dir_members.items():
        outs = [n for n, d in dm if d == 'out']
        ins = [n for n, d in dm if d == 'in']
        if len(outs) == 1 and len(ins) == 1 and outs[0] != ins[0]:
            pairs.append((outs[0], ins[0]))
    return pairs


def _cluster_fo1_pairs(all_inst, pairs, cap=FO1_CLUSTER_CAP):
    """Union-find over the FO=1 driver/receiver pair graph, size-capped at
    `cap` members per cluster. Deterministic: pairs and node visitation are
    processed in sorted order so re-running gives an identical result.
    Returns (cluster_id: name -> representative name, clusters: rep -> set
    of member names). Every instance is in exactly one cluster; instances
    untouched by any FO=1 pair form singleton clusters of themselves."""
    parent = {n: n for n in all_inst}
    members = {n: {n} for n in all_inst}

    def find(n):
        while parent[n] != n:
            n = parent[n]
        return n

    for a, b in sorted(pairs):
        if a not in parent or b not in parent:
            continue
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        if len(members[ra]) + len(members[rb]) > cap:
            continue
        if ra > rb:
            ra, rb = rb, ra
        parent[rb] = ra
        members[ra] |= members[rb]
        del members[rb]

    cluster_id = {n: find(n) for n in all_inst}
    clusters = defaultdict(set)
    for n in all_inst:
        clusters[find(n)].add(n)
    return cluster_id, dict(clusters)


def compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM, verbose=False):
    """Returns (rows, cell_width, row_height) where rows is a list of nrows
    lists of (instance_name, cell_type, width_um), left-to-right physical
    reading order within each row (row 0 = bottom, ascending upward).

    Row ASSIGNMENT (which row each instance goes to) is chosen by a
    hierarchical FM hypergraph min-cut partition (see design_notes.md
    section 24 for the original 4-row/zero-gap-pair version, section 26 for
    the current 5-row/all-real-channels version), minimizing the number of
    nets that cross a row boundary -- NOT a straight 1D L/R-score chop.
    With the physical structure now "channel + 1 unmirrored row + channel"
    repeated 5x (every boundary is a real M1 channel, no more zero-gap
    pairs), the partition tree is built to mirror the physical row CHAIN
    exactly: each FM cut corresponds to exactly one physical boundary
    (row0|row1, row1|row2, row2|row3, row3|row4), so minimizing each cut
    approximates minimizing the total number of channel-crossings a net
    needs (nets that skip more than one row still only get counted once,
    at the topmost level where they're cut -- an accepted approximation,
    same spirit as the rest of this heuristic).

    Within-row LEFT-TO-RIGHT order still uses the original L/R BFS-distance
    score (bias toward the SCL/SDA left-edge port group or the
    tx_data/rx_data/... right-edge port group), since that ordering affects
    channel-routing/block-I/O wire length quality independent of which row
    an instance landed in."""
    cell_width, row_height = _load_cell_widths()
    sym_pins, width_of, instances, assigns = _parse_netlist()
    instmap = {name: (typ, conns) for typ, name, conns in instances}
    find, parent = _canon_fn(width_of, instances, assigns)

    def canon(expr):
        return find(expr)

    net_members = defaultdict(list)
    net_dir_members = defaultdict(list)  # canon net -> [(instance_name, direction), ...]
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':  # VDD/GND: not useful for L/R graph distance
                continue
            net_members[canon(expr)].append(name)
            net_dir_members[canon(expr)].append((name, d))

    adj = defaultdict(set)
    for net, members in net_members.items():
        members = list(set(members))
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                adj[members[i]].add(members[j])
                adj[members[j]].add(members[i])

    root_keys = defaultdict(set)
    for k in list(parent.keys()):
        root_keys[find(k)].add(k)

    left_seeds, right_seeds = set(), set()
    for net, members in net_members.items():
        keys = root_keys.get(net, {net})
        if any(k in LEFT_PORTS for k in keys):
            left_seeds.update(members)
        if any(k in RIGHT_PORTS for k in keys):
            right_seeds.update(members)

    def bfs(seeds):
        dist = {s: 0 for s in seeds}
        q = deque(seeds)
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    q.append(v)
        return dist

    dist_left = bfs(left_seeds)
    dist_right = bfs(right_seeds)
    maxd = max(list(dist_left.values()) + list(dist_right.values()) + [1])

    scores = {}
    for typ, name, conns in instances:
        dl = dist_left.get(name, maxd + 1)
        dr = dist_right.get(name, maxd + 1)
        scores[name] = dl - dr  # negative => close to LEFT seeds, positive => close to RIGHT seeds

    all_inst = list(instmap.keys())
    weight = {n: cell_width[instmap[n][0]] for n in all_inst}
    total_w = sum(weight.values())
    target = total_w / nrows

    # FO=1 driver/receiver clustering (section 34): fuse simple
    # point-to-point pairs (and their up-to-FO1_CLUSTER_CAP-length chains)
    # into single FM-partition nodes so they are forced onto the same row
    # and placed contiguously within it.
    fo1_pairs = _build_fo1_pairs(net_dir_members)
    cluster_id, clusters = _cluster_fo1_pairs(all_inst, fo1_pairs, cap=FO1_CLUSTER_CAP)
    cluster_weight = {c: sum(weight[n] for n in members) for c, members in clusters.items()}
    net_members_c = {}
    for net, members in net_members.items():
        cm = sorted(set(cluster_id[m] for m in members))
        if len(cm) >= 1:
            net_members_c[net] = cm
    if verbose:
        multi = [c for c, m in clusters.items() if len(m) > 1]
        sizes = defaultdict(int)
        for c in multi:
            sizes[len(clusters[c])] += 1
        print(f"FO=1 clustering: {len(fo1_pairs)} simple pairs found, "
              f"{len(multi)} clusters with >1 member "
              f"(size distribution: {dict(sorted(sizes.items()))}), "
              f"{len(all_inst)} instances -> {len(clusters)} placement nodes")

    def nets_restricted_to(node_set):
        out = {}
        for net, members in net_members.items():
            m = [x for x in members if x in node_set]
            if len(set(m)) >= 2:
                out[net] = m
        return out

    def nets_restricted_to_c(node_set):
        out = {}
        for net, members in net_members_c.items():
            m = [x for x in members if x in node_set]
            if len(set(m)) >= 2:
                out[net] = m
        return out

    if nrows == 4:
        # Hierarchical FM partition -- see _fm_bipartition()'s docstring and
        # design_notes.md section 24. Structure fixed to match the physical
        # row pairing (row0+1 zero-gap pair, row2+3 zero-gap pair, row1/2
        # shared channel in between): split top-level into
        # lower={row0,row1} vs upper={row2,row3} first (this cut becomes
        # the CHEAP row1<->row2 shared-channel boundary), then split each
        # half into its two rows (these cuts become the EXPENSIVE zero-gap
        # row0<->row1 / row2<->row3 boundaries, so minimized hardest).
        rng = random.Random(42)
        all_set = set(all_inst)
        nets_all = nets_restricted_to(all_set)
        cap_half = 2 * row_width_um
        part_lu, cut_lu = _fm_bipartition(all_set, nets_all, weight, cap_half, cap_half,
                                           rng=rng, passes=20)
        lower = {n for n in all_set if part_lu[n] == 'A'}
        upper = {n for n in all_set if part_lu[n] == 'B'}

        nets_lower = nets_restricted_to(lower)
        part_01, cut_01 = _fm_bipartition(lower, nets_lower, weight, row_width_um, row_width_um,
                                           rng=rng, passes=20)
        row0_set = {n for n in lower if part_01[n] == 'A'}
        row1_set = {n for n in lower if part_01[n] == 'B'}

        nets_upper = nets_restricted_to(upper)
        part_23, cut_23 = _fm_bipartition(upper, nets_upper, weight, row_width_um, row_width_um,
                                           rng=rng, passes=20)
        row2_set = {n for n in upper if part_23[n] == 'A'}
        row3_set = {n for n in upper if part_23[n] == 'B'}

        row_sets = [row0_set, row1_set, row2_set, row3_set]
        if verbose:
            print(f"FM partition: top cut(lower/upper)={cut_lu}, "
                  f"row0/1 cut={cut_01}, row2/3 cut={cut_23}")
            for i, rs in enumerate(row_sets):
                w = sum(weight[n] for n in rs)
                print(f"  row{i}: {len(rs)} instances, {w:.1f}um "
                      f"({'OVER BUDGET' if w > row_width_um else 'ok'})")
    elif nrows == 5:
        # Chain-respecting recursive bisection (design_notes.md section 26):
        # every row boundary is now a real M1 channel, so there's no more
        # "cheap vs expensive boundary" distinction to bias toward -- the
        # tree is instead shaped to match physical adjacency exactly, so
        # each of the 4 FM cuts corresponds to exactly one of the 4 real
        # boundaries (row0|1, row1|2, row2|3, row3|4):
        #   top:    {row0,row1} vs {row2,row3,row4}   -> boundary row1|row2
        #   L-split: {row0} vs {row1}                  -> boundary row0|row1
        #   R-split: {row2} vs {row3,row4}              -> boundary row2|row3
        #   R2-split:{row3} vs {row4}                    -> boundary row3|row4
        # Partitioning runs at CLUSTER granularity (each FO=1 pair/chain is
        # one node, weight = sum of its members' cell widths) so a cluster
        # can never be split across a row boundary -- this is what forces
        # the FO=1 driver+receiver onto the same row (section 34).
        rng = random.Random(42)
        all_set_c = set(clusters.keys())
        nets_all = nets_restricted_to_c(all_set_c)
        # Capacities are sized around the EVEN-SPLIT target (total_w/nrows),
        # not the physical row_width_um budget -- using row_width_um*n here
        # gives FM so much slack (1800/1192 = 1.5x the actual per-row
        # target) that it happily dumps an entire row's worth of cells onto
        # one side to shave a few cut nets, leaving other rows *empty*
        # (observed: row1 got 0 instances). A tighter slack (1.28x, matching
        # the ratio that worked well for the old 4-row split) still gives
        # FM room to trade off cut count against balance, but can't leave a
        # whole row empty -- AT INSTANCE granularity. Once FO=1 clustering
        # (section 34) coarsens the FM nodes to 85 (some weighing up to 4
        # cells), 1.28 slack reproduced the exact same failure (row0 got 0
        # instances) because each node is now a much bigger "bin" relative
        # to the row budget. Re-swept SLACK empirically at cluster
        # granularity: 1.05 gives both the tightest row balance (1067-1248um
        # vs the 1192um target) AND the lowest true total channel-crossings
        # (117, vs 128-193 for 1.0/1.02/1.08) of the values tried.
        SLACK = 1.05
        cap1, cap2, cap3 = target * SLACK, 2 * target * SLACK, 3 * target * SLACK

        part_top, cut_top = _fm_bipartition(all_set_c, nets_all, cluster_weight, cap2, cap3,
                                             rng=rng, passes=20)
        lower2 = {c for c in all_set_c if part_top[c] == 'A'}   # rows 0,1
        upper3 = {c for c in all_set_c if part_top[c] == 'B'}   # rows 2,3,4

        nets_lower2 = nets_restricted_to_c(lower2)
        part_01, cut_01 = _fm_bipartition(lower2, nets_lower2, cluster_weight, cap1, cap1,
                                           rng=rng, passes=20)
        row0_c = {c for c in lower2 if part_01[c] == 'A'}
        row1_c = {c for c in lower2 if part_01[c] == 'B'}

        nets_upper3 = nets_restricted_to_c(upper3)
        part_2_34, cut_2_34 = _fm_bipartition(upper3, nets_upper3, cluster_weight, cap1, cap2,
                                               rng=rng, passes=20)
        row2_c = {c for c in upper3 if part_2_34[c] == 'A'}
        upper2 = {c for c in upper3 if part_2_34[c] == 'B'}   # rows 3,4

        nets_upper2 = nets_restricted_to_c(upper2)
        part_34, cut_34 = _fm_bipartition(upper2, nets_upper2, cluster_weight, cap1, cap1,
                                           rng=rng, passes=20)
        row3_c = {c for c in upper2 if part_34[c] == 'A'}
        row4_c = {c for c in upper2 if part_34[c] == 'B'}

        # Expand cluster-level row assignment back to instance-level sets.
        row_sets = []
        for rc in (row0_c, row1_c, row2_c, row3_c, row4_c):
            s = set()
            for c in rc:
                s |= clusters[c]
            row_sets.append(s)
        row0_set, row1_set, row2_set, row3_set, row4_set = row_sets
        if verbose:
            print(f"FM partition (5-row chain, {len(all_set_c)} cluster nodes): "
                  f"top(0,1|2,3,4)={cut_top}, "
                  f"row0|1={cut_01}, row2|3,4={cut_2_34}, row3|4={cut_34}")
            for i, rs in enumerate(row_sets):
                w = sum(weight[n] for n in rs)
                print(f"  row{i}: {len(rs)} instances, {w:.1f}um "
                      f"({'OVER BUDGET' if w > row_width_um else 'ok'})")

        # Report the TRUE final total boundary-crossing cost (not just the
        # hierarchical cut-count proxy above): for each of the 4 real
        # boundaries, count nets with >=1 member on each side, based on
        # actual final row indices -- this is the number a multi-row-span
        # net gets counted at EVERY boundary it truly crosses, unlike the
        # hierarchical proxy which only counts it once (see docstring).
        if verbose:
            row_of = {}
            for i, rs in enumerate(row_sets):
                for n in rs:
                    row_of[n] = i
            total_crossings = 0
            for b in range(4):
                c = 0
                for net, members in net_members.items():
                    rows_touched = set(row_of.get(m) for m in members if m in row_of)
                    if any(r <= b for r in rows_touched) and any(r > b for r in rows_touched):
                        c += 1
                total_crossings += c
                print(f"  true boundary{b}|{b+1} crossings: {c}")
            print(f"  true total channel-crossings (sum over 4 boundaries): {total_crossings}")
    else:
        # General chain-respecting recursive bisection (design_notes.md
        # section 34.6) for any nrows not in (4, 5): generalizes the nrows==5
        # hand-unrolled structure above -- recursively split the row-index
        # chain [0..nrows-1] at its midpoint via cluster-granularity FM
        # bipartition, so every cut again corresponds to exactly one real
        # physical row boundary. Used for the nrows==1 single-row experiment
        # (section 34.3, where it trivially returns everything in row 0 --
        # no split needed) and the nrows==6 trial (section 34.6).
        rng = random.Random(42)
        SLACK = 1.05

        def split_chain(node_set, row_labels):
            if len(row_labels) == 1:
                return {row_labels[0]: node_set}
            mid = len(row_labels) // 2
            left_labels, right_labels = row_labels[:mid], row_labels[mid:]
            cap_l = len(left_labels) * target * SLACK
            cap_r = len(right_labels) * target * SLACK
            nets_here = nets_restricted_to_c(node_set)
            part, cut = _fm_bipartition(node_set, nets_here, cluster_weight, cap_l, cap_r,
                                         rng=rng, passes=20)
            left_set = {n for n in node_set if part[n] == 'A'}
            right_set = {n for n in node_set if part[n] == 'B'}
            result = {}
            result.update(split_chain(left_set, left_labels))
            result.update(split_chain(right_set, right_labels))
            return result

        row_by_label_c = split_chain(set(clusters.keys()), list(range(nrows)))
        row_sets = []
        for i in range(nrows):
            s = set()
            for c in row_by_label_c.get(i, set()):
                s |= clusters[c]
            row_sets.append(s)
        if verbose:
            print(f"chain-split FM partition ({len(clusters)} cluster nodes, nrows={nrows}):")
            for i, rs in enumerate(row_sets):
                w = sum(weight[n] for n in rs)
                print(f"  row{i}: {len(rs)} instances, {w:.1f}um "
                      f"({'OVER BUDGET' if w > row_width_um else 'ok'})")

    # Within each row, order left-to-right by the same L/R BFS-distance
    # score as before (independent of which row FM assigned the instance
    # to) -- biases instances toward whichever block edge they are
    # electrically closer to. Instances are grouped by FO=1 cluster first
    # (section 34) so a driver/receiver pair (or chain, up to
    # FO1_CLUSTER_CAP members) always lands CONTIGUOUS in the row -- true
    # physical adjacency, not just a proximity bias -- ordered by the
    # cluster's mean score, with members inside the cluster ordered by
    # their own individual score.
    rows = [[] for _ in range(nrows)]
    row_w = [0.0] * nrows
    for i, rs in enumerate(row_sets):
        row_clusters = defaultdict(list)
        for name in rs:
            row_clusters[cluster_id[name]].append(name)

        def _cluster_score(members):
            return sum(scores[m] for m in members) / len(members)

        for c in sorted(row_clusters.keys(), key=lambda c: (_cluster_score(row_clusters[c]), c)):
            for name in sorted(row_clusters[c], key=lambda n: (scores[n], n)):
                typ = instmap[name][0]
                w = weight[name]
                rows[i].append((name, typ, w))
                row_w[i] += w

    if verbose:
        print(f"row height: {row_height} um")
        print(f"total cell width: {total_w:.1f} um, target/row: {target:.1f} um")
        print(f"rows: {nrows}, core: {row_width_um} x {nrows * row_height:.1f} um\n")
        for i in range(nrows):
            direction = "L->R"
            print(f"--- row {i} ({direction}), used {row_w[i]:.1f}/{row_width_um} um "
                  f"({100 * row_w[i] / row_width_um:.1f}%), {len(rows[i])} cells ---")
            print("  " + " ".join(t for _n, t, _w in rows[i]))

    return rows, cell_width, row_height


if __name__ == "__main__":
    compute_rows(verbose=True)
