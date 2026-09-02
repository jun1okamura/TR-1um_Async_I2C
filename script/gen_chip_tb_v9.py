"""
gen_chip_tb_v9.py (this session, user request: "プルアップは10Kにして
ください。テストベンチをngspice/TBに作成ください。" -- following on from
gen_chip_sim_ready_v9.py, and the user's original: "アドレス指定＞Write>
ReadのSPICEシミュレーションをして波形確認をします...SCLのクロック周波数
は 100KHz にします。")

Builds a real, locally-runnable ngspice testbench (ngspice/TB/tb_chip_
i2c.spice) for the whole chip (RING_OSC excluded -- ngspice/tr_1um_i2c_
slave_async_sim_ready.spice, see gen_chip_sim_ready_v9.py) that runs one
I2C WRITE transaction followed by one I2C READ transaction at
SCL=100kHz, mirroring script/test_i2c_slave_async.py's own bus-
functional-model sequence exactly (same SLAVE_ADDR=0x50, same DATA_WR_
VAL=0xA5, same DATA_RD_VAL=0x3C, same bit order (MSB-first, `for i in
range(7,-1,-1)`), same START/STOP/ACK/NACK conventions -- that file is
the project's own gold-standard reference for this protocol, already
confirmed correct against UM10204 3.1.4-3.1.6 and against the RTL). The
internal T-based relative timing of that MyHDL model is NOT reproduced
verbatim (T there is described as "arbitrary...value is irrelevant for
an async design"); instead this generates a clean, evenly-spaced
100kHz-clocked version of the SAME protocol shape, which is what
actually matters electrically.

**TX/RX pin handling (structural precedent: script/gen_irsim_cmd_v9.py's
own module docstring, "DIS=H (this script's default) lets TX be forced
externally without contention; NEVER force TX while DIS=L")**: DIS (P7)
is held HIGH for the entire run (Hi-Z / tx_data-input mode), so the 8
shared tx/rx pads never contend with this testbench's own TX drive.
Critically, rx_data is NOT observed by watching the P-pads themselves
(which would need DIS=L, driver-enabled, and is unnecessary here) --
it's observed directly at each pad's own internal receiver-output net
(NC_OUT11/12/13/14/6/5/4/3 for rx_data bit0..7, exactly as gen_irsim_
cmd_v9.py's own RX list documents), which continuously reflects the pad
voltage regardless of DIS. tx_data is likewise driven directly via DC
sources on the TX pins (P11/12/13/14/6/5/4/3 = tx_data bit0..7, same
list as gen_irsim_cmd_v9.py's TX), held at DATA_RD_VAL=0x3C for the
whole run (irrelevant during the write transaction, only consumed
during the read).

**SDA open-drain bus model**: SDA (P2) has no on-chip pull-up (design_
notes.md 76.29-76.38 -- the chip's own synthetic IRSIM pull-up was an
IRSIM-only artifact, not real circuitry), so this testbench adds an
external Rpu=10k (per the user's explicit instruction) from SDA to VDD,
plus a voltage-controlled switch (ngspice "S" device) from SDA to VSS,
gated by an SDA_CTRL waveform, modeling this testbench's own I2C-master
open-drain output stage (drive low when SDA_CTRL is high, release
otherwise) in parallel with the DUT's own internal SDA driver transistor
(already part of the sim_ready netlist's OSS_ESD_5V_DIO instance for
P2) -- exactly the real wired-AND bus topology, no special-casing needed
for who's "turn" it is to drive: both sides simply either pull low or
release, and the resistor decides the released level.

**Bit encoding**: every PWL breakpoint list is built through _scl()/
_sda(), which insert a short (T_EDGE) ramp only when the value actually
changes and otherwise emit a flat point -- avoiding the bug an earlier
draft of this generator had (recording only one point per bit-period
boundary lets ngspice's PWL linearly interpolate the ENTIRE bit period
between differing values, so a bit could still be mid-ramp when its own
SCL rising edge samples it; fixed by always holding flat until exactly
T_EDGE before a real transition).

Reset: RSTN (P15) held low for T_RST_LOW then released to VDD with a
fast edge -- a real async reset via each DFFRB's own RSTB pin (no
IRSIM-style QM/QS force-node workaround needed; those were specifically
IRSIM's own switch-level solver limitation for MID-run resets, see
design_notes.md 94.1 -- irrelevant here, this is a single power-on
reset simulated with real transistors).
"""
import re
from pathlib import Path

# 2026-09-02: made portable (was hardcoded to a Claude-sandbox absolute
# path -- see lef_parser.py's LEF_PATH for the same fix).
_REPO_ROOT = Path(__file__).resolve().parent.parent
SIM_READY_SRC = str(_REPO_ROOT / "ngspice" / "tr_1um_i2c_slave_async_sim_ready.spice")
TB_DIR = str(_REPO_ROOT / "ngspice" / "TB")
TB_OUT = TB_DIR + "/tb_chip_i2c.spice"

MODEL_INCLUDE = "~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/ip62_models"
SIM_READY_REL = "../tr_1um_i2c_slave_async_sim_ready.spice"
VDD = 5.0

SLAVE_ADDR = 0x50
DATA_WR_VAL = 0xA5   # script/test_i2c_slave_async.py's own value
DATA_RD_VAL = 0x3C   # script/test_i2c_slave_async.py's own value

# script/gen_irsim_cmd_v9.py's own TX/RX pad lists (bit0..bit7), read
# directly off the SAME x1(OSS_FRAME_GIO) instantiation line this
# script itself parses SIM_READY_SRC's top .subckt pin order from --
# kept here as literal constants since they are net/pad NAMES, not
# derivable from the top .subckt's own pin list (which only has the
# P-numbers, not the tx/rx bit mapping).
TX_PADS = ["P11", "P12", "P13", "P14", "P6", "P5", "P4", "P3"]         # tx_data bit0..7
RX_NETS = ["NC_OUT11", "NC_OUT12", "NC_OUT13", "NC_OUT14",
           "NC_OUT6", "NC_OUT5", "NC_OUT4", "NC_OUT3"]                  # rx_data bit0..7
DIS_PAD = "P7"
SCL_PAD = "P1"
SDA_PAD = "P2"
RSTN_PAD = "P15"

# ---- SCL=100kHz timing ----
T_BIT = 10e-6      # 1 SCL cycle per bit, 100kHz
T_HALF = T_BIT / 2  # 5us
T_EDGE = 100e-9     # fast (100ns) drive edge for SCL/SDA_CTRL/RSTN -- far
                    # shorter than T_HALF, so bits are fully settled long
                    # before the opposite clock edge samples them.
T_HOLD = 300e-9     # 2026-09-02 root-cause fix (design_notes.md #107 系):
                    # output hold margin the testbench (as master) waits,
                    # AFTER SCL has fully finished falling, before changing
                    # SDA to the next bit's value. Before this fix, SDA's
                    # own T_EDGE ramp was scheduled to END at the exact same
                    # instant as the PRECEDING SCL falling edge (dt=0, fully
                    # overlapping ramps) -- confirmed via
                    # ngspice/TB/tb_start_pulse_isolated.spice (a standalone
                    # extraction of i2c_slave_async.v's start_pulse detector,
                    # start_pulse = scl & sda_d & ~sda_in with a DEL1 edge
                    # detector) that this exact detector has ZERO real
                    # margin at dt=0 -- any real buffer-chain skew pushes it
                    # negative (SDA arriving before scl_row2 internally) and
                    # the detector fires a spurious ~5.5ns start_pulse pulse,
                    # which the reset-stretch latch turns into a real ~28ns
                    # RSTB glitch hitting every SCL-domain flop at once
                    # (bit_cnt_0/1 etc.) -- this IS the mechanism behind the
                    # mid-cycle bit_cnt glitches seen in tb_chip_i2c.spice.
                    # NXP UM10204 (I2C-bus spec) itself explicitly addresses
                    # this: tHD;DAT's spec minimum is 0ns, but Rev.6 and
                    # earlier state "A device must internally provide a
                    # hold time of at least 300 ns for the SDA signal...to
                    # bridge the undefined region of the falling edge of
                    # SCL." Rather than add that 300ns confirmation delay
                    # inside the DUT's detector (a real sequential/stateful
                    # circuit, rejected as impractical), this testbench
                    # instead behaves like a spec-compliant master and
                    # provides the 300ns hold margin itself -- which is
                    # exactly the behavior the spec anticipates from a
                    # well-behaved master, and easily satisfiable since
                    # T_HOLD=300ns << T_HALF=5us.
