"""
gen_055_bitcnt1_highlight_nrow_fm.py

Dedicated review GDS for the one short (design_notes.md 38.22) that
survived the draw_jog departure-leg fix: net=_055_ (pin _423_.B) <->
net=bit_cnt[1] (pin _464_.Q). Highlights WHY this is a structurally
different kind of problem than the two shorts (_115_/_126_buf0,
_080_/_126_buf1) that 38.22 fixed:

  - Those two were about WHICH X the router chose to land a spine
    crossing on -- fixable by searching for a different, already-clear
    X before committing to one.
  - This one is about two DIFFERENT nets' REAL PINS sitting at the
    exact same X in adjacent rows (_423_.B and _464_.Q both at
    x=494.1). Neither pin's X can be moved (they are real standard-
    cell pin locations), and bit_cnt[1]'s own M2 stub at that X spans
    nearly the channel's whole usable height (260.8-442.7, ~182um) --
    channel1 is also at 100% track capacity (65/65) by this point in
    the pipeline, so no track exists whose departure leg can dodge
    bit_cnt[1]'s stub. This is the "no free departure leg anywhere in
    the channel" case draw_jog's new safety check (38.22) correctly
    detects (see route_channels_nrow_fm.py's printed WARNING for this
    exact net/x) but cannot route around, since escaping would require
    moving the ORIGINAL x itself (not possible for a real pin) or
    growing channel1 (CH_HEIGHTS[1]).

Layers (non-fab, review only):
  (257,0) ERR_PIN_COINCIDENCE -- the two nets' real, coincident pin
          locations
  (257,1) ERR_BLOCKING_STUB   -- bit_cnt[1]'s own M2 stub at that X,
          the obstruction that spans nearly the whole channel
  (257,2) ERR_UNCHECKED_DEPARTURE -- _055_/_423_.B's pre-jog M2 run at
          the original x (the segment that could not find a track with
          a clear departure leg)
  (257,3) ERR_ACTUAL_SHORT -- the exact M2-vs-M2 overlap box that is
          the real short (both nets' own metal actually touching)

Usage:
    python3 gen_055_bitcnt1_highlight_nrow_fm.py
"""
import json

import klayout.db as db

NET_SHAPES_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/net_shapes_nrow_fm.json"
FORCE_JOG_EVENTS_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/force_jog_events_nrow_fm.json"
PIN_MAP_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_routed.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_055_bitcnt1_err.gds"
TOP_CELL = "i2c_slave_async_nrow_fm"

PAD_HALF = 3.4 / 2.0
LABEL_SIZE = 2.5
NET_A, PIN_A = "_055_", "_423_.B"
NET_B, PIN_B = "bit_cnt[1]", "_464_.Q"


