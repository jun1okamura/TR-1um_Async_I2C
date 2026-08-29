#!/usr/bin/env python3
"""
gen_irsim_debug_shregclk.py -- follow-up to irsim_debug_shreg.cmd
(design_notes.md 76.34): shreg[0..6] stayed at a flat, defined 0 through
all 8 address-byte bits + ACK -- the shift register never captured
anything at all, not even garbage. This is a stronger symptom than a
compare-logic bug: the register bank simply isn't clocking.

Netlist tracing (src/tr_1um_i2c_slave_async.extracted, DFFRB instantiations
around lines 46-152) shows the $28-group registers are NOT all on one
shared derived clock -- they split across several distinct nets depending
on which register: shreg[6]/shreg[4]/shreg[5]/rx_data[*] and, critically,
ADDR_MATCH's own DFFRB (X$16) all share CK=$635 (sanitized: XN3.N635);
shreg[0]/shreg[1]/shreg[2]/shreg[3] share CK=$666 (XN3.N666); RW's own
DFFRB (X$2) uses yet another net, CK=$34 (XN3.N34). (.sim confirms N635/
N666/N34 each drive some XN<inst>.CKB pin directly -- i.e. these ARE the
per-register derived clock inputs, not just coincidental net names.)

If these derived clocks never actually toggle in response to real SCL
edges, that alone explains BOTH earlier findings at once (shreg stuck at
its reset value, AND addr_match's own DFFRB never firing, since it's
clocked by the same N635). This script traces SCL alongside N635/N666/N34
through the same 8-bit address-byte window as irsim_debug_shreg.cmd, to
see whether these derived clocks toggle at all.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_shregclk.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import (  # noqa: E402
    CmdGen, SLAVE_ADDR, SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH,
)

CLKS = ["XN3.N635", "XN3.N666", "XN3.N34"]
SHREG = [f"XN3.shreg[{i}]" for i in range(7)]


def main():
    g = CmdGen()
    g.note("irsim_debug_shregclk.cmd -- do the $28-group's derived clock")
    g.note("nets (N635/N666/N34 -- feed shreg/addr_match/rw's own DFFRBs")
    g.note("respectively) actually toggle when SCL toggles? Follow-up to")
    g.note("irsim_debug_shreg.cmd -- see design_notes.md 76.34/76.35.")
    g.preamble()

    g.d(SCL, SDA, BUSY, *CLKS)
    g.raw("ana " + " ".join([SCL, SDA, BUSY, *CLKS]))
    g.raw("")

    g.note("==================== WRITE TRANSACTION (address byte only) ====================")
    g.start(first=True)

    addr_byte = (SLAVE_ADDR << 1) | 0
    g.note(f"ADDR+W = 0x{addr_byte:02X} -- dumping SCL + derived clocks after")
    g.note("EACH bit's SCL rising edge (the edge that should trigger a real")
    g.note("capture) to see whether N635/N666/N34 track it at all.")
    for i in range(7, -1, -1):
        bitval = (addr_byte >> i) & 1
        g.s()
        g.l(SCL)
        if bitval:
            g.x(SDA)
        else:
            g.l(SDA)
        g.s()
        g.h(SCL)
        g.note(f"---- bit {i} (value={bitval}): right after SCL rising edge ----")
        g.d(SCL, *CLKS)
        g.s(2 * 20 - 1)  # rest of send_bit()'s 2*T hold
        g.note(f"---- bit {i}: end of hold, shreg snapshot ----")
        g.d(*SHREG)

    g.raw("")
    g.note("end of irsim_debug_shregclk.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_shregclk.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
