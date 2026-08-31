#!/usr/bin/env python3
"""
export_to_mpw_submission.py -- copies this project's final chip-level GDS
and LVS reference netlist into an OpenSUSI TR-1um_MPW_template-based
submission repo (this session: TR-1um_I2C_2026, renamed from its
original TR-1um_TEST3 -- both the local folder and its GitHub remote),
and updates that repo's own info.yaml to match.

Background (this session, user: "TR-1um_TEST3 へチップレベルの最終GDS と
LVS 用の spice file をコピーします...同じ作業をする可能性があるので
script にして再利用できるようにしてください。"):

The destination repo follows OpenSUSI's TR-1um_MPW_template convention
(its own README.md / docs/info.md / scripts/pre_check.py):
  - exactly one design file pair goes under src/: "<top_cell>.gds"
    (layout) and "<top_cell>.<lvs.extension>" (LVS reference netlist,
    lvs.extension defaults to "cir" in a fresh template -- NOT ".spice",
    so the source .spice file here is renamed on copy, not just copied).
  - info.yaml's gds.top_cell must match the GDS's own top-level cell
    name EXACTLY (scripts/pre_check.py's validate_top_name()). This
    project's chip top cell is literally named "tr_1um_i2c_slave_async"
    throughout (GDS / schematic / SPICE all agree already), so that name
    is used verbatim as TOP_CELL below.
  - scripts/pre_check.py's get_single_top_cell() also requires EXACTLY 1
    top-level (unreferenced) cell in the whole GDS.

HISTORY, this project's own GDS/netlist naming vs. the above (this
session):
  1) script/strip_orphan_cells.py first found the copy source GDS had 8
     top-level cells, not 1: besides OSS_FRAME / OSS_FRAME_TEG /
     tr_1um_i2c_slave_async, five dead unused standard-cell library
     leftovers (AND3_X1, NAND4, DFF, TAP3, DFFS, each with 0 parents AND
     0 children -- pure leftovers, safe to delete) were also sitting at
     the top of the hierarchy. That script removed those 5 (verified via
     a full-layer XOR diff against the original: 0 differences across
     all 36 non-empty layers -- the real design's own geometry is
     untouched), producing tr_1um_i2c_slave_async_ringosc_clean.gds with
     3 top cells left: OSS_FRAME, OSS_FRAME_TEG, tr_1um_i2c_slave_async.
  2) OSS_FRAME / OSS_FRAME_TEG were deliberately kept at that point
     because this project's real, actually-instantiated frame cell is
     named OSS_FRAME_GIO (a GIO-pad-ring variant) -- a DIFFERENT name
     from what pre_check.py's has_required_frame_cell() checks for
     (exactly "OSS_FRAME" or "OSS_FRAME_TEG", by name, anywhere in the
     file) -- so the 2 orphans were left in as inert name-only markers to
     satisfy that check, at the cost of "exactly 1 top cell" still
     failing.
  3) User's decision (this turn): rename OSS_FRAME_GIO itself to
     OSS_FRAME, resolving the conflict properly instead of using inert
     markers -- confirmed via their own real LVS run that this is safe.
     transform_gds() below applies this: drop the now-fully-redundant
     OSS_FRAME/OSS_FRAME_TEG orphans (no longer needed once the REAL
     frame cell carries that name), then rename cell "OSS_FRAME_GIO" ->
     "OSS_FRAME". Result: exactly 1 top-level cell.
     transform_netlist_text() applies the equivalent rename to the LVS
     reference netlist's ".subckt OSS_FRAME_GIO" declaration and its one
     instance-call site, so the exported .cir stays consistent with the
     exported .gds.

SCOPE, deliberately: the rename is applied ONLY to this EXPORTED COPY
(in memory, at export time), NOT to the master files in ring_osc/ or
schematic/ back in this project. "OSS_FRAME_GIO" is used pervasively by
that exact name throughout this project's own scripts, JSON, and
design_notes.md -- a project-wide rename would be a much bigger, riskier
change than what's actually needed here (satisfying the destination
repo's naming convention). If a project-wide rename is ever wanted,
that's a separate, deliberate task.

Run from this project's own directory:
    python3 script/export_to_mpw_submission.py

To reuse for a different destination repo (e.g. TR-1um_TEST4) or a later/
different source GDS+netlist pair, edit the constants below.
"""
import pathlib
import re

import klayout.db as db

