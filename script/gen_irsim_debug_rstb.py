"""
gen_irsim_debug_rstb.py -- one-off diagnostic, NOT part of the regular
gen_irsim_cmd.py pipeline.

irsim_debug_phase.cmd showed phase/bit_cnt candidate bits (N43/N11/N62/
N243/N358/N137/N349) and RSTB (N28) completely unchanged across the whole
8000ns settle window after the 2nd START, even though busy's SET path
(N695/N696) fired correctly (busy=1 confirmed right after START). $28
(RSTB, active low, clears the phase/bit_cnt/shreg/addr_ok/rw_bit bank) is
driven by NOR2($813, $702); $813=NOR2($697,$703) is the gate-level
start-pulse-equivalent. This watches N813/N697/N703/N704/N28 at FINE
(one-stepsize) granularity for 500ns immediately around the 2nd START
edge, to see whether $813 pulses at all (vs. busy's separate N695/N696
path, already confirmed working).
"""
import sys
sys.path.insert(0, ".")
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, BUSY, T, RW, ADDR_MATCH, SCL, SDA

WATCH = ["XN3.N813", "XN3.N697", "XN3.N703", "XN3.N704", "XN3.N28",
         "XN3.N695", "XN3.N696"]

g = CmdGen()
g.note("irsim_debug_rstb.cmd -- does $813 (RSTB's start-pulse input) ever")
g.note("pulse on the 2nd START, at fine (one-stepsize) granularity? busy's")
g.note("SEPARATE start-detect path (N695/N696) already confirmed working.")
g.note("See design_notes.md 76.22/76.23.")
g.preamble()

g.note("==================== WRITE TRANSACTION ====================")
g.start(first=True)
addr_byte = (SLAVE_ADDR << 1) | 0
g.send_byte(addr_byte)
g.read_ack("addr ACK")
DATA_WR = 0xA5
g.send_byte(DATA_WR)
g.read_ack("data ACK")
g.stop("after write")

g.note("==================== 2nd START, watched at fine granularity ====================")
g.d(*WATCH)
g.h(SCL)
g.x(SDA)
g.s()
g.note("---- SDA released, before falling edge ----")
g.d(*WATCH)
g.l(SDA)   # the START edge itself
for i in range(25):
    g.s()  # one stepsize (T=20ns) at a time
    g.note(f"---- +{(i+1)*T}ns after START edge ----")
    g.d(*WATCH)

g.raw("")
g.note("end of irsim_debug_rstb.cmd")

with open("../irsim/irsim_debug_rstb.cmd", "w") as f:
    f.write("\n".join(g.lines) + "\n")
print("wrote irsim_debug_rstb.cmd:", len(g.lines), "lines")
