"""
route_channels_nrow_fm.py

Section 38: N-row / (N+1)-channel router, generalizing
route_channels_2row_fm.py. Channel i sits directly below row i and
directly above row (i-1); channel 0 is the bottom margin, channel n_rows
is the top margin.

Net classification (see estimate_channel_tracks_nrow_fm.py):
  - row-only (touches 1 row r): its own interval-colored lane, split
    between channel r (below) and channel r+1 (above), exactly like the
    2-row trial. Drawn with the plain (no live-geometry-check) method,
    same as route_channels_2row_fm.py -- case-1 track-bump only.
  - adjacent-pair (touches exactly 2 consecutive rows r, r+1): forced
    onto the one channel (r+1) that touches both. Same plain method.
  - spanning (touches 3+ rows, or 2 non-adjacent rows): assigned to one
    channel from its legal range [r_min, r_max+1] (greedy least-loaded),
    same as the estimate. Every pin of a spanning net is routed with the
    hop-based live-geometry method below, since its stub may need to
    physically pass through rows/channels it doesn't own a track in.

Hop-based path resolution for spanning nets (design_notes.md section 35:
real logic cells carry no M2 besides their own pins, so a vertical M2
run can cross a row at any X the row's own pins don't use):
`build_segments()` walks the fixed row/channel Y-structure between a
pin's own row edge and its target track_y, producing an ordered list of
("channel", i, y0, y1) / ("row", i, y0, y1) segments -- literally every
region of silicon the stub's vertical run physically passes through.
`resolve_passthrough_path()` then walks that list: within a "channel"
segment the stub is free to jog to a new X (any candidate is checked
live against the actual GDS content via `begin_shapes_rec_touching`,
which recurses into cell instances, so it sees real pins AND everything
already drawn); a "row" segment must be crossed in a straight line, so
the X for it is decided one step early, while still inside the
preceding channel segment, by additionally requiring that the
candidate's row-crossing box also be clear.

FIRST VERSION OF THIS ROUTER (superseded): originally used one constant
X for a pin's entire pass-through run and only checked it against real
pins in the rows crossed -- missing the OPEN CHANNELS the run also
crosses (packed with other nets' stubs/trunks), which produced 70
chained connectivity shorts. SECOND VERSION (also superseded): checked
the whole multi-hundred-um run as a single live-geometry probe, which
correctly caught the problem but then almost never found a clear
constant X (channels here run ~30-75% track-full, so a single X clear
across several channels *and* a distant row simultaneously is a much
harder constraint than clearing them one at a time). This hop-based
version is the fix: it only ever needs one clear X within one channel
or one row's Y-band at a time, jogging between them, which is exactly
as constrained as the problem actually is.

Within-channel same-track collision handling (row-only/adjacent-pair
nets) reuses route_channels_2row_fm.py's case-1 mechanism unchanged
(bump a net to a spare track if its via pad would land Y-adjacent to
another net's pad at a colliding X) -- a coarser, DRC-invisible-short-
tolerant baseline consistent with the 2-row FM trial (7 residual shorts
there).
"""
import json
import sys
from collections import defaultdict

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_placement.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
TOP_CELL_NAME = "i2c_slave_async_nrow_fm"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
V1_LAYER = (19, 0)

M1_TRUNK_WIDTH = 1.8
M1_PAD_SIZE = 3.4
VIA_SIZE = 1.4
PAD_HALF = M1_PAD_SIZE / 2.0

TRACK_PITCH = 4.0
TRACK0_OFFSET = 2.0
LANE_MARGIN = 2.0
M2_MIN_GAP = 2.0

# must match gen_placement_gds_nrow_fm.py
CH_HEIGHTS = [90.0, 180.0, 128.0, 136.0, 100.0]

HOP_STEP = 1.0
HOP_TRIES = 700  # +-1.0 .. +-700um per hop -- fine enough to find narrow gaps
                 # between other nets' channel stubs (a 5.4um-pitch grid
                 # search missed gaps narrower than one cell-pitch step)
JOG_H = PAD_HALF * 2.0


