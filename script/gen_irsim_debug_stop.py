"""
gen_irsim_debug_stop.py -- one-off diagnostic, NOT part of the regular
gen_irsim_cmd.py pipeline.

irsim_test_main.cmd's real-hardware run showed two problems after the
WRITE transaction's STOP condition:
  - busy stayed 1 (expected 0/cleared) only 2*T=40ns after STOP
  - the subsequent READ transaction's rw stayed 0 (expected 1), and all
    8 read-data bits came back as 1 (not matching the preloaded
    tx_data=0x3C=00111100b) -- consistent with the core still thinking
    it's mid-transaction and never actually driving read data.

This reuses gen_irsim_cmd.py's CmdGen/preamble()/start()/send_byte()/
read_ack()/stop() building blocks to replay the exact same WRITE
transaction, then instead of immediately starting the READ transaction,
holds and checks busy at several checkpoints (100/500/1000/3000/8000ns
after STOP) to see whether it's a genuine stuck bug or just needs more
settling time than the arbitrary T=20ns stepsize provides.
"""
import sys
sys.path.insert(0, ".")
from gen_irsim_cmd import CmdGen, SLAVE_ADDR, BUSY, T

g = CmdGen()
g.note("irsim_debug_stop.cmd -- does busy ever clear after WRITE's STOP?")
g.note("irsim_test_main.cmd showed busy=1 still 40ns after STOP, and the")
g.note("following READ transaction's rw stayed 0 / all read bits came back 1")
g.note("-- checking whether busy just needs more settling time.")
g.preamble()
g.d(BUSY)

g.note("==================== WRITE TRANSACTION ====================")
g.start(first=True)
addr_byte = (SLAVE_ADDR << 1) | 0
g.send_byte(addr_byte)
g.read_ack("addr ACK")
DATA_WR = 0xA5
g.send_byte(DATA_WR)
g.read_ack("data ACK")
g.stop("after write (immediate check)")

checkpoints = [100, 500, 1000, 3000, 8000]
prev = 2 * T  # stop() already waited 2*T before its own d(BUSY)
for cp in checkpoints:
    g.s(cp - prev)
    prev = cp
    g.note(f"---- t=+{cp}ns since STOP ----")
    g.d(BUSY)

g.raw("")
g.note("end of irsim_debug_stop.cmd")

with open("../irsim/irsim_debug_stop.cmd", "w") as f:
    f.write("\n".join(g.lines) + "\n")
print("wrote irsim_debug_stop.cmd:", len(g.lines), "lines")
