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

def ff_cell(name, area, rst_pin, rst_attr):
    out = f"    cell({name}) {{\n        area: {area};\n"
    out += "        ff(IQ, IQN) {\n"
    out += "            clocked_on : \"CK\";\n"
    out += "            next_state : \"D\";\n"
    out += f"            {rst_attr:8s} : \"{rst_pin}\";\n"
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

FF_CELLS = [
    ("DFFR", 8, "RST", "clear"),
    ("DFFS", 8, "SET", "preset"),
]

def main():
    out = HEADER
    for name, area, in_pins, func, sense, delay in COMB_CELLS:
        out += comb_cell(name, area, in_pins, func, sense, delay)
    for name, area, rst_pin, rst_attr in FF_CELLS:
        out += ff_cell(name, area, rst_pin, rst_attr)
    out += "}\n"
    print(out, end="")

if __name__ == "__main__":
    main()
