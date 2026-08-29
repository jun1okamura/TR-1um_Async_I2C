#!/usr/bin/env python3
"""
build_tr1um_prm.py -- assembles irsim/TR-1um.prm from (a) the real TR-1um
BSIM3 model file's own parameters (tox, cj -- no simulation needed) and
(b) the ngspice characterization runs produced by gen_prm_characterize.py
(prm_char_L1.raw / prm_char_L2.raw, run locally with ngspice -- this
environment cannot run ngspice itself). Run this AFTER both ngspice runs
have completed and their .raw files exist in irsim/.

--- Resistance table (from ngspice) ---

Ports IRSIM's own findr.c (lib/calibrate_spice3/findr.c in the irsim
source tree, https://github.com/RTimothyEdwards/irsim -- fetched and read
directly this session) to Python, reading ngspice's ASCII rawfile format
instead of spice3's (the two are compatible: same Title/Plotname/
"No. Variables"/"No. Points"/Variables:/Values: structure). Computes the
exact same "resistance <type> <context> <w> <l> <ohms>" table entries
IRSIM's own official calibration procedure defines -- see
gen_prm_characterize.py's docstring for the full measurement methodology
and design_notes.md for the derivation/citations.

--- Capacitance parameters (from the model file directly) ---

capga (mosfet gate capacitance per unit area): per IRSIM's own
lib/calibrate_spice3/README, "capga = Cox / Tox" where
Cox = epsilon_0 * epsilon_SiO2 = 8.85e-12 F/m * 3.9. Computed directly
from the real model's tox parameter (models_IP62_mos_v2.lib: tox=1.95e-8m
for BOTH PMOS_mst and NMOS_mst in this process -- IRSIM's .prm format only
has one shared capga field anyway, per the same README: "there should
really be a capnga & cappga for n and p fets, but this is not a severe
problem yet").

capda / cappda (n-diffusion / p-diffusion junction capacitance per unit
area): taken directly from the model's own cj parameter (NMOS_mst's cj
for capda, PMOS_mst's cj for cappda) -- F/m^2 and pF/um^2 are numerically
identical units (1e-12 cancels against 1e-12), so no conversion factor is
needed beyond a straight copy.

capdp / cappdp (perimeter/sidewall junction capacitance): the trimmed
model dump available for this project does not include a cjsw parameter,
so these are left at 0 -- an explicitly-flagged approximation (area-only
diffusion capacitance, no sidewall correction). See the printed warning
and design_notes.md.

diffext (assumed source/drain diffusion extension width, enables IRSIM's
TDIFFCAP mechanism so per-transistor diffusion capacitance is added even
though this project's plain MIT-format .sim carries no explicit AS/AD/PS/
PD area annotations -- confirmed by reading irsim's own base/sim.c and
base/config.c source this session): reused directly from the real model
file's own sdwidth=2.8u parameter (models_IP62_mos_v2.lib) -- this is
literally the same physical quantity the model's own AS/AD='w*sdwidth'
formula already assumes, so it is not an arbitrary guess.

lambda: 1.0 -- this project's .sim already uses real-micron L/W values
1:1 (confirmed via the "lambda:1.00u" IRSIM startup message on every real
run this session), so the .prm's lambda must match.

lowthresh/highthresh: kept at IRSIM's own built-in defaults (0.3/0.8,
see irsim source base/config.c) -- no TR-1um-specific data available to
justify a different choice.
"""
import pathlib
import re
import sys

IRSIM_DIR = pathlib.Path(__file__).resolve().parent.parent / "irsim"
MODEL_FILE = pathlib.Path.home() / "Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/models_IP62_mos_v2.lib"

# Must match gen_prm_characterize.py
PWIDTH = 10.2
NWIDTH = 3.4
CAP_FF = 1000
L_POINTS = [1.0, 2.0]

EPS0 = 8.854e-12  # F/m
EPS_SIO2 = 3.9


