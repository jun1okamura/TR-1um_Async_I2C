"""
gen_lvs_spice_top_v9.py (this session, user request: "LVS用の spice
ファイルをコアの LVS クリーンの spice とGIOのschematic、JSON情報を
使って作成ください" -- build the CHIP-LEVEL (core + GIO frame) LVS
reference netlist, now that v9's core-only LVS is clean (design_notes.md
77.47) and the chip-level physical routing (route_gio_core_v9.py,
design_notes.md 79.x) is DRC-clean).

Three inputs, exactly as the user specified:
1. "コアの LVS クリーンの spice" -- schematic/i2c_slave_async_nrow_fm_v9.
   spice (the CORE's own LVS-clean netlist, confirmed "Congratulations!
   Netlists match." by the user in 77.47). Self-contained: top subckt +
   all 18 library-cell bodies + FILL2/FILL3 decap MOSFETs, embedded
   inline (verified below, not assumed).
2. "GIOのschematic" -- simulations/OSS_FRAME_GIO.spice, the transistor-
   level netlist for OSS_FRAME_GIO (the pad-ring frame), generated from
   its own xschem schematic (schematic/OSS_FRAME_GIO.sch /
   TR-1um_frame/OSS_FRAME_GIO.sch -- same cell, PDK-side copy). Also
   self-contained: OSS_FRAME_GIO + its 3 dependency subckts
   (OSS_ESD_5V_DIO/_VDD/_VSS), embedded inline (verified below).
3. "JSON情報" -- schematic/gio_connections.json, the exhaustive,
   per-terminal GIO<->core connection map derived in 78.1 (cross-
   verified against v7's actual routing script, 78.4) and unchanged by
   any later HIZ/OUT/power-architecture work in this session (79.x
   power-routing changes are PHYSICAL and don't alter which SCHEMATIC
   net each pin belongs to -- the core's own VDD/GND ports still tie to
   exactly one net each, "VDD"/"VSS", regardless of how many physical
   TAP columns + bus bars now fan that net out on the layout side).

This script does NOT re-derive the connection map -- gio_connections.
json IS that derivation, already cross-verified in 78.1/78.4. This
script's only job is the mechanical, deterministic assembly: read the
two self-contained SPICE bodies verbatim, build the two instance lines'
positional-argument nets from the JSON, and emit one top-level subckt
tying them together -- matching the structural shape of the OLD (pre-v9,
now-stale) src/tr_1um_i2c_slave_async.cir (".subckt tr_1um_i2c_slave_
async" with no ports, x1=GIO, x2=core instances) but with v9-correct
connections instead of that file's outdated v7/v8-era wiring.

Port orders are read directly from each subckt's own declaration line in
its source file (not retyped by hand), and cross-checked at the end
against the JSON-derived net-count so a future edit to either source
file can't silently desync the instance line from the subckt it's
calling.
"""
import json
import re
from pathlib import Path

# 2026-09-02: made portable (was hardcoded to a Claude-sandbox absolute
# path -- see lef_parser.py's LEF_PATH for the same fix).
import os

BASE = str(Path(__file__).resolve().parent.parent)
# XSCHEM_SIM_DIR env var override -- see gen_lvs_spice_v9.py's identical
# comment (Claude's sandbox mounts ~/.xschem/simulations at a path that
# isn't literally Path.home()/".xschem"/"simulations").
_XSCHEM_SIM_DIR = os.environ.get("XSCHEM_SIM_DIR", str(Path.home() / ".xschem" / "simulations"))
GIO_SPICE = _XSCHEM_SIM_DIR + "/OSS_FRAME_GIO.spice"
CORE_SPICE = BASE + "/schematic/i2c_slave_async_nrow_fm_v9.spice"
CONN_JSON = BASE + "/schematic/gio_connections.json"
OUT_SCHEMATIC = BASE + "/schematic/tr_1um_i2c_slave_async_v9_lvs.spice"
OUT_SIMULATIONS = _XSCHEM_SIM_DIR + "/tr_1um_i2c_slave_async.spice"

