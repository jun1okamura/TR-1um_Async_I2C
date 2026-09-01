"""
gen_irsim_sim_v9.py

Recursively flattens the whole-chip LVS-reference SPICE netlist
(schematic/tr_1um_i2c_slave_async_v9_lvs.spice -- the SAME file used for
the now chip-level-DRC/LVS-clean v9 verification, design_notes.md
82-86) into a flat IRSIM .sim file (classic "p/n gate source drain
length width" format), covering every transistor in the design: the
digital core (i2c_slave_async_nrow_fm), the whole GIO pad ring
(OSS_FRAME_GIO), and all 16 OSS_ESD_5V_DIO/VDD/VSS pad cells.

This supersedes gen_irsim_sim.py, which read the OLD KLayout-extraction
source (src/tr_1um_i2c_slave_async.extracted). Per user direction
(design_notes.md 87, "IRSIMでの再検証に入ります。LVSで使った.spice から
IRSIM用のファイルを準備してください。"), IRSIM re-verification now
starts from the schematic-side LVS reference spice instead, which is:
  - already the exact deck proven chip-level LVS clean against the v9
    GDS (so IRSIM behavior traces back to the SAME verified topology,
    not a separate KLayout extraction pass that could itself drift),
  - structurally much cleaner: EVERY net has a real, meaningful name
    (top-level pins are literally "P1".."P15"/"VDD"/"VSS" since
    design_notes 82's TOP_PIN_ORDER fix; internal nets are the
    synthesis tool's own names, e.g. "bit_cnt[0]", "_065_") -- there
    are ZERO KLayout-style anonymous "$N" nets anywhere in this file,
    so the old sanitize()/VDD-GND "detective work" (76.3) is no longer
    needed: this file's own top subckt already has literal "VDD"/"VSS"
    ports.

Syntax differences from the old .extracted source (both confirmed by
direct inspection this session):
  - MOSFETs are "M<suffix> drain gate source bulk model params..." (any
    suffix, e.g. "MXM1", "MM2", "M_FILL2_1_p") instead of "XM$<n>".
  - Subcircuit instances are "x<name> net1 net2 ... netN CELLTYPE"
    (lowercase x, arbitrary net count) instead of "X$<n>".
  - ESD clamp diodes are "D<name> ..." (e.g. "DD1") instead of "D$<n>".
  - L=/W= parameters are lowercase ("l=2u w=150u") instead of upper.
  - ".subckt"/".ends" are lowercase, and ".ends" does NOT repeat the
    subckt name (unlike the old ".ENDS <name>").
"""
import re

SPICE = "../schematic/tr_1um_i2c_slave_async_ringosc_v9_lvs.spice"
OUT_SIM = "../irsim/tr_1um_i2c_slave_async.sim"
TOP = "tr_1um_i2c_slave_async"

MODEL_MAP = {'PMOS': 'p', 'NMOS': 'n', 'NMOSE': 'n'}


def sanitize(name):
    # kept as a no-op safety net -- this source has zero "$"-prefixed
    # nets (confirmed via grep), unlike the old .extracted source, but
    # IRSIM's command interpreter would still choke on one if it ever
    # showed up (see gen_irsim_sim.py's identical comment / a real
    # confirmed run for the original motivation).
    return name.replace('$', 'N')


def parse_spice(path):
    raw = open(path).read()
    # merge SPICE '+' continuation lines (pin lists AND multi-line
    # instance-call lines both use this) into their preceding line
    # BEFORE any further parsing, so every logical statement is one
    # line. Comment continuation lines use "*+" (not "+"), so they are
    # correctly left alone here and simply skipped as comments below.
    merged = []
    for line in raw.split("\n"):
        if line.startswith('+') and merged:
            merged[-1] += ' ' + line[1:]
        else:
            merged.append(line)

    blocks = {}
    cur_name = None
    cur_pins = None
    cur_body = []
    for line in merged:
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith('.subckt'):
            toks = s.split()
            cur_name = toks[1]
            cur_pins = toks[2:]
            cur_body = []
        elif low.startswith('.ends'):
            if cur_name is not None:
                if cur_name not in blocks:
                    blocks[cur_name] = (cur_pins, cur_body)
                cur_name = None
        elif cur_name is not None:
            cur_body.append(s)
        # lines outside any .subckt/.ends (top-of-file comments, blank
        # separators) are simply ignored.
    return blocks


