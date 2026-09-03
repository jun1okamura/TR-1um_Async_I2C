"""
gen_chip_tb_batch14_v10.py (V10 counterpart of gen_chip_tb_batch14_v9.py --
user request, this session: "14項目のテストベンチをお願いします。", after
the plainer gen_chip_tb_v10.py (single WRITE+READ) was not what the user
meant -- this project's established "14-item batch test" convention
(design_notes.md 108.3/108.4, section 18514-18556) is the WRITE -> READ ->
wrong-address-NACK 3-transaction, 14-named-check regression test already
cross-confirmed 14/14 PASS across IRSIM/Verilog-RTL/Verilog-netlist/SPICE
(V9) -- this builds the V10 SPICE version of the same thing.)

Same 14 checks, same WRITE(0x50)->READ(0x50)->wrong-address(0x11)-NACK
3-transaction sequence, same BusBuilder/timing engine -- imported from
gen_chip_tb_v10.py (this session's own V10 port of gen_chip_tb_v9.py, see
its module docstring for the pad-remapping verification already done
there) instead of gen_chip_tb_v9.py, so this automatically gets V10's own
TX_PADS/RX_NETS/SCL_PAD/SDA_PAD/DIS_PAD/RSTN_PAD (verified against V10's
own x1/x2 instantiation lines, NOT V9's).

The 14 checks (identical names/order/meaning to gen_chip_tb_batch14_v9.py,
see that file for the original rationale of each):
  TXN1 WRITE: busy_after_start, ack_addr_write, addr_match_write, rw_write,
              ack_data, rx_data (byte, ==0xA5), busy_after_stop1
  TXN2 READ:  ack_addr_read, rw_read, read_byte (byte, ==0x3C),
              busy_after_stop2
  TXN3 NEG:   nack_wrong_addr, addr_match_wrong, busy_after_stop3

**rx_data bit->net mapping**: V9's script hardcoded RX_NET_BY_BIT as a
literal dict (NC_OUT11/12/13/14/6/5/4/3). Derived here instead directly
from gen_chip_tb_v10.py's own (already-verified-against-the-real-netlist)
RX_NETS list, avoiding a second hand-typed copy of the same V10-specific
pad mapping that could drift out of sync with gen_chip_tb_v10.py's own copy.

**Diagnostic-only probes (rx_load_diag/rx_diag/stop1_diag/the final
`wrdata` trace line) -- NOT part of the 14-check pass/fail, only used to
troubleshoot a FAIL if one occurs**: V9's versions of these reference
several internal net names that a direct grep of ngspice/tr_1um_i2c_
slave_async_v10_sim_ready.spice confirms do NOT exist in V10's build --
specifically "scl_row2" (V10 has "scl_row1" instead -- a different, but
analogous, start/stop-detector-domain clock net) and the row-buffered
"_156__row0/1/2/3" / "scl_n_row0" nets (V10's bit_cnt/phase/last_bit_
pending DFFRBs all clock directly off the bare, unbuffered "_156_" net --
confirmed via direct inspection of their own DFFRB instance lines -- and
V10 only has "scl_n_row1/2/3", not "scl_n_row0"). Every OTHER internal
net V9's diagnostics reference (_087_, _092_, _079_, _005_, sda_oe_r,
sda_in_row2, sda_d, qn, _077_, _016_, shreg_0..6, txreg_0..7, last_bit_
pending, bit_cnt_0..2, scl_n) was confirmed present under the identical
name, so those are kept as-is; only the confirmed-absent ones were
swapped (scl_row2->scl_row1) or dropped (_156__row0/1/2/3->bare _156_
once, scl_n_row0 dropped).
"""
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "script"))

from gen_chip_tb_v10 import (          # noqa: E402  (path insert must come first)
    BusBuilder, SLAVE_ADDR, DATA_WR_VAL, DATA_RD_VAL, VDD,
    T_HALF, T_HOLD, T_RST_LOW, T_EDGE,
    T_POST_RST_SETTLE, T_INTER_TXN_GAP, T_FINAL_SETTLE,
    TX_PADS, RX_NETS, DIS_PAD, SCL_PAD, SDA_PAD, RSTN_PAD,
    MODEL_INCLUDE, SIM_READY_REL, SIM_READY_SRC,
    read_top_pin_order,
)

TB_DIR = str(_REPO_ROOT / "ngspice" / "TB")
TB_OUT = TB_DIR + "/tb_chip_i2c_batch14_v10.spice"

