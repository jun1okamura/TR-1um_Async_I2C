#!/usr/bin/env python3
"""
gen_irsim_debug_rwmargin.py -- follow-up to irsim_debug_rw2.cmd
(design_notes.md 76.43): src/i2c_slave_async.v (lines 102-164) shows
`rw_bit` and `addr_ok` are BOTH registered, gated updates -- both only
change on the SAME SCL posedge, specifically when `phase==PH_ADDR &&
bit_cnt==7` (the 8th address-byte bit's clock edge), capturing
`shreg_next[0]`/comparing `shreg_next[7:1]` at that instant. `shreg`
itself updates unconditionally every SCL edge, independent of phase/
bit_cnt. Since the earlier full-transaction analyzer screenshot showed
addr_match DID eventually rise to 1 somewhere in the READ transaction
(just apparently not by the time our existing checks fire, right after
read_ack() -- same "checked too early" pattern already hit twice this
session for SDA's own pull-up and for stop()'s own margin), this checks
RW/ADDR_MATCH at several increasing time offsets after the READ address
byte's ACK, to see whether they eventually resolve correctly (a pure
margin shortfall, matching the established pattern) or stay stuck (a
genuine new problem in phase/bit_cnt's own mid-run reset).

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_rwmargin.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, RW, ADDR_MATCH, BUSY, TX  # noqa: E402


def main():
    g = CmdGen()
    g.note("irsim_debug_rwmargin.cmd -- does RW/ADDR_MATCH eventually")
    g.note("resolve correctly after the READ address byte's ACK, given")
    g.note("more real elapsed time? Follow-up to irsim_debug_rw2.cmd --")
    g.note("see design_notes.md 76.43/76.44. Runs the REAL WRITE")
    g.note("transaction + READ transaction's address byte first (same")
    g.note("primitives as irsim_test_main.cmd).")
    g.preamble()

    g.note("==================== WRITE TRANSACTION (real, unmodified) ====================")
    g.start(first=True)
    addr_byte_w = (SLAVE_ADDR << 1) | 0
    g.send_byte(addr_byte_w)
    g.read_ack("address ack (write)")
    DATA_WR = 0xA5
    g.send_byte(DATA_WR)
    g.read_ack("data ack")
    g.stop("after write")

    g.note("==================== READ TRANSACTION ====================")
    DATA_RD = 0x3C
    for i in range(8):
        bit = (DATA_RD >> i) & 1
        (g.h if bit else g.l)(TX[i])
    g.s(2 * 20)
    g.start()

    addr_byte_r = (SLAVE_ADDR << 1) | 1
    g.send_byte(addr_byte_r)
    g.read_ack("address ack (read)")
    g.note("---- original (failing) check point: 0ns extra margin ----")
    g.d(RW, ADDR_MATCH, BUSY)

    checkpoints = [100, 200, 500, 1000, 2000, 4000]
    prev = 0
    for cp in checkpoints:
        g.s(cp - prev)
        prev = cp
        g.note(f"---- +{cp}ns after the READ address-byte ACK ----")
        g.d(RW, ADDR_MATCH, BUSY)

    g.raw("")
    g.note("end of irsim_debug_rwmargin.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_rwmargin.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
