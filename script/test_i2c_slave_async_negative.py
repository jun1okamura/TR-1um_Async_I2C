"""Extra check: wrong address must NACK and slave must stay released/idle."""
from myhdl import Signal, intbv, delay, instance, block, Simulation, StopSimulation, now
from script.i2c_slave_async_model import i2c_slave_async

SLAVE_ADDR = 0x50
WRONG_ADDR = 0x11
T = 20
errors = []

def check(cond, msg):
    if not cond:
        errors.append(f"[t={now()}] FAIL: {msg}")
    else:
        print(f"[t={now()}] OK: {msg}")

@block
def testbench():
    rst_n = Signal(bool(1)); scl = Signal(bool(1))
    sda_master_oe = Signal(bool(0))
    sda_slave_oe = Signal(bool(1))   # v3: active-low (0 = slave drives), section 77.3
    sda_line = Signal(bool(1))
    tx_data = Signal(intbv(0)[8:]); rx_data = Signal(intbv(0)[8:])
    rx_valid = Signal(bool(0)); addr_match = Signal(bool(0))
    rw = Signal(bool(0)); busy = Signal(bool(0))

    dut = i2c_slave_async(rst_n, scl, sda_line, sda_slave_oe,
                           tx_data, rx_data, rx_valid, addr_match, rw, busy,
                           slave_addr=SLAVE_ADDR)

    @instance
    def bus_model():
        while True:
            yield sda_master_oe, sda_slave_oe
            sda_line.next = not (sda_master_oe or (not sda_slave_oe))

    def send_bit(bitval):
        yield delay(T)
        scl.next = 0
        sda_master_oe.next = 0 if bitval else 1
        yield delay(T)
        scl.next = 1
        yield delay(2 * T)

    def send_byte(byte):
        for i in range(7, -1, -1):
            yield from send_bit((byte >> i) & 1)

    @instance
    def master():
        yield delay(5 * T)
        scl.next = 1; sda_master_oe.next = 0
        yield delay(T)
        sda_master_oe.next = 1                # START
        yield delay(2 * T)

        addr_byte = (WRONG_ADDR << 1) | 0
        yield from send_byte(addr_byte)

        scl.next = 0; sda_master_oe.next = 0
        yield delay(T)
        scl.next = 1
        yield delay(T)
        ack = 1 if sda_line else 0
        check(ack == 1, "unmatched address -> NACK (no slave ack)")
        check(not bool(addr_match), "addr_match not asserted for foreign address")
        yield delay(T)
        scl.next = 0

        sda_master_oe.next = 1
        scl.next = 1
        yield delay(T)
        sda_master_oe.next = 0                 # STOP
        yield delay(2 * T)
        check(not bool(busy), "busy cleared after STOP following NACK")

        yield delay(5 * T)
        raise StopSimulation

    return dut, bus_model, master

def main():
    Simulation(testbench()).run()
    print("\n---- RESULT ----")
    if errors:
        for e in errors: print(e)
        print(f"{len(errors)} check(s) FAILED"); raise SystemExit(1)
    print("All checks PASSED")

if __name__ == "__main__":
    main()