T_RST_LOW = 500e-9   # RSTN held low this long before releasing
T_POST_RST_SETTLE = 2e-6   # idle (bus released, SCL high) after RSTN
                             # releases, before the first START
T_RESET_LOW_HOLD = 1e-6   # SCL held LOW from t=0 through this point (must
                            # cover T_RST_LOW+T_EDGE=600ns with margin) --
                            # 2026-09-02 root-cause fix: DFFRB's async RSTB
                            # only clears the SLAVE-stage output (QB), never
                            # the MASTER latch (net2/QM/net4 in the actual
                            # transistor netlist -- see design_notes.md for
                            # the full trace). While CK is HIGH, the slave
                            # stage is transparently tied to the master
                            # latch via a transmission gate, so if CK is
                            # still HIGH at the instant RSTB releases, Q
                            # immediately snaps to whatever arbitrary value
                            # the (never-yet-written) master latch settled
                            # to at simulation start, bypassing the reset
                            # entirely -- this is exactly what was happening
                            # with SCL held high from t=0 the whole
                            # reset-assert+release window. Holding SCL LOW
                            # through reset release instead lets the slave
                            # latch's own CK=LOW hold loop (QB<->net5<->QS)
                            # settle to the RSTB-forced value and keep it
                            # after release, before SCL is ever raised.
T_INTER_TXN_GAP = 5e-6      # idle between the write and read transactions
T_FINAL_SETTLE = 5e-6       # idle after the final STOP


def read_top_pin_order(text):
    """Read the chip's real top-level pin order directly from
    SIM_READY_SRC's own '.subckt tr_1um_i2c_slave_async ...' line --
    not hand-typed (same convention as gen_ring_osc_tb.py's
    read_ring_osc_pin_order())."""
    m = re.search(r"^\.subckt\s+tr_1um_i2c_slave_async\s+(.+)$", text, re.M)
    if not m:
        raise RuntimeError(f"'.subckt tr_1um_i2c_slave_async ...' not found in {SIM_READY_SRC}")
    return m.group(1).split()


class BusBuilder:
    """Builds clean, edge-limited PWL breakpoint lists for SCL and for
    this testbench's own SDA_CTRL (drive-low-when-high open-drain
    control), plus a record of sample points worth measuring."""

    def __init__(self, t0):
        self.t = t0
        self.scl = []
        self.sda_ctrl = []
        self.read_bit_samples = []   # (time, expected_bit) for the read data byte
        self.notes = []              # (time, text) for header comments
        self.master_bit_samples = []  # (time, expected_bit, label) for every
                                       # master-driven bit -- a self-check of
                                       # this generator's OWN PWL output,
                                       # independent of the DUT's response.
        self.byte_last_bit_edges = []  # (scl_rising_edge_time, label) for the
                                        # LAST (bit0) bit of every master_byte()
                                        # call -- the instant the DUT's
                                        # is_last_bit comparison/capture fires.
        self.all_bit_edges = []        # (scl_rising_edge_time, label, bit_index)
                                        # for EVERY bit of every master_byte()
                                        # call, not just the last -- needed to
                                        # sample bit_cnt's full trajectory
                                        # edge-by-edge instead of guessing from
                                        # a coarse plot.

    def _set(self, lst, level):
        if lst and lst[-1][1] != level:
            last_t, last_v = lst[-1]
            edge_t = max(last_t + 1e-12, self.t - T_EDGE)
            lst.append((edge_t, last_v))
            lst.append((self.t, level))
        else:
            lst.append((self.t, level))

    def _scl_set(self, level):
        self._set(self.scl, level)

    def _sda_set(self, level):
        self._set(self.sda_ctrl, level)

    def note(self, text):
        self.notes.append((self.t, text))

    def power_on_settle(self, low_hold, idle_duration, label=None):
        """SCL held LOW from t=0 through RSTN's release (low_hold must
        cover T_RST_LOW+T_EDGE with margin), THEN raised to the normal
        I2C idle-high state for idle_duration before the first START.
        2026-09-02 root-cause fix: see T_RESET_LOW_HOLD's comment and
        design_notes.md -- DFFRB's async RSTB only clears the slave-stage
        output, not the master latch, so if SCL/CK were already HIGH at
        the instant RSTN releases (as a naive "idle-high from t=0"
        stimulus would do), Q can snap to the master latch's undefined
        power-up value instead of the intended reset value. Holding SCL
        LOW across the release avoids that race."""
        if label:
            self.note(label)
        self._scl_set(0.0)
        self._sda_set(0.0)
        self.t += low_hold
        self._scl_set(VDD)
        self.t += idle_duration

    def idle(self, duration, label=None):
        if label:
            self.note(label)
        self._scl_set(VDD)
        self._sda_set(0.0)
        self.t += duration

    def start_condition(self):
        self.note("START")
        self._scl_set(VDD)
        self._sda_set(0.0)
        self.t += T_HALF
        self._sda_set(VDD)          # SDA 1->0 while SCL=1: START
        self.t += T_HALF
        self._scl_set(0.0)          # begin first bit's low phase

    def master_bit(self, bitval):
        """Master drives this bit (address bits, R/W bit, write-data
        bits). Precondition: SCL currently low.
        2026-09-02: T_HOLD margin inserted before changing SDA -- see
        T_HOLD's comment (I2C tHD;DAT spec guidance, fixes the
        start_pulse-detector race confirmed in
        tb_start_pulse_isolated.spice). edge_t/sample_t in master_byte()
        are computed from self.t at call time and are unaffected, since
        this only re-splits the existing low-phase wait (T_HOLD +
        (T_HALF-T_HOLD) == T_HALF)."""
        self.t += T_HOLD
        self._sda_set(VDD if bitval == 0 else 0.0)   # ctrl=VDD -> drive low -> bit 0
        self.t += T_HALF - T_HOLD
        self._scl_set(VDD)
        self.t += T_HALF
        self._scl_set(0.0)

    def master_byte(self, byte, label):
        self.note(f"{label} = 0x{byte:02X}")
        last_bit_edge_t = None
        for i in range(7, -1, -1):
            bitval = (byte >> i) & 1
            sample_t = self.t + T_HALF + T_HALF / 2   # mid SCL-high window
            self.master_bit_samples.append((sample_t, bitval, f"{label} bit{i}"))
            edge_t = self.t + T_HALF   # this bit's SCL rising edge
            self.all_bit_edges.append((edge_t, label, i))
            if i == 0:
                last_bit_edge_t = edge_t   # SCL rising edge of the last (R/W) bit
            self.master_bit(bitval)
        self.byte_last_bit_edges.append((last_bit_edge_t, label))

    def release_bit(self, label=None):
        """Master fully releases SDA for this bit period (slave, or the
        pull-up if the slave also releases, decides the level) --
        used for ACK-from-slave bits and for slave-driven read-data
        bits. Precondition: SCL currently low."""
        if label:
            self.note(label)
        self.t += T_HOLD   # 2026-09-02: see T_HOLD's comment
        self._sda_set(0.0)
        self.t += T_HALF - T_HOLD
        self._scl_set(VDD)
        self.t += T_HALF
        self._scl_set(0.0)

    def slave_data_bit(self, expected_bit):
        sample_t = self.t + T_HALF + T_HALF / 2   # mid SCL-high window
        self.read_bit_samples.append((sample_t, expected_bit))
        self.release_bit()

    def master_ack_bit(self, ack, label):
        """Master, as receiver, drives ack(0)/nack(1). Precondition:
        SCL currently low."""
        self.note(label)
        self.t += T_HOLD   # 2026-09-02: see T_HOLD's comment
        self._sda_set(VDD if ack == 0 else 0.0)
        self.t += T_HALF - T_HOLD
        self._scl_set(VDD)
        self.t += T_HALF
        self._scl_set(0.0)

    def stop_condition(self):
        self.note("STOP")
        self.t += T_HOLD   # 2026-09-02: see T_HOLD's comment
        self._sda_set(VDD)          # ensure driven low
        self.t += T_HALF - T_HOLD
        self._scl_set(VDD)          # SCL rises with SDA still low
        self.t += T_HALF
        self._sda_set(0.0)          # SDA released -> 0->1 while SCL=1: STOP
        self.t += T_HALF

    def finish(self):
        self._scl_set(VDD)
        self._sda_set(0.0)

    def pwl(self, lst):
        return " ".join(f"{t:.9g} {v:.3f}" for t, v in lst)