def parse_lw(toks):
    L = W = None
    for t in toks:
        tl = t.lower()
        if tl.startswith('l='):
            L = t[2:].rstrip('uU')
        elif tl.startswith('w='):
            W = t[2:].rstrip('uU')
    return L, W


def flatten(blocks, top_name):
    devices = []  # (type, gate, source, drain, L, W, orig_model)
    stats = {'insts': 0, 'devs': 0, 'maxdepth': 0, 'diodes_skipped': 0}

    def resolve(local, node_map, path):
        if local in node_map:
            return node_map[local]
        return sanitize(f"{path}{local}")

    def walk(cellname, node_map, path, depth):
        stats['maxdepth'] = max(stats['maxdepth'], depth)
        pins, body = blocks[cellname]
        for line in body:
            if not line or line.startswith('*'):
                continue
            first = line[0]
            if first in ('D', 'd'):
                # ESD protection clamp diode (VSS<->internal pad node,
                # model "DN"). Reverse-biased / non-conducting during
                # normal digital operation. IRSIM's .sim format has no
                # diode primitive anyway, so skip it (same reasoning as
                # gen_irsim_sim.py's identical skip).
                stats['diodes_skipped'] += 1
                continue
            if first in ('M', 'm'):
                toks = line.split()
                d, g, s, b = toks[1], toks[2], toks[3], toks[4]
                model = toks[5]
                L, W = parse_lw(toks[6:])
                # NOTE: an "m=" multiplier parameter (device parallel
                # count, e.g. DEL1's "MM2 ... PMOS w=10.2u l=1u m=2")
                # is deliberately NOT folded into W here -- matches
                # gen_irsim_sim.py's identical simplification, which
                # this same source (via the .extracted derivative) was
                # already validated against in a prior full write-
                # transaction IRSIM run. Not re-litigated this session.
                typ = MODEL_MAP.get(model.upper())
                if typ is None:
                    raise ValueError(f"unknown model {model} in {cellname}: {line}")
                devices.append((typ, resolve(g, node_map, path), resolve(s, node_map, path),
                                 resolve(d, node_map, path), L, W, model))
                stats['devs'] += 1
            elif first in ('X', 'x'):
                toks = line.split()
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
    top_map = {p: sanitize(p) for p in top_pins}  # top ports keep their bare names (VDD -> VDD, P13 -> P13, ...)
    walk(top_name, top_map, "", 0)
    return devices, stats


# whole-chip VDD/GND supply nodes: TRIVIAL to identify in this source,
# unlike the old .extracted file's anonymous "$1" (76.3's "detective
# work") -- the top subckt's own formal pin list (line 752 of the
# source) already has literal "VDD" and "VSS" ports (a direct result of
# design_notes.md 82's TOP_PIN_ORDER fix), and standard SPICE port
# resolution propagates those bare names down through the whole
# hierarchy with no aliasing.
VDD_NODE = sanitize("VDD")
GND_NODE = sanitize("VSS")


def rename_rails(devices, vdd_name="Vdd", gnd_name="Gnd"):
    # IRSIM looks for nodes literally named "Vdd"/"Gnd" for the
    # power/ground rails (confirmed on a real run with the old .sim;
    # see gen_irsim_sim.py's identical comment / design_notes.md 76.8).
    ren = {VDD_NODE: vdd_name, GND_NODE: gnd_name}
    return [(typ, ren.get(g, g), ren.get(s, s), ren.get(d, d), L, W, model)
            for typ, g, s, d, L, W, model in devices]


