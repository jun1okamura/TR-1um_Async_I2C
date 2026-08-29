"""
gen_irsim_cmd.py

Generates IRSIM .cmd stimulus scripts for the whole-chip
tr_1um_i2c_slave_async.sim (see gen_irsim_sim.py), by mechanically
translating the SAME bus-functional-model logic already validated by
script/test_i2c_slave_async.py and script/test_i2c_slave_async_negative.py
(MyHDL testbenches) into IRSIM h/l/x/s commands on the equivalent flat
netlist nodes.

Node mapping (derived this session via positional analysis of X$3's --
the core instance's -- actual argument list against
i2c_slave_async_nrow_fm's .SUBCKT formal pin order in
src/tr_1um_i2c_slave_async.extracted; cross-validated independently via
X$1/OSS_FRAME_GIO's own pin binding for VDD, sda_oe/HIZ13, rst_n/P15,
scl/P2, sda_in/P13 -- see design_notes.md):

  VDD=$1  VSS=VSS  rst_n=$106  scl=$102  sda_in=$58(=SDA bond pad, has
  external 20k pull-up added in the .sim -- see gen_irsim_sim.py)
  sda_oe=$45 (internal, watch-only -- slave's open-drain drive enable)
  tx_data[7:0] = $68 $103 $72 $57 $22 $21 $19 $26  (bit7..bit0)
  rx_data[7:0] = $64 $78 $83 $13 $42 $34 $15 $32   (bit7..bit0)
  busy/rw/addr_match/rx_valid = X$3.busy / X$3.rw / X$3.addr_match /
  X$3.rx_valid (internal-only core diagnostics, not brought to a chip
  pin -- but any internal node can still be watched directly in IRSIM,
  no different from a real in-circuit probe).

  NOTE: gen_irsim_sim.py's sanitize() rewrites every literal "$" in a
  node name to "N" (IRSIM 9.7's command interpreter treats a leading
  "$" as a variable-substitution sigil -- confirmed on a real run:
  bare "$58" caused 'subcircuit "$58" is not defined!'). The constants
  below are the POST-sanitize names actually used in the .sim file, so
  e.g. X$3.busy -> XN3.busy. The chip's VDD/GND supply nodes ($1/VSS,
  i.e. would-be N1/VSS) are further renamed literally "Vdd"/"Gnd" --
  IRSIM looks for those exact names by default and segfaulted on a
  real run when they weren't found (see design_notes.md 76.8).
"""

VDD = "Vdd"
GND = "Gnd"
RST_N = "N106"
SCL = "N102"
SDA = "N58"
SDA_OE = "N45"
# P7/DIS: a real chip pin (GIO's P7, top-level net $2/N2). Netlist tracing
# (design_notes.md 76.25) confirmed DIS is the shared HIZ control for 8
# OTHER GIO pads (P1/P3/P4/P5/P6/P11/P12/P14) that are each genuinely
# bidirectional: the pad's own bond-pad node IS the "TX" node the I2C core
# reads combinationally (no register -- external voltage sampled directly)
# while the pad's internal OUT driver (enabled only when HIZ/DIS releases)
# is wired from the real "RX" DFFR register (what the last I2C WRITE
# captured). So DIS=H (Hi-Z, normal/default here) lets TX be forced
# externally without contention; DIS=L makes the SAME 8 pads actively
# drive RX onto themselves, which is externally indistinguishable from a
# write/read loopback (WRITE then READ echoes what was written) but is
# really just physical pad sharing, not an internal mux. NEVER force TX
# while DIS=L (drive contention). Left completely unconstrained (X) in
# every test until this session; forced H for normal (non-loopback)
# operation. See design_notes.md 76.19/76.25.
DIS = "N2"
TX = ["N26", "N19", "N21", "N22", "N57", "N103", "N72", "N68"]   # bit0..bit7 -- pad P nodes (P12,P11,P5,P6,P4,P1,P3,P14), not a register
RX = ["N32", "N15", "N34", "N13", "N42", "N78", "N83", "N64"]   # bit0..bit7 -- real DFFR register, also wired to the same 8 pads' OUT
BUSY = "XN3.busy"
RW = "XN3.rw"
ADDR_MATCH = "XN3.addr_match"
# RSTB for the $28-group DFFRBs (phase/bit_cnt/shreg/addr_ok/rw_bit/rw/
# addr_match's own registers), driven by NOR2($813,$702). $813 is the
# gate-level start_pulse-equivalent that RTL says should pulse briefly on
# every START condition to reset this register bank (src/i2c_slave_async.v
# ~L103, rst_scl_domain = ~rst_n | start_pulse) -- but two independent real
# runs (irsim_debug_rstb.cmd, and DEL1 substituted with a symmetric BUF_X1
# cascade) confirmed $813 NEVER pulses under IRSIM, regardless of settle
# time or which delay/buffer cell drives $704: IRSIM's ternary solver
# settles a whole combinational cone within a single timestep, so the
# transient $697-vs-$704 mismatch window $813's formula needs structurally
# never opens at this simulation granularity (design_notes.md 76.23/76.24).
# busy's OWN edge-detect (a differently-shaped NOR/NAND network, $695/$696)
# is unaffected and reliably fires on every START (confirmed repeatedly).
# Since busy proves the START condition WAS correctly detected at the gate
# level, this net was FIRST tried as a direct force/release stand-in for
# the reset pulse that should be happening -- but a real run showed this
# does NOT work: RSTB only force-drives Q/QB WHILE asserted (76.13), never
# the internal QM/QS storage, so releasing it after one stepsize just lets
# Q revert to whatever QM/QS still hold (stale). start() now instead force/
# releases each DFFRB_28_INSTANCES member's own QS node directly (same
# proven technique as preamble()'s cold-start fix) -- not a claim that real
# silicon has this problem (see 76.24/76.26). RSTB28 itself is kept here
# only for reference/diagnostics (e.g. gen_irsim_debug_rstb.py).
RSTB28 = "XN3.N28"

