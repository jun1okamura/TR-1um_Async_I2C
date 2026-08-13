"""
estimate_channel_tracks.py

design_notes.md section 14/estimate_m1.py's method, adapted to the new
section-35 architecture: every net's horizontal (X-direction) run now
happens exclusively on M1 inside a channel (design decision confirmed
in the "M2 always vertical, never X-direction over cells" thread), at
M1 pitch = 4.0um. VDD/GND are excluded (delivered separately by the
TAP2 M2 straps, not signal-channel routing).

For each signal net, take every pin's M2-port center X in this row
(from LEF/placement_row.json), giving an [xmin, xmax] interval (nets
with only one pin in the row are zero-width stubs and excluded, same
as the original estimate_m1.py). The minimum M1 track count needed is
the classic "max simultaneous interval overlap" (sweep-line), doubled
here into two independent channels (above / below the row) that can
each take a disjoint subset of nets -- so the number actually reported
is the max-overlap count *split as evenly as possible* between the two
channels, not the raw max-overlap number itself.
"""
import json
from collections import defaultdict

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_row.json"
M1_PITCH_UM = 4.0


def net_x_intervals(placement):
    net_xs = defaultdict(list)
    for inst in placement["instances"]:
        for pname, pinfo in inst["pins"].items():
            if pinfo["use"] in ("POWER", "GROUND"):
                continue
            for layer, x0, y0, x1, y1 in pinfo["rects"]:
                if layer != "M2":
                    continue
                cx = (x0 + x1) / 2.0
                net_xs[pinfo["net"]].append(cx)

    intervals = {}
    for net, xs in net_xs.items():
        if len(xs) < 2:
            continue  # single-pin-in-row stub, no horizontal run needed
        intervals[net] = (min(xs), max(xs))
    return intervals


def max_overlap(intervals):
    events = []
    for net, (x0, x1) in intervals.items():
        events.append((x0, 1))
        events.append((x1, -1))
    events.sort(key=lambda e: (e[0], -e[1]))  # opens before closes at same x
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def main():
    placement = json.load(open(PLACEMENT_JSON))
    intervals = net_x_intervals(placement)
    peak = max_overlap(intervals)

    # Two channels (above + below the row) can split the load. A single
    # net's own run still has to live entirely in ONE channel (can't split
    # one net's horizontal run across both), so a perfect 50/50 split of
    # peak isn't guaranteed by construction -- but the greedy split used
    # in the actual channel router (task 4) approaches it in practice.
    # For a track-count estimate we report the even split, ceil'd, plus a
    # documented margin.
    per_channel_min = -(-peak // 2)  # ceil
    margin = 2
    per_channel_target = per_channel_min + margin

    height_min = per_channel_min * M1_PITCH_UM
    height_target = per_channel_target * M1_PITCH_UM

    print(f"signal nets needing horizontal routing: {len(intervals)}")
    print(f"peak simultaneous overlap (single channel, all nets): {peak} tracks")
    print(f"split across 2 channels (above+below row):")
    print(f"  per-channel minimum: {per_channel_min} tracks = {height_min:.1f} um")
    print(f"  + margin {margin} tracks -> recommended: {per_channel_target} tracks "
          f"= {height_target:.1f} um per channel")
    print(f"total core height = channel + row + channel = "
          f"{height_target:.1f} + {placement['row_height']:.1f} + {height_target:.1f} = "
          f"{2*height_target + placement['row_height']:.1f} um")


if __name__ == "__main__":
    main()
