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
# v4.4 (design_notes 38.14, user request): scl_n added -- it was still
# treated as a plain high-FO net (dedicated guarded track, but ONE
# shared trunk across whichever rows/channel it landed in) and kept
# showing up as a case-2 short with unrelated nets (scl_n/txreg[1],
# scl_n/_080_, scl_n/_126_buf1 across this session's iterations).
PER_ROW_LOCAL_NETS = {"scl_buf0", "scl_buf1", "_126_buf0", "_126_buf1", "scl_n"}
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
# v5.1 (design_notes 38.18, user request): bit_cnt[2] added -- the OTHER
# side of the scl_n/bit_cnt[2] short (one of the 3 remaining "priority-net"
# shorts). Root cause: Pass 0 (per-row-local trunk+spine) runs FIRST and
# its crossings are live-checked only against what's drawn SO FAR -- it
# can't know where a not-yet-drawn net's own pin will land. bit_cnt[2] is
# a simple row-only net normally drawn with no live check at all in pass
# 1, so its pin coincidentally landed on an X scl_n's spine already
# claimed. Deferring its drawing to this same live-checked pass (which
# runs after Pass 0, so Pass 0's geometry IS visible to it) resolves it
# cleanly. NOTE: _115_/_080_ (the other 2 priority-net shorts, both vs.
# _126_buf0/_126_buf1) were ALSO tried here and did NOT resolve cleanly --
# their collision just relocated to a different net (whack-a-mole), so
# they are deliberately left out; see design_notes 38.18.
FORCE_JOG_NETS = {"txreg[1]", "_195_", "_055_", "_059_", "_172_", "_109_", "bit_cnt[2]"}


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