# NOTE on BUFTH: scl/sda_in are buffered through a BUFTH cell (Schmitt
# trigger) before reaching the core. Its real transistor-level structure
# has a genuine internal regenerative feedback node that IRSIM's ternary
# solver could not resolve -- not just at cold start but on EVERY
# transition of its input, confirmed on real hardware two different ways
# (force/release, then a permanent weak bias transistor -- neither fully
# worked once actual protocol toggling started, see design_notes.md
# 76.12/76.14). Per explicit user direction, gen_irsim_sim.py now
# substitutes BUFTH's transistor-level definition with BUF_X1's (a plain
# non-regenerative buffer, same pin list) for chip-level IRSIM purposes
# -- see design_notes.md 76.15. No BUFTH-specific handling is needed
# here anymore as a result.

# All 33 DFFRB instances in i2c_slave_async_nrow_fm (X$3 in the top chip,
# sanitized XN3), split by which RSTB net they use -- see design_notes.md
# 76.10 for how these two groups were found. DFFRB has the SAME cold-start
# ternary-resolution problem as BUFTH (confirmed on rw's own DFFRB,
# instance X$2/XN2, via irsim_debug_dffrb.cmd -- see 76.13): RSTB only
# force-drives QB/Q directly, never the internal master/slave storage
# nodes (QM/QS/the associated keeper node), so once RSTB genuinely
# releases -- and no clock edge has ever toggled this DFFRB's CK -- Q can
# stay stuck at X indefinitely even though the only physically sensible
# value (given no data has ever been clocked in) is the reset default 0.
# QS is the actual independent root (QB is a plain inverter of QS once
# RSTB=1, Q is a plain inverter of QB) -- forcing QS=0 then releasing it
# breaks the deadlock, mirroring BUFTH's N2 fix.
#
# Group A (24 instances, RSTB=$28, a NOR2-derived net -- releases as soon
# as rst_n releases, independent of busy):
DFFRB_28_INSTANCES = [
    "XN2", "XN16", "XN32", "XN46", "XN104", "XN105", "XN106", "XN107",
    "XN108", "XN109", "XN110", "XN111", "XN112", "XN113", "XN114",
    "XN115", "XN116", "XN117", "XN118", "XN119", "XN120", "XN121",
    "XN122", "XN123",
]
# Group B (9 instances incl. sda_oe's own register, RSTB=$227=busy AND
# rst_n -- only actually releases once busy goes high, i.e. after the
# first real START condition):
DFFRB_227_INSTANCES = [
    "XN314", "XN315", "XN316", "XN317", "XN318", "XN319", "XN320",
    "XN321", "XN322",
]
ALL_DFFRB_INSTANCES = DFFRB_28_INSTANCES + DFFRB_227_INSTANCES


def dffrb_qs(inst):
    return f"XN3.{inst}.QS"


