"""
gen_irsim_cmd_v9.py

Generates IRSIM .cmd stimulus scripts for the NEW (v9, LVS-clean-source-
derived) irsim/tr_1um_i2c_slave_async.sim -- see gen_irsim_sim_v9.py.
Supersedes gen_irsim_cmd.py, whose node-name constants (N45, N58, N102,
N106, XN3.busy, XN2/XN16/..., N34/N635/N666/N343, ...) refer to the OLD
.extracted-derived .sim and do not exist in the new one.

The bus-functional-model logic itself (CmdGen and every method on it)
is copied UNCHANGED from gen_irsim_cmd.py -- it is a mechanical
translation of script/test_i2c_slave_async.py / _negative.py, which
did not change, and the underlying workaround TECHNIQUES (force/release
a flip-flop's own QS node instead of its RSTB pin; the extra settle/hold
margins for DEL1 and the SDA pull-up RC) are properties of IRSIM's
switch-level solver and of general circuit topology (a back-to-back-
inverter storage node, an RC-charged bus), not of any specific net name
-- so they remain valid unchanged. Only two things needed re-deriving
for the new source: (1) the flat node names for each signal (all
"positional" derivations, no guessing -- see comments below), and (2)
confirming the new netlist still has the SAME structural groupings
(24+9 DFFRB instances split the same way, 4 distinct row-clock nets for
the 24-group) that the workarounds depend on -- confirmed by direct
inspection (design_notes.md 88.x).

---- Node mapping, all derived directly from schematic/
tr_1um_i2c_slave_async_ringosc_v9_lvs.spice (the same file
gen_irsim_sim_v9.py reads), NOT by trial and error: ----

RE-DERIVED 2026-09-01 after this session's GIO pad reassignment
(SCL/SDA moved P2->P1 / P13->P2, tx_data bits reshuffled across
P3/P4/P5/P6/P11/P12/P13/P14) -- the values below through v-1 of this
file were stale (still reflected the PRE-reassignment pad map) and
would have silently driven/watched the WRONG pads. Re-read positionally
off the current source's own x1 (OSS_FRAME_GIO)/x2
(i2c_slave_async_nrow_fm) instantiation lines (now at lines
1169-1178 of the ringosc-integrated file) -- no guessing:

Top-level signals (design_notes.md 87.4): the top subckt's own formal
pin list is already literal (P1..P15/VDD/VSS, from design_notes.md 82's
TOP_PIN_ORDER fix), and its instantiation lines (x1=OSS_FRAME_GIO,
x2=i2c_slave_async_nrow_fm) bind actual nets to both cells' formal pin
lists positionally -- reading straight off those two instantiation
lines (no probing/simulation needed) gives:
  rst_n=P15  scl=P1  sda_in=P2(=SDA pad itself, same node)
  sda_oe=NC_HIZ2 (the real net name of OSS_FRAME_GIO's HIZ2 pin, which
    core.sda_oe drives directly -- confirmed via x1's own instantiation
    line binding HIZ2->NC_HIZ2 and x2's binding sda_oe->NC_HIZ2, same
    net both sides)
  DIS=P7 (GIO's shared HIz control net for the 8 other bidirectional pads)
  tx_data[0..7] (bit0..bit7) = P11 P12 P13 P14 P6 P5 P4 P3 (bond-pad
    nodes themselves, sampled combinationally -- not registers)
  rx_data[0..7] (bit0..bit7) = NC_OUT11 NC_OUT12 NC_OUT13 NC_OUT14
    NC_OUT6 NC_OUT5 NC_OUT4 NC_OUT3 (each rx_data[n] binds to
    OSS_FRAME_GIO's OUT<pad> pin for whichever pad now carries bit n;
    NC_ = no chip pin connects that OUT pin further, but it's still a
    real top-scope net name, directly watchable)
  rx_valid/addr_match/rw/busy: these ARE formal ports of
    i2c_slave_async_nrow_fm in this source (unlike the old .extracted
    file, where they were internal-only) -- brought out to the top
    subckt as NC_CORE_rx_valid/addr_match/rw/busy (NC_ = no chip pin
    connects them, but they're still real top-scope net names,
    directly watchable, no instance-path prefix needed). Unaffected by
    the pad reassignment (not pad-facing) -- unchanged from before.

Internal-only DFFRB reset-group nodes (design_notes.md 88.x): grepped
every "... DFFRB" instance line inside i2c_slave_async_nrow_fm (33
total, x_269_ through x_301_) and read off each one's own RSTB (5th
net) and CK (7th net) fields directly -- both are formal DFFRB pins in
fixed position (".subckt DFFRB VDD QB D Q RSTB GND CK"), so no
disambiguation was needed. Two distinct RSTB nets found, tracing to the
SAME two gate-level derivations the old design used:
  "_008_" (24 instances) = NOR2(NOT(rst_n), start_pulse) -- releases as
    soon as rst_n releases (matches old $28 group exactly, same count).
  "_009_" (9 instances, incl. sda_oe's own register "sda_oe_r") =
    AND2_X1(busy, rst_n) -- only releases once busy first goes high
    (matches old $227 group exactly, same count: the old design's
    txreg[0..7]+sda_oe equivalent).
The "_008_" group's CK fields take exactly 4 distinct values
(scl_row0/1/2/3), matching the old design's "4 distinct derived CK
nets" structure. Each DFFRB instance's own internal QS storage node
(a real, non-port net named "QS" inside the DFFRB subckt body itself,
confirmed unchanged from the old design) flattens predictably to
"<top-instance-path>.QS" -- e.g. instance x_269_ (addr_match's own
flop) sits at top-level path "x2.x_269_", so its QS node is
"x2.x_269_.QS". All of this (33 QS nodes, 4 clock nets) was directly
grepped out of the generated .sim to confirm every node this script
references actually exists there (design_notes.md 88.2) -- not just
inferred from the spice source.
"""