def main(placement_json=PLACEMENT_JSON, in_gds=IN_GDS, out_gds=OUT_GDS,
         force_jog_nets=None, per_row_local_nets=None,
         pin_map_path=None, net_shapes_path=None, force_jog_events_path=None,
         channel_usage_path=None, ch_heights=None):
    """Section 40 CLI overrides -- see insert_row_buffers.py: lets this be
    re-run against a different (placement_json, in_gds, out_gds) triple
    (e.g. the v4 row-buffered netlist's placement) without disturbing the
    known-good defaults used for the original netlist's 0-shorts/0-DRC
    result. force_jog_nets/per_row_local_nets, if given, REPLACE the
    module-level FORCE_JOG_NETS/PER_ROW_LOCAL_NETS sets for this call only
    (both are stale, old-netlist-specific net names when left at their
    defaults -- a fresh netlist needs its own diagnosis)."""
    global FORCE_JOG_NETS, PER_ROW_LOCAL_NETS, CH_HEIGHTS
    if force_jog_nets is not None:
        FORCE_JOG_NETS = force_jog_nets
    if per_row_local_nets is not None:
        PER_ROW_LOCAL_NETS = per_row_local_nets
    if ch_heights is not None:
        CH_HEIGHTS = ch_heights
    if pin_map_path is None:
        pin_map_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
    if net_shapes_path is None:
        net_shapes_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/net_shapes_nrow_fm.json"

    placement = json.load(open(placement_json))
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
    per_row_rows_of = {}  # net -> sorted [row, ...] WITH PINS
    for net, pads in per_row_local_pads.items():
        per_row_rows_of[net] = sorted({p[0] for p in pads})
    # v5 (design_notes 38.17, user request): reserve a dedicated track in
    # EVERY channel the net's spine crosses, not just the channels where
    # it has its own pins -- covers the (currently unused but structurally
    # possible) case of a net whose rows-with-pins have a gap, so the
    # spine-crossing rewrite below always has its own pre-reserved track
    # to land on instead of ever falling back to the shared claim_track
    # pool. For all 5 nets in the current design rows_with_pins happens to
    # already be contiguous, so this is a no-op today (channels_of ==
    # rows_of) but keeps the mechanism correct if that ever changes.
    per_row_channels_of = {}  # net -> sorted [channel, ...] with pins OR pass-through
    for net, rows_with_pins in per_row_rows_of.items():
        per_row_channels_of[net] = list(range(min(rows_with_pins), max(rows_with_pins) + 1))
    per_row_nets_in_channel = defaultdict(list)  # channel -> [net, ...]
    for net, channels in per_row_channels_of.items():
        for c in channels:
            per_row_nets_in_channel[c].append(net)
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

    def claim_track_near(channel, cxs, target_idx, extra_ok=None, allow_claimed=False):
        """Like claim_track, but searches OUTWARD from `target_idx` for
        the CLOSEST unclaimed, collision-clear index, instead of always
        taking the next never-before-tried global index. `next_free_idx`
        only ever increases, so by the time a pass running LATE in the
        pipeline (e.g. FORCE_JOG_NETS, design_notes 38.13/38.16) claims
        a track, "next free" can be far from where this particular jog
        actually needs to land -- and draw_jog's departure leg (the
        vertical run at the ORIGINAL x, from the jog's start Y up to
        whatever track_y gets picked) is never live-checked, so a track
        far away means a long, unchecked run right back through the
        collision zone the jog was meant to escape. Searching near a
        caller-supplied target Y (typically right at the channel
        boundary the jog starts from) keeps that departure leg as short
        as physically possible instead.

        `extra_ok(idx, jog_y) -> bool`, if given (design_notes 38.22),
        is an additional validity test run BEFORE a candidate is
        claimed -- e.g. verifying the departure leg itself is clear, not
        just the via-proximity check `collides` already does. Candidates
        that fail it are skipped (left unclaimed) and the search keeps
        going outward, instead of blindly taking the first via-proximity-
        clear track and drawing an unchecked departure leg through it
        (the root cause traced in 38.21: the fallback path's own escape
        segment could re-cross the very obstruction it was meant to
        avoid).

        `allow_claimed`, if True (design_notes 38.23), lets the search
        also consider indices some OTHER net has already claimed --
        every track is normally reserved exclusively for one net for its
        entire width (v3 docstring, point 3/4: avoids ever needing a
        live M1-vs-M1 check), but a GDS-verified audit found a large
        fraction of "claimed" tracks in every channel have NO M1 drawn
        anywhere near the X a stuck jog actually needs (the claiming
        net's own trunk lives at a completely different X range) --
        real, physically idle capacity the exclusive-ownership model
        was leaving unused. Only meant to be used with an `extra_ok`
        that itself verifies the specific M1 run needed doesn't
        physically overlap whatever that other net already drew there
        (see m1_run_clear) -- collides() alone (via-proximity only)
        isn't enough once two different nets can share an index."""
        idx_hi = int((CH_HEIGHTS[channel] - 2 * TRACK0_OFFSET) // TRACK_PITCH)
        for offset in range(0, idx_hi + 1):
            candidates = {target_idx + offset, target_idx - offset} if offset else {target_idx}
            for idx in sorted(candidates):
                if idx < 0 or idx > idx_hi:
                    continue
                if not allow_claimed and (channel, idx) in channel_used_x:
                    continue
                if collides(channel, idx, cxs):
                    continue
                if extra_ok is not None:
                    jog_y = ch_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH
                    if not extra_ok(idx, jog_y):
                        continue
                channel_used_x[(channel, idx)].extend(cxs)
                next_free_idx[channel] = max(next_free_idx[channel], idx + 1)
                return idx
        raise SystemExit(f"claim_track_near: no free track near idx={target_idx} in channel {channel} "
                          f"satisfying all checks")

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
    per_row_track_y = {}  # (net, channel) -> track_y, one per channel in per_row_channels_of[net]
    for net, channels in per_row_channels_of.items():
        for channel in channels:
            idx = per_row_track_of[(net, channel)]
            cxs = [(x0 + x1) / 2.0 for row, _i, _p, x0, y0, x1, y1 in per_row_local_pads[net] if row == channel]
            channel_used_x[(channel, idx)].extend(cxs)
            per_row_track_y[(net, channel)] = ch_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH

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

    # v6 (design_notes 38.21/38.22, user-directed rework): every row-only/
    # adjacent-pair/high-FO net's OWN per-pin stub path (x, y-range from
    # the pin's own edge to its net's track_y) is fully known from
    # net_pins + final_track above -- STATIC, placement/assignment data,
    # available before any drawing (mirrors exactly the direction/
    # pin_edge_y logic pass 1's drawing loop uses below). This lets a
    # net drawn EARLY (e.g. pass 0's per-row-local nets) know about the
    # planned geometry of a net drawn LATER (e.g. pass 1's row-only
    # nets) -- something no live-geometry-only check can ever do,
    # because the later net's M2 simply doesn't exist in the GDS yet at
    # the time the earlier net is drawn. This is what actually caused
    # the _115_/_080_ shorts (design_notes 38.18/38.21): pass 0 draws
    # _126_buf0/_126_buf1 before pass 1 draws _115_/_080_, so no amount
    # of live-only checking inside pass 0 could ever see the collision
    # coming. Deliberately stub-level (not "does this cross some other
    # net's track_y at all", which over-blocks -- bare M1/M2 crossing
    # without a via is not a real short, only two nets' OWN M2 stubs
    # actually overlapping in both X and Y is).
    static_stub_spans = []  # [(net, x, y_lo, y_hi), ...]
    for net, pads in list(non_spanning_nets.items()) + list(high_fo_nets.items()):
        channel, track_y = final_track[net]
        for row, _inst, _pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1
            static_stub_spans.append((net, cx, min(pin_edge_y, track_y), max(pin_edge_y, track_y)))

    def static_stub_blocked(x, y_lo, y_hi, exclude_net):
        """Does (x, [y_lo,y_hi]) physically overlap (both X AND Y) some
        OTHER net's OWN planned stub? Order-independent (uses static
        data only) -- see static_stub_spans above for why this matters
        beyond what a live-geometry check alone can catch.

        v6 (design_notes 38.24): the threshold (PAD_HALF*2+M2_MIN_GAP)
        is exactly the X-distance at which two nets' M2 would sit at
        precisely the legal minimum gap -- legal, not a violation. A
        pin exactly one 5.4um placement-grid step away lands EXACTLY on
        this boundary, and floating-point arithmetic on real pin
        coordinates can put `abs(sx-x)` a hair under the nominal 5.4
        (e.g. 5.399999999999977), tripping the strict `<` and rejecting
        a perfectly legal candidate. EPS gives the boundary itself back
        to the legal (not-blocked) side."""
        EPS = 1e-6
        ylo, yhi = min(y_lo, y_hi), max(y_lo, y_hi)
        for net, sx, sy_lo, sy_hi in static_stub_spans:
            if net == exclude_net:
                continue
            if abs(sx - x) >= PAD_HALF * 2 + M2_MIN_GAP - EPS:
                continue
            if sy_hi < ylo or sy_lo > yhi:
                continue
            return True
        return False

    # --- open the layout + register the TR-1um PCell library ---
    layout = db.Layout()
    layout.read(in_gds)
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
        # v6 (design_notes 38.21/38.22): also reject an X whose column
        # this row's Y-range physically overlaps another net's OWN
        # statically-known planned stub -- order-independent, catches
        # what live geometry alone can't yet see (see static_stub_spans).
        if static_stub_blocked(x, y0, y1, cur_net[0]):
            return False
        return True

    def in_bounds(x):
        # keep the jog's via_1 pad (and its M2_MIN_GAP clearance) fully
        # inside the row's real cell area -- the out-of-bounds bug (task
        # #27) was find_row_clear_x wandering past X=0 / X=ROW_WIDTH_UM
        # into "clear" space that isn't actually over any standard cell.
        margin = PAD_HALF + M2_MIN_GAP
        return margin <= x <= ROW_WIDTH_UM - margin

    def find_row_clear_x(row_k, start_x, extra_ok=None):
        """`extra_ok(x) -> bool`, if given (design_notes 38.22), is an
        additional requirement checked alongside row_clear -- e.g. that
        the SAME x also lands cleanly in the channel this row-crossing
        is about to enter. Folding that requirement into the search
        itself (instead of discovering the problem only after cur_x is
        already fixed, at the channel-landing step) means the search can
        simply pick a DIFFERENT x up front, rather than needing a jog to
        escape an x it already committed to."""
        def ok(x):
            return in_bounds(x) and not x_forbidden(x) and row_clear(row_k, x) and (extra_ok is None or extra_ok(x))
        if ok(start_x):
            return start_x
        for s in range(1, ROW_X_TRIES + 1):
            for cand in (start_x + s * X_GRID, start_x - s * X_GRID):
                if ok(cand):
                    return cand
        raise SystemExit(f"no clear X found for row {row_k} near x={start_x} (net={cur_net[0]!r})")

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
        # v6 (design_notes 38.24): the probe already carries the full
        # legal clearance margin (PAD_HALF + M2_MIN_GAP) baked into its
        # size, so a candidate at EXACTLY the legal minimum spacing away
        # from existing M2 makes the probe's edge exactly touch that
        # M2's edge (zero-area intersection) -- legal (DRC requires "at
        # least" the minimum, and exactly-minimum satisfies that), but
        # `_touching` treats boundary-touching as a collision, over-
        # rejecting it. `_overlapping` requires a true positive-area
        # overlap (i.e. actually closer than the legal minimum), which
        # is what a real violation looks like. Confirmed via live
        # instrumentation (design_notes 38.24) that this was the
        # blocker for _423_.B's departure leg: two immediate row-
        # neighbor pins sit at exactly the legal 2.0um minimum gap
        # (overlap_cnt=0, touch_cnt>0) for the entire short-departure
        # range below bit_cnt[1]'s real stub.
        probe = db.Box(um(x - PAD_HALF - M2_MIN_GAP, dbu), um(min(y_lo, y_hi), dbu),
                        um(x + PAD_HALF + M2_MIN_GAP, dbu), um(max(y_lo, y_hi), dbu))
        if db.Region(top.begin_shapes_rec_overlapping(m2_idx, probe)).count() > 0:
            return False
        # v6 (design_notes 38.21/38.22): also reject a box that overlaps
        # another net's OWN statically-known planned stub, even if that
        # net hasn't been drawn yet (order-independent -- see
        # static_stub_spans above).
        if static_stub_blocked(x, y_lo, y_hi, cur_net[0]):
            return False
        return True

    def find_channel_clear_x(start_x, y_lo, y_hi, extra_ok=None):
        """v4.6 (design_notes 38.x, this session): `extra_ok(x) -> bool`,
        if given, is an additional requirement checked alongside
        channel_clear -- e.g. via-proximity to a NEIGHBORING track's
        already-registered via X (see via_x_clear below). Without this,
        a FORCE_JOG_NETS pin could land its via_1 pad at an X that is
        clear of live M2 (channel_clear's only check) but still too
        close, in Y, to an unrelated net's via on the immediately
        adjacent track -- channel_clear is deliberately M2-only (a bare
        M1/M2 crossing without a via is never a short), so it cannot see
        this M1-pad-vs-M1-pad proximity case; a real instance of exactly
        this (an M1+M2 space violation between _003_'s force-jogged via
        and txreg[1]'s untouched one, both landing near the same X on
        adjacent tracks) was found and fixed by adding this check."""
        def ok(x):
            return (in_bounds(x) and not x_forbidden(x) and channel_clear(x, y_lo, y_hi)
                    and (extra_ok is None or extra_ok(x)))
        if ok(start_x):
            return start_x
        for s in range(1, ROW_X_TRIES + 1):
            for cand in (start_x + s * X_GRID, start_x - s * X_GRID):
                if ok(cand):
                    return cand
        raise SystemExit(f"no clear X found in overlap zone near x={start_x} (y {y_lo}-{y_hi})")

    def via_x_clear(channel, track_y, x):
        """Is `x` far enough (MIN_VIA_X_SEP) from every via X already
        registered (channel_used_x) on the same or an immediately
        Y-adjacent track in `channel`? Reuses the exact same proximity
        test `collides()` already applies at initial track assignment --
        this just re-applies it at the point a FORCE_JOG_NETS pin's live
        landing X is chosen, since a jog can move a pin's via to an X
        collides() never got to re-check post-jog."""
        idx = int(round((track_y - ch_y0[channel] - TRACK0_OFFSET) / TRACK_PITCH))
        return not collides(channel, idx, [x])

    def register_via_x(channel, track_y, x):
        """Record a (post-jog) via X under its track's index in
        channel_used_x, so a LATER net in the same live-checked pass
        (e.g. another FORCE_JOG_NETS net) sees it via via_x_clear too --
        without this, only the ORIGINAL pre-jog X's of every net are
        registered (from the early track-assignment phase), so a jog
        earlier in this same pass would stay invisible to a jog later in
        it."""
        idx = int(round((track_y - ch_y0[channel] - TRACK0_OFFSET) / TRACK_PITCH))
        channel_used_x[(channel, idx)].append(x)

    def m1_run_clear(y, x0, x1):
        """v6 (design_notes 38.23): does an M1 run at track_y=y spanning
        [x0,x1] physically overlap M1 ALREADY DRAWN there (by any net,
        claimed-track-owner or not)? A GDS-verified audit found many
        "claimed" tracks (claim_track_near's exclusive-ownership model,
        v3 docstring point 3/4) have long idle stretches -- the owning
        net's own trunk simply doesn't reach the X a stuck jog needs.
        This lets claim_track_near's allow_claimed tier safely reuse
        that idle stretch: checked against the REAL drawn geometry, not
        the track's claim status, so two different nets sharing one
        track_y is safe as long as their actual metal never touches."""
        half_w = M1_TRUNK_WIDTH / 2.0
        probe = db.Box(um(min(x0, x1) - M2_MIN_GAP, dbu), um(y - half_w - M2_MIN_GAP, dbu),
                        um(max(x0, x1) + M2_MIN_GAP, dbu), um(y + half_w + M2_MIN_GAP, dbu))
        return db.Region(top.begin_shapes_rec_touching(m1_idx, probe)).count() == 0

    def draw_jog(cur_x, cur_y, clear_x, jog_channel, near_y=None):
        """via_1(M2->M1) at (cur_x, jog_y) -> M1 run to clear_x -> via_1
        (M1->M2) at (clear_x, jog_y). jog_y is a freshly claimed track in
        jog_channel. Returns the new (cur_x, cur_y) to continue from.
        Shared by pass 2's row-crossing jogs and pass 1's forced-overlap-
        zone jogs (v4).

        `near_y`, if given, claims the jog's track via claim_track_near
        (search outward from near_y) instead of claim_track (always the
        next never-before-tried global index) -- keeps the departure leg
        at `cur_x` short, which matters for a pass running late in the
        pipeline where "next free" can otherwise be far from where the
        jog starts (v4.5, design_notes 38.16).

        v6 (design_notes 38.21/38.22): a short departure leg is not
        enough on its own -- 38.21 found the fallback path could still
        land far from `near_y` when the channel is packed near the
        entry point, and the departure leg (drawn at the ORIGINAL,
        possibly-colliding `cur_x`) was never actually checked, so it
        could cross right back through the very obstruction the jog was
        meant to escape. When `near_y` is given, every candidate track
        claim_track_near considers is now ALSO required to have a clear
        departure leg (live geometry + static stubs, via channel_clear)
        before being claimed -- so the search keeps walking outward
        until it finds a track that is both free AND safely reachable,
        instead of taking the nearest free track unconditionally.

        v6 (design_notes 38.23): if NO exclusively-free track has a
        clear departure leg either (the obstruction and every reachable
        free track are on opposite sides of it -- confirmed via
        net_shapes/GDS audit for the one remaining short: bit_cnt[1]'s
        own stub spans nearly the whole channel, and every unclaimed
        track happens to sit beyond it), try again ALSO allowing reuse
        of a track some OTHER net has already claimed -- gated by BOTH
        the same departure-leg check AND a new m1_run_clear check (the
        M1 run itself must not physically overlap whatever that other
        net actually drew there). A GDS-verified audit found this idle
        capacity is real and substantial (9-24 fully-empty tracks per
        channel), just inaccessible under the exclusive-ownership model
        alone."""
        if near_y is not None:
            EPS = 0.01  # nudge the end touching cur_y off cur_y itself --
                        # cur_y is usually the exact edge of a segment
                        # this same net just drew, so an unnudged probe
                        # self-collides with its own geometry (same fix
                        # as the 38.17 channel-landing self-collision bug)

            def departure_leg_ok(idx, jog_y):
                if abs(jog_y - cur_y) < 1e-6:
                    return True  # no departure leg to check (same track)
                if jog_y > cur_y:
                    y_lo, y_hi = cur_y + EPS, jog_y
                else:
                    y_lo, y_hi = jog_y, cur_y - EPS
                return channel_clear(cur_x, y_lo, y_hi)

            def departure_leg_and_m1_ok(idx, jog_y):
                if not departure_leg_ok(idx, jog_y):
                    return False
                return m1_run_clear(jog_y, cur_x, clear_x)

            target_idx = int(round((near_y - TRACK0_OFFSET - ch_y0[jog_channel]) / TRACK_PITCH))
            try:
                jog_idx = claim_track_near(jog_channel, [cur_x, clear_x], target_idx, extra_ok=departure_leg_ok)
            except SystemExit:
                try:
                    jog_idx = claim_track_near(jog_channel, [cur_x, clear_x], target_idx,
                                                extra_ok=departure_leg_and_m1_ok, allow_claimed=True)
                    print(f"  INFO: draw_jog reused an already-claimed track near y={near_y} in "
                          f"channel {jog_channel} at x={cur_x} (idle stretch, design_notes 38.23)")
                except SystemExit:
                    # Still nothing -- genuinely no track, free or shared,
                    # has both a clear departure leg AND (if shared) clear
                    # M1. Fall back to the pre-38.22 behavior (nearest
                    # free track, unchecked departure leg) rather than
                    # aborting the whole run -- this is a real capacity
                    # limit, not a bug, and should surface as a
                    # connectivity-check short to investigate rather than
                    # a hard crash.
                    print(f"  WARNING: draw_jog could not find a track near y={near_y} in "
                          f"channel {jog_channel} with a clear departure leg at x={cur_x} -- "
                          f"falling back to nearest free track (may leave a short to investigate)")
                    jog_idx = claim_track_near(jog_channel, [cur_x, clear_x], target_idx)
        else:
            jog_idx = claim_track(jog_channel, [cur_x, clear_x])
        jog_y = ch_y0[jog_channel] + TRACK0_OFFSET + jog_idx * TRACK_PITCH
        m2_box(cur_x - PAD_HALF, min(cur_y, jog_y), cur_x + PAD_HALF, max(cur_y, jog_y))
        place_via(cur_x, jog_y)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(min(cur_x, clear_x), jog_y - half_w, max(cur_x, clear_x), jog_y + half_w)
        place_via(clear_x, jog_y)
        return clear_x, jog_y

    def bridge_final(cur_x, cur_y, target_y, jog_channel):
        """v9 (this session, design_notes 42): after draw_jog lands on
        (cur_x, jog_y), the caller still needs one more vertical M2 run
        from jog_y to the TRUE target_y at cur_x -- but jog_y is chosen
        by claim_track_near searching OUTWARD from near_y for a clear
        DEPARTURE leg + M1 run, with no guarantee it stays inside
        whatever Y-range the caller originally validated for cur_x. This
        re-validates the actual final [cur_y, target_y] run at cur_x
        and, if blocked, adds one more horizontal M1 bridge (at the
        ALREADY-CLAIMED track cur_y, so no new claim_track call is
        needed) to a nearby clear X before continuing down to target_y.
        Draws the final vertical run itself (unlike draw_jog, which
        leaves that to its caller) -- returns (x, target_y), already
        fully connected and ready for a via at target_y.

        Currently used only by per-row-local step 1's channel leg (where
        it cleanly fixed the sda_in/scl collision, design_notes 42).
        Also tried in the FORCE_JOG_NETS pass and the per-row-local
        spine's channel-landing fallback, where it fixed the specific
        shreg[1]/_071_ collision it was built for but introduced 2 new
        M1 and 2 new M2 min-spacing DRC violations elsewhere (the ad-hoc
        M1 bridge this function draws isn't itself guaranteed to respect
        M1-to-M1 spacing against whatever real geometry already occupies
        the claimed track at other X's -- unlike draw_jog's own M1 run,
        which is protected by claim_track's/claim_track_near's track-
        exclusivity model). Reverted from both of those call sites
        pending a proper fix (e.g. an m1_run_clear-gated search here
        too, which was tried but then made the per-row-local pass fail
        to find any valid X at all for a different net -- needs a more
        careful redesign, not a quick patch). shreg[1] vs _071_ remains
        a documented residual short as of this session's end."""
        final_lo, final_hi = min(cur_y, target_y), max(cur_y, target_y)
        if not channel_clear(cur_x, final_lo, final_hi):
            clear_x3 = find_channel_clear_x(cur_x, final_lo, final_hi)
            if abs(clear_x3 - cur_x) > 1e-6:
                half_w2 = M1_TRUNK_WIDTH / 2.0
                m1_box(min(cur_x, clear_x3), cur_y - half_w2, max(cur_x, clear_x3), cur_y + half_w2)
                place_via(clear_x3, cur_y)
                cur_x = clear_x3
        if abs(cur_y - target_y) > 1e-6:
            m2_box(cur_x - PAD_HALF, min(cur_y, target_y), cur_x + PAD_HALF, max(cur_y, target_y))
        return cur_x, target_y

    pin_map = {}
    routed = 0
    passthrough_pins = 0
    jog_count = 0
    overlap_jog_count = 0
    per_row_spine_jog_count = 0
    per_row_spine_events = []  # v5 (design_notes 38.17): per-step log of
                                # every segment Pass 0's spine mechanism
                                # draws, tagged by step name, for a
                                # dedicated step-by-step ERR-layer
                                # highlight (user request).

    def log_spine_event(net, step, channel, x, y0, y1):
        per_row_spine_events.append({
            "net": net, "step": step, "channel": channel,
            "x": x, "y0": min(y0, y1), "y1": max(y0, y1),
        })

    # pass 0 (v4 point 8, v5 design_notes 38.17): per-row local trunks for
    # PER_ROW_LOCAL_NETS, tied together by a spine. Drawn FIRST, before
    # everything else.
    #
    # v5 rewrite (user finding, design_notes 38.17): the OLD spine
    # mechanism reused the generic claim_track/draw_jog machinery for
    # EVERY channel it crossed, even channels where this exact net
    # already owned a dedicated per-row-local track (per_row_track_y) --
    # burning 1-2 extra tracks per crossing for no reason (observed:
    # _126_buf0 alone used 2-3 tracks in a channel where it only needed
    # 1). Now every channel the spine crosses (r_lo..r_hi inclusive,
    # per_row_channels_of above) reuses that net's OWN fixed track --
    # crossing a row body still uses the existing live-checked
    # find_row_clear_x (row_clear), and landing on the next channel's
    # fixed track is now ALSO live-checked (channel_clear) before being
    # drawn, with an X-only jog (still on the SAME fixed track) if
    # needed -- falling back to the old claim_track-based draw_jog
    # (near_y-anchored, design_notes 38.16) only in the rare case that
    # direct landing is blocked (not observed in the current design, kept
    # as a safety net rather than risk drawing through a known
    # obstruction).
    for net in sorted(per_row_local_pads):
        cur_net[0] = net
        pads = per_row_local_pads[net]
        rows_with_pins = per_row_rows_of[net]
        by_row = defaultdict(list)
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            by_row[row].append((inst_name, pname, x0, y0, x1, y1))
        half_w = M1_TRUNK_WIDTH / 2.0

        # 1. draw each row's own local trunk + connect that row's pins to
        # it (channel == row, i.e. directly below that row -- always
        # direction "-1"/downward from the row's own perspective).
        #
        # v7 (this session, discovered while re-routing after the
        # RSTB1/RSTB2 pin-name fix added 2 more simultaneous
        # PER_ROW_LOCAL_NETS): this per-pin stub used to draw straight
        # down from the pin's own raw X (cx) to track_y with NO live
        # collision check at all -- unlike every other drawing step in
        # this pass (step 2's row/channel crossings are all
        # channel_clear-guarded). With only ~5 simultaneous per-row-local
        # nets this never manifested; with 7, verify_connectivity found
        # real cross-net M2 overlaps (e.g. sda_in's row2 stub landing
        # directly on top of scl's already-drawn channel2 spine segment,
        # same X column, overlapping Y).
        #
        # v8 (this session, superseding v7's first attempt): v7 tried
        # live-checking the raw X and, if blocked, jogging with a short
        # M1 run AT THE PIN'S OWN Y (inside the busy cell row) -- that
        # search almost always failed to find clearance (a wide M1 jog
        # inside a row packed with unrelated cells' M1 pin geometry is
        # rarely free) and fell back to the unchecked raw X, leaving the
        # short unresolved. Root cause of the miss: the actual collision
        # (verified via net_shapes) always sits well INSIDE the channel,
        # not near the row edge -- so jogging inside the crowded row was
        # solving the problem in the wrong place. Fixed by splitting the
        # stub into two legs, each jogged in the space best suited for
        # it: (1) a fixed-X vertical run from the pin down to the row's
        # own boundary (short, stays inside the row, same
        # never-checked assumption every other pin-to-trunk connection
        # in this codebase already relies on) -- then (2), once past the
        # row boundary and into the open channel, the exact same
        # find_channel_clear_x + draw_jog(near_y=...) mechanism already
        # proven throughout step 2's row/channel crossings: search for a
        # clear landing X across just the channel portion of the run,
        # and if the direct X is blocked, jog via a freshly claimed M1
        # track (live departure-leg-checked) rather than a raw,
        # unchecked M1 box at a crowded Y.
        row_trunk_xmin = {}
        for r in rows_with_pins:
            channel = r
            track_y = per_row_track_y[(net, r)]
            row_boundary = row_y0[r]  # this row's edge nearest channel r (below it)
            pin_cxs = []
            for inst_name, pname, x0, y0, x1, y1 in by_row[r]:
                cx = (x0 + x1) / 2.0
                pin_edge_y = y0
                # leg 1: fixed-X, pin -> row boundary (stays inside the row)
                if abs(pin_edge_y - row_boundary) > 1e-6:
                    m2_box(cx - PAD_HALF, min(pin_edge_y, row_boundary), cx + PAD_HALF,
                           max(pin_edge_y, row_boundary))
                # leg 2: row boundary -> track_y, entirely inside the channel --
                # live-checked, jogged via draw_jog if the direct X is blocked.
                y_lo, y_hi = min(row_boundary, track_y), max(row_boundary, track_y)
                if channel_clear(cx, y_lo, y_hi):
                    land_x, land_y = cx, row_boundary
                else:
                    clear_x = find_channel_clear_x(cx, y_lo, y_hi)
                    land_x, land_y = draw_jog(cx, row_boundary, clear_x, channel, near_y=row_boundary)
                    land_x, land_y = bridge_final(land_x, land_y, track_y, channel)
                    log_spine_event(net, "stub_jog", r, land_x, row_boundary, land_y)
                if abs(land_y - track_y) > 1e-6:
                    m2_box(land_x - PAD_HALF, min(land_y, track_y), land_x + PAD_HALF,
                           max(land_y, track_y))
                place_via(land_x, track_y)
                register_via_x(channel, track_y, land_x)
                pin_cxs.append(land_x)
                pin_map.setdefault(net, []).append((inst_name, pname, land_x, track_y))
            xmin, xmax = min(pin_cxs), max(pin_cxs)
            row_trunk_xmin[r] = xmin
            m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
            log_spine_event(net, "trunk", channel, (xmin + xmax) / 2.0, track_y, track_y)

        # 2. spine: connect consecutive rows' local trunks, staying on
        # this net's own fixed track in every channel crossed.
        for r_lo, r_hi in zip(rows_with_pins, rows_with_pins[1:]):
            cur_x = row_trunk_xmin[r_lo]
            cur_y = per_row_track_y[(net, r_lo)]
            place_via(cur_x, cur_y)  # tap into row r_lo's trunk
            for row_k in range(r_lo, r_hi):
                track_y_k = per_row_track_y[(net, row_k)]
                row_ylo, row_yhi = row_y0[row_k], row_y0[row_k] + row_h
                next_channel = row_k + 1
                target_y = per_row_track_y[(net, next_channel)]

                # v6 (design_notes 38.22): require the row-crossing X to
                # ALSO land cleanly in the next channel (live geometry +
                # other nets' static stubs), folded into the SEARCH
                # itself -- so a bad X is never chosen in the first
                # place, rather than discovering the problem only after
                # cur_x is already fixed. 38.21 found the fallback jog
                # could not fix this after the fact: its own departure
                # leg can only move in Y at the SAME, already-blocked X,
                # so if the obstruction spans the whole channel there, no
                # jog_y can ever get around it -- only picking a
                # different X up front can.
                def landing_ok(x, _row_yhi=row_yhi, _target_y=target_y):
                    y_lo, y_hi = min(_row_yhi, _target_y), max(_row_yhi, _target_y)
                    return channel_clear(x, y_lo, y_hi)

                # 2a. cross row_k's own cell body (live-checked, now also
                # required to land cleanly on the other side)
                clear_x = find_row_clear_x(row_k, cur_x, extra_ok=landing_ok)
                row_signal_used[row_k].append(clear_x)
                if abs(clear_x - cur_x) > 1e-6:
                    per_row_spine_jog_count += 1
                    m1_box(min(cur_x, clear_x), track_y_k - half_w, max(cur_x, clear_x), track_y_k + half_w)
                    place_via(clear_x, track_y_k)
                    log_spine_event(net, "row_jog", row_k, clear_x, track_y_k, track_y_k)
                    cur_x = clear_x
                m2_box(cur_x - PAD_HALF, min(cur_y, row_ylo), cur_x + PAD_HALF, max(cur_y, row_ylo))
                m2_box(cur_x - PAD_HALF, min(row_ylo, row_yhi), cur_x + PAD_HALF, max(row_ylo, row_yhi))
                log_spine_event(net, "row_crossing", row_k, cur_x, cur_y, row_yhi)
                cur_y = row_yhi

                # 2b. land on the next channel's fixed track for this net
                # -- live-checked (design_notes 38.17); X-only jog on the
                # SAME track if blocked, generic-track fallback only if
                # even that is blocked. Since landing_ok above already
                # required clear_x to satisfy this exact check, this
                # should now always succeed -- the re-check + jog
                # fallback stays as a defensive safety net for edge
                # cases landing_ok's static data doesn't model.
                #
                # nudge the probe's near edge off cur_y by a tiny epsilon --
                # cur_y is exactly the top edge of the row_crossing M2 box
                # this net just drew at this same cur_x, so an unnudged
                # probe starting exactly there "touches" (self-collides
                # with) its own just-drawn geometry and channel_clear would
                # always report blocked (observed: 9/9 landings falsely
                # flagged before this fix).
                EPS = 0.01
                y_lo, y_hi = min(cur_y, target_y), max(cur_y, target_y)
                check_y_lo = y_lo + EPS
                if channel_clear(cur_x, check_y_lo, y_hi):
                    m2_box(cur_x - PAD_HALF, y_lo, cur_x + PAD_HALF, y_hi)
                    place_via(cur_x, target_y)
                    register_via_x(next_channel, target_y, cur_x)
                    log_spine_event(net, "channel_land", next_channel, cur_x, cur_y, target_y)
                else:
                    per_row_spine_jog_count += 1
                    clear_x2 = find_channel_clear_x(cur_x, check_y_lo, y_hi)
                    cur_x, cur_y = draw_jog(cur_x, cur_y, clear_x2, next_channel, near_y=cur_y)
                    log_spine_event(net, "channel_jog_fallback", next_channel, cur_x, cur_y, cur_y)
                    if abs(cur_y - target_y) > 1e-6:
                        m2_box(cur_x - PAD_HALF, min(cur_y, target_y), cur_x + PAD_HALF, max(cur_y, target_y))
                    place_via(cur_x, target_y)
                    register_via_x(next_channel, target_y, cur_x)
                cur_y = target_y
            # force the final X to land exactly on row r_hi's own trunk
            # tap point (row_trunk_xmin[r_hi]) -- cur_y is already
            # target_y == per_row_track_y[(net, r_hi)] at this point, so
            # this is an X-only jog on that SAME (already-owned) track,
            # not a new one. Without this the via below can miss the
            # trunk box entirely and split the net (real bug found via
            # connectivity check pre-v4 fix).
            target_x = row_trunk_xmin[r_hi]
            if abs(target_x - cur_x) > 1e-6:
                per_row_spine_jog_count += 1
                m1_box(min(cur_x, target_x), cur_y - half_w, max(cur_x, target_x), cur_y + half_w)
                log_spine_event(net, "trunk_land_jog", r_hi, target_x, cur_y, cur_y)
                cur_x = target_x
            place_via(cur_x, cur_y)  # tap into row r_hi's trunk
        routed += 1
    if per_row_local_pads:
        print(f"per-row local trunk spine jogs: {per_row_spine_jog_count}")

    per_row_spine_events_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/per_row_spine_events_nrow_fm.json"
    with open(per_row_spine_events_path, "w") as f:
        json.dump(per_row_spine_events, f, indent=1)
    print(f"wrote {per_row_spine_events_path} ({len(per_row_spine_events)} spine event(s))")

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
                        cur_x, cur_y = draw_jog(cx, channel_entry_y, clear_x, channel, near_y=channel_entry_y)
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
    force_jog_events = []  # v4.5 (design_notes 38.15): every jog FORCE_JOG_NETS
                            # actually inserted, for a dedicated ERR-layer highlight
                            # so jog placement can be visually cross-checked against
                            # the (253,3) remaining-short overlap polygons.
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
            # v4.6 (this session): also require via-X proximity clearance
            # (via_x_clear) against neighboring tracks' already-registered
            # vias -- channel_clear alone is M2-only and cannot see a
            # too-close M1-pad-vs-M1-pad case (see find_channel_clear_x
            # docstring for the real short this fixed: _003_/txreg[1]).
            if not channel_clear(cx, y_lo, y_hi) or not via_x_clear(channel, track_y, cx):
                clear_x = find_channel_clear_x(cx, y_lo, y_hi,
                                                extra_ok=lambda x: via_x_clear(channel, track_y, x))
                if abs(clear_x - cx) > 1e-6:
                    force_jog_count += 1
                    m2_box(cx - PAD_HALF, min(pin_edge_y, channel_entry_y),
                           cx + PAD_HALF, max(pin_edge_y, channel_entry_y))
                    cur_x, cur_y = draw_jog(cx, channel_entry_y, clear_x, channel, near_y=channel_entry_y)
                    register_via_x(channel, track_y, clear_x)
                    force_jog_events.append({
                        "net": net, "inst": inst_name, "pin": pname,
                        "orig_x": cx, "clear_x": clear_x, "jog_y": cur_y,
                        "channel": channel, "channel_entry_y": channel_entry_y,
                        "track_y": track_y,
                    })
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

    if force_jog_events_path is None:
        force_jog_events_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/force_jog_events_nrow_fm.json"
    with open(force_jog_events_path, "w") as f:
        json.dump(force_jog_events, f, indent=1)
    print(f"wrote {force_jog_events_path} ({len(force_jog_events)} jog event(s))")

    channel_usage = []
    for c in range(n_ch):
        budget = int((CH_HEIGHTS[c] - 2 * TRACK0_OFFSET) // TRACK_PITCH) + 1
        used = next_free_idx[c]
        status = "OK" if used <= budget else "OVERFLOW"
        print(f"  channel{c}: used {used} tracks, budget {budget} ({CH_HEIGHTS[c]} um) -> {status}")
        # real geometry extent (section 41 -- channel compression post-process):
        # max Y actually reached by M1/M2/via_1 drawn in this channel's band,
        # relative to the channel's own bottom edge. This is the ground-truth
        # figure for "how tall does this channel really need to be" -- more
        # reliable than the track-count budget formula, which was observed to
        # slightly OVER-count relative to real geometry in at least one case
        # (channel0: 23 "used" tracks vs. budget 22, yet actual max M1 Y was
        # 87.7um, safely under the 90um budget -- see design_notes.md 40.4).
        # real SIGNAL geometry extent (section 41 -- channel compression
        # post-process): max Y actually reached by M1/M2/via_1 drawn in
        # this channel's band, relative to the channel's own bottom edge,
        # EXCLUDING the TAP2 VDD/GND power-mesh strap columns (draw_tap_
        # power_mesh() always runs those the FULL channel height by
        # construction -- see TAP_GND_X_LOCAL/TAP_VDD_X_LOCAL -- so
        # including them would always measure "full height used" and
        # defeat the purpose). More reliable than the track-count budget
        # formula above, which was found to disagree with real geometry
        # in both directions (channel0 in the original run: 23 "used"
        # tracks vs budget 22, yet real max M1 Y was only 87.7 of a 90um
        # budget; see design_notes.md 40.4/41).
        band_lo, band_hi = ch_y0[c], ch_y0[c] + CH_HEIGHTS[c]
        tap_x_ranges = []
        for row_insts in rows:
            for inst in row_insts:
                if inst["type"] == TAP_CELL:
                    x0 = inst["x"]
                    tap_x_ranges.append((x0 + TAP_GND_X_LOCAL[0], x0 + TAP_GND_X_LOCAL[1]))
                    tap_x_ranges.append((x0 + TAP_VDD_X_LOCAL[0], x0 + TAP_VDD_X_LOCAL[1]))
            break  # TAP columns are at identical X in every row, by construction
        v1_idx = layout.layer(*V1_LAYER)
        max_y_rel = 0.0
        for lyr_idx in (m1_idx, m2_idx, v1_idx):
            probe = db.Box(0, um(band_lo, dbu), um(ROW_WIDTH_UM, dbu), um(band_hi, dbu))
            r = db.Region(top.begin_shapes_rec_touching(lyr_idx, probe))
            if r.count() == 0:
                continue
            for tx0, tx1 in tap_x_ranges:
                tap_box = db.Box(um(tx0 - 0.1, dbu), um(band_lo, dbu), um(tx1 + 0.1, dbu), um(band_hi, dbu))
                r -= db.Region(tap_box)
            if r.count() == 0:
                continue
            b = r.bbox()
            top_um = min(b.top * dbu, band_hi)  # clip: a shape can straddle into the next row
            max_y_rel = max(max_y_rel, top_um - band_lo)
        channel_usage.append({"channel": c, "used_tracks": used, "budget_tracks": budget,
                               "height_um": CH_HEIGHTS[c], "max_signal_geom_y_um": round(max_y_rel, 3)})
    if channel_usage_path:
        with open(channel_usage_path, "w") as f:
            json.dump(channel_usage, f, indent=1)
        print(f"wrote {channel_usage_path}")

    layout.write(out_gds)

    with open(pin_map_path, "w") as f:
        json.dump(pin_map, f, indent=1)

    with open(net_shapes_path, "w") as f:
        json.dump(net_shapes, f)

    print(f"wrote {out_gds}")
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
    # optional CLI overrides (section 40): placement_json in_gds out_gds
    _a = sys.argv[1:]
    _pj = _a[0] if len(_a) > 0 and _a[0] != "-" else PLACEMENT_JSON
    _ig = _a[1] if len(_a) > 1 and _a[1] != "-" else IN_GDS
    _og = _a[2] if len(_a) > 2 and _a[2] != "-" else OUT_GDS
    main(placement_json=_pj, in_gds=_ig, out_gds=_og)
