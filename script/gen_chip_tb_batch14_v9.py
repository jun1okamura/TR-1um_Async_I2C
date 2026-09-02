"""
gen_chip_tb_batch14_v9.py (2026-09-02, user request: "SPICEでも１４項目の
テストベンチのバッチファイルを作成して最終確認します。")

Clean, minimal 14-check SPICE batch testbench for the whole chip, covering
the exact same WRITE -> READ -> wrong-address-NACK scenario and the exact
same 14 pass/fail checks already used by:
  - irsim/irsim_tb.cmd + irsim/irsim_tb_expected.json (IRSIM, switch-level,
    confirmed 14/14 PASS via irsim/run_tb.sh)
  - src/i2c_slave_async_net_tb.v (Verilog gate-level netlist simulation,
    confirmed 14/14 PASS after the 2026-09-02 sda_oe-polarity fix)
  - src/i2c_slave_async_tb.v (Verilog RTL-level, confirmed 14/14 PASS)

...so all four simulation methodologies (SPICE/IRSIM/Verilog RTL/Verilog
netlist) can be checked against the identical 14-item list for a final,
apples-to-apples cross-confirmation.

Reuses BusBuilder and the SCL=100kHz PWL/timing model from gen_chip_tb_v9.py
(see that file's own module docstring for the full rationale -- T_HOLD's
300ns SDA-hold margin, the open-drain bus model, the DIS/TX/RX pad handling,
etc. -- all unchanged here) rather than duplicating it. The only additions
are: (1) a third, negative-test transaction (wrong address 0x11 -- same
value as gen_irsim_cmd_v9.py's and i2c_slave_async_net_tb.v's own WRONG_ADDR
-- expect NACK: no slave ACK, addr_match stays low), and (2) exactly 14
cleanly-named .measure statements, fed to a companion checker
(check_batch14.py) that parses ngspice's own .measure output and prints a
PASS/FAIL summary in the same "[t=...] OK/FAIL: <description>" format as
irsim/run_tb.sh's checker.

gen_chip_tb_v9.py's own tb_chip_i2c.spice is NOT modified or replaced by
this file -- it accumulated ~150 historical diagnostic .measure probes over
the course of the start_pulse-detector-race investigation and is kept as-is
as that record. This generates a separate, deliberately minimal file
(tb_chip_i2c_batch14.spice) for routine 14-check regression use going
forward.

Run (this sandbox cannot run ngspice -- must be run locally):
    cd script && python3 gen_chip_tb_batch14_v9.py
    cd ../ngspice/TB && ngspice -b tb_chip_i2c_batch14.spice > spice_batch14.log 2>&1
    python3 check_batch14.py spice_batch14.log
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "script"))

from gen_chip_tb_v9 import (          # noqa: E402  (path insert must come first)
    BusBuilder, SLAVE_ADDR, DATA_WR_VAL, DATA_RD_VAL, VDD,
    T_BIT, T_HALF, T_HOLD, T_RST_LOW, T_EDGE,
    T_POST_RST_SETTLE, T_INTER_TXN_GAP, T_FINAL_SETTLE,
    TX_PADS, RX_NETS, DIS_PAD, SCL_PAD, SDA_PAD, RSTN_PAD,
    MODEL_INCLUDE, SIM_READY_REL, SIM_READY_SRC,
    read_top_pin_order,
)

TB_DIR = str(_REPO_ROOT / "ngspice" / "TB")
TB_OUT = TB_DIR + "/tb_chip_i2c_batch14.spice"

WRONG_ADDR = 0x11   # same convention as gen_irsim_cmd_v9.py / i2c_slave_async_net_tb.v


def build_sequence_and_checks():
    """Builds the WRITE -> READ -> wrong-address-NACK sequence and records
    exactly the 14 checks needed, using the *actual* self.t bookkeeping at
    each step (not hand-computed offsets), so this stays correct even if
    BusBuilder's internal timing constants change."""
    b = BusBuilder(t0=0.0)
    checks = []   # dicts: name, kind ("level"/"byte"), target(s), time(s), expect, desc

    def level_check(name, net, t, expect, desc):
        checks.append(dict(name=name, kind="level", net=net, t=t, expect=expect, desc=desc))

    def byte_check(name, nets, t, expect_hex, desc, bit_indices):
        # bit_indices[i] is the bit WEIGHT (0=LSB..7=MSB) that nets[i]/t[i]
        # actually represents -- needed because rx_data's own RX_NETS list
        # is bit0(LSB)..bit7(MSB) order, while the read-data samples are
        # collected MSB-first (the I2C wire order, per master_byte()'s own
        # `for i in range(7,-1,-1)`); the checker must not assume either
        # list is already in bit0..bit7 order.
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
    addr_match_write_t = ack1_t + T_HALF + T_HALF - 200e-9   # near end of the
                                                              # ACK bit's SCL-high
                                                              # window (see
                                                              # gen_chip_tb_v9.py's
                                                              # identical-purpose
                                                              # comment)
    level_check("addr_match_write", "xdut.NC_CORE_addr_match",
                addr_match_write_t, "high", "addr_match asserted")
    level_check("rw_write", "xdut.NC_CORE_rw",
                addr_match_write_t, "low", "rw indicates WRITE")

    # 2026-09-02 diagnostic v2 (design_notes.md section 108.15): 108.13's
    # diagnostic assumed a uniform bit period computed as
    # (end_t - start_t)/8, which is NOT authoritative -- BusBuilder records
    # the REAL per-bit SCL-rising-edge time for every bit of every
    # master_byte() call in `b.all_bit_edges` (edge_t = self.t + T_HALF,
    # captured before self.t advances). Use that directly instead of
    # re-deriving it, and sample shortly AFTER each real edge (once the
    # gate delays feeding the capture mux/DFFRB have settled) rather than
    # "near the end of the bit period" (which, for the LAST bit, is AFTER
    # the capture edge has already happened and the FSM has moved into the
    # ACK phase -- not useful for seeing the value AT the capture instant).
    edge_start_idx = len(b.all_bit_edges)
    data_byte_start_t = b.t
    b.master_byte(DATA_WR_VAL, "DATA (write)")
    this_byte_edges = b.all_bit_edges[edge_start_idx:]   # [(edge_t, label, bit_index), ...] MSB(i=7) first
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
                ("scl_row2", "xdut.x2.scl_row2"),
            ):
                rx_load_diag.append((f"rxe_i{bit_index}_{tag}_{name}", net, t,
                                      f"{name} at DATA-byte bit_index={bit_index} ({label}) edge{tag}"))

    data_ack_t = b.t
    b.release_bit("ACK (slave, data)")
    level_check("ack_data", SDA_PAD,
                data_ack_t + T_HALF + T_HALF / 2, "low",
                "slave ACKed data byte")
    rx_data_sample_t = b.t + 2e-6   # rx_data_r updates on the data-ACK edge;
                                    # sample well after it settles
    # 2026-09-02 correction #2 (design_notes.md section 108.10): correction
    # #1 (probing `xdut.x2.rx_data_r_N`) turned out to be a different,
    # entirely undriven/floating net (a naming near-collision) -- see the
    # comment that used to be here. The fix attempted next, probing
    # `xdut.x2.rx_data_N` (no "_r", the name the DFFRB's Q pin has *inside*
    # its containing subckt `i2c_slave_async_nrow_fm`), ALSO failed --
    # ngspice reported "no such vector as v(xdut.x2.rx_data_N)" for every
    # bit. Root cause (confirmed via careful hierarchy tracing): `rx_data_N`
    # is a declared PORT of `i2c_slave_async_nrow_fm` (position 19+N in its
    # port list), not a purely-internal wire -- and ngspice's subckt
    # flattening collapses/merges a port node with whatever net the CALLER
    # wired to it, keeping only the caller-side name. At the top-level
    # `tr_1um_i2c_slave_async` subckt, `x2`'s instantiation line wires
    # `rx_data_N`'s port position to the net `NC_OUTxx` (per-bit mapping
    # below) -- so the only valid hierarchical path is `xdut.NC_OUTxx`, one
    # level up from where it was being probed, NOT `xdut.x2.rx_data_N`.
    # (Contrast with `rx_data_r_N`/`sda_d`/`shreg_N` etc., which are
    # internal-only wires with no port merge, and so correctly resolve
    # under `xdut.x2.<name>`.)
    #
    # These NC_OUTxx nets are exactly RX_NETS (imported above from
    # gen_chip_tb_v9.py) -- the same nets an even earlier revision of this
    # file tried and moved away from, on the belief that they reflect the
    # GPIO pad's externally-forced vtx0..7 DC voltage rather than the real
    # register value. Re-tracing the netlist this time found NO such
    # forcing path: inside the pad-ring subckt (`x1`/`OSS_FRAME_GIO`),
    # `NC_OUT4` (e.g.) feeds only an ESD-clamp bias input, never a pad
    # driver or receiver -- its one and only driver anywhere in the file is
    # `x2`'s DFFRB Q output. So NC_OUTxx should be a clean, undistorted tap
    # of the real register bit after all; that earlier belief looks to have
    # been mistaken (or based on a different symptom). Given this project's
    # history of subtle netlist-naming surprises, the diagnostic block
    # below (rx_diag) independently cross-checks shreg_0..6/sda_in_row2
    # (the raw shift-register bits feeding the capture mux) and the
    # already-proven-floating rx_data_r_0..7 (as a negative control)
    # alongside these NC_OUTxx nets, so a second failure would be fully
    # diagnosable from one run instead of needing another round-trip.
    RX_NET_BY_BIT = {  # bit weight -> top-level net (xdut.<net>), from RX_NETS'
                       # own bit0..7 ordering in gen_chip_tb_v9.py
        0: "NC_OUT11", 1: "NC_OUT12", 2: "NC_OUT13", 3: "NC_OUT14",
        4: "NC_OUT6",  5: "NC_OUT5",  6: "NC_OUT4",  7: "NC_OUT3",
    }
    byte_check("rx_data", [f"xdut.{RX_NET_BY_BIT[i]}" for i in range(8)],
                rx_data_sample_t, DATA_WR_VAL, "rx_data == 0x%02X" % DATA_WR_VAL,
                bit_indices=list(range(8)))   # bit0=LSB..bit7=MSB

    # ---- diagnostic-only (not part of the 14-check JSON): cross-check the
    # rx_data capture path in case the byte_check above fails again -- see
    # the long comment above for what each group of nets represents.
    #
    # 2026-09-02 fix (design_notes.md section 108.16): dropped the
    # `rx_data_r_0..7` probes that used to be here -- after 108.14's
    # netlist fix (rewiring the MUX2 hold-inputs away from that dangling
    # net to the real `rx_data_N` Q outputs), `rx_data_r_N` is no longer
    # referenced ANYWHERE in the netlist, so it no longer exists as a
    # node at all once flattened -- probing it now produces a hard
    # "Error: no such vector" (not just a warning), and worse, that error
    # was found to abort the unrelated `wrdata` command later in the same
    # `.control` script, silently preventing `rx_capture_trace.txt` from
    # ever being written. Removed the dead probes entirely.
    rx_diag = []
    for name, net in (
        ("shreg_0", "xdut.x2.shreg_0"), ("shreg_1", "xdut.x2.shreg_1"),
        ("shreg_2", "xdut.x2.shreg_2"), ("shreg_3", "xdut.x2.shreg_3"),
        ("shreg_4", "xdut.x2.shreg_4"), ("shreg_5", "xdut.x2.shreg_5"),
        ("shreg_6", "xdut.x2.shreg_6"), ("sda_in_row2", "xdut.x2.sda_in_row2"),
        ("nc_out3", "xdut.NC_OUT3"), ("nc_out4", "xdut.NC_OUT4"),
        ("nc_out5", "xdut.NC_OUT5"), ("nc_out6", "xdut.NC_OUT6"),
        ("nc_out11", "xdut.NC_OUT11"), ("nc_out12", "xdut.NC_OUT12"),
        ("nc_out13", "xdut.NC_OUT13"), ("nc_out14", "xdut.NC_OUT14"),
    ):
        rx_diag.append((f"rxdiag_{name}", net, rx_data_sample_t, f"{name} at rx_data sample time"))

    # 2026-09-02 fix: stop_condition()'s own body is
    #   self.t += T_HOLD; sda_set(VDD-ensure-low); self.t += T_HALF-T_HOLD;
    #   scl_set(VDD) [SCL rises here, at entry_t+T_HALF];
    #   self.t += T_HALF; sda_set(0.0) [STOP event: SDA rises here, at
    #   entry_t+2*T_HALF]; self.t += T_HALF.
    # An earlier revision of this diagnostic mistakenly added an extra
    # +T_HOLD (computing entry_t+T_HOLD+T_HALF+T_HALF instead of
    # entry_t+2*T_HALF), landing every sample -- including "pre" at
    # (wrong_t-200ns) -- 100ns AFTER the real STOP event instead of before
    # it, which is why every probe (scl_row2/sda_in_row2/sda_d all reading
    # already-settled 5V, busy_clr/qn reading already-settled ~0V) looked
    # identical across the whole -200ns..+5us window: the actual transition
    # was missed entirely, not a real "busy never clears" signature by
    # itself (busy_after_stop1's own check, sampled from the real self.t
    # after the stop_condition() call returns, is unaffected by this and
    # still failed with 7us of genuine margin -- so busy not clearing is
    # still an open question, just not yet correctly probed at the actual
    # transition instant).
    stop1_call_entry_t = b.t
    stop1_actual_t = stop1_call_entry_t + 2 * T_HALF   # SDA rises here (STOP event)
    b.stop_condition()
    busy_clear1_t = b.t + 2e-6
    level_check("busy_after_stop1", "xdut.NC_CORE_busy",
                busy_clear1_t, "low", "busy cleared after STOP")

    # ---- diagnostic-only (not part of the 14-check JSON): trace the STOP
    # detector chain (stop_pulse=_167_... wait, _167_=start_pulse; stop_pulse
    # itself has no top-level alias, only busy_clr=_077_) around the FIRST
    # STOP event, in case busy_after_stop1 fails -- same probing
    # methodology used throughout this investigation for start_pulse.
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
                           ("qn", "xdut.x2.qn"), ("scl_row2", "xdut.x2.scl_row2"),
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
    read_bit_samples = b.read_bit_samples[read_bit_start_idx:]   # [(t, expected_bit), ...] MSB-first
    byte_check("read_byte", [SDA_PAD] * 8,
                [t for t, _ in read_bit_samples], DATA_RD_VAL,
                "read byte == 0x%02X" % DATA_RD_VAL,
                bit_indices=list(range(7, -1, -1)))   # sampled MSB(bit7) first

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
* tb_chip_i2c_batch14.spice -- auto-generated by script/gen_chip_tb_batch14_v9.py
* DO NOT hand-edit -- regenerate instead.
*
* Minimal 14-check WRITE -> READ -> wrong-address-NACK batch testbench, at
* SCL=100kHz, using the real TR-1um transistor models -- see
* gen_chip_tb_v9.py's own docstring for the full PWL/bus-model rationale
* (unchanged here). This file exists for a clean, routine PASS/FAIL
* regression check (companion: check_batch14.py), matching exactly the
* same 14 checks already used by irsim/irsim_tb.cmd (IRSIM, 14/14 PASS)
* and src/i2c_slave_async_net_tb.v / i2c_slave_async_tb.v (Verilog, 14/14
* PASS both).
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

