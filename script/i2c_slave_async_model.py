"""
I2C slave - asynchronous (unclocked) logic model, written in MyHDL.

v3 (2026-08-28): rewritten to directly mirror src/i2c_slave_async.v's
actual v2/v3 architecture -- DEL1 delay-line + NOR2 cross-coupled SR latch
for unclocked START/STOP detection, phase/bit_walk (walking-one) FSM,
active-low sda_oe. This file previously modeled a structurally different
(older, pre-v2) architecture: separate IDLE/ADDR/... states with dedicated
sda_in.negedge/.posedge always-blocks for START/STOP, and a binary bit_cnt
counter. That mismatch was found during the V8 RTL rework (design_notes.md
section 77.7) -- this model had silently drifted out of sync with the RTL
it was supposed to verify, well before v3. Rewriting it as a close
transliteration of the RTL (rather than an independent behavioral
description) is the deliberate choice here: the whole point of this
regression is to catch RTL bugs, which an independently-diverged model
cannot reliably do.

v4 (this session, design_notes.md section 77.24): mirrors the RTL's
replacement of bit_walk (8bit walking-one) with bit_cnt (3bit binary) +
last_bit_pending (1bit, 1-edge-early registered "next edge is the last
bit" flag) -- same same-edge-race fix, much cheaper in DFF count. See
src/i2c_slave_async.v's header for the full rationale.

Design intent (unchanged from the RTL header, src/i2c_slave_async.v)
----------------------------------------------------------------------
This block has NO free-running system clock. Every state change is driven
directly by edges on the bus lines SCL/SDA themselves (self-timed / bus-timed
logic), mirroring how UM10204 defines the protocol:

  * 3.1.3 Data validity  -> SDA may change only while SCL is LOW; SDA must be
    stable while SCL is HIGH.
                                                => sample on posedge(scl),
                                                   drive  on negedge(scl)
  * 3.1.4 START/STOP     -> SDA falling/rising edge *while SCL is HIGH*
                             defines START / STOP. Modeled here with a
                             behavioral delay line (del1, DEL1_NS) standing
                             in for the RTL's DEL1 gate + combinational
                             edge detector, not a MyHDL sda_in.negedge/
                             posedge always-block (see design_notes.md
                             section 77.7).
  * 3.1.5 Byte format    -> 8 bits, MSB first, ACK/NACK bit follows each byte.
  * 3.1.6 ACK/NACK       -> receiver pulls SDA low during the 9th clock.
  * 3.1.9 Clock stretch  -> optional; this slave never drives SCL, so it is
                             not implemented (see design_notes.md).

sda_oe polarity (v3): 0 = drive SDA low, 1 = release (Hi-Z) -- active-low,
matching the SDA pad's HIZ13 pin directly (design_notes.md section 77.3).
This is the OPPOSITE of what this file used before v3.

There is deliberately no `clk` port anywhere in this design.
"""

from myhdl import Signal, intbv, always, always_comb, instance, delay, block


PH_ADDR, PH_ADDR_ACK, PH_DATA_WR, PH_DATA_WR_ACK, PH_DATA_RD, PH_DATA_RD_ACK, PH_IGNORE = range(7)

STATE_NAMES = ["PH_ADDR", "PH_ADDR_ACK", "PH_DATA_WR", "PH_DATA_WR_ACK",
               "PH_DATA_RD", "PH_DATA_RD_ACK", "PH_IGNORE"]

DEL1_NS = 1   # behavioral stand-in for the DEL1 gate's propagation delay


def _shift_in(reg, bit):
    return intbv((int(reg) << 1 | int(bit)) & 0xFF)[8:]