# ---------------------------------------------------------------------
# Part 1: capacitance parameters, straight from the real model file
# ---------------------------------------------------------------------

def extract_model_block(text, model_name):
    """Return the text of a `.model <model_name> ...` block (up to the
    next .model/.subckt or a blank line following '+'-continuation)."""
    m = re.search(rf"\.model\s+{re.escape(model_name)}\b", text, re.IGNORECASE)
    if not m:
        raise ValueError(f"'.model {model_name}' not found in {MODEL_FILE}")
    start = m.start()
    # block ends at the next blank line (after continuation lines stop)
    rest = text[start:]
    lines = rest.splitlines()
    block_lines = [lines[0]]
    for line in lines[1:]:
        if line.strip() == "" and len(block_lines) > 1:
            break
        block_lines.append(line)
    return "\n".join(block_lines)


def extract_param(block, name):
    m = re.search(rf"\b{name}\s*=\s*'?([-+0-9.eE]+)", block)
    if not m:
        raise ValueError(f"parameter '{name}' not found in model block")
    return float(m.group(1))


def compute_cap_params():
    if not MODEL_FILE.exists():
        raise SystemExit(
            f"real model file not found: {MODEL_FILE}\n"
            "(needs the ~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/ "
            "folder connected)"
        )
    text = MODEL_FILE.read_text()

    pmos_block = extract_model_block(text, "PMOS_mst")
    nmos_block = extract_model_block(text, "NMOS_mst")

    tox_p = extract_param(pmos_block, "tox")
    tox_n = extract_param(nmos_block, "tox")
    cj_p = extract_param(pmos_block, "cj")
    cj_n = extract_param(nmos_block, "cj")

    if tox_p != tox_n:
        print(f"NOTE: PMOS tox ({tox_p}) != NMOS tox ({tox_n}); "
              f"using NMOS tox for the single shared capga field.",
              file=sys.stderr)
    tox = tox_n

    tox_um = tox * 1e6
    cox_pf_per_um = EPS0 * EPS_SIO2 * 1e6  # pF/um (permittivity, per README's own formula shape)
    capga = cox_pf_per_um / tox_um  # pF/um^2

    # F/m^2 and pF/um^2 are numerically identical (1e-12 / 1e-12 cancels)
    capda = cj_n     # n-diffusion (NMOS) junction cap, pF/um^2
    cappda = cj_p     # p-diffusion (PMOS) junction cap, pF/um^2

    return {
        "capga": capga,
        "capda": capda,
        "cappda": cappda,
        "tox": tox,
        "cj_n": cj_n,
        "cj_p": cj_p,
    }


# ---------------------------------------------------------------------
# Part 2: resistance table, from ngspice's ASCII rawfile output
# (port of irsim/lib/calibrate_spice3/findr.c)
# ---------------------------------------------------------------------

def read_ascii_raw(path):
    """Parse an ngspice ASCII rawfile. Real ngspice output (confirmed on a
    real run this session) does NOT reliably put exactly one value per
    line in the Values: section -- e.g. the point-index and the first
    value (time) share a line ("0 0.000...e+00"), but line-wrapping
    beyond that point is not something to rely on. So instead of trusting
    line boundaries, the whole Values: section is tokenized by
    whitespace and consumed as a flat stream: each point is
    [index, val_0, val_1, ..., val_(nvars-1)]."""
    with open(path) as f:
        lines = f.readlines()

    i = 0
    nvars = npoints = None
    while i < len(lines):
        line = lines[i]
        if line.startswith("No. Variables:"):
            nvars = int(line.split(":")[1])
        elif line.startswith("No. Points:"):
            npoints = int(line.split(":")[1])
        elif line.startswith("Variables:"):
            i += 1
            break
        i += 1
    if nvars is None or npoints is None:
        raise ValueError(f"{path}: couldn't find No. Variables / No. Points header "
                          "-- is this really an ngspice ASCII rawfile?")

    names = []
    for _ in range(nvars):
        parts = lines[i].split()
        names.append(parts[1].lower())
        i += 1

    if not lines[i].startswith("Values:"):
        raise ValueError(f"{path}: expected 'Values:' at line {i + 1}, got: {lines[i]!r}")
    i += 1

    tokens = "".join(lines[i:]).split()
    expected = npoints * (nvars + 1)  # +1 for the point-index token
    if len(tokens) != expected:
        raise ValueError(
            f"{path}: expected {expected} tokens in Values: section "
            f"({npoints} points x ({nvars} vars + 1 index)), got {len(tokens)}"
        )

    data = {name: [0.0] * npoints for name in names}
    tok_i = 0
    for p in range(npoints):
        tok_i += 1  # skip point-index token
        for v in range(nvars):
            data[names[v]][p] = float(tokens[tok_i])
            tok_i += 1
    return data


