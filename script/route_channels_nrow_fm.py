"""
route_channels_nrow_fm.py (v3)

Section 38: N-row / (N+1)-channel router, generalizing
route_channels_2row_fm.py. Channel i sits directly below row i and
directly above row (i-1); channel 0 is the bottom margin, channel n_rows
is the top margin.

v3 CHANGES (user-directed rework of the v2 spanning-net router):

  1. Every via in this router -- pin-to-track connections AND the new
     jog vias below -- is now a `via_1` PCell instance (TR-1um library,
     klayout/tech/python/cells/via.py: a DRC-legal V1 cut array + M1 pad
     + M2 pad in one cell) instead of three raw boxes drawn by hand.

  2. Spanning nets no longer move in X by sweeping a wide M2 box from
     the old position to the new one (v2's method -- functionally fine
     but visually and structurally not how this design routes anything
     else: M2 stayed vertical everywhere else). Now M2 is vertical only,
     always. To change X inside a channel: via_1 (M2->M1) at a track_y
     that is one of that channel's real M1 tracks -> M1 runs
     horizontally (a plain wire, not a via) to the new X -> via_1
     (M1->M2) -> M2 continues vertically. This mirrors how a real
     detailed router alternates preferred directions per layer, and
     means every M1/M2 shape this router draws is a plain vertical or
     horizontal rectangle -- no more diagonal-looking wide sweeps.

  3. Grid discipline: every X used by a jog (both via_1 endpoints and
     the connecting M1 run) is reached by stepping in exact 5.4um
     increments from a position that is already on-grid (a real pin's
     own X, which sits on this grid by construction: cell widths are
     multiples of 5.4um). Every jog's M1 run happens at a track_y on
     the channel's own existing 4.0um-pitch track grid
     (ch_y0[c] + TRACK0_OFFSET + idx*TRACK_PITCH) -- the SAME shared
     track pool used by row-only/adjacent-pair nets' trunks, not a
     separate reservation. A jog always claims a *fresh* track index
     (bumped off next_free_idx, same mechanism as the case-1 spare-
     track bump below) precisely so its M1 run is guaranteed to have
     that entire track to itself -- no live-geometry collision search
     is needed for the run itself, only the same Y-adjacent-track via
     proximity check (case 1) applied to its two via_1 endpoints.

  4. Because jog tracks are always fresh/exclusive, resolving a
     spanning-net pin's path collapses to a much simpler problem than
     v2's multi-candidate walk: for each row it must cross, find one X
     clear of that row's real cell M2 (a simple grid-stepped local
     search, `find_row_clear_x`), and if that X differs from the
     current X, insert exactly one jog to get there. No channel-wide
     live-geometry walking is needed at all, because channel obstacles
     (other nets' trunks/pads) can no longer be hit -- the jog's M1 run
     lives on a track nothing else will ever use.

  5. TAP2 power mesh: TAP2's own VDD/GND M2 straps run the full height
     of the cell (section 35.9) but stopped at each row's edge with no
     link to the next row's TAP column across the channel between them.
     `draw_tap_power_mesh()` adds M2 straps through every channel at
     every TAP column's VDD/GND X, connecting the whole stack into one
     continuous vertical power mesh. These straps' X ranges are also
     registered as forbidden for signal routing (`x_forbidden`), so the
     row-crossing search for spanning nets won't pick an X that lands
     on a power strap.

v2's docstring (single-X-then-two-live-geometry-search redesigns, 70
shorts down to 25 with a 10-pin fallback) is preserved in git history
for anyone who needs the earlier reasoning; this version replaces that
mechanism entirely rather than layering on top of it.

v4 CHANGES (design_notes 38.8 -- two targeted mitigations for the
remaining case-2 shorts, root-caused in 38.6/38.7):

  6. High-fan-out (HIGH_FO_THRESHOLD=8 pins) row-only/adjacent-pair
     nets (clock/reset buffer trees like scl_buf0/scl_buf1/_126_buf0
     etc., with 13-15 pins spread across most of the row) draw an M1
     trunk spanning most of the channel's width. `collides()`/
     `claim_track()` only ever check DISCRETE registered pin X's
     against nearby tracks -- they have no notion of the CONTINUOUS
     span a wide trunk will occupy, so an unrelated net on an adjacent
     track index, with a via nowhere near any of the wide net's actual
     pins, can still end up geometrically under that trunk. Fix: these
     nets are pulled out of the normal lane-assignment pools and given
     a dedicated track region at the front of their channel, processed
     (assigned + drawn) FIRST, with HIGH_FO_GUARD_TRACKS empty tracks
     left on either side of each one -- a purely Y-based separation
     that makes the trunk's X-span irrelevant (no other net's via can
     be within reach regardless of X).

  7. Row-only/adjacent-pair nets whose pin X falls inside a channel's
     "forced overlap zone" -- the X range where the two rows sharing
     that channel both have real-cell content, which left/right row
     anchoring (38.7) cannot avoid once combined demand exceeds the
     available separation budget -- now get a live collision check
     (`channel_clear`, querying the M1/M2 already drawn in that exact
     box) before their straight stub is drawn. On a hit, a jog (same
     via_1+M1+via_1 pattern as spanning-net jogs, on a freshly claimed
     track) reroutes around it. This reuses the exact mechanism §37.6
     found did not scale when applied to an ENTIRE channel's stub
     population; scoping it to just the (typically narrow) forced-
     overlap zone keeps the checked population small.

  8. (design_notes 38.8, user proposal, REPLACES point 6 for these
     four specific nets) scl_buf0/scl_buf1/_126_buf0/_126_buf1 -- the
     highest fan-out nets, whose pins spread across MULTIPLE rows --
     no longer get ONE shared M1 trunk in ONE channel at all. Instead
     each row that has pins of one of these nets gets its OWN LOCAL M1
     trunk in the channel directly below that row (never shared with
     any other row), on its own dedicated+guarded track (same Y-based
     isolation idea as point 6, just scoped per (net, row) instead of
     per net). These per-row local trunks are then tied into one
     electrical net by a vertical M2 "spine" that reuses the exact
     row-crossing machinery spanning nets already use (`find_row_clear_x`
     + `draw_jog`) to hop from one row's local trunk, through any
     intervening rows, to the next row's local trunk. This trades
     routing redundancy (a real wire per row instead of one shared
     wire) for a structural guarantee: since no two rows ever share a
     track for these nets, the cross-row collision these nets were
     causing (design_notes 38.8's traced 12-net blob) cannot occur for
     them by construction, independent of trunk width.
"""
import json
import sys
from collections import defaultdict