def build_sequence():
    b = BusBuilder(t0=0.0)
    # 2026-09-02: back to the realistic "SCL already idle-high from t=0"
    # stimulus (matches the real bus -- SCL is driven/pulled by whatever
    # external master, independent of this slave's own reset timing).
    # The earlier power_on_settle() SCL-held-low-through-reset testbench
    # workaround only ever protected the power-on reset event; it could
    # NOT have protected the START-triggered rst_scl_domain reset in
    # i2c_slave_async.v (rst_scl_domain = ~rst_n | start_pulse), since a
    # real START is BY DEFINITION "SDA falls while SCL=1" -- CK is always
    # HIGH at that exact moment, unavoidably, so the same DFFRB
    # master-latch race would have resurfaced there regardless. The real
    # fix is now in the DFFRB cell itself (simulations/DFFRB.spice, MM27 --
    # see design_notes.md), so this reverts to the plain, realistic idle()
    # stimulus to verify the circuit-level fix on its own.
    b.idle(T_POST_RST_SETTLE, label="post-reset settle (bus idle)")

    # ---- WRITE transaction: S, ADDR+W, ACK, 0xA5, ACK, P ----
    b.start_condition()
    addr_w = (SLAVE_ADDR << 1) | 0
    b.master_byte(addr_w, "ADDR+W")
    b.release_bit("ACK (slave, address/write)")
    b.master_byte(DATA_WR_VAL, "DATA (write)")
    b.release_bit("ACK (slave, data)")
    b.stop_condition()

    b.idle(T_INTER_TXN_GAP, label="inter-transaction idle")

    # ---- READ transaction: S, ADDR+R, ACK, DATA (slave drives), NACK, P ----
    b.start_condition()
    addr_r = (SLAVE_ADDR << 1) | 1
    b.master_byte(addr_r, "ADDR+R")
    b.release_bit("ACK (slave, address/read)")
    b.note(f"DATA (read, expect 0x{DATA_RD_VAL:02X})")
    for i in range(7, -1, -1):
        b.slave_data_bit((DATA_RD_VAL >> i) & 1)
    b.master_ack_bit(1, "NACK (master, ends read)")
    b.stop_condition()

    b.idle(T_FINAL_SETTLE, label="final settle")
    b.finish()
    return b


