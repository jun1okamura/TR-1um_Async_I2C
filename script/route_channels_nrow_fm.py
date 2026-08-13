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

# must match gen_placement_gds_nrow_fm.py
CH_HEIGHTS = [90.0, 180.0, 220.0, 224.0, 100.0]

ROW_X_TRIES = 200  # +-5.4 .. +-1080um for a row-crossing clear-X search

TAP_CELL = "TAP2"
TAP_GND_X_LOCAL = (1.0, 4.4)
TAP_VDD_X_LOCAL = (6.4, 9.8)
TAP_STRAP_MARGIN = 1.1   # TAP2's own M2 strap starts/stops this far inside the cell edge


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
    spanning_nets = {n: p for n, p in net_pins.items() if n in span_channel_assign}

    final_track = {}
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

    def m1_box(x0, y0, x1, y1):
        top.shapes(m1_idx).insert(db.Box(um(x0, dbu), um(y0, dbu), um(x1, dbu), um(y1, dbu)))

    def m2_box(x0, y0, x1, y1):
        top.shapes(m2_idx).insert(db.Box(um(x0, dbu), um(y0, dbu), um(x1, dbu), um(y1, dbu)))

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

    def find_row_clear_x(row_k, start_x):
        if not x_forbidden(start_x) and row_clear(row_k, start_x):
            return start_x
        for s in range(1, ROW_X_TRIES + 1):
            for cand in (start_x + s * X_GRID, start_x - s * X_GRID):
                if not x_forbidden(cand) and row_clear(row_k, cand):
                    return cand
        raise SystemExit(f"no clear X found for row {row_k} near x={start_x}")

    pin_map = {}
    routed = 0
    passthrough_pins = 0
    jog_count = 0

    # pass 1: row-only / adjacent-pair nets -- unchanged routing, via_1 only
    for net, pads in non_spanning_nets.items():
        channel, track_y = final_track[net]
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            direction = -1 if channel <= row else 1
            pin_edge_y = y0 if direction == -1 else y1
            y_lo, y_hi = min(pin_edge_y, track_y), max(pin_edge_y, track_y)
            m2_box(cx - PAD_HALF, y_lo, cx + PAD_HALF, y_hi)
            place_via(cx, track_y)
            pin_cxs.append(cx)
            pin_map.setdefault(net, []).append((inst_name, pname, cx, track_y))
        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1

    # pass 2: spanning nets -- M2 vertical only; X changes go through a
    # via_1 -> M1 -> via_1 jog on a freshly claimed track
    for net, pads in spanning_nets.items():
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
                    jog_idx = claim_track(jog_channel, [cur_x, clear_x])
                    jog_y = ch_y0[jog_channel] + TRACK0_OFFSET + jog_idx * TRACK_PITCH
                    m2_box(cur_x - PAD_HALF, min(cur_y, jog_y), cur_x + PAD_HALF, max(cur_y, jog_y))
                    place_via(cur_x, jog_y)
                    half_w = M1_TRUNK_WIDTH / 2.0
                    m1_box(min(cur_x, clear_x), jog_y - half_w, max(cur_x, clear_x), jog_y + half_w)
                    place_via(clear_x, jog_y)
                    cur_y = jog_y
                    cur_x = clear_x
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

    for c in range(n_ch):
        budget = int((CH_HEIGHTS[c] - 2 * TRACK0_OFFSET) // TRACK_PITCH) + 1
        used = next_free_idx[c]
        status = "OK" if used <= budget else "OVERFLOW"
        print(f"  channel{c}: used {used} tracks, budget {budget} ({CH_HEIGHTS[c]} um) -> {status}")

    layout.write(OUT_GDS)

    pin_map_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
    with open(pin_map_path, "w") as f:
        json.dump(pin_map, f, indent=1)

    print(f"wrote {OUT_GDS}")
    print(f"wrote {pin_map_path}")
    print(f"signal nets: {len(net_pins)}, routed: {routed}, stubs: {stub_nets}")
    print(f"row-only={sum(len(v) for v in row_only.values())}, "
          f"adjacent-pair={sum(len(v) for v in adjacent_pair.values())}, spanning={len(spanning)}")
    print(f"spanning-net pins requiring a row pass-through: {passthrough_pins}")
    print(f"via_1-based jogs inserted: {jog_count}")


if __name__ == "__main__":
    main()