TOP_NAME = "tr_1um_i2c_slave_async"


def read_subckt_port_order(path, subckt_name):
    """Read the exact positional port order straight from the file's own
    `.subckt <name> ...` declaration line(s) (SPICE '+' continuation
    lines supported) -- never hand-transcribed, so it can't drift from
    the real file."""
    text = open(path).read()
    # find the .subckt block: starts at ".subckt <name>", continuation
    # lines start with '+', block ends at the first line that doesn't
    # start with '+'.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f".subckt {subckt_name} ") or line.strip() == f".subckt {subckt_name}":
            tokens = line.split()[2:]  # drop ".subckt" and the name
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                tokens += lines[j][1:].split()
                j += 1
            return tokens
    raise RuntimeError(f"'.subckt {subckt_name}' not found in {path}")


def load_body_verbatim(path):
    return open(path).read().rstrip("\n")


def main():
    conn = json.load(open(CONN_JSON))

    gio_ports = read_subckt_port_order(GIO_SPICE, "OSS_FRAME_GIO")
    core_ports = read_subckt_port_order(CORE_SPICE, "i2c_slave_async_nrow_fm")
    print(f"OSS_FRAME_GIO port order ({len(gio_ports)} ports), read from {GIO_SPICE}:")
    print(" ", gio_ports)
    print(f"i2c_slave_async_nrow_fm port order ({len(core_ports)} ports), read from {CORE_SPICE}:")
    print(" ", core_ports)

    # ---- build GIO-side port -> net map, straight from the JSON ----
    detail = conn["connections_per_terminal_detail"]
    gio_net = {}
    nc_count = [0]

    def nc(label):
        nc_count[0] += 1
        return f"NC_{label}"

    for pin in gio_ports:
        if pin == "VDD":
            gio_net[pin] = "VDD"
            continue
        if pin == "VSS":
            gio_net[pin] = "VSS"
            continue
        info = detail.get(pin)
        if info is None:
            raise RuntimeError(f"GIO pin {pin!r} has no entry in connections_per_terminal_detail")
        net = info.get("net")
        gio_net[pin] = net if net is not None else nc(pin)

    # ---- build core-side port -> net map ----
    # Invert the JSON's "core_signal" fields (found either directly on a
    # P<n>/OUT<n> terminal, or via the pad-cell's HIZ13/sda_oe special
    # case) to get, for each core port, which GIO-side net (already
    # computed above) it lands on.
    core_net = {}
    # power first (explicit block in the JSON)
    core_net["VDD"] = "VDD"
    core_net["GND"] = "VSS"  # JSON: "core symbol names its power pin 'GND' but the net is 'VSS'"

    # every other core port: find the GIO terminal whose core_signal
    # matches, and reuse that terminal's already-resolved net.
    signal_to_gio_pin = {}
    for pin, info in detail.items():
        sig = info.get("core_signal") if isinstance(info, dict) else None
        if sig:
            signal_to_gio_pin[sig] = pin

    unconnected_core_ports = []
    for port in core_ports:
        if port in ("VDD", "GND"):
            continue
        if port in signal_to_gio_pin:
            core_net[port] = gio_net[signal_to_gio_pin[port]]
        else:
            core_net[port] = nc(f"CORE_{port}")
            unconnected_core_ports.append(port)

    print("\nCore ports with NO GIO pad connection (net left floating, unique NC_* name):")
    for p in unconnected_core_ports:
        print("  ", p, "->", core_net[p])
    print("\nGIO pins with NO connection (net left floating, unique NC_* name):")
    for pin in gio_ports:
        if gio_net[pin].startswith("NC_"):
            print("  ", pin, "->", gio_net[pin])

    # ---- TOP-LEVEL CHIP PINS (79.13 / this fix) ----
    # User's root-cause diagnosis: the earlier version of this netlist had
    # a PORT-LESS top subckt (".subckt tr_1um_i2c_slave_async", no pins,
    # matching the old pre-v9 src/tr_1um_i2c_slave_async.cir's own
    # structure) -- and the LAYOUT-side extraction of the same top cell
    # independently confirmed the same gap (src/tr_1um_i2c_slave_async.
    # extracted: ".SUBCKT tr_1um_i2c_slave_async VSS", only ONE top pin).
    # Neither side exposes the chip's real bond-pad nets (P1-P7, P9-P15,
    # VDD, VSS -- P8 doesn't exist in this frame, per gio_connections.
    # json) as actual top-level PORTS; without that, KLayout's LVS
    # top-level pin/port alignment has nothing solid to anchor on, which
    # is what let the ambiguity cascade down into the OSS_FRAME_GIO
    # circuit-level pin mismatches (HIZ2/HIZ7/HIZ9/HIZ10/HIZ15/OUT13)
    # investigated in design_notes.md 79.x / this session's LVS_error.
    # lvsdb analysis.
    #
    # Fix: rename the internal net that already carries each pad's
    # connection (e.g. P1's net was called "IN5", purely an artifact of
    # this script picking whichever GIO-side terminal name it saw first)
    # to the pad's own canonical name, and declare all 16 as real ports
    # of the top subckt. VDD/VSS were already correctly named, so only
    # the 14 data-pad nets actually get renamed; P9/P10/P11 (currently
    # NC_-prefixed floating nets, since nothing internal uses them) still
    # become real top pins -- they're real physical pads on the chip
    # regardless of whether anything inside consumes them.
    TOP_PIN_ORDER = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "VSS",
                      "P9", "P10", "P11", "P12", "P13", "P14", "P15", "VDD"]
    rename = {}
    for pad in TOP_PIN_ORDER:
        if pad in ("VDD", "VSS"):
            continue
        old_name = gio_net[pad]
        rename[old_name] = pad
    print(f"\nTop-pin net renames ({len(rename)}):")
    for old, new in rename.items():
        print(f"   {old:10} -> {new}")
    for pin in gio_net:
        gio_net[pin] = rename.get(gio_net[pin], gio_net[pin])
    for port in core_net:
        core_net[port] = rename.get(core_net[port], core_net[port])

    # sanity: every core port and every GIO port must have been assigned
    # exactly one net string.
    assert len(core_net) == len(core_ports), (len(core_net), len(core_ports))
    assert len(gio_net) == len(gio_ports), (len(gio_net), len(gio_ports))
    assert all(p in core_net for p in core_ports)
    assert all(p in gio_net for p in gio_ports)

    x1_nets = [gio_net[p] for p in gio_ports]
    x2_nets = [core_net[p] for p in core_ports]

    gio_body = load_body_verbatim(GIO_SPICE)
    core_body = load_body_verbatim(CORE_SPICE)

    # subckt-name collision check between the two embedded bodies (both
    # files are otherwise independently self-contained; if they ever
    # shared a subckt name this assembly would silently redefine one
    # with the other's body).
    def subckt_names(text):
        return set(re.findall(r"^\.subckt\s+(\S+)", text, re.MULTILINE))

    gio_names = subckt_names(gio_body)
    core_names = subckt_names(core_body)
    overlap = gio_names & core_names
    if overlap:
        raise RuntimeError(f"subckt name collision between GIO and core bodies: {overlap}")
    print(f"\nNo subckt-name collisions: GIO defines {sorted(gio_names)}, core defines {len(core_names)} cells "
          f"(18 library cells + top), disjoint confirmed.")

    def wrap_instance_line(inst_name, nets, subckt_name):
        # SPICE line-length hygiene: wrap at ~8 nets per continuation
        # line, matching the style already used by the two embedded
        # files' own multi-line .subckt declarations.
        out = [f"{inst_name} " + " ".join(nets[:8])]
        rest = nets[8:]
        while rest:
            out.append("+ " + " ".join(rest[:8]))
            rest = rest[8:]
        out[-1] += f" {subckt_name}"
        return "\n".join(out)

    x1_line = wrap_instance_line("x1", x1_nets, "OSS_FRAME_GIO")
    x2_line = wrap_instance_line("x2", x2_nets, "i2c_slave_async_nrow_fm")

    header = f"""\
** {TOP_NAME}_v9_lvs.spice -- chip-level LVS reference netlist (v9)
** Generated by script/gen_lvs_spice_top_v9.py from:
**   1) schematic/i2c_slave_async_nrow_fm_v9.spice (core, LVS-clean per
**      design_notes.md 77.47 -- "Congratulations! Netlists match.")
**   2) simulations/OSS_FRAME_GIO.spice (GIO pad-ring frame, transistor
**      level, from its own xschem schematic)
**   3) schematic/gio_connections.json (GIO<->core connection map,
**      derived + cross-verified in design_notes.md 78.1/78.4)
** x1 = OSS_FRAME_GIO, x2 = i2c_slave_async_nrow_fm, matching the
** instance naming already used in the (now-stale, pre-v9)
** src/tr_1um_i2c_slave_async.cir. Nets prefixed NC_ are genuinely
** unconnected on both sides (spare pads P9/P10/P11-in/OUT2/OUT7/OUT9/
** OUT10/OUT15, and core's tx_data[1]/rx_valid/addr_match/rw/busy --
** none of these are wired to any GIO pad in this design, confirmed by
** gio_connections.json's own "core_outputs_not_connected_to_any_pad"
** and per-terminal "unconnected" notes) -- each gets its own unique
** floating net name rather than being tied together, so LVS sees them
** as independently floating, matching the real chip.
**
** TOP-LEVEL PIN FIX (this revision): the top subckt now declares its
** 16 real bond-pad ports explicitly (P1-P7, VSS, P9-P15, VDD -- P8
** does not exist in this frame). The previous revision had a
** port-less ".subckt {TOP_NAME}" line, matching the old pre-v9
** src/tr_1um_i2c_slave_async.cir's own structure -- and the
** LAYOUT-side extraction of the same top cell independently confirmed
** the same gap (src/tr_1um_i2c_slave_async.extracted:
** ".SUBCKT tr_1um_i2c_slave_async VSS", only one top pin). Neither
** side exposed the chip's real bond-pad nets as actual top-level
** PORTS, which is what let KLayout's LVS pin/port alignment fall back
** on ambiguous internal matching and produced the OSS_FRAME_GIO-level
** pin mismatches (HIZ2/HIZ7/HIZ9/HIZ10/HIZ15/OUT13) seen in
** src/LVS_error.lvsdb. Fix: rename each pad's carrying net to the
** pad's own canonical name (e.g. P1's net was "IN5") and declare all
** 16 as real subckt ports; see design_notes.md for the full writeup.
"""

    body_parts = [
        header,
        gio_body,
        "",
        core_body,
        "",
        f".subckt {TOP_NAME} " + " ".join(TOP_PIN_ORDER),
        x1_line,
        x2_line,
        ".ends",
        "",
    ]
    out_text = "\n".join(body_parts)

    open(OUT_SCHEMATIC, "w").write(out_text)
    open(OUT_SIMULATIONS, "w").write(out_text)
    print(f"\nwrote {OUT_SCHEMATIC}")
    print(f"wrote {OUT_SIMULATIONS}")
    print(f"\nx1 (OSS_FRAME_GIO) instance: {len(x1_nets)} nets")
    print(f"x2 (i2c_slave_async_nrow_fm) instance: {len(x2_nets)} nets")
    print(f"Total NC_* (floating) nets created: {nc_count[0]}")


if __name__ == "__main__":
    main()
