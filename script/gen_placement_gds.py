"""
gen_placement_gds.py

Builds the physical placement GDS for the single-row trial (design_notes.md
section 35 architecture test): reads LEF/placement_row.json (X positions
from gen_placement_row.py) and CH_H (channel height, from
estimate_channel_tracks.py's recommendation), instantiates each cell's
real geometry from LEF/TR-1um_STDCELL.gds at (x, CH_H) -- i.e. the row
sits between a bottom channel [0, CH_H) and a top channel
[CH_H+64.8, CH_H+64.8+CH_H). No routing yet (that's route_row_channels.py,
task 4) -- this step only places cells.
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from lef_parser import parse_lef  # noqa: E402

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_row.json"
CELL_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/TR-1um_STDCELL.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_row_placement.gds"
TOP_CELL_NAME = "i2c_slave_async_row"

CH_H_UM = 184.0  # from estimate_channel_tracks.py (46 tracks x 4.0um, after
                  # netlist_parser.py's assign-alias resolution fix)


def main():
    macros = parse_lef()
    placement = json.load(open(PLACEMENT_JSON))

    layout = db.Layout()
    layout.read(CELL_GDS)
    dbu = layout.dbu

    top = layout.create_cell(TOP_CELL_NAME)

    missing_gds = set()
    for inst in placement["instances"]:
        typ = inst["type"]
        gds_name = macros[typ]["foreign"]
        src_cell = layout.cell(gds_name)
        if src_cell is None:
            missing_gds.add(gds_name)
            continue
        x_dbu = int(round(inst["x"] / dbu))
        y_dbu = int(round(CH_H_UM / dbu))
        top.insert(db.CellInstArray(src_cell.cell_index(), db.Trans(db.Vector(x_dbu, y_dbu))))

    if missing_gds:
        raise SystemExit(f"cells referenced by LEF FOREIGN but missing from {CELL_GDS}: {missing_gds}")

    row_w = placement["row_width"]
    row_h = placement["row_height"]
    core_h = 2 * CH_H_UM + row_h

    # record the core bbox + channel bands on a non-manufacturing layer
    # (250/0, same "annotation only" convention used since section 13) so
    # downstream scripts (the router, DRC/connectivity checks) can read the
    # channel geometry back out of the GDS itself rather than needing this
    # script's constants hardcoded a second time.
    ann = layout.layer(250, 0)

    def box(x0, y0, x1, y1):
        return db.Box(int(round(x0/dbu)), int(round(y0/dbu)), int(round(x1/dbu)), int(round(y1/dbu)))

    top.shapes(ann).insert(box(0, 0, row_w, core_h))  # core outline
    top.shapes(ann).insert(box(0, 0, row_w, CH_H_UM))  # bottom channel band
    top.shapes(ann).insert(box(0, CH_H_UM + row_h, row_w, core_h))  # top channel band

    layout.write(OUT_GDS)
    print(f"wrote {OUT_GDS}")
    print(f"core bbox: (0,0)-({row_w:.1f},{core_h:.1f})  "
          f"[bottom channel 0-{CH_H_UM:.1f}, row {CH_H_UM:.1f}-{CH_H_UM+row_h:.1f}, "
          f"top channel {CH_H_UM+row_h:.1f}-{core_h:.1f}]")
    print(f"instances placed: {len(placement['instances'])}")


if __name__ == "__main__":
    main()