TB_HEADER = """\
* tb_chip_i2c.spice -- auto-generated by script/gen_chip_tb_v9.py
* DO NOT hand-edit -- regenerate instead.
*
* Whole-chip (RING_OSC excluded) I2C WRITE-then-READ testbench at
* SCL=100kHz, using the real TR-1um transistor models (same ip62_models
* include already confirmed working for RING_OSC's own ngspice
* testbench, script/gen_ring_osc_tb.py) and ngspice/tr_1um_i2c_slave_
* async_sim_ready.spice (the LVS-confirmed chip netlist, M->X + NMOSE->
* MNE converted -- see script/gen_chip_sim_ready_v9.py).
*
* Protocol (mirrors script/test_i2c_slave_async.py's own bus-functional
* model exactly -- same SLAVE_ADDR/DATA values/bit order/ACK convention,
* just re-timed to a clean 100kHz clock instead of that model's
* arbitrary-T relative timing):
*   WRITE: S, ADDR+W(0x{ADDR_W:02X}), ACK, DATA=0x{DATA_WR:02X}, ACK, P
*   READ : S, ADDR+R(0x{ADDR_R:02X}), ACK, DATA=0x{DATA_RD:02X} (slave-driven), NACK, P
*
* DIS (P7) held HIGH the whole run (Hi-Z / tx_data-input mode) so the 8
* shared tx/rx pads never contend with this testbench's own TX drive --
* rx_data is instead observed at each pad's own internal receiver net
* (NC_OUT.. ), which reflects the pad regardless of DIS (see this
* script's own module docstring, and gen_irsim_cmd_v9.py's identical
* convention). tx_data is held at 0x{DATA_RD:02X} for the whole run (only
* consumed during the read).

.include '{MODEL_INCLUDE}'
.include '{SIM_READY_REL}'

.param vdd={VDD}

vvdd VDD 0 DC {VDD}
vvss VSS 0 DC 0

* RSTN: low for {T_RST_LOW_NS:.0f}ns (power-on reset), then a fast edge to VDD,
* held for the rest of the run -- real async reset via each DFFRB's own
* RSTB pin (no IRSIM-style QM/QS force needed; that was an IRSIM
* switch-level-solver-only workaround, see this script's own docstring).
vrstn {RSTN_PAD} 0 PWL(0 0 {T_RST_LOW:.9g} 0 {T_RST_LOW_EDGE:.9g} {VDD})

* DIS: held high the whole run (see docstring).
vdis {DIS_PAD} 0 DC {VDD}

* P9/P10 (RING_OSC.OUTD/OUT in the full chip -- unused and otherwise
* floating here, since RING_OSC is excluded from this netlist). Tied to
* VSS via a large resistor purely for SPICE DC-path/convergence safety
* (each pad's own internal ESD diode already provides some finite
* leakage path to VSS, but an explicit high-value tie avoids relying on
* that for the operating-point solve).
rp9 P9 VSS 1G
rp10 P10 VSS 1G

* tx_data (bit0..7 = {TX_PADS}), held at 0x{DATA_RD:02X} for the whole run.
{TX_SOURCES}

* SCL: master clock, 100kHz during bus activity (idle high otherwise).
vscl {SCL_PAD} 0 PWL({SCL_PWL})

* SDA open-drain bus: this testbench's own master drive (voltage-
* controlled switch to VSS, gated by SDA_CTRL) in parallel with an
* external {RPU_KOHM:.0f}k pull-up to VDD (per user instruction -- the chip
* itself has no on-chip SDA pull-up, design_notes.md 76.29-76.38) and
* the DUT's own internal SDA driver (already part of the DUT netlist).
vsda_ctrl SDA_CTRL 0 PWL({SDA_PWL})
.model SDASW SW(RON=10 ROFF=1MEG VT={SW_VT} VH={SW_VH})
ssda {SDA_PAD} 0 SDA_CTRL 0 SDASW
rpu {SDA_PAD} VDD {RPU_KOHM:.0f}k

* DUT instantiation -- pin order read directly from ngspice/tr_1um_i2c_
* slave_async_sim_ready.spice's own '.subckt tr_1um_i2c_slave_async ...'
* line (not hand-typed), see read_top_pin_order().
xdut {XDUT_NETS} tr_1um_i2c_slave_async

.tran {TSTEP} {TSTOP}

* ---- sample points: read-data bits (mid SCL-high window of each of
* the 8 slave-driven bits during the read transaction) ----
{READ_MEASURES}

* ---- ACK sample points (expect ~0V = ACK asserted) ----
{ACK_MEASURES}

* ---- diagnostic: internal core state (busy/addr_match/rw), to
* localize a non-responsive-bus result -- see gen_chip_tb_v9.py's own
* module docstring / build_tb() comment for why these were added ----
{DIAG_MEASURES}

* ---- diagnostic: this generator's OWN driven bus level self-check
* (independent of the DUT) for every master-driven address/data bit ----
{TX_CHECK_MEASURES}

* ---- diagnostic: internal address shift-register (shreg_0..shreg_6,
* inside xdut.x2 = i2c_slave_async_nrow_fm) snapshot right after each
* address byte's last-bit SCL edge ----
{SHREG_MEASURES}

* ---- diagnostic: clock-tree (scl_row0 vs scl_row1) and phase-FSM
* (phase_0/1/2, x2-internal addr_match/rw) probes ----
{CLK_PHASE_MEASURES}

* ---- diagnostic: exact internal comparator-chain nodes (hand-traced
* from the actual gate-level netlist) ----
{CHAIN_MEASURES}

* ---- diagnostic: bit_cnt_0/1/2 + last_bit_pending numeric trajectory at
* every ADDR+W bit edge (edge1..edge8) ----
{BITCNT_MEASURES}

* ---- diagnostic: SDA release slew (pull-up charge time) ----
{SLEW_MEASURE}

.control
  * ngspice only keeps the FULL time-history of a node available for a
  * later "write"/"plot"/vector-slice if it was explicitly "save"d before
  * "run" -- .measure works without this (it evaluates incrementally
  * during the run), which is why a real local run's .measure results
  * for these exact internal nodes succeeded while a later "write"/"plot"
  * of the same nodes (added without a matching "save") failed with
  * "no such vector". Save the full diagnostic node set up front so the
  * .raw file this generates actually contains their waveforms.
  save all

  run

  print {READ_PRINTS}
  print {ACK_PRINTS}
  print {DIAG_PRINTS}
  print {TX_CHECK_PRINTS}
  print {SHREG_PRINTS}
  print {CLK_PHASE_PRINTS}
  print {CHAIN_PRINTS}
  print {BITCNT_PRINTS}
  print sda_release_trise

  * rx_data after the write transaction's ACK (expect 0x{DATA_WR:02X}):
  * bit0..7 = {RX_NETS}
  print {RX_PRINTS}

  set filetype=ascii
  * (2026-09-02: dropped the old scl_row0/scl_row1/_079_/_092_/_103_/
  * _104_/_059_/_061_ probes here -- those were auto-generated Yosys net
  * names from the pre-v5 synthesis and no longer exist/no longer refer
  * to the same nodes after resynthesis; comparator-chain logic was
  * already confirmed correct at the netlist level, so they're not
  * needed for ongoing verification. bit_cnt_0/1/2, phase_0/1/2,
  * last_bit_pending, shreg_0-6 are stable RTL-level register names and
  * kept.)
  write tb_chip_i2c.raw v({SCL_PAD}) v({SDA_PAD}) v({RSTN_PAD}) {RX_PLOTS} v(xdut.NC_CORE_busy) v(xdut.NC_CORE_addr_match) v(xdut.NC_CORE_rw) i(vvdd) v(xdut.x2.last_bit_pending) v(xdut.x2.phase_0) v(xdut.x2.phase_1) v(xdut.x2.phase_2) v(xdut.x2.shreg_0) v(xdut.x2.shreg_1) v(xdut.x2.shreg_2) v(xdut.x2.shreg_3) v(xdut.x2.shreg_4) v(xdut.x2.shreg_5) v(xdut.x2.shreg_6) v(xdut.x2.bit_cnt_0) v(xdut.x2.bit_cnt_1) v(xdut.x2.bit_cnt_2)

  * interactive viewing (see tb_ring_osc.spice's own note: ignored
  * harmlessly in -b batch mode without a display; run without -b, or
  * `ngspice -b tb_chip_i2c.spice` then load tb_chip_i2c.raw in any
  * viewer, e.g. `ngspice -r tb_chip_i2c.raw` + `plot` at the prompt).
  plot v({SCL_PAD}) v({SDA_PAD})
  plot v({RSTN_PAD})
  plot {RX_PLOTS}
  plot v(xdut.NC_CORE_busy) v(xdut.NC_CORE_addr_match) v(xdut.NC_CORE_rw)

  * ---- DFFRB slave-hold race diagnostic (bit_cnt_0's flop, x_505_) ----
  * bit_cnt_0 (Q) was seen to collapse from 5V to ~0V exactly in sync with
  * CK's own falling edge between edge1(17us) and edge2(27us) instead of
  * holding through the whole low phase. The earlier point-sample sweep
  * only showed the value AFTER the collapse had already completed (one
  * full 1us sample past it); these plots zoom into the actual transition
  * window (CK is known to fall somewhere between t=21.5us and t=22.5us)
  * so the real shape of the glitch -- fast digital race vs. slow settle,
  * which node moves first, whether QM/net2 (master) stay clean while
  * QS/net5 (slave) alone glitch -- can be read directly off the traces.
  * Widen/narrow with another `xlimit a b` + `plot ...` at the ngspice
  * prompt once the approximate glitch time is visible.
  plot v(xdut.x2._156__row1) v(xdut.x2.bit_cnt_0) xlimit 2.1e-05 2.3e-05
  plot v(xdut.x2.x_505_.qm) v(xdut.x2.x_505_.net2) xlimit 2.1e-05 2.3e-05
  plot v(xdut.x2.x_505_.qs) v(xdut.x2.x_505_.net5) xlimit 2.1e-05 2.3e-05
  plot v(xdut.x2._212_) v(xdut.x2._066_) xlimit 2.1e-05 2.3e-05
  plot v(xdut.x2._156__row1) v(xdut.x2.x_505_.qm) v(xdut.x2.x_505_.qs) v(xdut.x2._212_) v(xdut.x2.bit_cnt_0) xlimit 2.1e-05 2.3e-05
.endc

.end
"""


