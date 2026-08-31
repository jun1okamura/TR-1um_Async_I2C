"""
place_ring_osc.py (this session, user request: "RING_OSC を
tr_1um_i2c_slave_async_routed.gds チップに統合します...RING_OSCの原点
X:-810 Y:-600 で仮置きしてください。先ずは配置を確認させてください。")

STEP 1 of the RING_OSC integration: places ring_osc/RING_OSC.gds as a
single cell instance into the current v9 final chip GDS
(src/tr_1um_i2c_slave_async.gds -- NOT the old v7-era "_routed.gds",
confirmed with the user), at the requested absolute origin (-810,-600),
r0/no mirror. Deliberately does NOT route OUT/OUTD/ENB/VDD/VSS to
P9/P10/P15/power yet -- this is a placement-only staging step for
visual/geometric review, mirroring assemble_top_v9.py's "stop before
routing" convention (design_notes.md 78.2).

KNOWN ISSUE, confirmed with user and left in place per their explicit
choice: at this origin, RING_OSC's absolute footprint
(X:[-816.3,816.3], Y:[-770.0,-525.2] -- see the bbox check below) is
ENTIRELY INSIDE the PTECT keepout area (layer 63/1, measured
X:[-800,800] Y:[-800,-150]) that all of this project's GIO<->core
routing has otherwise carefully avoided (design_notes.md 78.x/79.x).
User was shown the exact numbers via AskUserQuestion and chose "proceed
at Y=-600 as instructed" anyway; a later message revised the Y origin
to -650 ("Y=-650のことです。"), which carries the same PTECT overlap
(now Y:[-770.0,-525.2] instead of Y:[-720.0,-475.2]). Left as an open
item for their own DRC/placement-rule review -- this script does not
attempt to resolve it.

Output: ring_osc/tr_1um_i2c_slave_async_ringosc_placed.gds (new file --
src/tr_1um_i2c_slave_async.gds itself is left untouched until the
integration is reviewed and approved).
"""
import klayout.db as db

CHIP_GDS = "../src/tr_1um_i2c_slave_async.gds"
RING_OSC_GDS = "../ring_osc/RING_OSC.gds"
OUT_GDS = "../ring_osc/tr_1um_i2c_slave_async_ringosc_placed.gds"

CHIP_TOP = "tr_1um_i2c_slave_async"
RING_OSC_TOP = "RING_OSC"

ORIGIN_X_UM = -810.0
ORIGIN_Y_UM = -650.0  # revised from -600.0 (user, 2026-08-31: "Y=-650のことです。")

# PTECT keepout, measured directly from src/tr_1um_i2c_slave_async.gds
# layer (63,1) this session -- see docstring.
PTECT_BOX_UM = (-800.0, -800.0, 800.0, -150.0)


def bbox_um(cell, dbu):
    bb = cell.bbox()
    return (bb.left * dbu, bb.bottom * dbu, bb.right * dbu, bb.top * dbu)


def boxes_overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def main():
    ly = db.Layout()
    ly.read(CHIP_GDS)
    # Merge RING_OSC's cells (RING_OSC + its own library cell
    # definitions: INV_X1, INV3D, AND2_X1, FILL2) into the SAME Layout
    # object so an instance of it can be placed in the chip top cell.
    # klayout.db.Layout.read() called a second time on an existing
    # Layout imports/merges new cells; cells whose names already exist
    # (e.g. FILL2, INV_X1 -- already present in the chip GDS from the
    # core) are merged/deduplicated by KLayout's importer rather than
    # duplicated, since their layouts are identical (same source
    # library cell).
    ly.read(RING_OSC_GDS)

    dbu = ly.dbu
    chip_top = ly.cell(CHIP_TOP)
    ring_cell = ly.cell(RING_OSC_TOP)
    assert chip_top is not None, f"top cell {CHIP_TOP!r} not found after merge"
    assert ring_cell is not None, f"top cell {RING_OSC_TOP!r} not found after merge"

    trans = db.DCplxTrans(1.0, 0.0, False, ORIGIN_X_UM, ORIGIN_Y_UM)
    chip_top.insert(db.DCellInstArray(ring_cell.cell_index(), trans))

    # Report the placed footprint and check it against PTECT + the core
    # bbox, purely as an informational summary (not a hard stop -- see
    # docstring, user already made the call on the PTECT overlap).
    ring_local_bbox_um = bbox_um(ring_cell, dbu)  # cell's own native bbox, in um
    llx = ORIGIN_X_UM + ring_local_bbox_um[0]
    lly = ORIGIN_Y_UM + ring_local_bbox_um[1]
    urx = ORIGIN_X_UM + ring_local_bbox_um[2]
    ury = ORIGIN_Y_UM + ring_local_bbox_um[3]
    placed_box = (llx, lly, urx, ury)
    print(f"RING_OSC placed footprint (absolute, um): "
          f"({llx:.2f},{lly:.2f}) - ({urx:.2f},{ury:.2f})")

    core_cell = ly.cell("i2c_slave_async_nrow_fm")
    if core_cell is not None:
        # core is placed at (-810,-140) per design_notes 78.2 / this
        # session's own inspection of the chip GDS's top-level instances.
        core_local = bbox_um(core_cell, dbu)
        core_box = (-810.0 + core_local[0], -140.0 + core_local[1],
                    -810.0 + core_local[2], -140.0 + core_local[3])
        print(f"core footprint (absolute, um): "
              f"({core_box[0]:.2f},{core_box[1]:.2f}) - ({core_box[2]:.2f},{core_box[3]:.2f})")
        print("  overlaps core:", boxes_overlap(placed_box, core_box))

    print(f"PTECT keepout (absolute, um): "
          f"({PTECT_BOX_UM[0]:.2f},{PTECT_BOX_UM[1]:.2f}) - "
          f"({PTECT_BOX_UM[2]:.2f},{PTECT_BOX_UM[3]:.2f})")
    print("  overlaps PTECT:", boxes_overlap(placed_box, PTECT_BOX_UM),
          "  <-- KNOWN, user-confirmed (see docstring); not treated as an error here")

    ly.write(OUT_GDS)
    print(f"wrote {OUT_GDS}")


if __name__ == "__main__":
    main()