def find_transition(t, v, vdd, direction):
    mid = vdd / 2.0
    if direction == "lh":
        for i in range(1, len(v)):
            if v[i - 1] < mid <= v[i]:
                return t[i - 1] + (mid - v[i - 1]) * (t[i] - t[i - 1]) / (v[i] - v[i - 1])
    else:
        for i in range(1, len(v)):
            if v[i - 1] > mid >= v[i]:
                return t[i - 1] + (mid - v[i - 1]) * (t[i] - t[i - 1]) / (v[i] - v[i - 1])
    raise ValueError(f"no {direction} transition found (vdd={vdd})")


def resistances_for_l(rawfile, pw, nw, length, cap_ff):
    data = read_ascii_raw(rawfile)
    t = data["time"]
    vdd = max(data["v(vdd)"])

    in1_lh = find_transition(t, data["v(in1)"], vdd, "lh")
    in1_hl = find_transition(t, data["v(in1)"], vdd, "hl")
    in2_lh = find_transition(t, data["v(in2)"], vdd, "lh")
    in3_hl = find_transition(t, data["v(in3)"], vdd, "hl")
    out1_lh = find_transition(t, data["v(out1)"], vdd, "lh")
    out1_hl = find_transition(t, data["v(out1)"], vdd, "hl")
    out2_lh = find_transition(t, data["v(out2)"], vdd, "lh")
    out2_hl = find_transition(t, data["v(out2)"], vdd, "hl")
    out3_lh = find_transition(t, data["v(out3)"], vdd, "lh")
    out4_hl = find_transition(t, data["v(out4)"], vdd, "hl")

    cap = cap_ff * 1e-15  # F

    out1_tphl = out1_hl - in1_lh
    out1_tplh = out1_lh - in1_hl
    out2_tphl = out2_hl - out1_lh
    out2_tplh = out2_lh - out1_hl
    out3_tplh = out3_lh - in2_lh
    out4_tphl = out4_hl - in3_hl

    n_dynhigh = out3_tplh / cap
    n_dynlow = out1_tphl / cap
    n_static = (out2_tphl ** 2 - out1_tphl ** 2) / (out1_tplh * cap)

    p_dynhigh = out1_tplh / cap
    p_dynlow = out4_tphl / cap
    p_static = (out2_tplh ** 2 - out1_tplh ** 2) / (out1_tphl * cap)

    return {
        "n-channel": {"dynamic-high": n_dynhigh, "dynamic-low": n_dynlow, "static": n_static,
                      "w": nw, "l": length},
        "p-channel": {"dynamic-high": p_dynhigh, "dynamic-low": p_dynlow, "static": p_static,
                      "w": pw, "l": length},
    }


# ---------------------------------------------------------------------
# Part 3: assemble irsim/TR-1um.prm
# ---------------------------------------------------------------------

