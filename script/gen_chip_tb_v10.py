"""
gen_chip_tb_v10.py (V10 counterpart of gen_chip_tb_v9.py -- user
request, this session: "V10のテストベンチを作ってください。", following
gen_chip_sim_ready_v10.py which the user had already asked for and
confirmed real KLayout DRC/LVS clean on V10 post-108.63/108.64 fixes).

Builds a real, locally-runnable ngspice testbench (ngspice/TB/tb_chip_
i2c_v10.spice) for the whole V10 chip (RING_OSC excluded -- ngspice/
tr_1um_i2c_slave_async_v10_sim_ready.spice, see gen_chip_sim_ready_
v10.py) that runs one I2C WRITE transaction followed by one I2C READ
transaction at SCL=100kHz -- same protocol shape as V9's testbench
(same SLAVE_ADDR=0x50, DATA_WR_VAL=0xA5, DATA_RD_VAL=0x3C, MSB-first
bit order, START/STOP/ACK/NACK conventions, same 10k SDA pull-up per
the user's original V9 instruction). The BusBuilder PWL-generation
engine and all timing constants (T_BIT/T_HALF/T_EDGE/T_HOLD/T_RST_LOW/
etc, including the T_HOLD/T_RESET_LOW_HOLD root-cause fixes) are reused
byte-for-byte from gen_chip_tb_v9.py -- these are protocol/timing-level,
not netlist-specific, so they carry over unchanged.

**What does NOT carry over unchanged: the physical pad map.** V10's own
pad-pairing-aware GIO terminal reassignment (v10_signal_routing_plan.
json, design_notes.md 108.57) changed which physical P-pad carries each
tx_data/rx_data bit vs V9 -- confirmed by directly reading the V10 sim_
ready netlist's own 'x2 ... i2c_slave_async_nrow_fm' instantiation line
and matching it position-by-position against the core subckt's formal
pin list (rst_n scl sda_in tx_data_0..7 sda_oe rx_data_0..7 rx_valid
addr_match rw busy VDD GND), NOT copied from V9's hardcoded constants:

    V9  TX_PADS = P11 P12 P13 P14 P6 P5 P4 P3
    V10 TX_PADS = P4  P12 P14 P5  P6 P3 P11 P13

    V9  RX_NETS = NC_OUT11 NC_OUT12 NC_OUT13 NC_OUT14 NC_OUT6 NC_OUT5 NC_OUT4 NC_OUT3
    V10 RX_NETS = NC_OUT4  NC_OUT12 NC_OUT14 NC_OUT5  NC_OUT6 NC_OUT3 NC_OUT11 NC_OUT13

SCL(P1)/SDA(P2)/RSTN(P15)/DIS(P7) are unchanged (verified the same way,
directly off the x2/x1 instantiation lines) -- these are outside the
20-net pad-pairing optimization's scope (108.57's docstring: only the
20 signal nets were reassigned).

**Internal diagnostic probes -- verified present, not assumed.** V10's
core is a re-placed (not re-synthesized-from-different-RTL) build of
the SAME RTL, and a direct grep of ngspice/tr_1um_i2c_slave_async_v10_
sim_ready.spice confirms EVERY internal net name V9's diagnostics used
-- bit_cnt_0/1/2, phase_0/1/2, last_bit_pending, shreg_0..6, and even
the Yosys-auto-numbered nets (_016_/_066_/_143_/_144_/_212_, the
x_505_/x_506_/x_507_ DFFRB instances, "_156_" the shared clock net) --
exist under the IDENTICAL names in V10's netlist (apparently the same
synthesis run, just re-placed/re-routed for the new floorplan). So the
STABLE, general-purpose diagnostics (busy/addr_match/rw via the NC_
CORE_* top-level aliases, shreg/bit_cnt/phase/last_bit_pending samples)
are reused here.

**What was deliberately DROPPED from V9's script**: the large "fine
sweep" / crossing-based diagnostic blocks (roughly 300+ extra .measure
points: fine_bitcnt0_t*/fine_ck_t*/fine_rstb_t*/etc, bc0_x*/bc1_x*/
bc2_x*/d004_x1/lbp_x1/ck_x1, and diagnostic rounds 6-8's D-logic-cone
and reset-chain-timeline probes) and the corresponding "DFFRB
slave-hold race diagnostic" `plot`/`xlimit` block at the end of
.control. Those were ALL added during V9's own live bug hunt for one
specific, since-fixed issue (a DFFRB master-latch/CK race, root-caused
and fixed in simulations/DFFRB.spice itself, MM27 -- see design_notes.
md). V10 reuses that same DFFRB cell UNCHANGED (standing constraint:
no changes to the DFFRB/RSLATCH STDCELL), so the bug those probes were
built to characterize should not reproduce -- carrying the entire
bug-hunt scaffolding forward would roughly triple this file's size for
no ongoing verification value. If a similar race is ever suspected in
V10, the exact same internal net names are confirmed present above and
the dropped blocks in gen_chip_tb_v9.py can be ported over verbatim.

**P9/P10 stand-in**: same as gen_chip_sim_ready_v10.py's own testbench
guidance -- with RING_OSC excluded, P9/P10 (its OUTD/OUT pads) are tied
to VSS via 1G resistors for DC-path/convergence safety only (reused
verbatim from V9's testbench).
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SIM_READY_SRC = str(_REPO_ROOT / "ngspice" / "tr_1um_i2c_slave_async_v10_sim_ready.spice")
TB_DIR = str(_REPO_ROOT / "ngspice" / "TB")
TB_OUT = TB_DIR + "/tb_chip_i2c_v10.spice"

MODEL_INCLUDE = "~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/ip62_models"
SIM_READY_REL = "../tr_1um_i2c_slave_async_v10_sim_ready.spice"
VDD = 5.0

SLAVE_ADDR = 0x50
DATA_WR_VAL = 0xA5   # script/test_i2c_slave_async.py's own value
DATA_RD_VAL = 0x3C   # script/test_i2c_slave_async.py's own value

# V10's own pad-pairing-aware terminal reassignment (108.57) -- read
# directly off ngspice/tr_1um_i2c_slave_async_v10_sim_ready.spice's own
# 'x2 ... i2c_slave_async_nrow_fm' instantiation line, position-matched
# against the core subckt's formal pin list. NOT the same as V9's own
# TX_PADS/RX_NETS -- see this script's own module docstring for the
# side-by-side diff and how this was verified (not assumed).
TX_PADS = ["P4", "P12", "P14", "P5", "P6", "P3", "P11", "P13"]          # tx_data bit0..7
RX_NETS = ["NC_OUT4", "NC_OUT12", "NC_OUT14", "NC_OUT5",
           "NC_OUT6", "NC_OUT3", "NC_OUT11", "NC_OUT13"]                 # rx_data bit0..7
DIS_PAD = "P7"     # unchanged from V9 -- verified via x1's own HIZ3/4/5/6/11/12/13/14->P7 ties
SCL_PAD = "P1"     # unchanged from V9 -- verified via x2's own pin-1 (scl) mapping
SDA_PAD = "P2"     # unchanged from V9 -- verified via x2's own pin-2 (sda_in) mapping
RSTN_PAD = "P15"   # unchanged from V9 -- verified via x2's own pin-0 (rst_n) mapping

# ---- SCL=100kHz timing (byte-for-byte reused from gen_chip_tb_v9.py --
# protocol/timing-level, not netlist-specific) ----
T_BIT = 10e-6      # 1 SCL cycle per bit, 100kHz
T_HALF = T_BIT / 2  # 5us
T_EDGE = 100e-9     # fast (100ns) drive edge for SCL/SDA_CTRL/RSTN
T_HOLD = 300e-9     # I2C tHD;DAT hold margin (see gen_chip_tb_v9.py's own
                    # docstring/comment for the full root-cause diagnosis
                    # of why this is needed -- the start_pulse-detector
                    # race at dt=0, fixed 2026-09-02, reused unchanged).
T_RST_LOW = 500e-9   # RSTN held low this long before releasing
T_POST_RST_SETTLE = 2e-6   # idle (bus released, SCL high) after RSTN releases
T_RESET_LOW_HOLD = 1e-6    # (unused directly here -- kept for parity with
                             # v9's constant set / possible future use;
                             # this testbench uses the plain idle() reset
                             # stimulus, see build_sequence()'s own comment)
T_INTER_TXN_GAP = 5e-6      # idle between the write and read transactions
T_FINAL_SETTLE = 5e-6       # idle after the final STOP


def read_top_pin_order(text):
    """Read the chip's real top-level pin order directly from
    SIM_READY_SRC's own '.subckt tr_1um_i2c_slave_async ...' line --
    not hand-typed."""
    m = re.search(r"^\.subckt\s+tr_1um_i2c_slave_async\s+(.+)$", text, re.M)
    if not m:
        raise RuntimeError(f"'.subckt tr_1um_i2c_slave_async ...' not found in {SIM_READY_SRC}")
    return m.group(1).split()


class BusBuilder:
    """Builds clean, edge-limited PWL breakpoint lists for SCL and for
    this testbench's own SDA_CTRL (drive-low-when-high open-drain
    control), plus a record of sample points worth measuring. Reused
    verbatim from gen_chip_tb_v9.py (protocol/timing-level engine, no
    netlist-specific content)."""

    def __init__(self, t0):
        self.t = t0
        self.scl = []
        self.sda_ctrl = []
        self.read_bit_samples = []
        self.notes = []
        self.master_bit_samples = []
        self.byte_last_bit_edges = []
        self.all_bit_edges = []

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
        """Precondition: SCL currently low. T_HOLD margin inserted
        before changing SDA (see T_HOLD's comment)."""
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
                last_bit_edge_t = edge_t
            self.master_bit(bitval)
        self.byte_last_bit_edges.append((last_bit_edge_t, label))

    def release_bit(self, label=None):
        """Master fully releases SDA for this bit period (ACK-from-slave
        bits, slave-driven read-data bits). Precondition: SCL currently low."""
        if label:
            self.note(label)
        self.t += T_HOLD
        self._sda_set(0.0)
        self.t += T_HALF - T_HOLD
        self._scl_set(VDD)
        self.t += T_HALF
        self._scl_set(0.0)

    def slave_data_bit(self, expected_bit):
        sample_t = self.t + T_HALF + T_HALF / 2
        self.read_bit_samples.append((sample_t, expected_bit))
        self.release_bit()

    def master_ack_bit(self, ack, label):
        """Master, as receiver, drives ack(0)/nack(1). Precondition: SCL currently low."""
        self.note(label)
        self.t += T_HOLD
        self._sda_set(VDD if ack == 0 else 0.0)
        self.t += T_HALF - T_HOLD
        self._scl_set(VDD)
        self.t += T_HALF
        self._scl_set(0.0)

    def stop_condition(self):
        self.note("STOP")
        self.t += T_HOLD
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
    # Realistic "SCL already idle-high from t=0" stimulus (matches the
    # real bus). The DFFRB power-on-reset master-latch race this used to
    # need a workaround for is now fixed at the cell level (simulations/
    # DFFRB.spice, MM27 -- see gen_chip_tb_v9.py's own docstring), so
    # this reverts to the plain, realistic idle() stimulus, same as V9's
    # own final revision.
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
* tb_chip_i2c_v10.spice -- auto-generated by script/gen_chip_tb_v10.py
* DO NOT hand-edit -- regenerate instead.
*
* Whole-V10-chip (RING_OSC excluded) I2C WRITE-then-READ testbench at
* SCL=100kHz, using the real TR-1um transistor models and ngspice/
* tr_1um_i2c_slave_async_v10_sim_ready.spice (the LVS-confirmed V10
* chip netlist, M->X + NMOSE->MNE converted -- see script/gen_chip_sim_
* ready_v10.py). Same protocol as V9's own tb_chip_i2c.spice, but V10's
* own pad-pairing-aware terminal reassignment (108.57) means TX_PADS/
* RX_NETS differ from V9's -- see this script's own module docstring.
*
* Protocol:
*   WRITE: S, ADDR+W(0x{ADDR_W:02X}), ACK, DATA=0x{DATA_WR:02X}, ACK, P
*   READ : S, ADDR+R(0x{ADDR_R:02X}), ACK, DATA=0x{DATA_RD:02X} (slave-driven), NACK, P
*
* DIS (P7) held HIGH the whole run (Hi-Z / tx_data-input mode) so the 8
* shared tx/rx pads never contend with this testbench's own TX drive --
* rx_data is instead observed at each pad's own internal receiver net
* (NC_OUT.. ), which reflects the pad regardless of DIS. tx_data is
* held at 0x{DATA_RD:02X} for the whole run (only consumed during the read).

.include '{MODEL_INCLUDE}'
.include '{SIM_READY_REL}'

.param vdd={VDD}

vvdd VDD 0 DC {VDD}
vvss VSS 0 DC 0

* RSTN: low for {T_RST_LOW_NS:.0f}ns (power-on reset), then a fast edge to VDD,
* held for the rest of the run -- real async reset via each DFFRB's own
* RSTB pin.
vrstn {RSTN_PAD} 0 PWL(0 0 {T_RST_LOW:.9g} 0 {T_RST_LOW_EDGE:.9g} {VDD})

* DIS: held high the whole run (see docstring).
vdis {DIS_PAD} 0 DC {VDD}

* P9/P10 (RING_OSC.OUTD/OUT in the full chip -- unused and otherwise
* floating here, since RING_OSC is excluded from this netlist). Tied to
* VSS via a large resistor purely for SPICE DC-path/convergence safety.
rp9 P9 VSS 1G
rp10 P10 VSS 1G

* tx_data (bit0..7 = {TX_PADS}), held at 0x{DATA_RD:02X} for the whole run.
{TX_SOURCES}

* SCL: master clock, 100kHz during bus activity (idle high otherwise).
vscl {SCL_PAD} 0 PWL({SCL_PWL})

* SDA open-drain bus: this testbench's own master drive (voltage-
* controlled switch to VSS, gated by SDA_CTRL) in parallel with an
* external {RPU_KOHM:.0f}k pull-up to VDD (chip itself has no on-chip SDA
* pull-up) and the DUT's own internal SDA driver (already part of the
* DUT netlist).
vsda_ctrl SDA_CTRL 0 PWL({SDA_PWL})
.model SDASW SW(RON=10 ROFF=1MEG VT={SW_VT} VH={SW_VH})
ssda {SDA_PAD} 0 SDA_CTRL 0 SDASW
rpu {SDA_PAD} VDD {RPU_KOHM:.0f}k