@block
def i2c_slave_async(rst_n, scl, sda_in, sda_oe,
                     tx_data, rx_data, rx_valid, addr_match, rw, busy,
                     slave_addr=0x50):
    """Asynchronous (bus-timed) I2C slave core -- MyHDL twin of
    src/i2c_slave_async.v (v3).

    Ports
    -----
    rst_n      : async reset, active low
    scl        : bus SCL, already deglitched/level input
    sda_in     : sensed value of the (open-drain, externally pulled-up) SDA
    sda_oe     : v3, ACTIVE-LOW: 0 => this slave pulls SDA low;
                 1 => released (Hi-Z). Matches SDA pad HIZ13 directly.
    tx_data    : byte to shift out to master on a read (app supplies it
                 before/at the start of the DATA_RD phase)
    rx_data    : last byte received from master
    rx_valid   : high while phase == PH_DATA_WR_ACK
    addr_match : this slave was addressed in the current transaction
    rw         : 0 = master write (this slave receives), 1 = master read
    busy       : high from START until STOP
    """

    # ---- SCL(posedge)-domain state: phase/bit_cnt/shreg/addr/rw ---------
    phase = Signal(intbv(PH_ADDR)[3:])
    # v4: plain 3bit binary counter again, plus last_bit_pending (1bit,
    # registered one edge early from bit_cnt==6's pre-edge value) --
    # replaces v3's 8bit walking-one bit_walk. See i2c_slave_async.v's
    # header (v4) for the full rationale.
    bit_cnt = Signal(intbv(0)[3:])
    last_bit_pending = Signal(bool(0))
    shreg = Signal(intbv(0)[8:])
    addr_ok = Signal(bool(0))
    rw_bit = Signal(bool(0))
    rx_data_r = Signal(intbv(0)[8:])

    # ---- SCL(negedge)-domain state: sda_oe/txreg -------------------------
    sda_oe_r = Signal(bool(0))   # internal sense: 1 = drive low (flipped
                                  # to active-low only at the sda_oe output
                                  # port, exactly like the RTL, v3 section 77.3)
    txreg = Signal(intbv(0)[8:])

    # ---- START/STOP edge detector: behavioral DEL1 delay line -----------
    sda_d = Signal(bool(1))
    start_pulse = Signal(bool(0))
    stop_pulse = Signal(bool(0))
    busy_clr = Signal(bool(0))
    rst_scl_domain = Signal(bool(0))
    rst_sdaoe_domain = Signal(bool(0))
    scl_n = Signal(bool(0))

    @instance
    def del1():
        while True:
            yield sda_in
            yield delay(DEL1_NS)
            sda_d.next = sda_in

    @always_comb
    def edge_detect():
        sp = bool(scl) and bool(sda_d) and not bool(sda_in)   # SDA 1->0 while SCL=1
        stp = bool(scl) and not bool(sda_d) and bool(sda_in)  # SDA 0->1 while SCL=1
        start_pulse.next = sp
        stop_pulse.next = stp
        busy_clr.next = stp or (not rst_n)
        rst_scl_domain.next = (not rst_n) or sp
        rst_sdaoe_domain.next = (not rst_n) or (not busy)
        scl_n.next = not scl

    # ---- busy: NOR2 cross-coupled SR latch (SET by start_pulse, CLEARed
    # by stop_pulse/reset) -- modeled as an edge-triggered SET/CLEAR with
    # CLEAR priority, the same simplification the pre-v3 model already
    # used successfully for its own start/stop handling. ------------------
    @always(busy_clr.posedge, start_pulse.posedge)
    def busy_latch():
        if busy_clr:
            busy.next = 0
        elif start_pulse:
            busy.next = 1

    @always(scl.posedge, rst_scl_domain.posedge)
    def fsm():
        if rst_scl_domain:
            phase.next = PH_ADDR
            bit_cnt.next = 0
            last_bit_pending.next = 0
            shreg.next = 0
            addr_ok.next = 0
            rw_bit.next = 0
            rx_data_r.next = 0
        else:
            shreg_next = _shift_in(shreg, sda_in)
            shreg.next = shreg_next
            is_last_bit = bool(last_bit_pending)
            # Precompute next edge's is_last_bit from bit_cnt's current
            # (pre-edge, stable) value -- ordinary D-input logic, no race
            # with bit_cnt's own simultaneous update below (mirrors the
            # RTL exactly, v4, design_notes.md section 77.24).
            last_bit_pending.next = (bit_cnt == 6)
            if phase == PH_ADDR:
                if is_last_bit:
                    addr_ok.next = (int(shreg_next[8:1]) == slave_addr)
                    rw_bit.next = bool(shreg_next[0])
                    phase.next = PH_ADDR_ACK
                    bit_cnt.next = 0
                else:
                    bit_cnt.next = bit_cnt + 1
            elif phase == PH_ADDR_ACK:
                phase.next = (PH_DATA_RD if rw_bit else PH_DATA_WR) if addr_ok else PH_IGNORE
                bit_cnt.next = 0
            elif phase == PH_DATA_WR:
                if is_last_bit:
                    rx_data_r.next = shreg_next
                    phase.next = PH_DATA_WR_ACK
                    bit_cnt.next = 0
                else:
                    bit_cnt.next = bit_cnt + 1
            elif phase == PH_DATA_WR_ACK:
                phase.next = PH_DATA_WR
                bit_cnt.next = 0
            elif phase == PH_DATA_RD:
                if is_last_bit:
                    phase.next = PH_DATA_RD_ACK
                # RTL's 3bit bit_cnt silently wraps 7+1->0 (Verilog fixed-
                # width arithmetic); MyHDL's intbv enforces strict bounds,
                # so this must be masked explicitly to match hardware
                # truncation semantics (unconditional per-edge increment,
                # same as bit_walk's unconditional shift in this phase --
                # the transition already fires above via is_last_bit, this
                # wrapped value is simply discarded on the next phase
                # entry's bit_cnt<=0).
                bit_cnt.next = (bit_cnt + 1) & 0x7
            elif phase == PH_DATA_RD_ACK:
                phase.next = PH_DATA_RD if sda_in == 0 else PH_IGNORE
                bit_cnt.next = 0
            else:
                phase.next = PH_IGNORE

    @always_comb
    def outputs():
        addr_match.next = addr_ok
        rw.next = rw_bit
        rx_data.next = rx_data_r
        rx_valid.next = (phase == PH_DATA_WR_ACK)

    # bit_cnt/phase read here are a genuine cross-domain (posedge-clocked
    # register read from a negedge-triggered block) combinational read --
    # exactly as in the RTL (design_notes.md section 77.7). v4: back to
    # bit_cnt==0 / txreg[7-bit_cnt] (the original v2 mechanism) since
    # bit_walk's one-hot AND-OR select no longer exists (section 77.24).
    @always(scl_n.posedge, rst_sdaoe_domain.posedge)
    def sda_oe_gen():
        if rst_sdaoe_domain:
            sda_oe_r.next = False
            txreg.next = 0
        else:
            if phase == PH_ADDR_ACK:
                sda_oe_r.next = bool(addr_ok)
            elif phase == PH_DATA_WR_ACK:
                sda_oe_r.next = True
            elif phase == PH_DATA_RD:
                if bit_cnt == 0:
                    txreg.next = tx_data
                    sda_oe_r.next = not bool(tx_data[7])
                else:
                    sda_oe_r.next = not bool(txreg[7 - int(bit_cnt)])
            else:
                sda_oe_r.next = False

    @always_comb
    def sda_oe_out():
        sda_oe.next = not sda_oe_r

    return (del1, edge_detect, busy_latch, fsm, outputs, sda_oe_gen, sda_oe_out)