def substitute_bufth_with_buf_x1(blocks):
    # BUFTH's regenerative Schmitt-trigger feedback is a confirmed,
    # permanent limitation of IRSIM's ternary switch-level solver (not
    # a cold-start-only issue) -- design_notes.md 76.12/76.14/76.15.
    # Per explicit user direction, BUFTH is substituted with BUF_X1 for
    # chip-level IRSIM purposes. Both subckts have the IDENTICAL pin
    # list in this source too ("VDD A Y GND" -- confirmed directly,
    # lines 542/555 of the v9 lvs spice), so this remains a pure
    # drop-in replacement.
    assert "BUFTH" in blocks and "BUF_X1" in blocks
    assert blocks["BUFTH"][0] == blocks["BUF_X1"][0], (
        f"BUFTH/BUF_X1 pin lists differ: {blocks['BUFTH'][0]} vs {blocks['BUF_X1'][0]}")
    blocks["BUFTH"] = blocks["BUF_X1"]


# NOTE: gen_irsim_sim.py's insert_sda_hiz_inverter() (76.17/76.18) is
# DELIBERATELY NOT ported here. That fix compensated for sda_oe being
# wired with backwards polarity directly into HIZ13 at the RTL/gate
# level in the OLD (v7-era) design. Per README.md/design_notes.md, this
# polarity bug was fixed at the RTL source itself for V8+ (the register
# now drives the correct sense directly), and this v9 source's own
# chip-level LVS is clean against a schematic that already reflects
# that corrected RTL -- so inserting a synthetic compensating inverter
# here would reintroduce the bug's mirror image. If a real IRSIM run
# shows SDA drive polarity is wrong again, that would mean the RTL fix
# regressed, not that this generator needs the old inverter hack back.


def find_pad_pullup_gate_node(devices, pad_net="P2"):
    # Structural (not path-hardcoded) lookup of the SDA pad's own
    # actively-driving-low NMOS gate, so this doesn't silently break if
    # instance numbering shifts. Inside OSS_ESD_5V_DIO (source lines
    # 63-87), "MXM2 PAD NG VSS VSS NMOSE w=150u l=2u" is unambiguously
    # the pad's big pulldown driver (PAD=drain, gate="NG"): it is the
    # only NMOSE w=150/l=2 device in the whole design, and among the
    # 16 OSS_ESD_5V_DIO instances only the one wired to top-level net
    # "P2" (the SDA pad, per gio_connections.json's pad_reassignment_
    # 2026_08_31 -- SDA moved from the old P13 to P2 this session) is
    # the one we want. (MXM6, "NMOSE w=350u l=2u" with gate tied
    # straight to VSS, is a separate always-off ESD device on the same
    # PAD net -- excluded by the W match.)
    candidates = [g for (typ, g, s, d, L, W, model) in devices
                  if model.upper() == 'NMOSE' and L == '2' and W == '150'
                  and (d == pad_net or s == pad_net)]
    assert len(candidates) == 1, (
        f"expected exactly 1 pad-driver NMOSE(l=2,w=150) touching net {pad_net}, "
        f"found {len(candidates)}: {candidates}")
    return candidates[0]


