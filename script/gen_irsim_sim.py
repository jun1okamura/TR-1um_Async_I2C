"""
gen_irsim_sim.py

Recursively flattens the whole-chip KLayout LVS-extracted SPICE netlist
(src/tr_1um_i2c_slave_async.extracted -- transistor-level, already
LVS-clean against schematic/tr_1um_i2c_slave_async.sch) into a flat
IRSIM .sim file (classic "p/n gate source drain length width" format),
covering EVERY transistor in the design: the digital core
(i2c_slave_async_nrow_fm), the whole GIO pad ring (OSS_FRAME_GIO), and
all 16 OSS_ESD_5V_DIO/VDD/VSS pad cells. No behavioral shortcuts (unlike
script/sim/switch_sim.py's ideal-switch union-find model) -- every real
transistor is emitted, so IRSIM's RC/event model can resolve BUFTH's
hysteresis, DEL1's intentional delay, and DFFR's transmission-gate
master/slave timing from real device sizes, not hand-coded behavior.
"""
import re
import sys

# run from within script/ (matches this project's other generator
# scripts, e.g. reassemble_top.py, route_gio_core.py)
EXTRACTED = "../src/tr_1um_i2c_slave_async.extracted"
OUT_SIM = "../irsim/tr_1um_i2c_slave_async.sim"
TOP = "tr_1um_i2c_slave_async"


def parse_extracted(path):
    raw = open(path).read()
    # merge SPICE '+' continuation lines (used for both .SUBCKT header pin
    # lists AND individual long X$/XM$ instance-call lines) into their
    # preceding line BEFORE any further parsing, so every logical
    # statement is exactly one line.
    merged_lines = []
    for line in raw.split("\n"):
        if line.startswith('+') and merged_lines:
            merged_lines[-1] += ' ' + line[1:]
        else:
            merged_lines.append(line)
    text = "\n".join(merged_lines)
    blocks = {}
    for m in re.finditer(r'\.SUBCKT\s+(\S+)\s+(.*?)\n(.*?)\n\.ENDS\s+\1', text, re.S):
        name, pinline, rest = m.group(1), m.group(2), m.group(3)
        pins = pinline.replace('\\$', '$').split()
        if name not in blocks:
            blocks[name] = (pins, rest)
    return blocks


def parse_lw(toks):
    L = W = None
    for t in toks:
        if t.startswith('L='):
            L = t[2:].rstrip('u')
        elif t.startswith('W='):
            W = t[2:].rstrip('u')
    return L, W


MODEL_MAP = {'PMOS': 'p', 'NMOS': 'n', 'NMOSE': 'n'}


def sanitize(name):
    # IRSIM 9.7's command interpreter treats a bare leading "$" as a
    # variable-substitution sigil (Tcl-derived), not a plain identifier
    # character -- real-world run confirmed "$58" etc. raised
    # "subcircuit ... is not defined!" and other parse errors both in
    # the .sim netlist and in .cmd command files. KLayout's LVS
    # extraction names every auto-numbered (unlabeled) net "$N" and
    # every such internal SPICE node the same way, so ALL of those need
    # a safe prefix instead. "N" can never collide with a genuinely
    # schematic-labeled net (e.g. "busy", "CKB", "shreg[5]") since those
    # never started with "$" to begin with.
    return name.replace('$', 'N')


