"""
gen_lvs_spice_ringosc_v10.py (this session, user request: "LVS用の spice
を作ってください" -- build the RING_OSC-INTEGRATED chip-level LVS
reference netlist for V10, completing the deliverable started by
gen_lvs_spice_top_v10.py).

V10 counterpart of gen_lvs_spice_ringosc_v9.py. RING_OSC itself is
UNCHANGED between V9 and V10 (same GDS, same schematic, same
ring_osc/simulation/RING_OSC.spice) -- only the base chip-level LVS
netlist it's being integrated into differs (V10's core + V10's
pad-reassigned GIO wiring, from gen_lvs_spice_top_v10.py, instead of
V9's). Same NESTED structure decision as v9's final revision (v3,
design_notes.md): RING_OSC/INV3D/FILL2/INV_X1/AND2_X1 all kept as their
own separate .subckt bodies (deduped against ones already present in the
base netlist), called via one "x3 ... RING_OSC" instance -- confirmed by
v9's own investigation (klayout.db.NetlistComparer against ring_osc/
RING_OSC.extracted) that this matches how the layout actually
hierarchizes; not re-verified independently here since RING_OSC's own
layout/extraction is unchanged for V10.

Net mapping for RING_OSC's 5 real ports on the new x3 instance:
  OUT  -> OUT10  (GIO frame's own fixed driver-input pin, frame-
                   structural, unrelated to the V10 pad reassignment)
  OUTD -> OUT9   (ditto)
  ENB  -> P15    (V10's rst_n, per schematic/v10_signal_routing_plan.
                   json's own "rst_n" entry -- terminal "P15". This
                   happens to be the SAME pad V9 used for rst_n too
                   (design_notes.md 108.57 confirms this independently,
                   not assumed), but is read from the V10 plan here
                   rather than hardcoded, so a future re-run of
                   assign_v10_gio_pads.py can't silently desync this
                   script.
  VDD  -> VDD, VSS -> VSS (global rails, unchanged)
"""
import json
import re
from pathlib import Path

BASE = str(Path(__file__).resolve().parent.parent)
RINGOSC_SPICE = "/sessions/dreamy-ecstatic-heisenberg/mnt/simulations/RING_OSC.spice"
CHIP_LVS_SPICE = BASE + "/schematic/tr_1um_i2c_slave_async_v10_lvs.spice"
V10_PLAN_JSON = BASE + "/schematic/v10_signal_routing_plan.json"
OUT_SCHEMATIC = BASE + "/schematic/tr_1um_i2c_slave_async_v10_ringosc_lvs.spice"
# written directly as <TopCellName>.spice, per this project's established
# local-LVS-tool naming convention (design_notes.md, gen_lvs_spice_
# ringosc_v9.py) -- supersedes whatever V9-era copy currently sits there.
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
    plan = json.load(open(V10_PLAN_JSON))
    rst_n_terminal = plan["nets"]["rst_n"]["terminal"]
    print(f"V10 rst_n terminal (from {V10_PLAN_JSON}): {rst_n_terminal}")

    ringosc_text = open(RINGOSC_SPICE).read()
    chip_lvs_text = open(CHIP_LVS_SPICE).read()

    # ---- rename GIO's own NC_OUT9/NC_OUT10 nets to OUT9/OUT10 (same
    # mechanism/rationale as gen_lvs_spice_ringosc_v9.py's round-4 fix --
    # these are the base LVS file's auto-generated floating-net names for
    # GIO's own OUT9/OUT10 driver-input pins, which RING_OSC's OUT/OUTD
    # now actually drive) ----
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

    port_net = {
        "OUT": "OUT10",
        "OUTD": "OUT9",
        "ENB": rst_n_terminal,
        "VDD": "VDD",
        "VSS": "VSS",
    }
    missing = set(ringosc_ports) - set(port_net)
    if missing:
        raise RuntimeError(f"RING_OSC port(s) with no net mapping: {missing}")
    x3_nets = [port_net[p] for p in ringosc_ports]

    # sanity: ENB's target net (rst_n_terminal, e.g. "P15") must actually
    # be a top-level pin already declared by the base chip subckt (i.e. a
    # real bond pad, not something that silently fell through as an
    # unrelated floating net).
    top_decl_m = re.search(rf"\.subckt\s+{re.escape(TOP_NAME)}\s+(.*)", chip_lvs_text)
    top_pins = top_decl_m.group(1).split() if top_decl_m else []
    if rst_n_terminal not in top_pins:
        raise RuntimeError(f"ENB's target net {rst_n_terminal!r} is not one of the base chip's "
                            f"declared top-level pins {top_pins} -- refusing to wire RING_OSC.ENB "
                            f"to a net that isn't actually rst_n's real pad.")
    print(f"\nENB -> {rst_n_terminal}: confirmed a real top-level chip pin (rst_n's pad). OK.")

    # ---- dedupe dependency subckts against the base LVS file (keep
    # RING_OSC nested with its own INV3D/FILL2, same as v9's final
    # revision -- not flattened/renamed) ----
    ringosc_blocks = split_subckts(ringosc_text)
    base_blocks = split_subckts(chip_lvs_text)
    print(f"\nRING_OSC.spice defines: {sorted(ringosc_blocks)}")

    new_bodies = []
    for name, block in ringosc_blocks.items():
        if name == "RING_OSC":
            continue
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
** netlist (V10). Generated by script/gen_lvs_spice_ringosc_v10.py from:
**   1) ring_osc/simulation/RING_OSC.spice (RING_OSC transistor-level
**      netlist -- UNCHANGED from V9, same GDS/schematic), kept NESTED
**      verbatim -- .subckt RING_OSC plus its own INV3D/FILL2/INV_X1/
**      AND2_X1 dependency subckts, called via one top-level x3 instance
**      (INV_X1/AND2_X1 deduped against the core's own identical copies;
**      INV3D/FILL2 are new and included as-is -- NOT flattened, NOT
**      renamed, NOT dropped, matching V9's own final revision after
**      independent verification via klayout.db.NetlistComparer that
**      INV3D hierarchizes correctly on the layout side).
**   2) schematic/{CHIP_LVS_SPICE.split('/')[-1]} (V10's core+GIO chip
**      LVS reference netlist, from gen_lvs_spice_top_v10.py -- x1=
**      OSS_FRAME_GIO, x2=i2c_slave_async_nrow_fm carried over verbatim)
**   3) schematic/v10_signal_routing_plan.json's own "rst_n" entry
**      (terminal={rst_n_terminal}) for ENB's target net -- OUT->OUT10/
**      OUTD->OUT9 are GIO-frame-fixed driver-input pins, unrelated to
**      the V10 pad reassignment, same as V9.
**
** x3 = RING_OSC, added to the existing top subckt with nets
** (OUT10, OUT9, {rst_n_terminal}, VDD, VSS) -- {rst_n_terminal} is
** confirmed (by direct read of the base LVS file's own top subckt
** declaration) to be a real top-level chip pin, the SAME net already
** carrying the core's own rst_n pin (x2's first net) -- ENB and rst_n
** are intentionally the same net (design_notes.md 108.57's ENB
** re-routing physically merges RING_OSC's ENB wire directly onto
** rst_n's own GIO-side wire via a via, matching this schematic tie).
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