VDD = "Vdd"
GND = "Gnd"
RST_N = "P15"
SCL = "P1"
SDA = "P2"
SDA_OE = "NC_HIZ2"
# P7/DIS: shared HIZ control for the 8 OTHER genuinely-bidirectional GIO
# pads (P3/P4/P5/P6/P11/P12/P13/P14 -- P1 left the DIS chain this
# session, now the plain-Hi-Z-always SCL pad) -- same role/net identity
# as the old design's "N2" (design_notes.md 76.19/76.25), just under
# this source's own literal top-level pin name. DIS=H (this script's
# default) lets TX be forced externally without contention; NEVER force
# TX while DIS=L.
DIS = "P7"
TX = ["P11", "P12", "P13", "P14", "P6", "P5", "P4", "P3"]  # bit0..bit7 -- pad P nodes, not a register
RX = ["NC_OUT11", "NC_OUT12", "NC_OUT13", "NC_OUT14", "NC_OUT6", "NC_OUT5", "NC_OUT4", "NC_OUT3"]  # bit0..bit7
BUSY = "NC_CORE_busy"
RW = "NC_CORE_rw"
ADDR_MATCH = "NC_CORE_addr_match"

# NOTE on BUFTH: no BUFTH-specific handling needed here -- gen_irsim_sim_v9.py
# substitutes BUFTH's definition with BUF_X1's (plain non-regenerative
# buffer, same pin list) directly in the .sim, same as the old generator
# (design_notes.md 76.15/87.2).

# All 33 DFFRB instances in i2c_slave_async_nrow_fm (x2 at the top chip),
# split by which RSTB net they use (design_notes.md 88.1 -- read directly
# off each instance line's RSTB field, not inferred):
#
# Group A (24 instances, RSTB="_008_" = NOR2(~rst_n, start_pulse) --
# releases as soon as rst_n releases, independent of busy):
DFFRB_28_INSTANCES = [
    "x2.x_269_", "x2.x_270_", "x2.x_271_", "x2.x_272_",
    "x2.x_273_", "x2.x_274_", "x2.x_275_", "x2.x_276_",
    "x2.x_285_", "x2.x_286_", "x2.x_287_", "x2.x_288_",
    "x2.x_289_", "x2.x_290_", "x2.x_291_", "x2.x_292_",
    "x2.x_294_", "x2.x_295_", "x2.x_296_", "x2.x_297_",
    "x2.x_298_", "x2.x_299_", "x2.x_300_", "x2.x_301_",
]
# Group B (9 instances incl. sda_oe's own register "sda_oe_r",
# RSTB="_009_" = AND2_X1(busy, rst_n) -- only actually releases once
# busy goes high, i.e. after the first real START condition):
DFFRB_227_INSTANCES = [
    "x2.x_277_", "x2.x_278_", "x2.x_279_", "x2.x_280_",
    "x2.x_281_", "x2.x_282_", "x2.x_283_", "x2.x_284_", "x2.x_293_",
]
ALL_DFFRB_INSTANCES = DFFRB_28_INSTANCES + DFFRB_227_INSTANCES


