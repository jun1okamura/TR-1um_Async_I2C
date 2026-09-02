"""
gen_chip_sim_ready_v9.py (this session, user request: "TR-1um_Async_I2C
にて、ダメ押しで、ngspice で全体チップ検証をします。TR-1um_Async_I2C/
ngspice のディレクトリを作成して、LVS検証がOKになった spice net から
RING_OSC を除いて検証用の spice ファイルを準備ください。")

Builds a real, locally-runnable ngspice netlist for the WHOLE CHIP
(OSS_FRAME_GIO pad ring + i2c_slave_async_nrow_fm core, RING_OSC
excluded) from the schematic-side LVS reference netlist that the user's
local KLayout LVS run already confirmed clean (design_notes.md 104.3:
"ユーザーがローカルLVSツールで実行しLVSクリーンを確認").

**Netlist source and the "remove RING_OSC" step**: `gen_lvs_spice_top_
v9.py` already emits TWO sibling files from the same generation run --
schematic/tr_1um_i2c_slave_async_v9_lvs.spice (x1=OSS_FRAME_GIO,
x2=i2c_slave_async_nrow_fm only) and schematic/tr_1um_i2c_slave_async_
ringosc_v9_lvs.spice (the same plus x3=RING_OSC). Directly diffed the
two: byte-identical for the first 723 lines (everything up to the final
top .subckt block), and the ringosc file's only additions are (a) the
RING_OSC/INV3D subckt bodies, (b) one "x3 OUT10 OUT9 P15 VDD VSS
RING_OSC" instance line, and (c) x1's own OUT9/OUT10 ports switch from
floating NC_OUT9/NC_OUT10 (base file) to real OUT9/OUT10 nets (ringosc
file, so x3 can drive them). I.e. the base (non-ringosc) file already
*is* "the LVS-confirmed netlist with RING_OSC mechanically removed" --
by construction from the same script, not by coincidence -- so no
manual stripping is needed; it's used directly as SRC below.

**Two fixes needed before a real ngspice .tran will run**, neither of
which is optional and both confirmed by direct inspection (not
assumed):

1. **Bare M-line -> X-line (subckt-call) conversion.** Every one of
   this file's 358 transistor instance lines is a bare M-line (e.g.
   "MXM1 PAD PG VDD VDD PMOS w=300u l=2u") -- KLayout's own LVS netlist
   convention, which expects a real ".model PMOS ..." card. But
   ~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/ip62_models (the
   same model include already confirmed working for RING_OSC's own
   ngspice testbench, script/gen_ring_osc_tb.py) only provides PMOS/
   NMOS as **.subckt** wrappers (".subckt PMOS d g s b" internally
   calling ".model PMOS_mst PMOS"), not as bare .model cards under
   those exact names -- so bare M-lines can't resolve them, and a real
   ngspice run would abort with an unresolved-model error. This is the
   SAME class of fix design_notes.md 104 (ring_osc v1 testbench, now
   superseded by the extracted-netlist v2) already applied to RING_OSC.
   spice's own leaf cells, for the identical reason. Fix: mechanically
   rename every bare M-line's leading "M" to "X" (nothing else on the
   line changes -- same node order, same model token, same w=/l=/m=
   params) so it becomes a subckt-instantiation line ip62_models can
   resolve.

2. **Bracket-vector net names -> underscore form (152 occurrences, 39
   distinct identifiers -- e.g. "tx_data[0]" -> "tx_data_0"), everywhere
   they appear (both the i2c_slave_async_nrow_fm .subckt header's own
   formal pin list AND every internal net reference inside that
   subckt's body -- rx_data/tx_data/txreg/shreg/bit_cnt/phase/_147_,
   all Yosys-carried-over Verilog vector names from the netlist this
   file's source was generated from, gen_lvs_spice_v9.py's own
   i2c_slave_async_net_v9_rowbuf.v). Added after a REAL local ngspice
   run (2026-09-01) failed with "too few nodes" on the x2 (i2c_slave_
   async_nrow_fm) instantiation line, despite the raw node COUNT on
   both the instantiation call and the .subckt header verified byte-
   for-byte equal (26==26, checked both by eye and by an independent
   Python token count) -- i.e. not a real node-count mismatch, and no
   duplicate ".subckt i2c_slave_async_nrow_fm" declaration exists
   either. The only structural difference between this subckt and every
   other one in the file (OSS_FRAME_GIO, the ESD cells, all the leaf
   standard cells) is these bracket-containing net names -- ngspice's
   own default (non-compatibility-mode, per that real run's own "Note:
   No compatibility mode selected!" banner) node-name tokenizer
   apparently doesn't treat "[...]" as safe within a bare identifier the
   same way this project's other tools (Yosys, IRSIM, KLayout LVS) do.
   Renaming to a bracket-free but still fully distinct/unambiguous form
   sidesteps the tokenizer issue without touching electrical topology --
   confirmed after the rename that the SAME 152 locations, now suffixed
   "_N" instead of "[N]", still uniquely round-trip to the same 39
   original names (verified by re-deriving the original bracket form
   from each renamed one and diffing against the pre-rename occurrence
   set).
3. **Malformed multi-line PININFO comment (1 block, i2c_slave_async_
   nrow_fm only) -- the ACTUAL "too few nodes" root cause.** Two real
   local ngspice runs after fixes #1/#2 above STILL failed with the
   identical "too few nodes: x2 <26 nodes> i2c_slave_async_nrow_fm"
   error -- despite the raw node count on both the x2 instantiation and
   the .subckt header being independently re-verified equal (26==26,
   twice, once before and once after the bracket rename). The real
   cause, found by comparing this file's OWN two different multi-line
   "*.PININFO ..." comment blocks against each other: OSS_FRAME_GIO's
   PININFO block (this file's other multi-line one, lines 67-69 in an
   early revision) correctly prefixes EVERY continuation line with
   "*+" (so the whole thing stays a comment, line by line) -- but
   i2c_slave_async_nrow_fm's PININFO block (generated by a DIFFERENT
   script, gen_lvs_spice_v9.py, per this file's own header, not
   klayout's own SPICE writer that emits the "*+"-style blocks
   elsewhere) instead used a BARE "+" for its own continuation lines --
   a real bug in that other, unrelated generator. A bare "+" line is
   NOT a comment; it's SPICE's own line-continuation marker, which
   applies to the nearest preceding REAL (non-comment) statement --
   since the immediately preceding line here IS a comment ("*.PININFO
   ..."), ngspice's parser evidently reaches back past it and silently
   appends this "PININFO" block's own ~17 extra ":I"/":O"/":B"-suffixed
   pseudo-node tokens onto the .subckt HEADER's real 26-pin argument
   list instead -- inflating i2c_slave_async_nrow_fm's registered
   formal-pin count well past 26, so any real 26-node instantiation
   (x2's, correct) then reads as "too few". (OSS_FRAME_GIO's own x1
   instantiation was unaffected simply because ITS PININFO block uses
   the correct "*+" form throughout, confirmed by direct comparison of
   the two blocks side by side.) Fix: any comment line's own "+"
   continuation that is missing its OWN leading "*" gets one added
   (bare "+" -> "*+"), matching the correct/working convention already
   used everywhere else in this file -- purely a comment-syntax fix,
   removes zero information, changes no electrical node.
4. **Diode instance parameter names: A=/P= -> AREA=/PJ= (2 instances,
   DD1/DD2 inside OSS_ESD_5V_DIO).** A real local ngspice run past
   fixes #1-#3 above got further (no more "too few nodes") but then
   failed on "d.xdut.x1.x1.dd1 vss vdd dn a=12.96p p=14.4u: unknown
   parameter (a)". KLayout's LVS SPICE writer emits diode instance
   area/perimeter as the short forms "A="/"P=" (matching the MOSFET
   AS=/AD=/PS=/PD= convention's spirit, just for a 2-terminal device),
   but ngspice's native (non-compatibility-mode) diode instance parser
   only recognizes the full keywords "AREA="/"PJ=" -- "A"/"P" alone
   aren't accepted synonyms. Renamed both instances' parameter names
   (values unchanged: AREA=12.96p, PJ=14.4u for both DD1 and DD2) --
   purely a keyword-spelling fix, same class as fixes #1-#3.
5. **NMOSE -> MNE model rename (4 instances, chip-only -- RING_OSC never
   hit this).** Of the 358 bare M-lines, 354 reference "PMOS"/"NMOS"
   (fine after the M->X fix above) but 4 reference "NMOSE" -- all
   inside the OSS_ESD_5V_DIO/VDD/VSS pad-ESD subcircuits (the chip's
   pad ring, never exercised by the RING_OSC-only testbench, which is
   why this is a new problem). "NMOSE" does not exist anywhere in
   ip62_models (checked: only PMOS/NMOS/MPE/MNE are defined) or as a
   SPICE model/subckt name anywhere in this repo or the connected PDK
   mount. Traced its origin: it's a KLayout DRC/LVS device-recognition
   label (libs.tech/klayout/tech/python/cells/rules_def.py's own
   'ANE.WM'/'ANE.LM' rules, keyed to an "ANE" -- Active-N-Extended --
   layer), assigned purely for LVS device typing, NOT a SPICE library
   name. Cross-checked against the ORIGINAL xschem schematic these ESD
   cells were captured from (libs.tech/xschem/TR-1um_frame/OSS_ESD_5V_
   DIO.sch): its own transistor instances carry a "model=MNE" property
   for the extended-drain NMOS devices (never "model=NMOSE") -- MNE is
   exactly the "Extended NMOS" subckt ip62_models does provide, and the
   only PDK-real synonym for a KLayout-recognized extended-drain NMOS.
   Physically plausible too: 5V-tolerant ESD pad cells routinely need
   an extended-drain (higher breakdown voltage) device for their large
   pull-down/clamp transistors, which is exactly where all 4 NMOSE
   instances sit (OSS_ESD_5V_DIO's MXM2/MXM6, OSS_ESD_5V_VDD's MXM6,
   OSS_ESD_5V_VSS's MXM4 -- all W=150u-500u power devices, not small
   logic transistors). This is the best-supported mapping available,
   but IS an inference (no single authoritative KLayout<->ip62_models
   cross-reference table was found) -- flagged to the user; sanity-
   check the ESD-cell node waveforms on the first real run.

Nothing else in the file is touched: same 16 top-level ports (P1-P7,
VSS, P9-P15, VDD -- P8 does not exist), same net names, same hierarchy,
same w=/l=/m= device sizing. Verified after generation via (a) a diff
against the source showing ONLY M->X prefix changes and the 4 NMOSE->
MNE token swaps, and (b) klayout.db.NetlistSpiceReader successfully
parsing the result and resolving the full x1/x2 hierarchy (this sandbox
has no ngspice -- confirmed in design_notes.md 16607, root-less install
not possible -- so this is the same syntactic-only verification already
used for the RING_OSC v1 testbench before the user's first real local
run).
"""
import re
from pathlib import Path