import klayout.db as db

TECH_PY_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/tech/python"
sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
sys.path.insert(0, TECH_PY_DIR)
import pya  # noqa: E402  (klayout's pya compatibility shim -- pya.X is klayout.db.X)
from cells import tr_1um  # noqa: E402

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_placement.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
TOP_CELL_NAME = "i2c_slave_async_nrow_fm"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
V1_LAYER = (19, 0)

M1_TRUNK_WIDTH = 1.8
M1_PAD_SIZE = 3.4        # via_1 default pad size (Wmin), matches the old raw-box pad
PAD_HALF = M1_PAD_SIZE / 2.0

TRACK_PITCH = 4.0
TRACK0_OFFSET = 2.0
LANE_MARGIN = 2.0
M2_MIN_GAP = 2.0
X_GRID = 5.4              # cell/pin grid pitch -- all jog/search X steps use this
ROW_WIDTH_UM = 5.4 * 300  # 1620.0um -- must match gen_placement_nrow_fm.py TARGET_ROW_WIDTH_UM

# must match gen_placement_gds_nrow_fm.py
CH_HEIGHTS = [90.0, 260.0, 240.0, 224.0, 100.0]

ROW_X_TRIES = 200  # +-5.4 .. +-1080um for a row-crossing clear-X search

TAP_CELL = "TAP2"
TAP_GND_X_LOCAL = (1.0, 4.4)
TAP_VDD_X_LOCAL = (6.4, 9.8)
TAP_STRAP_MARGIN = 1.1   # TAP2's own M2 strap starts/stops this far inside the cell edge

# v4 (design_notes 38.8)
HIGH_FO_THRESHOLD = 8    # pin count at/above which a row-only/adjacent-pair
                          # net is treated as "high fan-out" (dedicated track)
HIGH_FO_GUARD_TRACKS = 1  # empty tracks left on either side of a high-FO net's
                           # own track -- Y-only separation, makes its wide
                           # trunk's X-span irrelevant to collides()

# v4 point 8 (user proposal): these highest-fanout, multi-row nets get
# per-row local trunks + a connecting spine instead of the generic
# dedicated-track treatment above -- see module docstring point 8.
PER_ROW_LOCAL_NETS = {"scl_buf0", "scl_buf1", "_126_buf0", "_126_buf1"}
PER_ROW_GUARD_TRACKS = 1

