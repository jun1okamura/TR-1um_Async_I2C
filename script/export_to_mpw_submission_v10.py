#!/usr/bin/env python3
"""
export_to_mpw_submission_v10.py (V10 counterpart of export_to_mpw_
submission.py -- user request, this session: "V10の成果を
TR-1um_I2C_2026 にコピーして、READMEやPROVENANCEをアップデートして
ください。", after V10's chip-level integration reached DRC/LVS-clean
+ SPICE 14/14 PASS, design_notes.md §108.52〜108.67).

Copies this project's V10 final chip-level GDS
(layout/step10/v10_chip_final.gds) and LVS reference netlist
(schematic/tr_1um_i2c_slave_async_v10_ringosc_lvs.spice) into the same
OpenSUSI TR-1um_MPW_template-based submission repo
(TR-1um_I2C_2026) that export_to_mpw_submission.py already targets for
V9, superseding that V9 export with V10 (same top-level design, same
info.yaml top_cell name "tr_1um_i2c_slave_async" -- no destination-repo
naming change needed, only the underlying design files are newer).

**Difference from the V9 script's transform_gds(): one extra pruning
pass.** V9's SRC_GDS (`ring_osc/tr_1um_i2c_slave_async_reassigned_
logodots.gds`) had ALREADY been through `script/strip_orphan_cells.py`
(a separate, earlier one-time step) before export, so V9's transform_
gds() only had to handle the OSS_FRAME/OSS_FRAME_TEG orphan-marker
drop + OSS_FRAME_GIO->OSS_FRAME rename. V10's SRC_GDS (`layout/step10/
v10_chip_final.gds`, straight out of `finalize_chip_v10.py`, never
run through strip_orphan_cells.py) was checked directly via klayout.db
before writing this script and found to have 9 top-level cells, not
the 3 V9's source had at the equivalent stage: the real design
(`tr_1um_i2c_slave_async`), the 2 frame markers (`OSS_FRAME`/
`OSS_FRAME_TEG`), AND 6 dead unreferenced standard-cell leftovers
(`DFFS`, `TAP3`, `DFF`, `DEL1`, `NAND4`, `AND3_X1` -- one MORE than
V9's own 5-cell list, `DEL1` newly present, consistent with V10's
resynthesized core using DEL1 during an intermediate step but not in
the final placed netlist). Each of the 6 was independently confirmed
(0 parent cells AND 0 child instances -- same safety criterion as
strip_orphan_cells.py's own verify_safe_to_remove()) to be a true,
self-contained dead leftover before being added to ORPHAN_CELLS_TO_
STRIP below, so this script folds strip_orphan_cells.py's own pruning
pass directly into transform_gds() instead of requiring a separate
script run first.

Everything else (OSS_FRAME_GIO->OSS_FRAME rename, LVS netlist rename,
info.yaml update, preflight check against scripts/pre_check.py's own
rules) is identical logic to export_to_mpw_submission.py -- see that
script's own module docstring for the full rationale of each.

Run from this project's own directory:
    python3 script/export_to_mpw_submission_v10.py
"""
import pathlib
import re

import klayout.db as db

# ---- source (this project, V10) ----
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_GDS = PROJECT_ROOT / "layout" / "step10" / "v10_chip_final.gds"
SRC_LVS_NETLIST = PROJECT_ROOT / "schematic" / "tr_1um_i2c_slave_async_v10_ringosc_lvs.spice"

# ---- destination (OpenSUSI TR-1um_MPW_template-based submission repo,
# same one V9 was previously exported to) ----
DEST_REPO = pathlib.Path("~/Dropbox/98_LSI_Design/TR-1um_I2C_2026").expanduser()
TOP_CELL = "tr_1um_i2c_slave_async"

# dead, unreferenced standard-cell leftovers sitting at the top of
# v10_chip_final.gds's hierarchy (0 parents AND 0 children each,
# independently verified before this script was written -- see module
# docstring). One more than V9's own 5-cell list (DEL1 newly present).
ORPHAN_CELLS_TO_STRIP = ["DFFS", "TAP3", "DFF", "DEL1", "NAND4", "AND3_X1"]

# cell rename applied at export time only -- matches export_to_mpw_
# submission.py's own history item (3)
REAL_FRAME_CELL_OLD_NAME = "OSS_FRAME_GIO"
REAL_FRAME_CELL_NEW_NAME = "OSS_FRAME"
# now-redundant inert markers to drop once the real frame cell carries
# REAL_FRAME_CELL_NEW_NAME
REDUNDANT_ORPHAN_MARKERS = ["OSS_FRAME", "OSS_FRAME_TEG"]

