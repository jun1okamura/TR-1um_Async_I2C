"""
gen_irsim_debug_read_addr.py

One-off diagnostic (design_notes.md 91.x): both irsim_test_main.cmd
(group_a_mode="gated") and irsim_test_main_noforce.cmd
(group_a_mode="none") show the IDENTICAL failure on the 2nd (READ)
START -- no ACK, rw stuck at 0 -- which rules out the DFFRB QS-forcing
strategy as the cause (see design_notes.md 90/91). This script builds a
version of the same WRITE-then-READ sequence that, instead of only
dumping the final addr_match/rw/ACK result, dumps the actual internal
register-bank state (bit_cnt[0..2], phase[0..2], shreg[0..6], the
Group-A reset net "_008_", and "start_pulse" itself) after EVERY bit of
the 2nd address byte, so the point where the 2nd START's dynamics
diverge from the (known-good) 1st START's can be seen directly, instead
of only the end result.

Reuses CmdGen/constants from gen_irsim_cmd_v9.py unchanged.
"""
import sys
sys.path.insert(0, ".")
from gen_irsim_cmd_v9 import (
    CmdGen, VDD, GND, RST_N, SCL, SDA, SDA_OE, DIS, TX, RX,
    BUSY, RW, ADDR_MATCH, SLAVE_ADDR, T, SDA_RELEASE_SETTLE_NS,
)

# Internal core registers of interest, all plain internal nets of
# i2c_slave_async_nrow_fm (x2 at the top level) -- flattened names
# confirmed by the same positional-grep method as design_notes.md 88.1.
BIT_CNT = ["x2.bit_cnt[0]", "x2.bit_cnt[1]", "x2.bit_cnt[2]"]
PHASE = ["x2.phase[0]", "x2.phase[1]", "x2.phase[2]"]
SHREG = [f"x2.shreg[{i}]" for i in range(7)]
RSTB28_NET = "x2._008_"     # Group-A's own gate-level reset net
START_PULSE = "x2.start_pulse"


def gen():
    g = CmdGen()
    g.note("irsim_debug_read_addr.cmd -- diagnostic (design_notes.md 91.x):")
    g.note("dumps bit_cnt/phase/shreg/RSTB28/start_pulse after every bit of")
    g.note("the 2ND START's address byte, to see where the (broken) READ")
    g.note("transaction's address phase diverges from the (working) WRITE")
    g.note("transaction's. group_a_mode=\"gated\" here (same as baseline --")
    g.note("the \"none\" experiment showed identical failure either way).")
    g.preamble()

    g.d(SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH)
    g.raw("ana " + " ".join([SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH]))
    g.raw("")

    def dbg(label):
        g.note(f"---- debug snapshot: {label} ----")
        g.d(*BIT_CNT, *PHASE, RSTB28_NET, START_PULSE)
        g.d(*SHREG)
        g.d(ADDR_MATCH, RW, BUSY)

    g.note("==================== WRITE TRANSACTION (known-good baseline) ====================")
    g.start(first=True)
    dbg("right after 1st START's Group-A reset")
    addr_byte = (SLAVE_ADDR << 1) | 0
    g.note(f"ADDR+W = 0x{addr_byte:02X}")
    for i in range(7, -1, -1):
        g.send_bit((addr_byte >> i) & 1)
        dbg(f"after WRITE addr bit {i} (value={(addr_byte >> i) & 1})")
    g.read_ack("slave ACKed matching address (write)")
    dbg("after WRITE address ACK")

    DATA_WR = 0xA5
    g.send_byte(DATA_WR)
    g.read_ack("slave ACKed data byte")
    g.d(*RX)
    g.stop("after write")
    dbg("after STOP (write)")

    g.note("==================== READ TRANSACTION (broken) ====================")
    DATA_RD = 0x3C
    for i in range(8):
        bit = (DATA_RD >> i) & 1
        (g.h if bit else g.l)(TX[i])
    g.s(2 * T)

    g.start(group_a_mode="gated")
    dbg("right after 2nd START's Group-A reset (BEFORE any addr bits)")
    addr_byte = (SLAVE_ADDR << 1) | 1
    g.note(f"ADDR+R = 0x{addr_byte:02X}")
    for i in range(7, -1, -1):
        g.send_bit((addr_byte >> i) & 1)
        dbg(f"after READ addr bit {i} (value={(addr_byte >> i) & 1})")
    g.l(SCL)
    g.x(SDA)
    g.s(SDA_RELEASE_SETTLE_NS)
    g.h(SCL)
    g.s()
    g.note("check: ACK? (SDA low = ACK, high = NACK -- expect ACK, real run found NACK)")
    g.d(SDA)
    dbg("after READ address ACK window")
    g.s()
    g.l(SCL)

    g.raw("")
    g.note("end of irsim_debug_read_addr.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    txt = gen()
    with open("../irsim/irsim_debug_read_addr.cmd", "w") as f:
        f.write(txt)
    print("wrote irsim_debug_read_addr.cmd:", len(txt.splitlines()), "lines")
