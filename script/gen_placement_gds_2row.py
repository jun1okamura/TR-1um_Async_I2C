"""
gen_placement_gds_2row.py

Builds the physical placement GDS for the two-row trial (design_notes.md
section 37): bottom margin channel [0, CH_B), row1 [CH_B, CH_B+64.8),
middle shared channel [.., ..+CH_M), row2 [.., ..+64.8), top margin
channel [.., ..+CH_T). Channel heights from
estimate_channel_tracks_2row.py. No routing yet (route_channels_2row.py).
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from lef_parser import parse_lef  # noqa: E402

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_2row.json"
CELL_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/TR-1um_STDCELL.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_2row_placement.gds"
TOP_CELL_NAME = "i2c_slave_async_2row"

# from estimate_channel_tracks_2row.py
CH_BOTTOM_UM = 68.0
CH_MIDDLE_UM = 360.0
CH_TOP_UM = 16.0


def main():
    macros = parse_lef()
    placement = json.load(open(PLACEMENT_JSON))
    row_h = placement["row_height"]
    row_w = placement["row_width"]

    y_row1 = CH_BOTTOM_UM
    y_row2 = CH_BOTTOM_UM + row_h + CH_MIDDLE_UM
    core_h = CH_BOTTOM_UM + row_h + CH_MIDDLE_UM + row_h + CH_TOP_UM

    layout = db.Layout()
    layout.read(CELL_GDS)
    dbu = layout.dbu
    top = layout.create_cell(TOP_CELL_NAME)

    missing = set()
    for row_key, y_off in (("row1", y_row1), ("row2", y_row2)):
        for inst in placement[row_key]:
            gds_name = macros[inst["type"]]["foreign"]
            src = layout.cell(gds_name)
            if src is None:
                missing.add(gds_name)
                continue
            x_dbu = int(round(inst["x"] / dbu))
            y_dbu = int(round(y_off / dbu))
            top.insert(db.CellInstArray(src.cell_index(), db.Trans(db.Vector(x_dbu, y_dbu))))
    if missing:
        raise SystemExit(f"cells missing from {CELL_GDS}: {missing}")

    ann = layout.layer(250, 0)

    def box(x0, y0, x1, y1):
        return db.Box(int(round(x0/dbu)), int(round(y0/dbu)), int(round(x1/dbu)), int(round(y1/dbu)))

    top.shapes(ann).insert(box(0, 0, row_w, core_h))
    top.shapes(ann).insert(box(0, 0, row_w, CH_BOTTOM_UM))
    top.shapes(ann).insert(box(0, CH_BOTTOM_UM + row_h, row_w, CH_BOTTOM_UM + row_h + CH_MIDDLE_UM))
    top.shapes(ann).insert(box(0, core_h - CH_TOP_UM, row_w, core_h))

    layout.write(OUT_GDS)
    print(f"wrote {OUT_GDS}")
    print(f"core bbox: (0,0)-({row_w:.1f},{core_h:.1f})")
    print(f"  bottom channel  0.0 - {CH_BOTTOM_UM:.1f}")
    print(f"  row1            {CH_BOTTOM_UM:.1f} - {CH_BOTTOM_UM+row_h:.1f}")
    print(f"  middle channel  {CH_BOTTOM_UM+row_h:.1f} - {CH_BOTTOM_UM+row_h+CH_MIDDLE_UM:.1f}")
    print(f"  row2            {y_row2:.1f} - {y_row2+row_h:.1f}")
    print(f"  top channel     {core_h-CH_TOP_UM:.1f} - {core_h:.1f}")
    print(f"instances: row1={len(placement['row1'])}, row2={len(placement['row2'])}")


if __name__ == "__main__":
    main()