def dffrb_qs(inst):
    return f"{inst}.QS"


def dffrb_qm(inst):
    return f"{inst}.QM"


def dffrb_state_nodes(insts):
    """Both master AND slave storage nodes for each instance, flattened
    to a single list suitable for force_release()/force_release_gated().

    design_notes.md 94.1's QS/QB/D probe found the ROOT CAUSE of the
    bit_cnt[0] corruption: forcing QS alone is not enough for a mid-run
    (non-cold-start) reset. A real run showed QS correctly forced to 0,
    and STILL 0 right after being released (while the clock nets were
    still held low) -- but the INSTANT the clock nets were released back
    to the real network, QS flipped straight back to 1. The master
    latch's own storage node, QM, was never touched by the old code (it
    only forced QS) -- once the clock returns to a level where the
    QM<->QS transmission gate is transparent, QM's own STALE
    pre-reset value overwrites the QS value we just forced, undoing it.
    bit_cnt[1]/bit_cnt[2]/rw/addr_match were never seen to have this
    problem simply because their OWN stale QM values already happened to
    be 0 (the desired reset value) after the preceding WRITE transaction
    -- not because they're structurally immune. Fix: force/release BOTH
    QM and QS together everywhere a DFFRB gets reset."""
    return [dffrb_qs(i) for i in insts] + [dffrb_qm(i) for i in insts]


# The Group-A (24-instance) DFFRBs split across 4 distinct derived CK
# nets (each instance's own CK field, read directly off its instance
# line -- design_notes.md 88.1): addr_match/rw/phase[0..2] on
# "x2.scl_row0"; bit_cnt[0..2]/last_bit_pending on "x2.scl_row1";
# rx_data[0]/shreg[0] on "x2.scl_row2"; rx_data[1..7]/shreg[1..6] on
# "x2.scl_row3". Needed by force_release_gated() for mid-run Group-A
# resets (see its docstring below for why).
DFFRB_28_CLOCK_NETS = ["x2.scl_row0", "x2.scl_row1", "x2.scl_row2", "x2.scl_row3"]

T = 20  # ns, matches script/test_i2c_slave_async.py's T -- value is
        # arbitrary for this async design; only used as IRSIM's stepsize.

# IRSIM's "settle" command: delays how long IRSIM waits before declaring
# a node genuinely conflicted/undefined ("X"), instead of reacting to
# the very first instant a node looks like it's driven two ways at once.
# This is IRSIM's own documented fix for exactly a DFFRB-style back-to-
# back-inverter (QM/QS) topology (design_notes.md 76.31/76.32) -- a
# property of the flip-flop's transistor topology, unchanged in this
# netlist regeneration. 50ns per IRSIM's own docs ("on the order of
# 50" -- longer than a gate delay, shorter than a clock phase; this
# async design has no clock phase to bound it by).
SETTLE_NS = 50

# Margin between "SDA is set (released to the pull-up, or forced) while
# SCL is low" and "SCL actually rises" -- real I2C data-setup-before-
# clock timing, needed because the external SDA pull-up is a real RC
# (not an ideal driver) and needs real time to charge SDA's node
# capacitance under the characterized TR-1um.prm (design_notes.md
# 76.37-76.40). A property of the pull-up's calibrated resistance and
# the bus's capacitance, not of any specific net name -- unchanged here.
SDA_RELEASE_SETTLE_NS = 500

SLAVE_ADDR = 0x50