def build_tb():
    src_text = open(SIM_READY_SRC).read()
    pins = read_top_pin_order(src_text)
    print(f"tr_1um_i2c_slave_async top-level pin order (read directly from the file): {pins}")

    xdut_nets = " ".join(pins)

    b = build_sequence()

    tx_sources = []
    for i, pad in enumerate(TX_PADS):
        bit = (DATA_RD_VAL >> i) & 1
        tx_sources.append(f"vtx{i} {pad} 0 DC {VDD if bit else 0.0}")

    read_measures = []
    read_prints = []
    for i, (t, expect) in enumerate(b.read_bit_samples):
        read_measures.append(
            f".measure tran rd_bit{i} FIND v({SDA_PAD}) AT={t:.9g}  "
            f"$ expect {'~0V (bit=0)' if expect == 0 else '~VDD (bit=1)'}"
        )
        read_prints.append(f"rd_bit{i}")

    # ACK sample times: mid SCL-high of each release_bit() call tagged
    # "ACK ..." -- re-derive from the notes list (time, text) rather
    # than re-running the sequence, so this stays exactly in sync.
    ack_measures = []
    ack_prints = []
    ack_idx = 0
    for note_t, text in b.notes:
        if text.startswith("ACK") or text.startswith("NACK"):
            sample_t = note_t + T_HALF + T_HALF / 2
            name = f"ack{ack_idx}"
            ack_measures.append(
                f".measure tran {name} FIND v({SDA_PAD}) AT={sample_t:.9g}  $ {text}"
            )
            ack_prints.append(name)
            ack_idx += 1

    # ---- diagnostic measures: internal core state, to localize a
    # non-responsive-bus result (all rd_bit*/ack* pinned at the pull-up
    # rail) to either "START/reset never reached the core" vs.
    # "reached the core but address decode/ACK-drive failed". Added
    # after a real local run showed ALL 12 rd_bit*/ack* measures stuck
    # at ~4.95V (the bare pull-up level) -- i.e. SDA is never pulled low
    # by EITHER side's own drive at any sampled point, including the
    # very first (write-address) ACK window.
    diag_measures = []
    diag_prints = []
    for note_t, text in b.notes:
        if text == "START":
            t = note_t + T_HALF + T_HALF / 2
            diag_measures.append(
                f".measure tran busy_after_start FIND v(xdut.NC_CORE_busy) AT={t:.9g}  "
                f"$ expect ~VDD (busy asserted shortly after START)"
            )
            diag_prints.append("busy_after_start")
            break  # only need the first START (write transaction)
    addr_ack_idx = 0
    for note_t, text in b.notes:
        if text.startswith("ACK") and "address" in text:
            # 2026-09-02: sample near the END of the ACK bit's SCL-high
            # window (T_HALF-200ns in, not the midpoint) -- now that the
            # T_HOLD fix keeps bit_cnt/last_bit_pending on the testbench's
            # own real-time schedule (no more multi-edge lag), addr_match
            # can transition close to the window's start; sampling right
            # at the old midpoint left too little margin and made the
            # FIND-at-fixed-AT measure sensitive to run-to-run SPICE
            # adaptive-timestep jitter landing on either side of the edge.
            t = note_t + T_HALF + T_HALF - 200e-9
            tag = "write" if "write" in text else "read"
            diag_measures.append(
                f".measure tran addr_match_{tag} FIND v(xdut.NC_CORE_addr_match) AT={t:.9g}  "
                f"$ expect ~VDD if address 0x{SLAVE_ADDR:02X} matched ({text})"
            )
            diag_measures.append(
                f".measure tran rw_{tag} FIND v(xdut.NC_CORE_rw) AT={t:.9g}  "
                f"$ expect {'~0V (write)' if tag == 'write' else '~VDD (read)'}"
            )
            # WHEN-based crossing measure too (robust regardless of exact
            # settling time -- reports the actual transition instant
            # rather than a single fixed-time sample).
            diag_measures.append(
                f".measure tran addr_match_{tag}_x1 WHEN v(xdut.NC_CORE_addr_match)=2.5 "
                f"RISE={addr_ack_idx + 1}  $ addr_match rise #{addr_ack_idx + 1} ({text})"
            )
            diag_prints.append(f"addr_match_{tag}")
            diag_prints.append(f"rw_{tag}")
            diag_prints.append(f"addr_match_{tag}_x1")
            addr_ack_idx += 1

    # ---- further diagnostics, added after busy_after_start=VDD but
    # addr_match_write/addr_match_read=0V showed the DUT sees START/
    # reset fine but never decodes the address -- need to know (a)
    # whether THIS GENERATOR's own PWL actually puts the intended 0xA0/
    # 0xA1 bit pattern onto the bus (self-check, independent of the
    # DUT), and (b) what the DUT's own address shift register (shreg_0.
    # .shreg_6, i2c_slave_async_nrow_fm's internal net names post-
    # debracket()) actually captured at the moment the last (R/W) bit's
    # SCL edge fires -- and (c) whether SDA's release (pull-up-driven)
    # edge is actually settling well before that edge, since T_HALF=5us
    # of margin assumes fast RC settling that hasn't been checked
    # against the real 10k-pullup + parasitic-node-capacitance time
    # constant (design_notes.md 76.37-76.40 flagged exactly this class
    # of bug for the IRSIM stimulus, fixed there with an explicit 500ns
    # settle margin -- this SPICE testbench should already have far
    # more margin (5us) if the real RC is anywhere near IRSIM's implied
    # scale, but that assumption is unverified here).
    tx_check_measures = []
    tx_check_prints = []
    for t, expect, label in b.master_bit_samples:
        name = "tx_" + re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
        tx_check_measures.append(
            f".measure tran {name} FIND v({SDA_PAD}) AT={t:.9g}  "
            f"$ self-check: this generator's OWN driven bus level, {label} "
            f"(expect {'~0V (bit=0)' if expect == 0 else '~VDD (bit=1)'})"
        )
        tx_check_prints.append(name)

    SHREG_NETS = [f"shreg_{i}" for i in range(7)]
    shreg_measures = []
    shreg_prints = []
    for edge_t, label in b.byte_last_bit_edges:
        if not label.startswith("ADDR"):
            continue
        tag = "write" if "+W" in label else "read"
        # 2026-09-02: bumped from 200ns to 2us margin -- the _156__row1
        # buffer now drives all 9 write-address-critical-group flops
        # (matching the same fanout count that showed visible overshoot/
        # ringing on scl_row0 earlier in this investigation), and 200ns
        # was occasionally landing mid-settling, producing a bogus
        # non-monotonic bit_cnt trajectory across edges despite the
        # flops being logically/clock-wise correct. 2us is still safely
        # inside the 5us (T_HALF) half-bit-period margin before the next
        # real edge.
        sample_t = edge_t + 2e-6   # well after the last address bit's
                                    # SCL rising edge -- the instant the
                                    # DUT's is_last_bit comparison fires
        for n in SHREG_NETS:
            name = f"{n}_{tag}"
            shreg_measures.append(
                f".measure tran {name} FIND v(xdut.x2.{n}) AT={sample_t:.9g}  "
                f"$ internal address shift-reg bit, right after the {label} "
                f"last-bit SCL edge"
            )
            shreg_prints.append(name)

    # ---- clock-tree / phase-FSM diagnostic: addr_match/rw/phase_0-2 all
    # share ONE clock buffer (scl_row0, per the sim_ready file's own
    # "xu_buf_scl_row0 VDD scl_buf scl_row0 GND BUF_X1" instance),
    # structurally identical to the scl_row1/2/3 buffers that clock
    # bit_cnt/shreg/rx_data (which DID correctly toggle/shift, per the
    # shreg diagnostic above) -- if scl_row0 itself isn't toggling, or
    # "phase" never leaves its reset value, that alone would explain
    # addr_match/rw staying low while shreg still shifts correctly.
    clk_phase_measures = []
    clk_phase_prints = []

    def add_probe(name, net, t, note):
        clk_phase_measures.append(f".measure tran {name} FIND v({net}) AT={t:.9g}  $ {note}")
        clk_phase_prints.append(name)

    start_t = None
    for note_t, text in b.notes:
        if text == "START":
            start_t = note_t
            break

    bit7_entries = [s for s in b.master_bit_samples if s[2] == "ADDR+W bit7"]
    # (2026-09-02: the scl_row0/scl_row1_lo/hi probes that used to live here
    # were removed -- those specific internal net names no longer exist
    # after the v5 RTL fix + resynthesis (the row-buffer partition changed,
    # and the flops' clock net is now named "_156_"/"_156__row0..3", an
    # auto-generated Yosys name that isn't stable across resyntheses, so
    # hardcoding it here would just go stale again next time. bit_cnt_0/
    # phase_0/last_bit_pending below are stable RTL-level register names
    # and don't have this problem.)

    if start_t is not None:
        t_after_start = start_t + T_HALF + T_HALF / 2
        add_probe("phase0_after_start", "xdut.x2.phase_0", t_after_start, "phase bit0 shortly after START")
        add_probe("phase1_after_start", "xdut.x2.phase_1", t_after_start, "phase bit1 shortly after START")
        add_probe("phase2_after_start", "xdut.x2.phase_2", t_after_start, "phase bit2 shortly after START")

        # ---- diagnostic: is bit_cnt ALREADY nonzero before bit7's own SCL
        # rising edge ever fires? The edge1..edge8 trajectory came back
        # shifted exactly one edge early vs. the ideal zero-delay model
        # (real bit_cnt after edge1 == ideal's value after edge2, in
        # lockstep all the way through) -- consistent with either (a) a
        # spurious extra clock pulse landing on bit_cnt's clock net before
        # bit7's real edge (e.g. from START-detection logic), or (b) bit_cnt
        # simply being pre-loaded/incremented once as part of reset-release
        # or START handling, by design, in a way this hand-derived ideal
        # model didn't account for. These two probes bracket exactly when
        # any such extra increment would have to happen: right when START
        # begins (before any SCL toggling within start_condition()), and
        # right when SCL first drops to begin bit7's low phase (right
        # before bit7's own rising edge, i.e. this testbench's "edge1").
        t_at_start_begin = start_t + 1e-9
        t_before_bit7_edge = start_t + T_HALF + T_HALF + 200e-9
        for tag, t in (("at_start_begin", t_at_start_begin), ("before_bit7_edge", t_before_bit7_edge)):
            add_probe(f"bit_cnt_0_{tag}", "xdut.x2.bit_cnt_0", t, f"bit_cnt_0 {tag}")
            add_probe(f"bit_cnt_1_{tag}", "xdut.x2.bit_cnt_1", t, f"bit_cnt_1 {tag}")
            add_probe(f"bit_cnt_2_{tag}", "xdut.x2.bit_cnt_2", t, f"bit_cnt_2 {tag}")
            add_probe(f"lbp_{tag}", "xdut.x2.last_bit_pending", t, f"last_bit_pending {tag}")

        # ---- diagnostic: fine-grained sweep across reset release
        # (RSTN_PAD: 0V for T_RST_LOW=500ns, rises to VDD at 600ns) through
        # the post-reset idle window (idle ends at t=2000ns=start_t) --
        # bit_cnt reads 1 (not 0) at BOTH the start-of-idle and
        # right-before-bit7 probes above, with scl_row0 never toggling in
        # between (bus held idle, SCL high, no master_bit() calls yet) --
        # meaning bit_cnt became nonzero either (a) during/at reset release
        # itself with no real clock edge involved (a reset-clear failure,
        # not a clock-race), or (b) from some transient right at reset
        # release. These probes bracket t=300ns (mid-reset, RSTB should
        # still be asserted low) through t=2000ns at fine granularity, on
        # bit_cnt_0 + scl_row0 + the reset net itself (_008_), to find the
        # exact instant of the 0->1 transition and whether scl_row0 (the
        # flop's own clock) shows any edge there at all.
        for tag, t in (
            ("rst_300n", 300e-9),
            ("rst_550n", 550e-9),
            ("rst_650n", 650e-9),   # just after RSTN_PAD's rising edge completes (600ns)
            ("rst_900n", 900e-9),
            ("rst_1200n", 1200e-9),
            ("rst_1600n", 1600e-9),
        ):
            add_probe(f"bit_cnt_0_{tag}", "xdut.x2.bit_cnt_0", t, f"bit_cnt_0 at {tag}")
            add_probe(f"phase_0_{tag}", "xdut.x2.phase_0", t, f"phase_0 at {tag} (for comparison -- resets correctly per earlier probes)")

    # (NOTE: an earlier revision also probed v(xdut.x2.addr_match) and
    # v(xdut.x2.rw) directly, bypassing the xdut-level NC_CORE_* alias --
    # removed after a real run showed "no such vector" for both: addr_
    # match/rw are x2's own formal PORT names, and SPICE merges a
    # subckt's port node into whatever net is wired to it at the call
    # site, so it has no separate "x2.addr_match" identity distinct from
    # "xdut.NC_CORE_addr_match" -- only genuinely internal, non-port nets
    # like shreg_N keep their own x2-scoped name.)

    # ---- diagnostic: exact internal comparator-chain nodes, added after
    # a hand-trace of the actual gate-level netlist (NOR4/OR4/NAND2/MUX2
    # feeding the addr_match/rw DFFRBs, all clocked by scl_row0) showed
    # that, GIVEN the shreg values already confirmed correct, the
    # comparator SHOULD combinationally evaluate to a match and the load
    # -vs-hold MUX select (net "_092_") SHOULD select "load" on the
    # is_last_bit edge -- i.e. addr_match SHOULD assert on paper. These
    # probe the actual SPICE-simulated value of every node in that
    # chain, at the same instant as the shreg snapshot, to find exactly
    # where the real simulation diverges from the hand-traced expectation
    # (net names are internal, from ngspice/tr_1um_i2c_slave_async_sim_
    # ready.spice's own i2c_slave_async_nrow_fm body -- not derivable
    # from RTL names, only from directly reading that generated netlist).
    # 2026-09-02: dropped _079_/_092_/_103_/_104_/_059_/_061_ (the
    # comparator-chain internal probes from the earlier investigation) --
    # those were Yosys auto-generated net names specific to the
    # pre-v5 synthesis and no longer refer to the same nodes (or may not
    # exist at all) after resynthesis; the comparator logic itself was
    # already confirmed correct at the netlist level, not the actual bug,
    # so they aren't needed for ongoing verification. Only stable
    # RTL-level register names kept.
    CHAIN_NETS = {
        "last_bit_pending": "last_bit_pending",   # is_last_bit
        "phase_0": "phase_0",
        "phase_1": "phase_1",
        "phase_2": "phase_2",
    }
    chain_measures = []
    chain_prints = []
    for edge_t, label in b.byte_last_bit_edges:
        if not label.startswith("ADDR"):
            continue
        tag = "write" if "+W" in label else "read"
        sample_t = edge_t + 2e-6   # see shreg_measures' identical margin-bump comment above
        for tag_name, net in CHAIN_NETS.items():
            name = f"{tag_name}_{tag}"
            chain_measures.append(
                f".measure tran {name} FIND v(xdut.x2.{net}) AT={sample_t:.9g}  "
                f"$ comparator-chain node, right after the {label} last-bit SCL edge"
            )
            chain_prints.append(name)

    # ---- diagnostic: exact bit_cnt_0/1/2 + last_bit_pending trajectory at
    # EVERY bit edge of ADDR+W (not just the last bit like the shreg/chain
    # probes above) -- a coarse interactive plot of this same window looked
    # like bit_cnt was NOT counting 1..7 monotonically (e.g. sitting at one
    # value across an edge where it should have changed), which would
    # contradict the ideal zero-delay digital-logic simulation (bit_cnt
    # should read 1,2,3,4,5,6,7,0 after edges 1-8 respectively, with
    # last_bit_pending going high exactly at edge 7). Numeric .measure
    # samples remove any ambiguity from reading a coarse plot by eye.
    bitcnt_measures = []
    bitcnt_prints = []
    for edge_t, label, bit_idx in b.all_bit_edges:
        if label != "ADDR+W":
            continue
        sample_t = edge_t + 2e-6   # see shreg_measures' identical margin-bump comment above
        for tag_name, net in (
            ("bit_cnt_0", "bit_cnt_0"),
            ("bit_cnt_1", "bit_cnt_1"),
            ("bit_cnt_2", "bit_cnt_2"),
            ("lbp", "last_bit_pending"),
        ):
            name = f"{tag_name}_edge{8 - bit_idx}"   # edge1..edge8, MSB-first
            bitcnt_measures.append(
                f".measure tran {name} FIND v(xdut.x2.{net}) AT={sample_t:.9g}  "
                f"$ {net} 2us after ADDR+W bit{bit_idx}'s SCL rising edge "
                f"(edge {8 - bit_idx} of 8)"
            )
            bitcnt_prints.append(name)

    # ---- diagnostic: bit_cnt_0's LSB should simply TOGGLE every real
    # clock edge (D0=NOT(Q0) is the standard up-counter LSB pattern) --
    # observed edge1..edge8 trajectory is 1,1,2,1,2,3,4,5, i.e. bit_cnt_0
    # (LSB) toggles correctly 1,0,1,0,1,0,1 from edge2 onward but FAILS
    # to toggle specifically between edge1(t=17us) and edge2(t=27us) --
    # reproduced IDENTICALLY across two independent runs at two different
    # sample-margin settings (200ns and 2us), ruling out a settling-time/
    # measurement artifact. Fine sweep across that one 10us window (every
    # 1us) on bit_cnt_0 and the actual shared clock net (_156__row1) to
    # see directly whether there's a missed edge, a double-pulse that
    # cancels out, or a genuine stuck value.
    # (uses add_probe(), which appends into clk_phase_measures/prints above)
    edge1_entries = [e for e in b.all_bit_edges if e[1] == "ADDR+W" and e[2] == 7]
    if edge1_entries:
        edge1_t = edge1_entries[0][0]
        for k in range(21):  # 17.5us .. 37.5us in 1us steps, spanning edge1->edge3
            t = edge1_t + 0.5e-6 + k * 1e-6
            add_probe(f"fine_bitcnt0_t{k}", "xdut.x2.bit_cnt_0", t, f"bit_cnt_0 fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_ck_t{k}", "xdut.x2._156__row1", t, f"_156__row1 (shared clock net) fine sweep point {k} ({t*1e6:.1f}us)")
            # diagnostic round 2: bit_cnt_0 tracked CK's own level almost
            # exactly (both edges, not just the rising edge) across the
            # first fine sweep -- that's consistent with RSTB (shared by
            # ALL 9 write-address-critical DFFRB flops, net _016_ =
            # NOR(rst_scl_domain_held, rst_scl_domain_raw)) itself
            # glitching low in sync with the clock, forcing QB high (Q low)
            # via MM26 every time it dips, instead of a real edge-triggered
            # capture. Probe the whole reset-stretch SR-latch chain
            # (u_rst_stretch_q/u_rst_stretch_qn from the v5 RTL fix,
            # preserved by name through synthesis) alongside RSTB itself to
            # see directly whether it's misbehaving during normal (non-
            # reset) clocking.
            add_probe(f"fine_rstb_t{k}", "xdut.x2._016_", t, f"_016_ (RSTB, shared by write-addr critical group) fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_held_t{k}", "xdut.x2.rst_scl_domain_held", t, f"rst_scl_domain_held fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_qn_t{k}", "xdut.x2.rst_stretch_qn", t, f"rst_stretch_qn fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_raw_t{k}", "xdut.x2._143_", t, f"_143_ (rst_scl_domain_raw) fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_clr_t{k}", "xdut.x2._144_", t, f"_144_ (rst_stretch_clr) fine sweep point {k} ({t*1e6:.1f}us)")
            # diagnostic round 3: RSTB (_016_) stayed rock-solid at 5.0V
            # across the whole window (round 2 data) -- the reset-stretch
            # network is NOT glitching, ruling that hypothesis out
            # completely. Q (bit_cnt_0) still tracked CK almost exactly.
            # Only two possibilities remain: (a) D itself (_066_, the
            # combinational next-state input) is glitching in sync with CK
            # for a genuine RTL/synthesis reason, or (b) DFFRB's internal
            # dynamic hold nodes (master net2/net4/QM, slave net5/QS/QB)
            # are not holding statically -- these are TG-coupled dynamic
            # nodes with NO explicit static keeper, sized for fast (MHz)
            # clocking; at 100kHz SCL the ~5us hold phase may be far longer
            # than these nodes can retain charge without decaying/glitching.
            # Probe D directly plus every internal dynamic node of this
            # exact flop instance (x_505_) to distinguish the two.
            add_probe(f"fine_d_t{k}", "xdut.x2._066_", t, f"_066_ (D input to bit_cnt_0's flop) fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_qb_t{k}", "xdut.x2._212_", t, f"_212_ (QB output of bit_cnt_0's flop) fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_qm_t{k}", "xdut.x2.x_505_.qm", t, f"internal QM (master latch out) of x_505_ fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_net2_t{k}", "xdut.x2.x_505_.net2", t, f"internal net2 (master dynamic node) of x_505_ fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_qs_t{k}", "xdut.x2.x_505_.qs", t, f"internal QS (slave latch out) of x_505_ fine sweep point {k} ({t*1e6:.1f}us)")
            add_probe(f"fine_net5_t{k}", "xdut.x2.x_505_.net5", t, f"internal net5 (slave dynamic node) of x_505_ fine sweep point {k} ({t*1e6:.1f}us)")

        # diagnostic round 4: QS/net5 are NOT floating dynamic nodes --
        # confirmed by circuit inspection (user correction): at CK=0, QS is
        # actively driven via the TG from net5, and net5 is a proper static
        # CMOS inverter output (MM9/MM12) fed by QB -- a real cross-coupled
        # static latch, not a leaky dynamic node. So the 1us-grid sweep
        # above, which only sees the AFTERMATH of the collapse (already
        # settled to ~0V one full sample past the edge), cannot be
        # explained by charge leakage over microseconds. The remaining
        # candidate is a genuine RACE right at the CK transition itself:
        # CKB is generated by ONE inverter from CK (MM20/21) while CKP is
        # generated by a SECOND inverter from CKB (MM23/24) -- CKP lags CKB
        # by one gate delay, during which BOTH the transparent pair
        # (MM5/MM6) and the hold pair (MM16/MM14) are left with only their
        # NMOS half active. User asked to look at this directly as a
        # waveform rather than more .measure points -- see the `plot`
        # block added near the end of .control, zoomed into the
        # t4(21.5us)-t5(22.5us) window where the collapse happens, for CK,
        # QM/net2 (master), QS/net5 (slave), QB, D and bit_cnt_0 overlaid.
        # (An earlier attempt to chain a WHEN-based .measure result into
        # later AT='ck_fall_e12+...' expressions failed --
        # "Undefined parameter [ck_fall_e12]" -- ngspice did not accept
        # that inter-measure parameter chaining here, so this round uses
        # save all + plot/xlimit instead, which needs no such chaining.)

        # diagnostic round 5: interactive `plot` showed bit_cnt_1 apparently
        # staying high for many clock periods in a row (not toggling every
        # edge like a normal counter bit should), and last_bit_pending/_004_
        # never asserting through 100us -- but reading exact transition
        # times off a small plotted waveform is unreliable. These are
        # standalone WHEN-based .measure statements (no inter-measure
        # parameter chaining, unlike the failed ck_fall_e12 attempt above)
        # to get the EXACT crossing times of bit_cnt_0/1/2, _004_ (D input
        # to last_bit_pending) and last_bit_pending itself, so the real
        # counting sequence can be reconstructed precisely instead of
        # eyeballed off a plot.
        for j in range(1, 9):
            clk_phase_measures.append(f".measure tran bc0_x{j} WHEN v(xdut.x2.bit_cnt_0)=2.5 CROSS={j}  $ bit_cnt_0 crossing #{j}")
            clk_phase_prints.append(f"bc0_x{j}")
        for j in range(1, 7):
            clk_phase_measures.append(f".measure tran bc1_x{j} WHEN v(xdut.x2.bit_cnt_1)=2.5 CROSS={j}  $ bit_cnt_1 crossing #{j}")
            clk_phase_prints.append(f"bc1_x{j}")
        for j in range(1, 5):
            clk_phase_measures.append(f".measure tran bc2_x{j} WHEN v(xdut.x2.bit_cnt_2)=2.5 CROSS={j}  $ bit_cnt_2 crossing #{j}")
            clk_phase_prints.append(f"bc2_x{j}")
        clk_phase_measures.append(".measure tran d004_x1 WHEN v(xdut.x2._004_)=2.5 RISE=1  $ _004_ (D of last_bit_pending) first rise")
        clk_phase_prints.append("d004_x1")
        clk_phase_measures.append(".measure tran lbp_x1 WHEN v(xdut.x2.last_bit_pending)=2.5 RISE=1  $ last_bit_pending first rise")
        clk_phase_prints.append("lbp_x1")
        clk_phase_measures.append(".measure tran ck_x1 WHEN v(xdut.x2._156__row1)=2.5 RISE=1  $ CK (_156__row1) first rise, timing reference")
        clk_phase_prints.append("ck_x1")

        # diagnostic round 6: an ISOLATED single-DFFRB toggle-FF testbench
        # (tb_dffrb_isolated.spice) proved the cell itself is clean --
        # Q toggles perfectly on every real edge, QS/net5 never glitch, no
        # missed toggle edge1->edge2. So the chip-level bit_cnt_0 anomaly
        # must come from the REAL combinational D-logic feeding it, which
        # is NOT a plain NOT(Q0) toggle: netlist tracing found
        # _066_(D) = bit_cnt_0 ? _100_ : _111_ (a 3-NAND mux), with
        # _100_ = AND4(_085_,_094_,_098_,_099_) and
        # _111_ = NOR2(_094_,_110_) -- both share the term _094_, likely
        # some "actively counting" condition. Rather than hand-deriving the
        # full Boolean function through several more fan-in levels, probe
        # every node in this cone directly at 3 key instants spanning the
        # edge1(17us)->edge2(27us) window: right after edge1 (17.5us),
        # mid-cycle at the previously-found glitch point (22us), and just
        # before edge2 latches (26.9us) -- this shows exactly what the real
        # D-logic computes and why, without further symbolic derivation.
        for tag, t in (("e1", 17.5e-6), ("mid", 22e-6), ("e2pre", 26.9e-6)):
            for name, net in (
                ("d_066", "_066_"), ("d_100", "_100_"), ("d_111", "_111_"),
                ("d_094", "_094_"), ("d_085", "_085_"), ("d_098", "_098_"),
                ("d_099", "_099_"), ("d_110", "_110_"),
                ("bc0", "bit_cnt_0"), ("bc0_qb", "_212_"),
            ):
                add_probe(f"{name}_{tag}", f"xdut.x2.{net}", t, f"{net} at {tag} ({t*1e6:.1f}us) -- bit_cnt_0 D-logic cone")

        # diagnostic round 7: rather than reasoning further from the RTL
        # comments about start_pulse/reset-stretch timing (which may not
        # match the synthesized/simulated reality exactly), get the ACTUAL
        # measured crossing times of the whole reset/clock-gating chain
        # from real SCL (scl_row2) through _016_(RSTB)/rst_scl_domain_held/
        # rst_stretch_qn/_143_(raw)/_144_(clr)/_156_(pre-buffer gated
        # clock)/_156__row1, covering the whole START sequence
        # (t=0 through ~30us, i.e. power-on reset, bus-idle, START,
        # first bit). This replaces guessing about exact timing with
        # direct measurement, needed to build a faithful isolated-DFFRB
        # replay test using the REAL waveform timing instead of an
        # idealized approximation (which did not reproduce the glitch).
        for sig in ("scl_row2", "_016_", "rst_scl_domain_held", "rst_stretch_qn",
                    "_143_", "_144_", "_156_", "_156__row1"):
            for j in range(1, 5):
                name = f"tl_{sig.strip('_')}_x{j}"
                clk_phase_measures.append(f".measure tran {name} WHEN v(xdut.x2.{sig})=2.5 CROSS={j}  $ {sig} crossing #{j} (timeline reconstruction)")
                clk_phase_prints.append(name)

        # diagnostic round 8: round 7's first pass turned up something
        # unexpected -- _016_(RSTB) showed a SECOND, very close crossing
        # pair (x2=21.9758us, x3=22.0034us, only ~27.6ns apart) landing
        # almost exactly ON TOP of edge2 (_156__row1's own crossing at
        # ~21.984us). That looks like a brief (~28ns) real glitch on RSTB
        # itself, synchronized to the clock edge -- and it would have been
        # completely invisible to diagnostic round 2's point-sampled fine
        # sweep (FIND...AT=fixed_t, ~1us spacing), which is exactly why
        # that earlier sweep reported RSTB as "rock solid": a 28ns dip
        # between two 1us-apart sample points is aliased away by point
        # sampling but cannot be missed by CROSS-based WHEN measures.
        # This diagnostic round only widens the crossing count (1..16
        # instead of 1..4) for the reset-stretch chain signals, so we can
        # see whether this same narrow glitch repeats at edge3/edge4 (where
        # the chip-level bit_cnt_1 glitch was separately observed) and, if
        # so, trace which signal in the chain (_143_ raw -> SR latch
        # held/qn -> _016_ RSTB) is the true origin rather than a
        # downstream symptom.
        for sig in ("_143_", "_144_", "rst_scl_domain_held", "rst_stretch_qn", "_016_"):
            for j in range(1, 17):
                name = f"g2_{sig.strip('_')}_x{j}"
                clk_phase_measures.append(f".measure tran {name} WHEN v(xdut.x2.{sig})=2.5 CROSS={j}  $ {sig} crossing #{j} (round 8: RSTB glitch trace)")
                clk_phase_prints.append(name)

    # SDA release slew: how long does P2 actually take to rise from 1V
    # to 4.5V once this generator's own switch releases it (the FIRST
    # such release, right after START, before ADDR+W bit7=1) -- if this
    # takes anywhere close to T_HALF=5us, the SCL rising edge could be
    # sampling SDA mid-slew even though our margin looked generous on
    # paper.
    slew_measure = (
        f".measure tran sda_release_trise TRIG v({SDA_PAD}) VAL=1.0 RISE=1 "
        f"TARG v({SDA_PAD}) VAL=4.5 RISE=1  $ SDA release slew after START, "
        f"before ADDR+W bit7"
    )

    rx_prints = " ".join(f"v(xdut.{n})" for n in RX_NETS)
    rx_plots = " ".join(f"v(xdut.{n})" for n in RX_NETS)

    tstop = b.t + 2e-6

    text = TB_HEADER.format(
        MODEL_INCLUDE=MODEL_INCLUDE,
        SIM_READY_REL=SIM_READY_REL,
        VDD=VDD,
        ADDR_W=(SLAVE_ADDR << 1) | 0,
        ADDR_R=(SLAVE_ADDR << 1) | 1,
        DATA_WR=DATA_WR_VAL,
        DATA_RD=DATA_RD_VAL,
        T_RST_LOW_NS=T_RST_LOW * 1e9,
        T_RST_LOW=T_RST_LOW,
        T_RST_LOW_EDGE=T_RST_LOW + T_EDGE,
        RSTN_PAD=RSTN_PAD,
        DIS_PAD=DIS_PAD,
        TX_PADS=TX_PADS,
        TX_SOURCES="\n".join(tx_sources),
        SCL_PAD=SCL_PAD,
        SCL_PWL=b.pwl(b.scl),
        RPU_KOHM=10,
        SDA_PWL=b.pwl(b.sda_ctrl),
        SW_VT=VDD / 2,
        SW_VH=0.3,
        SDA_PAD=SDA_PAD,
        XDUT_NETS=xdut_nets,
        TSTEP="50n",
        TSTOP=f"{tstop:.9g}",
        READ_MEASURES="\n".join(read_measures),
        READ_PRINTS=" ".join(read_prints),
        ACK_MEASURES="\n".join(ack_measures),
        ACK_PRINTS=" ".join(ack_prints),
        DIAG_MEASURES="\n".join(diag_measures),
        DIAG_PRINTS=" ".join(diag_prints),
        TX_CHECK_MEASURES="\n".join(tx_check_measures),
        TX_CHECK_PRINTS=" ".join(tx_check_prints),
        SHREG_MEASURES="\n".join(shreg_measures),
        SHREG_PRINTS=" ".join(shreg_prints),
        CLK_PHASE_MEASURES="\n".join(clk_phase_measures),
        CLK_PHASE_PRINTS=" ".join(clk_phase_prints),
        CHAIN_MEASURES="\n".join(chain_measures),
        CHAIN_PRINTS=" ".join(chain_prints),
        BITCNT_MEASURES="\n".join(bitcnt_measures),
        BITCNT_PRINTS=" ".join(bitcnt_prints),
        SLEW_MEASURE=slew_measure,
        RX_NETS=RX_NETS,
        RX_PRINTS=rx_prints,
        RX_PLOTS=rx_plots,
    )
    return text


def main():
    import os
    os.makedirs(TB_DIR, exist_ok=True)
    text = build_tb()
    with open(TB_OUT, "w") as f:
        f.write(text)
    print(f"wrote {TB_OUT}")
    print()
    print("Run locally (this sandbox cannot run ngspice):")
    print(f"  cd ngspice/TB && ngspice -b tb_chip_i2c.spice")


if __name__ == "__main__":
    main()
