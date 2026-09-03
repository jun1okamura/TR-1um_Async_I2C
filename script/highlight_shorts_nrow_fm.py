"""
highlight_shorts_nrow_fm.py (design_notes.md section 108.36, user request
"ショート箇所をハイライトするLayoutを出力ください")

Marks every remaining cross-net metal overlap ("SHORT SUSPECTED" per
verify_connectivity_nrow_fm.py / raw box conflict per ripup_reroute_
shorts.find_conflicts()) directly on a duplicated copy of a routed GDS,
so the user can visually locate and inspect each one in KLayout.

Method: reuses ripup_reroute_shorts.py's own find_conflicts() against the
SAME net_shapes_*.json the router/ripup-reroute pass wrote (exact,
ground-truth per-net drawn-box log -- no independent geometry re-
derivation, so this can never disagree with what verify_connectivity_
nrow_fm.py itself flagged). For each conflicting box pair, computes the
actual overlapping (intersection) region and draws:
  (261, 0): a box covering the overlap region itself (the literal short),
            expanded by HALO_UM so it's easy to spot even for a very
            thin/small overlap.
  (261, 1): a text label "netA x netB" at the overlap region's center.
  (261, 2): a larger, more visible bounding box around BOTH full
            conflicting shapes (not just their overlap), so the user can
            see the two full metal runs involved, not just the pinpoint
            overlap.

Never modifies the input GDS -- always writes a new file.

Run: python3 highlight_shorts_nrow_fm.py <in_gds> <net_shapes_json> <out_gds>
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from ripup_reroute_shorts import find_conflicts  # noqa: E402

TOP_CELL_NAME = "i2c_slave_async_nrow_fm"
MARKER_LAYER_BASE = 261
HALO_UM = 3.0


def main(in_gds, net_shapes_json, out_gds):
    net_shapes = json.load(open(net_shapes_json))
    conflicts = find_conflicts(net_shapes)

    layout = db.Layout()
    layout.read(in_gds)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL_NAME)

    overlap_idx = layout.layer(MARKER_LAYER_BASE, 0)
    text_idx = layout.layer(MARKER_LAYER_BASE, 1)
    bbox_idx = layout.layer(MARKER_LAYER_BASE, 2)

    def um(v):
        return int(round(v / dbu))

    def overlap_1d(a0, a1, b0, b1):
        lo = max(min(a0, a1), min(b0, b1))
        hi = min(max(a0, a1), max(b0, b1))
        return lo, hi

    seen_pairs = set()
    n_marked = 0
    print(f"{len(conflicts)} raw box conflict(s) found in {net_shapes_json}:")
    for na, ia, nb, ib, lyr in conflicts:
        _lyr_a, ax0, ay0, ax1, ay1 = net_shapes[na][ia]
        _lyr_b, bx0, by0, bx1, by1 = net_shapes[nb][ib]

        ox0, ox1 = overlap_1d(ax0, ax1, bx0, bx1)
        oy0, oy1 = overlap_1d(ay0, ay1, by0, by1)
        cx, cy = (ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0

        # (261,0): the literal overlap region, expanded by HALO_UM
        box = db.Box(um(ox0 - HALO_UM), um(oy0 - HALO_UM),
                     um(ox1 + HALO_UM), um(oy1 + HALO_UM))
        top.shapes(overlap_idx).insert(box)

        label = f"{na} x {nb}"
        t = db.Text(label, db.Trans(um(cx), um(cy + HALO_UM + 2.0)))
        top.shapes(text_idx).insert(t)

        # (261,2): bounding box around BOTH full conflicting shapes, for
        # visual context of the two nets' actual metal runs involved.
        full_x0, full_x1 = min(ax0, bx0), max(ax1, bx1)
        full_y0, full_y1 = min(ay0, by0), max(ay1, by1)
        bbox = db.Box(um(full_x0), um(full_y0), um(full_x1), um(full_y1))
        top.shapes(bbox_idx).insert(bbox)

        n_marked += 1
        pair_key = tuple(sorted((na, nb)))
        seen_pairs.add(pair_key)
        print(f"  [{lyr}] {na} <-> {nb}  overlap=({ox0:.2f},{oy0:.2f})-({ox1:.2f},{oy1:.2f}) "
              f"center=({cx:.2f},{cy:.2f})")

    layout.write(out_gds)
    print(f"\nwrote {out_gds}")
    print(f"marked {n_marked} conflict(s) across {len(seen_pairs)} net pair(s) on layer "
          f"({MARKER_LAYER_BASE},0)=overlap box, ({MARKER_LAYER_BASE},1)=label, "
          f"({MARKER_LAYER_BASE},2)=both full shapes' bounding box")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <in_gds> <net_shapes_json> <out_gds>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