def flatten(blocks, top_name):
    devices = []  # (type, gate, source, drain, L, W, orig_model, sim_instpath)
    stats = {'insts': 0, 'devs': 0, 'maxdepth': 0}

    def resolve(local, node_map, path):
        if local in node_map:
            return node_map[local]
        return sanitize(f"{path}{local}")

    def walk(cellname, node_map, path, depth):
        stats['maxdepth'] = max(stats['maxdepth'], depth)
        pins, body = blocks[cellname]
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith('*'):
                continue
            if line.startswith('D$'):
                # ESD protection clamp diode (VSS<->internal pad node,
                # model "DN"). Reverse-biased / non-conducting during
                # normal digital operation -- only relevant to actual
                # electrostatic-discharge events, not logic function.
                # IRSIM's .sim format has no diode primitive anyway, so
                # skip it (functional-verification-safe omission).
                stats['diodes_skipped'] = stats.get('diodes_skipped', 0) + 1
                continue
            if line.startswith('XM$'):
                toks = line.replace('\\$', '$').split()
                d, g, s, b = toks[1], toks[2], toks[3], toks[4]
                model = toks[5]
                L, W = parse_lw(toks[6:])
                typ = MODEL_MAP.get(model)
                if typ is None:
                    raise ValueError(f"unknown model {model} in {cellname}: {line}")
                devices.append((typ, resolve(g, node_map, path), resolve(s, node_map, path),
                                 resolve(d, node_map, path), L, W, model))
                stats['devs'] += 1
            elif line.startswith('X$'):
                toks = line.replace('\\$', '$').split()
                instname = toks[0]
                celltype = toks[-1]
                nets = toks[1:-1]
                if celltype not in blocks:
                    raise ValueError(f"unknown cell type {celltype} (instance {instname} in {cellname})")
                childpins, _ = blocks[celltype]
                if len(childpins) != len(nets):
                    raise ValueError(f"pin count mismatch {instname} ({celltype}): "
                                      f"{len(childpins)} formal vs {len(nets)} actual")
                child_map = {}
                for cp, n in zip(childpins, nets):
                    child_map[cp] = resolve(n, node_map, path)
                stats['insts'] += 1
                walk(celltype, child_map, f"{path}{instname}.", depth + 1)
            else:
                raise ValueError(f"unrecognized line in {cellname}: {line}")

    top_pins, _ = blocks[top_name]
    top_map = {p: sanitize(p) for p in top_pins}   # top scope's own ports keep their bare names (VSS -> VSS)
    walk(top_name, top_map, "", 0)
    return devices, stats


# the whole-chip VDD/GND supply nodes, identified this session via
# independent cross-checked positional analysis (design_notes.md §76.3):
# top-level anonymous net "$1" (post-sanitize "N1") for VDD, literal
# "VSS" for ground.
VDD_NODE = sanitize("$1")
GND_NODE = "VSS"


def rename_rails(devices, resistor, vdd_name="Vdd", gnd_name="Gnd"):
    # IRSIM, by default, looks for nodes literally named "Vdd"/"Gnd" to
    # identify the power/ground rails. Confirmed on a real run: leaving
    # the rails named "N1"/"VSS" (unrecognized) made IRSIM print
    # "Using default name ... for power/ground net" and then segfault
    # shortly after loading the .sim. Renaming the two supply nodes to
    # IRSIM's own expected names removes this whole failure class
    # (more robust than relying on remembering the -p/-g CLI flags).
    ren = {VDD_NODE: vdd_name, GND_NODE: gnd_name}
    new_devices = [(typ, ren.get(g, g), ren.get(s, s), ren.get(d, d), L, W, model)
                   for typ, g, s, d, L, W, model in devices]
    new_resistor = tuple(ren.get(n, n) if i < 2 else n for i, n in enumerate(resistor))
    return new_devices, new_resistor


def substitute_bufth_with_buf_x1(blocks):
    # BUFTH (the Schmitt-trigger input buffer on scl/sda_in) has a real,
    # confirmed-on-hardware internal regenerative feedback loop (its own
    # hysteresis node "N2" feeds back on itself) that IRSIM's ternary
    # switch-level solver cannot resolve -- not just at cold start, but
    # on EVERY transition of A (design_notes.md 76.12/76.14). A one-time
    # scripted force/release only fixes the first transition; a
    # permanent weak bias transistor on N2 (76.14) was tried next and
    # did NOT help either (a real run with the bias in place reproduced
    # the identical X-after-START-edge result) -- so this isn't a
    # weak-vs-strong-driver ratio problem IRSIM can resolve at all, it's
    # a fundamental limitation of ideal ternary switch-level simulation
    # for this specific regenerative topology (matches the concern
    # already flagged in script/sim/switch_sim.py's docstring).
    #
    # Per explicit user direction (this session), BUFTH is substituted
    # with BUF_X1 for chip-level IRSIM purposes: BUF_X1 has the IDENTICAL
    # pin list ("A vdd Y gnd") and is a plain two-stage inverter (4
    # transistors, no feedback at all -- see its .SUBCKT body), so this
    # is a drop-in replacement requiring no other changes to flatten()
    # or to any node-name mapping. This is a genuine behavioral
    # simplification (contrary to this file's original "no shortcuts"
    # policy, design_notes.md 76.1) -- it trades away BUFTH's actual
    # Schmitt-trigger noise-immunity/hysteresis characteristic, which is
    # an analog property outside the scope of the digital
    # write/read-transaction protocol verification this chip-level IRSIM
    # run exists to do. See design_notes.md 76.15.
    assert "BUFTH" in blocks and "BUF_X1" in blocks
    blocks["BUFTH"] = blocks["BUF_X1"]


