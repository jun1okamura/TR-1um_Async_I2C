#!/usr/bin/env python3
"""
gen_irsim_debug_n123n235.py -- follow-up to irsim_debug_n23.cmd
(design_notes.md 76.46): N23 (rw's and addr_match's shared D-input mux
select, "0"=capture / "1"=hold) briefly went to 0 one edge too early
(right after bit1, when bit_cnt has JUST become 7 but the RTL's
bit_cnt==7 CHECK -- which should fire on the FOLLOWING edge, bit0's --
hasn't happened yet), then returned to 1 by the time bit0 (the actual R/W
bit) arrives, missing the real capture window entirely.

Netlist tracing found N23's exact drive gate: N23 = NAND(N123, N235) (2
parallel PMOS pull-up + 2 series NMOS pull-down, confirmed via the .sim).
N123 is itself gated in part by N11 (one of the confirmed bit_cnt Q
outputs) -- likely part of a bit_cnt==7 comparator. N235 has very high
fanout elsewhere in the design (appears at many unrelated gates), and is
gated in part by N137 (one of the phase candidates) -- likely a
phase==PH_ADDR-type decode. This traces N123 and N235 (N23's two direct
NAND inputs) alongside N23 itself, through the READ address byte, to see
which one is the actual source of the one-edge-early transition: does
N123 (bit_cnt-derived) go high one edge early, or does N235 (phase-
derived) drop low one edge late, or do both change at the "wrong" time
for some other reason?

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_n123n235.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, RW, ADDR_MATCH, TX  # noqa: E402

N123 = "XN3.N123"
N235 = "XN3.N235"
N23 = "XN3.N23"
N11 = "XN3.N11"   # bit_cnt candidate, one of N123's gate inputs
N137 = "XN3.N137"  # phase candidate, one of N235's gate inputs


def main():
    g = CmdGen()
    g.note("irsim_debug_n123n235.cmd -- traces N23's two direct NAND")
    g.note("inputs (N123, bit_cnt-derived; N235, phase-derived, high")
    g.note("fanout) through the READ address byte, to find which one")
    g.note("causes N23's capture window to open one edge too early.")
    g.note("Follow-up to irsim_debug_n23.cmd -- see design_notes.md")
    g.note("76.46/76.47.")
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
    g.note(f"ADDR+R = 0x{addr_byte_r:02X}")
    for i in range(7, -1, -1):
        bitval = (addr_byte_r >> i) & 1
        g.send_bit(bitval)
        g.note(f"---- after bit {i} (value={bitval}) ----")
        g.d(N123, N235, N23, N11, N137, RW, ADDR_MATCH)

    g.read_ack("address ack (read)")
    g.d(N123, N235, N23, N11, N137, RW, ADDR_MATCH)

    g.raw("")
    g.note("end of irsim_debug_n123n235.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_n123n235.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
