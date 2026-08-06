"""
gen_err_report.py

Generates:
  1. A human-readable text report (Layout/unrouted_report.txt) listing every
     remaining unrouted item: the 86 channel-level open pins (from
     route_all_channels.py's log) and the 15 multi-hop nets' unrouted
     segments (from route_multihop.py's log), with net name, instance/pin,
     and (x,y) position.
  2. A review copy of the routed GDS with an "ERR" layer added, marking
     every unrouted item so it can be visually inspected in KLayout:
       - layer (252,0): channel-level open pins -- a small box + net-name
         text at the pin's own via anchor position.
       - layer (252,1): multi-hop unrouted segments -- a box at each of
         the segment's two endpoint pins, plus a thin connecting box
         showing which two points were supposed to be joined, all
         labeled with the net name.
     Written to a SEPARATE file (i2c_slave_async_layout_with_err.gds) so
     the main routed_all.gds stays exactly as verified (0 DRC violations)
     -- the ERR layer is non-fab, reference-only, same convention as
     layers 250/251 (see gen_gds_placement.py's docstring).

Usage:
    python3 script/gen_err_report.py
Requires the channel + multihop routing logs to already exist at:
    /sessions/dreamy-ecstatic-heisenberg/mnt/outputs/final_channel_log.txt
    /sessions/dreamy-ecstatic-heisenberg/mnt/outputs/final_multihop_log.txt
(regenerate via route_all_channels.py / route_multihop.py if stale)
"""
import re
import sys
import os

import klayout.db as db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_channel as rc  # noqa: E402

IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_all.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_with_err.gds"
REPORT_TXT = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/unrouted_report.txt"
CHANNEL_LOG = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/final_channel_log.txt"
MULTIHOP_LOG = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/final_multihop_log.txt"

ERR_PIN_LAYER = (252, 0)   # channel-level open pins
ERR_SEG_LAYER = (252, 1)   # multi-hop unrouted segment endpoints/lines
DRC_GRID = rc.DRC_GRID


def main():
    channel_log = open(CHANNEL_LOG).read()
    channel_opens = re.findall(
        r'WARNING: net (\S+) pin (\S+) at \(([\d.]+),([\d.]+)\): no clear M2 jog', channel_log)

    multihop_log = open(MULTIHOP_LOG).read()
    mh_segments = re.findall(
        r'WARNING: net (\S+): segment (\S+) -> (\S+) \(([\d.]+),([\d.]+)\)->\(([\d.]+),([\d.]+)\): '
        r'no clear M2 path found', multihop_log)
    mh_segments_reverify = re.findall(
        r'WARNING: net (\S+): segment (\S+) -> (\S+): grid path found but failed exact re-verification',
        multihop_log)
    mh_net_rows = re.findall(r'net=(\S+) rows=(\[[\d, ]+\])', multihop_log)
    mh_net_rows = dict(mh_net_rows[:15])  # first block is the authoritative listing

    # ---------- text report ----------
    lines = []
    lines.append("=" * 78)
    lines.append("未配線レポート (design_notes.md section 28-33 参照)")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"[1] チャネル内オープンピン: {len(channel_opens)} 件")
    lines.append("-" * 78)
    lines.append(f"{'net':<20}{'instance.pin':<20}{'x':>10}{'y':>10}")
    for net, instpin, x, y in sorted(channel_opens, key=lambda t: (t[0], t[1])):
        lines.append(f"{net:<20}{instpin:<20}{float(x):>10.2f}{float(y):>10.2f}")
    lines.append("")
    lines.append(f"[2] マルチホップネット未配線セグメント: "
                  f"{len(mh_segments) + len(mh_segments_reverify)} 件 (対象ネット15件中)")
    lines.append("-" * 78)
    lines.append(f"{'net':<16}{'rows':<14}{'from':<16}{'to':<16}{'x0,y0':<16}{'x1,y1':<16}")
    seg_by_net = {}
    for net, i0, i1, x0, y0, x1, y1 in mh_segments:
        seg_by_net.setdefault(net, []).append((i0, i1, x0, y0, x1, y1))
    for net, i0, i1 in mh_segments_reverify:
        seg_by_net.setdefault(net, []).append((i0, i1, None, None, None, None))
    for net in sorted(seg_by_net):
        rows = mh_net_rows.get(net, "?")
        for i0, i1, x0, y0, x1, y1 in seg_by_net[net]:
            xy0 = f"({float(x0):.1f},{float(y0):.1f})" if x0 else "(再検証で失敗)"
            xy1 = f"({float(x1):.1f},{float(y1):.1f})" if x1 else ""
            lines.append(f"{net:<16}{rows:<14}{i0:<16}{i1:<16}{xy0:<16}{xy1:<16}")
    lines.append("")
    lines.append(f"総計: チャネルオープン {len(channel_opens)} 件 + "
                  f"マルチホップ未配線セグメント {len(mh_segments) + len(mh_segments_reverify)} 件")
    with open(REPORT_TXT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", REPORT_TXT)

    # ---------- ERR layer overlay on a review copy of the GDS ----------
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell("i2c_slave_async_layout")
    err_pin_idx = layout.layer(*ERR_PIN_LAYER)
    err_seg_idx = layout.layer(*ERR_SEG_LAYER)

    def um(v):
        return int(round(round(v / DRC_GRID) * DRC_GRID / dbu))

    MARK = 6.0  # marker box half-size-ish (full size), um

    def mark_pin(x, y, label, layer_idx):
        box = db.Box(um(x - MARK / 2), um(y - MARK / 2), um(x + MARK / 2), um(y + MARK / 2))
        top.shapes(layer_idx).insert(box)
        t = db.Text(label, db.Trans(um(x), um(y + MARK)))
        t.size = um(2.0)
        top.shapes(layer_idx).insert(t)

    for net, instpin, x, y in channel_opens:
        mark_pin(float(x), float(y), f"{net}:{instpin}", err_pin_idx)

    for net, i0, i1, x0, y0, x1, y1 in mh_segments:
        x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
        mark_pin(x0, y0, f"{net}:{i0}", err_seg_idx)
        mark_pin(x1, y1, f"{net}:{i1}", err_seg_idx)
        # thin connecting box (L-shape via two boxes) so the intended link is visible
        top.shapes(err_seg_idx).insert(db.Box(um(min(x0, x1) - 0.5), um(y0 - 0.5),
                                               um(max(x0, x1) + 0.5), um(y0 + 0.5)))
        top.shapes(err_seg_idx).insert(db.Box(um(x1 - 0.5), um(min(y0, y1) - 0.5),
                                               um(x1 + 0.5), um(max(y0, y1) + 0.5)))

    layout.write(OUT_GDS)
    print("wrote", OUT_GDS)
    print(f"ERR layers: {ERR_PIN_LAYER} = channel-open pins, {ERR_SEG_LAYER} = "
          f"multi-hop unrouted segment endpoints/links (non-fab, reference only)")


if __name__ == "__main__":
    main()
