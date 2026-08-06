"""
gen_gds_placement.py

Generates Layout/i2c_slave_async_layout.gds: a placement-only (no M1/M2/poly
signal routing yet) GDSII for i2c_slave_async_net.v, using the real
TR-1um_STDCELL.gds cell library and the row plan from
plan_placement.compute_rows() (logical rows 0..3, row 0 = bottom of the
4-row standard-cell stack, ascending upward).

Physical row stack (bottom to top), each physical row 55.0um tall
(row_height, prBoundary-based):
    2 x FILL1 filler row   -- bottom M1 routing margin  (below logical row0)
    logical row 0
    logical row 1
    3 x FILL1 filler row   -- shared M1 routing channel (between logical row1/row2)
    logical row 2
    logical row 3
    2 x FILL1 filler row   -- top M1 routing margin     (above logical row3)
  = 11 physical rows x 55.0um = 605.0um core height.

Why these specific channel sizes/locations (see design_notes.md section 15
for the full derivation): logical row0 and row3 each have an unobstructed
block edge available, so they get their own dedicated M1 channel sized to
their own routing need (row0: 27 tracks / 108.0um practical -> 2 filler
rows = 110um; row3: 14 tracks / 56.0um practical -> 2 filler rows = 110um).
logical row1 and row2 are the two "inner" rows and only have each other's
shared boundary to route through (their other boundary, against row0/row3
respectively, stays a zero-gap power-rail-shared abutment -- same mirroring
scheme as before), so they share ONE channel sized to their COMBINED need
(29 tracks / 116.0um practical -> 3 filler rows = 165um).

The Y-mirroring alternates by PHYSICAL row index (0..10), not logical row
index, so that VDD/GND rail sharing (and continuity through the filler
rows, which have vdd/gnd pins at the same local y=0/y=55 as real cells)
holds at every physical row boundary, including the boundaries against the
filler regions -- verified after generation by reading back vdd/gnd pin
label y-coordinates (see design_notes.md section 15).

Filler cells (FILL1, prBoundary width 16.5um) are only used to satisfy
density/well-tap continuity rules -- they carry no signal routing
themselves, so placing them anywhere costs nothing routing-wise. 1800.0 /
16.5 = 109.09, so a full-width filler-only row places 109 instances
(1798.5um) with a 1.5um leftover gap on the right.

Within each LOGICAL (real-cell) row, the row's own unused width (~250-470um,
see design_notes.md section 13) is filled with FILL1 too, but spread out as
several short corridors interspersed through the cell sequence
(distribute_row_fillers(), ~1 corridor per 200um of placed cell width)
rather than left as one big empty/unfilled block at the row's right end.
This gives every real cell a nearby M1/M2-clear corridor to route a
vertical trunk through, instead of only cells near the right edge having
easy channel access (see design_notes.md section 16).

Also draws (non-fab, reference-only):
  - block-boundary pin markers on layer 48/0 (same convention the stdcell
    library itself uses for pin labels): SCL/SDA(in/oe)/RST_N on the LEFT
    edge (x=0), everything else (tx_data/rx_data/rx_valid/addr_match/rw/
    busy/VDD/GND) on the RIGHT edge (x=ROW_WIDTH_UM), spaced evenly over
    the full (new, 605.0um) core height.
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
# NOTE on layer choice: 48/0 is "TXM1" (real pin-name text layer, used by the
# stdcell library itself) and 48/1 is "pin" (real pin shape layer) per
# tech/TR-1um.lyp -- both are legitimate PDK layers, reused here on purpose
# for the block-boundary pin markers so they read the same way as the
# stdcell library's own pins. 199/0 is "COVER" (a real PDK layer) so the
# non-fab annotation/outline layers are moved to unused numbers instead.
PIN_LAYER = (48, 0)     # same convention as the stdcell library's own pin labels
ANNOT_LAYER = (250, 0)  # non-fab: instance-name annotation only
OUTLINE_LAYER = (251, 0)  # non-fab: core outline only

FILLER_CELL = "FILL1"
# Physical row stack, bottom to top. None = one filler-only row; an int = a
# logical row index into compute_rows()'s `rows` list.
PHYSICAL_ROWS = (
    [None, None]        # bottom M1 routing margin (below logical row 0)
    + [0, 1]             # logical rows 0, 1 (zero-gap, rail-shared pair)
    + [None] * 7           # shared M1 routing channel (between row1/row2) --
                            # widened 3->7 filler rows (165->385um, ~24->56
                            # track slots) to fit the 46 tracks row1/2's
                            # FM-optimized intra-row nets need. Must stay ODD
                            # to preserve row2/row3 mirror parity.
    + [2, 3]             # logical rows 2, 3 (zero-gap, rail-shared pair)
    + [None] * 4           # top M1 routing margin (above logical row 3) --
                            # widened 2->4 filler rows (110->220um, ~16->32
                            # track slots) to fit the 22 tracks row3's
                            # intra-row nets need. No parity constraint here.
)
# Zero-gap, rail-shared row pairs -- their in-row filler corridors are
# aligned in absolute X (see distribute_paired_row_fillers()) so a straight
# M2 vertical trunk can pass through both rows of a pair without a jog.
ROW_PAIRS = [(0, 1), (2, 3)]

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

    def distribute_paired_row_fillers(idx_a, row_a, idx_b, row_b, target_spacing_um=200.0):
        """Insert filler corridors into two zero-gap, rail-shared logical
        rows (a pair) so that the corridors land at (approximately) the
        same absolute X in both rows -- letting a straight M2 vertical
        trunk pass through both rows without a horizontal jog.

        Both rows walk the SAME set of evenly-spaced X thresholds. At each
        threshold, real cells are consumed from each row up to that point,
        then the SAME number of FILL1 cells (a fixed corridor size, shared
        by both rows) is inserted in both -- this keeps every corridor a
        consistent size (evenly distributed, not lumped) while placing them
        at matching thresholds in both rows. The corridor size is capped by
        whichever row has the SMALLER total gap, so it fits in both; the
        row with the larger gap gets one extra, unaligned corridor of its
        own leftover slack appended at the very end.

        Because the two rows' real-cell content differs, the actual
        corridor start position in each row can drift from the shared
        threshold by up to one cell's width (the cell that was "in flight"
        when the threshold was crossed) -- exact pixel alignment isn't
        possible at cell granularity, but this keeps the drift bounded and
        corridors overlapping in practice.
        """
        used_a = sum(w for _n, _t, w in row_a)
        used_b = sum(w for _n, _t, w in row_b)
        gap_a = ROW_WIDTH_UM - used_a
        gap_b = ROW_WIDTH_UM - used_b
        shared_gap = min(gap_a, gap_b)

        n_corridors = max(1, round(min(used_a, used_b) / target_spacing_um))
        n_corridors = max(1, min(n_corridors, int(shared_gap // (2 * filler_w)) or 1))
        fillers_per_corridor = int((shared_gap / n_corridors) // filler_w)
        thresholds = [(k + 1) * ROW_WIDTH_UM / (n_corridors + 1) for k in range(n_corridors)]

        seq_a, seq_b = [], []
        ia, ib = 0, 0
        cum_a = cum_b = 0.0
        max_drift = 0.0
        for k, thr in enumerate(thresholds):
            while ia < len(row_a) and cum_a < thr:
                seq_a.append(row_a[ia]); cum_a += row_a[ia][2]; ia += 1
            while ib < len(row_b) and cum_b < thr:
                seq_b.append(row_b[ib]); cum_b += row_b[ib][2]; ib += 1
            # Pre-pad whichever row is behind with a couple of extra FILL1
            # (taken from that row's own slack, not the shared corridor
            # budget) to bring both rows closer together BEFORE placing the
            # shared corridor block -- tightens the corridor's start
            # position match between the two rows. Capped at a few fillers
            # (small correction only) AND never allowed to eat into the
            # width still needed for that row's remaining real cells OR the
            # width still committed to THIS and remaining thresholds' own
            # shared corridors -- otherwise the row could overflow past
            # ROW_WIDTH_UM (this is exactly what happened before this
            # reserve was added: a tight row's small true leftover slack
            # got eaten by padding, leaving no room for its own later
            # corridors).
            remaining_corridor_budget = (n_corridors - k) * fillers_per_corridor * filler_w
            remaining_a = sum(w for _n, _t, w in row_a[ia:]) + remaining_corridor_budget
            remaining_b = sum(w for _n, _t, w in row_b[ib:]) + remaining_corridor_budget
            p = 0
            while abs(cum_a - cum_b) >= filler_w and p < 3:
                if cum_a < cum_b:
                    if cum_a + filler_w + remaining_a > ROW_WIDTH_UM:
                        break
                    seq_a.append((f"padA{idx_a}_{k}_{p}", FILLER_CELL, filler_w)); cum_a += filler_w
                else:
                    if cum_b + filler_w + remaining_b > ROW_WIDTH_UM:
                        break
                    seq_b.append((f"padB{idx_b}_{k}_{p}", FILLER_CELL, filler_w)); cum_b += filler_w
                p += 1
            max_drift = max(max_drift, abs(cum_a - cum_b))
            for j in range(fillers_per_corridor):
                seq_a.append((f"corrA{idx_a}_{k}_{j}", FILLER_CELL, filler_w)); cum_a += filler_w
                seq_b.append((f"corrB{idx_b}_{k}_{j}", FILLER_CELL, filler_w)); cum_b += filler_w
        seq_a.extend(row_a[ia:])
        seq_b.extend(row_b[ib:])

        # Whichever row had the larger gap still has leftover slack beyond
        # what the shared/aligned corridors used -- fill it with one extra,
        # unaligned corridor at the end (right edge) rather than leaving it
        # as a raw unfilled gap.
        for seq, w_used in ((seq_a, sum(w for _n, _t, w in seq_a)),
                             (seq_b, sum(w for _n, _t, w in seq_b))):
            extra_gap = max(0.0, ROW_WIDTH_UM - w_used)
            n_extra = int(extra_gap // filler_w)
            for j in range(n_extra):
                seq.append((f"extra_{idx_a}_{idx_b}_{j}", FILLER_CELL, filler_w))

        final_a = sum(w for _n, _t, w in seq_a)
        final_b = sum(w for _n, _t, w in seq_b)
        assert final_a <= ROW_WIDTH_UM + 1e-6, f"row {idx_a} overflowed: {final_a:.1f}um > {ROW_WIDTH_UM}um"
        assert final_b <= ROW_WIDTH_UM + 1e-6, f"row {idx_b} overflowed: {final_b:.1f}um > {ROW_WIDTH_UM}um"
        print(f"  rows {idx_a}+{idx_b} (paired): {n_corridors} aligned corridors x "
              f"{fillers_per_corridor} FILL1 each (pre-corridor drift <= {max_drift:.1f}um), "
              f"final used+filler: row{idx_a}={final_a:.1f}um, row{idx_b}={final_b:.1f}um")
        return seq_a, seq_b

    # Mirrored rows are drawn RIGHT-TO-LEFT (reversed), so to get corridors
    # that line up in absolute X after drawing, the pairing/alignment must
    # run on each row's cell list in its actual PHYSICAL (post-mirror)
    # drawing order, not compute_rows()'s raw left-to-right order.
    logical_row_mirrored = {}
    for phys_idx, entry in enumerate(PHYSICAL_ROWS):
        if entry is not None:
            logical_row_mirrored[entry] = (phys_idx % 2 == 1)

    def physical_order(idx):
        row = rows[idx]
        return list(reversed(row)) if logical_row_mirrored[idx] else row

    logical_row_seq = {}
    for a, b in ROW_PAIRS:
        seq_a, seq_b = distribute_paired_row_fillers(a, physical_order(a), b, physical_order(b))
        logical_row_seq[a] = seq_a
        logical_row_seq[b] = seq_b

    placed = 0
    n_phys = len(PHYSICAL_ROWS)
    for phys_idx, entry in enumerate(PHYSICAL_ROWS):
        mirrored = (phys_idx % 2 == 1)
        row_bottom_abs = phys_idx * row_height

        if entry is None:
            seq = [(f"fill_{phys_idx}_{i}", FILLER_CELL, filler_w) for i in range(n_filler)]
            kind = "filler"
        else:
            # Already in correct physical (post-mirror) drawing order --
            # do NOT reverse again here.
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
