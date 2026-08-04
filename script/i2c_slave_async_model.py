"""
I2C slave - asynchronous (unclocked) logic model, written in MyHDL.

Design intent
--------------
This block has NO free-running system clock. Every state change is driven
directly by edges on the bus lines SCL/SDA themselves (self-timed / bus-timed
logic), mirroring how UM10204 defines the protocol:

  * 3.1.3 Data validity  -> SDA may change only while SCL is LOW; SDA must be
    stable while SCL is HIGH.
                                                => sample on posedge(scl),
                                                   drive  on negedge(scl)
  * 3.1.4 START/STOP     -> SDA falling/rising edge *while SCL is HIGH*
                             defines START / STOP.
                                                => negedge(sda)/posedge(sda),
                                                   qualified by scl == 1
  * 3.1.5 Byte format    -> 8 bits, MSB first, ACK/NACK bit follows each byte.
  * 3.1.6 ACK/NACK       -> receiver pulls SDA low during the 9th clock.
  * 3.1.9 Clock stretch  -> optional; this slave never drives SCL, so it is
                             not implemented (see design_notes.md).

There is deliberately no `clk` port anywhere in this design.
"""

from myhdl import Signal, intbv, always, always_comb, block


IDLE, ADDR, ADDR_ACK, DATA_WR, DATA_WR_ACK, DATA_RD, DATA_RD_ACK = range(7)

STATE_NAMES = ["IDLE", "ADDR", "ADDR_ACK", "DATA_WR", "DATA_WR_ACK",
               "DATA_RD", "DATA_RD_ACK"]


def _shift_in(reg, bit):
    return intbv((int(reg) << 1 | int(bit)) & 0xFF)[8:]


@block
def i2c_slave_async(rst_n, scl, sda_in, sda_oe,
                     tx_data, rx_data, rx_valid, addr_match, rw, busy,
                     slave_addr=0x50):
    """Asynchronous (bus-timed) I2C slave core.

    Ports
    -----
    rst_n      : async reset, active low
    scl        : bus SCL, already deglitched/level input
    sda_in     : sensed value of the (open-drain, externally pulled-up) SDA
    sda_oe     : 1 => this slave pulls SDA low; 0 => released (Hi-Z)
    tx_data    : byte to shift out to master on a read (app supplies it
                 before/at the start of the DATA_RD phase)
    rx_data    : last byte received from master
    rx_valid   : one bus-clock pulse (high for one SCL HIGH phase) when a
                 full data byte has been latched into rx_data
    addr_match : this slave was addressed in the current transaction
    rw         : 0 = master write (this slave receives), 1 = master read
    busy       : high from START until STOP
    """

    state = Signal(intbv(IDLE)[3:])
    bit_cnt = Signal(intbv(0)[4:])
    shreg = Signal(intbv(0)[8:])
    txreg = Signal(intbv(0)[8:])
    addr_ok = Signal(bool(0))
    rw_bit = Signal(bool(0))

    # ---- START / STOP detector --------------------------------------
    # Level/edge based only, independent of any clock. In a discrete-gate
    # realization this is the NAND-based SR latch of UM10204 Fig. 5,
    # gated by SCL sampling a SDA transition.
    @always(sda_in.negedge)
    def start_detect():
        if rst_n and scl:
            state.next = ADDR
            bit_cnt.next = 0
            busy.next = 1
            sda_oe.next = 0

    @always(sda_in.posedge)
    def stop_detect():
        if rst_n and scl:
            state.next = IDLE
            sda_oe.next = 0
            busy.next = 0

    # ---- Sample + state transition on SCL rising edge -----------------
    # (data is guaranteed stable while SCL=1, so this is where we both
    #  capture bits AND decide the next state/ack outcome)
    @always(scl.posedge)
    def sample():
        if not rst_n:
            return
        if state == ADDR:
            newsh = _shift_in(shreg, sda_in)
            shreg.next = newsh
            if bit_cnt == 7:
                addr_ok.next = (int(newsh[8:1]) == slave_addr)
                rw_bit.next = bool(newsh[0])
                state.next = ADDR_ACK
                bit_cnt.next = 0
            else:
                bit_cnt.next = bit_cnt + 1

        elif state == ADDR_ACK:
            if addr_ok:
                state.next = DATA_RD if rw_bit else DATA_WR
            else:
                state.next = IDLE
            bit_cnt.next = 0

        elif state == DATA_WR:
            newsh = _shift_in(shreg, sda_in)
            shreg.next = newsh
            if bit_cnt == 7:
                rx_data.next = newsh
                rx_valid.next = 1
                state.next = DATA_WR_ACK
                bit_cnt.next = 0
            else:
                bit_cnt.next = bit_cnt + 1

        elif state == DATA_WR_ACK:
            state.next = DATA_WR
            bit_cnt.next = 0

        elif state == DATA_RD:
            if bit_cnt == 7:
                state.next = DATA_RD_ACK
            bit_cnt.next = bit_cnt + 1

        elif state == DATA_RD_ACK:
            if sda_in == 0:            # master ACKed -> wants another byte
                state.next = DATA_RD
                bit_cnt.next = 0
            else:                      # master NACKed -> transfer ends
                state.next = IDLE

    # ---- Drive changes on SCL falling edge -----------------------------
    # (SDA may only move while SCL=0); output depends only on the state
    # already settled by the preceding posedge, so there is no race.
    @always(scl.negedge)
    def drive():
        if not rst_n:
            return
        rx_valid.next = 0
        if state == ADDR:
            sda_oe.next = 0
        elif state == ADDR_ACK:
            sda_oe.next = 1 if addr_ok else 0
        elif state == DATA_WR:
            sda_oe.next = 0
        elif state == DATA_WR_ACK:
            sda_oe.next = 1
        elif state == DATA_RD:
            if bit_cnt == 0:
                txreg.next = tx_data
                sda_oe.next = not tx_data[7]
            else:
                sda_oe.next = not txreg[7 - bit_cnt]
        elif state == DATA_RD_ACK:
            sda_oe.next = 0

    @always_comb
    def outputs():
        addr_match.next = addr_ok
        rw.next = rw_bit

    @always(rst_n.negedge)
    def areset():
        state.next = IDLE
        bit_cnt.next = 0
        sda_oe.next = 0
        busy.next = 0
        rx_valid.next = 0

    return start_detect, stop_detect, sample, drive, outputs, areset