# project metadata written into info.yaml (edit to reuse for a different
# submission -- these are free-text documentation fields only, not
# validated by pre_check.py)
PROJECT_TITLE = "Async I2C Slave + RING_OSC (V10)"
PROJECT_AUTHOR = "jun1okamura"
PROJECT_DISCORD = ""
PROJECT_DESCRIPTION = (
    "Clockless (SCL/SDA edge-driven) I2C slave core (V10: MUXDFFRB/RSLATCH "
    "synthesized-cell integration + full re-placement/re-routing), with an "
    "on-die ring-oscillator test structure. Chip-level DRC/LVS clean and "
    "SPICE transistor-level 14/14 PASS (WRITE/READ/NACK regression)"
)

# ---- pre_check.py's own constants (mirrored here for the preflight
# check only -- see scripts/pre_check.py in the destination repo) ----
FRAME_CELL_NAMES = {"OSS_FRAME", "OSS_FRAME_TEG"}
EXPECTED_DBU = 0.001
CHIP_SIZE_UM = 2500.0


def transform_gds():
    """Loads SRC_GDS, strips the dead orphan standard-cell leftovers,
    drops the now-redundant frame markers, and renames the real frame
    cell OSS_FRAME_GIO -> OSS_FRAME. Returns the in-memory transformed
    db.Layout (nothing is written to SRC_GDS itself -- this project's
    own master file is left untouched).
    """
    layout = db.Layout()
    layout.read(str(SRC_GDS))

    for name in ORPHAN_CELLS_TO_STRIP:
        ci = layout.cell_by_name(name)
        cell = layout.cell(ci)
        parents = list(cell.caller_cells())
        children = list(cell.each_inst())
        if parents:
            raise RuntimeError(
                f"{name} is NOT an orphan -- has {len(parents)} parent "
                f"cell(s), refusing to delete"
            )
        if children:
            raise RuntimeError(
                f"{name} has {len(children)} child instance(s) -- refusing "
                f"to blindly prune, check by hand first"
            )
        layout.prune_cell(ci, -1)

    for name in REDUNDANT_ORPHAN_MARKERS:
        ci = layout.cell_by_name(name)
        cell = layout.cell(ci)
        if list(cell.caller_cells()):
            raise RuntimeError(
                f"{name} unexpectedly has parent cells -- not a top-level "
                f"orphan, aborting (check the GDS by hand)"
            )
        layout.prune_cell(ci, -1)

    gio_ci = layout.cell_by_name(REAL_FRAME_CELL_OLD_NAME)
    layout.rename_cell(gio_ci, REAL_FRAME_CELL_NEW_NAME)

    tops = list(layout.top_cells())
    if len(tops) != 1 or tops[0].name != TOP_CELL:
        names = [c.name for c in tops]
        raise RuntimeError(
            f"expected exactly 1 top cell named {TOP_CELL!r} after transform, got {names}"
        )

    return layout


def transform_netlist_text():
    """Reads SRC_LVS_NETLIST and renames the OSS_FRAME_GIO subckt
    declaration + its one instance-call site to OSS_FRAME, matching
    transform_gds(). Returns the new text (SRC_LVS_NETLIST itself is
    left untouched).
    """
    text = SRC_LVS_NETLIST.read_text()

    new_text, n_decl = re.subn(
        rf"(?m)^(\.subckt ){re.escape(REAL_FRAME_CELL_OLD_NAME)}\b",
        rf"\1{REAL_FRAME_CELL_NEW_NAME}",
        text,
    )
    new_text, n_call = re.subn(
        rf"(?m){re.escape(REAL_FRAME_CELL_OLD_NAME)}$",
        REAL_FRAME_CELL_NEW_NAME,
        new_text,
    )
    if n_decl != 1 or n_call != 1:
        raise RuntimeError(
            f"expected 1 '.subckt {REAL_FRAME_CELL_OLD_NAME}' declaration + 1 "
            f"instance-call site, got {n_decl} + {n_call} -- netlist format may "
            f"have changed, check by hand"
        )

    header = (
        f"* NOTE: {REAL_FRAME_CELL_OLD_NAME} renamed to {REAL_FRAME_CELL_NEW_NAME} "
        f"in this exported copy only, by script/export_to_mpw_submission_v10.py.\n"
        f"* The master netlist in TR-1um_Async_I2C/schematic/ keeps the original\n"
        f"* {REAL_FRAME_CELL_OLD_NAME} name, used pervasively elsewhere in that project.\n"
    )
    return header + new_text


