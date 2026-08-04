"""
MyHDL behavioral mirror of i2c_slave_async_v2.v (the gate-synthesizable
restructuring). Used to verify functional equivalence with the original
protocol behavior before committing the new architecture.

Structural elements from v2 are modeled behaviorally here:
  - DEL1        -> a small explicit delay on sda_in (sda_d)
  - NOR2 x2 SR  -> a single behavioral "busy" latch process
  - DFFR banks  -> ordinary MyHDL @always(scl.posedge / rst.posedge) blocks
"""

from myhdl import Signal, intbv, always, always_comb, instance, delay, block

PH_ADDR, PH_ADDR_ACK, PH_DATA_WR, PH_DATA_WR_ACK, PH_DATA_RD, PH_DATA_RD_ACK, PH_IGNORE = range(7)

DEL_UNIT = 1  # nominal DEL1 delay, must be << bit period used by the testbench


@block
def i2c_slave_async(rst_n, scl, sda_in, sda_oe,
                     tx_data, rx_data, rx_valid, addr_match, rw, busy,
                     slave_addr=0x50):

    sda_d = Signal(bool(1))
    start_pulse = Signal(bool(0))
    stop_pulse = Signal(bool(0))
    rst_scl_domain = Signal(bool(1))
    rst_sdaoe_domain = Signal(bool(1))

    phase = Signal(intbv(PH_ADDR)[3:])
    bit_cnt = Signal(intbv(0)[4:])
    shreg = Signal(intbv(0)[8:])
    addr_ok = Signal(bool(0))
    rw_bit = Signal(bool(0))
    rx_data_r = Signal(intbv(0)[8:])
    sda_oe_r = Signal(bool(0))
    txreg = Signal(intbv(0)[8:])

    # ---- DEL1 behavioral model ----
    @instance
    def del_sda():
        while True:
            yield sda_in
            yield delay(DEL_UNIT)
            sda_d.next = sda_in

    @always_comb
    def edge_detect():
        start_pulse.next = scl and sda_d and not sda_in
        stop_pulse.next = scl and (not sda_d) and sda_in

    # ---- NOR2 x2 SR latch (busy), modeled behaviorally ----
    @always(start_pulse, stop_pulse, rst_n)
    def busy_latch():
        if (not rst_n) or stop_pulse:
            busy.next = 0
        elif start_pulse:
            busy.next = 1

    @always_comb
    def rst_domains():
        rst_scl_domain.next = (not rst_n) or start_pulse
        rst_sdaoe_domain.next = (not rst_n) or (not busy)

    # ---- SCL(posedge) domain ----
    @always(scl.posedge, rst_scl_domain.posedge)
    def scl_domain():
        if rst_scl_domain:
            phase.next = PH_ADDR
            bit_cnt.next = 0
            shreg.next = 0
            addr_ok.next = 0
            rw_bit.next = 0
            rx_data_r.next = 0
        else:
            shreg_next = intbv((int(shreg) << 1 | int(sda_in)) & 0xFF)[8:]
            shreg.next = shreg_next
            if phase == PH_ADDR:
                if bit_cnt == 7:
                    addr_ok.next = (int(shreg_next[8:1]) == slave_addr)
                    rw_bit.next = bool(shreg_next[0])
                    phase.next = PH_ADDR_ACK
                    bit_cnt.next = 0
                else:
                    bit_cnt.next = bit_cnt + 1
            elif phase == PH_ADDR_ACK:
                if addr_ok:
                    phase.next = PH_DATA_RD if rw_bit else PH_DATA_WR
                else:
                    phase.next = PH_IGNORE
                bit_cnt.next = 0
            elif phase == PH_DATA_WR:
                if bit_cnt == 7:
                    rx_data_r.next = shreg_next
                    phase.next = PH_DATA_WR_ACK
                    bit_cnt.next = 0
                else:
                    bit_cnt.next = bit_cnt + 1
            elif phase == PH_DATA_WR_ACK:
                phase.next = PH_DATA_WR
                bit_cnt.next = 0
            elif phase == PH_DATA_RD:
                if bit_cnt == 7:
                    phase.next = PH_DATA_RD_ACK
                bit_cnt.next = bit_cnt + 1
            elif phase == PH_DATA_RD_ACK:
                if sda_in == 0:
                    phase.next = PH_DATA_RD
                    bit_cnt.next = 0
                else:
                    phase.next = PH_IGNORE
            else:
                phase.next = PH_IGNORE

    @always_comb
    def outputs():
        addr_match.next = addr_ok
        rw.next = rw_bit
        rx_data.next = rx_data_r
        rx_valid.next = (phase == PH_DATA_WR_ACK)

    # ---- SCL(negedge) domain ----
    scl_n = Signal(bool(0))

    @always_comb
    def inv_scl():
        scl_n.next = not scl

    @always(scl_n.posedge, rst_sdaoe_domain.posedge)
    def sdaoe_domain():
        if rst_sdaoe_domain:
            sda_oe_r.next = 0
            txreg.next = 0
        else:
            if phase == PH_ADDR_ACK:
                sda_oe_r.next = addr_ok
            elif phase == PH_DATA_WR_ACK:
                sda_oe_r.next = 1
            elif phase == PH_DATA_RD:
                if bit_cnt == 0:
                    txreg.next = tx_data
                    sda_oe_r.next = not tx_data[7]
                else:
                    sda_oe_r.next = not txreg[7 - int(bit_cnt)]
            else:
                sda_oe_r.next = 0

    @always_comb
    def sda_oe_out():
        sda_oe.next = sda_oe_r

    return (del_sda, edge_detect, busy_latch, rst_domains, scl_domain,
            outputs, inv_scl, sdaoe_domain, sda_oe_out)
