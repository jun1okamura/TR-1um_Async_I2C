"""
i2c_tb.py

I2C-bus testbench driving switch_sim.SwitchSim over the FLATTENED,
transistor-level netlist extracted from the actual GDS layout
(layout/steps_v7_v2/i2c_slave_async_nrow_fm.extracted).

Scenario: reset -> START -> address 0x50 + WRITE -> ACK -> one data
byte (0xA5) -> ACK -> STOP. Then a second transaction: START ->
address 0x50 + READ -> ACK -> one byte read back (tx_data=0x3C) ->
master NACKs -> STOP.

Also drives a wrong-address write (0x51) to confirm addr_match stays 0
and the slave does NOT ACK.

Records every input drive and every observed output into a VCD file
for waveform viewing (e.g. GTKWave), plus a plain-text transcript.
"""
import sys
sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs")
from switch_sim import parse_extracted, flatten, SwitchSim, EXTRACTED

OUT_VCD = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/i2c_layout_sim.vcd"

OBSERVE = ["rst_n", "scl", "sda_in", "sda_oe", "busy", "addr_match", "rw",
           "rx_valid"] + [f"rx_data[{i}]" for i in range(8)]
DRIVE_TX = [f"tx_data[{i}]" for i in range(8)]


class Recorder:
    def __init__(self, sim, signals):
        self.sim = sim
        self.signals = signals
        self.t = 0
        self.log = []          # [(t, {sig: val, ...}), ...] only on change
        self.prev = {s: None for s in signals}
        self.vcd_ids = {s: chr(33 + i) for i, s in enumerate(signals)}

    def sample(self, label=""):
        changed = {}
        for s in self.signals:
            v = self.sim.get(s)
            v = v if v is not None else 'x'
            if v != self.prev[s]:
                changed[s] = v
                self.prev[s] = v
        if changed or label:
            self.log.append((self.t, dict(changed), label))
        self.t += 1

    def write_vcd(self, path):
        with open(path, "w") as f:
            f.write("$timescale 1ns $end\n")
            f.write("$scope module i2c_slave_async_nrow_fm $end\n")
            for s in self.signals:
                safe = s.replace('[', '_').replace(']', '')
                f.write(f"$var wire 1 {self.vcd_ids[s]} {safe} $end\n")
            f.write("$upscope $end\n$enddefinitions $end\n")
            f.write("$dumpvars\n")
            for s in self.signals:
                v = self.prev0.get(s, 'x')
                f.write(f"{v}{self.vcd_ids[s]}\n")
            f.write("$end\n")
            for t, changed, label in self.log:
                f.write(f"#{t}\n")
                if label:
                    f.write(f"$comment {label} $end\n")
                for s, v in changed.items():
                    f.write(f"{v}{self.vcd_ids[s]}\n")


def bits_msb_first(byte, n=8):
    return [(byte >> (n - 1 - i)) & 1 for i in range(n)]