def um(v, dbu):
    return int(round(v / dbu))


def assign_lanes(nets_subset):
    items = []
    for net, (xmin, xmax) in nets_subset.items():
        items.append((net, xmin, xmax))
    items.sort(key=lambda t: t[1])
    lane_last_x = []
    assignment = {}
    for net, xmin, xmax in items:
        placed = False
        for i, last_x in enumerate(lane_last_x):
            if last_x < xmin - LANE_MARGIN:
                assignment[net] = i
                lane_last_x[i] = xmax
                placed = True
                break
        if not placed:
            assignment[net] = len(lane_last_x)
            lane_last_x.append(xmax)
    return assignment, len(lane_last_x)


def main():
    placement = json.load(open(PLACEMENT_JSON))
    rows = placement["rows"]
    n_rows = len(rows)
    n_ch = n_rows + 1
    row_h = placement["row_height"]
    assert len(CH_HEIGHTS) == n_ch

    row_y0 = []
    ch_y0 = []
    y = 0.0
    for i in range(n_rows):
        ch_y0.append(y)
        y += CH_HEIGHTS[i]
        row_y0.append(y)
        y += row_h
    ch_y0.append(y)
    core_h = y + CH_HEIGHTS[n_rows]

    net_pins = defaultdict(list)  # net -> [(row, inst, pname, x0,y0,x1,y1), ...] (abs Y)
    for r, row_insts in enumerate(rows):
        yoff = row_y0[r]
        for inst in row_insts:
            for pname, pinfo in inst["pins"].items():
                if pinfo["use"] in ("POWER", "GROUND"):
                    continue
                for layer, x0, y0, x1, y1 in pinfo["rects"]:
                    if layer != "M2":
                        continue
                    net_pins[pinfo["net"]].append((r, inst["name"], pname, x0, y0 + yoff, x1, y1 + yoff))

    row_only = defaultdict(dict)       # row -> {net: (xmin,xmax)}
    row_only_net_row = {}              # net -> row
    adjacent_pair = defaultdict(dict)  # channel -> {net: (xmin,xmax)}
    adj_net_ch = {}                    # net -> channel
    spanning = []                      # [(net, xmin, xmax, legal_channels)]
    stub_nets = 0
    for net, pads in net_pins.items():
        if len(pads) < 2:
            stub_nets += 1
            continue
        pin_rows = sorted({p[0] for p in pads})
        xs = [(x0 + x1) / 2.0 for _r, _i, _p, x0, y0, x1, y1 in pads]
        interval = (min(xs), max(xs))
        if len(pin_rows) == 1:
            r = pin_rows[0]
            row_only[r][net] = interval
            row_only_net_row[net] = r
        elif len(pin_rows) == 2 and pin_rows[1] == pin_rows[0] + 1:
            c = pin_rows[0] + 1
            adjacent_pair[c][net] = interval
            adj_net_ch[net] = c
        else:
            legal = list(range(pin_rows[0], pin_rows[-1] + 2))
            spanning.append((net, interval[0], interval[1], legal))

    row_only_lanes = {r: assign_lanes(row_only[r]) for r in range(n_rows)}

    span_channel_assign = {}
    span_pool = defaultdict(dict)
    running_count = [0] * n_ch
    for net, xmin, xmax, legal in spanning:
        c = min(legal, key=lambda ch: running_count[ch])
        running_count[c] += 1
        span_channel_assign[net] = c
        span_pool[c][net] = (xmin, xmax)
    span_lanes = {c: assign_lanes(span_pool[c]) for c in range(n_ch)}
    adj_lanes = {c: assign_lanes(adjacent_pair[c]) for c in range(n_ch)}

    block_offset = [dict() for _ in range(n_ch)]
    channel_total = [0] * n_ch
    for c in range(n_ch):
        off = 0
        if c - 1 >= 0:
            _a, n = row_only_lanes[c - 1]
            n_bottom = -(-n // 2)
            n_upper = n - n_bottom
            block_offset[c]["row_below_upper"] = (off, n_bottom)
            off += n_upper
        if c <= n_rows - 1:
            _a, n = row_only_lanes[c]
            n_bottom = -(-n // 2)
            block_offset[c]["row_above_lower"] = (off,)
            off += n_bottom
        _a, n = adj_lanes[c]
        block_offset[c]["adjacent_pair"] = (off,)
        off += n
        _a, n = span_lanes[c]
        block_offset[c]["spanning"] = (off,)
        off += n
        channel_total[c] = off

    print("channel primary track usage:", channel_total)

    def channel_primary(net):
        if net in row_only_net_row:
            r = row_only_net_row[net]
            a, n = row_only_lanes[r]
            lane = a[net]
            n_bottom = -(-n // 2)
            if lane < n_bottom:
                c = r
                off, = block_offset[c]["row_above_lower"]
                return c, off + lane
            else:
                c = r + 1
                off, n_bot = block_offset[c]["row_below_upper"]
                return c, off + (lane - n_bottom)
        if net in adj_net_ch:
            c = adj_net_ch[net]
            a, n = adj_lanes[c]
            lane = a[net]
            off, = block_offset[c]["adjacent_pair"]
            return c, off + lane
        c = span_channel_assign[net]
        a, n = span_lanes[c]
        lane = a[net]
        off, = block_offset[c]["spanning"]
        return c, off + lane

    next_free_idx = list(channel_total)
    channel_used_x = defaultdict(list)  # (channel, idx) -> [cx, ...]
    MIN_VIA_X_SEP = M1_PAD_SIZE + 1.4

    def collides(channel, idx, cxs):
        for nb in (idx - 1, idx, idx + 1):
            for ux in channel_used_x.get((channel, nb), []):
                for cx in cxs:
                    if abs(cx - ux) < MIN_VIA_X_SEP:
                        return True
        return False

    non_spanning_nets = {}
    non_spanning_nets.update({n: p for n, p in net_pins.items() if n in row_only_net_row})
    non_spanning_nets.update({n: p for n, p in net_pins.items() if n in adj_net_ch})
    spanning_nets = {n: p for n, p in net_pins.items() if n in span_channel_assign}

    final_track = {}
    bumped = 0
    for net, pads in list(non_spanning_nets.items()) + list(spanning_nets.items()):
        channel, idx = channel_primary(net)
        cxs = [(x0 + x1) / 2.0 for _r, _i, _p, x0, y0, x1, y1 in pads]
        if collides(channel, idx, cxs):
            bumped += 1
            idx = next_free_idx[channel]
            next_free_idx[channel] += 1
            while collides(channel, idx, cxs):
                idx = next_free_idx[channel]
                next_free_idx[channel] += 1
        channel_used_x[(channel, idx)].extend(cxs)
        track_y = ch_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH
        final_track[net] = (channel, track_y)
    if bumped:
        print(f"case-1 collisions resolved by moving {bumped} net(s) to a spare track")

    for c in range(n_ch):
        budget = int((CH_HEIGHTS[c] - 2 * TRACK0_OFFSET) // TRACK_PITCH) + 1
        used = next_free_idx[c]
        status = "OK" if used <= budget else "OVERFLOW"
        print(f"  channel{c}: used {used} tracks, budget {budget} ({CH_HEIGHTS[c]} um) -> {status}")

    # fixed Y-structure boundaries, used by build_segments()
    struct = []
    for i in range(n_rows):
        struct.append(("channel", i, ch_y0[i], ch_y0[i] + CH_HEIGHTS[i]))
        struct.append(("row", i, row_y0[i], row_y0[i] + row_h))
    struct.append(("channel", n_rows, ch_y0[n_rows], ch_y0[n_rows] + CH_HEIGHTS[n_rows]))

    def build_segments(pin_edge_y, track_y, direction):
        y_lo, y_hi = min(pin_edge_y, track_y), max(pin_edge_y, track_y)
        segs = []
        for typ, i, ylo, yhi in struct:
            clo, chi = max(ylo, y_lo), min(yhi, y_hi)
            if clo < chi - 1e-9:
                segs.append((typ, i, clo, chi))
        if direction < 0:
            segs = list(reversed(segs))
        # the leading segment, if it's a "row", is always just the tail of
        # the PIN'S OWN row between pin_edge_y and that row's boundary (the
        # pin always starts strictly inside its own row) -- that is normal
        # in-cell stub routing, not a foreign obstacle to route around, so
        # drop it (its geometry is drawn as part of the first real channel
        # hop's starting box instead).
        start_y = pin_edge_y
        if segs and segs[0][0] == "row":
            _typ, _i, rlo, rhi = segs[0]
            start_y = rhi if direction > 0 else rlo
            segs = segs[1:]
        return segs, start_y

    # --- open the layout now so pass-through resolution can query live
    # GDS content (real pins + everything already drawn) ---
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL_NAME)
    m1_idx = layout.layer(*M1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)
    v1_idx = layout.layer(*V1_LAYER)

    def m1_box(x0, y0, x1, y1):
        top.shapes(m1_idx).insert(db.Box(um(x0, dbu), um(y0, dbu), um(x1, dbu), um(y1, dbu)))

    def m2_box(x0, y0, x1, y1):
        top.shapes(m2_idx).insert(db.Box(um(x0, dbu), um(y0, dbu), um(x1, dbu), um(y1, dbu)))

    def via_box(cx, cy):
        h = VIA_SIZE / 2.0
        top.shapes(v1_idx).insert(db.Box(um(cx - h, dbu), um(cy - h, dbu), um(cx + h, dbu), um(cy + h, dbu)))

    # DRC's rule is "space >= M2_MIN_GAP" (exactly-at-minimum is legal), but
    # begin_shapes_rec_touching treats an exactly-touching probe edge as a
    # hit -- and this design places pins on a strict grid where many real
    # neighbors sit at EXACTLY the minimum clearance, so a literal margin
    # of M2_MIN_GAP rejects perfectly legal positions (including a pin's
    # own natural, already-legal X). Shave a tiny epsilon off the search
    # margin so exact-minimum spacing reads as clear; the boxes actually
    # drawn are unchanged, so real spacing is still >= M2_MIN_GAP.
    CHECK_MARGIN = M2_MIN_GAP - 0.01

    def boxes_clear(boxes, margin=CHECK_MARGIN):
        for x0, y0, x1, y1 in boxes:
            probe = db.Box(um(x0 - margin, dbu), um(y0, dbu), um(x1 + margin, dbu), um(y1, dbu))
            if db.Region(top.begin_shapes_rec_touching(m2_idx, probe)).count() > 0:
                return False
        return True

    WALK_STEP_Y = 5.4     # height of each independent walk segment
    WALK_X_STEP = 1.0     # x resolution when a segment needs to jog
    WALK_X_TRIES = 400    # +-1.0 .. +-400um search per segment
    MAX_TARGETS_TRIED = 150  # how many candidate target X's to fully walk to

    def target_candidates(cur_x, verify_x):
        cands = [cur_x]
        for s in range(1, WALK_X_TRIES + 1):
            cands.append(cur_x + s * WALK_X_STEP)
            cands.append(cur_x - s * WALK_X_STEP)
        if verify_x is None:
            return cands[:1]
        out = []
        for c in cands:
            if verify_x(c):
                out.append(c)
                if len(out) >= MAX_TARGETS_TRIED:
                    break
        return out

    def walk_to_target(cur_x, cur_y, y_arrive, direction, target_x):
        """Walk from (cur_x,cur_y) to y_arrive in short WALK_STEP_Y-tall
        segments toward one fixed target X. At every step the walker
        retries a full jump straight to target_x first; if that band
        happens to be blocked it nudges a little closer instead and tries
        again next step, with a last-resort drift-away escape on non-final
        steps. Returns (new_x, boxes) or None if this particular target_x
        turns out to be unreachable from here."""
        x, y = cur_x, cur_y
        boxes = []
        while (direction > 0 and y < y_arrive - 1e-9) or (direction < 0 and y > y_arrive + 1e-9):
            y_next = y + direction * WALK_STEP_Y
            y_next = min(y_next, y_arrive) if direction > 0 else max(y_next, y_arrive)
            seg_ylo, seg_yhi = (y, y_next) if direction > 0 else (y_next, y)
            is_final_seg = abs(y_next - y_arrive) < 1e-9

            if abs(target_x - x) < 1e-6:
                cand_list = [x]
            else:
                cand_list = [target_x]
                step_dir = 1 if target_x > x else -1
                n_steps = int(abs(target_x - x) / WALK_X_STEP)
                for s in range(1, n_steps + 1):
                    cand_list.append(x + step_dir * s * WALK_X_STEP)
                if not is_final_seg:
                    for s in range(1, WALK_X_TRIES + 1):
                        cand_list.append(x + s * WALK_X_STEP)
                        cand_list.append(x - s * WALK_X_STEP)

            found = None
            for cand in cand_list:
                if is_final_seg and abs(cand - target_x) > 1e-6:
                    continue  # must land exactly on target_x by the end
                if abs(cand - x) < 1e-6:
                    box = (x - PAD_HALF, seg_ylo, x + PAD_HALF, seg_yhi)
                else:
                    box = (min(x, cand) - PAD_HALF, seg_ylo, max(x, cand) + PAD_HALF, seg_yhi)
                if boxes_clear([box]):
                    found = (cand, box)
                    break
            if found is None:
                return None
            x, box = found
            boxes.append(box)
            y = y_next
        return x, boxes

    def try_reach(cur_x, cur_y, y_arrive, direction, verify_x):
        """Try walking to each candidate target X (nearest first) until one
        works end to end. A single fixed target can be unreachable even
        though it individually satisfies verify_x -- e.g. the row/channel
        boundary is a natural chokepoint every net crossing it must pass
        through, so the nearest legal target sometimes sits behind a wall
        of other nets' stubs at every step along the way, while a slightly
        farther legal target has a clear lane the whole distance. Trying
        several, not just the first, is what makes this findable."""
        import os
        debug = os.environ.get("ROUTE_DEBUG")
        tcands = target_candidates(cur_x, verify_x)
        if debug:
            print(f"    try_reach: cur_x={cur_x} cur_y={cur_y} y_arrive={y_arrive} "
                  f"direction={direction} n_targets={len(tcands)} "
                  f"first5={tcands[:5]}")
        for ti, target_x in enumerate(tcands):
            result = walk_to_target(cur_x, cur_y, y_arrive, direction, target_x)
            if result is not None:
                if debug:
                    print(f"    try_reach: succeeded with target #{ti}={target_x}")
                return result
        if debug:
            print(f"    try_reach EXHAUSTED all {len(tcands)} targets from x={cur_x} to y_arrive={y_arrive}")
        return None

    class PathBlocked(Exception):
        pass

    def resolve_passthrough_path(cx, pin_edge_y, track_y, direction, segs, start_y):
        cur_x, cur_y = cx, start_y
        all_boxes = []
        if start_y != pin_edge_y:
            # the piece of stub still inside the pin's own row (from the pin
            # edge to the row/channel boundary) -- always safe, same as any
            # ordinary direct stub drawn elsewhere in this router
            y0, y1 = min(pin_edge_y, start_y), max(pin_edge_y, start_y)
            all_boxes.append((cx - PAD_HALF, y0, cx + PAD_HALF, y1))
        for seg_idx, (typ, i, ylo, yhi) in enumerate(segs):
            if typ == "row":
                box = (cur_x - PAD_HALF, ylo, cur_x + PAD_HALF, yhi)
                if not boxes_clear([box]):
                    raise PathBlocked(f"row {i} crossing unexpectedly blocked at x={cur_x}")
                all_boxes.append(box)
                cur_y = yhi if direction > 0 else ylo
            else:
                is_last = (seg_idx == len(segs) - 1)
                y_target = yhi if direction > 0 else ylo
                if is_last:
                    verify_x = lambda cand: True
                else:
                    nylo, nyhi = segs[seg_idx + 1][2], segs[seg_idx + 1][3]
                    verify_x = lambda cand, a=nylo, b=nyhi: boxes_clear(
                        [(cand - PAD_HALF, a, cand + PAD_HALF, b)])
                result = try_reach(cur_x, cur_y, y_target, direction, verify_x)
                if result is None:
                    raise PathBlocked(f"could not route through channel {i} near x={cur_x}")
                cur_x, seg_boxes = result
                all_boxes.extend(seg_boxes)
                cur_y = y_target
        return cur_x, all_boxes

    pin_map = {}
    routed = 0
    passthrough_count = 0
    fallback_count = 0

    # pass 1: plain method for row-only / adjacent-pair nets (unchanged
    # from route_channels_2row_fm.py -- no live-geometry check)
    for net, pads in non_spanning_nets.items():
        channel, track_y = final_track[net]
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1
            y_lo, y_hi = min(pin_edge_y, track_y), max(pin_edge_y, track_y)
            m2_box(cx - PAD_HALF, y_lo, cx + PAD_HALF, y_hi)
            via_box(cx, track_y)
            m1_box(cx - PAD_HALF, track_y - PAD_HALF, cx + PAD_HALF, track_y + PAD_HALF)
            pin_cxs.append(cx)
            pin_map.setdefault(net, []).append((inst_name, pname, cx, track_y))
        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1

    # pass 2: hop-based live-geometry method for every pin of every
    # spanning net (both pins directly adjacent to the target channel and
    # pins that must pass through intervening rows/channels)
    for net, pads in spanning_nets.items():
        channel, track_y = final_track[net]
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1
            segs, start_y = build_segments(pin_edge_y, track_y, direction)
            n_row_segs = sum(1 for s in segs if s[0] == "row")
            if n_row_segs > 0:
                passthrough_count += 1
            try:
                final_x, boxes = resolve_passthrough_path(cx, pin_edge_y, track_y, direction, segs, start_y)
            except PathBlocked:
                # Some spanning-net pins sit in channels dense enough (this
                # 4-row stack's channels run 40-78% track-utilized) that no
                # legal jog path exists within the search budget -- the same
                # fundamental difficulty documented in design_notes.md 37.4/
                # 37.6 for the 2-row trial's "case 2", just at a much smaller
                # scale now (a handful of pins, not hundreds). Rather than
                # hang indefinitely searching, fall back to the plain direct
                # stub (same method as row-only/adjacent-pair nets) so the
                # router finishes and the true short count -- some of these
                # fallbacks may or may not actually collide -- is measured
                # by DRC + connectivity, not guessed at here.
                fallback_count += 1
                y0f, y1f = min(pin_edge_y, track_y), max(pin_edge_y, track_y)
                final_x, boxes = cx, [(cx - PAD_HALF, y0f, cx + PAD_HALF, y1f)]
            for x0b, y0b, x1b, y1b in boxes:
                m2_box(x0b, y0b, x1b, y1b)
            via_box(final_x, track_y)
            m1_box(final_x - PAD_HALF, track_y - PAD_HALF, final_x + PAD_HALF, track_y + PAD_HALF)
            pin_cxs.append(final_x)
            pin_map.setdefault(net, []).append((inst_name, pname, final_x, track_y))
        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1

    layout.write(OUT_GDS)

    pin_map_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
    with open(pin_map_path, "w") as f:
        json.dump(pin_map, f, indent=1)

    print(f"wrote {OUT_GDS}")
    print(f"wrote {pin_map_path}")
    print(f"signal nets: {len(net_pins)}, routed: {routed}, stubs: {stub_nets}")
    print(f"row-only={sum(len(v) for v in row_only.values())}, "
          f"adjacent-pair={sum(len(v) for v in adjacent_pair.values())}, spanning={len(spanning)}")
    print(f"spanning-net pins requiring a row pass-through: {passthrough_count}")
    print(f"spanning-net pins that fell back to a plain (unchecked) stub: {fallback_count}")


if __name__ == "__main__":
    main()