WRONG_ADDR = 0x11   # same convention as V9's batch14 / gen_irsim_cmd_v9.py

# Derived directly from V10's own RX_NETS (gen_chip_tb_v10.py, bit0=LSB..
# bit7=MSB order) rather than a second hand-typed literal.
RX_NET_BY_BIT = {i: RX_NETS[i] for i in range(8)}


def build_sequence_and_checks():
    """Builds the WRITE -> READ -> wrong-address-NACK sequence and records
    exactly the 14 checks, using the *actual* self.t bookkeeping at each
    step (not hand-computed offsets) -- same structure as V9's batch14
    generator."""
    b = BusBuilder(t0=0.0)
    checks = []

    def level_check(name, net, t, expect, desc):
        checks.append(dict(name=name, kind="level", net=net, t=t, expect=expect, desc=desc))

    def byte_check(name, nets, t, expect_hex, desc, bit_indices):
        checks.append(dict(name=name, kind="byte", nets=nets, t=t, expect=expect_hex,
                            desc=desc, bit_indices=bit_indices))

    b.idle(T_POST_RST_SETTLE, label="post-reset settle (bus idle)")

    # ================= TXN1: WRITE (S, ADDR+W, ACK, 0xA5, ACK, P) =========
    start1_t = b.t
    b.start_condition()
    level_check("busy_after_start", "xdut.NC_CORE_busy",
                start1_t + T_HALF + T_HALF / 2, "high",
                "busy asserted after START")

    addr_w = (SLAVE_ADDR << 1) | 0
    b.master_byte(addr_w, "ADDR+W")

    ack1_t = b.t
    b.release_bit("ACK (slave, address/write)")
    level_check("ack_addr_write", SDA_PAD,
                ack1_t + T_HALF + T_HALF / 2, "low",
                "slave ACKed matching address (write)")
    addr_match_write_t = ack1_t + T_HALF + T_HALF - 200e-9
    level_check("addr_match_write", "xdut.NC_CORE_addr_match",
                addr_match_write_t, "high", "addr_match asserted")
    level_check("rw_write", "xdut.NC_CORE_rw",
                addr_match_write_t, "low", "rw indicates WRITE")

    edge_start_idx = len(b.all_bit_edges)
    b.master_byte(DATA_WR_VAL, "DATA (write)")
    this_byte_edges = b.all_bit_edges[edge_start_idx:]
    rx_load_diag = []
    for edge_t, label, bit_index in this_byte_edges:
        for dt_ns, tag in ((-0.05e-6, "pre50n"), (0.05e-6, "post50n"), (0.5e-6, "post500n")):
            t = edge_t + dt_ns
            for name, net in (
                ("sel_087", "xdut.x2._087_"),
                ("last_bit_pending", "xdut.x2.last_bit_pending"),
                ("shreg_0", "xdut.x2.shreg_0"), ("shreg_1", "xdut.x2.shreg_1"),
                ("shreg_2", "xdut.x2.shreg_2"), ("shreg_3", "xdut.x2.shreg_3"),
                ("shreg_4", "xdut.x2.shreg_4"), ("shreg_5", "xdut.x2.shreg_5"),
                ("shreg_6", "xdut.x2.shreg_6"), ("sda_in_row2", "xdut.x2.sda_in_row2"),
                # V10: no "scl_row2" (confirmed absent, see module
                # docstring) -- "scl_row1" is V10's own analogous
                # start/stop-detector-domain clock net.
                ("scl_row1", "xdut.x2.scl_row1"),
            ):
                rx_load_diag.append((f"rxe_i{bit_index}_{tag}_{name}", net, t,
                                      f"{name} at DATA-byte bit_index={bit_index} ({label}) edge{tag}"))

    data_ack_t = b.t
    b.release_bit("ACK (slave, data)")
    level_check("ack_data", SDA_PAD,
                data_ack_t + T_HALF + T_HALF / 2, "low",
                "slave ACKed data byte")
    rx_data_sample_t = b.t + 2e-6

    byte_check("rx_data", [f"xdut.{RX_NET_BY_BIT[i]}" for i in range(8)],
                rx_data_sample_t, DATA_WR_VAL, "rx_data == 0x%02X" % DATA_WR_VAL,
                bit_indices=list(range(8)))

    rx_diag = []
    for name, net in (
        ("shreg_0", "xdut.x2.shreg_0"), ("shreg_1", "xdut.x2.shreg_1"),
        ("shreg_2", "xdut.x2.shreg_2"), ("shreg_3", "xdut.x2.shreg_3"),
        ("shreg_4", "xdut.x2.shreg_4"), ("shreg_5", "xdut.x2.shreg_5"),
        ("shreg_6", "xdut.x2.shreg_6"), ("sda_in_row2", "xdut.x2.sda_in_row2"),
    ) + tuple((f"nc_out_{n}", f"xdut.{n}") for n in RX_NETS):
        rx_diag.append((f"rxdiag_{name}", net, rx_data_sample_t, f"{name} at rx_data sample time"))

    stop1_call_entry_t = b.t
    stop1_actual_t = stop1_call_entry_t + 2 * T_HALF
    b.stop_condition()
    busy_clear1_t = b.t + 2e-6
    level_check("busy_after_stop1", "xdut.NC_CORE_busy",
                busy_clear1_t, "low", "busy cleared after STOP")

    stop1_diag = []
    for tag, dt in (
        ("m500n", -500e-9), ("m100n", -100e-9), ("m50n", -50e-9),
        ("m20n", -20e-9), ("m10n", -10e-9), ("m5n", -5e-9),
        ("evt", 0.0),
        ("p5n", 5e-9), ("p10n", 10e-9), ("p20n", 20e-9), ("p50n", 50e-9),
        ("p100n", 100e-9), ("p500n", 500e-9), ("p1u", 1e-6), ("p2u", 2e-6), ("p5u", 5e-6),
    ):
        t = stop1_actual_t + dt
        for name, net in (("busy", "xdut.NC_CORE_busy"), ("busy_clr", "xdut.x2._077_"),
                           ("qn", "xdut.x2.qn"), ("scl_row1", "xdut.x2.scl_row1"),
                           ("sda_in_row2", "xdut.x2.sda_in_row2"), ("sda_d", "xdut.x2.sda_d")):
            stop1_diag.append((f"stop1_{name}_{tag}", net, t,
                                f"{name} at STOP1{'+' if dt >= 0 else ''}{dt*1e9:.0f}ns"))

    b.idle(T_INTER_TXN_GAP, label="inter-transaction idle 1")

    # ================= TXN2: READ (S, ADDR+R, ACK, 0x3C, NACK, P) =========
    b.start_condition()
    addr_r = (SLAVE_ADDR << 1) | 1
    b.master_byte(addr_r, "ADDR+R")

    ack2_t = b.t
    b.release_bit("ACK (slave, address/read)")
    level_check("ack_addr_read", SDA_PAD,
                ack2_t + T_HALF + T_HALF / 2, "low",
                "slave ACKed matching address (read)")
    addr_match_read_t = ack2_t + T_HALF + T_HALF - 200e-9
    level_check("rw_read", "xdut.NC_CORE_rw",
                addr_match_read_t, "high", "rw indicates READ")

    b.note(f"DATA (read, expect 0x{DATA_RD_VAL:02X})")
    read_bit_start_idx = len(b.read_bit_samples)
    for i in range(7, -1, -1):
        b.slave_data_bit((DATA_RD_VAL >> i) & 1)
    read_bit_samples = b.read_bit_samples[read_bit_start_idx:]
    byte_check("read_byte", [SDA_PAD] * 8,
               [t for t, _ in read_bit_samples], DATA_RD_VAL,
               "read byte == 0x%02X" % DATA_RD_VAL,
               bit_indices=list(range(7, -1, -1)))

    b.master_ack_bit(1, "NACK (master, ends read)")
    b.stop_condition()
    busy_clear2_t = b.t + 2e-6
    level_check("busy_after_stop2", "xdut.NC_CORE_busy",
                busy_clear2_t, "low", "busy cleared after final STOP")

    b.idle(T_INTER_TXN_GAP, label="inter-transaction idle 2")

    # ================= TXN3: NEGATIVE (wrong address -> NACK) =============
    b.start_condition()
    wrong_addr_w = (WRONG_ADDR << 1) | 0
    b.master_byte(wrong_addr_w, "ADDR+W (wrong, expect NACK)")

    ack3_t = b.t
    b.release_bit("ACK (expect NACK, wrong address)")
    level_check("nack_wrong_addr", SDA_PAD,
                ack3_t + T_HALF + T_HALF / 2, "high",
                "unmatched address -> NACK (no slave ack)")
    addr_match_wrong_t = ack3_t + T_HALF + T_HALF - 200e-9
    level_check("addr_match_wrong", "xdut.NC_CORE_addr_match",
                addr_match_wrong_t, "low",
                "addr_match not asserted for foreign address")

    b.stop_condition()
    busy_clear3_t = b.t + 2e-6
    level_check("busy_after_stop3", "xdut.NC_CORE_busy",
                busy_clear3_t, "low",
                "busy cleared after STOP following NACK")

    b.idle(T_FINAL_SETTLE, label="final settle")
    b.finish()

    assert len(checks) == 14, f"expected exactly 14 checks, got {len(checks)}"
    return b, checks, rx_load_diag + rx_diag + stop1_diag