# ---- source (this project) ----
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# script/strip_orphan_cells.py's output -- see module docstring history
# item (1). Geometry-identical to tr_1um_i2c_slave_async_ringosc_logo.gds
# (verified via full-layer XOR diff), just with 5 dead orphan cells gone.
SRC_GDS = PROJECT_ROOT / "ring_osc" / "tr_1um_i2c_slave_async_ringosc_clean.gds"
SRC_LVS_NETLIST = PROJECT_ROOT / "schematic" / "tr_1um_i2c_slave_async_ringosc_v9_lvs.spice"

# ---- destination (OpenSUSI TR-1um_MPW_template-based submission repo) ----
DEST_REPO = pathlib.Path("~/Dropbox/98_LSI_Design/TR-1um_I2C_2026").expanduser()
TOP_CELL = "tr_1um_i2c_slave_async"

# cell rename applied at export time only -- see module docstring
# history item (3)
REAL_FRAME_CELL_OLD_NAME = "OSS_FRAME_GIO"
REAL_FRAME_CELL_NEW_NAME = "OSS_FRAME"
# now-redundant inert markers to drop once the real frame cell carries
# REAL_FRAME_CELL_NEW_NAME -- see module docstring history item (2)
REDUNDANT_ORPHAN_MARKERS = ["OSS_FRAME", "OSS_FRAME_TEG"]

# project metadata written into info.yaml (edit to reuse for a different
# submission -- these are free-text documentation fields only, not
# validated by pre_check.py)
PROJECT_TITLE = "Async I2C Slave + RING_OSC"
PROJECT_AUTHOR = "jun1okamura"
PROJECT_DISCORD = ""
PROJECT_DESCRIPTION = (
    "Clockless (SCL/SDA edge-driven) I2C slave core, with an on-die "
    "ring-oscillator test structure"
)

# ---- pre_check.py's own constants (mirrored here for the preflight
# check only -- see scripts/pre_check.py in the destination repo) ----
FRAME_CELL_NAMES = {"OSS_FRAME", "OSS_FRAME_TEG"}
EXPECTED_DBU = 0.001
CHIP_SIZE_UM = 2500.0


def transform_gds():
    """Loads SRC_GDS, drops the now-redundant orphan frame markers, and
    renames the real frame cell OSS_FRAME_GIO -> OSS_FRAME. Returns the
    in-memory transformed db.Layout (nothing is written to SRC_GDS
    itself -- this project's own master file is left untouched).
    """
    layout = db.Layout()
    layout.read(str(SRC_GDS))

    for name in REDUNDANT_ORPHAN_MARKERS:
        ci = layout.cell_by_name(name)
        cell = layout.cell(ci)
        # only require 0 PARENTS (i.e. genuinely unreferenced at the top
        # of the hierarchy) -- OSS_FRAME/OSS_FRAME_TEG are actually full,
        # self-contained alternate frame layouts with their own children
        # (OSS_FRAME_CNR, OSS_ESD_5V_*, OSS_EDGE_SEAL, etc., some shared
        # with the real OSS_FRAME_GIO hierarchy), so requiring 0 children
        # too would be wrong. prune_cell() itself only deletes a child
        # cell if it becomes fully unreferenced as a result -- shared
        # library cells still used elsewhere (e.g. by OSS_FRAME_GIO) are
        # correctly left alone.
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
        f"in this exported copy only, by script/export_to_mpw_submission.py.\n"
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
    print(f"wrote {dest_gds} (from {SRC_GDS.name}, {REAL_FRAME_CELL_OLD_NAME}->{REAL_FRAME_CELL_NEW_NAME} renamed)")

    dest_cir = dest_src / f"{TOP_CELL}.cir"
    dest_cir.write_text(transformed_netlist_text)
    print(f"wrote {dest_cir} (from {SRC_LVS_NETLIST.name}, renamed + .spice -> .cir)")

    # NOTE: the template's own placeholder files (tr_1um_username.*) are
    # deliberately left in place -- they don't match info.yaml's
    # top_cell anymore so pre_check.py (which reads the specific
    # <top_cell>.gds/.cir path from info.yaml, not a glob) ignores them,
    # but they're harmless clutter. Delete them by hand in the
    # destination repo if you want a clean src/.
    stale = [p.name for p in dest_src.glob("tr_1um_username.*")]
    if stale:
        print(f"NOTE: template placeholder file(s) still present (harmless, not deleted): {', '.join(stale)}")

    return dest_gds, dest_cir


def update_info_yaml():
    info_path = DEST_REPO / "info.yaml"
    text = info_path.read_text()

    # each pattern only replaces the FIRST quoted string after the key on
    # its own line -- deliberately NOT ".*" (greedy) since several of
    # these lines have a trailing "# ... (e.g. "foo", "bar")" comment
    # with its own quotes that must be left untouched.
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
