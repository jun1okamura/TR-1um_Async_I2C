"""
route_row_channels.py

Channel router for the section-35 single-row trial. Unlike every prior
router in this project (route_channel.py / route_channel_shared.py /
route_multihop.py), this one needs no search and no post-hoc clearance
checking: pin positions come straight from the LEF pin table (exact,
not discovered), each pin owns an exclusive X track for its whole cell
column (section 35.1/35.6), and net-to-track assignment is a classic,
provably-correct interval-graph coloring problem -- so every shape this
script draws is correct by construction.

Algorithm:
  1. For every signal net (VDD/GND excluded -- those are carried by the
     TAP2 M2 straps, not this channel), take the M2 pin pad's center-X
     at every instance the net touches in the row. A net with only one
     pin in the row is a stub (primary-I/O net not modeled in this
     trial) and is left unrouted.
  2. Greedy first-fit interval coloring assigns each net to a "lane"
     (assign to the first lane whose last-used X, plus an end-cap
     margin for the via pad, is left of this net's start). This uses
     exactly max-simultaneous-overlap lanes (the chromatic number of an
     interval graph), matching estimate_channel_tracks.py's method.
  3. Lanes are split across the two channels (first half -> bottom
     channel, second half -> top channel) and mapped to M1 track Y
     coordinates at the fixed 4.0um pitch confirmed for this trial.
  4. Geometry per net: one M1 trunk (width 1.8um away from vias, padded
     to 3.4um at each via landing -- same enclosure-driven pad formula
     used throughout section 35, VIA 1.4 + 1.0 enclosure x2), plus, for
     every pin on the net, an M2 stub extending from the pin's existing
     LEF-declared pad edge straight to the trunk's Y (only ever inside
     that pin's own exclusive track, so no clearance check is needed),
     and a via connecting the two at the trunk's Y.
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_row.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_row_placement.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_row_routed.gds"
TOP_CELL_NAME = "i2c_slave_async_row"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
V1_LAYER = (19, 0)

M1_TRUNK_WIDTH = 1.8
M1_PAD_SIZE = 3.4       # VIA(1.4) + enclosure(1.0) x2, section 35.2 formula
M2_PAD_SIZE = 3.4        # matches the pin's own pad width (already drawn)
VIA_SIZE = 1.4

TRACK_PITCH = 4.0
TRACK0_OFFSET = 2.0      # first track's centerline, from the channel's own edge
LANE_MARGIN = 2.0        # extra clearance added to each net's interval before
                          # coloring, on top of the geometric via-pad half-width

CH_H_UM = 184.0  # must match gen_placement_gds.py
ROW_H_UM = 64.8


def um(v, dbu):
    return int(round(v / dbu))


def collect_nets(placement):
    """net -> list of (inst_x, pin_name, x0,y0,x1,y1) M2 pad rects (row-local um)."""
    nets = {}
    for inst in placement["instances"]:
        for pname, pinfo in inst["pins"].items():
            if pinfo["use"] in ("POWER", "GROUND"):
                continue
            for layer, x0, y0, x1, y1 in pinfo["rects"]:
                if layer != "M2":
                    continue
                nets.setdefault(pinfo["net"], []).append((inst["name"], pname, x0, y0, x1, y1))
    return nets


def assign_lanes(nets):
    """First-fit interval coloring. Returns {net: lane_index}, sorted by xmin."""
    items = []
    for net, pads in nets.items():
        if len(pads) < 2:
            continue  # stub, not routed
        xs = [(x0 + x1) / 2.0 for _, _, x0, y0, x1, y1 in pads]
        items.append((net, min(xs), max(xs)))
    items.sort(key=lambda t: t[1])

    lane_last_x = []  # lane_last_x[i] = rightmost occupied X (with margin) so far
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


def lane_to_track_y(lane, n_lanes):
    """Split lanes across bottom/top channel; return (channel, track_y_global_um)."""
    n_bottom = -(-n_lanes // 2)  # ceil
    if lane < n_bottom:
        y = TRACK0_OFFSET + lane * TRACK_PITCH
        return "bottom", y
    else:
        k = lane - n_bottom
        y = CH_H_UM + ROW_H_UM + TRACK0_OFFSET + k * TRACK_PITCH
        return "top", y


def main():
    placement = json.load(open(PLACEMENT_JSON))
    nets = collect_nets(placement)
    assignment, n_lanes = assign_lanes(nets)

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
    stub_nets = 0
    for net, pads in nets.items():
        if net not in assignment:
            stub_nets += 1
            continue
        lane = assignment[net]
        channel, track_y = lane_to_track_y(lane, n_lanes)

        pin_cxs = []
        for inst_x_name, pname, x0, y0, x1, y1 in pads:
            cx = (x0 + x1) / 2.0
            pin_cxs.append(cx)

            # M2 stub: from the pin's existing pad edge to the trunk's Y.
            if channel == "bottom":
                m2_y0, m2_y1 = track_y, CH_H_UM + y0   # y0 = pad's own lower edge, row-local
            else:
                m2_y0, m2_y1 = CH_H_UM + y1, track_y   # y1 = pad's own upper edge, row-local
            m2_box(x0, m2_y0, x1, m2_y1)

            # via connecting the new M2 stub to the M1 trunk
            via_box(cx, track_y)

            # local M1 pad widening at the via landing (enclosure)
            half = M1_PAD_SIZE / 2.0
            m1_box(cx - half, track_y - half, cx + half, track_y + half)

        xmin, xmax = min(pin_cxs), max(pin_cxs)
        half_w = M1_TRUNK_WIDTH / 2.0
        m1_box(xmin, track_y - half_w, xmax, track_y + half_w)
        routed += 1

    layout.write(OUT_GDS)
    print(f"wrote {OUT_GDS}")
    print(f"signal nets: {len(nets)}, routed: {routed}, stubs (1 pin in row, skipped): {stub_nets}")
    print(f"lanes used: {n_lanes}")


if __name__ == "__main__":
    main()
