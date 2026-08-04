"""
Functional verification of i2c_slave_async using MyHDL's own event-driven
simulator (no external Verilog simulator available in this sandbox).

A minimal bus-functional master model drives SCL/SDA exactly like a real
I2C master (open-drain wired-AND on SDA) and runs:
  1. write transaction  : S, ADDR+W, ACK, DATA=0xA5, ACK, P
  2. read transaction    : S, ADDR+R, ACK, DATA (slave drives 0x3C), NACK, P
and self-checks addressing, ack/nack and byte values against UM10204
3.1.4-3.1.6.
"""

from myhdl import (Signal, intbv, delay, instance, block, Simulation,
                    traceSignals, StopSimulation, now)

from i2c_slave_async_model_v2 import i2c_slave_async

SLAVE_ADDR = 0x50
T = 20          # half-bit-period-ish time unit (ns), value is irrelevant
                # for an async design - correctness must not depend on it.

errors = []


def check(cond, msg):
    if not cond:
        errors.append(f"[t={now()}] FAIL: {msg}")
    else:
        print(f"[t={now()}] OK: {msg}")


@block
def testbench():
    rst_n = Signal(bool(1))
    scl = Signal(bool(1))
    sda_master_oe = Signal(bool(0))   # master pulls SDA low when 1
    sda_slave_oe = Signal(bool(0))    # slave pulls SDA low when 1
    sda_line = Signal(bool(1))        # resolved open-drain bus value

    tx_data = Signal(intbv(0)[8:])
    rx_data = Signal(intbv(0)[8:])
    rx_valid = Signal(bool(0))
    addr_match = Signal(bool(0))
    rw = Signal(bool(0))
    busy = Signal(bool(0))

    dut = i2c_slave_async(rst_n, scl, sda_line, sda_slave_oe,
                           tx_data, rx_data, rx_valid, addr_match, rw, busy,
                           slave_addr=SLAVE_ADDR)

    @instance
    def bus_model():
        # open-drain wired-AND: line is LOW if either side pulls it low
        while True:
            yield sda_master_oe, sda_slave_oe
            sda_line.next = not (sda_master_oe or sda_slave_oe)

    def send_bit(bitval):
        yield delay(T)
        scl.next = 0
        sda_master_oe.next = 0 if bitval else 1   # oe=1 => drive 0
        yield delay(T)
        scl.next = 1
        yield delay(2 * T)

    def recv_bit():
        yield delay(T)
        scl.next = 0
        sda_master_oe.next = 0    # release, let slave (or pull-up) drive
        yield delay(T)
        scl.next = 1
        yield delay(T)
        bit = 1 if sda_line else 0
        yield delay(T)
        return bit

    def send_ack(ack):
        # master, as receiver, drives ack(0)/nack(1)
        yield delay(T)
        scl.next = 0
        sda_master_oe.next = 1 if ack == 0 else 0
        yield delay(T)
        scl.next = 1
        yield delay(2 * T)
        scl.next = 0
        sda_master_oe.next = 0

    def send_byte(byte):
        for i in range(7, -1, -1):
            yield from send_bit((byte >> i) & 1)

    @instance
    def master():
        yield delay(5 * T)

        # ---------------- START -----------------
        scl.next = 1
        sda_master_oe.next = 0
        yield delay(T)
        sda_master_oe.next = 1          # SDA 1->0 while SCL=1 : START
        yield delay(2 * T)
        check(bool(busy), "busy asserted after START")

        # ---------------- ADDR + W(0) ------------
        addr_byte = (SLAVE_ADDR << 1) | 0
        yield from send_byte(addr_byte)

        # ---------------- read ACK from slave -----
        scl.next = 0
        sda_master_oe.next = 0
        yield delay(T)
        scl.next = 1
        yield delay(T)
        ack = 1 if sda_line else 0
        check(ack == 0, "slave ACKed matching address (write)")
        check(bool(addr_match), "addr_match asserted")
        check(not bool(rw), "rw indicates WRITE")
        yield delay(T)
        scl.next = 0

        # ---------------- DATA byte 0xA5 ----------
        DATA_WR_VAL = 0xA5
        yield from send_byte(DATA_WR_VAL)

        scl.next = 0
        sda_master_oe.next = 0
        yield delay(T)
        scl.next = 1
        yield delay(T)
        ack = 1 if sda_line else 0
        check(ack == 0, "slave ACKed data byte")
        yield delay(T)
        scl.next = 0
        yield delay(T)
        check(int(rx_data) == DATA_WR_VAL,
              f"rx_data == 0x{DATA_WR_VAL:02X} (got 0x{int(rx_data):02X})")

        # ---------------- STOP ---------------------
        sda_master_oe.next = 1
        scl.next = 1
        yield delay(T)
        sda_master_oe.next = 0           # SDA 0->1 while SCL=1 : STOP
        yield delay(2 * T)
        check(not bool(busy), "busy cleared after STOP")

        # =====================================================
        #  READ transaction: master reads one byte then NACKs
        # =====================================================
        DATA_RD_VAL = 0x3C
        tx_data.next = DATA_RD_VAL
        yield delay(2 * T)

        scl.next = 1
        sda_master_oe.next = 0
        yield delay(T)
        sda_master_oe.next = 1           # START
        yield delay(2 * T)

        addr_byte = (SLAVE_ADDR << 1) | 1
        yield from send_byte(addr_byte)

        scl.next = 0
        sda_master_oe.next = 0
        yield delay(T)
        scl.next = 1
        yield delay(T)
        ack = 1 if sda_line else 0
        check(ack == 0, "slave ACKed matching address (read)")
        check(bool(rw), "rw indicates READ")
        yield delay(T)
        scl.next = 0

        got = 0
        for i in range(8):
            bit = yield from recv_bit()
            got = (got << 1) | bit
        check(got == DATA_RD_VAL,
              f"read byte == 0x{DATA_RD_VAL:02X} (got 0x{got:02X})")

        yield from send_ack(1)   # master NACKs -> ends read

        sda_master_oe.next = 1
        scl.next = 1
        yield delay(T)
        sda_master_oe.next = 0           # STOP
        yield delay(2 * T)
        check(not bool(busy), "busy cleared after final STOP")

        yield delay(5 * T)
        raise StopSimulation

    return dut, bus_model, master


def main():
    tb = testbench()
    sim = Simulation(tb)
    sim.run()

    print("\n---- RESULT ----")
    if errors:
        for e in errors:
            print(e)
        print(f"{len(errors)} check(s) FAILED")
        raise SystemExit(1)
    else:
        print("All checks PASSED")


if __name__ == "__main__":
    main()
