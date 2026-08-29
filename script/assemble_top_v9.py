"""
assemble_top_v9.py (this session, user request: "src/tr_1um_i2c_slave_
async.gds にコアとGIOを配置します。OSS_FRAME_GIO は FRAME/TR-1um_
frame_25x25.gds からインポートして（0,0）に配置してコアはV7に比べて
Yが小さくなった分50um 移動して(-180,-140)で配置してください。また
コア部の下にV7と同じようにPTECTエリアを設定ください。配線する前に
確認しますのでそこで止めてください。")

Builds the v9 top-level (chip) placement -- GIO frame + core + PTECT
area -- as a fresh src/tr_1um_i2c_slave_async.gds. STOPS here (no
routing) per explicit user instruction; script/route_gio_core.py (the
existing v7 precedent) is the next step, once the user has reviewed
this placement and the GIO connection open_questions in
schematic/gio_connections.json (design_notes.md 78.1).

Placement values, derived from/verified against the EXISTING v7
src/tr_1um_i2c_slave_async.gds (read directly via klayout.db, not
assumed):
  - OSS_FRAME_GIO: (0,0), rot=0, no mirror. Native bbox
    (-1250,-1250)-(1250,1250) -- confirmed identical between v7's
    already-embedded copy and the current FRAME/TR-1um_frame_25x25.gds
    source (2500x2500um GIO frame square).
  - core (i2c_slave_async_nrow_fm): v7 used offset (-810.0,-190.0).
    v7's core native bbox was (-6.3,0.0)-(1626.3,988.2) (width
    1632.6um, height 988.2um) -- the X offset -810.0 exactly centers
    this width in the GIO frame (native X-center 810.0 -> 0.0).
    v9's core native bbox is (-6.3,0.0)-(1626.3,936.1) -- SAME width
    (row_width unchanged), height reduced by 52.1um (936.1 vs 988.2,
    per this session's earlier v7/v9 BBOX comparison). Per explicit
    user confirmation (AskUserQuestion this session, after flagging
    that the literally-stated "-180" X value would badly decenter the
    core relative to the 2500x2500 GIO frame): X offset stays -810.0
    (same centering as v7, unchanged since core width is unchanged),
    Y offset becomes -140.0 (+50um up from v7's -190.0, matching the
    user's stated "V9 is ~50um shorter, so move up by that amount").
  - PTECT (layer 63,1) area below the core: v7's box was exactly
    (-800,-800)-(800,-200) -- 1600um wide (X-centered on 0, slightly
    narrower than the core's own 1632.6um width), 600um tall, with its
    TOP edge sitting exactly 10.0um below the core's bottom edge
    (v7 core bottom = -190.0, PTECT top = -200.0). "V7と同じように"
    (same as V7) is read here as "the same SIZE/gap RULE relative to
    the core", not literally-identical numbers, since v9's core
    bottom edge itself moved (from -190.0 to -140.0) -- so this script
    recomputes the PTECT box against v9's new core bottom edge,
    keeping the same 10.0um gap:
      PTECT top    = core_bottom_chip - 10.0 = -140.0 - 10.0 = -150.0
      PTECT bottom = PTECT top - PTECT_HEIGHT
      PTECT X range unchanged: [-800, 800]

    v2 fix (user request, this session): after reviewing the initial
    600um-tall PTECT box, the user manually edited the GDS directly
    (extending PTECT's BOTTOM edge from -750.0 to -800.0, i.e. height
    600 -> 650um, top edge/gap-below-core unchanged) so that the
    top-level GIO<->core ROUTING CHANNEL below the core -- the gap
    between PTECT's bottom edge and the GIO frame's usable pin-routing
    boundary -- becomes ~120um. Confirmed by direct GDS read-back
    (src/tr_1um_i2c_slave_async.gds) and by cross-referencing
    route_gio_core.py's (v7's existing routing-step precedent) own
    established GIO pin-projection radius, 921.7um from chip center
    (literal constant used throughout that script's NETS dict, e.g.
    "...,921.7,'TOP','M2'..."): 921.7 - 800.0 = 121.7um, matching the
    user's "120um程度" (approximately 120um) target. PTECT_HEIGHT
    below is updated to 650.0 to match this reviewed value -- the
    script (not just the hand-edited GDS) is now the source of truth
    again.
"""
import klayout.db as db

FRAME_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/FRAME/TR-1um_frame_25x25.gds"
CORE_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/layout/step8/v9_step_9_power_pins_added.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/tr_1um_i2c_slave_async.gds"

TOP_CELL_NAME = "tr_1um_i2c_slave_async"
CORE_CELL_NAME = "i2c_slave_async_nrow_fm"
GIO_CELL_NAME = "OSS_FRAME_GIO"
PTECT_LAYER = (63, 1)

GIO_OFFSET = (0.0, 0.0)
CORE_OFFSET = (-810.0, -140.0)  # X unchanged from v7 (re-confirmed with user), Y: -190.0 -> -140.0

PTECT_GAP_BELOW_CORE = 10.0   # matches v7 exactly (core bottom -190.0, PTECT top -200.0)
PTECT_HEIGHT = 650.0          # v2: was 600.0 (v7's value) -- user extended the bottom
                               # edge by 50um (-750.0 -> -800.0) so the GIO<->core
                               # routing channel below the core (gap to the GIO's
                               # established 921.7um pin-routing boundary, per
                               # route_gio_core.py) becomes ~120um (921.7-800=121.7)
PTECT_X0, PTECT_X1 = -800.0, 800.0  # matches v7 exactly, unchanged


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

    layout.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")
    print("STOPPED before routing, per user instruction -- next step is "
          "script/route_gio_core.py (existing v7 precedent), only after review.")


if __name__ == "__main__":
    main()
