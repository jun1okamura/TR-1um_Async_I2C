#!/usr/bin/env python3
"""
gen_irsim_debug_addrmatch2.py -- follow-up to the real irsim_test_main.cmd
run (design_notes.md 76.40): the WRITE transaction now passes completely
(addr_match=1, rw=0 after the address byte; rx_data=0xA5 exactly after the
data byte -- both confirmed on a real run). But at the START of the
following READ transaction, right after the SAME $28-group QS force/
release that correctly clears everything on cold start and mid-run for
`rw`, `addr_match` specifically reads back 1 (stale, leftover from the
WRITE match) instead of the expected 0 -- while `rw`, force/released via
the exact same mechanism in the exact same call, DOES correctly read 0.
The analyzer screenshot showed addr_match briefly glitch low (matching the
force) then immediately jump right back to 1 on release, rather than
holding 0 -- a "weak force loses to something else re-driving it"
signature, not a "force never took effect" one.

addr_match's own DFFRB is XN16 (confirmed in DFFRB_28_INSTANCES). Its D
input is XN3.N642 (netlist: X$16's D pin, XN3.N642 -- driven by two
inverter stages, XN3.XN17.N6 -> XN3.N642), and its clock is XN3.N635
(shared with several shreg bits and rx_data bits -- confirmed toggling in
sync with real SCL in 76.35). If N642 (the address-compare result feeding
addr_match's D) still reads "match" at the exact moment N635 clocks
during/after our force/release (e.g. because the compare logic hasn't
caught up with shreg's OWN concurrent force/release yet), a real capture
could re-latch the stale 1 right as we release the force -- this script
checks that theory directly by tracing addr_match's QS/D/CK together with
rw's own QS at single-stepsize resolution through the second start()'s
force/release, instead of only checking the end result.

This reuses the real, unmodified CmdGen primitives (preamble/start/
send_byte/read_ack/stop) for the WHOLE write transaction -- so this is
running the SAME real production sequence, not a simplified stand-in --
and only replaces the second start() call with a manually-unrolled,
finer-grained version for the specific moment of interest.

Run locally:
    cd irsim
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_addrmatch2.cmd
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_irsim_cmd import (  # noqa: E402
    CmdGen, SLAVE_ADDR, SCL, SDA, BUSY, RW, ADDR_MATCH,
    DFFRB_28_INSTANCES, dffrb_qs,
)

ADDR_MATCH_QS = dffrb_qs("XN16")
ADDR_MATCH_D = "XN3.N642"
ADDR_MATCH_CK = "XN3.N635"
RW_QS = dffrb_qs("XN2")


def main():
    g = CmdGen()
    g.note("irsim_debug_addrmatch2.cmd -- fine-grained trace of addr_match's")
    g.note("own QS/D/CK (XN16, D=N642, CK=N635) around the SECOND start()'s")
    g.note("$28-group force/release, to see whether the force never takes")
    g.note("effect, or takes effect then gets immediately re-driven back to")
    g.note("1 (e.g. by a real clock edge re-latching a stale compare result")
    g.note("before shreg's own concurrent force/release has caught up).")
    g.note("See design_notes.md 76.40/76.41. Runs the REAL, unmodified")
    g.note("WRITE transaction first (same primitives as irsim_test_main.cmd)")
    g.note("so the state going into the second start() is realistic.")
    g.preamble()

    g.d(SCL, SDA, BUSY, RW, ADDR_MATCH)
    g.raw("")

    g.note("==================== WRITE TRANSACTION (real, unmodified) ====================")
    g.start(first=True)
    addr_byte = (SLAVE_ADDR << 1) | 0
    g.send_byte(addr_byte)
    g.read_ack("address ack")
    g.d(ADDR_MATCH, RW)
    DATA_WR = 0xA5
    g.send_byte(DATA_WR)
    g.read_ack("data ack")
    g.stop("after write")
    g.note("check: after STOP settles, addr_match/rw BEFORE the next START")
    g.d(BUSY, RW, ADDR_MATCH)

    g.note("==================== READ TRANSACTION START (manually unrolled) ====================")
    g.h(SCL)
    g.x(SDA)
    g.s()
    g.l(SDA)          # START
    g.s(2 * 20)
    g.note("---- busy just reasserted ----")
    g.d(BUSY, ADDR_MATCH_QS, ADDR_MATCH_D, ADDR_MATCH_CK, RW_QS, ADDR_MATCH, RW)

    g.note("---- forcing $28-group QS=0 (all instances incl. addr_match's XN16) ----")
    setter_nodes = [dffrb_qs(i) for i in DFFRB_28_INSTANCES]
    for n in setter_nodes:
        g.l(n)
    g.s()
    g.note("---- forced, still held: addr_match's own QS/D/CK ----")
    g.d(ADDR_MATCH_QS, ADDR_MATCH_D, ADDR_MATCH_CK, RW_QS, ADDR_MATCH, RW)

    for n in setter_nodes:
        g.x(n)
    for i in range(10):
        g.s()
        g.note(f"---- +{(i + 1) * 20}ns after release ----")
        g.d(ADDR_MATCH_QS, ADDR_MATCH_D, ADDR_MATCH_CK, RW_QS, ADDR_MATCH, RW)

    g.raw("")
    g.note("end of irsim_debug_addrmatch2.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = main()
    outdir = pathlib.Path(__file__).resolve().parent.parent / "irsim"
    path = outdir / "irsim_debug_addrmatch2.cmd"
    path.write_text(txt)
    print(f"wrote {path}: {len(txt.splitlines())} lines")
