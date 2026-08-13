"""
estimate_channel_tracks_nrow_fm.py

Section 38: track-count estimate for the N+1 channel stack around the
N-row FM-partitioned placement (LEF/placement_nrow_fm.json). Generalizes
estimate_channel_tracks_2row.py's per-net channel eligibility to N rows:

  - a net touching only row r ("row-only") can use channel r (below) or
    channel r+1 (above) -- split its estimated lane count evenly between
    them, same halving approximation as the 2-row trial.
  - a net touching exactly two ADJACENT rows r, r+1 ("adjacent-pair") can
    ONLY use channel r+1, the one channel that touches both.
  - a net touching 3+ rows, or two non-adjacent rows ("spanning") needs a
    channel somewhere in [r_min, r_max+1] and must pass straight through
    every row strictly between its own pins' rows and that channel (see
    design_notes.md section 38: cells carry no M2 besides their own pins,
    so a vertical M2 run can pass through a row's cells at any X the
    row's own pins don't use -- this is why route_channels_nrow_fm.py
    distributes FILL cells throughout each row, section 38.1, as
    plentiful verified-clear pass-through X candidates). For this
    estimate, each spanning net is greedily assigned to whichever legal
    channel currently has the lowest running net count -- a coarse
    load-balance approximation, not true interval coloring (that happens
    for real in the router).

This is a planning estimate; the router does genuine per-channel lane
assignment (first-fit interval coloring, same as every router in this
project) which may need slightly more tracks -- gen_placement_gds_nrow_fm
.py's channel heights should keep the same margin the 2-row trial did
(the router's actual track usage came in ~15-20% above this kind of
estimate there).
"""
import json
import math
from collections import defaultdict

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm.json"
M1_PITCH_UM = 4.0
MARGIN_TRACKS = 2


def net_pin_rows_x(placement):
    """net -> [(row, x_center), ...] from M2 signal pins."""
    net_pins = defaultdict(list)
    for r, row_insts in enumerate(placement["rows"]):
        for inst in row_insts:
            for pname, pinfo in inst["pins"].items():
                if pinfo["use"] in ("POWER", "GROUND"):
                    continue
                for layer, x0, y0, x1, y1 in pinfo["rects"]:
                    if layer != "M2":
                        continue
                    net_pins[pinfo["net"]].append((r, (x0 + x1) / 2.0))
    return net_pins


def classify(net_pins):
    row_only = defaultdict(dict)      # row -> {net: (xmin,xmax)}
    adjacent_pair = defaultdict(dict)  # channel -> {net: (xmin,xmax)}
    spanning = []                      # [(net, xmin, xmax, legal_channels)]
    stubs = 0
    for net, pins in net_pins.items():
        if len(pins) < 2:
            stubs += 1
            continue
        rows = sorted({r for r, x in pins})
        xs = [x for r, x in pins]
        interval = (min(xs), max(xs))
        if len(rows) == 1:
            row_only[rows[0]][net] = interval
        elif len(rows) == 2 and rows[1] == rows[0] + 1:
            adjacent_pair[rows[0] + 1][net] = interval
        else:
            legal = list(range(rows[0], rows[-1] + 2))
            spanning.append((net, interval[0], interval[1], legal))
    return row_only, adjacent_pair, spanning, stubs


def max_overlap(intervals):
    events = []
    for x0, x1 in intervals:
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
    n_rows = len(placement["rows"])
    n_ch = n_rows + 1
    row_h = placement["row_height"]

    net_pins = net_pin_rows_x(placement)
    row_only, adjacent_pair, spanning, stubs = classify(net_pins)

    ch_count = [0] * n_ch  # running net-count for spanning-net greedy balance
    ch_tracks = [0.0] * n_ch

    # row-only: half the peak overlap goes to each of the row's two channels
    for r in range(n_rows):
        peak = max_overlap(list(row_only[r].values()))
        half = -(-peak // 2)
        ch_tracks[r] += half
        ch_tracks[r + 1] += half
        ch_count[r] += len(row_only[r])
        ch_count[r + 1] += len(row_only[r])

    # adjacent-pair: full peak overlap on the one shared channel
    for c in range(n_ch):
        peak = max_overlap(list(adjacent_pair[c].values()))
        ch_tracks[c] += peak
        ch_count[c] += len(adjacent_pair[c])

    # spanning: greedy least-loaded legal channel (by net count, coarse)
    for net, xmin, xmax, legal in spanning:
        c = min(legal, key=lambda ch: ch_count[ch])
        ch_count[c] += 1
        ch_tracks[c] += 1  # coarse: 1 track per spanning net (they're few)

    ch_tracks = [t + MARGIN_TRACKS for t in ch_tracks]
    ch_um = [t * M1_PITCH_UM for t in ch_tracks]

    print(f"n_rows={n_rows}, n_channels={n_ch}")
    print(f"stubs (1 pin, unrouted): {stubs}")
    print(f"spanning nets: {len(spanning)}")
    for c in range(n_ch):
        label = "bottom margin" if c == 0 else ("top margin" if c == n_rows else f"channel{c}")
        print(f"  {label:14s}: {ch_tracks[c]:.0f} tracks = {ch_um[c]:.1f} um "
              f"(row-only-half x2 + adjacent-pair {len(adjacent_pair[c])} nets "
              f"+ spanning {sum(1 for n,_,_,l in spanning if min(l,key=lambda ch: ch)<=c<=max(l))} candidates)")

    core_h = sum(ch_um) + n_rows * row_h
    print(f"total core height estimate = {core_h:.1f} um "
          f"(rows: {n_rows}x{row_h:.1f}={n_rows*row_h:.1f}, channels: {sum(ch_um):.1f})")


if __name__ == "__main__":
    main()
