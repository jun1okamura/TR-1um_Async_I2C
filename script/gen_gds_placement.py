"""
gen_gds_placement.py

Generates Layout/i2c_slave_async_layout.gds: a placement-only (no M1/M2/poly
signal routing yet) GDSII for i2c_slave_async_net.v, using the real
TR-1um_STDCELL.gds cell library and the row plan from
plan_placement.compute_rows() (logical rows 0..4, row 0 = bottom of the
5-row standard-cell stack, ascending upward).

Physical row stack (bottom to top), each physical row 55.0um tall
(row_height, prBoundary-based) -- see design_notes.md section 26 for why
this replaced the old 4-row/mirrored-pair structure:

    N_BM  x FILL1 filler row  -- bottom M1 routing margin (below row 0)
    logical row 0
    N_01  x FILL1 filler row  -- channel between row 0 / row 1
    logical row 1
    N_12  x FILL1 filler row  -- channel between row 1 / row 2
    logical row 2
    N_23  x FILL1 filler row  -- channel between row 2 / row 3
    logical row 3
    N_34  x FILL1 filler row  -- channel between row 3 / row 4
    logical row 4
    N_TM  x FILL1 filler row  -- top M1 routing margin (above row 4)

Unlike the old design, NO row is Y-mirrored: every logical row is placed
R0 (unmirrored). The old scheme alternated mirror orientation by physical
row index so that adjacent zero-gap (no-channel) row pairs could share one
VDD/GND rail -- that saved a bit of area but created two "zero-gap" row
boundaries with no M1 channel at all, which turned out to be extremely
hard to route across (see design_notes.md sections 22.5-23.5): ~50% pin
failure rate, DRC violations, new shorts. The new structure gives EVERY
row boundary a real M1 channel (same proven design as the old row1/row2
"shared channel"), fully eliminating the zero-gap case, at the cost of
some extra die area (more filler rows) and giving up rail sharing.

Channel heights (N_BM, N_01, N_12, N_23, N_34, N_TM, all in filler-row
units) are NOT fixed a priori -- they are sized empirically to fit each
channel's actual measured track demand once routing is attempted (see
design_notes.md section 25's methodology, reused here), so the values in
PHYSICAL_ROWS below are expected to be edited iteratively.

Also draws (non-fab, reference-only):
  - block-boundary pin markers on layer 48/0 (same convention the stdcell
    library itself uses for pin labels): SCL/SDA(in/oe)/RST_N on the LEFT
    edge (x=0), everything else (tx_data/rx_data/rx_valid/addr_match/rw/
    busy/VDD/GND) on the RIGHT edge (x=ROW_WIDTH_UM), spaced evenly over
    the full core height.
  - per-instance name annotations on layer 250/0, for cross-referencing
    against the netlist / SPICE (schematic/i2c_slave_async_net.spice)
    during manual routing and LVS debug.
  - a core outline box on layer 251/0.

Layers 250/0 and 251/0 are NOT fabrication layers -- delete/ignore them
before tapeout.

Rerun after editing plan_placement.py or i2c_slave_async_net.v:
    python3 script/gen_gds_placement.py
"""
import sys
import os

import klayout.db as db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402

GDS_LIB = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/libraries/TR-1um_STDCELL.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout.gds"
PIN_LAYER = (48, 0)     # same convention as the stdcell library's own pin labels
ANNOT_LAYER = (250, 0)  # non-fab: instance-name annotation only
OUTLINE_LAYER = (251, 0)  # non-fab: core outline only

FILLER_CELL = "FILL1"
ROW_HEIGHT_FILLER_ROWS = 55.0  # nominal, overwritten from the real prBoundary below

# Channel sizes in FILL1-row units. Every row boundary is now a real M1
# channel (design_notes.md section 26) -- no more zero-gap pairs. Mirroring
# is back (section 27, applied to every physical row incl. filler/channel
# rows, for VDD/GND rail + N-well/P-well continuity) but that doesn't
# constrain channel sizing -- any row's channel(s) can still be resized
# independently without side effects on other rows. Sized empirically.
# Iteration 4 (section 28.2's same-instance channel grouping fix rebalanced
# net counts across channels -- ch0_1 went from 7/16 to 16/16, zero margin
# -- bumped up for safety headroom):
#   chbm_0 2/8, ch0_1 16/16(no margin)->16/24, ch1_2 10/24, ch2_3 29/32,
#   ch3_4 33/40, ch4_tm 2/16
N_BM = 1   # bottom margin (below row 0)
N_01 = 4   # channel between row 0 / row 1 (kept as an EVEN increment from
           # the prior working value of 2, to preserve every downstream
           # row's mirror parity -- an odd increment flipped row1-4's
           # mirror orientation and, by chance, landed on a worse M2
           # collision pattern; not a hard requirement, just what tested
           # well)