TB_HEADER = """\
* tb_chip_i2c_batch14_v10.spice -- auto-generated by
* script/gen_chip_tb_batch14_v10.py
* DO NOT hand-edit -- regenerate instead.
*
* Minimal 14-check WRITE -> READ -> wrong-address-NACK batch testbench for
* the V10 chip, at SCL=100kHz, using the real TR-1um transistor models --
* see gen_chip_tb_v10.py's own docstring for the full PWL/bus-model
* rationale (unchanged here) and V10-specific pad-mapping verification.
* Companion checker: check_batch14_v10.py. Matches the exact same 14
* checks already used by irsim/irsim_tb.cmd (IRSIM, 14/14 PASS),
* src/i2c_slave_async_net_tb.v / i2c_slave_async_tb.v (Verilog, 14/14 PASS
* both), and gen_chip_tb_batch14_v9.py (V9 chip SPICE, 14/14 PASS).
*
*   WRITE : S, ADDR+W(0x{ADDR_W:02X}), ACK, DATA=0x{DATA_WR:02X}, ACK, P
*   READ  : S, ADDR+R(0x{ADDR_R:02X}), ACK, DATA=0x{DATA_RD:02X} (slave-driven), NACK, P
*   NEG   : S, ADDR+W(0x{WRONG_ADDR_W:02X}, wrong addr 0x{WRONG_ADDR:02X}), expect NACK, P

.include '{MODEL_INCLUDE}'
.include '{SIM_READY_REL}'

.param vdd={VDD}

vvdd VDD 0 DC {VDD}
vvss VSS 0 DC 0

vrstn {RSTN_PAD} 0 PWL(0 0 {T_RST_LOW:.9g} 0 {T_RST_LOW_EDGE:.9g} {VDD})
vdis {DIS_PAD} 0 DC {VDD}

rp9 P9 VSS 1G
rp10 P10 VSS 1G

* tx_data (bit0..7 = {TX_PADS}), held at 0x{DATA_RD:02X} for the whole run.
{TX_SOURCES}

vscl {SCL_PAD} 0 PWL({SCL_PWL})

vsda_ctrl SDA_CTRL 0 PWL({SDA_PWL})
.model SDASW SW(RON=10 ROFF=1MEG VT={SW_VT} VH={SW_VH})
ssda {SDA_PAD} 0 SDA_CTRL 0 SDASW
rpu {SDA_PAD} VDD {RPU_KOHM:.0f}k

xdut {XDUT_NETS} tr_1um_i2c_slave_async

.tran {TSTEP} {TSTOP}

* ---- the 14 checks ----
{CHECK_MEASURES}

* ---- diagnostic-only: STOP1 detector-chain trace -- not part of the
* 14-item pass/fail list, only emitted to localize a busy_after_stop1
* FAIL if one occurs.
{STOP1_DIAG_MEASURES}

* No explicit `print <names>` command here -- see gen_chip_tb_batch14_
* v9.py's own comment for why (a real ngspice batch-mode bug where an
* explicit print after `run` can trigger a silent, corrupted second
* .tran pass). ngspice auto-prints every .measure result once, right
* after `run`, in its own "Measurements for Transient Analysis" block --
* that's the sole source check_batch14_v10.py parses.
.control
  save all
  run
  wrdata rx_capture_trace_v10.txt v(xdut.x2.shreg_0) v(xdut.x2.shreg_1) v(xdut.x2.shreg_2) v(xdut.x2.shreg_3) v(xdut.x2.shreg_4) v(xdut.x2.shreg_5) v(xdut.x2.shreg_6) v(xdut.x2.sda_in_row2) v(xdut.x2._087_) v(xdut.x2.last_bit_pending) v(xdut.x2._156_) v(xdut.x2._016_) v(xdut.x2.bit_cnt_0) v(xdut.x2.bit_cnt_1) v(xdut.x2.bit_cnt_2) v(xdut.NC_CORE_busy) {NC_OUT_TRACE} v(xdut.x2.txreg_0) v(xdut.x2.txreg_1) v(xdut.x2.txreg_2) v(xdut.x2.txreg_3) v(xdut.x2.txreg_4) v(xdut.x2.txreg_5) v(xdut.x2.txreg_6) v(xdut.x2.txreg_7) v(xdut.x2._092_) v(xdut.x2._079_) v(xdut.x2._005_) v(xdut.x2.sda_oe_r) v(xdut.x2.scl_n_row1) v(xdut.x2.scl_n_row2) v(xdut.x2.scl_n_row3) v(xdut.x2.scl_n)
.endc

.end
"""