def main():
    blocks = parse_spice(SPICE)
    print(f"parsed {len(blocks)} .subckt blocks from {SPICE}")
    substitute_bufth_with_buf_x1(blocks)

    devices, stats = flatten(blocks, TOP)
    print(f"flattened: {stats['insts']} instances walked, {stats['devs']} transistors, "
          f"{stats['diodes_skipped']} ESD diodes skipped, max hierarchy depth {stats['maxdepth']}")

    # find the SDA pad's own drive-gate BEFORE renaming rails (P13 is
    # untouched by rename_rails either way, but the gate node found
    # here is neither VDD_NODE nor GND_NODE, so order doesn't matter --
    # done pre-rename simply to keep this next to the raw flatten()
    # output it inspects).
    pad_drive_node = find_pad_pullup_gate_node(devices, pad_net="P2")
    print(f"SDA pad drive-gate node (structurally found): {pad_drive_node}")

    devices = rename_rails(devices)

    # SDA weak pull-up: this die's SDA driver is open-drain only (no
    # on-die pull-up), so IRSIM needs an external one for the bus to
    # idle high, same reasoning as gen_irsim_sim.py. Sizing reused
    # as-is (technology/device-physics based, independent of which
    # netlist source this is generated from): L=1u/W=1.9u against the
    # real characterized TR-1um.prm gives ~19.6 kohm (design_notes.md
    # 76.29-76.38), close to the original ~20k design intent.
    #
    # PMOS ON (pull-up active) when pad_drive_node=0 (pad released),
    # OFF when pad_drive_node=1 (pad actively driving low) -- gating on
    # the pad's own real-time drive-gate node, by construction, so it
    # can never contend with the driver regardless of sda_oe's RTL-
    # level polarity.
    PULLUP_NODE = "P2"  # already a clean top-level net name in this source -- no aliasing needed
    devices.append(('p', pad_drive_node, 'Vdd', PULLUP_NODE, '1', '1.9', 'PMOS-pullup-gated'))

    by_model = {}
    nodes = set()
    for typ, g, s, d, L, W, model in devices:
        by_model[model] = by_model.get(model, 0) + 1
        nodes.update((g, s, d))
    print("by original model:", by_model)
    print(f"distinct nodes: {len(nodes)}")
    assert "Vdd" in nodes and "Gnd" in nodes, "rail rename did not take effect"

    with open(OUT_SIM, "w") as f:
        f.write("| units: 100 tech: scmos\n")
        f.write("| generated by gen_irsim_sim_v9.py from\n")
        f.write("| schematic/tr_1um_i2c_slave_async_ringosc_v9_lvs.spice (whole-chip,\n")
        f.write("| RING_OSC-integrated, pad-reassignment-2026 chip-level DRC/LVS-\n")
        f.write("| clean reference -- confirmed clean by the user this session).\n")
        f.write("| This source has NO anonymous KLayout-style \"$N\" nets: every\n")
        f.write("| node is a real port name (P1..P15/VDD/VSS) or a real synthesis\n")
        f.write("| net name (e.g. bit_cnt[0], _065_).\n")
        f.write(f"| VDD/GND supply nodes ({VDD_NODE}/{GND_NODE} pre-rename) are\n")
        f.write("| renamed literally \"Vdd\"/\"Gnd\" -- IRSIM looks for those exact\n")
        f.write("| names by default (design_notes.md 76.8).\n")
        f.write("| BUFTH (scl/sda_in Schmitt-trigger input buffer) is substituted\n")
        f.write("| with BUF_X1 (plain 2-stage inverter, identical pin list) --\n")
        f.write("| BUFTH's regenerative feedback is unresolvable by IRSIM's ternary\n")
        f.write("| switch-level solver on every transition, not just cold start\n")
        f.write("| (design_notes.md 76.12-76.15).\n")
        f.write("| The old gen_irsim_sim.py's insert_sda_hiz_inverter() compensating\n")
        f.write("| fix is deliberately NOT applied here: it worked around a v7-era\n")
        f.write("| sda_oe/HIZ13 RTL polarity bug that was fixed at the RTL source for\n")
        f.write("| V8+ (see README.md); this source's schematic already reflects\n")
        f.write("| that corrected RTL.\n")
        f.write("|type  gate            source          drain           length  width\n")
        f.write("| last device below (Vdd-side PMOS gated by the SDA pad's own real\n")
        f.write("| drive-gate node) is a synthetic weak pull-up, not part of the real\n")
        f.write("| netlist -- see comment in gen_irsim_sim_v9.py's main().\n")
        for typ, g, s, d, L, W, model in devices:
            f.write(f"{typ}\t{g}\t{s}\t{d}\t{L}\t{W}\n")
    print(f"wrote {OUT_SIM}")
    return devices, nodes


if __name__ == "__main__":
    main()
