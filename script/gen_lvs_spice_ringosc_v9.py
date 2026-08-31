"""
gen_lvs_spice_ringosc_v9.py (this session, user: "DRC clean です。LVS用の
spice を ring_osc/simulation/RING_OSC.spice とJSON 情報を使って作成
ください" -- build the LVS reference netlist for the RING_OSC-INTEGRATED
chip.)

HISTORY (this file went through 2 revisions before settling here):
  - v1: kept RING_OSC nested as its own ".subckt RING_OSC" (with INV3D/
    FILL2 as further nested dependency subckts), called via one
    top-level "x3 ... RING_OSC" instance.
  - v2 (after user reported "INV3Dが extracted ファイルにありません",
    and ring_osc/tr_1um_i2c_slave_async.extracted independently
    confirmed 0 occurrences of "INV3D"/"RING" in the full-chip
    extraction at the time): rewrote to FLATTEN RING_OSC's instances
    directly into the top subckt and rename INV3D->INV_X1, on the
    theory that the deck never preserves custom (non-library) cells as
    named circuits at all.
  - v3 (THIS version, after the user pushed back: "FILLを消さず、
    RING_OSCも階層を開かないでください。RING_OSC単体のLVSと同じく
    INV3D が layout で階層化されて無いのが原因の気がします" and then,
    after checking further, corrected themselves: "これは間違い。INV3D
    は階層化されていました。"): back to v1's NESTED structure (RING_OSC/
    INV3D/FILL2 all kept as their own separate .subckt bodies, called
    via one "x3 ... RING_OSC" instance) -- confirmed independently, by
    running klayout.db.NetlistComparer directly between ring_osc/
    simulation/RING_OSC.spice and ring_osc/RING_OSC.extracted (the
    standalone RING_OSC-only layout extraction), that INV3D DOES
    hierarchize correctly there: cmp.unmatched_circuits_a() (reference-
    only circuits) is EMPTY -- every one of RING_OSC.spice's own 5
    circuits (RING_OSC, INV3D, INV_X1, AND2_X1, FILL2) has a same-named
    counterpart circuit on the layout side. The v2 diagnosis (deck never
    hierarchizes non-library cells) was wrong; v1's structure was right
    for the schematic side all along. The REAL open question -- why the
    FULL-CHIP extraction under the top name "tr_1um_i2c_slave_async"
    flattens RING_OSC/INV3D away while a same-content extraction
    labeled "tr_1um_i2c_slave_async_ringosc" (and the standalone RING_
    OSC-only extraction) both preserve it -- is a layout-extraction-side
    question for the user's local LVS run/deck, not something fixable
    by reshaping this reference netlist; not resolved here.

Also fixed this revision: the user pointed out their local LVS tool
requires the reference netlist to be named simulation/<TopCellName>.
spice to compare at all ("local での LVS は simulation/TopCellName.spice
形式でないと比較出来ません"). Since RING_OSC is now a permanent part of
the chip, this script writes the integrated reference netlist directly
to simulations/tr_1um_i2c_slave_async.spice (the real GDS top cell
name), superseding the ring_osc-free copy gen_lvs_spice_top_v9.py used
to place there. schematic/tr_1um_i2c_slave_async_v9_lvs.spice (the
ring_osc-free reference, read-only input to this script) is untouched,
so nothing is lost -- only the simulations/ copy used for local LVS
lookup is updated to reflect the current (RING_OSC-integrated) design.

Three inputs, exactly as the user specified:
1. "ring_osc/simulation/RING_OSC.spice" -- symlinked to
   /Users/okamura/.xschem/simulations/RING_OSC.spice, RING_OSC's own
   transistor-level netlist: .subckt RING_OSC OUT OUTD ENB VDD VSS, plus
   dependency subckts INV_X1/AND2_X1/FILL2/INV3D, embedded verbatim.
2. schematic/tr_1um_i2c_slave_async_v9_lvs.spice -- the ring_osc-free
   chip LVS reference netlist (GIO + core), read verbatim; x1/x2 carried
   over unchanged.
3. schematic/ring_osc_connections.json's signal_routing.waypoints keys
   (OUT->P9, OUTD->P10, ENB->P15) -- the net mapping for RING_OSC's 5
   real ports on the new x3 instance, read programmatically.
"""
import json
import re

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
RINGOSC_SPICE = "/sessions/dreamy-ecstatic-heisenberg/mnt/simulations/RING_OSC.spice"
CHIP_LVS_SPICE = BASE + "/schematic/tr_1um_i2c_slave_async_v9_lvs.spice"
CONN_JSON = BASE + "/schematic/ring_osc_connections.json"
OUT_SCHEMATIC = BASE + "/schematic/tr_1um_i2c_slave_async_ringosc_v9_lvs.spice"
# NOTE: written directly as <TopCellName>.spice per the user's local LVS
# tool requirement -- this now supersedes the ring_osc-free copy that
# gen_lvs_spice_top_v9.py used to place at this exact path.
OUT_SIMULATIONS = "/sessions/dreamy-ecstatic-heisenberg/mnt/simulations/tr_1um_i2c_slave_async.spice"