def build_tb():
    src_text = open(SIM_READY_SRC).read()
    pins = read_top_pin_order(src_text)
    xdut_nets = " ".join(pins)

    b, checks, stop1_diag = build_sequence_and_checks()

    tx_sources = []
    for i, pad in enumerate(TX_PADS):
        bit = (DATA_RD_VAL >> i) & 1
        tx_sources.append(f"vtx{i} {pad} 0 DC {VDD if bit else 0.0}")

    check_measures = []
    check_prints = []
    for c in checks:
        if c["kind"] == "level":
            check_measures.append(
                f".measure tran {c['name']} FIND v({c['net']}) AT={c['t']:.9g}  "
                f"$ expect {'~VDD' if c['expect'] == 'high' else '~0V'} -- {c['desc']}"
            )
            check_prints.append(c["name"])
        else:
            times = c["t"] if isinstance(c["t"], list) else [c["t"]] * len(c["nets"])
            for i, (net, t) in enumerate(zip(c["nets"], times)):
                bname = f"{c['name']}_bit{i}"
                check_measures.append(
                    f".measure tran {bname} FIND v({net}) AT={t:.9g}  "
                    f"$ {c['desc']} -- bit{i}"
                )
                check_prints.append(bname)

    stop1_diag_measures = []
    for name, net, t, note in stop1_diag:
        stop1_diag_measures.append(f".measure tran {name} FIND v({net}) AT={t:.9g}  $ {note}")

    nc_out_trace = " ".join(f"v(xdut.{n})" for n in RX_NETS)

    tstop = b.t + 2e-6

    text = TB_HEADER.format(
        ADDR_W=(SLAVE_ADDR << 1) | 0,
        ADDR_R=(SLAVE_ADDR << 1) | 1,
        WRONG_ADDR_W=(WRONG_ADDR << 1) | 0,
        WRONG_ADDR=WRONG_ADDR,
        DATA_WR=DATA_WR_VAL,
        DATA_RD=DATA_RD_VAL,
        MODEL_INCLUDE=MODEL_INCLUDE,
        SIM_READY_REL=SIM_READY_REL,
        VDD=VDD,
        T_RST_LOW=T_RST_LOW,
        T_RST_LOW_EDGE=T_RST_LOW + T_EDGE,
        RSTN_PAD=RSTN_PAD,
        DIS_PAD=DIS_PAD,
        TX_PADS=TX_PADS,
        TX_SOURCES="\n".join(tx_sources),
        SCL_PAD=SCL_PAD,
        SCL_PWL=b.pwl(b.scl),
        SDA_PAD=SDA_PAD,
        SDA_PWL=b.pwl(b.sda_ctrl),
        SW_VT=VDD / 2,
        SW_VH=0.3,
        RPU_KOHM=10,
        XDUT_NETS=xdut_nets,
        TSTEP="50n",
        TSTOP=f"{tstop:.9g}",
        CHECK_MEASURES="\n".join(check_measures),
        STOP1_DIAG_MEASURES="\n".join(stop1_diag_measures),
        NC_OUT_TRACE=nc_out_trace,
    )
    return text, checks


def main():
    import os
    import json
    os.makedirs(TB_DIR, exist_ok=True)
    text, checks = build_tb()
    with open(TB_OUT, "w") as f:
        f.write(text)
    print(f"wrote {TB_OUT}")

    expected_path = TB_DIR + "/spice_batch14_v10_expected.json"
    with open(expected_path, "w") as f:
        json.dump(checks, f, indent=2)
    print(f"wrote {expected_path}")

    print()
    print("Run locally (this sandbox cannot run ngspice):")
    print("  cd ngspice/TB && ngspice -b tb_chip_i2c_batch14_v10.spice > spice_batch14_v10.log 2>&1")
    print("  python3 check_batch14_v10.py spice_batch14_v10.log")


if __name__ == "__main__":
    main()
