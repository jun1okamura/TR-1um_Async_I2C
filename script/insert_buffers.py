"""
insert_buffers.py

Inserts buffering into src/i2c_slave_async_net.v for the high-fanout nets
identified by script/fanout_net.py (design_notes.md section 18).

Revision: scl/sda_in were originally proposed as a 3-stage CHAIN
(BUF_X2->BUF_X8->BUF_X16), but a chain only ramps up drive strength at a
single point -- it doesn't reduce the physical fanout each single buffer
must reach across the placed floorplan (all sinks still land on the last
stage). Switched to SPLIT (matching _126_/_127_) so the wide physical
distribution of scl (a clock, driving DFFR.CK across all 4 rows) and
sda_in actually gets shared across independent drivers:

  scl     (FO=27, primary input, SCL-domain clock)       -> SPLIT into 2 branches, each BUF_X16
  sda_in  (FO=7,  primary input)                          -> SPLIT into 2 branches, each BUF_X2
  _126_   (FO=24, = rst_scl_domain driver, OR2 _435_.Y)   -> SPLIT into 2 branches, each BUF_X4
  _127_   (FO=9,  = rst_sdaoe_domain driver, NAND2 _432_.Y) -> SPLIT into 2 branches, each BUF_X2

"chain" = one sequential buffer chain; ALL of the net's original sinks are
redirected to the chain's FINAL output.

"split" = the net's sinks are divided into N balanced groups; each group
gets its OWN single buffer instance (reading directly from the original
net), redirected only to that group's sinks -- this is what actually
reduces each individual buffer's fanout (a chain does not: every sink still
ends up on the one last buffer in the chain).

All other FO>=5 nets (scl_n, _070_/_073_ mux-select, bit_cnt[0]/[1],
_046_/_055_/_058_) are left untouched per instruction.

Method: for each target net, resolve its canonical form and full sink list
(inst.pin) via the same Union-Find alias resolution used by
script/fanout_net.py, then for each sink, do a precise per-instance text
substitution (locate that exact instance's block, replace only that one
pin's connection) -- no blind global string replace.

Run: python3 script/insert_buffers.py
Writes src/i2c_slave_async_net.v in place (a .bak copy is kept alongside).
"""
import re
import os
import shutil

STDLIB_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"

CHAIN_PLAN = [
]
SPLIT_PLAN = [
    ("scl", "BUF_X16", 2, "scl_buf"),
    ("sda_in", "BUF_X2", 2, "sda_in_buf"),
    ("_126_", "BUF_X4", 2, "_126_buf"),
    ("_127_", "BUF_X2", 2, "_127_buf"),
]


def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins


