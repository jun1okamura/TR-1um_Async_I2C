#!/usr/bin/env python3
"""
gen_irsim_debug_addrmatch.py -- targeted diagnostic for the NEW discrepancy
found under TR-1um.prm + settle 50 (design_notes.md 76.33): after the WRITE
transaction's address byte (0xA0 = SLAVE_ADDR 0x50, W) is sent and ACKed,
irsim_test_main.cmd's existing single-shot check `d(ADDR_MATCH, RW)` (with
ZERO extra margin -- it fires immediately after read_ack() leaves SCL low,
at the exact same simulated instant) read ADDR_MATCH=0 instead of the
expected 1, and rx_data read back all-zero after the data byte too (real
run, TR-1um.prm, settle 50 in effect -- see the analyzer screenshot the
user flagged as "something's wrong").

Under scmos100.prm this exact same script position worked fine (design_notes.md
76.27, full WRITE+READ pass). The real TR-1um.prm's characterized resistances
are on the order of several kOhm (design_notes.md 76.29) -- plausibly slow
enough that some multi-gate-delay combinational path (e.g. an 8-bit address
comparator, or a shift-register enable chain) genuinely needs more real
elapsed time to settle than scmos100.prm's placeholder timing did, and the
existing script's per-bit margins (send_bit: 2*T=40ns hold after each SCL
edge) were empirically tuned against scmos100.prm all session -- never
against real TR-1um.prm timing.

This script distinguishes the two possible explanations by checking
ADDR_MATCH/RW/BUSY repeatedly at increasing time offsets (0, 100, 200, 500,
1000, 2000, 4000ns) after the SAME address-byte-ACK point where the
original check failed:
  - If it eventually reads ADDR_MATCH=1 -- pure timing-margin shortfall
    (the real .prm is just slower than scmos100.prm assumed -- fix: add
    margin to the .cmd generator's checks/hold times generally).
  - If it stays 0 at every checkpoint out to 4000ns -- a genuine
    structural/logic issue (comparable category to the $813-never-pulses
    finding earlier this session), needs deeper investigation.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_addrmatch.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import CmdGen, SLAVE_ADDR  # noqa: E402


def main():
    g = CmdGen()
    g.note("irsim_debug_addrmatch.cmd -- does ADDR_MATCH/RW ever resolve to")
    g.note("the correct value after the WRITE address byte's ACK, given more")
    g.note("real elapsed time, or does it stay stuck at 0 forever? See")
    g.note("design_notes.md 76.33 / script/gen_irsim_debug_addrmatch.py.")
    g.preamble()

    g.note("watch the whole transaction")
    from gen_irsim_cmd import SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH
    g.d(SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH)
    g.raw("ana " + " ".join([SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH]))
    g.raw("")

    g.note("==================== WRITE TRANSACTION (address byte only) ====================")
    g.start(first=True)
    addr_byte = (SLAVE_ADDR << 1) | 0
    g.note(f"ADDR+W = 0x{addr_byte:02X}")
    g.send_byte(addr_byte)
    g.read_ack("slave ACKed matching address (write); also check addr_match=1, rw=0")

    g.note("---- original (failing) check point: 0ns extra margin ----")
    g.d(ADDR_MATCH, RW, BUSY)

    checkpoints = [100, 200, 500, 1000, 2000, 4000]
    prev = 0
    for cp in checkpoints:
        g.s(cp - prev)
        prev = cp
        g.note(f"---- +{cp}ns after the address-byte ACK ----")
        g.d(ADDR_MATCH, RW, BUSY)

    g.raw("")
    g.note("end of irsim_debug_addrmatch.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_addrmatch.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
