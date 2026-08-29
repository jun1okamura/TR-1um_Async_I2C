"""
gen_irsim_debug_dffrb2.py -- one-off diagnostic, NOT part of the regular
gen_irsim_cmd.py pipeline.

irsim_reset_check.cmd under the new real TR-1um.prm (design_notes.md
76.29) showed a REGRESSION vs the scmos100.prm placeholder: N58/N45/busy
resolve to defined values fine (even before the $28-group QS force/
release runs), but rw/addr_match are STILL X at the check right after
the $28-group QS force/release (t=8160ns, ~160ns after rst_n released,
~120ns after the QS force/release completed) -- the exact same margin
that worked fine under scmos100.prm.

This watches rw's own DFFRB (instance XN2, per DFFRB_28_INSTANCES) at
FINE (one-stepsize) granularity right around and after its QS force/
release, to see exactly where the chain breaks under the real .prm:
does QS itself fail to hold the forced value? Does QB (N4, its inverter)
fail to follow QS? Does rw (Q, a further inverter of QB) fail to follow
QB? This directly extends the same technique used successfully in
irsim_debug_dffrb.cmd (design_notes.md 76.13), just re-run under the new
TR-1um.prm and at finer time resolution after release.

IMPORTANT: run this with the REAL prm, not the placeholder:
    irsim TR-1um.prm tr_1um_i2c_slave_async.sim
    irsim> @ irsim_debug_dffrb2.cmd
"""
import sys
sys.path.insert(0, ".")
from gen_irsim_cmd import (CmdGen, T, DIS, SDA, SCL, RST_N, SDA_OE, BUSY, RW,
                            ADDR_MATCH, TX, dffrb_qs, DFFRB_28_INSTANCES)

QS_RW = dffrb_qs("XN2")   # rw's own DFFRB
QB_RW = "XN3.N4"          # rw's DFFRB's QB node (per irsim_debug_dffrb.cmd)

g = CmdGen()
g.note("irsim_debug_dffrb2.cmd -- fine-grained trace of rw's DFFRB (QS/QB/Q)")
g.note("around its $28-group force/release, under the REAL TR-1um.prm. See")
g.note("design_notes.md 76.29/76.30.")
g.raw(f"stepsize {T}")
g.h("Vdd")
g.l("Gnd")
g.x(SDA)
g.h(SCL)
g.h(DIS)
for t in TX:
    g.l(t)
g.l(RST_N)
g.s(3000)
g.note("---- t=3000ns, still in reset ----")
g.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH, QS_RW, QB_RW)
g.s(5000)
g.note("---- t=8000ns, still in reset ----")
g.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH, QS_RW, QB_RW)
g.h(RST_N)
g.s()
g.note("---- rst_n released, +1 stepsize, BEFORE QS force/release ----")
g.d(RST_N, "XN3.N28", QS_RW, QB_RW, RW, ADDR_MATCH)

g.note("---- forcing QS=0 for all $28-group instances ----")
for inst in DFFRB_28_INSTANCES:
    g.l(dffrb_qs(inst))
g.s()
g.note("---- QS forced, before release ----")
g.d(QS_RW, QB_RW, RW)
for inst in DFFRB_28_INSTANCES:
    g.x(dffrb_qs(inst))

for i in range(20):
    g.s()
    g.note(f"---- +{(i + 1) * T}ns after QS release ----")
    g.d(QS_RW, QB_RW, RW, ADDR_MATCH)

g.raw("")
g.note("end of irsim_debug_dffrb2.cmd")

with open("../irsim/irsim_debug_dffrb2.cmd", "w") as f:
    f.write("\n".join(g.lines) + "\n")
print("wrote irsim_debug_dffrb2.cmd:", len(g.lines), "lines")