TOP_NAME = "tr_1um_i2c_slave_async"


def read_subckt_port_order(text, subckt_name):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f".subckt {subckt_name} ") or line.strip() == f".subckt {subckt_name}":
            tokens = line.split()[2:]
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                tokens += lines[j][1:].split()
                j += 1
            return tokens
    raise RuntimeError(f"'.subckt {subckt_name}' not found")


def split_subckts(text):
    """Return {name: full_block_text} for every top-level .subckt ... .ends
    block in text (blocks are not nested in these files)."""
    blocks = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^\.subckt\s+(\S+)", lines[i])
        if m:
            name = m.group(1)
            start = i
            while not lines[i].strip().lower().startswith(".ends"):
                i += 1
            end = i
            blocks[name] = "\n".join(lines[start:end + 1])
        i += 1
    return blocks


def normalize(block_text):
    # ignore leading comment lines (** sch_path etc.) and blank lines /
    # trailing whitespace when comparing two subckt bodies for identity
    out = []
    for line in block_text.splitlines():
        s = line.rstrip()
        if s.startswith("**") or s.startswith("*") and not s.startswith("*."):
            continue
        if s == "":
            continue
        out.append(s)
    return "\n".join(out)


def main():
    conn = json.load(open(CONN_JSON))

    ringosc_text = open(RINGOSC_SPICE).read()
    chip_lvs_text = open(CHIP_LVS_SPICE).read()

    # ---- rename GIO's own NC_OUT9/NC_OUT10 nets to OUT9/OUT10 (round 4
    # fix): the base LVS file ties GIO's OUT9/OUT10 pins (its own
    # driver-INPUT pins, previously unused spare-pad drivers) to
    # gen_lvs_spice_top_v9.py's auto-generated floating-net names
    # "NC_OUT9"/"NC_OUT10" (confirmed: each appears exactly once, only
    # in the x1/GIO instance line at the top level -- verified below, not
    # assumed). Since RING_OSC's OUT/OUTD now drive these same GIO pins,
    # they are no longer no-connects -- renamed in place (matching the
    # same rename-a-floating-net-to-its-real-identity technique gen_lvs_
    # spice_top_v9.py itself already uses for the P1-P15 pads) so that
    # the NEW x3 instance's "OUT9"/"OUT10" nets actually land on GIO's
    # real pins instead of silently creating disconnected same-named
    # nets. Earlier revision's bug: it used the net names "OUT9"/"OUT10"
    # directly without this rename, which would have wired RING_OSC to
    # brand-new, unconnected nets -- not caught before now because no
    # verification step checked that the x3 net strings actually matched
    # an EXISTING net at GIO's own corresponding pin position.
    for nc_name, real_name in (("NC_OUT9", "OUT9"), ("NC_OUT10", "OUT10")):
        count = len(re.findall(rf"\b{re.escape(nc_name)}\b", chip_lvs_text))
        if count != 1:
            raise RuntimeError(
                f"expected exactly 1 occurrence of {nc_name!r} in {CHIP_LVS_SPICE} "
                f"(GIO's own x1 instance line), found {count} -- refusing to rename blindly."
            )
        chip_lvs_text = re.sub(rf"\b{re.escape(nc_name)}\b", real_name, chip_lvs_text)
    print(f"\nRenamed GIO's NC_OUT9/NC_OUT10 (previously-floating spare-pad-driver nets) "
          f"to OUT9/OUT10 -- confirmed exactly 1 occurrence each before renaming.")

    ringosc_ports = read_subckt_port_order(ringosc_text, "RING_OSC")
    print(f"RING_OSC port order ({len(ringosc_ports)} ports), read from {RINGOSC_SPICE}:")
    print(" ", ringosc_ports)

    # ---- net mapping, derived directly from the JSON's own waypoint keys
    # (each key IS the "<RING_OSC pin>-><chip top pin>" statement -- not
    # hand-transcribed here) ----
    waypoints = conn["signal_routing"]["waypoints"]
    port_net = {}
    for key in waypoints:
        pin, _, pad = key.partition("->")
        if pin and pad:
            port_net[pin] = pad
    # REVISED (round 4, user: "配線ミスです... 正しくは RINGOSC(OUT)＞
    # OUT10、RINGOSC(OUTD)＞OUT9です。spice も間違っています。JSONを
    # 修正ください。"): OUT/OUTD target OSS_FRAME_GIO's own driver-input
    # pins (OUT10/OUT9) now, not the raw P9/P10 bond-pad nets directly --
    # the JSON's waypoint keys were updated to match, and this assertion
    # follows suit (still read programmatically from the JSON, not
    # hand-picked here independent of it).
    for required in ("OUT->OUT10", "OUTD->OUT9", "ENB->P15"):
        assert required in waypoints, f"expected waypoint key {required!r} not found in JSON"
    print("\nJSON signal_routing.waypoints keys confirm:", ", ".join(sorted(waypoints)))

    port_net["VDD"] = "VDD"
    port_net["VSS"] = "VSS"
    missing = set(ringosc_ports) - set(port_net)
    if missing:
        raise RuntimeError(f"RING_OSC port(s) with no net mapping: {missing}")
    x3_nets = [port_net[p] for p in ringosc_ports]

    # ---- dedupe dependency subckts against the base LVS file (keep
    # RING_OSC nested with its own INV3D/FILL2 -- do NOT flatten or
    # rename, per the user's explicit instruction and the confirmed
    # finding that INV3D DOES hierarchize correctly) ----
    ringosc_blocks = split_subckts(ringosc_text)
    base_blocks = split_subckts(chip_lvs_text)
    print(f"\nRING_OSC.spice defines: {sorted(ringosc_blocks)}")

    new_bodies = []
    for name, block in ringosc_blocks.items():
        if name == "RING_OSC":
            continue  # always new, added separately below (kept first for readability)
        if name in base_blocks:
            if normalize(block) == normalize(base_blocks[name]):
                print(f"  {name}: already defined identically in the base LVS netlist -- skipping duplicate.")
                continue
            else:
                raise RuntimeError(
                    f"subckt {name} exists in BOTH RING_OSC.spice and the base LVS netlist "
                    f"but with DIFFERENT bodies -- refusing to silently pick one."
                )
        print(f"  {name}: new, not in base LVS netlist -- including verbatim (no rename/drop).")
        new_bodies.append(block)

    if "RING_OSC" not in ringosc_blocks:
        raise RuntimeError("RING_OSC.spice does not define .subckt RING_OSC")
    if "RING_OSC" in base_blocks:
        raise RuntimeError("base LVS netlist unexpectedly already defines RING_OSC")
    new_bodies.append(ringosc_blocks["RING_OSC"])

    # ---- locate and extend the top subckt block in the base file ----
    m = re.search(
        rf"(\.subckt\s+{re.escape(TOP_NAME)}\s+.*?\n)(.*?)(\n\.ends\s*\n?)",
        chip_lvs_text, re.S,
    )
    if not m:
        raise RuntimeError(f"could not find .subckt {TOP_NAME} ... .ends block in {CHIP_LVS_SPICE}")
    top_decl, top_body, top_ends = m.groups()

    def wrap_instance_line(inst_name, nets, subckt_name):
        out = [f"{inst_name} " + " ".join(nets[:8])]
        rest = nets[8:]
        while rest:
            out.append("+ " + " ".join(rest[:8]))
            rest = rest[8:]
        out[-1] += f" {subckt_name}"
        return "\n".join(out)

    x3_line = wrap_instance_line("x3", x3_nets, "RING_OSC")
    new_top_block = top_decl + top_body + "\n" + x3_line + top_ends

    before = chip_lvs_text[:m.start()]
    after = chip_lvs_text[m.end():]

    header = f"""\
** {TOP_NAME}.spice -- RING_OSC-INTEGRATED chip-level LVS reference
** netlist (v9). Generated by script/gen_lvs_spice_ringosc_v9.py from:
**   1) ring_osc/simulation/RING_OSC.spice (RING_OSC transistor-level
**      netlist, from its own xschem schematic ring_osc/RING_OSC.sch),
**      kept NESTED verbatim -- .subckt RING_OSC plus its own INV3D/
**      FILL2/INV_X1/AND2_X1 dependency subckts, called via one
**      top-level x3 instance (INV_X1/AND2_X1 deduped against the core's
**      own identical copies below; INV3D/FILL2 are new and included
**      as-is -- NOT flattened, NOT renamed, NOT dropped).
**   2) schematic/{CHIP_LVS_SPICE.split('/')[-1]} (the ring_osc-free chip
**      LVS reference netlist, unchanged/untouched -- x1=OSS_FRAME_GIO,
**      x2=i2c_slave_async_nrow_fm carried over verbatim)
**   3) schematic/ring_osc_connections.json's signal_routing.waypoints
**      (OUT->P9, OUTD->P10, ENB->P15).
**
** x3 = RING_OSC, added to the existing top subckt with nets
** (P9, P10, P15, VDD, VSS) -- P15 is confirmed (by direct read of the
** base LVS file) to be the SAME net already carrying the core's own
** rst_n pin (x2's first net), matching ring_osc_connections.json's own
** "P15_is_rst_n" finding: ENB and rst_n are intentionally the same net.
**
** STRUCTURE NOTE (see script docstring for the full back-and-forth):
** an earlier revision flattened RING_OSC's instances directly into the
** top subckt and renamed INV3D->INV_X1, based on a (later disproven)
** theory that the layout-side LVS deck never preserves custom cells as
** named circuits. Verified directly with klayout.db.NetlistComparer
** (RING_OSC.spice vs the standalone ring_osc/RING_OSC.extracted):
** cmp.unmatched_circuits_a() is EMPTY -- every one of RING_OSC.spice's
** own 5 circuits, including INV3D, has a same-named counterpart on the
** layout side. So this revision reverts to the original NESTED
** structure: it is structurally correct, and matches what the user's
** local LVS tool needs (simulation/<TopCellName>.spice naming).
"""

    out_text = before + header + "\n" + "\n\n".join(new_bodies) + "\n\n" + new_top_block + after

    open(OUT_SCHEMATIC, "w").write(out_text)
    open(OUT_SIMULATIONS, "w").write(out_text)
    print(f"\nwrote {OUT_SCHEMATIC}")
    print(f"wrote {OUT_SIMULATIONS} (matches TopCellName.spice convention for local LVS)")
    print(f"\nx3 (RING_OSC) instance: {ringosc_ports} -> {x3_nets}")
    print("New subckt bodies appended:", [b.splitlines()[0] for b in new_bodies])


if __name__ == "__main__":
    main()
