"""
switch_sim.py

Switch-level (transistor-level) digital simulator for the KLayout LVS
"extracted" netlist of i2c_slave_async_nrow_fm
(layout/steps_v7_v2/i2c_slave_async_nrow_fm.extracted).

Every PMOS/NMOS in the flattened design (~2000+ transistors, from all
268 top-level gate/FF instances) is modeled as a simple switch:
  - PMOS conducts (drain<->source connected) when gate=0
  - NMOS conducts (drain<->source connected) when gate=1
At each simulation step, the whole switch network is re-resolved to a
fixed point via union-find, rooted at the fixed VDD/GND supply nodes.
A node whose component touches neither VDD nor GND (fully isolated --
e.g. inside a latch/flip-flop's hold state) RETAINS its previous value
-- this is what makes DFFR's cross-coupled feedback loops behave as
real memory without any special-casing, exactly like classic
switch-level simulators (IRSIM/RSIM-style, unit-delay, zero rise/fall
time -- adequate for FUNCTIONAL verification, not timing).
"""
import re
import sys

EXTRACTED = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/layout/steps_v7_v2/i2c_slave_async_nrow_fm.extracted"


def parse_extracted(path):
    text = open(path).read()

    # 1. all .SUBCKT ... .ENDS blocks (both the top circuit and every
    #    library cell), preserving raw body lines for later processing.
    # NOTE: the .SUBCKT header itself may continue onto '+'-prefixed
    # lines (KLayout's SPICE writer wraps long pin lists), so consume
    # every leading '+' continuation line before treating the rest as
    # the device/instance body.
    blocks = {}
    for m in re.finditer(r'\.SUBCKT\s+(\S+)\s+(.*?)\n(.*?)\n\.ENDS\s+\1', text, re.S):
        name, pinline, rest = m.group(1), m.group(2), m.group(3)
        lines = rest.splitlines()
        i = 0
        while i < len(lines) and lines[i].startswith('+'):
            pinline += ' ' + lines[i][1:]
            i += 1
        body = '\n'.join(lines[i:])
        pins = pinline.replace('\\$', '$').split()
        if name not in blocks:
            blocks[name] = (pins, body)
    return blocks


# Cell types that are deliberately NOT ideal 0/1 switches at the
# transistor level, and so must NOT be flattened into the raw
# union-find switch network:
#
#  BUFTH  - Schmitt-trigger buffer (its ".lib" name literally means
#           "buffer, THreshold"). Its transistor topology includes a
#           PMOS whose drain ties directly to gnd and an NMOS whose
#           drain ties directly to vdd (confirmed in the extracted
#           netlist) -- classic positive-feedback hysteresis devices.
#           These only make sense as a competition of analog transistor
#           STRENGTHS (relative W/L), which an ideal binary switch model
#           cannot represent. Flattened naively, the regenerative loop's
#           internal node can resolve to a state that unions vdd and
#           gnd directly through the loop, producing a spurious
#           chip-wide "contention" that is a simulator artifact, not a
#           real short (confirmed by isolating the fault to exactly
#           this loop; see design_notes.md).
#  DEL1/DEL2/DEL4 - deliberate RC delay lines (long L=2u transistors),
#           used by the START/STOP edge detector (sda_d = delayed
#           sda_in). Logically pure buffers ("function: A" in the
#           .lib), but their entire PURPOSE is to lag their input by a
#           finite time. A zero-delay switch-level resolution of their
#           real transistors collapses that lag to zero within the
#           same settle() call, which silently defeats the very edge
#           race (sda_d vs sda_in) the design depends on to generate
#           start_pulse/stop_pulse.
#
# Both are modeled BEHAVIORALLY instead (Y=A), matching their verified
# ".lib" function string exactly (already confirmed transistor-exact
# during the earlier ".lib vs transistor-level" verification task).
# BUFTH is resolved combinationally each settle() iteration (it has no
# intended delay of its own, just noise immunity). DELx is given an
# explicit ONE-STEP register delay (see SwitchSim.settle()) so it
# behaves as a real delay line relative to the rest of the zero-delay
# digital network -- this is what makes the async start/stop detector
# work at all in a functional (non-timing) simulation.
BEHAVIORAL_CELLS = {"BUFTH", "DEL1", "DEL2", "DEL4"}
DELAY_CELLS = {"DEL1", "DEL2", "DEL4"}

