"""
gen_irsim_debug_phase.py -- one-off diagnostic, NOT part of the regular
gen_irsim_cmd.py pipeline.

irsim_test_main.cmd (even with start()'s new 8000ns settle) still shows
the 2nd (READ) transaction's address NACKed and rw stuck at 0. The RTL
(design_notes.md 76.22) says phase/bit_cnt/shreg/addr_ok/rw_bit are ONE
register bank, all reset by the same rst_scl_domain=$28(RSTB) net. rw and
addr_match (both $28-group DFFRBs) are already watched elsewhere; this
finds the OTHER 7 $28-group DFFRB instances (X$32/$46/$104/$111/$115/
$116/$117 -- their Q outputs have no literal net name in the extracted
netlist, unlike rw/addr_match/shreg[]/rx_data[]) and watches them
directly, on the theory that they are exactly "phase" (3 bits) + "bit_cnt"
(4 bits) = 7 bits. Watches them continuously through the 2nd START's
8000ns settle window and into the address-bit clocking, to see whether
they actually reset to 0 or stay stuck at their pre-STOP values.
"""
import sys
sys.path.insert(0, ".")
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, BUSY, T, RW, ADDR_MATCH, SCL, SDA

# Q outputs of the 7 unidentified $28-group DFFRB instances (X$32, $46,
# $104, $111, $115, $116, $117) -- sanitized ($->N), all top-level
# (i2c_slave_async_nrow_fm is XN3, but these nets have no further
# instance-path prefix since they're the core's own internal signals,
# same pattern as busy/rw/addr_match).
PHASE_BITCNT_NODES = ["XN3.N43", "XN3.N11", "XN3.N62", "XN3.N243",
                       "XN3.N358", "XN3.N137", "XN3.N349"]
RSTB28 = "XN3.N28"
CK34 = "XN3.N34"
CK343 = "XN3.N343"

g = CmdGen()
g.note("irsim_debug_phase.cmd -- do phase/bit_cnt bits actually reset on")
g.note("the 2nd START? Watching the 7 unidentified $28-group DFFRB")
g.note("outputs (theorized phase[2:0]+bit_cnt[3:0]) plus RSTB($28) and")
g.note("both clock nets ($34,$343) through the 2nd transaction's START")
g.note("and address-bit clocking. See design_notes.md 76.22/76.23.")
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

g.note("==================== READ TRANSACTION (watched closely) ====================")
g.note("---- pre-START, right after STOP ----")
g.d(*PHASE_BITCNT_NODES)
g.d(RSTB28, CK34, CK343, BUSY, RW, ADDR_MATCH)

g.note("---- START edge ----")
g.h(SCL)
g.x(SDA)
g.s()
g.l(SDA)
g.s(2 * T)
g.d(BUSY)
g.note("---- +0ns after START edge (before the 8000ns settle) ----")
g.d(*PHASE_BITCNT_NODES)
g.d(RSTB28)

checkpoints = [500, 1000, 2000, 4000, 8000]
prev = 0
for cp in checkpoints:
    g.s(cp - prev)
    prev = cp
    g.note(f"---- +{cp}ns after START edge ----")
    g.d(*PHASE_BITCNT_NODES)
    g.d(RSTB28)

g.note("---- now clock in the READ address byte (0xA1), watching every bit ----")
addr_byte_r = (SLAVE_ADDR << 1) | 1
for i in range(7, -1, -1):
    bitval = (addr_byte_r >> i) & 1
    g.send_bit(bitval)
    g.note(f"---- after address bit {i} (val={bitval}) ----")
    g.d(*PHASE_BITCNT_NODES)
g.read_ack("READ addr ACK")
g.d(RW, ADDR_MATCH)

g.raw("")
g.note("end of irsim_debug_phase.cmd")

with open("../irsim/irsim_debug_phase.cmd", "w") as f:
    f.write("\n".join(g.lines) + "\n")
print("wrote irsim_debug_phase.cmd:", len(g.lines), "lines")
