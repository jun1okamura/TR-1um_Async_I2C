#!/usr/bin/env python3
"""
strip_orphan_cells.py (this session, user: "コピー元の未使用セルを削除して
ください。LVSで確認します。その後コピーし直します。" -- after script/
export_to_mpw_submission.py's own preflight_pre_check() found the copy
source GDS has 8 top-level cells, not 1, which fails the OpenSUSI
TR-1um_MPW_template's scripts/pre_check.py (get_single_top_cell()
requires exactly 1).)

Removes ORPHAN top-level cells from a GDS: cells with zero parent
instances anywhere in the file (i.e. klayout's own layout.top_cells()
already treats them as "top" alongside the real design) that are ALSO
not the intended design top cell. Verified this session, before writing
this script, that all 5 target cells here are true dead leftovers:
  - AND3_X1, NAND4, DFF, TAP3, DFFS: each has 0 parent cells (real
    orphans) AND 0 child instances (self-contained leaf geometry, so
    deleting them cannot orphan-and-silently-drop any OTHER cell used
    elsewhere, e.g. via_1/cont_g/diode_n which the real design's DFFRB/
    TAP2/etc. legitimately depend on).
Confirmed via klayout.db before writing this script:
    for name in [...]: cell.caller_cells() == [] and
                        list(cell.each_inst()) == []

NOT touched here, deliberately: OSS_FRAME / OSS_FRAME_TEG. These are
ALSO orphan top-level cells (0 parents -- confirmed the real frame
instantiated under tr_1um_i2c_slave_async is a completely independent,
differently-named cell, OSS_FRAME_GIO, which does NOT reference OSS_FRAME
at all), but the destination repo's scripts/pre_check.py's
has_required_frame_cell() specifically requires a cell literally named
"OSS_FRAME" or "OSS_FRAME_TEG" to exist SOMEWHERE in the file (by name,
regardless of whether it's actually used) -- so deleting them would trade
one pre_check.py failure ("more than one top cell") for another ("no
required OpenSUSI frame/TEG cell found"), since our real frame cell is
named OSS_FRAME_GIO, not OSS_FRAME. This is a real, still-open naming
mismatch between this project's frame variant and the plain
"OSS_FRAME"/"OSS_FRAME_TEG" names pre_check.py's frame check expects --
worth the user's own separate decision (rename the real frame cell? keep
these 2 orphans on purpose as an inert marker?) rather than resolved
silently here. After this script runs, the GDS still has 3 top-level
cells (OSS_FRAME, OSS_FRAME_TEG, tr_1um_i2c_slave_async), down from 8 --
verified below, and printed clearly so it isn't mistaken for "fixed".

Run from this project's own directory:
    python3 script/strip_orphan_cells.py

To reuse for a different GDS or cell list, edit the constants below.
"""
import pathlib

import klayout.db as db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_GDS = PROJECT_ROOT / "ring_osc" / "tr_1um_i2c_slave_async_ringosc_logo.gds"
OUT_GDS = PROJECT_ROOT / "ring_osc" / "tr_1um_i2c_slave_async_ringosc_clean.gds"

# orphan cells to remove -- verified (see module docstring) to have zero
# parent instances AND zero child instances each, so removing them
# cannot affect any other cell's geometry or the real design's hierarchy.
ORPHAN_CELLS_TO_REMOVE = ["AND3_X1", "NAND4", "DFF", "TAP3", "DFFS"]

# left in place on purpose -- see module docstring
KNOWN_REMAINING_ORPHANS = ["OSS_FRAME", "OSS_FRAME_TEG"]

TOP_CELL = "tr_1um_i2c_slave_async"


def verify_safe_to_remove(layout, name):
    ci = layout.cell_by_name(name)
    cell = layout.cell(ci)
    parents = list(cell.caller_cells())
    children = list(cell.each_inst())
    if parents:
        raise RuntimeError(
            f"{name} is NOT an orphan -- has {len(parents)} parent cell(s), "
            f"refusing to delete (would affect the real design)"
        )
    if children:
        raise RuntimeError(
            f"{name} has {len(children)} child instance(s) -- refusing to "
            f"blindly prune, check by hand whether those children are shared "
            f"with the real design first"
        )


def main():
    layout = db.Layout()
    layout.read(str(SRC_GDS))

    before_tops = sorted(c.name for c in layout.top_cells())
    print(f"before: {len(before_tops)} top-level cells: {before_tops}")

    for name in ORPHAN_CELLS_TO_REMOVE:
        verify_safe_to_remove(layout, name)

    for name in ORPHAN_CELLS_TO_REMOVE:
        ci = layout.cell_by_name(name)
        layout.prune_cell(ci, -1)
        print(f"removed orphan cell: {name}")

    after_tops = sorted(c.name for c in layout.top_cells())
    print(f"after: {len(after_tops)} top-level cells: {after_tops}")

    # sanity: the real design's own top cell must be untouched (same
    # bbox, same shape/instance counts) -- comparing against the
    # original file's own copy of the same cell, read fresh.
    orig = db.Layout()
    orig.read(str(SRC_GDS))
    orig_top = orig.cell(orig.cell_by_name(TOP_CELL))
    new_top = layout.cell(layout.cell_by_name(TOP_CELL))
    if orig_top.dbbox() != new_top.dbbox():
        raise RuntimeError(
            f"BUG: {TOP_CELL}'s own bbox changed "
            f"({orig_top.dbbox()} -> {new_top.dbbox()}) -- aborting write"
        )
    if orig_top.child_cells() != new_top.child_cells():
        raise RuntimeError(
            f"BUG: {TOP_CELL}'s own child cell count changed "
            f"({orig_top.child_cells()} -> {new_top.child_cells()}) -- aborting write"
        )
    print(f"verified: {TOP_CELL}'s own bbox and child-cell count unchanged")

    remaining_orphans = [n for n in KNOWN_REMAINING_ORPHANS if n in after_tops]
    still_off = [n for n in after_tops if n not in (KNOWN_REMAINING_ORPHANS + [TOP_CELL])]
    if still_off:
        print(f"WARNING: unexpected extra top-level cell(s) remain: {still_off}")
    if remaining_orphans:
        print(
            f"NOTE: {remaining_orphans} deliberately left in place (see module "
            f"docstring) -- pre_check.py's 'exactly 1 top cell' will still fail "
            f"until that naming mismatch (OSS_FRAME_GIO vs OSS_FRAME) is "
            f"resolved separately."
        )

    layout.write(str(OUT_GDS))
    print(f"\nwrote {OUT_GDS}")


if __name__ == "__main__":
    main()
