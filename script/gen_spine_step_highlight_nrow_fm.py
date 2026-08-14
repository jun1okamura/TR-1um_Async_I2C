"""
gen_spine_step_highlight_nrow_fm.py

Separate review GDS highlighting, step by step, what route_channels_
nrow_fm.py's Pass 0 (per-row-local trunk + spine, design_notes 38.17)
actually drew for each PER_ROW_LOCAL_NETS net -- built from the
per_row_spine_events_nrow_fm.json event log (one entry per drawing
step, tagged by step name):

  trunk               -- a row's own local M1 trunk (step 1)
  row_jog              -- an X-only M1 jog INSIDE a row's own channel,
                          before punching through that row's cell body
  row_crossing          -- the M2 run punching vertically through a row's
                          cell body (channel -> row -> next channel)
  channel_land           -- direct (no jog needed) landing on the next
                          channel's own fixed track for this net
  channel_jog_fallback  -- rare fallback: direct landing was blocked, so
                          a generic (freshly claimed) track was used
                          instead, near the entry point
  trunk_land_jog         -- final X-only jog onto the destination row's
                          trunk tap point

One ERR layer per step (256, i), each shape labeled with the net name,
so the whole spine-drawing sequence can be replayed/inspected in
KLayout net by net, step by step.

Usage:
    python3 gen_spine_step_highlight_nrow_fm.py
"""
import json
from collections import defaultdict

import klayout.db as db

EVENTS_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/per_row_spine_events_nrow_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_spine_steps_err.gds"
TOP_CELL = "i2c_slave_async_nrow_fm"

PAD_HALF = 3.4 / 2.0
LABEL_SIZE = 2.0
MARK_LAYER_BASE = 256

STEP_ORDER = [
    "trunk", "row_jog", "row_crossing", "channel_land",
    "channel_jog_fallback", "trunk_land_jog",
]


def main():
    events = json.load(open(EVENTS_JSON))
    by_step = defaultdict(list)
    for ev in events:
        by_step[ev["step"]].append(ev)

    steps_present = [s for s in STEP_ORDER if by_step[s]]
    print(f"{len(events)} spine event(s), steps present: "
          + ", ".join(f"{s}={len(by_step[s])}" for s in steps_present))

    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)

    def um(v):
        return int(round(v / dbu))

    layer_of = {}
    for i, step in enumerate(steps_present):
        layer_of[step] = layout.layer(MARK_LAYER_BASE, i)

    for step in steps_present:
        layer_idx = layer_of[step]
        for ev in by_step[step]:
            x, y0, y1, net = ev["x"], ev["y0"], ev["y1"], ev["net"]
            if y1 - y0 < 1e-6:
                y1 = y0 + 1e-6
            box = db.Box(um(x - PAD_HALF), um(y0), um(x + PAD_HALF), um(y1))
            top.shapes(layer_idx).insert(box)
            t = db.Text(f"{step}:{net}", db.Trans(um(x), um(y1 + 1.0)))
            t.size = um(LABEL_SIZE)
            top.shapes(layer_idx).insert(t)

    layout.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")
    print("layer map: " + ", ".join(f"(256,{i})={s}" for i, s in enumerate(steps_present)))


if __name__ == "__main__":
    main()
