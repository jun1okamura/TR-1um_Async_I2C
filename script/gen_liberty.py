#!/usr/bin/env python3
"""
gen_liberty.py

Generates TR1um_5_stdcell.lib, a PLACEHOLDER Liberty (.lib) timing/function
library for the TR-1um_5_stdcell cell set, for use with Yosys/ABC
(`abc -liberty ...`) during logic synthesis feasibility work.

IMPORTANT: every delay/capacitance/area value below is a nominal placeholder
chosen only so ABC's stricter NLDM-style Liberty parser accepts the file
(it requires cell_rise/cell_fall/rise_transition/fall_transition lookup
tables, not the simpler intrinsic_rise/intrinsic_fall scalars that Yosys's
own `read_liberty` would otherwise accept). NONE of these numbers are
SPICE-characterized. Do not use for real STA or tapeout sign-off -- replace
the `DELAY` value (and ideally the whole lu_table_template resolution) per
cell once real characterization data for TR-1um_5_stdcell is available.

Regenerate with:  python3 script/gen_liberty.py > TR1um_5_stdcell.lib
"""

HEADER = """/* TR1um_5_stdcell.lib
 *
 * PLACEHOLDER Liberty file for synthesis-feasibility purposes only.
 * Functions/pins from xschem .sym (dir=in/out/inout) + standard naming.
 * area = simple relative placeholder. Timing uses a trivial 1x1 NLDM-style
 * lookup table (fixed 0.1-0.2ns regardless of slew/load) purely so ABC's
 * liberty/SCL reader accepts the file; NOT characterized, do not use for
 * real STA. Replace with SPICE-characterized Liberty before tapeout use.
 */

library(TR1um_5_stdcell) {
    delay_model : table_lookup;
    time_unit : "1ns";
    voltage_unit : "1V";
    current_unit : "1mA";
    pulling_resistance_unit : "1kohm";
    leakage_power_unit : "1nW";
    capacitive_load_unit (1, pf);

    default_input_pin_cap  : 1.0;
    default_output_pin_cap : 0.0;
    default_fanout_load    : 1.0;
    default_max_transition : 1.0;

    nom_process : 1.0;
    nom_temperature : 25.0;
    nom_voltage : 5.0;

    lu_table_template(delay_template) {
        variable_1 : input_net_transition;
        variable_2 : total_output_net_capacitance;
        index_1 ("0.1, 1.0");
        index_2 ("0.1, 1.0");
    }

"""

# rise_transition/fall_transition are held constant across every cell in
# this placeholder library -- only cell_rise/cell_fall ("DELAY" below) vary
# per cell, scaled roughly by input count / drive strength.
TRANSITION = "0.1, 0.1"

def vt(v):
    return f'"{v}, {v}"'

def timing_block(related_pin, sense, delay, indent="            "):
    return (
        f"{indent}timing() {{\n"
        f"{indent}    related_pin: \"{related_pin}\";\n"
        f"{indent}    timing_sense: {sense};\n"
        f"{indent}    cell_rise(delay_template) {{ values({vt(delay)}, {vt(delay)}); }}\n"
        f"{indent}    cell_fall(delay_template) {{ values({vt(delay)}, {vt(delay)}); }}\n"
        f"{indent}    rise_transition(delay_template) {{ values({vt(TRANSITION.split(', ')[0])}, {vt(TRANSITION.split(', ')[0])}); }}\n"
        f"{indent}    fall_transition(delay_template) {{ values({vt(TRANSITION.split(', ')[0])}, {vt(TRANSITION.split(', ')[0])}); }}\n"
        f"{indent}}}\n"
    )

def comb_cell(name, area, in_pins, func, sense, delay):
    pins_related = " ".join(in_pins)
    out = f"    cell({name}) {{\n        area: {area};\n"
    for p in in_pins:
        out += f"        pin({p}) {{ direction: input; capacitance: 1.0; }}\n"
    out += "        pin(Y) {\n            direction: output;\n"
    out += f"            function: \"{func}\";\n"
    out += timing_block(pins_related, sense, delay)
    out += "        }\n    }\n"
    return out