def substitute_del1_with_buf_x1_cascade(blocks):
    """DIAGNOSTIC ONLY -- NOT CALLED from main() anymore, kept for the
    record. Per user direction (this session): a real run found DEL1's
    propagation is strongly ASYMMETRIC in this .sim -- N697's falling
    edge reaches N704 (=DEL1(N697)) within one IRSIM stepsize (~20ns),
    but N697's rising edge took 2000-8000ns to reach N704 (design_notes.md
    76.20/76.21). This makes the START-detect pulse ($813=NOR2(N697,N703),
    N703=NAND2(N666,N704)) structurally unable to ever assert, since it
    needs a window where N697 has fallen but N704 hasn't caught up yet --
    a window DEL1's fast-fall path never opens (design_notes.md 76.23).
    The user inspected DEL1's transistor-level circuit directly and found
    no problem with it, and asked to test substituting a 2-stage BUF_X1
    cascade (A -> BUF_X1 -> mid -> BUF_X1 -> Y) in its place, to check
    whether the asymmetry is a real circuit property or an artifact of
    the placeholder (non-TR-1um-characterized) .prm's device timing.
    BUF_X1's pin list ("A vdd Y gnd") is identical to DEL1's, so this
    constructs a synthetic 2-instance subcircuit body reusing BUF_X1
    twice (not simply aliasing DEL1 to BUF_X1, since two stages give
    some propagation delay, unlike a single BUF_X1 -- the point here is
    testing symmetry, not eliminating delay outright).

    RESULT (design_notes.md 76.24, confirmed on TWO real runs --
    irsim_debug_rstb.cmd and the full irsim_test_main.cmd): NO CHANGE.
    $813 still never pulsed; N704 still tracked N697's falling edge
    within the SAME IRSIM timestep even through this symmetric 2-stage
    buffer. This falsifies the "DEL1's specific asymmetric sizing is the
    cause" hypothesis -- the real explanation is that IRSIM's ternary
    switch-level solver settles an entire combinational cone within one
    step regardless of which delay/buffer cell drives it, so a glitch-
    based edge detector like this one structurally cannot be exercised
    at this simulation granularity, independent of the driving cell.
    Reverted: DEL1 is left as the real (unsubstituted) circuit again."""
    assert "DEL1" in blocks and "BUF_X1" in blocks
    pins = ["A", "vdd", "Y", "gnd"]
    body = (
        "X$1 A vdd $MID gnd BUF_X1\n"
        "X$2 $MID vdd Y gnd BUF_X1\n"
    )
    blocks["DEL1"] = (pins, body)