def main():
    celltypes = [f[:-4] for f in os.listdir(STDLIB_DIR) if f.endswith(".sym")]
    sym_pins = {ct: parse_sym(os.path.join(STDLIB_DIR, ct + ".sym")) for ct in celltypes}

    src = open(NET_FILE).read()

    port_width, wire_width = {}, {}
    for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        kind, _, msb, lsb, name = m.groups()
        port_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
    for m in re.finditer(r'^\s*wire\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        _, msb, lsb, name = m.groups()
        wire_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
    width_of = {}
    width_of.update(wire_width)
    width_of.update(port_width)

    instances = []
    for m in re.finditer(r'\n\s*(\w+)\s+(\w+)\s*\(\s*(.*?)\)\s*;', src, re.S):
        typ, name, body = m.groups()
        if typ not in sym_pins:
            continue
        conns = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([^()]*?)\s*\)', body):
            pin, expr = pm.groups()
            conns[pin] = expr.strip()
        instances.append((typ, name, conns))

    assigns = []
    for m in re.finditer(r'assign\s+(.+?)\s*=\s*(.+?);', src):
        lhs, rhs = m.groups()
        if '{' in lhs or '{' in rhs or "'" in rhs:
            continue
        assigns.append((lhs.strip(), rhs.strip()))

    parent = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def expand(expr):
        m = re.match(r'^(\w+)\[(\d+)\]$', expr)
        if m:
            return [f"{m.group(1)}[{m.group(2)}]"]
        m = re.match(r'^(\w+)$', expr)
        if m:
            w = width_of.get(m.group(1), 1)
            return [f"{m.group(1)}[{i}]" for i in range(w)] if w > 1 else [m.group(1)]
        return None

    for lhs, rhs in assigns:
        lb, rb = expand(lhs), expand(rhs)
        if lb is None or rb is None or len(lb) != len(rb):
            continue
        for a, b in zip(lb, rb):
            union(a, b)

    def canon(expr):
        return find(expr)

    def get_sinks():
        sinks = {}
        for typ, name, conns in instances:
            for pin, expr in conns.items():
                d = sym_pins[typ].get(pin)
                if d != 'in':
                    continue
                net = canon(expr)
                sinks.setdefault(net, []).append((name, pin))
        return sinks

    sinks = get_sinks()

    def redirect(instname, pinname, new_net):
        nonlocal src
        block_re = re.compile(r'(\b' + re.escape(instname) + r'\s*\(.*?\)\s*;)', re.S)
        bm = block_re.search(src)
        assert bm, f"could not find instance block for {instname}"
        block = bm.group(1)
        pin_re = re.compile(r'(\.' + re.escape(pinname) + r'\s*\(\s*)([^()]*?)(\s*\))')
        new_block, n = pin_re.subn(lambda m2: m2.group(1) + new_net + m2.group(3), block, count=1)
        assert n == 1, f"could not redirect {instname}.{pinname}"
        src = src[:bm.start()] + new_block + src[bm.end():]

    inserted_blocks = []
    report = []

    # ---- chains ----
    for target_net, chain, new_base in CHAIN_PLAN:
        net = canon(target_net)
        sink_list = sinks.get(net, [])
        assert sink_list, f"net {target_net!r} has no sinks"
        final_net = new_base
        for instname, pinname in sink_list:
            redirect(instname, pinname, final_net)

        stage_in = target_net
        chain_text = []
        for i, celltype in enumerate(chain):
            stage_out = final_net if i == len(chain) - 1 else f"{new_base}_s{i}"
            iname = f"u_{new_base}_{i}"
            chain_text.append(
                f"  {celltype} {iname} (\n    .A({stage_in}),\n    .Y({stage_out}),\n"
                f"    .VDD(VDD),\n    .GND(GND)\n  );"
            )
            stage_in = stage_out
        inserted_blocks.append("\n".join(chain_text))

        new_wires = [f"{new_base}_s{i}" for i in range(len(chain) - 1)] + [final_net]
        decl = "\n".join(f"  wire {w};" for w in new_wires)
        first_inst_m = re.search(r'\n  \w+ \w+\s*\(', src)
        src = src[:first_inst_m.start()] + "\n" + decl + src[first_inst_m.start():]

        report.append((target_net, "chain", [(final_net, len(sink_list))]))
        print(f"{target_net}: chain {' -> '.join(chain)}, {len(sink_list)} sinks -> {final_net}")

    # ---- splits ----
    for target_net, celltype, n_branches, new_base in SPLIT_PLAN:
        net = canon(target_net)
        sink_list = sinks.get(net, [])
        assert sink_list, f"net {target_net!r} has no sinks"
        # balanced split, e.g. 9 sinks / 2 branches -> 5, 4
        groups = [[] for _ in range(n_branches)]
        for i, s in enumerate(sink_list):
            groups[i % n_branches].append(s)

        branch_nets = []
        branch_text = []
        for b, group in enumerate(groups):
            branch_net = f"{new_base}{b}"
            branch_nets.append((branch_net, len(group)))
            for instname, pinname in group:
                redirect(instname, pinname, branch_net)
            iname = f"u_{new_base}{b}"
            branch_text.append(
                f"  {celltype} {iname} (\n    .A({target_net}),\n    .Y({branch_net}),\n"
                f"    .VDD(VDD),\n    .GND(GND)\n  );"
            )
        inserted_blocks.append("\n".join(branch_text))

        decl = "\n".join(f"  wire {bn};" for bn, _ in branch_nets)
        first_inst_m = re.search(r'\n  \w+ \w+\s*\(', src)
        src = src[:first_inst_m.start()] + "\n" + decl + src[first_inst_m.start():]

        report.append((target_net, "split", branch_nets))
        print(f"{target_net}: split x{n_branches} {celltype}, "
              f"{len(sink_list)} sinks -> " + ", ".join(f"{bn}({c})" for bn, c in branch_nets))

    # ---- append all new instances just before 'endmodule' ----
    endmod_idx = src.rindex("endmodule")
    src = src[:endmod_idx] + "\n" + "\n\n".join(inserted_blocks) + "\n\n" + src[endmod_idx:]

    shutil.copy(NET_FILE, NET_FILE + ".bak")
    with open(NET_FILE, "w") as f:
        f.write(src)
    print(f"\nwrote {NET_FILE} (backup at {NET_FILE}.bak)")

    print("\n=== branch FO summary ===")
    for target_net, mode, branches in report:
        for bn, c in branches:
            print(f"  {bn:<14} FO={c}  (from {target_net}, {mode})")


if __name__ == "__main__":
    main()