def preflight_pre_check(layout):
    """Reproduces destination repo's scripts/pre_check.py checks locally
    against an in-memory (already-transformed) layout, so problems are
    caught here instead of only after a real CI push. Prints warnings
    but does not block the copy.
    """
    problems = []

    if abs(layout.dbu - EXPECTED_DBU) > 1e-9:
        problems.append(f"dbu is {layout.dbu:.6g}, expected {EXPECTED_DBU:.6g}")

    top_cells = list(layout.top_cells())
    if len(top_cells) != 1:
        names = ", ".join(c.name for c in top_cells)
        problems.append(
            f"{len(top_cells)} top-level cells found (pre_check.py requires "
            f"exactly 1): {names}"
        )
        named = [c for c in top_cells if c.name == TOP_CELL]
        top_cell = named[0] if named else top_cells[0]
    else:
        top_cell = top_cells[0]

    if top_cell.name != TOP_CELL:
        problems.append(f"top cell name is '{top_cell.name}', expected '{TOP_CELL}'")

    bbox = top_cell.dbbox()
    expected_half = CHIP_SIZE_UM / 2.0
    if not (
        abs(bbox.p1.x + expected_half) < 1e-6
        and abs(bbox.p1.y + expected_half) < 1e-6
        and abs(bbox.p2.x - expected_half) < 1e-6
        and abs(bbox.p2.y - expected_half) < 1e-6
    ):
        problems.append(
            f"bbox is ({bbox.p1.x:.2f},{bbox.p1.y:.2f})-({bbox.p2.x:.2f},{bbox.p2.y:.2f}), "
            f"expected (-{expected_half:.2f},-{expected_half:.2f})-({expected_half:.2f},{expected_half:.2f})"
        )

    cell_names = {c.name for c in layout.each_cell()}
    if not (cell_names & FRAME_CELL_NAMES):
        problems.append(f"no {'/'.join(sorted(FRAME_CELL_NAMES))} cell found")

    if problems:
        print("WARNING: this GDS will FAIL the destination repo's scripts/pre_check.py:")
        for p in problems:
            print(f"  - {p}")
        print("  (copying anyway)")
    else:
        print("preflight OK: transformed GDS would pass scripts/pre_check.py")


def write_design_files(transformed_layout, transformed_netlist_text):
    dest_src = DEST_REPO / "src"
    dest_src.mkdir(parents=True, exist_ok=True)

    dest_gds = dest_src / f"{TOP_CELL}.gds"
    transformed_layout.write(str(dest_gds))
    print(f"wrote {dest_gds} (from {SRC_GDS.name}, {len(ORPHAN_CELLS_TO_STRIP)} dead cells "
          f"stripped, {REAL_FRAME_CELL_OLD_NAME}->{REAL_FRAME_CELL_NEW_NAME} renamed)")

    dest_cir = dest_src / f"{TOP_CELL}.cir"
    dest_cir.write_text(transformed_netlist_text)
    print(f"wrote {dest_cir} (from {SRC_LVS_NETLIST.name}, renamed + .spice -> .cir)")

    stale = [p.name for p in dest_src.glob("tr_1um_username.*")]
    if stale:
        print(f"NOTE: template placeholder file(s) still present (harmless, not deleted): {', '.join(stale)}")

    return dest_gds, dest_cir


def update_info_yaml():
    info_path = DEST_REPO / "info.yaml"
    text = info_path.read_text()

    replacements = [
        (r'(?m)^(  title: )"[^"]*"', f'\\1"{PROJECT_TITLE}"'),
        (r'(?m)^(  author: )"[^"]*"', f'\\1"{PROJECT_AUTHOR}"'),
        (r'(?m)^(  discord: )"[^"]*"', f'\\1"{PROJECT_DISCORD}"'),
        (r'(?m)^(  description: )"[^"]*"', f'\\1"{PROJECT_DESCRIPTION}"'),
        (r'(?m)^(  top_cell: )"[^"]*"', f'\\1"{TOP_CELL}"'),
    ]
    new_text = text
    for pattern, repl in replacements:
        new_text, n = re.subn(pattern, repl, new_text)
        if n != 1:
            raise RuntimeError(
                f"expected exactly 1 match for {pattern!r}, got {n} -- "
                "info.yaml's format may have changed, check/update manually"
            )

    info_path.write_text(new_text)
    print(f"updated {info_path} (title/author/discord/description/gds.top_cell)")


def main():
    if not SRC_GDS.exists():
        raise FileNotFoundError(SRC_GDS)
    if not SRC_LVS_NETLIST.exists():
        raise FileNotFoundError(SRC_LVS_NETLIST)
    if not DEST_REPO.exists():
        raise FileNotFoundError(f"destination repo not found: {DEST_REPO}")

    layout = transform_gds()
    netlist_text = transform_netlist_text()
    preflight_pre_check(layout)
    write_design_files(layout, netlist_text)
    update_info_yaml()

    print()
    print("Done. Review the diff in the destination repo, e.g.:")
    print(f"  cd {DEST_REPO} && git status && git diff info.yaml")


if __name__ == "__main__":
    main()
