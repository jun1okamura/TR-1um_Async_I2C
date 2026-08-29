#!/usr/bin/env python3
"""
analyze_dffrb_reset_tb.py -- reads irsim/dffrb_reset_tb.raw (from
gen_dffrb_reset_tb.py's ngspice run) and reports V(qs)/V(qb)/V(q)/V(rstb)
at a series of time checkpoints, plus the exact moment (if any) QS
crosses a logic threshold. Reuses build_tr1um_prm.py's ASCII-rawfile
reader (same ngspice format, already confirmed working this session).

Run locally (after `ngspice -b dffrb_reset_tb.spi`):
    python3 script/analyze_dffrb_reset_tb.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_tr1um_prm import read_ascii_raw  # noqa: E402

RAWFILE = pathlib.Path(__file__).resolve().parent.parent / "irsim" / "dffrb_reset_tb.raw"
VDD = 5.0
CHECKPOINTS_S = [0, 50e-9, 100e-9, 101e-9, 150e-9, 200e-9, 500e-9,
                 1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 40e-6]


def nearest_index(t_list, target):
    best_i, best_d = 0, abs(t_list[0] - target)
    for i, t in enumerate(t_list):
        d = abs(t - target)
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def main():
    if not RAWFILE.exists():
        raise SystemExit(f"missing {RAWFILE} -- run ngspice locally first:\n"
                          "  cd irsim && ngspice -b dffrb_reset_tb.spi")
    data = read_ascii_raw(RAWFILE)
    print("available variables:", ", ".join(sorted(data.keys())))
    print()

    def pick(*candidates):
        for c in candidates:
            if c in data:
                return c
        return None

    t_name = "time"
    qs_name = pick("v(x1.qs)", "v(x1.qs#branch)", "v(qs)")
    qb_name = pick("v(qb)", "v(x1.qb)")
    q_name = pick("v(q)", "v(x1.q)")
    rstb_name = pick("v(rstb)")

    missing = [n for n, v in [("QS", qs_name), ("QB", qb_name), ("Q", q_name),
                               ("RSTB", rstb_name)] if v is None]
    if missing:
        print(f"WARNING: could not find variable(s) for {missing} -- check the "
              "'available variables' list above and adjust pick() candidates.")

    t = data[t_name]
    print(f"{'t (s)':>12}  {'RSTB':>7}  {'QS':>7}  {'QB':>7}  {'Q':>7}")
    for cp in CHECKPOINTS_S:
        i = nearest_index(t, cp)
        row = [f"{t[i]:12.4e}"]
        for name in (rstb_name, qs_name, qb_name, q_name):
            row.append(f"{data[name][i]:7.3f}" if name else "    n/a")
        print("  ".join(row))

    if qs_name:
        print()
        low, high = 0.3 * VDD, 0.7 * VDD  # generous "mid-rail crossing" band
        crossed_at = None
        was_low = data[qs_name][0] < VDD / 2
        for i in range(1, len(t)):
            now_low = data[qs_name][i] < VDD / 2
            if now_low != was_low:
                crossed_at = t[i]
                break
            was_low = now_low
        if crossed_at is None:
            print(f"QS never crossed Vdd/2 ({VDD/2}V) anywhere in the "
                  f"{t[-1]:.2e}s transient -- held its forced value the whole time.")
        else:
            print(f"QS crossed Vdd/2 ({VDD/2}V) at t={crossed_at:.4e}s "
                  f"({crossed_at*1e9:.1f}ns after t=0, "
                  f"{(crossed_at-101e-9)*1e9:.1f}ns after RSTB released).")


if __name__ == "__main__":
    main()
