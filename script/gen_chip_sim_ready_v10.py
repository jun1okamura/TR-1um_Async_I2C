"""
gen_chip_sim_ready_v10.py (V10 counterpart of gen_chip_sim_ready_v9.py --
user request, this session: "Spiceでチップレベルのテストベンチでの動作
検証をします。RING_OSCを除いたファイルを用意してください。", after
confirming real KLayout DRC/LVS clean on V10 post-108.63/108.64 fixes).

Builds a real, locally-runnable ngspice netlist for the WHOLE V10 CHIP
(OSS_FRAME_GIO pad ring + i2c_slave_async_nrow_fm core, RING_OSC
excluded) from schematic/tr_1um_i2c_slave_async_v10_lvs.spice -- the
V10 schematic-side LVS reference netlist (script/gen_lvs_spice_top_
v10.py), unaffected by this session's 108.63/108.64 fixes since those
were LAYOUT-side-only (route_gio_core_v10.py physical GDS routing);
gio_connections.json (the schematic-side source of truth for HIZ1/
HIZ7/OUT2's net assignments) never needed correction -- the layout was
the thing not matching the schematic, not the other way around.

**"RING_OSC excluded" needs no manual stripping**, same as v9: `gen_lvs_
spice_top_v10.py` emits tr_1um_i2c_slave_async_v10_lvs.spice (x1=OSS_
FRAME_GIO, x2=i2c_slave_async_nrow_fm only) as a sibling of tr_1um_
i2c_slave_async_v10_ringosc_lvs.spice (adds x3=RING_OSC) from the same
run -- the non-ringosc file already *is* the RING_OSC-free netlist by
construction, so it's used directly as SRC below.

**Same five mechanical fixes as v9** (full rationale for each -- why
they're needed, how they were diagnosed against a real local ngspice
run, and why each is safe/lossless -- is documented at length in
gen_chip_sim_ready_v9.py's own module docstring; not re-derived here
since the transform logic is 100% reused verbatim, only the SRC/OUT_
PATH constants below changed). Confirmed by direct inspection that
V10's LVS spice has the identical five defect *shapes* as v9's did
(counts differ, same regexes apply cleanly):
  1) bare M-line -> X-line transistor conversion (V10: 378 lines, vs
     v9's 358 -- V10 has more standard cells from its re-synthesized/
     re-placed core).
  2) bracket-vector net names -> underscore form (V10: 37 distinct
     names / 145 occurrences, vs v9's 39/152).
  3) malformed PININFO comment continuation (bare "+" -> "*+") in the
     i2c_slave_async_nrow_fm block -- same 2-line fix as v9.
  4) diode instance A=/P= -> AREA=/PJ= (DD1/DD2 inside OSS_ESD_5V_DIO)
     -- same 2-instance/4-parameter fix as v9.
  5) NMOSE -> MNE model rename (4 instances, all inside the OSS_ESD_5V_*
     pad-ESD cells) -- same count and same inferred mapping as v9 (see
     v9 script's docstring for the full cross-check against the ESD
     cells' own xschem source schematic, which is shared/unchanged
     between v9 and v10 -- same physical GIO frame).

Nothing else in the file is touched: same 16 top-level ports (P1-P7,
VSS, P9-P15, VDD -- P8 does not exist), same net names, same hierarchy,
same w=/l=/m= device sizing -- just V10's own core netlist and V10's
own pad-pairing-aware terminal reassignment (v10_signal_routing_plan.
json, design_notes.md 108.57) baked into the x1/x2 instantiation lines
already, unchanged by this script. Verified after generation the same
way as v9: (a) a diff against the source showing ONLY M->X prefix
changes and NMOSE->MNE token swaps, (b) klayout.db.NetlistSpiceReader
successfully parsing the result end-to-end.
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = str(_REPO_ROOT / "schematic" / "tr_1um_i2c_slave_async_v10_lvs.spice")
OUT_DIR = str(_REPO_ROOT / "ngspice")
OUT_PATH = OUT_DIR + "/tr_1um_i2c_slave_async_v10_sim_ready.spice"

MODEL_RENAME = {"NMOSE": "MNE"}

# Matches a bare MOSFET instance line: "M<name> <4 nodes> <model> <params...>"
# Captures: (1) instance-name suffix after the leading M, (2) everything
# between the name and the model token (the 4 node names), (3) the model
# token itself, (4) the rest of the line (w=/l=/m= params, unchanged).
BARE_M_RE = re.compile(
    r"^M(\S+)((?: \S+){4}) (PMOS|NMOSE|NMOS)\b(.*)$", re.M
)


def convert(text):
    n_converted = 0
    n_renamed = 0

    def repl(m):
        nonlocal n_converted, n_renamed
        name, nodes, model, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        n_converted += 1
        if model in MODEL_RENAME:
            n_renamed += 1
            model = MODEL_RENAME[model]
        return f"X{name}{nodes} {model}{rest}"

    new_text = BARE_M_RE.sub(repl, text)
    return new_text, n_converted, n_renamed


# Matches a Verilog-vector-style bracket net name, e.g. "tx_data[0]",
# "_147_[2]" -- anywhere it appears (subckt header formal pins AND
# internal net references), all confined to the i2c_slave_async_
# nrow_fm subckt body (see module docstring, fix #2).
BRACKET_NET_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]")


def debracket(text):
    occurrences = BRACKET_NET_RE.findall(text)
    original_names = sorted(set(f"{base}[{idx}]" for base, idx in occurrences))
    renamed_names = sorted(set(f"{base}_{idx}" for base, idx in occurrences))

    # Collision check: none of the NEW (renamed) identifiers may already
    # exist as a distinct, standalone identifier in the ORIGINAL text --
    # otherwise the rename would silently merge two different nets (a
    # pre-existing "tx_data_0" net colliding with renamed "tx_data[0]",
    # for instance) into one.
    collisions = [
        n for n in renamed_names
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_\[])", text)
    ]
    if collisions:
        raise RuntimeError(
            f"debracket(): {collisions} already exist as standalone identifiers "
            f"in the source -- renaming the bracket form to the same spelling "
            f"would silently short two distinct nets together; refusing."
        )

    new_text, n_subs = BRACKET_NET_RE.subn(r"\1_\2", text)
    return new_text, len(original_names), n_subs


def fix_comment_continuations(text):
    """Any comment line ('*...') whose own wrap continuation was written
    as a bare '+' (a REAL SPICE continuation marker, applying to the
    nearest preceding non-comment statement -- not a comment itself)
    instead of '*+' (the correct form used elsewhere in this file, see
    module docstring fix #3) gets '*' prepended, so it stays a comment
    line-for-line like every other multi-line comment block here."""
    lines = text.split("\n")
    n_fixed = 0
    prev_is_comment = False
    for i, line in enumerate(lines):
        if line.startswith("*"):
            prev_is_comment = True
            continue
        if prev_is_comment and line.startswith("+"):
            lines[i] = "*" + line
            n_fixed += 1
            # stay "in comment" for further continuation lines of the
            # SAME (now-fixed) comment block
            continue
        prev_is_comment = False
    return "\n".join(lines), n_fixed


# Matches a bare diode instance line's short-form area/perimeter
# parameters, e.g. "DD1 VSS HIZ DN A=12.96p P=14.4u" -- see module
# docstring fix #4. Scoped to lines starting with "D" (diode instances
# only) so this can never touch the MOSFET AS=/AD=/PS=/PD= parameters
# used elsewhere (those already have extra letters before "=", so
# wouldn't match bare "A="/"P=" anyway, but the line-prefix scoping
# keeps this fix maximally narrow/auditable regardless).
DIODE_LINE_RE = re.compile(r"^D\S+ .*$", re.M)


def fix_diode_params(text):
    n_fixed = 0

    def repl(m):
        nonlocal n_fixed
        line = m.group(0)
        new_line, n_a = re.subn(r"(?<![A-Za-z])A=", "AREA=", line)
        new_line, n_p = re.subn(r"(?<![A-Za-z])P=", "PJ=", new_line)
        n_fixed += n_a + n_p
        return new_line

    return DIODE_LINE_RE.sub(repl, text), n_fixed


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    src_text = open(SRC).read()

    # Sanity: confirm the source really is all-bare-M (no pre-existing
    # X-line PMOS/NMOS/NMOSE devices that this pass might double-touch,
    # and no bare-M devices this regex might miss).
    n_bare = len(re.findall(r"^M\S+ .*\b(?:PMOS|NMOS|NMOSE)\b", src_text, re.M))
    n_x_already = len(re.findall(r"^X\S+ .*\b(?:PMOS|NMOS|NMOSE)\b", src_text, re.M))
    print(f"source: {n_bare} bare M-line PMOS/NMOS/NMOSE devices, "
          f"{n_x_already} already X-line (expect 0)")
    if n_x_already:
        raise RuntimeError(
            f"{SRC} unexpectedly has {n_x_already} X-line PMOS/NMOS/NMOSE "
            f"device(s) already -- re-check before assuming a clean M-only source."
        )

    converted_text, n_converted, n_renamed = convert(src_text)
    if n_converted != n_bare:
        raise RuntimeError(
            f"converted {n_converted} lines but source had {n_bare} bare "
            f"M-line devices -- regex missed some; do not trust this output."
        )

    remaining_bare = len(re.findall(r"^M\S+ .*\b(?:PMOS|NMOS|NMOSE)\b", converted_text, re.M))
    if remaining_bare:
        raise RuntimeError(f"{remaining_bare} bare M-line device(s) remain after conversion")

    converted_text, n_bracket_names, n_bracket_subs = debracket(converted_text)
    remaining_brackets = len(BRACKET_NET_RE.findall(converted_text))
    if remaining_brackets:
        raise RuntimeError(f"{remaining_brackets} bracket-style net reference(s) remain after debracket()")

    converted_text, n_comment_fixed = fix_comment_continuations(converted_text)

    converted_text, n_diode_fixed = fix_diode_params(converted_text)

    header = (
        "* tr_1um_i2c_slave_async_v10_sim_ready.spice -- auto-generated by\n"
        "* script/gen_chip_sim_ready_v10.py, from:\n"
        "*   " + SRC + "\n"
        "* (the LVS-confirmed-clean V10 chip netlist, RING_OSC excluded -- see\n"
        "* this script's own module docstring for why the source file already\n"
        "* excludes RING_OSC with no manual stripping needed). Mechanical\n"
        "* fixes applied on top of the verbatim source, all required for a\n"
        "* real ngspice run (none change electrical intent) -- same fix classes\n"
        "* as V9's gen_chip_sim_ready_v9.py, whose docstring has the full\n"
        "* diagnosis/rationale for each:\n"
        f"*   1) all {n_converted} bare M-line transistor instances -> X-line\n"
        "*      (subckt-call) form, so ip62_models' PMOS/NMOS .subckt wrappers\n"
        "*      resolve them (KLayout's own bare-M LVS convention doesn't).\n"
        f"*   2) {n_bracket_names} bracket-vector net names ({n_bracket_subs}\n"
        "*      occurrences, e.g. tx_data[0] -> tx_data_0), everywhere they\n"
        "*      appear.\n"
        f"*   3) {n_comment_fixed} malformed comment-continuation line(s) in the\n"
        "*      i2c_slave_async_nrow_fm PININFO block (bare \"+\" -> \"*+\") --\n"
        "*      the real root cause of V9's own \"too few nodes\" ngspice error\n"
        "*      on the x2 instantiation; see gen_chip_sim_ready_v9.py's\n"
        "*      docstring fix #3 for the full diagnosis.\n"
        f"*   4) {n_diode_fixed} diode instance parameter(s) renamed A=/P= ->\n"
        "*      AREA=/PJ= (DD1/DD2 inside OSS_ESD_5V_DIO) -- ngspice's native\n"
        "*      diode instance parser doesn't accept the short forms KLayout's\n"
        "*      LVS writer emits; values unchanged, purely a keyword-spelling\n"
        "*      fix.\n"
        f"*   5) {n_renamed} bare-M devices (originally model=NMOSE, all inside\n"
        "*      the OSS_ESD_5V_* pad-ESD cells) renamed to model=MNE -- NMOSE is\n"
        "*      a KLayout DRC/LVS device-recognition label with no SPICE-library\n"
        "*      counterpart; MNE is ip62_models' extended-drain NMOS and what\n"
        "*      these cells' own source xschem schematic actually specifies\n"
        "*      (property model=MNE) -- see gen_chip_sim_ready_v9.py's docstring\n"
        "*      for the full cross-check (same ESD cells, unchanged from v9).\n"
        "*      This is the best-supported mapping found but IS an inference;\n"
        "*      sanity-check ESD-cell nodes on first real run.\n"
        "* DO NOT hand-edit -- regenerate instead.\n\n"
    )
    out_text = header + converted_text

    with open(OUT_PATH, "w") as f:
        f.write(out_text)

    print(f"converted {n_converted} bare M-lines to X-line form "
          f"({n_renamed} of them NMOSE->MNE)")
    print(f"debracketed {n_bracket_names} distinct net names "
          f"({n_bracket_subs} occurrences)")
    print(f"fixed {n_comment_fixed} malformed comment-continuation line(s) "
          f"(bare '+' -> '*+')")
    print(f"fixed {n_diode_fixed} diode instance parameter name(s) "
          f"(A=/P= -> AREA=/PJ=)")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