# The $28 group's 24 DFFRB instances split across 4 distinct derived CK
# nets (src/tr_1um_i2c_slave_async.extracted lines ~46-152; confirmed
# against the .sim that each drives the corresponding instances' CKB pin
# directly, design_notes.md 76.35/76.41): rw(XN2)/XN32/XN46/XN104/XN111
# on N34; addr_match(XN16)/XN105/XN106/XN107/XN113/XN114/XN118-XN123 on
# N635; XN108/XN109/XN110/XN112 (shreg[0..3]) on N666; XN115/XN116/XN117
# on N343. Needed by force_release_gated() for mid-run $28-group resets.
DFFRB_28_CLOCK_NETS = ["XN3.N34", "XN3.N635", "XN3.N666", "XN3.N343"]

T = 20  # ns, matches script/test_i2c_slave_async.py's T -- value is
        # arbitrary for this async design; only used as IRSIM's stepsize.

# IRSIM's "settle" command (added revision 28, see design_notes.md 76.32):
# delays how long IRSIM waits before declaring a node genuinely conflicted/
# undefined ("X"), instead of reacting to the very first instant a node
# looks like it's driven two ways at once. This is IRSIM's own documented
# fix for exactly DFFRB's back-to-back-inverter (QM/QS) topology -- real
# transistor-level SPICE (76.31) confirms QS actually just holds its forced
# value with zero drift, so the X seen under TR-1um.prm without "settle" is
# IRSIM's decay heuristic being too impatient, not a real conflict. Official
# docs suggest "on the order of 50" (ns) as a typical value -- longer than a
# gate delay, shorter than a clock phase; this async design has no clock
# phase to bound it by, so 50 is used as the documented default, not tuned.
SETTLE_NS = 50

# Margin between "SDA is set (released to the pull-up, or forced) while SCL
# is low" and "SCL actually rises" -- real I2C data-setup-before-clock
# timing. Was a single stepsize (20ns) everywhere SDA gets released ("x
# SDA") right before a clock edge that reads it (send_bit/read_ack/
# recv_bit/send_ack_from_master) -- fine under scmos100.prm's placeholder
# pull-up, but design_notes.md 76.37/76.38's real-TR-1um.prm pull-up
# recalibration (L=20/W=1 -> L=1/W=1.9, correcting a ~745kohm mis-sized
# pull-up down to its intended ~20kohm) exposed that even the CORRECT
# ~20kohm resistance still needs real RC time to charge SDA's node
# capacitance -- a real run showed SDA still mid-rise when SCL went high
# only 20ns after release, which reads as a spurious STOP (SDA rising
# while SCL is high), clearing busy and explaining why the shift register
# never captured anything (design_notes.md 76.39). 500ns matches the
# general order of magnitude already needed elsewhere in this design's
# real timing (stop()'s own settle_before_ns/sda_low_hold_ns margins).
SDA_RELEASE_SETTLE_NS = 500

SLAVE_ADDR = 0x50