class CmdGen:
    def __init__(self):
        self.lines = []
        # Ordered, 1:1 with every d()/checked_dump() call in generation
        # order -- lets check_irsim_tb_log.py line up each block of dump
        # output in a REAL run's log with what it means, purely by
        # position (no timestamps or labels needed in the log itself).
        # Entries from plain d() have expect=None (informational only,
        # not compared); entries from checked_dump() carry an expected
        # {node: 0/1} dict compared against the real run automatically --
        # this is what makes a generated .cmd "self-checking" the way
        # i2c_slave_async_tb.v's check()/errors/RESULT are, since IRSIM's
        # own .cmd language has no conditionals/arithmetic to do this
        # itself (design_notes.md 98.x).
        self.checks = []

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
        self.checks.append({"label": None, "nodes": list(nodes), "expect": None, "group": None})

    def checked_dump(self, label, expect, group=None):
        """Like d(), but records `label` and the expected {node: 0/1}
        values so check_irsim_tb_log.py can automatically verify a real
        run's log against them and print a PASS/FAIL summary -- the
        IRSIM-side equivalent of i2c_slave_async_tb.v's check() task.
        `group`, if given, tags several related checked_dump() calls
        (e.g. the 8 individual bits of a received byte) so the checker
        can also print one synthesized higher-level check from them, the
        same way i2c_slave_async_tb.v's read_byte() task samples 8 bits
        without individually asserting each one, then the testbench
        checks only the reconstructed byte."""
        nodes = list(expect.keys())
        self.note(f"CHECK: {label}")
        self.lines.append("d " + " ".join(nodes))
        self.checks.append({"label": label, "nodes": nodes, "expect": expect, "group": group})

    def force_release(self, nodes, value=0):
        """One-time symmetry-break for a batch of nodes stuck in a cold-X
        feedback loop (a DFFRB's own QS node, at cold start before its CK
        has ever toggled) -- force them all to `value`, settle, then
        release them all back to the network, which (once its other
        inputs are known) holds the correct value on its own. See
        design_notes.md 76.12/76.13.

        Only valid when the target nodes are GENUINELY floating (e.g.
        cold start, before CK has ever toggled and both of DFFRB's
        QM<->QS/QS<->net5 transmission gates are still X-gated). Do NOT
        reuse this for a mid-run reset once CK has a real, defined level
        -- see force_release_gated() and design_notes.md 76.41/76.42."""
        setter = self.l if value == 0 else self.h
        for n in nodes:
            setter(n)
        self.s()
        for n in nodes:
            self.x(n)
        self.s()

    def force_release_gated(self, nodes, gate_nets, value=0, probe=None):
        """Like force_release(), but for MID-RUN reuse once CK has a real,
        settled level (not X) -- design_notes.md 76.41/76.42 found that
        plain force_release() on a DFFRB's QS gets immediately overridden
        in this case: DFFRB has TWO transmission gates touching QS
        (QM<->QS, transparent when CK=1; QS<->net5, transparent when
        CK=0) -- once CK is a real defined value, exactly one of the two
        is ALWAYS transparent, so QS is never actually isolated the way
        it is at cold start (both gates X-gated together).

        `nodes` is expected to be dffrb_state_nodes(...)'s output -- BOTH
        the QS (slave) and QM (master) storage nodes for each instance,
        not just QS. An earlier version of this function forced CK LOW
        and only QS (design_notes.md 76.41/76.42's original fix). A real
        run (design_notes.md 94.1) found that fix incomplete: QS itself
        stayed correctly forced through the whole CK=0 window (net5's
        self-reinforcing loop does hold it, as originally reasoned), but
        QM was never forced at all, and the master latch (net2's own
        pass-gates, MM1/MM7 in DFFRB's body) is DIRECTLY TRANSPARENT TO
        D whenever CK=0 -- there is no self-reinforcing loop protecting
        QM the way there is for QS, so QM continued tracking real D the
        entire time regardless of what was forced into it. Once the
        clock nets were released and a later real CK 0->1 edge made
        QM<->QS transparent again, QM's un-reset, D-tracking value
        overwrote the QS value that had been correctly held until then.

        Fix (design_notes.md 94.3): force CK **HIGH** instead of LOW.
        At CK=1, DFFRB's own topology is the opposite of the CK=0 case:
        the master latch (QM) is OPAQUE (isolated from D, so an external
        force on QM actually sticks, the same way net5's loop protected
        QS at CK=0), and QM<->QS is transparent (so forcing QM also
        drives QS to match through the network itself, not by fighting
        it -- forcing QS at the same time is redundant but harmless).
        Doing this for the WHOLE group at once (not just one instance)
        matters: several other Group-A instances share these same
        row-clock nets, so they get isolated and reset together too."""
        setter = self.l if value == 0 else self.h
        for g in gate_nets:
            self.h(g)
        for n in nodes:
            setter(n)
        self.s()
        if probe:
            self.note("probe: right after forcing (clock still forced HIGH)")
            self.d(*probe)
        for n in nodes:
            self.x(n)
        self.s()
        if probe:
            self.note("probe: right after releasing QM/QS (clock still forced HIGH)")
            self.d(*probe)
        for g in gate_nets:
            self.x(g)
        self.s()
        if probe:
            self.note("probe: right after releasing clock nets too")
            self.d(*probe)

    def preamble(self, reset_hold_ns=3000):
        self.note("Auto-generated by script/gen_irsim_cmd_v9.py -- do not hand-edit.")
        self.note("Ties VDD/VSS, releases SDA to the (now sda_oe-gated) weak pull-up,")
        self.note("forces a known-0 tx_data bus and scl=1 idle, then pulses rst_n.")
        self.note(f"Reset is held for {reset_hold_ns}ns (not just a few stepsizes) --")
        self.note("this design's \"busy\" is a cross-coupled SR latch (not a DFFRB),")
        self.note("and RSTB for 9 of the 33 DFFRBs (incl. sda_oe's) is gated as")
        self.note("\"busy AND rst_n\", so busy's own latch must resolve out of its")
        self.note("post-power-up X state before those registers' clear is well-")
        self.note("defined again after rst_n releases (see design_notes.md 76.10).")
        self.note("SDA needs no explicit \"h\" override here: the SDA pull-up PMOS's")
        self.note("gate is the pad's own real drive-gate node (gen_irsim_sim_v9.py),")
        self.note("and sda_oe is held at a genuinely DEFINED 0 throughout this whole")
        self.note("window by AND-domination alone (Group-B RSTB=busy AND rst_n=0")
        self.note("while rst_n=0, and stays 0 even after rst_n releases as long as")
        self.note("busy hasn't gone high yet) -- so the pull-up's gate is never X")
        self.note("here, and SDA resolves cleanly on its own.")
        self.note("DIS (P7) is forced H -- normal operation, not the loopback/test")
        self.note("mode where DIS=L makes the read-data register echo back whatever")
        self.note("was last written instead of the real RX shift register (76.19).")
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
        self.note("feedback problem as BUFTH's OLD (pre-substitution) topology, one")
        self.note("level deeper: RSTB only force-drives QB/Q directly, never the")
        self.note("internal master/slave storage nodes (QM/QS), so once RSTB")
        self.note("genuinely releases -- with this design's async, never-yet-toggled")
        self.note("clocking -- Q can stay stuck at X forever even though 0 (nothing")
        self.note("has been clocked in yet) is the only physically sensible value.")
        self.note("QS is the actual independent root (QB/Q are plain inverters of it")
        self.note("once RSTB=1); confirmed via a real run on this cell (76.13).")
        self.note("Force/release all 24 Group-A instances (RSTB=\"_008_\") here; the")
        self.note("9 Group-B instances (RSTB=\"_009_\"=busy AND rst_n, incl. sda_oe's)")
        self.note("only release once busy actually goes high, so those get the same")
        self.note("treatment in start(), right after the first START condition.")
        self.force_release(dffrb_state_nodes(DFFRB_28_INSTANCES), value=0)
        self.s(5 * T)
        self.note("check: still defined immediately after release")
        self.d(SDA_OE, BUSY, RW, ADDR_MATCH)
        self.raw("")

    # ---- bus-functional primitives, 1:1 with test_i2c_slave_async.py ----
    def start(self, first=False, group_a_mode="gated", debug_probe=None):
        """group_a_mode controls how the non-first-START branch handles
        Group-A's QS reset (ignored when first=True, which always uses a
        plain one-time force_release() -- see design_notes.md 89.1's
        finding that this design doesn't seem to need forcing at all, an
        open question only for the REPEAT-START case so far):
          "gated" (default) -- force_release_gated() as before: force QM
            AND QS, AND the group's own row-clock nets HIGH, together.
            This is what irsim_test_main.cmd uses (design_notes.md 94.3
            for why CK is forced HIGH, not LOW as an earlier revision
            did).
          "plain" -- force_release() on QS only, no clock-net forcing
            (the OLD design's technique that a real run on THIS netlist
            has not yet been tried).
          "none" -- skip the force/release step entirely and let the
            circuit's own dynamics settle on their own, per the
            hypothesis (design_notes.md 89.1) that v9's re-synthesized
            netlist may not have the cold-X QM/QS deadlock the old
            design did at all, given irsim_reset_check.cmd resolved
            cleanly on this .sim WITHOUT ever forcing anything."""
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
            self.note("time, which releases the 9 Group-B DFFRBs (RSTB=\"_009_\"=busy")
            self.note("AND rst_n, incl. sda_oe's own register). Same cold-X QS")
            self.note("deadlock as Group-A in preamble() -- see 76.13 -- give them")
            self.note("the same one-time force/release now that Group-B has actually")
            self.note("released.")
            self.force_release(dffrb_state_nodes(DFFRB_227_INSTANCES), value=0)
            self.note("check: sda_oe now holds a defined value instead of X")
            self.d(SDA_OE)
        self.note("The core's phase/bit_cnt/shreg/addr_ok/rw_bit register bank is")
        self.note("async-reset via a NOR2-derived net (gate-level Group-A RSTB,")
        self.note("\"_008_\") that is structurally intended to pulse briefly on every")
        self.note("START condition (RTL: rst_scl_domain = ~rst_n | start_pulse).")
        self.note("Two independent real runs on the OLD .sim (incl. substituting the")
        self.note("delay cell with a symmetric buffer cascade) proved this pulse")
        self.note("structurally never fires under IRSIM at this simulation")
        self.note("granularity -- not a settling-time shortfall, but IRSIM's ternary")
        self.note("solver settling the whole combinational cone within one timestep")
        self.note("(design_notes.md 76.22-76.24). busy's OWN edge-detect (a")
        self.note("differently-shaped network) is unaffected and just proved START")
        self.note("WAS correctly detected at the gate level (busy=1 above).")
        self.note("First attempt (on the OLD .sim): force/release the RSTB net")
        self.note("itself directly -- this FAILED on a real run (stale value read")
        self.note("back immediately after release), because RSTB only force-drives")
        self.note("Q/QB WHILE asserted, never the internal QM/QS storage (76.13).")
        self.note("Fix: force/release each instance's OWN QS node directly (same")
        self.note("proven technique as preamble()'s cold-start fix), bypassing RSTB")
        self.note("entirely, for all 24 Group-A instances (this also covers")
        self.note("rw/addr_match's own registers, which share this same group).")
        if first:
            self.note("first START: SCL has only ever been held high so far (never")
            self.note("toggled low-high for a real bit yet), so Group-A's own")
            self.note("row-clock nets are still at their cold-start X -- both of")
            self.note("QS's transmission gates are still X-gated (genuinely floating),")
            self.note("same as preamble()'s cold-start fix -- plain force_release() is")
            self.note("valid here.")
            self.force_release(dffrb_state_nodes(DFFRB_28_INSTANCES), value=0)
        elif group_a_mode == "none":
            self.note("NOT the first START, group_a_mode=\"none\" (EXPERIMENT,")
            self.note("design_notes.md 89.6): skipping Group-A QS force/release")
            self.note("entirely here, testing the hypothesis that this")
            self.note("re-synthesized netlist doesn't have the old design's cold-X")
            self.note("QM/QS deadlock at all (irsim_reset_check.cmd resolved cleanly")
            self.note("with zero forcing anywhere -- 89.1). If addr_match/rw now")
            self.note("assert correctly for this 2nd START where the \"gated\" mode")
            self.note("previously did not (89.3), that confirms force_release_gated()")
            self.note("was unnecessary (or actively harmful) on this netlist, not")
            self.note("that the design itself has a bug.")
        elif group_a_mode == "plain":
            self.note("NOT the first START, group_a_mode=\"plain\" (EXPERIMENT):")
            self.note("force_release() on QS only, no clock-net forcing -- the OLD")
            self.note("design's pre-76.41 technique, not yet tried on this netlist.")
            self.force_release(dffrb_state_nodes(DFFRB_28_INSTANCES), value=0)
        else:
            self.note("NOT the first START: real SCL clocking has already happened")
            self.note("in an earlier transaction, so Group-A's own row-clock nets")
            self.note("now hold real, DEFINED levels -- NOT the cold-start X that")
            self.note("made plain force_release() work above.")
            self.note("Diagnostic history (design_notes.md 89-94): plain force_release()")
            self.note("on QS alone breaks addr_match (76.41/76.42's transparent-latch")
            self.note("finding). Gating the row-clock nets LOW while forcing QS alone")
            self.note("(an earlier revision of this function) LOOKED like it worked for")
            self.note("most Group-A registers but silently left bit_cnt[0] wrong (94.1):")
            self.note("QM (the master latch) is directly transparent to D whenever CK=0,")
            self.note("so it was never actually reset, and re-corrupted QS the moment")
            self.note("the clock nets were released. Fix: force BOTH QM and QS, AND")
            self.note("gate the row-clock nets HIGH (not low) -- at CK=1 the master is")
            self.note("OPAQUE (a force on QM actually sticks) and QM<->QS is transparent")
            self.note("(QS follows QM through the network itself). See")
            self.note("force_release_gated()'s docstring for the full derivation (94.3).")
            self.force_release_gated(
                dffrb_state_nodes(DFFRB_28_INSTANCES),
                DFFRB_28_CLOCK_NETS, value=0, probe=debug_probe)
        self.note("check: phase/bit_cnt-owning registers cleared (rw/addr_match are")
        self.note("in this same Group-A, so also visible here)")
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
        self.note("STOP's edge-detect path routes through a real intentional delay")
        self.note("element (design_notes.md 76.10/76.13/76.20/76.21). A short")
        self.note(f"settle ({settle_before_ns}ns) is inserted first so any residual")
        self.note("propagation from the immediately-preceding bit's SDA activity")
        self.note("clears before the STOP sequence starts counting its own hold.")
        self.note(f"SDA is then held low {sda_low_hold_ns}ns (not just one {T}ns")
        self.note("stepsize) before releasing it, so the falling edge has time to")
        self.note("actually propagate through the delay cell before the rising")
        self.note("(STOP) edge arrives -- otherwise the edge gets \"swallowed\" and")
        self.note("busy never clears (see design_notes.md 76.20/76.21 for the real")
        self.note("run that found this on the OLD .sim's same DEL1-based topology).")
        self.s(settle_before_ns)
        self.l(SDA)
        self.h(SCL)
        self.s(sda_low_hold_ns)
        self.x(SDA)          # SDA 0->1 while SCL=1 : STOP
        self.note("same real SDA pull-up RC recovery margin as send_bit() etc.")
        self.note("(76.39) -- give SDA time to actually finish rising under the")
        self.note("calibrated TR-1um.prm pull-up before checking busy below.")
        self.s(SDA_RELEASE_SETTLE_NS)
        self.note(f"check: busy cleared after STOP ({label})")
        self.d(BUSY)