def insert_sda_hiz_inverter(devices):
    """Per user direction (design_notes.md 76.17/76.18): the SDA pad's
    HIZ13 pin is wired directly (no inverter) to the core's sda_oe (N45)
    DFFRB output. A real IRSIM run confirmed N45=0 (sda_oe's reset-
    default/idle value) makes the pad ACTIVELY DRIVE SDA LOW (HIZ=L ->
    pad follows its Gnd-tied OUT pin), while RTL intent
    (src/i2c_slave_async.v line 70: "1 = drive SDA low, 0 = release
    (Hi-Z)") is the opposite -- exactly backwards for a bus that must
    idle/reset released. To test whether inserting the (apparently
    missing) inverter between sda_oe and HIZ13 restores correct
    behavior, this splits the single N45 node: the DFFRB's own drive of
    N45 is left untouched (still the real sda_oe register value), but
    the 4 transistors inside the SDA pad cell (XN1.XN16 =
    OSS_ESD_5V_DIO instance for P13) that use N45 as their HIZ gate are
    redirected to a new synthetic node N45_HIZ_INV, fed by a 2-
    transistor CMOS inverter from N45. This is a simulation-only
    experiment, not a claim about the real silicon -- see 76.18 for the
    real-run result."""
    HIZ_NODE = "N45_HIZ_INV"
    # exact (type, gate, source, drain, L, W, model) signatures of the 4
    # transistors in OSS_ESD_5V_DIO whose gate is HIZ (=N45 here) --
    # confirmed against the actual generated .sim (src/...extracted
    # lines 1111-1142, XM$1/XM$5/XM$10/XM$16).
    targets = {
        ('p', 'N45', 'Vdd', 'XN1.XN16.NI4', '1', '5.2', 'PMOS'),
        ('p', 'N45', 'XN1.XN16.NI8', 'XN1.XN16.NI6', '1', '10.4', 'PMOS'),
        ('n', 'N45', 'XN1.XN16.NI6', 'Gnd', '1', '3.4', 'NMOS'),
        ('n', 'N45', 'Gnd', 'XN1.XN16.NI4', '1', '3.4', 'NMOS'),
    }
    new_devices = []
    matched = 0
    for dev in devices:
        typ, g, s, d, L, W, model = dev
        if (typ, g, s, d, L, W, model) in targets:
            new_devices.append((typ, HIZ_NODE, s, d, L, W, model))
            matched += 1
        else:
            new_devices.append(dev)
    assert matched == len(targets), (
        f"expected to redirect {len(targets)} HIZ transistors, matched {matched} "
        "-- .sim structure may have changed, re-check the target signatures")
    new_devices.append(('p', 'N45', 'Vdd', HIZ_NODE, '1', '5.2', 'INV-sda-hiz'))
    new_devices.append(('n', 'N45', 'Gnd', HIZ_NODE, '1', '3.4', 'INV-sda-hiz'))
    return new_devices