* DUT instantiation -- pin order read directly from ngspice/tr_1um_i2c_
* slave_async_v10_sim_ready.spice's own '.subckt tr_1um_i2c_slave_async
* ...' line (not hand-typed), see read_top_pin_order().
xdut {XDUT_NETS} tr_1um_i2c_slave_async

.tran {TSTEP} {TSTOP}

* ---- sample points: read-data bits (mid SCL-high window of each of
* the 8 slave-driven bits during the read transaction) ----
{READ_MEASURES}

* ---- ACK sample points (expect ~0V = ACK asserted) ----
{ACK_MEASURES}

* ---- diagnostic: internal core state (busy/addr_match/rw), to
* localize a non-responsive-bus result ----
{DIAG_MEASURES}

* ---- diagnostic: this generator's OWN driven bus level self-check
* (independent of the DUT) for every master-driven address/data bit ----
{TX_CHECK_MEASURES}

* ---- diagnostic: internal address shift-register (shreg_0..shreg_6,
* inside xdut.x2 = i2c_slave_async_nrow_fm) snapshot right after each
* address byte's last-bit SCL edge ----
{SHREG_MEASURES}

* ---- diagnostic: phase-FSM (phase_0/1/2) after START, and bit_cnt/
* last_bit_pending across reset release ----
{CLK_PHASE_MEASURES}

