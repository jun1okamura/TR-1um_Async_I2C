#!/usr/bin/env python3
"""
gen_irsim_debug_shreg.py -- follow-up to irsim_debug_addrmatch.cmd
(design_notes.md 76.33): ADDR_MATCH stayed a clean, defined 0 the entire
time from the WRITE address byte's ACK out to +4000ns (real run, confirmed
via both console dumps and the analyzer screenshot -- rw/addr_match glitch
X only briefly right as busy asserts, from the $28-group force/release,
then settle to a flat, un-glitching 0 for the rest of the window). This
rules out a pure timing-margin shortfall (that would show it eventually
resolving to 1, or at least glitching) -- so the ADDRESS COMPARE ITSELF
must not be seeing a match.

The 7-bit address shift register survives in the flattened .sim with its
literal RTL name (design_notes.md's netlist tracing, src/
tr_1um_i2c_slave_async.extracted lines ~96-134): XN3.shreg[0] through
XN3.shreg[6] (7 bits -- the 8th bit of the address+R/W byte is the R/W bit,
captured separately, not part of shreg). This script dumps all 7 shreg
bits (plus ADDR_MATCH/RW/BUSY for cross-reference) right after the address
byte's ACK, to see whether the shift register actually captured something
resembling SLAVE_ADDR=0x50 (0b101_0000) or garbage/stuck-at-X/stuck-at-0 --
which tells us whether the bug is in the SHIFTING (bits never captured
correctly) or in the COMPARE (bits captured fine, but the comparator/
addr_match register itself doesn't fire).

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_shreg.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import (  # noqa: E402
    CmdGen, SLAVE_ADDR, SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH,
)

SHREG = [f"XN3.shreg[{i}]" for i in range(7)]


def main():
    g = CmdGen()
    g.note("irsim_debug_shreg.cmd -- does the 7-bit address shift register")
    g.note("(XN3.shreg[0..6]) actually capture SLAVE_ADDR=0x50 during the")
    g.note("WRITE address byte, or is the SHIFTING itself broken under")
    g.note("TR-1um.prm? Follow-up to irsim_debug_addrmatch.cmd -- see")
    g.note("design_notes.md 76.33/76.34.")
    g.preamble()

    g.d(SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH, *SHREG)
    g.raw("ana " + " ".join([SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH]))
    g.raw("")

    g.note("==================== WRITE TRANSACTION (address byte only) ====================")
    g.start(first=True)

    addr_byte = (SLAVE_ADDR << 1) | 0
    g.note(f"ADDR+W = 0x{addr_byte:02X} -- sending bit-by-bit via the real")
    g.note("send_bit() (now with SDA_RELEASE_SETTLE_NS margin, 76.39),")
    g.note("dumping shreg after EACH bit so we can see it shift in real")
    g.note("time, not just at the end.")
    for i in range(7, -1, -1):
        bitval = (addr_byte >> i) & 1
        g.send_bit(bitval)
        g.note(f"---- after bit {i} (value={bitval}) ----")
        g.d(*SHREG, RW, ADDR_MATCH)

    g.read_ack("slave ACKed matching address (write)")
    g.note("---- final: after ACK ----")
    g.d(*SHREG, RW, ADDR_MATCH, BUSY)

    g.raw("")
    g.note("end of irsim_debug_shreg.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_shreg.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