class CmdGen:
    def __init__(self):
        self.lines = []

    def raw(self, s=""):
        self.lines.append(s)

    def note(self, s):
        self.lines.append(f"| {s}")

    def s(self, n=None):
        self.lines.append(f"s {n}" if n else "s")

    def h(self, node):
        self.lines.append(f"h {node}")

    def l(self, node):
        self.lines.append(f"l {node}")

    def x(self, node):
        self.lines.append(f"x {node}")

    def d(self, *nodes):
        self.lines.append("d " + " ".join(nodes))

    def force_release(self, nodes, value=0):
        """One-time symmetry-break for a batch of nodes stuck in a cold-X
        feedback loop (BUFTH's N2, DFFRB's QS) -- force them all to
        `value`, settle, then release them all back to the network, which
        (once its other inputs are known) holds the correct value on its
        own. See design_notes.md 76.12/76.13.

        Only valid when the target nodes are GENUINELY floating (e.g. cold
        start, before CK has ever toggled and both of DFFRB's QM<->QS/
        QS<->net5 transmission gates are still X-gated). Do NOT reuse this
        for a mid-run reset once CK has a real, defined level -- see
        force_release_gated() and design_notes.md 76.41/76.42."""
        setter = self.l if value == 0 else self.h
        for n in nodes:
            setter(n)
        self.s()
        for n in nodes:
            self.x(n)
        self.s()

    def force_release_gated(self, nodes, gate_nets, value=0):
        """Like force_release(), but for MID-RUN reuse once CK has a real,
        settled level (not X) -- design_notes.md 76.41/76.42 found that
        plain force_release() on DFFRB's QS gets immediately overridden in
        this case: DFFRB has TWO transmission gates touching QS (QM<->QS,
        transparent when CK=1; QS<->net5, transparent when CK=0) -- once
        CK is a real defined value, exactly one of the two is ALWAYS
        transparent, so QS is never actually isolated the way it is at
        cold start (both gates X-gated together). A real run confirmed
        this: addr_match's QS forced to 0 correctly, but the instant it
        was released, it snapped right back to 1 -- CK(N635) was steady at
        1 (QM<->QS transparent) and D (still reflecting a stale
        pre-force compare result) simply overrode the force in the very
        next event.

        Fix: also force `gate_nets` (the group's derived CK nets) LOW for
        the SAME window as the QS force. CK=0 makes QM<->QS opaque
        (isolating QS from stale D) while QS<->net5 becomes transparent
        instead -- but net5=NOT(QB) and QB is an always-on inverter of QS,
        so this forms a SELF-REINFORCING loop with our forced value rather
        than fighting it. Doing this for the WHOLE group at once (not just
        one instance) matters: shreg's own instances share these same CK
        nets, so they get isolated and reset together too, meaning by the
        time the CK nets are released back to their real levels, the
        combinational logic downstream (e.g. the address comparator
        feeding addr_match's D) already reflects the freshly-cleared
        register state instead of a stale one."""
        setter = self.l if value == 0 else self.h
        for g in gate_nets:
            self.l(g)
        for n in nodes:
            setter(n)
        self.s()
        for n in nodes:
            self.x(n)
        for g in gate_nets:
            self.x(g)
        self.s()

    def preamble(self, reset_hold_ns=3000):
        self.note("Auto-generated by script/irsim/gen_irsim_cmd.py -- do not hand-edit.")
        self.note("Ties VDD/VSS, releases SDA to the (now sda_oe-gated) weak pull-up,")
        self.note("forces a known-0 tx_data bus and scl=1 idle, then pulses rst_n.")
        self.note(f"Reset is held for {reset_hold_ns}ns (not just a few stepsizes) --")
        self.note("this design's \"busy\" is a cross-coupled NOR2 SR latch (not a")
        self.note("DFFRB), and RSTB for 9 of the 33 DFFRBs (incl. sda_oe's) is")
        self.note("gated as \"busy AND rst_n\", so busy's own latch must resolve out")
        self.note("of its post-power-up X state before those registers' clear is")
        self.note("well-defined again after rst_n releases (see design_notes.md 76.10).")
        self.note("SDA no longer needs an explicit \"h\" override here (unlike an")
        self.note("earlier version of this script -- see design_notes.md 76.11/76.16):")
        self.note("the SDA pull-up PMOS's gate is sda_oe itself (gen_irsim_sim.py), and")
        self.note("sda_oe is held at a genuinely DEFINED 0 throughout this whole window")
        self.note("by AND-domination alone (RSTB2=busy AND rst_n=0 while rst_n=0, and")
        self.note("stays 0 even after rst_n releases as long as busy hasn't gone high")
        self.note("yet -- true regardless of BUFTH/DFFRB internals). So the pull-up's")
        self.note("gate is never X here, and SDA resolves cleanly on its own.")
        self.note("DIS (P7, N2) is forced H -- normal operation, not the loopback/")
        self.note("test mode where DIS=L makes the read-data register echo back")
        self.note("whatever was last written instead of the real RX shift register")
        self.note("(design_notes.md 76.19).")
        self.note(f"settle {SETTLE_NS}: IRSIM's own documented fix for back-to-back-")
        self.note("inverter nodes like DFFRB's QM/QS (76.32) -- gives IRSIM time to")
        self.note("see a node hold its value before declaring it X, instead of")
        self.note("reacting to the first instant of an apparent conflict.")
        self.raw(f"stepsize {T}")
        self.raw(f"settle {SETTLE_NS}")
        self.h(VDD)
        self.l(GND)
        self.x(SDA)
        self.h(SCL)
        self.h(DIS)
        for t in TX:
            self.l(t)
        self.l(RST_N)
        self.s(reset_hold_ns)
        self.note("check: slave held in reset -- busy/addr_match/rw/sda_oe must all")
        self.note("read a DEFINED 0 here, and SDA a DEFINED 1 (via the sda_oe-gated")
        self.note("pull-up), not X. If still X at this point, reset itself isn't")
        self.note("resolving (see design_notes.md 76.10) -- report back before")
        self.note("proceeding, since nothing downstream will make sense yet.")
        self.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH)
        self.h(RST_N)
        self.s()
        self.note("DFFRB (the 33x-instantiated flip-flop cell) has the SAME cold-X")
        self.note("feedback problem as BUFTH, one level deeper: RSTB only force-")
        self.note("drives QB/Q directly, never the internal master/slave storage")
        self.note("nodes (QM/QS), so once RSTB genuinely releases -- with this")
        self.note("design's async, never-yet-toggled clocking -- Q can stay stuck")
        self.note("at X forever even though 0 (nothing has been clocked in yet) is")
        self.note("the only physically sensible value. QS is the actual independent")
        self.note("root (QB/Q are plain inverters of it once RSTB=1); confirmed via")
        self.note("irsim_debug_dffrb.cmd on rw's own DFFRB (design_notes.md 76.13).")
        self.note("Force/release all 24 instances whose RSTB=$28 (this net has just")
        self.note("released, above) here; the 9 whose RSTB=$227=busy AND rst_n only")
        self.note("release once busy actually goes high, so those get the same")
        self.note("treatment in start(), right after the first START condition.")
        self.force_release([dffrb_qs(i) for i in DFFRB_28_INSTANCES], value=0)
        self.s(5 * T)
        self.note("check: still defined immediately after release")
        self.d(SDA_OE, BUSY, RW, ADDR_MATCH)
        self.raw("")

    # ---- bus-functional primitives, 1:1 with test_i2c_slave_async.py ----
    def start(self, first=False):
        self.note("---- START ----")
        self.h(SCL)
        self.x(SDA)  # already released since preamble() -- explicit here for clarity
        self.s()
        self.l(SDA)          # SDA 1->0 while SCL=1 : START
        self.s(2 * T)
        self.note("check: busy asserted after START")
        self.d(BUSY)
        if first:
            self.note("first START of this run: busy just went high for the first")
            self.note("time, which releases RSTB=$227 (=busy AND rst_n) for the 9")
            self.note("DFFRBs gated on it (incl. sda_oe's own register). Same cold-X")
            self.note("QS deadlock as the $28 group in preamble() -- see 76.13 --")
            self.note("give them the same one-time force/release now that $227 has")
            self.note("actually released.")
            self.force_release([dffrb_qs(i) for i in DFFRB_227_INSTANCES], value=0)
            self.note("check: sda_oe now holds a defined value instead of X")
            self.d(SDA_OE)
        self.note("The core's phase/bit_cnt/shreg/addr_ok/rw_bit register bank is")
        self.note("async-reset by rst_scl_domain = ~rst_n | start_pulse (RTL:")
        self.note("src/i2c_slave_async.v ~L103), gate-level equivalent RSTB=$28.")
        self.note("start_pulse's gate-level source ($813=NOR2($697,$703)) was proven")
        self.note("(two independent real runs, incl. substituting DEL1 with a")
        self.note("symmetric BUF_X1 cascade) to NEVER pulse under IRSIM at all --")
        self.note("not a settling-time shortfall, but IRSIM's ternary solver settling")
        self.note("the whole combinational cone within one timestep, so the transient")
        self.note("window $813 needs never opens here regardless of wait time (design")
        self.note("notes 76.22-76.24). busy's OWN edge-detect (differently-shaped")
        self.note("network, $695/$696) is unaffected and just proved START WAS")
        self.note("correctly detected at the gate level (busy=1 above).")
        self.note("First attempt: force/release RSTB28 (=$28) directly -- this FAILED")
        self.note("on a real run (addr_match read back as the STALE prior-transaction")
        self.note("value immediately after release). Root cause: per 76.13, RSTB only")
        self.note("force-drives Q/QB WHILE asserted -- it never touches the internal")
        self.note("QM/QS storage nodes. Releasing RSTB after one stepsize lets Q revert")
        self.note("to whatever QM/QS still hold (the stale value, since no clock edge")
        self.note("has loaded a fresh D into them) -- the exact same failure mode as")
        self.note("76.13's cold-start deadlock, just re-triggered mid-run instead of at")
        self.note("power-up. Fix: force/release each instance's OWN QS node directly")
        self.note("(same proven technique as preamble()'s $28-group cold-start fix),")
        self.note("bypassing RSTB entirely, for all 24 $28-group instances (this also")
        self.note("covers rw/addr_match's own registers, which share this same group).")
        if first:
            self.note("first START: SCL has only ever been held high so far (never")
            self.note("toggled low-high for a real bit yet), so the $28 group's")
            self.note("derived CK nets are still at their cold-start X -- both of")
            self.note("QS's transmission gates are still X-gated (genuinely floating),")
            self.note("same as preamble()'s cold-start fix -- plain force_release() is")
            self.note("valid here (and is what every successful WRITE-transaction run")
            self.note("this session actually exercised).")
            self.force_release([dffrb_qs(i) for i in DFFRB_28_INSTANCES], value=0)
        else:
            self.note("NOT the first START: real SCL clocking has already happened")
            self.note("in an earlier transaction, so the $28 group's derived CK nets")
            self.note("(N34/N635/N666/N343) now hold real, DEFINED levels -- NOT the")
            self.note("cold-start X that made plain force_release() work above. A real")
            self.note("run confirmed this breaks addr_match specifically: DFFRB's")
            self.note("QM<->QS gate is transparent whenever its CK=1, so a QS force")
            self.note("gets immediately overridden by whatever D says the instant the")
            self.note("force releases -- not an IRSIM artifact, genuinely correct")
            self.note("transparent-latch behavior (design_notes.md 76.41/76.42).")
            self.note("Fix: also force the group's own CK nets low for the same")
            self.note("window, so QS is genuinely isolated (not just nominally X)")
            self.note("while we reset it, and the whole group (incl. shreg) settles")
            self.note("together before the CK nets are released back to real values.")
            self.force_release_gated(
                [dffrb_qs(i) for i in DFFRB_28_INSTANCES],
                DFFRB_28_CLOCK_NETS, value=0)
        self.note("check: phase/bit_cnt-owning registers cleared (rw/addr_match are")
        self.note("in this same $28 group, so also visible here)")
        self.d(RW, ADDR_MATCH)

    def send_bit(self, bitval):
        self.s()
        self.l(SCL)
        if bitval:
            self.x(SDA)
        else:
            self.l(SDA)
        self.s(SDA_RELEASE_SETTLE_NS)
        self.h(SCL)
        self.s(2 * T)

    def send_byte(self, byte):
        for i in range(7, -1, -1):
            self.send_bit((byte >> i) & 1)

    def read_ack(self, label):
        self.l(SCL)
        self.x(SDA)
        self.s(SDA_RELEASE_SETTLE_NS)
        self.h(SCL)
        self.s()
        self.note(f"check: {label} (SDA low = ACK)")
        self.d(SDA)
        self.s()
        self.l(SCL)

    def recv_bit(self, idx):
        self.s()
        self.l(SCL)
        self.x(SDA)
        self.s(SDA_RELEASE_SETTLE_NS)
        self.h(SCL)
        self.s()
        self.note(f"sample read-data bit {idx} (MSB first)")
        self.d(SDA)
        self.s()

    def send_ack_from_master(self, ack):
        self.s()
        self.l(SCL)
        if ack == 0:
            self.l(SDA)
        else:
            self.x(SDA)
        self.s(SDA_RELEASE_SETTLE_NS)
        self.h(SCL)
        self.s(2 * T)
        self.l(SCL)
        self.x(SDA)

    def stop(self, label, settle_before_ns=500, sda_low_hold_ns=8000):
        self.note("STOP's edge-detect path routes through DEL1 (N704=DEL1(N697),")
        self.note("a real intentional delay element -- design_notes.md 76.10/76.13).")
        self.note(f"A short settle ({settle_before_ns}ns) is inserted first so any")
        self.note("residual DEL1 propagation from the immediately-preceding bit's")
        self.note("SDA activity clears before the STOP sequence starts counting its")
        self.note(f"own hold. SDA is then held low {sda_low_hold_ns}ns (not just one")
        self.note(f"{T}ns stepsize) before releasing it, so the falling edge has time")
        self.note("to actually propagate through DEL1 before the rising (STOP) edge")
        self.note("arrives -- otherwise the edge gets \"swallowed\" and busy never")
        self.note("clears. A real run confirmed busy stays stuck at 1 forever with a")
        self.note("2000ns hold measured in isolation right after START, but the SAME")
        self.note("2000ns was NOT enough once real address/data bit traffic preceded")
        self.note("it (see design_notes.md 76.20/76.21) -- hence the added settle gap")
        self.note("and a larger hold as a safety margin against the unknown real DEL1")
        self.note("delay (placeholder .prm, no characterized timing yet).")
        self.s(settle_before_ns)
        self.l(SDA)
        self.h(SCL)
        self.s(sda_low_hold_ns)
        self.x(SDA)          # SDA 0->1 while SCL=1 : STOP
        self.note(f"same real SDA pull-up RC recovery margin as send_bit() etc.")
        self.note("(76.39) -- this exact check used to fire only 2*T=40ns after")
        self.note("x(SDA), too soon for SDA to have actually finished rising")
        self.note("under the recalibrated TR-1um.prm pull-up: a real run showed")
        self.note("busy STILL reading 1 here (STOP not yet detected), not 0 --")
        self.note("missed this same margin class when send_bit()/read_ack()/")
        self.note("recv_bit()/send_ack_from_master() were fixed (76.40).")
        self.s(SDA_RELEASE_SETTLE_NS)
        self.note(f"check: busy cleared after STOP ({label})")
        self.d(BUSY)


