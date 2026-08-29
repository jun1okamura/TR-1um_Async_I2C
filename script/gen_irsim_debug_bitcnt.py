#!/usr/bin/env python3
"""
gen_irsim_debug_bitcnt.py -- follow-up to irsim_debug_rwmargin.cmd
(design_notes.md 76.44): rw/addr_match stayed stuck at 0 even after
+4000ns of extra margin post-READ-address-byte-ACK -- ruling out a simple
timing shortfall. src/i2c_slave_async.v shows both are only updated on
the SCL edge where `phase==PH_ADDR && bit_cnt==7`; if `bit_cnt` (a 4-bit
counter, also part of the $28 force/release group) isn't actually
counting up correctly after force_release_gated()'s mid-run reset, that
edge would simply never arrive.

The $28 group's 24 DFFRB instances are fully accounted for by: rw(XN2),
addr_match(XN16), shreg[0..6]+rx_data[*] (14 instances), and 7 remaining
unidentified instances -- XN32/XN46/XN104/XN111 (CK=N34, same net as rw)
and XN115/XN116/XN117 (CK=N343) -- which match exactly phase[2:0] (3
bits) + bit_cnt[3:0] (4 bits) from the RTL. This traces the presumed
bit_cnt candidates (XN32->N43, XN46->N11, XN104->N62, XN111->N243, all
sharing CK=N34 with rw -- possibly relevant, since rw is the one that's
stuck) after each bit of the READ address byte, to see whether they
actually count up 0..7 or are stuck.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_bitcnt.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, RW, ADDR_MATCH, TX  # noqa: E402

BITCNT_CANDIDATES = ["XN3.N43", "XN3.N11", "XN3.N62", "XN3.N243"]
PHASE_CANDIDATES = ["XN3.N358", "XN3.N137", "XN3.N349"]  # XN115/116/117 Q pins


def main():
    g = CmdGen()
    g.note("irsim_debug_bitcnt.cmd -- does the presumed bit_cnt[3:0]")
    g.note("(N43/N11/N62/N243, CK=N34 same as rw) actually count 0..7")
    g.note("during the READ address byte, or is it stuck? Also watching")
    g.note("presumed phase[2:0] (N358/N137/N349, CK=N343) for comparison")
    g.note("-- see design_notes.md 76.44/76.45.")
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

    g.note("---- right after $28-group reset (before any READ address bits) ----")
    g.d(*BITCNT_CANDIDATES, *PHASE_CANDIDATES, RW, ADDR_MATCH)

    addr_byte_r = (SLAVE_ADDR << 1) | 1
    g.note(f"ADDR+R = 0x{addr_byte_r:02X} -- dumping presumed bit_cnt/phase")
    g.note("after EACH bit.")
    for i in range(7, -1, -1):
        bitval = (addr_byte_r >> i) & 1
        g.send_bit(bitval)
        g.note(f"---- after bit {i} (value={bitval}) ----")
        g.d(*BITCNT_CANDIDATES, *PHASE_CANDIDATES)

    g.read_ack("address ack (read)")
    g.d(*BITCNT_CANDIDATES, *PHASE_CANDIDATES, RW, ADDR_MATCH)

    g.raw("")
    g.note("end of irsim_debug_bitcnt.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_bitcnt.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