def main():
    print("Reading real TR-1um model parameters (tox, cj) ...")
    cap = compute_cap_params()
    print(f"  tox={cap['tox']:g} m  ->  capga={cap['capga']:.6f} pF/um^2")
    print(f"  NMOS cj={cap['cj_n']:g}  ->  capda={cap['capda']:.6f} pF/um^2")
    print(f"  PMOS cj={cap['cj_p']:g}  ->  cappda={cap['cappda']:.6f} pF/um^2")
    print("  (capdp/cappdp left at 0 -- no cjsw in the available model dump; "
          "diffusion sidewall cap is not modeled, area-only via diffext.)")

    print()
    print("Parsing ngspice characterization runs ...")
    entries = []
    for L in L_POINTS:
        rawfile = IRSIM_DIR / f"prm_char_L{L:g}.raw"
        if not rawfile.exists():
            raise SystemExit(
                f"missing {rawfile} -- run ngspice locally first:\n"
                f"  cd irsim && ngspice -b prm_char_L{L:g}.spi"
            )
        r = resistances_for_l(rawfile, PWIDTH, NWIDTH, L, CAP_FF)
        entries.append(r)
        print(f"  L={L:g}u: n-channel static={r['n-channel']['static']:.0f} ohm, "
              f"p-channel static={r['p-channel']['static']:.0f} ohm")

    lines = []
    lines.append("; TR-1um.prm -- generated by script/build_tr1um_prm.py")
    lines.append("; DO NOT hand-edit -- regenerate instead (script/gen_prm_characterize.py")
    lines.append("; + ngspice locally + script/build_tr1um_prm.py). See design_notes.md")
    lines.append("; and irsim/README.md for the full derivation/methodology.")
    lines.append(";")
    lines.append("; Resistance table from ngspice characterization of the REAL TR-1um")
    lines.append("; PMOS/NMOS models (~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/")
    lines.append("; ip62_models, vdd=5.0V, per IRSIM's own official calibration procedure).")
    lines.append("; Capacitance parameters (capga/capda/cappda) computed directly from the")
    lines.append("; same real model file's tox/cj parameters (no simulation needed).")
    lines.append("")
    lines.append("lambda 1.0")
    lines.append("")
    lines.append(f"capga {cap['capga']:.6f}")
    lines.append(f"capda {cap['capda']:.6f}")
    lines.append("capdp 0.0")
    lines.append(f"cappda {cap['cappda']:.6f}")
    lines.append("cappdp 0.0")
    lines.append("; interconnect-layer caps not modeled by this flow (this project's .sim")
    lines.append("; carries no wire/layer geometry -- see design_notes.md); set to 0.")
    lines.append("capm2a 0.0")
    lines.append("capm2p 0.0")
    lines.append("capma 0.0")
    lines.append("capmp 0.0")
    lines.append("cappa 0.0")
    lines.append("cappp 0.0")
    lines.append("")
    lines.append("; diffusion extension: enables IRSIM's TDIFFCAP mechanism so per-")
    lines.append("; transistor S/D diffusion cap is added even without explicit AS/AD in")
    lines.append("; the .sim. Reused directly from the real model's own sdwidth=2.8u")
    lines.append("; (models_IP62_mos_v2.lib) -- the same physical quantity its own AS/AD")
    lines.append("; formula already assumes, not an arbitrary guess.")
    lines.append("diffext 2.8")
    lines.append("")
    lines.append("lowthresh 0.3")
    lines.append("highthresh 0.8")
    lines.append("")
    for r in entries:
        for ttype in ("n-channel", "p-channel"):
            d = r[ttype]
            for ctx in ("dynamic-high", "dynamic-low", "static"):
                lines.append(f"resistance {ttype}\t{ctx}\t{d['w']:.2f}\t{d['l']:.2f}\t"
                              f"{round(d[ctx])}.0")
        lines.append("")

    out_path = IRSIM_DIR / "TR-1um.prm"
    out_path.write_text("\n".join(lines) + "\n")
    print()
    print(f"wrote {out_path}")
    print()
    print("Try it: irsim TR-1um.prm tr_1um_i2c_slave_async.sim")


if __name__ == "__main__":
    main()
