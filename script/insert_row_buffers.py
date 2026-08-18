"""
insert_row_buffers.py

Row-aware buffer insertion for i2c_slave_async_net_v3.v's two clock nets
(scl, scl_n), per user request (design_notes.md section 40): instead of
insert_buffers.py's row-UNAWARE N-way SPLIT (sinks divided by plain
instance order, so each branch still spans multiple rows -- see section
18/38's PER_ROW_LOCAL_NETS mechanism that had to work around exactly this
by giving such nets per-row trunks *inside the router*), insert one real
BUF_X1 per placement ROW, each driven directly from the global net and
feeding ONLY that row's sinks. Every such per-row net becomes a genuine
row-only net (no multi-row spanning at all), which needs no special
router treatment -- the "spread across rows" problem is solved at the
netlist level instead of the router level.

Method:
  1. Parse i2c_slave_async_net_v3.v (already-synthesized netlist).
  2. Compute a REFERENCE row assignment via the same fm_multiway_partition
     used by gen_placement_nrow_fm.py, at N_ROWS=4 (this is only a
     reference pass to decide sink groupings -- the real placement is
     re-run from scratch on the buffered netlist afterward, see
     design_notes.md section 40 for why this two-pass approach is safe:
     grouping a net's sinks by row creates a strong-locality net that
     gives the partitioner every incentive to keep the buffer + its
     sinks together on the second, real pass).
  3. For each target net (scl, scl_n), group its sink (pin, direction=in)
     connections by the row their owning instance landed in.
  4. For every row with >=1 sink, add one BUF_X1 instance
     (u_buf_{net}_row{r}), driven by the original global net, feeding a
     new row-local net ({net}_row{r}); redirect every one of that row's
     sinks to the new local net via precise per-instance text
     substitution (same mechanism as insert_buffers.py's redirect()).
  5. Write the result as i2c_slave_async_net_v4.v (v3 is left untouched).

Run: python3 script/insert_row_buffers.py
"""
import json
import re
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from lef_parser import parse_lef  # noqa: E402
from netlist_parser import parse_netlist  # noqa: E402
from fm_partition import fm_multiway_partition  # noqa: E402

V3_PATH = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net_v3.v"
V4_PATH = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net_v4.v"
# Full instance->row assignment for v4: the 175 pre-existing instances keep
# EXACTLY the row fm_multiway_partition gave them on the reference
# (unbuffered) pass below; each new buffer is placed in the row of the
# sink group it was built from (by construction, not re-derived). This is
# saved so gen_placement_nrow_fm.py can be told to use it AS-IS instead of
# re-running fm_multiway_partition on the buffered netlist -- re-running
# was tried and found unstable (design_notes.md section 40): adding just 6
# small instances shifted the recursive-bisection's top-level cut enough
# that most instances (including several buffer/sink pairs) landed in
# different rows than intended, defeating the whole point of row-aware
# buffering. Reusing the reference partition for unchanged instances
# sidesteps that instability entirely.
ROW_ASSIGNMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/row_assignment_v4.json"

N_ROWS = 4
BUF_CELL = "BUF_X1"
TARGET_NETS = ["scl", "scl_n"]


def main(in_path=V3_PATH, out_path=V4_PATH, row_assignment_json=ROW_ASSIGNMENT_JSON,
         target_nets=None):
    global TARGET_NETS
    if target_nets is not None:
        TARGET_NETS = target_nets
    macros = parse_lef()
    widths = {name: m["size"][0] for name, m in macros.items()}

    net = parse_netlist(path=in_path)
    instances = net["instances"]  # [(typ, name, {pin: canon_net}), ...]

    print(f"parsed {len(instances)} instances from {in_path}")

    part = fm_multiway_partition(instances, widths, N_ROWS)
    print(f"reference row assignment computed ({N_ROWS} rows)")
    row_counts = {}
    for name, r in part.items():
        row_counts[r] = row_counts.get(r, 0) + 1
    for r in sorted(row_counts):
        print(f"  row{r}: {row_counts[r]} instances")

    # sinks[net] = [(instname, pinname, row), ...] -- only INPUT-direction
    # pins (a net can only be usefully split by its LOAD side; the driver
    # side, if any, stays connected to the original global net).
    sinks_by_net = {t: [] for t in TARGET_NETS}
    for typ, name, pins in instances:
        pin_meta = macros[typ]["pins"]
        for pname, net_name in pins.items():
            if net_name not in TARGET_NETS:
                continue
            info = pin_meta.get(pname)
            if info is None or info["direction"] != "INPUT":
                continue
            sinks_by_net[net_name].append((name, pname, part[name]))

    for t in TARGET_NETS:
        assert sinks_by_net[t], f"net {t!r} has no INPUT-direction sinks -- check net name"

    src = open(in_path).read()

    def redirect(instname, pinname, new_net):
        nonlocal src
        block_re = re.compile(r'(\b' + re.escape(instname) + r'\s*\(.*?\)\s*;)', re.S)
        bm = block_re.search(src)
        assert bm, f"could not find instance block for {instname}"
        block = bm.group(1)
        pin_re = re.compile(r'(\.' + re.escape(pinname) + r'\s*\(\s*)([^()]*?)(\s*\))')
        new_block, n = pin_re.subn(lambda m2: m2.group(1) + new_net + m2.group(3), block, count=1)
        assert n == 1, f"could not redirect {instname}.{pinname}"
        src = src[:bm.start()] + new_block + src[bm.end():]

    inserted_blocks = []
    new_wires = []
    report = []

    for target_net in TARGET_NETS:
        by_row = {}
        for instname, pinname, row in sinks_by_net[target_net]:
            by_row.setdefault(row, []).append((instname, pinname))

        branch_report = []
        for r in sorted(by_row):
            group = by_row[r]
            branch_net = f"{target_net}_row{r}"
            iname = f"u_buf_{target_net}_row{r}"
            for instname, pinname in group:
                redirect(instname, pinname, branch_net)
            inserted_blocks.append(
                f"  {BUF_CELL} {iname} (\n    .A({target_net}),\n    .Y({branch_net}),\n"
                f"    .VDD(VDD),\n    .GND(GND)\n  );"
            )
            new_wires.append(branch_net)
            branch_report.append((r, branch_net, len(group)))

        report.append((target_net, branch_report))
        print(f"{target_net}: {len(by_row)} rows touched -> "
              + ", ".join(f"row{r}:{bn}({c})" for r, bn, c in branch_report))

    decl = "\n".join(f"  wire {w};" for w in new_wires)
    first_inst_m = re.search(r'\n  \w+ \w+\s*\(', src)
    src = src[:first_inst_m.start()] + "\n" + decl + src[first_inst_m.start():]

    endmod_idx = src.rindex("endmodule")
    src = src[:endmod_idx] + "\n" + "\n\n".join(inserted_blocks) + "\n\n" + src[endmod_idx:]

    with open(out_path, "w") as f:
        f.write(src)
    print(f"\nwrote {out_path}")

    # full row assignment: reference `part` for the original instances
    # (unchanged names) + each new buffer's row by construction.
    full_part = dict(part)
    for target_net, branch_report in report:
        for r, bn, _c in branch_report:
            full_part[f"u_buf_{target_net}_row{r}"] = r
    with open(row_assignment_json, "w") as f:
        json.dump(full_part, f, indent=1)
    print(f"wrote {row_assignment_json} ({len(full_part)} instances)")

    print("\n=== summary ===")
    for target_net, branch_report in report:
        for r, bn, c in branch_report:
            print(f"  {bn:<16} FO={c}  (row{r}, from {target_net})")


if __name__ == "__main__":
    main()
