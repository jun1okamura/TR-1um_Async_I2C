"""
estimate_channel_tracks_2row.py

Section 37: track-count estimate for the 3-channel stack (bottom
margin / shared middle / top margin) around the two-row placement.
Extends estimate_channel_tracks.py's method (max-simultaneous-overlap
via sweep line) with per-net channel eligibility:

  - a net with pins ONLY in row1 can use the bottom-margin channel or
    the middle channel (row1's top edge touches middle).
  - a net with pins ONLY in row2 can use the middle channel or the
    top-margin channel.
  - a net with pins in BOTH rows (a "cross-row" net) can ONLY use the
    middle channel -- it's the sole channel touching both rows.

This estimate assumes each row's own single-row nets split evenly
between their two eligible channels (matching the single-row trial's
halving approach) -- the real router (task 9) does genuine per-net
assignment, which should do at least this well, so these numbers are
a conservative (safe, not undersized) planning target.
"""
import json
from collections import defaultdict

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_2row.json"
M1_PITCH_UM = 4.0


def net_pin_x(placement):
    net_pins = defaultdict(list)  # net -> [(row, x_center), ...]
    for row_key, row_idx in (("row1", 1), ("row2", 2)):
        for inst in placement[row_key]:
            for pname, pinfo in inst["pins"].items():
                if pinfo["use"] in ("POWER", "GROUND"):
                    continue
                for layer, x0, y0, x1, y1 in pinfo["rects"]:
                    if layer != "M2":
                        continue
                    net_pins[pinfo["net"]].append((row_idx, (x0 + x1) / 2.0))
    return net_pins


def classify(net_pins):
    row1_only, row2_only, cross, stubs = {}, {}, {}, 0
    for net, pins in net_pins.items():
        if len(pins) < 2:
            stubs += 1
            continue
        rows = {r for r, x in pins}
        xs = [x for r, x in pins]
        interval = (min(xs), max(xs))
        if rows == {1}:
            row1_only[net] = interval
        elif rows == {2}:
            row2_only[net] = interval
        else:
            cross[net] = interval
    return row1_only, row2_only, cross, stubs


def max_overlap(intervals):
    events = []
    for x0, x1 in intervals.values():
        events.append((x0, 1))
        events.append((x1, -1))
    events.sort(key=lambda e: (e[0], -e[1]))
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def main():
    placement = json.load(open(PLACEMENT_JSON))
    net_pins = net_pin_x(placement)
    row1_only, row2_only, cross, stubs = classify(net_pins)

    p1 = max_overlap(row1_only)
    p2 = max_overlap(row2_only)
    pc = max_overlap(cross)

    margin = 2
    bottom_tracks = -(-p1 // 2) + margin
    top_tracks = -(-p2 // 2) + margin
    middle_tracks = pc + (-(-p1 // 2)) + (-(-p2 // 2)) + margin

    bottom_um = bottom_tracks * M1_PITCH_UM
    top_um = top_tracks * M1_PITCH_UM
    middle_um = middle_tracks * M1_PITCH_UM
    row_h = placement["row_height"]
    core_h = bottom_um + row_h + middle_um + row_h + top_um

    print(f"nets: row1-only={len(row1_only)} (peak {p1}), row2-only={len(row2_only)} (peak {p2}), "
          f"cross-row={len(cross)} (peak {pc}), stubs={stubs}")
    print(f"bottom margin: {bottom_tracks} tracks = {bottom_um:.1f} um")
    print(f"middle (shared): {middle_tracks} tracks = {middle_um:.1f} um "
          f"(= cross {pc} + row1-half {-(-p1//2)} + row2-half {-(-p2//2)} + margin {margin})")
    print(f"top margin: {top_tracks} tracks = {top_um:.1f} um")
    print(f"total core height = {bottom_um:.1f} + {row_h:.1f} + {middle_um:.1f} + {row_h:.1f} + {top_um:.1f} "
          f"= {core_h:.1f} um")


if __name__ == "__main__":
    main()