def gen_main(group_a_mode="gated", label="irsim_test_main.cmd"):
    g = CmdGen()
    g.note(f"{label} -- write 0xA5 then read 0x3C, mirrors")
    g.note("script/test_i2c_slave_async.py exactly (SLAVE_ADDR=0x50).")
    if group_a_mode != "gated":
        g.note(f"** EXPERIMENT VARIANT: 2nd START uses group_a_mode=\"{group_a_mode}\" **")
        g.note("(design_notes.md 89.6 -- see start()'s docstring in gen_irsim_cmd_v9.py)")
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

    g.start(group_a_mode=group_a_mode)
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
    g.note(f"end of {label}")
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
    g.note(f"same SDA pull-up RC recovery margin as send_bit()/read_ack() etc.")
    g.note(f"({SDA_RELEASE_SETTLE_NS}ns, not just one {T}ns stepsize) -- this inline")
    g.note("NACK check previously used a single stepsize here (carried over")
    g.note("unmodified from the old gen_irsim_cmd.py), which is the same margin")
    g.note("gap design_notes.md 76.39/76.40 found and fixed everywhere else SDA")
    g.note("is released -- a real v9 run (design_notes.md 89.x) caught SDA still")
    g.note("reading 0 here (looking like a false ACK) purely from not having had")
    g.note("time to rise yet, even though addr_match itself already correctly")
    g.note("read 0 (foreign address correctly not matched).")
    g.s(SDA_RELEASE_SETTLE_NS)
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
    g.note("be held this long: busy is a cross-coupled SR latch (not")
    g.note("a DFFRB) that must itself resolve out of X, since 9 of the 33")
    g.note("DFFRBs (incl. sda_oe's) gate their clear as \"busy AND rst_n\".")
    g.note("SDA is just released (\"x\") to the sda_oe-gated weak pull-up (see")
    g.note("gen_irsim_sim_v9.py) -- no explicit \"h\" override needed: sda_oe is")
    g.note("held at a genuinely DEFINED 0 throughout by AND-domination alone")
    g.note("(Group-B RSTB=busy AND rst_n=0 while rst_n=0, and stays 0 after")
    g.note("release as long as busy hasn't gone high yet), so the pull-up's")
    g.note("gate is never X and SDA resolves cleanly on its own (76.11/76.16).")
    g.note("DFFRB (33x, incl. rw/addr_match's own registers) has a similar cold-X")
    g.note("problem via its internal QS node -- see 76.13. One-time force/release")
    g.note("below. (BUFTH had a related issue but is substituted with BUF_X1 in")
    g.note("the .sim itself, see 76.15/87.2 -- no BUFTH-specific handling here.)")
    g.note("DIS (P7) is forced H -- normal operation, not the write/read-register")
    g.note("loopback test mode (76.19).")
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
    g.note("---- Group-A DFFRBs (24 incl. rw/addr_match) force/release ----")
    g.force_release(dffrb_state_nodes(DFFRB_28_INSTANCES), value=0)
    g.s(5 * T)
    g.note("---- reset released ----")
    g.d(SDA, SDA_OE, BUSY, RW, ADDR_MATCH)
    g.note("(sda_oe stays a legitimate 0 here, not from resolving -- its own")
    g.note("DFFRB is in Group B (busy AND rst_n), still held in reset since")
    g.note("busy hasn't gone high yet. That group's force/release happens in")
    g.note("start(), after the first real START condition -- see 76.13.)")
    g.raw("")
    g.note("end of irsim_reset_check.cmd")
    return "\n".join(g.lines) + "\n"


