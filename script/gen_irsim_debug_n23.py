#!/usr/bin/env python3
"""
gen_irsim_debug_n23.py -- follow-up to irsim_debug_bitcnt.cmd (design_notes.md
76.45): bit_cnt/phase appear to correctly count up and transition at the
right moment (evidence: two of the presumed candidates jump together
exactly when the decoded counter value reaches 7). But rw/addr_match still
never update. Netlist tracing of rw's D-input mux (XN1, feeding N207)
found the exact mechanism: N207 = N40 when N23=0 ("capture"), or N207 = rw
itself (feedback) when N23=1 ("hold"). The SAME N23 net also selects
addr_match's own analogous mux (XN17) -- so if N23 never actually drops to
0 at the bit_cnt==7 moment, BOTH rw and addr_match would stay permanently
in "hold" mode, exactly matching what's been observed. N23 itself is
driven combinationally off nodes including N11 (one of the bit_cnt
candidates) -- so this is likely the actual "bit_cnt==7 && phase==PH_ADDR"
decode gate.

This traces N23 (the capture/hold select), N40 (rw's actual "new value"
source when capturing), N207 (rw's D-input, = NOT(mux output)), shreg[0]
(should hold the R/W bit once fully shifted in), and rw itself, together,
after each bit of the READ address byte -- to see whether N23 ever
actually asserts "capture" (0), and if so, whether N40 correctly reflects
1 (the R/W bit) at that moment.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_n23.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, RW, ADDR_MATCH, TX  # noqa: E402

N23 = "XN3.N23"
N40 = "XN3.N40"
N207 = "XN3.N207"
SHREG0 = "XN3.shreg[0]"


def main():
    g = CmdGen()
    g.note("irsim_debug_n23.cmd -- traces rw's D-input mux select (N23,")
    g.note("shared with addr_match's own mux XN17) and its 'new value'")
    g.note("source (N40) through the READ address byte, to see whether")
    g.note("N23 ever asserts capture (0) at bit_cnt==7, and whether N40")
    g.note("correctly reflects the R/W bit at that moment. Follow-up to")
    g.note("irsim_debug_bitcnt.cmd -- see design_notes.md 76.45/76.46.")
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
        g.d(N23, N40, N207, SHREG0, RW, ADDR_MATCH)

    g.read_ack("address ack (read)")
    g.d(N23, N40, N207, SHREG0, RW, ADDR_MATCH)

    g.raw("")
    g.note("end of irsim_debug_n23.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_n23.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