N_12 = 3   # channel between row 1 / row 2
N_23 = 4   # channel between row 2 / row 3
N_34 = 5   # channel between row 3 / row 4
N_TM = 2   # top margin (above row 4)

PHYSICAL_ROWS = (
    [None] * N_BM
    + [0]
    + [None] * N_01
    + [1]
    + [None] * N_12
    + [2]
    + [None] * N_23
    + [3]
    + [None] * N_34
    + [4]
    + [None] * N_TM
)

LEFT_PINS = ["scl", "sda_in", "sda_oe", "rst_n"]
RIGHT_PINS = (["VDD", "GND"] + [f"tx_data[{i}]" for i in range(7, -1, -1)]
              + [f"rx_data[{i}]" for i in range(7, -1, -1)]
              + ["rx_valid", "addr_match", "rw", "busy"])


def main():
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)

    layout = db.Layout()
    layout.read(GDS_LIB)
    dbu = layout.dbu
    top = layout.create_cell("i2c_slave_async_layout")

    pin_layer_idx = layout.layer(*PIN_LAYER)
    annot_layer_idx = layout.layer(*ANNOT_LAYER)
    outline_layer_idx = layout.layer(*OUTLINE_LAYER)
    pr_layer_idx = layout.layer(*PR_LAYER)

    def um(v):
        return int(round(v / dbu))

    cell_cache = {}
    pr_bbox_cache = {}

    def get_cell(name):
        if name not in cell_cache:
            c = layout.cell(name)
            if c is None:
                raise RuntimeError(f"cell {name} not found in library")
            cell_cache[name] = c
        return cell_cache[name]

    def get_pr_bbox(name):
        # The real abutment box (prBoundary, 235/0) -- NOT cell.bbox(), which
        # includes a padded guard-band overhang meant to overlap neighboring
        # cells once correctly abutted at the prBoundary edges.
        if name not in pr_bbox_cache:
            cell = get_cell(name)
            pr_bbox_cache[name] = db.Region(cell.begin_shapes_rec(pr_layer_idx)).bbox()
        return pr_bbox_cache[name]

    filler_w = get_pr_bbox(FILLER_CELL).width() * dbu
    n_filler = int(ROW_WIDTH_UM // filler_w)

    def distribute_row_fillers(idx, row, target_spacing_um=200.0):
        """Insert FILL1 corridors into a single row's cell sequence, spread
        out roughly every target_spacing_um of placed cell width, instead of
        leaving all unused width as one big block at the row's right end --
        gives every real cell a nearby M1/M2-clear corridor to route a
        vertical trunk through. No cross-row alignment needed any more
        (unlike the old zero-gap-pair scheme): every row now has its own
        independent channel(s) on both sides, so there's no requirement for
        this row's corridors to line up in X with any other row's."""
        used = sum(w for _n, _t, w in row)
        gap = max(0.0, ROW_WIDTH_UM - used)
        if not row or gap < filler_w:
            return list(row)
        n_corridors = max(1, round(used / target_spacing_um))
        n_corridors = max(1, min(n_corridors, int(gap // filler_w) or 1))
        fillers_per_corridor = int((gap / n_corridors) // filler_w)
        thresholds = [(k + 1) * ROW_WIDTH_UM / (n_corridors + 1) for k in range(n_corridors)]

        seq = []
        i = 0
        cum = 0.0
        for k, thr in enumerate(thresholds):
            while i < len(row) and cum < thr:
                seq.append(row[i]); cum += row[i][2]; i += 1
            for j in range(fillers_per_corridor):
                seq.append((f"corr{idx}_{k}_{j}", FILLER_CELL, filler_w)); cum += filler_w
        seq.extend(row[i:])

        final_used = sum(w for _n, _t, w in seq)
        extra_gap = max(0.0, ROW_WIDTH_UM - final_used)
        n_extra = int(extra_gap // filler_w)
        for j in range(n_extra):
            seq.append((f"extra_{idx}_{j}", FILLER_CELL, filler_w))

        final = sum(w for _n, _t, w in seq)
        assert final <= ROW_WIDTH_UM + 1e-6, f"row {idx} overflowed: {final:.1f}um > {ROW_WIDTH_UM}um"
        print(f"  row {idx}: {n_corridors} corridors x {fillers_per_corridor} FILL1 each, "
              f"final used+filler: {final:.1f}um")
        return seq

    logical_row_seq = {}
    for idx, row in enumerate(rows):
        logical_row_seq[idx] = distribute_row_fillers(idx, row)

    placed = 0
    n_phys = len(PHYSICAL_ROWS)
    for phys_idx, entry in enumerate(PHYSICAL_ROWS):
        row_bottom_abs = phys_idx * row_height
        # Alternating Y-mirror by PHYSICAL row index, applied to EVERY
        # physical row -- real stdcell rows AND filler-only channel rows
        # alike (design_notes.md section 27): every cell's VDD/GND pins sit
        # on the prBoundary top/bottom edge (y=55/y=0 local), so mirroring
        # every other physical row keeps the power rail polarity (and
        # N-well/P-well banding) continuous across every row boundary in
        # the stack, exactly as conventional standard-cell flows require.
        # The earlier 5-row rearchitecture (section 26) dropped mirroring
        # under the mistaken assumption it was ONLY needed for zero-gap
        # rail sharing; real DRC (well/tap rules our own simplified M1/M2/
        # V1-only checker never covered) showed this was wrong.
        mirrored = (phys_idx % 2 == 1)

        if entry is None:
            seq = [(f"fill_{phys_idx}_{i}", FILLER_CELL, filler_w) for i in range(n_filler)]
            kind = "filler"
        else:
            seq = logical_row_seq[entry]
            kind = f"logical row {entry}"

        cursor_x = 0.0
        for instname, typ, w in seq:
            cell = get_cell(typ)
            bbox = get_pr_bbox(typ)  # in dbu, on the prBoundary layer
            bleft = bbox.left * dbu
            bbottom = bbox.bottom * dbu
            btop = bbox.top * dbu
            width = bbox.width() * dbu

            tx = cursor_x - bleft
            if not mirrored:
                ty = row_bottom_abs - bbottom
                trans = db.Trans(db.Trans.R0, um(tx), um(ty))
            else:
                ty = row_bottom_abs + btop
                trans = db.Trans(db.Trans.M0, um(tx), um(ty))

            top.insert(db.CellInstArray(cell.cell_index(), trans))

            cx = tx + (bleft + width / 2.0)
            cy = row_bottom_abs + row_height / 2.0
            text = db.Text(instname, db.Trans(um(cx), um(cy)))
            text.size = um(3.0)
            top.shapes(annot_layer_idx).insert(text)

            cursor_x += width
            placed += 1
        print(f"physical row {phys_idx}/{n_phys - 1} ({kind}): placed {len(seq)} cells, "
              f"used width {cursor_x:.1f} um, mirrored={mirrored}")

    print("total placed:", placed)

    core_h = n_phys * row_height

    def place_edge_pins(names, x_um):
        n = len(names)
        step = core_h / (n + 1)
        for i, name in enumerate(names):
            y_um = step * (i + 1)
            box = db.Box(um(x_um - 2), um(y_um - 2), um(x_um + 2), um(y_um + 2))
            top.shapes(pin_layer_idx).insert(box)
            t = db.Text(name, db.Trans(um(x_um), um(y_um)))
            t.size = um(3.0)
            top.shapes(pin_layer_idx).insert(t)

    place_edge_pins(LEFT_PINS, 0.0)
    place_edge_pins(RIGHT_PINS, ROW_WIDTH_UM)

    top.shapes(outline_layer_idx).insert(db.Box(0, 0, um(ROW_WIDTH_UM), um(core_h)))

    os.makedirs(os.path.dirname(OUT_GDS), exist_ok=True)
    layout.write(OUT_GDS)
    print("wrote", OUT_GDS)
    print("core bbox (design):", 0, 0, ROW_WIDTH_UM, core_h)


if __name__ == "__main__":
    main()
