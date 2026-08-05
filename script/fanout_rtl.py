"""
fanout_rtl.py

RTL-level fanout estimate for src/i2c_slave_async.v: for each signal (module
port or internal wire/reg), count how many places it is READ (used as an
input to something -- an instance pin, the RHS of an assign/nonblocking
assignment, an if/case condition, or an always-block sensitivity list entry)
within this module. This is a proxy for what its physical net fanout will
look like once synthesized (each read site becomes a gate input pin the net
must drive), NOT the actual gate-level fanout (which depends on synthesis
choices) -- see design_notes.md for the caveat.

Handles:
  - assign LHS = RHS;            -> RHS reads, LHS is a drive (not a read)
  - reg <= expr;  (nonblocking)  -> expr reads, reg is a drive
  - if (cond) / else if (cond)   -> cond reads
  - case (expr) ... endcase      -> expr is a read; case ITEM labels
                                     (PH_ADDR: etc.) are localparams, skipped
  - always @(posedge/negedge SIG or ...) -> each SIG is a read (it's a real
    clock/reset load on that net)
  - structural instances TYPE NAME (.PIN(expr), ...); -> expr is a read only
    if PIN's direction (from the cell's .sym) is "in"; a write/drive if "out"
    (inout, i.e. VDD/GND, is not counted as a logic fanout).

Bus signals (tx_data, rx_data, phase, bit_cnt, shreg, txreg) are counted as
a single whole-bus identifier, matching how they appear in the RTL (no
per-bit slicing is done in this module except shreg_next[6:0] etc., which
still count as a read of `shreg`/`shreg_next` as a whole).
"""
import re
import os

RTL_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async.v"
STDLIB_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"


def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins


def strip_comments(src):
    src = re.sub(r'//.*', '', src)
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return src


def main():
    celltypes = [f[:-4] for f in os.listdir(STDLIB_DIR) if f.endswith(".sym")]
    sym_pins = {ct: parse_sym(os.path.join(STDLIB_DIR, ct + ".sym")) for ct in celltypes}

    src = strip_comments(open(RTL_FILE).read())

    # ---- declared signals ----
    ports = {}  # name -> direction (input/output/inout)
    for m in re.finditer(r'^\s*(input|output|inout)\s+wire\s*(\[\d+:\d+\])?\s*(\w+)\s*[,;)]', src, re.M):
        d, _w, name = m.groups()
        ports[name] = d

    internal = set()
    for m in re.finditer(r'^\s*(wire|reg)\s*(\[\d+:\d+\])?\s*(\w+)\s*(=[^;]*)?;', src, re.M):
        _kind, _w, name, _init = m.groups()
        internal.add(name)
    # 'wire X = expr;' inline (e.g. shreg_next) is both a declaration AND a
    # drive; the RHS of that inline expr is itself a set of reads.
    for m in re.finditer(r'^\s*wire\s*(\[\d+:\d+\])?\s*(\w+)\s*=\s*(.+?);', src, re.M):
        pass  # handled generically below via the assign-like scan

    all_signals = set(ports) | internal

    reads = {s: 0 for s in all_signals}

    def count_reads(expr):
        # `expr` is always just the RHS/condition text (the LHS is never
        # passed in), so every signal token found here is a genuine read --
        # including self-referencing updates like `bit_cnt <= bit_cnt + 1`,
        # which DO count (the net really does feed back into itself as a
        # load). No exclude-by-name filtering here on purpose.
        for tok in re.findall(r'[A-Za-z_]\w*', expr):
            if tok in all_signals:
                reads[tok] += 1

    # ---- assign statements (also covers inline 'wire X = expr;') ----
    for m in re.finditer(r'\bassign\s+(\w+)\s*=\s*(.+?);', src):
        _lhs, rhs = m.groups()
        count_reads(rhs)
    for m in re.finditer(r'^\s*wire\s*(?:\[\d+:\d+\])?\s*(\w+)\s*=\s*(.+?);', src, re.M):
        _lhs, rhs = m.groups()
        count_reads(rhs)

    # ---- always blocks: sensitivity list, if/case conditions, <= RHS ----
    for am in re.finditer(r'always\s*@\s*\((.*?)\)\s*begin(.*?)\n    end', src, re.S):
        sens, body = am.groups()
        # sensitivity list: 'posedge scl or posedge rst_scl_domain'
        for tok in re.findall(r'(?:posedge|negedge)\s+(\w+)', sens):
            if tok in all_signals:
                reads[tok] += 1
        # if (...) / else if (...)
        for cond in re.findall(r'if\s*\((.*?)\)', body):
            count_reads(cond)
        # case (...) -- expr only, not the item labels
        for cond in re.findall(r'case\s*\((.*?)\)', body):
            count_reads(cond)
        # nonblocking assigns: LHS <= RHS;  (only RHS is a read, even if
        # RHS re-mentions the same signal as LHS -- that's a real read)
        for _lhs, rhs in re.findall(r'(\w+(?:\s*\[[^\]]*\])?)\s*<=\s*(.+?);', body):
            count_reads(rhs)

    # ---- structural instances: TYPE NAME (.PIN(expr), ...); ----
    for m in re.finditer(r'\n\s*(\w+)\s+(\w+)\s*\(\s*(.*?)\)\s*;', src, re.S):
        typ, name, body = m.groups()
        if typ not in sym_pins:
            continue
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([^()]*?)\s*\)', body):
            pin, expr = pm.groups()
            direction = sym_pins[typ].get(pin)
            if direction == 'in':
                count_reads(expr)
            # 'out' pins are drives (not reads); 'inout' (VDD/GND) not counted.

    # ---- report ----
    print(f"{'signal':<18}{'dir/kind':<10}{'FO (internal reads)'}")
    print("-" * 45)
    for name in sorted(all_signals, key=lambda s: -reads[s]):
        kind = ports.get(name, "internal")
        print(f"{name:<18}{kind:<10}{reads[name]}")

    print()
    print("=== nets with FO >= 5 ===")
    for name in sorted(all_signals, key=lambda s: -reads[s]):
        if reads[name] >= 5:
            kind = ports.get(name, "internal")
            print(f"  {name:<18} FO={reads[name]:<3} ({kind})")


if __name__ == "__main__":
    main()