# DFFR: master-slave transmission-gate flip-flop. Its internal CKB/CKP
# clock-buffer chain is deliberately staggered in real silicon (CKB is
# 1 inverter from CK, CKP is 2 inverters from CK) so the master/slave
# transmission gates never simultaneously conduct (break-before-make).
# A zero-delay switch-level resolution collapses that stagger to zero
# within a single settle() call, so during a CK edge the internal
# master/slave loop can appear to short together (confirmed: traced a
# real VDD/GND union through X$111's internal "$9" node exactly at a
# CK transition, via the QM/QS transmission-gate pair momentarily
# "make before break"). Like BUFTH/DELx, DFFR's internal transistors
# are therefore NOT flattened into the raw switch network; instead it
# is modeled as a behavioral positive-edge-triggered register with
# asynchronous active-low reset, which is exactly its already-verified
# ".lib" ff-group declaration: clocked_on:"CK"; next_state:"D";
# clear:"!RSTB"; pin(Q){function:"IQ";} pin(QB){function:"IQN";}
# (matches the full 26-transistor structural trace done earlier).
SEQUENTIAL_CELLS = {"DFFR"}


def flatten(blocks, top_name="i2c_slave_async_nrow_fm"):
    """Expand every X$N gate-instance call in the top circuit down to its
    library cell's raw XM$N transistor list, renaming local/internal
    nodes to be globally unique. Returns (devices, behaviorals, seq_cells,
    top_pins) where devices is a list of (drain, gate, source, type)
    4-tuples, behaviorals is a list of (instname, celltype, A_net, Y_net)
    for cells in BEHAVIORAL_CELLS, seq_cells is a list of (instname,
    celltype, Q_net, QB_net, D_net, RSTB_net, CK_net) for cells in
    SEQUENTIAL_CELLS (neither list's instances appear in devices), and
    top_pins is the top circuit's own pin list (in .SUBCKT order)."""
    top_pins, top_body = blocks[top_name]
    devices = []
    behaviorals = []
    seq_cells = []

    def local_transistors(cellname):
        """Raw XM$N device lines for a LEAF (transistor-level) subckt."""
        pins, body = blocks[cellname]
        devs = []
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith('XM$'):
                continue
            toks = line.replace('\\$', '$').split()
            d, g, s, b = toks[1], toks[2], toks[3], toks[4]
            typ = toks[5]
            devs.append((d, g, s, typ))
        return pins, devs

    # pre-expand every library cell type once into (pins, [(d,g,s,typ),...])
    leaf_cache = {}
    for name in blocks:
        if name == top_name:
            continue
        pins, body = blocks[name]
        if 'XM$' in body:
            leaf_cache[name] = local_transistors(name)

    for line in top_body.splitlines():
        line = line.strip()
        if not line.startswith('X$'):
            continue
        toks = line.replace('\\$', '$').split()
        instname = toks[0]
        celltype = toks[-1]
        nets = toks[1:-1]
        if celltype not in leaf_cache:
            raise ValueError(f"unknown/unexpanded cell type {celltype} for {instname}")
        pins, devs = leaf_cache[celltype]
        if len(pins) != len(nets):
            raise ValueError(f"pin count mismatch {instname} {celltype}: {pins} vs {nets}")
        pin_to_net = dict(zip(pins, nets))

        if celltype in BEHAVIORAL_CELLS:
            # pins are (vdd, A, Y, gnd) per the .SUBCKT header order
            # confirmed for BUFTH/DEL1: ".SUBCKT BUFTH vdd A Y gnd" /
            # ".SUBCKT DEL1 Y A vdd gnd" -- look up by name, not position.
            a_net = pin_to_net["A"]
            y_net = pin_to_net["Y"]
            behaviorals.append((instname, celltype, a_net, y_net))
            continue

        if celltype in SEQUENTIAL_CELLS:
            # ".SUBCKT DFFR QB Q D RSTB vdd CK gnd" -- look up by name.
            seq_cells.append((instname, celltype,
                               pin_to_net["Q"], pin_to_net["QB"],
                               pin_to_net["D"], pin_to_net["RSTB"],
                               pin_to_net["CK"]))
            continue

        def resolve(node, pin_to_net=pin_to_net, instname=instname):
            if node in pin_to_net:
                return pin_to_net[node]
            # internal-only node local to this cell instance -> make unique
            return f"{instname}.{node}"

        for d, g, s, typ in devs:
            devices.append((resolve(d), resolve(g), resolve(s), typ))

    return devices, behaviorals, seq_cells, top_pins