def latch_cell(name, area, set_pin, clear_pin):
    """SR-latch (cross-coupled NOR2 pair, design_notes.md 108.27/108.29/
    108.41): Liberty has no clean native primitive for a bare NOR-NOR SR
    latch (its `latch()` group is written for a D-latch with an enable),
    so this is modeled, same placeholder spirit as ff_cell() below, as a
    transparent latch whose data_in/enable are chosen so ABC's liberty
    reader accepts a syntactically valid sequential element with the
    right pin set/directions -- NOT a rigorous SR-latch timing model.
    RSLATCH is never actually synthesis-mapped TO by ABC in this flow
    (merge_muxdffrb_rslatch.py inserts it via a post-synthesis text
    transform on cross-coupled NOR2 pairs it finds directly), so this
    entry exists for library completeness/LVS-adjacent consistency with
    every other STDCELL, not because ABC needs to map onto it."""
    out = f"    cell({name}) {{\n        area: {area};\n"
    out += "        latch(IQ, IQN) {\n"
    out += f"            enable  : \"{set_pin} + {clear_pin}\";\n"
    out += f"            data_in : \"{set_pin}\";\n"
    out += f"            clear   : \"{clear_pin}\";\n"
    out += "        }\n"
    out += f"        pin({set_pin})   {{ direction: input; capacitance: 1.0; }}\n"
    out += f"        pin({clear_pin}) {{ direction: input; capacitance: 1.0; }}\n"
    for outpin, func in (("Q", "IQ"), ("QB", "IQN")):
        out += f"        pin({outpin}) {{\n            direction: output; function: \"{func}\";\n"
        out += timing_block(set_pin, "non_unate", "0.15")
        out += timing_block(clear_pin, "non_unate", "0.15")
        out += "        }\n"
    out += "    }\n"
    return out


def muxdffrb_cell(name, area, rst_pin, rst_attr, active_low=True):
    """DFFRB with a MUX2(A,B,S) folded directly into its D input
    (design_notes.md 108.27/108.29): same ff() shape as ff_cell() below,
    but next_state is the MUX2 function of A/B/S instead of a bare D pin
    -- MUX2's own function string/timing_sense/delay (COMB_CELLS' MUX2
    entry) is reused here so this stays consistent if that entry ever
    changes. CK/RSTB timing arcs and clear polarity are exactly
    ff_cell()'s DFFRB entry (same physical DFFRB half of the compound
    cell); the mux select-to-output arc uses MUX2's own delay/sense."""
    mux_func = "(S*B)+(S'*A)"
    mux_sense = "non_unate"
    mux_delay = "0.2"
    rst_expr = f"!{rst_pin}" if active_low else rst_pin
    out = f"    cell({name}) {{\n        area: {area};\n"
    out += "        ff(IQ, IQN) {\n"
    out += "            clocked_on : \"CK\";\n"
    out += f"            next_state : \"{mux_func}\";\n"
    out += f"            {rst_attr:8s} : \"{rst_expr}\";\n"
    out += "        }\n"
    out += "        pin(CK)  { direction: input; clock: true; capacitance: 1.0; }\n"
    for p in ("A", "B", "S"):
        out += f"        pin({p})   {{ direction: input; capacitance: 1.0; }}\n"
    out += f"        pin({rst_pin}) {{ direction: input; capacitance: 1.0; }}\n"
    for outpin, func in (("Q", "IQ"), ("QB", "IQN")):
        out += f"        pin({outpin}) {{\n            direction: output; function: \"{func}\";\n"
        out += timing_block("CK", "non_unate", "0.25")
        out += timing_block(rst_pin, "non_unate", "0.2")
        for mux_pin in ("A", "B", "S"):
            out += timing_block(mux_pin, mux_sense, mux_delay)
        out += "        }\n"
    out += "    }\n"
    return out


def ff_cell(name, area, rst_pin, rst_attr, active_low=False):
    # active_low=True emits the Liberty "!pin" inversion syntax on the
    # clear/preset attribute (see design_notes.md: DFFR.RSTB was
    # SPICE/schematic-confirmed active-low; the "!" prefix is Liberty's
    # own inversion notation, not a separate pin). The pin() declaration
    # itself always uses the bare (uninverted) pin name -- only the
    # ff() attribute value carries the "!".
    rst_expr = f"!{rst_pin}" if active_low else rst_pin
    out = f"    cell({name}) {{\n        area: {area};\n"
    out += "        ff(IQ, IQN) {\n"
    out += "            clocked_on : \"CK\";\n"
    out += "            next_state : \"D\";\n"
    out += f"            {rst_attr:8s} : \"{rst_expr}\";\n"
    out += "        }\n"
    out += "        pin(CK)  { direction: input; clock: true; capacitance: 1.0; }\n"
    out += "        pin(D)   { direction: input; capacitance: 1.0; }\n"
    out += f"        pin({rst_pin}) {{ direction: input; capacitance: 1.0; }}\n"
    for outpin, func in (("Q", "IQ"), ("QB", "IQN")):
        out += f"        pin({outpin}) {{\n            direction: output; function: \"{func}\";\n"
        out += timing_block("CK", "non_unate", "0.25")
        out += timing_block(rst_pin, "non_unate", "0.2")
        out += "        }\n"
    out += "    }\n"
    return out

