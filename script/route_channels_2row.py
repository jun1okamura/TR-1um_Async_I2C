"""
route_channels_2row.py

Channel router for the section-37 two-row trial. Extends
route_row_channels.py's method (exact LEF pin positions, exclusive
per-pin X track, provably-correct interval-graph coloring -> no search,
no post-hoc clearance check) to 3 channels (bottom margin / shared
middle / top margin) around 2 stacked rows.

Per-net channel eligibility (same classification as
estimate_channel_tracks_2row.py):
  - row1-only net -> bottom channel (below row1) or middle channel
    (above row1). First-fit lane assignment on row1-only nets alone,
    then the lower half of lanes go to bottom, the upper half to
    middle.
  - row2-only net -> middle channel (below row2) or top channel (above
    row2). Same half-split, lower half -> middle, upper half -> top.
  - cross-row net (pins in both rows) -> middle channel only (the sole
    channel touching both rows). One M2 stub per pin: row1 pins stub
    upward to the shared track, row2 pins stub downward.

The middle channel is shared by three independent lane-assignment
results (cross, row1's upper half, row2's lower half) that were each
colored without knowledge of the other two, so lanes are stacked
(concatenated), not jointly re-colored. This is not track-minimal but
is correct by construction and was already budgeted for by
estimate_channel_tracks_2row.py's conservative (+margin) track counts,
which gen_placement_gds_2row.py's channel heights were sized to.

Two clearance cases turned out NOT to be automatically safe, both found
empirically (DRC for the first, the layer-aware connectivity checker
for the second -- neither was predicted from the design policy alone):

1. M1 via-pad vs via-pad on Y-adjacent tracks: the local M1 via-landing
   pad is 3.4um square (VIA 1.4 + 1.0 enclosure x2) but the track pitch
   is only 4.0um, leaving a 0.6um gap between two different nets' pads
   if their via X positions coincide or nearly coincide -- below the
   1.4um M1 minimum spacing. DRC-visible (space violation).

2. M2 stub vs M2 stub, far apart in track index but both LONG: a net
   assigned to a track far from its row needs an M2 stub running the
   full vertical distance at its pin's raw X. Pin X positions are
   grid-derived (multiples of the 5.4um cell track), so two entirely
   unrelated pins -- in different cells, assigned to very different
   tracks -- routinely land on the exact same X by coincidence (136
   such coincidences found in this trial's row1/row2 pin set). Two
   stubs at the same X with overlapping Y-spans simply merge into one
   polygon: DRC reports no violation (there's no gap to measure, they
   fused), but the two nets are electrically shorted. Only the
   layer-aware connectivity checker (design_notes.md 36.4) catches
   this -- it's invisible to DRC by construction.

Both are really the same underlying issue: pin X-exclusivity is only
guaranteed WITHIN one cell's own pin grid (section 35's whole
correctness argument), not across the thousands of X positions
produced by placing many different cell instances on the shared
5.4um grid. Rather than change the documented 4.0um M1 track pitch or
the 5.4um cell grid (both are load-bearing elsewhere), case 1 is
fixed locally in `collides()`/the track-bump loop below: it nudges a
colliding net to a spare track index (there is always margin -- the
channel heights were sized with a +2-track safety margin) so no two
nets' via pads ever land on Y-adjacent tracks at a colliding X.

Case 2 was NOT fixed with a per-pin jog, after that approach was
actually implemented and found not to scale. A first version (jog
right at the pin edge, search a small X window) failed to even find a
legal corridor for many pins once the search window was widened enough
to matter. A second version (checked the jog's own connecting path for
collisions too, not just the final lane) still failed: with ~517
signal pins funneling through a handful of shared row edges into an
80-plus-track channel, nearly every stub's Y-span overlaps nearly every
other one's (peak simultaneous overlap measured at 122 of 122 in the
bottom channel and 229 of 384 in the middle channel), so a jog for one
pin routinely has no choice but to cross another pin's already-reserved
stub somewhere along its path. Avoiding that in general is a real
detailed/maze-router problem (multi-level doglegs, not a single jog at
a fixed Y), which is out of scope for this trial. The routed GDS below
is therefore DRC-clean but the layer-aware connectivity checker still
finds real shorts from case 2 (see the session report handed back to
the user); this is a known, documented limitation of the simple
per-net "no search" router at this channel depth, not of the
underlying section-35 cell/grid architecture.
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_2row.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_2row_placement.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_2row_routed.gds"
TOP_CELL_NAME = "i2c_slave_async_2row"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
V1_LAYER = (19, 0)

M1_TRUNK_WIDTH = 1.8
M1_PAD_SIZE = 3.4
VIA_SIZE = 1.4

TRACK_PITCH = 4.0
TRACK0_OFFSET = 2.0
LANE_MARGIN = 2.0

# must match gen_placement_gds_2row.py
CH_BOTTOM_UM = 68.0
CH_MIDDLE_UM = 360.0
CH_TOP_UM = 16.0


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
        """-> (channel, primary_track_index) for a net, given its lane
        assignment -- a channel-local track index, not yet a Y coordinate,
        and not yet checked for the Y-adjacent-track pad clearance issue
        (see module docstring)."""
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

    channel_y0 = {"bottom": 0.0, "middle": middle_y0, "top": top_y0}
    primary_count = {"bottom": n1_bottom, "middle": middle_total, "top": n2_top}
    next_free_idx = dict(primary_count)  # spares start right after the primary range
    channel_used_x = {}  # (channel, idx) -> [cx, ...] of vias already placed on that track

    MIN_VIA_X_SEP = M1_PAD_SIZE + 1.4  # pad width + M1 min space -> guarantees a
                                        # >=1.4um real gap even against a Y-adjacent
                                        # track's pad (see module docstring, case 1)

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

    # NOTE: case 2 from the module docstring (long M2 stubs at coincidental X
    # crossing each other far from their own track) is NOT fixed here. A
    # per-pin jog was attempted and found to require full detailed-router-grade
    # pathfinding to avoid the jogs themselves crossing other nets' stubs near
    # the shared row edge -- see the session report for details. This routed
    # GDS is DRC-clean but the layer-aware connectivity check still finds
    # ~28 real shorts from case 2, concentrated among row1-only-middle and
    # cross-row nets whose track is far from their pin's row.

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

    pin_map_path = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_2row.json"
    with open(pin_map_path, "w") as f:
        json.dump(pin_map, f, indent=1)

    print(f"wrote {OUT_GDS}")
    print(f"wrote {pin_map_path}")
    print(f"signal nets: {len(nets)}, routed: {routed}, stubs (1 pin, skipped): {stub_nets}")
    print(f"row1-only={len(row1_only)}, row2-only={len(row2_only)}, cross-row={len(cross)}")

    # sanity: verify no channel's track usage exceeds its budgeted height
    def check(name, n_used, height_um):
        budget = int((height_um - 2 * TRACK0_OFFSET) // TRACK_PITCH) + 1
        status = "OK" if n_used <= budget else "OVERFLOW"
        print(f"  {name}: used {n_used} tracks, budget {budget} tracks ({height_um} um) -> {status}")

    check("bottom", final_channel_tracks["bottom"], CH_BOTTOM_UM)
    check("middle", final_channel_tracks["middle"], CH_MIDDLE_UM)
    check("top", final_channel_tracks["top"], CH_TOP_UM)


if __name__ == "__main__":
    main()
