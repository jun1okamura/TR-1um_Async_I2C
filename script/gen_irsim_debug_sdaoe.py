#!/usr/bin/env python3
"""
gen_irsim_debug_sdaoe.py -- follow-up to irsim_debug_n697.cmd (design_notes.md
76.36): the analyzer screenshot revealed something much bigger than a
shreg-capture problem. N58 (SDA) and N697 track each other exactly, and
BOTH fall to 0 at the START condition and then stay FLAT AT 0 through the
entire address-byte window -- including bit 7 and bit 5, which the
stimulus explicitly RELEASES (`x SDA`, expecting the external pull-up to
pull it back toward 1). SDA never recovers. Since every bit of the address
byte gets read back as an SDA-low ("0"), this alone would explain BOTH
earlier findings at once: shreg[6:0] never captures anything but 0s
(because every bit really does read as 0 at the slave's input, regardless
of what the master intends to send), and addr_match never asserts
(0xA0 was never actually what arrived).

The obvious suspect: is SDA being actively held low by the slave's own
sda_oe (open-drain drive enable), rather than just failing to recover
via the weak pull-up? sda_oe is itself a DFFRB output (X$318, D=$333,
RSTB=$227, CK=$513, Q=sda_oe) in the $227 group, force-released once
busy first asserts in start()'s first=True branch (design_notes.md
76.13) -- but if $513 toggles again during the bit-clocking window (it's
driven by BUF_X1 from $708, structurally similar to N635/N666/N34), sda_oe
could get re-clocked mid-transaction and latch a stale/wrong D value,
actively pulling SDA low via the slave's own open-drain NMOS -- which
would look exactly like what the screenshot shows (a hard, flat,
non-drifting 0, not a slowly-recovering pull-up).

This script traces SDA/SCL/SDA_OE(N45)/N513 continuously (via `ana`) plus
explicit per-bit `d` checks through the whole address byte, to confirm or
rule out sda_oe as the active culprit.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_sdaoe.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, SCL, SDA, SDA_OE, BUSY  # noqa: E402

N513 = "XN3.N513"


def main():
    g = CmdGen()
    g.note("irsim_debug_sdaoe.cmd -- is SDA_OE actively pulling SDA low")
    g.note("during the address byte (not just a slow pull-up recovery)?")
    g.note("Follow-up to irsim_debug_n697.cmd -- see design_notes.md")
    g.note("76.36/76.37. sda_oe is itself a DFFRB (X$318) in the $227")
    g.note("group, CK=$513 -- checking whether $513 re-toggles mid-byte")
    g.note("and re-latches sda_oe to a bad value.")
    g.preamble()

    g.d(SCL, SDA, SDA_OE, BUSY, N513)
    g.raw("ana " + " ".join([SCL, SDA, SDA_OE, BUSY, N513]))
    g.raw("")

    g.note("==================== WRITE TRANSACTION (address byte only) ====================")
    g.start(first=True)

    addr_byte = (SLAVE_ADDR << 1) | 0
    g.note(f"ADDR+W = 0x{addr_byte:02X}")
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
        g.s()
        g.note(f"---- bit {i} (value={bitval}): +1 stepsize after SCL rising edge ----")
        g.d(SCL, SDA, SDA_OE, N513)
        g.s(2 * 20 - 2)

    g.raw("")
    g.note("end of irsim_debug_sdaoe.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_sdaoe.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
