"""
route_channels_2row_fm.py

FM-partitioned variant of route_channels_2row.py -- identical routing
algorithm (see that file's docstring for the full method and the two
known clearance cases / case-1 fix), just pointed at the FM-split
placement (LEF/placement_2row_fm.json) and its smaller channel budget
(gen_placement_gds_2row_fm.py). The point of this run: with cross-row
nets cut from 76 (peak 56) to 14 (peak 7) by FM partitioning
(fm_partition.py), the middle channel is far shallower, so far fewer
pins need a long M2 stub -- this should substantially shrink (not
necessarily eliminate) the case-2 long-stub-crossing short count found
in the naive-split trial (28 shorts).
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_2row_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_2row_fm_placement.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_2row_fm_routed.gds"
TOP_CELL_NAME = "i2c_slave_async_2row_fm"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
V1_LAYER = (19, 0)

M1_TRUNK_WIDTH = 1.8
M1_PAD_SIZE = 3.4
VIA_SIZE = 1.4

TRACK_PITCH = 4.0
TRACK0_OFFSET = 2.0
LANE_MARGIN = 2.0

# must match gen_placement_gds_2row_fm.py
CH_BOTTOM_UM = 120.0
CH_MIDDLE_UM = 270.0
CH_TOP_UM = 112.0


def um(v, dbu):
    return int(round(v / dbu))


def collect_nets(placement, row1_y0, row2_y0):
    """net -> list of (row, inst_name, pname, x0, y0_abs, x1, y1_abs)."""
    nets = {}
    for row_key, row_idx, yoff in (("row1", 1, row1_y0), ("row2", 2, row2_y0)):
        for inst in placement[row_key]:
            for pname, pinfo in inst["pins"].items():
                if pinfo["use"] in ("POWER", "GROUND"):
                    continue
                for layer, x0, y0, x1, y1 in pinfo["rects"]:
                    if layer != "M2":
                        continue
                    nets.setdefault(pinfo["net"], []).append(
                        (row_idx, inst["name"], pname, x0, y0 + yoff, x1, y1 + yoff))
    return nets


def assign_lanes(nets_subset):
    """First-fit interval coloring over a net->pads dict. Returns
    ({net: lane}, n_lanes)."""
    items = []
    for net, pads in nets_subset.items():
        xs = [(x0 + x1) / 2.0 for _r, _i, _p, x0, y0, x1, y1 in pads]
        items.append((net, min(xs), max(xs)))
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
    row_h = placement["row_height"]

    row1_y0 = CH_BOTTOM_UM
    middle_y0 = CH_BOTTOM_UM + row_h
    row2_y0 = middle_y0 + CH_MIDDLE_UM
    top_y0 = row2_y0 + row_h
    core_h = top_y0 + CH_TOP_UM

    nets = collect_nets(placement, row1_y0, row2_y0)

    row1_only, row2_only, cross = {}, {}, {}
    stub_nets = 0
    for net, pads in nets.items():
        if len(pads) < 2:
            stub_nets += 1
            continue
        rows = {p[0] for p in pads}
        if rows == {1}:
            row1_only[net] = pads
        elif rows == {2}:
            row2_only[net] = pads
        else:
            cross[net] = pads

    a1, n1 = assign_lanes(row1_only)
    a2, n2 = assign_lanes(row2_only)
    ac, nc = assign_lanes(cross)

    n1_bottom = -(-n1 // 2)  # ceil: lanes [0, n1_bottom) -> bottom channel
    n1_middle = n1 - n1_bottom  # lanes [n1_bottom, n1) -> middle channel
    n2_middle = -(-n2 // 2)  # lanes [0, n2_middle) -> middle channel
    n2_top = n2 - n2_middle  # lanes [n2_middle, n2) -> top channel

    middle_total = nc + n1_middle + n2_middle
    print(f"lanes: row1-only n1={n1} (bottom={n1_bottom}, middle={n1_middle}), "
          f"row2-only n2={n2} (middle={n2_middle}, top={n2_top}), cross nc={nc}")
    print(f"channel track usage: bottom={n1_bottom}, middle={middle_total}, top={n2_top}")

    def channel_primary(net):
        if net in row1_only:
            lane = a1[net]
            if lane < n1_bottom:
                return "bottom", lane
            return "middle", nc + (lane - n1_bottom)
        if net in row2_only:
            lane = a2[net]
            if lane < n2_middle:
                return "middle", nc + n1_middle + lane
            return "top", lane - n2_middle
        lane = ac[net]  # cross
        return "middle", lane

    # NOTE: a generalized version of this check (comparing every pin's full
    # stub reach -- X and actual [y_lo, y_hi] span -- against every other
    # pin's stub in the channel, not just Y-adjacent-track vias) was tried
    # here to also close case 2. It was reverted: bumping a net to a spare
    # track pushes that net's track_y further from its row, which *enlarges*
    # its stub's Y-span, which can trigger new collisions with other already
    # -placed stubs, cascading the same way the naive-split trial's runaway
    # bumping did (design_notes.md 37.4/37.6). FM partitioning shrank case 2
    # from 28 to 7 shorts, but did not make a bump-based fix for it safe in
    # general -- it stays open, same as the naive-split trial, just smaller.
    channel_y0 = {"bottom": 0.0, "middle": middle_y0, "top": top_y0}
    primary_count = {"bottom": n1_bottom, "middle": middle_total, "top": n2_top}
    next_free_idx = dict(primary_count)  # spares start right after the primary range
    channel_used_x = {}  # (channel, idx) -> [cx, ...] of vias already placed on that track

    MIN_VIA_X_SEP = M1_PAD_SIZE + 1.4  # pad width + M1 min space (case 1, see
                                        # route_channels_2row.py's docstring)

    def collides(channel, idx, cxs):
        for nb in (idx - 1, idx, idx + 1):
            for ux in channel_used_x.get((channel, nb), []):
                for cx in cxs:
                    if abs(cx - ux) < MIN_VIA_X_SEP:
                        return True
        return False

    final_track = {}  # net -> (channel, track_y_um)
    bumped = 0
    for net, pads in {**row1_only, **row2_only, **cross}.items():
        channel, idx = channel_primary(net)
        cxs = [(x0 + x1) / 2.0 for _row, _inst, _pname, x0, y0, x1, y1 in pads]
        if collides(channel, idx, cxs):
            bumped += 1
            idx = next_free_idx[channel]
            next_free_idx[channel] += 1
            while collides(channel, idx, cxs):
                idx = next_free_idx[channel]
                next_free_idx[channel] += 1
        channel_used_x.setdefault((channel, idx), []).extend(cxs)
        final_track[net] = (channel, channel_y0[channel] + TRACK0_OFFSET + idx * TRACK_PITCH)

    if bumped:
        print(f"via-pad Y-adjacency collisions (case 1) resolved by moving {bumped} net(s) to a spare track")
    final_channel_tracks = {ch: next_free_idx[ch] for ch in ("bottom", "middle", "top")}

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

    routed = 0
    all_nets = {}
    all_nets.update(row1_only)
    all_nets.update(row2_only)
    all_nets.update(cross)

    pin_map = {}  # net -> [(inst_name, pname, vx, vy), ...] -- via center, for verification
    for net, pads in all_nets.items():
        channel, track_y = final_track[net]
        pin_cxs = []
        for row, inst_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            pin_cxs.append(cx)
            pin_map.setdefault(net, []).append((inst_name, pname, cx, track_y))

            if channel == "bottom":
                m2_lo, m2_hi = track_y, y0
            elif channel == "top":
                m2_lo, m2_hi = y1, track_y
            else:  # middle
                if row == 1:
                    m2_lo, m2_hi = y1, track_y
                else:
                    m2_lo, m2_hi = track_y, y0
            m2_box(x0, m2_lo, x1, m2_hi)
            via_box(cx, track_y)
            half = M1_PAD_SIZE / 2.0
            m1_box(cx - half, track_y - half, cx + half, track_y + half)

        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1

    layout.write(OUT_GDS)

    pin_map_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_2row_fm.json"
    with open(pin_map_path, "w") as f:
        json.dump(pin_map, f, indent=1)

    print(f"wrote {OUT_GDS}")
    print(f"wrote {pin_map_path}")
    print(f"signal nets: {len(nets)}, routed: {routed}, stubs (1 pin, skipped): {stub_nets}")
    print(f"row1-only={len(row1_only)}, row2-only={len(row2_only)}, cross-row={len(cross)}")

    def check(name, n_used, height_um):
        budget = int((height_um - 2 * TRACK0_OFFSET) // TRACK_PITCH) + 1
        status = "OK" if n_used <= budget else "OVERFLOW"
        print(f"  {name}: used {n_used} tracks, budget {budget} tracks ({height_um} um) -> {status}")

    check("bottom", final_channel_tracks["bottom"], CH_BOTTOM_UM)
    check("middle", final_channel_tracks["middle"], CH_MIDDLE_UM)
    check("top", final_channel_tracks["top"], CH_TOP_UM)


if __name__ == "__main__":
    main()