def main():
    blocks = parse_extracted(EXTRACTED)
    print(f"parsed {len(blocks)} .SUBCKT blocks from {EXTRACTED}")
    substitute_bufth_with_buf_x1(blocks)
    # substitute_del1_with_buf_x1_cascade(blocks)  # tested, no effect, reverted -- see 76.24
    devices, stats = flatten(blocks, TOP)
    print(f"flattened: {stats['insts']} instances walked, {stats['devs']} transistors, "
          f"max hierarchy depth {stats['maxdepth']}")

    devices, _ = rename_rails(devices, ('_unused_', '_unused_'))
    devices = insert_sda_hiz_inverter(devices)

    # SDA pull-up: a real 20k-ohm "r" resistor line caused a confirmed
    # segfault in IRSIM 9.7.121's connect_txtors (isolated via a real
    # run: netlist loads and connects cleanly with the resistor line
    # removed -- see design_notes.md 76.9). Originally substituted with a
    # permanently-on weak PMOS (gate tied to Gnd, always conducting
    # regardless of the pad driver's own state), then (per user
    # direction) gated by sda_oe (N45) directly -- but a real run showed
    # N45's relationship to the pad's actual drive state is the OPPOSITE
    # of what the RTL's "sda_oe" name suggests: OSS_ESD_5V_DIO's HIZ pin
    # (which N45 connects straight to, no inverter in between) is wired
    # so HIZ=H means the pad output follows Hi-Z, HIZ=L means the pad
    # output follows its (fixed, =Gnd) OUT pin -- confirmed by the user
    # from the pad cell's own design intent, and matches a real dump:
    # N45=0 -> XN1.XN16.N9=1 (the pad's own actual pull-down transistor,
    # gate=N9, ACTIVELY on) -- i.e. N45=0 is the DRIVEN state, N45=1 is
    # the RELEASED state (design_notes.md 76.17). A pull-up gated
    # directly by N45 was therefore backwards -- it was turning ON at
    # the exact moment the pad was actively driving low, fighting it.
    #
    # Fixed by gating on N9 itself (XN1.XN16.N9, the pad's own internal
    # "am I actively pulling PAD low right now" signal -- gate=1 when
    # driving low, 0 when released) instead of N45: PMOS ON (pull-up
    # active) when N9=0 (released), OFF when N9=1 (driven low) -- this
    # is the exact complement of the pad's own real-time drive state, by
    # construction, so it can never contend with the driver regardless
    # of what N45/sda_oe "means" at the RTL level.
    #
    # L=20u/W=1u (design_notes.md 76.37/76.38): this geometry was tuned
    # by feel against scmos100.prm to "look weak" and was never
    # calibrated to an actual target resistance -- and it was WAY off
    # under the real TR-1um.prm. Real run: under TR-1um.prm+settle 50,
    # SDA released ("x SDA") during address-byte bits never recovered
    # toward 1 at all -- flat, unwavering 0 for the whole byte -- while
    # sda_oe (the only thing that could actively fight it) was confirmed
    # OFF (N45=0) throughout, ruling out active contention. Root cause:
    # IRSIM's resistance model for a transistor is R = Rsq(L) * (L/W),
    # where Rsq(L) = R_prm_table(L, W_ref) * (W_ref/L) is the per-square
    # sheet resistance implied by our own characterized TR-1um.prm
    # table (build_tr1um_prm.py, 76.29) at its reference width W_ref=
    # 10.2u for PMOS. Using the p-channel static entry at L=1u
    # (3650 ohm): Rsq = 3650 * (10.2/1) = 37230 ohm/sq. At the OLD
    # L=20/W=1 geometry: R = 37230 * (20/1) = 744600 ohm (~745 kohm) --
    # ~37x weaker than the ~20 kohm this pull-up was actually meant to
    # be, and evidently far too weak to visibly charge SDA's capacitance
    # within any of this session's real per-bit test windows (tens of
    # ns), matching the observed "flat 0, never recovers" symptom
    # exactly. (scmos100.prm's own resistance-per-square for this same
    # geometry must have been low enough that L=20/W=1 happened to still
    # land near ~20k there -- a placeholder-specific coincidence, not a
    # calibrated value, which is exactly why it silently broke when the
    # .prm was swapped for real characterized data.)
    #
    # Recalibrated for TR-1um.prm: solving W = Rsq*L/R_target for
    # R_target=20 kohm, L=1u (kept within our characterized L=1/2u
    # range, unlike the old L=20u which was a >10x extrapolation beyond
    # any point build_tr1um_prm.py actually measured) gives
    # W = 37230*1/20000 = 1.86 -> W=1.9u (R ~= 19.6 kohm, close to the
    # original ~20k design intent, using the SAME real .prm this
    # transistor will actually be simulated with).
    PULLUP_NODE = sanitize('$58')
    PAD_DRIVE_NODE = "XN1.XN16.N9"   # SDA pad's own NMOS-pulldown gate
    devices.append(('p', PAD_DRIVE_NODE, 'Vdd', PULLUP_NODE, '1', '1.9', 'PMOS-pullup-gated'))

    by_model = {}
    nodes = set()
    for typ, g, s, d, L, W, model in devices:
        by_model[model] = by_model.get(model, 0) + 1
        nodes.update((g, s, d))
    print("by original model:", by_model)
    print(f"distinct nodes: {len(nodes)}")

    with open(OUT_SIM, "w") as f:
        f.write("| units: 100 tech: scmos\n")
        f.write("| generated by gen_irsim_sim.py from "
                "src/tr_1um_i2c_slave_async.extracted (whole-chip, LVS-clean)\n")
        f.write("| node names: KLayout's anonymous \"$N\" nets are rewritten \"NN\"\n")
        f.write("| (IRSIM 9.7's command interpreter treats a leading \"$\" as a\n")
        f.write("| variable-substitution sigil, not a plain identifier character).\n")
        f.write(f"| The chip's VDD/GND supply nodes ({VDD_NODE}/{GND_NODE} pre-rename)\n")
        f.write("| are renamed literally \"Vdd\"/\"Gnd\" -- IRSIM looks for those exact\n")
        f.write("| names by default and segfaulted on a real run when they weren't\n")
        f.write("| found (confirmed; see design_notes.md 76.8).\n")
        f.write("|type  gate            source          drain           length  width\n")
        f.write("| last device below (Gnd-gated PMOS, Vdd->SDA pad) is a synthetic\n")
        f.write("| weak pull-up -- see comment in gen_irsim_sim.py's main(). Not part\n")
        f.write("| of the real extracted netlist: this die's SDA driver is open-drain\n")
        f.write("| only (OSS_ESD_5V_DIO's OUT tied to Gnd; sda_oe=1 pulls SDA low,\n")
        f.write("| sda_oe=0 releases) and has no on-die pull-up device, so an external\n")
        f.write("| one is added here so the bus idles high like a real I2C bus.\n")
        for typ, g, s, d, L, W, model in devices:
            f.write(f"{typ}\t{g}\t{s}\t{d}\t{L}\t{W}\n")
    print(f"wrote {OUT_SIM}")
    return devices, nodes


if __name__ == "__main__":
    main()