def main():
    net_shapes = json.load(open(NET_SHAPES_JSON))
    force_jog_events = json.load(open(FORCE_JOG_EVENTS_JSON))
    pin_map = json.load(open(PIN_MAP_JSON))

    # 1. the coincident real pin locations
    jog_ev = next(e for e in force_jog_events if e["net"] == NET_A and e["inst"] == "_423_" and e["pin"] == "B")
    orig_x = jog_ev["orig_x"]
    channel_entry_y = jog_ev["channel_entry_y"]
    jog_y = jog_ev["jog_y"]
    bitcnt1_q = next(p for p in pin_map[NET_B] if p[0] == "_464_" and p[1] == "Q")
    bitcnt1_x, bitcnt1_track_y = bitcnt1_q[2], bitcnt1_q[3]

    # find _055_'s original (pre-jog) pin edge Y from net_shapes: the
    # first M2 segment at this x is the pin-edge-to-channel-entry leg
    a_segs = [s for s in net_shapes[NET_A] if s[0] == "M2" and abs((s[1] + s[3]) / 2.0 - orig_x) < 0.1]
    pin_edge_y = min(s[2] for s in a_segs)
    departure_y_hi = max(s[4] for s in a_segs)  # top of the unconditional pre-jog run

    # bit_cnt[1]'s own M2 stub at (approximately) this X -- the blocking obstruction
    b_segs = [s for s in net_shapes[NET_B] if s[0] == "M2" and abs((s[1] + s[3]) / 2.0 - bitcnt1_x) < 0.5]
    stub_y_lo = min(s[2] for s in b_segs)
    stub_y_hi = max(s[4] for s in b_segs)

    print(f"pin coincidence: {NET_A}/{PIN_A} x={orig_x:.1f}  vs  {NET_B}/{PIN_B} x={bitcnt1_x:.1f}")
    print(f"{NET_A} unconditional departure run: x={orig_x:.1f} y=[{pin_edge_y:.1f},{departure_y_hi:.1f}]")
    print(f"{NET_B} blocking stub: x={bitcnt1_x:.1f} y=[{stub_y_lo:.1f},{stub_y_hi:.1f}] "
          f"({stub_y_hi - stub_y_lo:.1f}um span)")

    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL)

    def um(v):
        return int(round(v / dbu))

    def box_layer(layer, x0, y0, x1, y1, label=None, label_y=None):
        top.shapes(layer).insert(db.Box(um(x0 - PAD_HALF), um(y0), um(x1 + PAD_HALF), um(y1)))
        if label:
            t = db.Text(label, db.Trans(um((x0 + x1) / 2.0), um((label_y if label_y is not None else y1) + 1.0)))
            t.size = um(LABEL_SIZE)
            top.shapes(layer).insert(t)

    l_pin = layout.layer(257, 0)
    l_stub = layout.layer(257, 1)
    l_dep = layout.layer(257, 2)
    l_short = layout.layer(257, 3)

    # (257,0) the two coincident real pin points
    box_layer(l_pin, orig_x, pin_edge_y - 1.0, orig_x, pin_edge_y + 1.0,
              f"PIN:{NET_A}/{PIN_A} x={orig_x:.1f}", label_y=pin_edge_y + 2.0)
    box_layer(l_pin, bitcnt1_x, bitcnt1_track_y - 1.0, bitcnt1_x, bitcnt1_track_y + 1.0,
              f"PIN:{NET_B}/{PIN_B} x={bitcnt1_x:.1f}", label_y=bitcnt1_track_y + 2.0)

    # (257,1) bit_cnt[1]'s blocking stub -- spans nearly the whole channel
    box_layer(l_stub, bitcnt1_x, stub_y_lo, bitcnt1_x, stub_y_hi,
              f"BLOCKING STUB:{NET_B} span={stub_y_hi - stub_y_lo:.0f}um (channel1 100% capacity)",
              label_y=stub_y_hi + 1.0)

    # (257,2) _055_'s unconditional pre-jog departure run
    box_layer(l_dep, orig_x, pin_edge_y, orig_x, departure_y_hi,
              f"UNCHECKED DEPARTURE:{NET_A}/{PIN_A} (target near_y={channel_entry_y:.1f}, "
              f"landed y={jog_y:.1f} -- no track found w/ clear leg)",
              label_y=departure_y_hi + 3.0)

    # (257,3) the actual M2-vs-M2 short overlap (intersection of the two spans)
    ov_lo, ov_hi = max(pin_edge_y, stub_y_lo), min(departure_y_hi, stub_y_hi)
    if ov_lo < ov_hi:
        box_layer(l_short, orig_x, ov_lo, orig_x, ov_hi,
                  f"SHORT: {NET_A} <-> {NET_B}", label_y=ov_hi + 5.0)
        print(f"actual short overlap: x={orig_x:.1f} y=[{ov_lo:.1f},{ov_hi:.1f}]")

    layout.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")
    print("layer map: (257,0)=coincident pins, (257,1)=bit_cnt[1] blocking stub, "
          "(257,2)=_055_ unchecked departure run, (257,3)=actual short overlap")


if __name__ == "__main__":
    main()
