#!/usr/bin/env python3
"""
gen_irsim_debug_rw2.py -- follow-up to the real irsim_test_main.cmd run
(design_notes.md 76.42): with force_release_gated() fixing addr_match's
mid-run reset, the READ transaction's START now correctly clears
addr_match to 0, and addr_match correctly re-asserts partway through the
READ address byte -- but `rw` reads 0 right after the READ address byte's
ACK, where it should be 1 (R/W=1 for a READ). rw's own DFFRB (XN2) is
clocked by N34, one of the SAME 4 nets force_release_gated() just forced
low/released as part of resetting the $28 group -- possible that this
disrupted N34's own tracking of real SCL for the rest of the transaction,
or that rw's D input (XN3.N207, confirmed in the .sim) simply isn't
reflecting the R/W bit correctly.

This reuses the real, unmodified CmdGen primitives for the WHOLE WRITE
transaction plus the READ transaction's START (so the fix is exercised
exactly as irsim_test_main.cmd does), then manually unrolls the READ
address byte's 8 bits with a fine-grained trace of rw's own QS/D(N207)/
CK(N34) after each bit, instead of only checking the end result.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_rw2.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import (  # noqa: E402
    CmdGen, SLAVE_ADDR, SCL, SDA, BUSY, RW, ADDR_MATCH, TX, dffrb_qs,
)

RW_QS = dffrb_qs("XN2")
RW_D = "XN3.N207"
RW_CK = "XN3.N34"


def main():
    g = CmdGen()
    g.note("irsim_debug_rw2.cmd -- fine-grained trace of rw's own QS/D/CK")
    g.note("(XN2, D=N207, CK=N34) through the READ address byte, after")
    g.note("force_release_gated() correctly fixed addr_match's mid-run")
    g.note("reset but rw still read 0 after the READ address byte's ACK")
    g.note("(expected 1). See design_notes.md 76.42/76.43. Runs the REAL")
    g.note("WRITE transaction + READ START first (same primitives as")
    g.note("irsim_test_main.cmd).")
    g.preamble()
    g.d(SCL, SDA, BUSY, RW, ADDR_MATCH)
    g.raw("")

    g.note("==================== WRITE TRANSACTION (real, unmodified) ====================")
    g.start(first=True)
    addr_byte_w = (SLAVE_ADDR << 1) | 0
    g.send_byte(addr_byte_w)
    g.read_ack("address ack (write)")
    DATA_WR = 0xA5
    g.send_byte(DATA_WR)
    g.read_ack("data ack")
    g.stop("after write")

    g.note("==================== READ TRANSACTION (real START, then unrolled address byte) ====================")
    DATA_RD = 0x3C
    for i in range(8):
        bit = (DATA_RD >> i) & 1
        (g.h if bit else g.l)(TX[i])
    g.s(2 * 20)
    g.start()

    addr_byte_r = (SLAVE_ADDR << 1) | 1
    g.note(f"ADDR+R = 0x{addr_byte_r:02X} -- unrolled, tracing rw's own")
    g.note("QS/D/CK after EACH bit.")
    for i in range(7, -1, -1):
        bitval = (addr_byte_r >> i) & 1
        g.send_bit(bitval)
        g.note(f"---- after bit {i} (value={bitval}) ----")
        g.d(RW_QS, RW_D, RW_CK, RW)

    g.read_ack("address ack (read) -- check rw=1")
    g.d(RW_QS, RW_D, RW_CK, RW, ADDR_MATCH)

    g.raw("")
    g.note("end of irsim_debug_rw2.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_rw2.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
