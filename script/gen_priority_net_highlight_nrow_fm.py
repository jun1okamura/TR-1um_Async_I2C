"""
gen_priority_net_highlight_nrow_fm.py

Separate review copy of the routed nrow_fm GDS (does NOT touch
i2c_slave_async_nrow_fm_with_err.gds, the short/jog-focused report)
highlighting the channel-track region actually occupied by each
"priority net" -- a net route_channels_nrow_fm.py assigns a dedicated
guarded track and draws FIRST, ahead of the general per-net loop:

  - high fan-out (>=8 pins) row-only/adjacent-pair nets, NOT also in
    PER_ROW_LOCAL_NETS (currently: _073_, _070_)
  - PER_ROW_LOCAL_NETS (currently: scl_buf0, scl_buf1, _126_buf0,
    _126_buf1, scl_n) -- per-row-local trunk + spine nets

Each net gets its OWN ERR layer (254, i) so it can be toggled/colored
independently in KLayout, drawn from net_shapes_nrow_fm.json ground
truth (every M1/M2 box route_channels_nrow_fm.py actually drew for
that net, including jog/spine doglegs). Every M1 trunk segment (i.e.
every channel-track run) is labeled with the net name so the exact
channel + track it occupies is readable directly in the viewer.

Usage:
    python3 gen_priority_net_highlight_nrow_fm.py
"""
import json

import klayout.db as db

NET_SHAPES_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/net_shapes_nrow_fm.json"
PIN_MAP_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_priority_err.gds"
TOP_CELL = "i2c_slave_async_nrow_fm"

# must match route_channels_nrow_fm.py
PER_ROW_LOCAL_NETS = {"scl_buf0", "scl_buf1", "_126_buf0", "_126_buf1", "scl_n"}
HIGH_FO_THRESHOLD = 8

MARK_LAYER_BASE = 254  # (254, i) per priority net, i assigned below
LABEL_SIZE = 2.0


def main():
    net_shapes = json.load(open(NET_SHAPES_JSON))
    pin_map = json.load(open(PIN_MAP_JSON))

    high_fo_nets = sorted(
        n for n, pads in pin_map.items()
        if len(pads) >= HIGH_FO_THRESHOLD and n not in PER_ROW_LOCAL_NETS
    )
    priority_nets = high_fo_nets + sorted(PER_ROW_LOCAL_NETS)
    print(f"priority nets ({len(priority_nets)}): "
          f"{len(high_fo_nets)} high-FO dedicated-track {high_fo_nets} + "
          f"{len(PER_ROW_LOCAL_NETS)} per-row-local {sorted(PER_ROW_LOCAL_NETS)}")

    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)

    def um(v):
        return int(round(v / dbu))

    def mark_label(x, y, label, layer_idx):
        t = db.Text(label, db.Trans(um(x), um(y)))
        t.size = um(LABEL_SIZE)
        top.shapes(layer_idx).insert(t)

    layer_of = {}
    for i, net in enumerate(priority_nets):
        layer_of[net] = layout.layer(MARK_LAYER_BASE, i)

    missing = [n for n in priority_nets if n not in net_shapes]
    if missing:
        print(f"WARNING: no net_shapes entry for: {missing} (not drawn -- stale/missing log?)")

    for net in priority_nets:
        layer_idx = layer_of[net]
        boxes = net_shapes.get(net, [])
        n_m1 = n_m2 = 0
        for kind, x0, y0, x1, y1 in boxes:
            top.shapes(layer_idx).insert(db.Box(um(x0), um(y0), um(x1), um(y1)))
            if kind == "M1":
                n_m1 += 1
                mark_label((x0 + x1) / 2.0, y1 + 1.0, net, layer_idx)
            else:
                n_m2 += 1
        print(f"  net={net:12s} layer=(254,{priority_nets.index(net)})  "
              f"{n_m1} M1 trunk box(es), {n_m2} M2 stub box(es)")

    layout.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")
    print("layer map: " + ", ".join(f"(254,{i})={n}" for i, n in enumerate(priority_nets)))


if __name__ == "__main__":
    main()