def main():
    print("parsing extracted netlist...")
    blocks = parse_extracted(EXTRACTED)
    devices, behaviorals, seq_cells, top_pins = flatten(blocks)
    print(f"  {len(devices)} transistors, {len(behaviorals)} behavioral "
          f"(BUFTH/DELx) cells, {len(seq_cells)} sequential (DFFR) cells, "
          f"{len(top_pins)} top pins")

    sim = SwitchSim(devices, behaviorals, seq_cells)
    rec = Recorder(sim, OBSERVE)
    rec.prev0 = {}

    def drive(sig, val):
        sim.set(sig, val)

    def step(label=""):
        contentions = sim.settle()
        if contentions:
            print(f"  ** CONTENTION at t={rec.t} ({label}): {contentions[:5]}"
                  f"{'...' if len(contentions) > 5 else ''}")
        rec.sample(label)

    # ---- initial: everything undriven except supplies; hold in reset ----
    drive("rst_n", 0)
    drive("scl", 1)
    drive("sda_in", 1)
    for i in range(8):
        drive(f"tx_data[{i}]", 0)
    step("power-up / reset asserted")
    for s in OBSERVE:
        rec.prev0[s] = rec.prev[s] if rec.prev[s] is not None else 'x'

    transcript = []

    def check(name, sig, expect):
        got = sim.get(sig)
        ok = (got == expect)
        transcript.append((name, sig, expect, got, ok))
        mark = "OK" if ok else "**FAIL**"
        print(f"  [{mark}] {name}: {sig} expected={expect} got={got}")
        return ok

    print("\n=== reset state ===")
    check("reset: busy=0", "busy", 0)
    check("reset: addr_match=0", "addr_match", 0)
    check("reset: rw=0", "rw", 0)
    check("reset: sda_oe=0", "sda_oe", 0)
    for i in range(8):
        check(f"reset: rx_data[{i}]=0", f"rx_data[{i}]", 0)

    print("\n=== release reset ===")
    drive("rst_n", 1)
    step("rst_n released")
    check("post-reset: busy=0", "busy", 0)

    def i2c_start():
        # SDA falls while SCL is high
        drive("scl", 1)
        drive("sda_in", 1)
        step("bus idle")
        drive("sda_in", 0)
        step("START condition (SDA 1->0 while SCL=1)")

    def i2c_stop():
        drive("scl", 1)
        drive("sda_in", 0)
        step("(pre-STOP) SDA low, SCL high")
        drive("sda_in", 1)
        step("STOP condition (SDA 0->1 while SCL=1)")

    def i2c_send_bit(bit):
        drive("scl", 0)
        drive("sda_in", bit)
        step(f"SCL low, drive SDA={bit}")
        drive("scl", 1)
        step("SCL rising edge (bit sampled)")

    def i2c_send_byte(byte):
        for b in bits_msb_first(byte):
            i2c_send_bit(b)

    def i2c_recv_bit():
        drive("scl", 0)
        step("SCL low (slave may drive SDA)")
        drive("scl", 1)
        step("SCL rising edge")
        v = sim.get("sda_in")  # bus level as driven by slave (sda_oe) or released(=we leave sda_in as pulled up)
        return v

    def i2c_master_ack():
        # master pulls SDA low to ACK
        drive("scl", 0)
        drive("sda_in", 0)
        step("master ACK: SDA low")
        drive("scl", 1)
        step("SCL rising edge (ACK bit)")

    def i2c_master_nack():
        drive("scl", 0)
        drive("sda_in", 1)
        step("master NACK: SDA released/high")
        drive("scl", 1)
        step("SCL rising edge (NACK bit)")

    # =========================================================
    # Transaction 1: WRITE to 0x50, one data byte 0xA5
    # =========================================================
    print("\n=== Transaction 1: WRITE addr=0x50 data=0xA5 ===")
    i2c_start()
    check("busy set after START", "busy", 1)
    i2c_send_byte((0x50 << 1) | 0)  # 7-bit addr + W(0)
    # ACK phase: slave should drive SDA low (sda_oe=1) once SCL falls
    drive("scl", 0)
    step("SCL falls -> sda_oe should latch ACK")
    check("addr_match after address byte", "addr_match", 1)
    check("rw=0 (write)", "rw", 0)
    check("sda_oe=1 (slave ACK, addr matched)", "sda_oe", 1)
    drive("scl", 1)
    step("SCL rising (ACK bit clocked)")

    i2c_send_byte(0xA5)
    drive("scl", 0)
    step("SCL falls after data byte")
    for i in range(8):
        check(f"rx_data[{i}] bit of 0xA5", f"rx_data[{i}]", (0xA5 >> i) & 1)
    check("rx_valid=1 after data byte", "rx_valid", 1)
    check("sda_oe=1 (slave ACKs data)", "sda_oe", 1)
    drive("scl", 1)
    step("SCL rising (data-ACK bit clocked)")

    i2c_stop()
    check("busy cleared after STOP", "busy", 0)

    # =========================================================
    # Transaction 2: wrong-address WRITE to 0x51 (should NOT ack)
    # =========================================================
    print("\n=== Transaction 2: WRONG ADDRESS 0x51 (expect NACK) ===")
    i2c_start()
    i2c_send_byte((0x51 << 1) | 0)
    drive("scl", 0)
    step("SCL falls after wrong-address byte")
    check("addr_match=0 (wrong address)", "addr_match", 0)
    check("sda_oe=0 (no ACK for wrong address)", "sda_oe", 0)
    drive("scl", 1)
    step("SCL rising")
    i2c_stop()
    check("busy cleared after STOP (txn2)", "busy", 0)

    # =========================================================
    # Transaction 3: READ from 0x50, tx_data=0x3C
    # =========================================================
    print("\n=== Transaction 3: READ addr=0x50 tx_data=0x3C ===")
    for i in range(8):
        drive(f"tx_data[{i}]", (0x3C >> i) & 1)
    i2c_start()
    i2c_send_byte((0x50 << 1) | 1)  # 7-bit addr + R(1)
    drive("scl", 0)
    step("SCL falls after address+R byte")
    check("addr_match after address byte (read)", "addr_match", 1)
    check("rw=1 (read)", "rw", 1)
    check("sda_oe=1 (slave ACK, addr matched)", "sda_oe", 1)
    drive("scl", 1)
    step("SCL rising (ACK bit clocked)")

    # slave now shifts tx_data out MSB-first on sda_oe (sda_oe=1 means
    # "drive low" i.e. bit=0 -- comment in RTL: sda_oe_r <= ~txreg[bit]).
    # We don't drive sda_in during these bits (master is listening);
    # we read back sda_oe each cycle instead and reconstruct the byte.
    read_bits = []
    tx_expect = bits_msb_first(0x3C)
    for i in range(8):
        drive("scl", 0)
        step(f"SCL low, bit {i} settling")
        oe = sim.get("sda_oe")
        bit_val = 0 if oe == 1 else 1   # sda_oe=1 -> driving SDA low -> bus bit = 0
        read_bits.append(bit_val)
        drive("scl", 1)
        step(f"SCL rising, bit {i} clocked")
    print(f"  read back bits (MSB first): {read_bits}  expected: {tx_expect}")
    transcript.append(("read-back 0x3C", "sda_oe-derived bits", tx_expect, read_bits, read_bits == tx_expect))
    print(f"  [{'OK' if read_bits==tx_expect else '**FAIL**'}] read-back matches tx_data=0x3C")

    i2c_master_nack()   # master ends read with NACK
    i2c_stop()
    check("busy cleared after STOP (txn3)", "busy", 0)

    rec.write_vcd(OUT_VCD)
    print(f"\nwrote VCD waveform -> {OUT_VCD} ({rec.t} time steps, {len(rec.log)} logged events)")

    n_fail = sum(1 for t in transcript if not t[-1])
    print(f"\n=== SUMMARY: {len(transcript)} checks, {len(transcript)-n_fail} passed, {n_fail} failed ===")
    return n_fail


if __name__ == "__main__":
    n_fail = main()
    sys.exit(1 if n_fail else 0)
