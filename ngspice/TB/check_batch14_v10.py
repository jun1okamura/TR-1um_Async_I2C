#!/usr/bin/env python3
"""
check_batch14_v10.py (V10 counterpart of check_batch14.py)

Companion checker for tb_chip_i2c_batch14_v10.spice (script/gen_chip_tb_
batch14_v10.py). Parses ngspice's own ".measure tran <name> ... " batch-mode
output (lines of the form "name = value", one per .measure statement) out
of a captured ngspice log, applies the pass/fail criteria recorded in
spice_batch14_v10_expected.json (written alongside the .spice file by the
same generator run), and prints a PASS/FAIL summary in the same
"[t=...] OK/FAIL: <description>" format as check_batch14.py's own (V9)
checker and irsim/run_tb.sh's checker -- for a final, apples-to-apples
cross-check against IRSIM/Verilog/V9-SPICE, all already 14/14 PASS.

Logic is identical to check_batch14.py -- only the expected-JSON filename
differs (spice_batch14_v10_expected.json instead of spice_batch14_
expected.json), so this file's own results never collide with the V9
checker's.

Usage:
    cd ngspice/TB
    ngspice -b tb_chip_i2c_batch14_v10.spice > spice_batch14_v10.log 2>&1
    python3 check_batch14_v10.py spice_batch14_v10.log
"""
import json
import re
import sys
from pathlib import Path

VDD = 5.0
THRESH = VDD / 2

# ngspice batch .measure output is a plain "name = value" line (scientific
# notation), possibly with surrounding whitespace; a measure that could not
# be evaluated instead prints "name = failed" (no value) -- treated as an
# error for that check rather than crashing the whole parse.
MEASURE_RE = re.compile(r"^\s*(\S+)\s*=\s*(\S+)\s*$")


def parse_measures(log_text):
    values = {}
    for line in log_text.splitlines():
        m = MEASURE_RE.match(line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        try:
            values[name] = float(raw)
        except ValueError:
            values[name] = None   # "failed" or other non-numeric result
    return values


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <ngspice_log_file>")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    expected_path = Path(__file__).parent / "spice_batch14_v10_expected.json"

    values = parse_measures(log_path.read_text())
    checks = json.loads(expected_path.read_text())

    n_pass = 0
    n_fail = 0
    for c in checks:
        name = c["name"]
        desc = c["desc"]
        t_report = c["t"] if c["kind"] == "level" else (
            c["t"][0] if isinstance(c["t"], list) else c["t"]
        )

        if c["kind"] == "level":
            v = values.get(name)
            if v is None:
                ok = False
                detail = "measure not found / failed"
            else:
                is_high = v > THRESH
                expect_high = (c["expect"] == "high")
                ok = (is_high == expect_high)
                detail = f"{v:.3f}V"
        else:   # byte
            bits = [None] * 8
            missing = False
            for i, bit_idx in enumerate(c["bit_indices"]):
                v = values.get(f"{name}_bit{i}")
                if v is None:
                    missing = True
                    continue
                bits[bit_idx] = 1 if v > THRESH else 0
            if missing or any(b is None for b in bits):
                ok = False
                detail = "one or more bit measures not found / failed"
            else:
                got = 0
                for i, bit in enumerate(bits):
                    got |= (bit << i)
                ok = (got == c["expect"])
                detail = f"got 0x{got:02X}, expected 0x{c['expect']:02X}"

        status = "OK" if ok else "FAIL"
        if ok:
            n_pass += 1
        else:
            n_fail += 1
        print(f"[t={t_report * 1e9:.0f}ns] {status}: {desc:<55s} ({detail})")

    print()
    print("---- RESULT ----")
    if n_fail == 0:
        print(f"All {n_pass} checks PASSED")
    else:
        print(f"{n_pass} passed, {n_fail} FAILED")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
