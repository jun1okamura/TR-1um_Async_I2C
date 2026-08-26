"""reassemble_top.py

Re-assembles src/tr_1um_i2c_slave_async.gds with the CURRENT
FRAME/TR-1um_frame_25x25.gds's OSS_FRAME_GIO cell.

Whenever the user edits the FRAME GDS (pad layout, VDD/VSS pad
relabeling, etc.), the OSS_FRAME_GIO instance embedded in the top-level
GDS goes stale. This script:
  1. reads the top-level GDS,
  2. deletes the old OSS_FRAME_GIO instance (keeping its placement
     transform),
  3. merges in the current FRAME GDS's cells (which brings in a fresh
     OSS_FRAME_GIO),
  4. re-inserts a new OSS_FRAME_GIO instance at the same transform.

Run this BEFORE route_gio_core.py any time the FRAME GDS changes -- the
router's IN_GDS points at this script's OUT_GDS.

Companion step: after any FRAME GDS edit, also regenerate
LEF/OSS_FRAME_GIO.lef (matches pins by literal "VDD"/"VSS"/signal-name
text on GDS layers 48/0 and 49/0, so it auto-adapts to pad relabeling --
see design_notes.md section 75.2). The original one-off script for this
(gen_gio_lef.py) was written to a scratch location during that session
and not preserved; gen_lef.py in this directory implements the same
text-label-matching approach for the standard-cell library and can be
adapted for OSS_FRAME_GIO if the LEF needs regenerating again.
"""
import klayout.db as db

TOP_GDS = "../src/tr_1um_i2c_slave_async.gds"
FRAME_GDS = "../FRAME/TR-1um_frame_25x25.gds"
OUT_GDS = "../src/tr_1um_i2c_slave_async_newgio.gds"

ly = db.Layout()
ly.read(TOP_GDS)
top_cell = ly.top_cell()
print("top cell:", top_cell.name)

for inst in top_cell.each_inst():
    print("  inst:", inst.cell.name, inst.trans)

old_gio = ly.cell("OSS_FRAME_GIO")
assert old_gio is not None

gio_trans = None
for inst in top_cell.each_inst():
    if inst.cell.name == "OSS_FRAME_GIO":
        gio_trans = inst.trans
        inst.delete()
        break
print("captured transform:", gio_trans)

ly.delete_cell(old_gio.cell_index())

# import new GIO cell(s) directly by merging FRAME_GDS into this layout
n_cells_before = ly.cells()
ly.read(FRAME_GDS)
n_cells_after = ly.cells()
print("cells before/after merge:", n_cells_before, n_cells_after)

new_gio = ly.cell("OSS_FRAME_GIO")
assert new_gio is not None
print("new gio cell:", new_gio.name, "bbox:", new_gio.bbox())

top_cell.insert(db.CellInstArray(new_gio.cell_index(), gio_trans))

print("after reassembly, instances:")
for inst in top_cell.each_inst():
    print("  inst:", inst.cell.name, inst.trans)

ly.write(OUT_GDS)
print("wrote", OUT_GDS)
