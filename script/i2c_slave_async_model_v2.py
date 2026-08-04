"""
Second MyHDL model, structured as a literal 1:1 mirror of the single-process
shadow-register style used in the delivered i2c_slave_async.v (one always
block, sensitive to level changes of scl/sda_in, no multiple-driver issue).

Run through the SAME testbench as i2c_slave_async_model.py to cross-check
that consolidating the FSM into one process did not change behavior.
"""

from myhdl import Signal, intbv, always, always_comb, block

IDLE, ADDR, ADDR_ACK, DATA_WR, DATA_WR_ACK, DATA_RD, DATA_RD_ACK = range(7)


@block
def i2c_slave_async(rst_n, scl, sda_in, sda_oe,
                     tx_data, rx_data, rx_valid, addr_match, rw, busy,
                     slave_addr=0x50):

    state = Signal(intbv(IDLE)[3:])
    bit_cnt = Signal(intbv(0)[4:])
    shreg = Signal(intbv(0)[8:])
    txreg = Signal(intbv(0)[8:])
    addr_ok = Signal(bool(0))
    rw_bit = Signal(bool(0))
    scl_q = Signal(bool(1))
    sda_q = Signal(bool(1))

    @always(scl, sda_in, rst_n.negedge)
    def proc():
        if not rst_n:
            state.next = IDLE
            bit_cnt.next = 0
            sda_oe.next = 0
            busy.next = 0
            rx_valid.next = 0
            scl_q.next = 1
            sda_q.next = 1
            return

        rx_valid.next = 0

        start_cond = bool(scl_q) and bool(scl) and bool(sda_q) and not sda_in
        stop_cond = bool(scl_q) and bool(scl) and not sda_q and bool(sda_in)
        scl_rise = (not scl_q) and bool(scl)
        scl_fall = bool(scl_q) and (not scl)

        if start_cond:
            state.next = ADDR
            bit_cnt.next = 0
            busy.next = 1
            sda_oe.next = 0

        elif stop_cond:
            state.next = IDLE
            sda_oe.next = 0
            busy.next = 0

        elif scl_rise:
            shreg_next = intbv((int(shreg) << 1 | int(sda_in)) & 0xFF)[8:]
            if state == ADDR:
                shreg.next = shreg_next
                if bit_cnt == 7:
                    addr_ok.next = (int(shreg_next[8:1]) == slave_addr)
                    rw_bit.next = bool(shreg_next[0])
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
                shreg.next = shreg_next
                if bit_cnt == 7:
                    rx_data.next = shreg_next
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
                if sda_in == 0:
                    state.next = DATA_RD
                    bit_cnt.next = 0
                else:
                    state.next = IDLE

        elif scl_fall:
            if state == ADDR:
                sda_oe.next = 0
            elif state == ADDR_ACK:
                sda_oe.next = addr_ok
            elif state == DATA_WR:
                sda_oe.next = 0
            elif state == DATA_WR_ACK:
                sda_oe.next = 1
            elif state == DATA_RD:
                if bit_cnt == 0:
                    txreg.next = tx_data
                    sda_oe.next = not tx_data[7]
                else:
                    sda_oe.next = not txreg[7 - int(bit_cnt)]
            elif state == DATA_RD_ACK:
                sda_oe.next = 0

        scl_q.next = scl
        sda_q.next = sda_in

    @always_comb
    def outputs():
        addr_match.next = addr_ok
        rw.next = rw_bit

    return proc, outputs
