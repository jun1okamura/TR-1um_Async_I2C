#!/usr/bin/env python3
"""
gen_irsim_debug_n697.py -- follow-up to irsim_debug_shregclk.cmd
(design_notes.md 76.35): the analyzer's own CONTINUOUS trace (not the
console's zero-margin snapshots, which turned out to have a display-timing
artifact -- querying a node in the same zero-elapsed-time instant as
forcing it with h/l doesn't yet reflect the new value in IRSIM's "d"
output, even though the analyzer's real trace shows the transition) proved
N635/N666/N34 (the $28-group's derived clocks) DO toggle correctly, in
lockstep with SCL, through the whole address byte. So the shift register's
clock input is fine -- the bug must be either in the D input path or in
DFFRB's actual capture behavior on a real toggling edge.

Netlist tracing (src/tr_1um_i2c_slave_async.extracted) found shreg[0]'s D
pin is fed by \\$697 (X$109), and \\$697 turns out to be a heavily-shared
node: X$167 (BUF_X1) drives it from \\$37; it also feeds DEL1 (\\$704,
the already-known-limited chain from 76.22-76.24), NOR2 with \\$703 (the
never-pulsing \\$813, same limitation), AND NAND3 with \\$666 (producing
\\$696, part of busy's OWN edge-detect network -- which we already know
DOES work correctly on every real run this session, including under
TR-1um.prm). Since busy's edge-detect successfully uses the SAME \\$697
net, \\$697 itself is probably fine -- the more likely remaining
explanation is that DFFRB's actual master/slave capture (D=$697,
CK=$666) doesn't successfully latch a REAL toggling D value on a REAL
toggling clock edge under TR-1um.prm's timing, as opposed to the
"reset once, then hold statically with CK never toggling" scenario
already validated by SPICE in 76.31 -- a genuinely different regime.

This script re-traces SDA/N697/N666/shreg[0] together through all 8
address-byte bits, this time with a small settle margin (1 stepsize)
inserted between every h/l/x force and the following "d" check, to avoid
repeating the zero-elapsed-time display artifact from irsim_debug_shregclk.cmd.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_n697.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, SCL, SDA, BUSY  # noqa: E402

N697 = "XN3.N697"
N666 = "XN3.N666"
SHREG0 = "XN3.shreg[0]"


def main():
    g = CmdGen()
    g.note("irsim_debug_n697.cmd -- does N697 (shreg[0]'s D input, shared")
    g.note("with busy's own working edge-detect NAND3) track SDA correctly")
    g.note("bit-by-bit, and does shreg[0] actually latch it on N666's real")
    g.note("clock edges? Follow-up to irsim_debug_shregclk.cmd -- see")
    g.note("design_notes.md 76.35/76.36. Every h/l/x force below is")
    g.note("followed by a 1-stepsize settle BEFORE the check, to avoid the")
    g.note("zero-elapsed-time display artifact found in the previous run.")
    g.preamble()

    g.d(SCL, SDA, BUSY, N697, N666, SHREG0)
    g.raw("ana " + " ".join([SCL, SDA, BUSY, N697, N666, SHREG0]))
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
        g.note(f"---- bit {i} (value={bitval}): SDA set, SCL still low ----")
        g.d(SDA, N697)
        g.h(SCL)
        g.s()
        g.note(f"---- bit {i}: right after SCL rising edge (+1 stepsize settle) ----")
        g.d(SCL, N697, N666, SHREG0)
        g.s(2 * 20 - 2)  # rest of send_bit()'s 2*T hold
        g.note(f"---- bit {i}: end of hold ----")
        g.d(SHREG0)

    g.raw("")
    g.note("end of irsim_debug_n697.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_n697.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