if __name__ == "__main__":
    main_txt = gen_main()
    neg_txt = gen_negative()
    reset_txt = gen_reset_check()
    # EXPERIMENT (design_notes.md 89.6): 2nd START skips Group-A QS
    # force/release entirely, testing whether v9's re-synthesized
    # netlist needs it at all -- see start()'s docstring. Written to a
    # SEPARATE file so the validated baseline irsim_test_main.cmd (WRITE
    # transaction end-to-end confirmed correct, 89.2) is untouched.
    noforce_txt = gen_main(group_a_mode="none", label="irsim_test_main_noforce.cmd")
    # run from within script/ (matches this project's other generator scripts)
    with open("../irsim/irsim_test_main.cmd", "w") as f:
        f.write(main_txt)
    with open("../irsim/irsim_test_negative.cmd", "w") as f:
        f.write(neg_txt)
    with open("../irsim/irsim_reset_check.cmd", "w") as f:
        f.write(reset_txt)
    with open("../irsim/irsim_test_main_noforce.cmd", "w") as f:
        f.write(noforce_txt)
    print("wrote irsim_test_main.cmd:", len(main_txt.splitlines()), "lines")
    print("wrote irsim_test_negative.cmd:", len(neg_txt.splitlines()), "lines")
    print("wrote irsim_reset_check.cmd:", len(reset_txt.splitlines()), "lines")
    print("wrote irsim_test_main_noforce.cmd:", len(noforce_txt.splitlines()), "lines")