* ---- diagnostic: comparator-chain nodes (last_bit_pending/phase_0-2)
* right after each address byte's last-bit SCL edge ----
{CHAIN_MEASURES}

* ---- diagnostic: bit_cnt_0/1/2 + last_bit_pending trajectory at every
* ADDR+W bit edge (edge1..edge8) ----
{BITCNT_MEASURES}

* ---- diagnostic: SDA release slew (pull-up charge time) ----
{SLEW_MEASURE}

.control
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
  write tb_chip_i2c_v10.raw v({SCL_PAD}) v({SDA_PAD}) v({RSTN_PAD}) {RX_PLOTS} v(xdut.NC_CORE_busy) v(xdut.NC_CORE_addr_match) v(xdut.NC_CORE_rw) i(vvdd) v(xdut.x2.last_bit_pending) v(xdut.x2.phase_0) v(xdut.x2.phase_1) v(xdut.x2.phase_2) v(xdut.x2.shreg_0) v(xdut.x2.shreg_1) v(xdut.x2.shreg_2) v(xdut.x2.shreg_3) v(xdut.x2.shreg_4) v(xdut.x2.shreg_5) v(xdut.x2.shreg_6) v(xdut.x2.bit_cnt_0) v(xdut.x2.bit_cnt_1) v(xdut.x2.bit_cnt_2)

  * interactive viewing (ignored harmlessly in -b batch mode without a
  * display; run without -b, or `ngspice -b tb_chip_i2c_v10.spice` then
  * load tb_chip_i2c_v10.raw in any viewer, e.g.
  * `ngspice -r tb_chip_i2c_v10.raw` + `plot` at the prompt).
  plot v({SCL_PAD}) v({SDA_PAD})
  plot v({RSTN_PAD})
  plot {RX_PLOTS}
  plot v(xdut.NC_CORE_busy) v(xdut.NC_CORE_addr_match) v(xdut.NC_CORE_rw)
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
            break
    addr_ack_idx = 0
    for note_t, text in b.notes:
        if text.startswith("ACK") and "address" in text:
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
            diag_measures.append(
                f".measure tran addr_match_{tag}_x1 WHEN v(xdut.NC_CORE_addr_match)=2.5 "
                f"RISE={addr_ack_idx + 1}  $ addr_match rise #{addr_ack_idx + 1} ({text})"
            )
            diag_prints.append(f"addr_match_{tag}")
            diag_prints.append(f"rw_{tag}")
            diag_prints.append(f"addr_match_{tag}_x1")
            addr_ack_idx += 1

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
        sample_t = edge_t + 2e-6
        for n in SHREG_NETS:
            name = f"{n}_{tag}"
            shreg_measures.append(
                f".measure tran {name} FIND v(xdut.x2.{n}) AT={sample_t:.9g}  "
                f"$ internal address shift-reg bit, right after the {label} "
                f"last-bit SCL edge"
            )
            shreg_prints.append(name)

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

    if start_t is not None:
        t_after_start = start_t + T_HALF + T_HALF / 2
        add_probe("phase0_after_start", "xdut.x2.phase_0", t_after_start, "phase bit0 shortly after START")
        add_probe("phase1_after_start", "xdut.x2.phase_1", t_after_start, "phase bit1 shortly after START")
        add_probe("phase2_after_start", "xdut.x2.phase_2", t_after_start, "phase bit2 shortly after START")

        t_at_start_begin = start_t + 1e-9
        t_before_bit7_edge = start_t + T_HALF + T_HALF + 200e-9
        for tag, t in (("at_start_begin", t_at_start_begin), ("before_bit7_edge", t_before_bit7_edge)):
            add_probe(f"bit_cnt_0_{tag}", "xdut.x2.bit_cnt_0", t, f"bit_cnt_0 {tag}")
            add_probe(f"bit_cnt_1_{tag}", "xdut.x2.bit_cnt_1", t, f"bit_cnt_1 {tag}")
            add_probe(f"bit_cnt_2_{tag}", "xdut.x2.bit_cnt_2", t, f"bit_cnt_2 {tag}")
            add_probe(f"lbp_{tag}", "xdut.x2.last_bit_pending", t, f"last_bit_pending {tag}")

        for tag, t in (
            ("rst_300n", 300e-9),
            ("rst_550n", 550e-9),
            ("rst_650n", 650e-9),
            ("rst_900n", 900e-9),
            ("rst_1200n", 1200e-9),
            ("rst_1600n", 1600e-9),
        ):
            add_probe(f"bit_cnt_0_{tag}", "xdut.x2.bit_cnt_0", t, f"bit_cnt_0 at {tag}")
            add_probe(f"phase_0_{tag}", "xdut.x2.phase_0", t, f"phase_0 at {tag} (for comparison)")

    CHAIN_NETS = {
        "last_bit_pending": "last_bit_pending",
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
        sample_t = edge_t + 2e-6
        for tag_name, net in CHAIN_NETS.items():
            name = f"{tag_name}_{tag}"
            chain_measures.append(
                f".measure tran {name} FIND v(xdut.x2.{net}) AT={sample_t:.9g}  "
                f"$ comparator-chain node, right after the {label} last-bit SCL edge"
            )
            chain_prints.append(name)

    bitcnt_measures = []
    bitcnt_prints = []
    for edge_t, label, bit_idx in b.all_bit_edges:
        if label != "ADDR+W":
            continue
        sample_t = edge_t + 2e-6
        for tag_name, net in (
            ("bit_cnt_0", "bit_cnt_0"),
            ("bit_cnt_1", "bit_cnt_1"),
            ("bit_cnt_2", "bit_cnt_2"),
            ("lbp", "last_bit_pending"),
        ):
            name = f"{tag_name}_edge{8 - bit_idx}"
            bitcnt_measures.append(
                f".measure tran {name} FIND v(xdut.x2.{net}) AT={sample_t:.9g}  "
                f"$ {net} 2us after ADDR+W bit{bit_idx}'s SCL rising edge "
                f"(edge {8 - bit_idx} of 8)"
            )
            bitcnt_prints.append(name)

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
    print(f"  cd ngspice/TB && ngspice -b tb_chip_i2c_v10.spice")


if __name__ == "__main__":
    main()