# 2026-09-02: made portable (was hardcoded to a Claude-sandbox absolute
# path -- see lef_parser.py's LEF_PATH for the same fix).
_REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = str(_REPO_ROOT / "schematic" / "tr_1um_i2c_slave_async_v9_lvs.spice")
OUT_DIR = str(_REPO_ROOT / "ngspice")
OUT_PATH = OUT_DIR + "/tr_1um_i2c_slave_async_sim_ready.spice"

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
        "* tr_1um_i2c_slave_async_sim_ready.spice -- auto-generated by\n"
        "* script/gen_chip_sim_ready_v9.py, from:\n"
        "*   " + SRC + "\n"
        "* (the LVS-confirmed-clean chip netlist, RING_OSC excluded -- see\n"
        "* this script's own module docstring for why the source file already\n"
        "* excludes RING_OSC with no manual stripping needed). Mechanical\n"
        "* fixes applied on top of the verbatim source, all required for a\n"
        "* real ngspice run (none change electrical intent):\n"
        f"*   1) all {n_converted} bare M-line transistor instances -> X-line\n"
        "*      (subckt-call) form, so ip62_models' PMOS/NMOS .subckt wrappers\n"
        "*      resolve them (KLayout's own bare-M LVS convention doesn't).\n"
        f"*   2) {n_bracket_names} bracket-vector net names ({n_bracket_subs}\n"
        "*      occurrences, e.g. tx_data[0] -> tx_data_0), everywhere they\n"
        "*      appear -- a general SPICE-portability cleanup (kept even after\n"
        "*      #3 below turned out to be the real fix for the \"too few nodes\"\n"
        "*      error; harmless and arguably still worth having).\n"
        f"*   3) {n_comment_fixed} malformed comment-continuation line(s) in the\n"
        "*      i2c_slave_async_nrow_fm PININFO block (bare \"+\" -> \"*+\") --\n"
        "*      THIS was the actual root cause of a real local ngspice run's\n"
        "*      \"too few nodes\" error on the x2 instantiation, found by\n"
        "*      comparing this file's two multi-line PININFO comment blocks\n"
        "*      against each other; see module docstring fix #3 for the full\n"
        "*      diagnosis.\n"
        f"*   4) {n_diode_fixed} diode instance parameter(s) renamed A=/P= ->\n"
        "*      AREA=/PJ= (DD1/DD2 inside OSS_ESD_5V_DIO) -- ngspice's native\n"
        "*      diode instance parser doesn't accept the short forms KLayout's\n"
        "*      LVS writer emits; values unchanged, purely a keyword-spelling\n"
        "*      fix. Found from a real local ngspice run's \"unknown parameter\n"
        "*      (a)\" error past fix #3 above; see module docstring fix #4.\n"
        f"*   5) {n_renamed} bare-M devices (originally model=NMOSE, all inside\n"
        "*      the OSS_ESD_5V_* pad-ESD cells) renamed to model=MNE -- NMOSE is\n"
        "*      a KLayout DRC/LVS device-recognition label with no SPICE-library\n"
        "*      counterpart; MNE is ip62_models' extended-drain NMOS and what\n"
        "*      these cells' own source xschem schematic actually specifies\n"
        "*      (property model=MNE) -- see module docstring for the full\n"
        "*      cross-check. This is the best-supported mapping found but IS\n"
        "*      an inference; sanity-check ESD-cell nodes on first real run.\n"
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
