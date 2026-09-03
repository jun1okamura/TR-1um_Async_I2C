"""
assemble_top_v10.py (design_notes.md section 108.54, user request:
"チップ（GIO)への組み込みをします。V9と同じ座標にコアをはめて、
配線ができるか？確認ください。")

V10 equivalent of assemble_top_v9.py: places the V10 core
(layout/step10/v10_step_9_power_pins_added.gds, DRC/LVS clean this
session, 108.23-108.53) into the chip frame at EXACTLY the same
CORE_OFFSET/GIO_OFFSET/PTECT box v9 used -- per explicit user
instruction ("V9と同じ座標"), no recentering even though V10's core
BBOX height (938.9um) differs slightly from V9's (936.1um, +2.8um).
This is intentionally the simplest possible placement: same offsets,
different CORE_GDS. If V10's slightly taller core turns out to clip
into the PTECT gap or the GIO's own routing boundary, that will show
up directly in the DRC/routing step, not silently here.

STOPS here (no routing), matching assemble_top_v9.py's own convention
-- script/route_gio_core_v10.py is the next step.
"""
import klayout.db as db

FRAME_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/FRAME/TR-1um_frame_25x25.gds"
CORE_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/layout/step10/v10_step_9_power_pins_added.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/tr_1um_i2c_slave_async_v10.gds"

TOP_CELL_NAME = "tr_1um_i2c_slave_async"
CORE_CELL_NAME = "i2c_slave_async_nrow_fm"
GIO_CELL_NAME = "OSS_FRAME_GIO"
PTECT_LAYER = (63, 1)

GIO_OFFSET = (0.0, 0.0)
CORE_OFFSET = (-810.0, -140.0)  # IDENTICAL to assemble_top_v9.py, per user instruction

PTECT_GAP_BELOW_CORE = 10.0
PTECT_HEIGHT = 650.0
PTECT_X0, PTECT_X1 = -800.0, 800.0


def main():
    layout = db.Layout()
    dbu = 0.001
    layout.dbu = dbu

    def um(v):
        return int(round(v / dbu))

    top = layout.create_cell(TOP_CELL_NAME)

    # ---- core ----
    core_src = db.Layout()
    core_src.read(CORE_GDS)
    core_cell_src = core_src.cell(CORE_CELL_NAME)
    assert core_cell_src is not None, f"{CORE_CELL_NAME} not found in {CORE_GDS}"
    core_bbox = core_cell_src.bbox()
    core_native_w = (core_bbox.right - core_bbox.left) * core_src.dbu
    core_native_h = (core_bbox.top - core_bbox.bottom) * core_src.dbu
    print(f"core native bbox (um): {core_bbox.left*core_src.dbu:.1f},{core_bbox.bottom*core_src.dbu:.1f} "
          f"to {core_bbox.right*core_src.dbu:.1f},{core_bbox.top*core_src.dbu:.1f}  "
          f"({core_native_w:.1f} x {core_native_h:.1f})")

    n_before = layout.cells()
    core_map = layout.read(CORE_GDS)
    n_after = layout.cells()
    print(f"merged core GDS: {n_before} -> {n_after} cells")
    core_cell = layout.cell(CORE_CELL_NAME)
    assert core_cell is not None

    core_trans = db.Trans(db.Vector(um(CORE_OFFSET[0]), um(CORE_OFFSET[1])))
    top.insert(db.CellInstArray(core_cell.cell_index(), core_trans))
    core_bottom_chip = CORE_OFFSET[1] + core_bbox.bottom * core_src.dbu
    core_top_chip = CORE_OFFSET[1] + core_bbox.top * core_src.dbu
    core_left_chip = CORE_OFFSET[0] + core_bbox.left * core_src.dbu
    core_right_chip = CORE_OFFSET[0] + core_bbox.right * core_src.dbu
    print(f"core placed at offset {CORE_OFFSET} -> chip-frame bbox "
          f"({core_left_chip:.1f},{core_bottom_chip:.1f}) to ({core_right_chip:.1f},{core_top_chip:.1f})")

    # ---- GIO frame ----
    gio_src = db.Layout()
    gio_src.read(FRAME_GDS)
    gio_cell_src = gio_src.cell(GIO_CELL_NAME)
    assert gio_cell_src is not None, f"{GIO_CELL_NAME} not found in {FRAME_GDS}"
    gio_bbox = gio_cell_src.bbox()
    print(f"GIO native bbox (um): {gio_bbox.left*gio_src.dbu:.1f},{gio_bbox.bottom*gio_src.dbu:.1f} "
          f"to {gio_bbox.right*gio_src.dbu:.1f},{gio_bbox.top*gio_src.dbu:.1f}")

    layout.read(FRAME_GDS)
    gio_cell = layout.cell(GIO_CELL_NAME)
    assert gio_cell is not None

    gio_trans = db.Trans(db.Vector(um(GIO_OFFSET[0]), um(GIO_OFFSET[1])))
    top.insert(db.CellInstArray(gio_cell.cell_index(), gio_trans))
    print(f"GIO placed at offset {GIO_OFFSET}")

    # ---- PTECT area ----
    ptect_top = core_bottom_chip - PTECT_GAP_BELOW_CORE
    ptect_bottom = ptect_top - PTECT_HEIGHT
    ptect_idx = layout.layer(*PTECT_LAYER)
    box = db.Box(um(PTECT_X0), um(ptect_bottom), um(PTECT_X1), um(ptect_top))
    top.shapes(ptect_idx).insert(box)
    print(f"PTECT box (um): ({PTECT_X0},{ptect_bottom:.1f}) to ({PTECT_X1},{ptect_top:.1f})  "
          f"[{PTECT_X1-PTECT_X0:.1f} x {ptect_top-ptect_bottom:.1f}, gap below core = {PTECT_GAP_BELOW_CORE}um]")

    # ---- sanity: does the core clip the GIO's own usable envelope? ----
    print(f"\ncore top edge = {core_top_chip:.1f}  (v9's was 796.1 = -140.0+936.1)")
    print(f"core bottom edge = {core_bottom_chip:.1f}  (v9's was -140.0)")
    print(f"core left/right edges = {core_left_chip:.1f} / {core_right_chip:.1f}  (v9's were -816.3/816.3)")

    layout.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")
    print("STOPPED before routing -- next step is script/route_gio_core_v10.py.")


if __name__ == "__main__":
    main()