def gen_main():
    g = CmdGen()
    g.note("irsim_test_main.cmd -- write 0xA5 then read 0x3C, mirrors")
    g.note("script/test_i2c_slave_async.py exactly (SLAVE_ADDR=0x50).")
    g.preamble()

    g.note("watch the whole transaction")
    g.d(SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH)
    g.raw("ana " + " ".join([SCL, SDA, SDA_OE, RST_N, BUSY, RW, ADDR_MATCH]))
    g.raw("")

    g.note("==================== WRITE TRANSACTION ====================")
    g.start(first=True)
    addr_byte = (SLAVE_ADDR << 1) | 0
    g.note(f"ADDR+W = 0x{addr_byte:02X}")
    g.send_byte(addr_byte)
    g.read_ack("slave ACKed matching address (write); also check addr_match=1, rw=0")
    g.d(ADDR_MATCH, RW)

    DATA_WR = 0xA5
    g.note(f"DATA byte = 0x{DATA_WR:02X}")
    g.send_byte(DATA_WR)
    g.read_ack("slave ACKed data byte")
    g.note(f"check: rx_data == 0x{DATA_WR:02X} (bit0..bit7 nodes below, MSB last)")
    g.d(*RX)
    g.stop("after write")

    g.note("==================== READ TRANSACTION ====================")
    DATA_RD = 0x3C
    g.note(f"preload tx_data = 0x{DATA_RD:02X} (what the slave will transmit)")
    for i in range(8):
        bit = (DATA_RD >> i) & 1
        (g.h if bit else g.l)(TX[i])
    g.s(2 * T)

    g.start()
    addr_byte = (SLAVE_ADDR << 1) | 1
    g.note(f"ADDR+R = 0x{addr_byte:02X}")
    g.send_byte(addr_byte)
    g.read_ack("slave ACKed matching address (read); also check rw=1")
    g.d(RW)

    for i in range(8):
        g.recv_bit(7 - i)
    g.note(f"expected read byte == 0x{DATA_RD:02X} (reconstruct MSB..LSB from the")
    g.note("SDA samples logged above)")
    g.send_ack_from_master(1)   # master NACKs -> ends read
    g.stop("after final STOP")

    g.raw("")
    g.note("end of irsim_test_main.cmd")
    return "\n".join(g.lines) + "\n"