# v4.3 (design_notes 38.13, user-directed targeted fix): these 6 nets are
# the lower-fan-out side of a specific, already-diagnosed case-2 short
# (design_notes 38.10's exact-overlap-polygon analysis pinpointed all 6).
# Each gets a live channel-collision check (reusing the exact same
# channel_clear/find_channel_clear_x/draw_jog machinery as the general
# forced-overlap-zone mechanism, point 7 below) in a dedicated pass run
# AFTER every other net is drawn, so the check sees the true final
# picture. Scoped to just these 6 named nets (not a whole zone), so the
# jog/area cost stays small -- unlike applying the same live check to an
# entire forced-overlap zone (176 jogs, +71% core height, design_notes
# 38.8), which was measured too costly and left disabled.
FORCE_JOG_NETS = {"txreg[1]", "_195_", "_055_", "_059_", "_172_", "_109_"}


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
    for r, row_insts in enumerate(rows):
        last = row_insts[-1]
        w = round(last["x"] + last["width"], 3)
        assert abs(w - ROW_WIDTH_UM) < 1e-6, f"row {r} width {w} != ROW_WIDTH_UM {ROW_WIDTH_UM}"

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

    # v4 (design_notes 38.8, point 7): per-channel "forced overlap zone"
    # -- the X range where BOTH rows sharing a channel have real-cell M2
    # pins. Left/right row anchoring (38.7) cannot avoid this once the
    # two rows' combined real-cell demand exceeds the channel's non-TAP
    # budget; row-only/adjacent-pair stubs landing here get an extra
    # live collision check before drawing (see pass 1 below).
    row_real_x = defaultdict(list)
    for net, pads in net_pins.items():
        for r, _inst, _pname, x0, y0, x1, y1 in pads:
            row_real_x[r].append((x0 + x1) / 2.0)
    row_x_range = {r: (min(xs), max(xs)) for r, xs in row_real_x.items() if xs}
    overlap_zone = {}  # channel -> (lo, hi)
    for c in range(1, n_rows):
        below, above = row_x_range.get(c - 1), row_x_range.get(c)
        if below is None or above is None:
            continue
        lo, hi = max(below[0], above[0]), min(below[1], above[1])
        if lo <= hi:
            overlap_zone[c] = (lo, hi)
    overlap_zone = {}  # TEMP DISABLED pending user decision (design_notes 38.8)
    if overlap_zone:
        print("forced overlap zone(s):", {c: (round(lo, 1), round(hi, 1)) for c, (lo, hi) in overlap_zone.items()})

    row_only = defaultdict(dict)       # row -> {net: (xmin,xmax)}  (excludes high-FO)
    row_only_net_row = {}              # net -> row
    adjacent_pair = defaultdict(dict)  # channel -> {net: (xmin,xmax)}  (excludes high-FO)
    adj_net_ch = {}                    # net -> channel
    spanning = []                      # [(net, xmin, xmax, legal_channels)]
    stub_nets = 0
    high_fo_row_only = {}   # net -> row  (high-FO, single-row)
    high_fo_adjacent = {}   # net -> channel  (high-FO, adjacent-pair)
    per_row_local_pads = {}  # net -> pads  (v4 point 8, bypasses all classification below)
    for net, pads in net_pins.items():
        if len(pads) < 2:
            stub_nets += 1
            continue
        if net in PER_ROW_LOCAL_NETS:
            per_row_local_pads[net] = pads
            continue
        pin_rows = sorted({p[0] for p in pads})
        xs = [(x0 + x1) / 2.0 for _r, _i, _p, x0, y0, x1, y1 in pads]
        interval = (min(xs), max(xs))
        is_high_fo = len(pads) >= HIGH_FO_THRESHOLD
        if len(pin_rows) == 1:
            r = pin_rows[0]
            if is_high_fo:
                high_fo_row_only[net] = r
            else:
                row_only[r][net] = interval
                row_only_net_row[net] = r
        elif len(pin_rows) == 2 and pin_rows[1] == pin_rows[0] + 1:
            c = pin_rows[0] + 1
            if is_high_fo:
                high_fo_adjacent[net] = c
            else:
                adjacent_pair[c][net] = interval
                adj_net_ch[net] = c
        else:
            legal = list(range(pin_rows[0], pin_rows[-1] + 2))
            spanning.append((net, interval[0], interval[1], legal))
    n_high_fo = len(high_fo_row_only) + len(high_fo_adjacent)
    if n_high_fo:
        print(f"high fan-out (>={HIGH_FO_THRESHOLD} pins) nets: {n_high_fo} "
              f"({len(high_fo_row_only)} row-only, {len(high_fo_adjacent)} adjacent-pair) "
              f"-- dedicated guarded tracks, routed first")

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

    # v4: assign each high-FO net to a channel (row-only ones pick
    # whichever of their row's two adjacent channels currently has fewer
    # high-FO nets, same load-balancing idea as spanning nets; adjacent-
    # pair ones have only one legal channel already), then lay out a
    # dedicated front-of-channel region: one track per net, with
    # HIGH_FO_GUARD_TRACKS empty tracks on either side of it, so no
    # other net's via can ever land within reach of its trunk regardless
    # of the trunk's X-span (see module docstring, point 6).
    high_fo_nets_in_channel = defaultdict(list)  # channel -> [net, ...]
    running_hf = [0] * n_ch
    for net, r in high_fo_row_only.items():
        candidates = [ch for ch in (r, r + 1) if 0 <= ch < n_ch]
        c = min(candidates, key=lambda ch: running_hf[ch])
        running_hf[c] += 1
        high_fo_nets_in_channel[c].append(net)
    for net, c in high_fo_adjacent.items():
        running_hf[c] += 1
        high_fo_nets_in_channel[c].append(net)

    high_fo_track_of = {}   # net -> track idx (within its channel)
    high_fo_block_size = [0] * n_ch
    for c in range(n_ch):
        idx = 0
        for net in high_fo_nets_in_channel[c]:
            high_fo_track_of[net] = idx
            idx += 1 + HIGH_FO_GUARD_TRACKS
        high_fo_block_size[c] = idx

    # v4 point 8: per-row local trunks for PER_ROW_LOCAL_NETS. Row R's
    # local segment of net `net` always lives in channel R (directly
    # below row R) on its own dedicated+guarded track -- same isolation
    # idea as high-FO above, just keyed by (net, row) instead of net.
    #
    # Placement within the channel (user request): these dedicated
    # tracks sit at the END nearest row R itself -- i.e. the HIGHEST
    # track index in channel R (track_y = ch_y0[R] + TRACK0_OFFSET +
    # idx*TRACK_PITCH increases with idx, and row R sits directly ABOVE
    # channel R, so higher idx = physically closer to row R). Normal
    # Pass-1 lane allocation (row_below_upper/row_above_lower/
    # adjacent_pair/spanning) fills everything below that, right after
    # the high-FO block. This also shortens the per-row-local nets' own
    # M2 stubs (their pins all live in row R, right next to this end of
    # the channel).
    per_row_rows_of = {}  # net -> sorted [row, ...] with pins
    for net, pads in per_row_local_pads.items():
        per_row_rows_of[net] = sorted({p[0] for p in pads})
    per_row_nets_in_channel = defaultdict(list)  # channel(=row) -> [net, ...]
    for net, rows_with_pins in per_row_rows_of.items():
        for r in rows_with_pins:
            per_row_nets_in_channel[r].append(net)
    per_row_block_size = [
        (len(per_row_nets_in_channel[c]) * (1 + PER_ROW_GUARD_TRACKS) + PER_ROW_GUARD_TRACKS)
        if per_row_nets_in_channel[c] else 0
        for c in range(n_ch)
    ]  # +1 extra leading guard to separate this block from the normal
       # lanes below it (the block's own internal/trailing guards only
       # protect nets from each other and used to double as the boundary
       # guard back when this block sat at the front -- now that it's
       # last, the boundary is on the OTHER side and needs its own gap)
    if per_row_local_pads:
        n_segments = sum(len(v) for v in per_row_rows_of.values())
        print(f"per-row local trunk nets: {len(per_row_local_pads)} ({sorted(per_row_local_pads)}), "
              f"{n_segments} row-local segment(s) total, dedicated guarded tracks nearest each row, routed first")

    block_offset = [dict() for _ in range(n_ch)]
    channel_total = [0] * n_ch
    per_row_track_of = {}  # (net, row) -> track idx within channel=row
    for c in range(n_ch):
        off = high_fo_block_size[c]
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
        idx = off + PER_ROW_GUARD_TRACKS  # leading guard before this block
        for net in per_row_nets_in_channel[c]:
            per_row_track_of[(net, c)] = idx
            idx += 1 + PER_ROW_GUARD_TRACKS
        off = off + per_row_block_size[c]
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

    def claim_track(channel, cxs):
        """Bump to the next unused track index in `channel` whose via
        proximity (case 1) is clear for `cxs`, and register it as used.
        Shared by both the primary track assignment below and every
        spanning-net jog -- a jog's cxs are its two via_1 endpoints, so a
        freshly claimed track can never collide with anything else."""
        idx = next_free_idx[channel]
        next_free_idx[channel] += 1
        while collides(channel, idx, cxs):
            idx = next_free_idx[channel]
            next_free_idx[channel] += 1
        channel_used_x[(channel, idx)].extend(cxs)
        return idx

    non_spanning_nets = {}
    non_spanning_nets.update({n: p for n, p in net_pins.items() if n in row_only_net_row})
    non_spanning_nets.update({n: p for n, p in net_pins.items() if n in adj_net_ch})
    # v4.3: the 6 FORCE_JOG_NETS still get their normal structural track
    # assignment below (channel_primary/claim_track, unchanged), but
    # their actual DRAWING is deferred to a dedicated, live-checked pass
    # at the very end instead of the normal pass 1 loop (see
    # FORCE_JOG_NETS definition above).
    force_jog_pads = {n: p for n, p in non_spanning_nets.items() if n in FORCE_JOG_NETS}
    spanning_nets = {n: p for n, p in net_pins.items() if n in span_channel_assign}
    high_fo_nets = {}
    high_fo_nets.update({n: p for n, p in net_pins.items() if n in high_fo_row_only})
    high_fo_nets.update({n: p for n, p in net_pins.items() if n in high_fo_adjacent})

    final_track = {}
    # high-FO nets FIRST (v4, "priority routing" -- both their track
    # claim and their drawing later happen before everything else, so
    # their wide trunk is on the layout before anything else could ever
    # need to consider it).
    net_channel_of_high_fo = {}
    for c, nets_here in high_fo_nets_in_channel.items():
        for net in nets_here:
            net_channel_of_high_fo[net] = c
    for net, pads in high_fo_nets.items():
        channel = net_channel_of_high_fo[net]
        idx = high_fo_track_of[net]
        cxs = [(x0 + x1) / 2.0 for _r, _i, _p, x0, y0, x1, y1 in pads]
        channel_used_x[(channel, idx)].extend(cxs)
        track_y = ch_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH
        final_track[net] = (channel, track_y)

    # v4 point 8: per-row local trunk track_y for each (net, row) segment
    # of PER_ROW_LOCAL_NETS -- also claimed/registered first, same
    # priority-routing rationale as high-FO nets above.
    per_row_track_y = {}  # (net, row) -> track_y  (channel == row)
    for net, rows_with_pins in per_row_rows_of.items():
        for r in rows_with_pins:
            channel = r
            idx = per_row_track_of[(net, r)]
            cxs = [(x0 + x1) / 2.0 for row, _i, _p, x0, y0, x1, y1 in per_row_local_pads[net] if row == r]
            channel_used_x[(channel, idx)].extend(cxs)
            per_row_track_y[(net, r)] = ch_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH

    bumped = 0
    for net, pads in list(non_spanning_nets.items()) + list(spanning_nets.items()):
        channel, idx = channel_primary(net)
        cxs = [(x0 + x1) / 2.0 for _r, _i, _p, x0, y0, x1, y1 in pads]
        if collides(channel, idx, cxs):
            bumped += 1
            idx = claim_track(channel, cxs)
        else:
            channel_used_x[(channel, idx)].extend(cxs)
        track_y = ch_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH
        final_track[net] = (channel, track_y)
    if bumped:
        print(f"case-1 collisions resolved by moving {bumped} net(s) to a spare track")

    # --- open the layout + register the TR-1um PCell library ---
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL_NAME)
    m1_idx = layout.layer(*M1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)

    tr_1um("TR-1um")
    via_lib = pya.Library.library_by_name("TR-1um", "*")
    via_decl = via_lib.layout().pcell_declaration("via_1")

    # per-net shape log (v4.1): records every M1/M2 box actually drawn,
    # tagged with whichever net is "current" at draw time (set at the
    # top of each per-net loop body in passes 0/1/2). This is the
    # ground truth for gen_err_report_nrow_fm.py's exact short-overlap
    # reconstruction -- unlike re-deriving stub/trunk geometry from
    # pin_map after the fact, it also captures jog/spine dogleg
    # segments that a from-pins reconstruction can't see.
    net_shapes = defaultdict(list)
    cur_net = [None]

    def m1_box(x0, y0, x1, y1):
        top.shapes(m1_idx).insert(db.Box(um(x0, dbu), um(y0, dbu), um(x1, dbu), um(y1, dbu)))
        if cur_net[0] is not None:
            net_shapes[cur_net[0]].append(("M1", x0, y0, x1, y1))

    def m2_box(x0, y0, x1, y1):
        top.shapes(m2_idx).insert(db.Box(um(x0, dbu), um(y0, dbu), um(x1, dbu), um(y1, dbu)))
        if cur_net[0] is not None:
            net_shapes[cur_net[0]].append(("M2", x0, y0, x1, y1))

    def place_via(cx, cy):
        pcell_idx = layout.add_pcell_variant(
            via_lib, via_decl.id(), {"x": M1_PAD_SIZE, "y": M1_PAD_SIZE, "x0": "c", "y0": "c"})
        top.insert(db.CellInstArray(pcell_idx, db.Trans(db.Vector(um(cx, dbu), um(cy, dbu)))))

    # --- TAP2 power mesh: connect every row's TAP column M2 straps into
    # one continuous vertical mesh through every channel (user request) ---
    tap_xs = sorted({round(it["x"], 3) for row in rows for it in row if it["type"] == TAP_CELL})
    for c in range(n_ch):
        y_lo = max(0.0, ch_y0[c] - TAP_STRAP_MARGIN)
        y_hi = min(core_h, ch_y0[c] + CH_HEIGHTS[c] + TAP_STRAP_MARGIN)
        for tap_x in tap_xs:
            for lx0, lx1 in (TAP_GND_X_LOCAL, TAP_VDD_X_LOCAL):
                m2_box(tap_x + lx0, y_lo, tap_x + lx1, y_hi)
    print(f"TAP power mesh: {len(tap_xs)} column(s) x {n_ch} channel(s) x 2 nets (VDD/GND)")

    forbidden_x_ranges = [
        (tap_x + lx0, tap_x + lx1)
        for tap_x in tap_xs
        for lx0, lx1 in (TAP_GND_X_LOCAL, TAP_VDD_X_LOCAL)
    ]

    def x_forbidden(x, half=PAD_HALF, margin=M2_MIN_GAP):
        for fx0, fx1 in forbidden_x_ranges:
            if not (x + half + margin <= fx0 or fx1 + margin <= x - half):
                return True
        return False

    # --- row-crossing clear-X search: a simple, LOCAL, grid-stepped
    # search against a single row's real cell M2 (plus the TAP mesh and
    # anything another spanning net has already claimed in that row) ---
    row_signal_used = defaultdict(list)  # row -> [cx, ...]

    def row_clear(row_k, x):
        y0, y1 = row_y0[row_k], row_y0[row_k] + row_h
        probe = db.Box(um(x - PAD_HALF - M2_MIN_GAP, dbu), um(y0, dbu),
                        um(x + PAD_HALF + M2_MIN_GAP, dbu), um(y1, dbu))
        if db.Region(top.begin_shapes_rec_touching(m2_idx, probe)).count() > 0:
            return False
        for ux in row_signal_used[row_k]:
            if abs(ux - x) < M1_PAD_SIZE + M2_MIN_GAP:
                return False
        return True

    def in_bounds(x):
        # keep the jog's via_1 pad (and its M2_MIN_GAP clearance) fully
        # inside the row's real cell area -- the out-of-bounds bug (task
        # #27) was find_row_clear_x wandering past X=0 / X=ROW_WIDTH_UM
        # into "clear" space that isn't actually over any standard cell.
        margin = PAD_HALF + M2_MIN_GAP
        return margin <= x <= ROW_WIDTH_UM - margin

    def find_row_clear_x(row_k, start_x):
        if in_bounds(start_x) and not x_forbidden(start_x) and row_clear(row_k, start_x):
            return start_x
        for s in range(1, ROW_X_TRIES + 1):
            for cand in (start_x + s * X_GRID, start_x - s * X_GRID):
                if in_bounds(cand) and not x_forbidden(cand) and row_clear(row_k, cand):
                    return cand
        raise SystemExit(f"no clear X found for row {row_k} near x={start_x}")

    # v4 (design_notes 38.8, point 7): live check for the forced-overlap
    # zone only -- queries the M2 ALREADY DRAWN in the exact box the stub
    # would occupy. M2-only (matching row_clear's precedent): M1 and M2
    # are different layers and a bare crossing without a via never
    # shorts, so an M1 trunk at some OTHER, unrelated track_y happening
    # to pass through this Y-range is not a real collision -- checking
    # M1 here produced spurious "no clear X" failures against completely
    # unrelated tracks elsewhere in the (tall) channel. Scoped to a small
    # X range (not a whole channel), unlike the full live-collision-
    # search attempt in section 37.6 that didn't scale.
    def channel_clear(x, y_lo, y_hi):
        probe = db.Box(um(x - PAD_HALF - M2_MIN_GAP, dbu), um(min(y_lo, y_hi), dbu),
                        um(x + PAD_HALF + M2_MIN_GAP, dbu), um(max(y_lo, y_hi), dbu))
        return db.Region(top.begin_shapes_rec_touching(m2_idx, probe)).count() == 0

    def find_channel_clear_x(start_x, y_lo, y_hi):
        if in_bounds(start_x) and not x_forbidden(start_x) and channel_clear(start_x, y_lo, y_hi):
            return start_x
        for s in range(1, ROW_X_TRIES + 1):
            for cand in (start_x + s * X_GRID, start_x - s * X_GRID):
                if in_bounds(cand) and not x_forbidden(cand) and channel_clear(cand, y_lo, y_hi):
                    return cand
        raise SystemExit(f"no clear X found in overlap zone near x={start_x} (y {y_lo}-{y_hi})")

    def draw_jog(cur_x, cur_y, clear_x, jog_channel):
        """via_1(M2->M1) at (cur_x, jog_y) -> M1 run to clear_x -> via_1
        (M1->M2) at (clear_x, jog_y). jog_y is a freshly claimed track in
        jog_channel. Returns the new (cur_x, cur_y) to continue from.
        Shared by pass 2's row-crossing jogs and pass 1's forced-overlap-
        zone jogs (v4)."""
        jog_idx = claim_track(jog_channel, [cur_x, clear_x])
        jog_y = ch_y0[jog_channel] + TRACK0_OFFSET + jog_idx * TRACK_PITCH
        m2_box(cur_x - PAD_HALF, min(cur_y, jog_y), cur_x + PAD_HALF, max(cur_y, jog_y))
        place_via(cur_x, jog_y)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(min(cur_x, clear_x), jog_y - half_w, max(cur_x, clear_x), jog_y + half_w)
        place_via(clear_x, jog_y)
        return clear_x, jog_y

    pin_map = {}
    routed = 0
    passthrough_pins = 0
    jog_count = 0
    overlap_jog_count = 0
    per_row_spine_jog_count = 0

    # pass 0 (v4 point 8): per-row local trunks for PER_ROW_LOCAL_NETS,
    # tied together by a spine. Drawn FIRST, before everything else.
    for net in sorted(per_row_local_pads):
        cur_net[0] = net
        pads = per_row_local_pads[net]
        rows_with_pins = per_row_rows_of[net]
        by_row = defaultdict(list)
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            by_row[row].append((inst_name, pname, x0, y0, x1, y1))

        # 1. draw each row's own local trunk + connect that row's pins to
        # it (channel == row, i.e. directly below that row -- always
        # direction "-1"/downward from the row's own perspective).
        row_trunk_xmin = {}
        for r in rows_with_pins:
            channel = r
            track_y = per_row_track_y[(net, r)]
            pin_cxs = []
            for inst_name, pname, x0, y0, x1, y1 in by_row[r]:
                cx = (x0 + x1) / 2.0
                pin_edge_y = y0
                y_lo, y_hi = min(pin_edge_y, track_y), max(pin_edge_y, track_y)
                m2_box(cx - PAD_HALF, y_lo, cx + PAD_HALF, y_hi)
                place_via(cx, track_y)
                pin_cxs.append(cx)
                pin_map.setdefault(net, []).append((inst_name, pname, cx, track_y))
            xmin, xmax = min(pin_cxs), max(pin_cxs)
            row_trunk_xmin[r] = xmin
            half_w = M1_TRUNK_WIDTH / 2.0
            m1_box(xmin, track_y - half_w, xmax, track_y + half_w)

        # 2. spine: connect consecutive rows' local trunks, reusing the
        # exact row-crossing machinery spanning nets use (find_row_clear_x
        # + draw_jog), tapping into each trunk via an extra via_1 at its
        # own xmin.
        for r_lo, r_hi in zip(rows_with_pins, rows_with_pins[1:]):
            cur_x = row_trunk_xmin[r_lo]
            cur_y = per_row_track_y[(net, r_lo)]
            place_via(cur_x, cur_y)  # tap into row r_lo's trunk
            for row_k in range(r_lo, r_hi):
                clear_x = find_row_clear_x(row_k, cur_x)
                row_signal_used[row_k].append(clear_x)
                if abs(clear_x - cur_x) > 1e-6:
                    per_row_spine_jog_count += 1
                    jog_channel = row_k
                    cur_x, cur_y = draw_jog(cur_x, cur_y, clear_x, jog_channel)
                row_ylo, row_yhi = row_y0[row_k], row_y0[row_k] + row_h
                m2_box(cur_x - PAD_HALF, min(cur_y, row_ylo), cur_x + PAD_HALF, max(cur_y, row_ylo))
                m2_box(cur_x - PAD_HALF, min(row_ylo, row_yhi), cur_x + PAD_HALF, max(row_ylo, row_yhi))
                cur_y = row_yhi
            # force the final X to land exactly on row r_hi's own trunk
            # tap point (row_trunk_xmin[r_hi]) -- `cur_x` after crossing
            # the intervening rows is just "some clear X", not
            # necessarily anywhere near row r_hi's trunk's own X-range,
            # so without this the via below can miss the trunk entirely
            # and leave the net split into disconnected pieces (a real
            # bug found via connectivity check: NET SPLIT on all 4 of
            # these nets before this fix).
            target_x = row_trunk_xmin[r_hi]
            if abs(target_x - cur_x) > 1e-6:
                per_row_spine_jog_count += 1
                cur_x, cur_y = draw_jog(cur_x, cur_y, target_x, r_hi)
            target_track_y = per_row_track_y[(net, r_hi)]
            m2_box(cur_x - PAD_HALF, min(cur_y, target_track_y), cur_x + PAD_HALF, max(cur_y, target_track_y))
            place_via(cur_x, target_track_y)  # tap into row r_hi's trunk
        routed += 1
    if per_row_local_pads:
        print(f"per-row local trunk spine jogs: {per_row_spine_jog_count}")

    # pass 1: row-only / adjacent-pair nets, via_1 only. High-FO nets are
    # drawn FIRST (v4, "priority routing" -- their dedicated guarded
    # tracks make this a formality for correctness, but it means their
    # wide trunk is always on the layout before anything else). Every
    # stub whose pin X falls in that channel's forced-overlap zone (v4,
    # point 7) gets a live collision check first; on a hit, a jog
    # (shared `draw_jog` helper) reroutes to a clear X on a fresh track.
    for net, pads in list(high_fo_nets.items()) + list(non_spanning_nets.items()):
        if net in FORCE_JOG_NETS:
            continue  # drawn later in its own dedicated live-checked pass (v4.3)
        cur_net[0] = net
        channel, track_y = final_track[net]
        zone = overlap_zone.get(channel)
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1
            cur_x, cur_y = cx, pin_edge_y
            if zone and zone[0] <= cx <= zone[1]:
                # only check the CHANNEL portion of the stub's path (from
                # the row's own boundary edge to track_y) -- excluding
                # the part still inside the row body, which is dense
                # with unrelated intra-cell M1/M2 and was never the
                # source of case 2 (a probe spanning the whole row body
                # here previously produced false-positive "collisions"
                # against ordinary standard-cell wiring).
                channel_entry_y = row_y0[row] if direction == -1 else row_y0[row] + row_h
                y_lo, y_hi = min(channel_entry_y, track_y), max(channel_entry_y, track_y)
                if not channel_clear(cx, y_lo, y_hi):
                    clear_x = find_channel_clear_x(cx, y_lo, y_hi)
                    if abs(clear_x - cx) > 1e-6:
                        overlap_jog_count += 1
                        m2_box(cx - PAD_HALF, min(pin_edge_y, channel_entry_y),
                               cx + PAD_HALF, max(pin_edge_y, channel_entry_y))
                        cur_x, cur_y = draw_jog(cx, channel_entry_y, clear_x, channel)
            y_lo, y_hi = min(cur_y, track_y), max(cur_y, track_y)
            m2_box(cur_x - PAD_HALF, y_lo, cur_x + PAD_HALF, y_hi)
            place_via(cur_x, track_y)
            pin_cxs.append(cur_x)
            pin_map.setdefault(net, []).append((inst_name, pname, cur_x, track_y))
        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1
    if overlap_jog_count:
        print(f"forced-overlap-zone collisions resolved by jogging {overlap_jog_count} pin(s)")

    # pass 2: spanning nets -- M2 vertical only; X changes go through a
    # via_1 -> M1 -> via_1 jog on a freshly claimed track
    for net, pads in spanning_nets.items():
        cur_net[0] = net
        channel, track_y = final_track[net]
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1

            if direction == -1 and channel < row:
                ordered_rows = list(range(row - 1, channel - 1, -1))
            elif direction == 1 and channel > row + 1:
                ordered_rows = list(range(row + 1, channel))
            else:
                ordered_rows = []
            if ordered_rows:
                passthrough_pins += 1

            cur_x, cur_y = cx, pin_edge_y
            for row_k in ordered_rows:
                clear_x = find_row_clear_x(row_k, cur_x)
                row_signal_used[row_k].append(clear_x)
                if abs(clear_x - cur_x) > 1e-6:
                    jog_count += 1
                    jog_channel = row_k if direction > 0 else row_k + 1
                    cur_x, cur_y = draw_jog(cur_x, cur_y, clear_x, jog_channel)
                row_ylo, row_yhi = row_y0[row_k], row_y0[row_k] + row_h
                entry_y = row_ylo if direction > 0 else row_yhi
                exit_y = row_yhi if direction > 0 else row_ylo
                m2_box(cur_x - PAD_HALF, min(cur_y, entry_y), cur_x + PAD_HALF, max(cur_y, entry_y))
                m2_box(cur_x - PAD_HALF, min(entry_y, exit_y), cur_x + PAD_HALF, max(entry_y, exit_y))
                cur_y = exit_y

            m2_box(cur_x - PAD_HALF, min(cur_y, track_y), cur_x + PAD_HALF, max(cur_y, track_y))
            place_via(cur_x, track_y)
            pin_cxs.append(cur_x)
            pin_map.setdefault(net, []).append((inst_name, pname, cur_x, track_y))

        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1

    # pass 3 (v4.3, design_notes 38.13): FORCE_JOG_NETS -- the same live
    # channel-collision check as the forced-overlap-zone mechanism
    # (point 7), but unconditional (not gated by zone membership) and
    # run LAST so it sees every other net's true final geometry. Scoped
    # to just these 6 already-diagnosed nets, so cost stays small.
    force_jog_count = 0
    for net, pads in force_jog_pads.items():
        cur_net[0] = net
        channel, track_y = final_track[net]
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1
            cur_x, cur_y = cx, pin_edge_y
            channel_entry_y = row_y0[row] if direction == -1 else row_y0[row] + row_h
            y_lo, y_hi = min(channel_entry_y, track_y), max(channel_entry_y, track_y)
            if not channel_clear(cx, y_lo, y_hi):
                clear_x = find_channel_clear_x(cx, y_lo, y_hi)
                if abs(clear_x - cx) > 1e-6:
                    force_jog_count += 1
                    m2_box(cx - PAD_HALF, min(pin_edge_y, channel_entry_y),
                           cx + PAD_HALF, max(pin_edge_y, channel_entry_y))
                    cur_x, cur_y = draw_jog(cx, channel_entry_y, clear_x, channel)
            y_lo, y_hi = min(cur_y, track_y), max(cur_y, track_y)
            m2_box(cur_x - PAD_HALF, y_lo, cur_x + PAD_HALF, y_hi)
            place_via(cur_x, track_y)
            pin_cxs.append(cur_x)
            pin_map.setdefault(net, []).append((inst_name, pname, cur_x, track_y))
        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1
    if force_jog_pads:
        print(f"FORCE_JOG_NETS: {len(force_jog_pads)} net(s), {force_jog_count} pin(s) jogged")

    for c in range(n_ch):
        budget = int((CH_HEIGHTS[c] - 2 * TRACK0_OFFSET) // TRACK_PITCH) + 1
        used = next_free_idx[c]
        status = "OK" if used <= budget else "OVERFLOW"
        print(f"  channel{c}: used {used} tracks, budget {budget} ({CH_HEIGHTS[c]} um) -> {status}")

    layout.write(OUT_GDS)

    pin_map_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
    with open(pin_map_path, "w") as f:
        json.dump(pin_map, f, indent=1)

    net_shapes_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/net_shapes_nrow_fm.json"
    with open(net_shapes_path, "w") as f:
        json.dump(net_shapes, f)

    print(f"wrote {OUT_GDS}")
    print(f"wrote {pin_map_path}")
    print(f"wrote {net_shapes_path} ({sum(len(v) for v in net_shapes.values())} boxes, {len(net_shapes)} nets)")
    print(f"signal nets: {len(net_pins)}, routed: {routed}, stubs: {stub_nets}")
    print(f"row-only={sum(len(v) for v in row_only.values())}, "
          f"adjacent-pair={sum(len(v) for v in adjacent_pair.values())}, spanning={len(spanning)}, "
          f"high-FO={n_high_fo}, per-row-local={len(per_row_local_pads)}")
    print(f"spanning-net pins requiring a row pass-through: {passthrough_pins}")
    print(f"via_1-based jogs inserted: {jog_count} (row-crossing) + {overlap_jog_count} (forced-overlap zone) "
          f"+ {per_row_spine_jog_count} (per-row local trunk spine)")


if __name__ == "__main__":
    main()