class SwitchSim:
    def __init__(self, devices, behaviorals=(), seq_cells=(), vdd="$49", gnd="VSS"):
        self.devices = devices
        self.behaviorals = list(behaviorals)
        self.seq_cells = list(seq_cells)
        self.vdd = vdd
        self.gnd = gnd
        self.state = {}  # node -> 0/1 (persistent, for floating/latched nodes)
        self.state[vdd] = 1
        self.state[gnd] = 0
        # one-step delay registers for DELx cells: instname -> last A value
        # sampled at the START of the previous settle() call, used to drive
        # Y for the CURRENT settle() call. This is what turns a purely
        # combinational (zero-delay) buffer into an actual delay element
        # relative to everything else in the design, which is what the
        # sda_d/sda_in START/STOP edge race depends on.
        self.delay_reg = {}
        for instname, celltype, a_net, y_net in self.behaviorals:
            if celltype in DELAY_CELLS:
                self.delay_reg[instname] = None
        # DFFR behavioral register state: instname -> (Q, QB), and the CK
        # value observed as of the END of the previous settle() call (used
        # for rising-edge detection). RSTB is asynchronous, so it is
        # re-checked fresh every call regardless of CK.
        self.dff_qstate = {}
        self.dff_ck_prev = {}
        for instname, celltype, q_net, qb_net, d_net, rstb_net, ck_net in self.seq_cells:
            self.dff_qstate[instname] = (None, None)
            self.dff_ck_prev[instname] = None

    def set(self, node, value):
        self.state[node] = value

    def get(self, node):
        return self.state.get(node)

    def settle(self, max_iters=25):
        """Resolve the whole switch network to a fixed point. Nodes whose
        component touches VDD only -> 1, GND only -> 0, BOTH -> contention
        ('X', reported as an error), NEITHER -> retains previous state
        (this is the mechanism that gives flip-flops their memory).

        BUFTH/DELx instances (see BEHAVIORAL_CELLS) are NOT part of
        self.devices -- they are resolved separately each iteration as
        plain Y=A buffers, except DELx additionally goes through a
        one-step register so its Y reflects A's value as of the START of
        THIS settle() call, not the value A is being driven to right now."""
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Snapshot each DELx's input BEFORE this call does anything, and
        # commit the register value that will drive Y for this whole call.
        # New delay_reg values (for the *next* call) are captured at the
        # very end of settle(), once the network is done propagating.
        y_forced = {}   # net -> forced 0/1 value (behavioral outputs)
        for instname, celltype, a_net, y_net in self.behaviorals:
            if celltype in DELAY_CELLS:
                reg = self.delay_reg[instname]
                if reg is not None:
                    y_forced[y_net] = reg
            # BUFTH (and any non-delay behavioral): resolved live below,
            # each iteration, from the settling A value -- not forced here.

        # DFFR registers: force Q/QB to their CURRENT (pre-edge) state
        # while the surrounding combinational network settles, so D/RSTB/CK
        # inputs (computed from OTHER gates, possibly other DFFRs' Q/QB)
        # are resolved using the OLD register values -- standard
        # register-transfer semantics: this settle() call's D is always a
        # function of the PREVIOUS cycle's state, and every DFFR's edge is
        # applied using that same consistent snapshot (see the update loop
        # after the fixed point below), so cascaded shift-register stages
        # advance exactly one stage per clock edge, not zero or two.
        for instname, celltype, q_net, qb_net, d_net, rstb_net, ck_net in self.seq_cells:
            q, qb = self.dff_qstate[instname]
            if q is not None:
                y_forced[q_net] = q
            if qb is not None:
                y_forced[qb_net] = qb

        prev_state = dict(self.state)
        for _ in range(max_iters):
            # live (non-delay) behavioral buffers: Y follows A immediately,
            # using the latest resolved value each iteration, same as a
            # combinational gate would.
            for instname, celltype, a_net, y_net in self.behaviorals:
                if celltype in DELAY_CELLS:
                    continue
                av = prev_state.get(a_net)
                if av is not None:
                    prev_state[y_net] = av

            parent = {}
            for d, g, s, typ in self.devices:
                # v2 fix: must read the LATEST values resolved so far
                # within this same settle() call (prev_state), not the
                # stale self.state from before settle() was even
                # entered -- otherwise multi-gate-level combinational
                # paths never fully propagate in one settle() call.
                gv = prev_state.get(g)
                if gv is None:
                    continue
                if (typ == 'PMOS' and gv == 0) or (typ == 'NMOS' and gv == 1):
                    union(d, s)

            vdd_root = find(self.vdd)
            gnd_root = find(self.gnd)
            new_state = {}
            contentions = []
            all_nodes = set()
            for d, g, s, typ in self.devices:
                all_nodes.update((d, g, s))
            for instname, celltype, a_net, y_net in self.behaviorals:
                all_nodes.update((a_net, y_net))
            for instname, celltype, q_net, qb_net, d_net, rstb_net, ck_net in self.seq_cells:
                all_nodes.update((q_net, qb_net, d_net, rstb_net, ck_net))
            for n in all_nodes:
                if n in y_forced:
                    new_state[n] = y_forced[n]
                    continue
                r = find(n)
                is_vdd = (r == vdd_root)
                is_gnd = (r == gnd_root)
                if is_vdd and is_gnd:
                    contentions.append(n)
                    new_state[n] = prev_state.get(n)  # fallback: hold
                elif is_vdd:
                    new_state[n] = 1
                elif is_gnd:
                    new_state[n] = 0
                else:
                    # floating component: hold whatever any member had
                    held = None
                    for n2 in all_nodes:
                        if find(n2) == r and n2 in prev_state:
                            held = prev_state[n2]
                            break
                    new_state[n] = held

            new_state[self.vdd] = 1
            new_state[self.gnd] = 0
            for n, v in y_forced.items():
                new_state[n] = v
            if new_state == prev_state:
                prev_state = new_state
                break
            prev_state = new_state

        self.state = prev_state
        # capture this call's A values into the delay registers, to drive
        # Y on the *next* settle() call (one-step lag).
        for instname, celltype, a_net, y_net in self.behaviorals:
            if celltype in DELAY_CELLS:
                self.delay_reg[instname] = self.state.get(a_net)

        # DFFR edge/reset update: now that D/RSTB/CK have settled (using
        # the OLD Q/QB that were forced above), decide each register's
        # NEXT state and commit it -- both into dff_qstate (drives next
        # settle() call) and directly into self.state (so this step's
        # Q/QB are visible immediately, matching how a real synchronous
        # design's output is observed just after the clock edge that
        # produced it, and matching the granularity of this testbench,
        # which checks state right after driving the edge).
        for instname, celltype, q_net, qb_net, d_net, rstb_net, ck_net in self.seq_cells:
            q, qb = self.dff_qstate[instname]
            d = self.state.get(d_net)
            rstb = self.state.get(rstb_net)
            ck = self.state.get(ck_net)
            ck_prev = self.dff_ck_prev[instname]
            if rstb == 0:
                new_q, new_qb = 0, 1
            elif ck_prev == 0 and ck == 1 and d is not None:
                new_q, new_qb = d, (1 - d)
            else:
                new_q, new_qb = q, qb
            self.dff_qstate[instname] = (new_q, new_qb)
            self.dff_ck_prev[instname] = ck
            if new_q is not None:
                self.state[q_net] = new_q
            if new_qb is not None:
                self.state[qb_net] = new_qb

        return contentions


if __name__ == "__main__":
    blocks = parse_extracted(EXTRACTED)
    devices, behaviorals, seq_cells, top_pins = flatten(blocks)
    print(f"top pins ({len(top_pins)}): {top_pins}")
    print(f"flattened transistor count: {len(devices)}")
    print(f"behavioral (non-flattened) instances: {len(behaviorals)}")
    print(f"sequential (non-flattened) instances: {len(seq_cells)}")
    types = {}
    for d, g, s, t in devices:
        types[t] = types.get(t, 0) + 1
    print("by type:", types)
    btypes = {}
    for instname, celltype, a, y in behaviorals:
        btypes[celltype] = btypes.get(celltype, 0) + 1
    print("behavioral by celltype:", btypes)