# ---------------------------------------------------------------------
# Combinational cells: (name, area, input pins, boolean function, timing_sense, delay)
# Delay scales roughly with input count / drive strength -- placeholder only.
# ---------------------------------------------------------------------
COMB_CELLS = [
    ("INV_X1",  1,   ["A"],           "A'",                 "negative_unate", "0.06"),
    ("BUF_X1",  1.5, ["A"],           "A",                  "positive_unate", "0.08"),
    # BUFTH: hysteresis (Schmitt-trigger) buffer, added directly in
    # TR-1um_STDCELL.gds this session. Same A->Y function as BUF_X1 but
    # physically 2x wider (32.4um vs 16.2um, see LEF/gen_lef.py PIN_META
    # comment) for the extra hysteresis transistors -- area scaled 2x
    # from BUF_X1 to match. Delay bumped slightly above BUF_X1 as a
    # placeholder only (no real characterization); not switching-
    # threshold-aware since this whole library is a fixed-delay NLDM
    # stand-in for ABC's parser, not real STA data.
    ("BUFTH",   3,   ["A"],           "A",                  "positive_unate", "0.1"),
    ("AND2_X1", 2,   ["A", "B"],      "(A*B)",              "positive_unate", "0.12"),
    ("AND3_X1", 3,   ["A", "B", "C"], "(A*B*C)",            "positive_unate", "0.16"),
    ("AND4_X1", 4,   ["A", "B", "C", "D"], "(A*B*C*D)",     "positive_unate", "0.2"),
    ("OR2",     2,   ["A", "B"],      "(A+B)",              "positive_unate", "0.12"),
    ("OR3",     3,   ["A", "B", "C"], "(A+B+C)",            "positive_unate", "0.16"),
    ("OR4",     4,   ["A", "B", "C", "D"], "(A+B+C+D)",     "positive_unate", "0.2"),
    ("NAND2",   1.5, ["A", "B"],      "(A*B)'",             "negative_unate", "0.1"),
    ("NAND3",   2.5, ["A", "B", "C"], "(A*B*C)'",           "negative_unate", "0.14"),
    ("NAND4",   3.5, ["A", "B", "C", "D"], "(A*B*C*D)'",    "negative_unate", "0.18"),
    ("NOR2",    1.5, ["A", "B"],      "(A+B)'",             "negative_unate", "0.1"),
    ("NOR3",    2.5, ["A", "B", "C"], "(A+B+C)'",           "negative_unate", "0.14"),
    ("NOR4",    3.5, ["A", "B", "C", "D"], "(A+B+C+D)'",    "negative_unate", "0.18"),
    ("XOR2",    3,   ["A", "B"],      "(A^B)",              "non_unate",      "0.18"),
    ("XNOR2",   3,   ["A", "B"],      "(A^B)'",             "non_unate",      "0.18"),
    ("MUX2",    3,   ["A", "B", "S"], "(S*B)+(S'*A)",       "non_unate",      "0.2"),
    ("DEL1",    2,   ["A"],           "A",                  "positive_unate", "0.4"),
    ("DEL2",    3,   ["A"],           "A",                  "positive_unate", "0.8"),
    ("DEL4",    5,   ["A"],           "A",                  "positive_unate", "1.6"),
]

# DFFR.RSTB confirmed active-low from the real schematic/SPICE trace (see
# design_notes.md) -- active_low=True emits Liberty's "!RSTB" inversion.
# DFFS is a legacy/placeholder entry: no physical cell currently exists in
# TR-1um_STDCELL.gds (dropped from the remade library), kept here only so
# the generator doesn't error if it's reintroduced later; polarity unverified.
FF_CELLS = [
    ("DFFRB", 8, "RSTB", "clear",  True),
    ("DFFS", 8, "SET",  "preset", False),
]

# RSLATCH (design_notes.md 108.27/108.29/108.41): cross-coupled NOR2 SR
# latch, added by the user as a dedicated STDCELL. Area 3 = 2x NOR2's
# own 1.5 (RSLATCH really is 2 NOR2 gates cross-coupled -- confirmed via
# LVS-extracted transistor count, 108.41: 8 transistors = 2x NOR2's 4).
LATCH_CELLS = [
    ("RSLATCH", 3, "S", "R"),
]

# MUXDFFRB (design_notes.md 108.27/108.29/108.41): DFFRB with a
# MUX2(A,B,S) folded into its D input. Area 11 = DFFRB's 8 + MUX2's 3
# (confirmed via LVS-extracted transistor count, 108.41: 38 transistors
# vs a standalone DFFRB+MUX2's combined transistor count in the same
# ballpark). Same RSTB polarity as DFFRB (same physical DFFRB half).
MUXFF_CELLS = [
    ("MUXDFFRB", 11, "RSTB", "clear", True),
]


def main():
    out = HEADER
    for name, area, in_pins, func, sense, delay in COMB_CELLS:
        out += comb_cell(name, area, in_pins, func, sense, delay)
    for name, area, rst_pin, rst_attr, active_low in FF_CELLS:
        out += ff_cell(name, area, rst_pin, rst_attr, active_low)
    for name, area, set_pin, clear_pin in LATCH_CELLS:
        out += latch_cell(name, area, set_pin, clear_pin)
    for name, area, rst_pin, rst_attr, active_low in MUXFF_CELLS:
        out += muxdffrb_cell(name, area, rst_pin, rst_attr, active_low)
    out += "}\n"
    print(out, end="")

if __name__ == "__main__":
    main()
