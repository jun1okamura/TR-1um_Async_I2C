"""
estimate_m2.py

Rough M2 (vertical trunk) routing-area estimate for the 3-channel floorplan
used by gen_gds_placement.py (see design_notes.md section 15):
    bottom margin   = logical row 0
    middle channel  = logical rows 1 + 2 (combined -- they share one channel)
    top margin      = logical row 3

Model (explicitly conservative -- a true upper bound, not a tight
requirement; see design_notes.md section 15 for discussion):
  - For each group, count the distinct signal nets (excl. VDD/GND) that have
    at least one pin in that group's row(s) -- each such net needs at least
    one M2 vertical trunk reaching that group's M1 channel.
  - Worst-case M2 width if EVERY one of those trunks needed its own
    simultaneous parallel column (no sharing at all) = net_count * M2 pitch.
  - Compare against the actual unused width in that group's row(s) (the
    row's own placed-cell width vs. ROW_WIDTH_UM), to see whether trunks
    plausibly fit without growing the block width.

Rerun after re-placing (plan_placement.py / gen_gds_placement.py change):
    python3 script/estimate_m2.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_placement import compute_rows, _parse_netlist, _canon_fn, NROWS, ROW_WIDTH_UM  # noqa: E402

M2_MIN_PITCH = 3.0 + 2.0  # um, DRC minimum (M2.W1 width 3.0 + M2.S1 space 2.0)

# Same 3-group floorplan as gen_gds_placement.py's PHYSICAL_ROWS.
GROUPS = [
    ("bottom margin (logical row 0 / \"4列目\")", {0}),
    ("middle channel (logical rows 1+2 / \"3列目\"+\"2列目\")", {1, 2}),
    ("top margin (logical row 3 / \"1列目\")", {3}),
]


def main():
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)
    row_used_width = {r: sum(w for _n, _t, w in rows[r]) for r in range(NROWS)}

    sym_pins, width_of, instances, assigns = _parse_netlist()
    find, parent = _canon_fn(width_of, instances, assigns)

    # Reconstruct which logical row each instance lives in (same order as
    # gen_gds_placement.py, though only row membership matters here).
    inst_row = {}
    for r in range(NROWS):
        for name, typ, w in rows[r]:
            inst_row[name] = r

    net_rows = {}  # canonical net -> set of logical rows it touches
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':  # VDD/GND
                continue
            net = find(expr)
            net_rows.setdefault(net, set()).add(inst_row[name])

    for label, rset in GROUPS:
        nets = {net for net, touched in net_rows.items() if touched & rset}
        worst_um = len(nets) * M2_MIN_PITCH
        avail_um = sum(ROW_WIDTH_UM - row_used_width[r] for r in rset)
        verdict = "OK (margin available)" if worst_um <= avail_um else "SHORTFALL"
        print(f"{label}: {len(nets)} nets -> worst-case M2 width {worst_um:.1f}um "
              f"vs available row-end margin {avail_um:.1f}um  [{verdict}]")


if __name__ == "__main__":
    main()