def gen_negative():
    g = CmdGen()
    g.note("irsim_test_negative.cmd -- wrong address must NACK, mirrors")
    g.note("script/test_i2c_slave_async_negative.py exactly.")
    g.preamble()

    g.d(SCL, SDA, SDA_OE, ADDR_MATCH, BUSY)
    g.raw("ana " + " ".join([SCL, SDA, SDA_OE, ADDR_MATCH, BUSY]))
    g.raw("")

    WRONG_ADDR = 0x11
    g.start(first=True)
    addr_byte = (WRONG_ADDR << 1) | 0
    g.note(f"ADDR+W (WRONG) = 0x{addr_byte:02X}")
    g.send_byte(addr_byte)
    g.l(SCL)
    g.x(SDA)
    g.s()
    g.h(SCL)
    g.s()
    g.note("check: unmatched address -> NACK, i.e. SDA stays HIGH (no slave pulldown)")
    g.d(SDA)
    g.note("check: addr_match NOT asserted for foreign address")
    g.d(ADDR_MATCH)
    g.s()
    g.l(SCL)

    g.stop("after STOP following NACK")

    g.raw("")
    g.note("end of irsim_test_negative.cmd")
    return "\n".join(g.lines) + "\n"


def gen_reset_check():
    """Minimal, fast diagnostic: assert reset for a long time in several
    checkpointed steps (dumping state after each), release it, and stop
    -- nothing else. Meant to be run FIRST, before the full transaction
    tests, to confirm the design actually leaves its post-power-up X
    state; much faster to read than wading through irsim_test_main.cmd's
    full trace for the same check. See design_notes.md 76.10."""
    g = CmdGen()
    g.note("irsim_reset_check.cmd -- does reset alone resolve busy/sda_oe/")
    g.note("addr_match/rw out of X? Run this BEFORE the transaction tests")
    g.note("(much faster to read than the full write/read trace for the")
    g.note("same check). See design_notes.md 76.10 for why reset needs to")
    g.note("be held this long: busy is a cross-coupled NOR2 SR latch (not")
    g.note("a DFFRB) that must itself resolve out of X, since 9 of the 33")
    g.note("DFFRBs (incl. sda_oe's) gate their clear as \"busy AND rst_n\".")
    g.note("SDA is just released (\"x\") to the sda_oe-gated weak pull-up (see")
    g.note("gen_irsim_sim.py) -- no explicit \"h\" override needed: sda_oe is held")
    g.note("at a genuinely DEFINED 0 throughout by AND-domination alone (RSTB2=")
    g.note("busy AND rst_n=0 while rst_n=0, and stays 0 after release as long as")
    g.note("busy hasn't gone high yet), so the pull-up's gate is never X and SDA")
    g.note("resolves cleanly on its own (see 76.11/76.16, supersedes an earlier")
    g.note("version of this script that forced SDA high here).")
    g.note("DFFRB (33x, incl. rw/addr_match's own registers) has a similar cold-X")
    g.note("problem via its internal QS node -- see 76.13. One-time force/release")
    g.note("below. (BUFTH had a related issue but is now substituted with BUF_X1")
    g.note("in the .sim itself, see 76.15 -- no BUFTH-specific handling needed here.)")
    g.note("DIS (P7, N2) is forced H -- normal operation, not the write/read-")
    g.note("register loopback test mode (76.19).")
    g.note(f"settle {SETTLE_NS}: see preamble()'s comment / design_notes.md 76.32.")
    g.raw(f"stepsize {T}")
    g.raw(f"settle {SETTLE_NS}")
    g.h(VDD)
    g.l(GND)
    g.x(SDA)
    g.h(SCL)
    g.h(DIS)
    for t in TX:
        g.l(t)
    g.l(RST_N)
    g.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH)
    checkpoints = [100, 500, 1000, 3000, 8000]
    prev = 0
    for cp in checkpoints:
        g.s(cp - prev)
        prev = cp
        g.note(f"---- t={cp}ns since reset asserted ----")
        g.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH)
    g.h(RST_N)
    g.s()
    g.note("---- $28-group DFFRBs (24 incl. rw/addr_match) force/release ----")
    g.force_release([dffrb_qs(i) for i in DFFRB_28_INSTANCES], value=0)
    g.s(5 * T)
    g.note("---- reset released ----")
    g.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH)
    g.note("(sda_oe stays a legitimate 0 here, not from resolving -- its own")
    g.note("DFFRB is in the $227=busy AND rst_n group, still held in reset")
    g.note("since busy hasn't gone high yet. That group's force/release happens")
    g.note("in start(), after the first real START condition -- see 76.13.)")
    g.raw("")
    g.note("end of irsim_reset_check.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    main_txt = gen_main()
    neg_txt = gen_negative()
    reset_txt = gen_reset_check()
    # run from within script/ (matches this project's other generator scripts)
    with open("../irsim/irsim_test_main.cmd", "w") as f:
        f.write(main_txt)
    with open("../irsim/irsim_test_negative.cmd", "w") as f:
        f.write(neg_txt)
    with open("../irsim/irsim_reset_check.cmd", "w") as f:
        f.write(reset_txt)
    print("wrote irsim_test_main.cmd:", len(main_txt.splitlines()), "lines")
    print("wrote irsim_test_negative.cmd:", len(neg_txt.splitlines()), "lines")
    print("wrote irsim_reset_check.cmd:", len(reset_txt.splitlines()), "lines")