* ---- diagnostic-only: STOP1 detector-chain trace (see gen_chip_tb_
* batch14_v9.py's own comment) -- not part of the 14-item pass/fail list,
* only emitted to localize a busy_after_stop1 FAIL if one occurs.
{STOP1_DIAG_MEASURES}

* 2026-09-02 fix (design_notes.md section 108.12): do NOT issue any
* explicit `print <names>` command here. ngspice already auto-prints every
* `.measure` result once, immediately after `run` finishes, in its own
* "Measurements for Transient Analysis" block -- that block is the single,
* clean, uncorrupted source of truth check_batch14.py needs (it just
* regexes "name = value" lines out of the whole log). Issuing our own
* `print` commands afterward (even split into small chunks -- chunk size
* was NOT the cause, see 108.11/108.12) was empirically found to trigger a
* real ngspice batch-mode bug: `Warning from checkvalid: vector ... is not
* available or has zero length` followed by `Warning: can't parse
* '<netname>': ignored`, and then ngspice silently RE-RUNS the entire
* `.tran` analysis a second time from scratch, printing a SECOND
* "Measurements for Transient Analysis" block whose values do not match
* the first (confirmed via `xdut.x2.shreg_N`, which held a stable, sane
* bit pattern in both duplicate runs, while `NC_OUTxx`/`rx_data_bitN`
* swung between all-5V and all-0V between the two -- i.e. the corrupted
* second pass, not the real circuit, is what produced the nonsense
* "rx_data" byte). check_batch14.py's parser keeps the LAST "name=value"
* match per name, so it was silently picking up the corrupted second run.
* Removing `print` avoids triggering the second run entirely.
.control
  save all
  run
* 2026-09-02 fix (design_notes.md section 108.16): the original version of
* this line used `v(xdut.x2.rx_data_N)` -- the SAME mistake already
* diagnosed and fixed once in 108.10 for the .measure-based checks
* (rx_data_N is a subckt PORT, so ngspice's flattening merges it into the
* caller-side net NC_OUTxx; `xdut.x2.rx_data_N` does not exist as a
* vector). Using it here caused a hard "Error: no such vector" that
* silently aborted this entire `wrdata` command, so no trace file was
* ever written. Fixed to use the correct `xdut.NC_OUTxx` aliases
* (bit0..7 = NC_OUT11/12/13/14/6/5/4/3, per RX_NET_BY_BIT above).
* 2026-09-02 addition (design_notes.md section 108.17): add the 3 actual
* per-row-buffered DFFRB clock nets (`_156__row1/2/3`) -- the earlier
* version of this dump only had `scl_row2` (a DIFFERENT signal, used by
* the START/STOP detector, not the rx_data DFFRBs' own clock input) by
* mistake, so it could not actually show whether `_156__row3` (which
* clocks 7 of the 8 rx_data DFFRBs, vs `_156__row2` for just rx_data_0)
* is toggling at all.
* 2026-09-02 addition (design_notes.md section 108.21): after the 108.20
* row-buffer reassignment fixed rx_data, a NEW, previously-unseen failure
* appeared on "read byte == 0x3C" (got 0x3E, differs only in weight-bit1,
* i.e. the 7th bit shifted out, sampled while bit_cnt==6). Static netlist
* tracing shows the tx-side bit-select network (txreg_0..7, the MUX2 tree
* x_455_/457_/461_/462_/463_, `_092_`/`_079_`/`_005_`) has NO combinational
* or clock dependency on `_156__row0`/`_156__row3` (it lives on the
* completely separate `scl_n_row0`/`scl_n_row2` negedge-domain clock
* trees) -- so this is not explained by the 108.20 patch through any
* logical fan-in we can find by inspection. Adding these nets to the trace
* to check empirically whether it is a genuine tx-path bug (independent of
* 108.20) or a timing-margin issue in that separate clock domain.
  wrdata rx_capture_trace.txt v(xdut.x2.shreg_0) v(xdut.x2.shreg_1) v(xdut.x2.shreg_2) v(xdut.x2.shreg_3) v(xdut.x2.shreg_4) v(xdut.x2.shreg_5) v(xdut.x2.shreg_6) v(xdut.x2.sda_in_row2) v(xdut.x2._087_) v(xdut.x2.last_bit_pending) v(xdut.x2._156__row0) v(xdut.x2._156__row1) v(xdut.x2._156__row2) v(xdut.x2._156__row3) v(xdut.x2._016_) v(xdut.x2.bit_cnt_0) v(xdut.x2.bit_cnt_1) v(xdut.x2.bit_cnt_2) v(xdut.NC_CORE_busy) v(xdut.NC_OUT11) v(xdut.NC_OUT12) v(xdut.NC_OUT13) v(xdut.NC_OUT14) v(xdut.NC_OUT6) v(xdut.NC_OUT5) v(xdut.NC_OUT4) v(xdut.NC_OUT3) v(xdut.x2.txreg_0) v(xdut.x2.txreg_1) v(xdut.x2.txreg_2) v(xdut.x2.txreg_3) v(xdut.x2.txreg_4) v(xdut.x2.txreg_5) v(xdut.x2.txreg_6) v(xdut.x2.txreg_7) v(xdut.x2._092_) v(xdut.x2._079_) v(xdut.x2._005_) v(xdut.x2.sda_oe_r) v(xdut.x2.scl_n_row0) v(xdut.x2.scl_n_row2) v(xdut.x2.scl_n_row3) v(xdut.x2.scl_n)
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
        else:   # byte: one FIND per bit, bit0 first in c['nets']/c['t']
            times = c["t"] if isinstance(c["t"], list) else [c["t"]] * len(c["nets"])
            for i, (net, t) in enumerate(zip(c["nets"], times)):
                bname = f"{c['name']}_bit{i}"
                check_measures.append(
                    f".measure tran {bname} FIND v({net}) AT={t:.9g}  "
                    f"$ {c['desc']} -- bit{i}"
                )
                check_prints.append(bname)

    stop1_diag_measures = []
    stop1_diag_prints = []
    for name, net, t, note in stop1_diag:
        stop1_diag_measures.append(f".measure tran {name} FIND v({net}) AT={t:.9g}  $ {note}")
        stop1_diag_prints.append(name)

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

    # Companion expected-value table, read by check_batch14.py -- mirrors
    # irsim/irsim_tb_expected.json's own role for the IRSIM checker.
    expected_path = TB_DIR + "/spice_batch14_expected.json"
    with open(expected_path, "w") as f:
        json.dump(checks, f, indent=2)
    print(f"wrote {expected_path}")

    print()
    print("Run locally (this sandbox cannot run ngspice):")
    print("  cd ngspice/TB && ngspice -b tb_chip_i2c_batch14.spice > spice_batch14.log 2>&1")
    print("  python3 check_batch14.py spice_batch14.log")


if __name__ == "__main__":
    main()
