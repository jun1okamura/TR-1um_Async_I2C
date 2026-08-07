"""
gen_err_report2.py

Generates a review copy of the latest routed GDS with THREE separate
non-fab ERR layers, for manual-fix triage:

  - (252,0) ERR_OPEN_PIN_LAYER: pins that are open but belong to a net
    that DOES have some connectivity elsewhere (i.e. the net is not
    totally dead -- just this pin's branch is missing).
  - (252,1) ERR_UNCONNECTED_NET_LAYER: pins belonging to a net with ZERO
    connectivity anywhere (every one of its pins is its own isolated
    M1 component -- no two pins of the net are joined at all).
  - (252,2) ERR_DEST_LAYER: for every open pin (both categories above),
    a marker + connecting line at the pin's "destination" -- the
    nearest OTHER pin of the same net it should be hooked up to
    (nearest already-connected pin for category 1; nearest sibling pin
    for category 2, since there is no connected group to reference).

Connectivity ground truth is derived directly from the routed GDS itself
(M1 shapes unioned via V1 vias to M2 shapes, same technique as
verify_channel_connectivity.py) over the FULL core height, not scanned
per-channel -- this makes the classification independent of which
channel/pass (channel router or route_multihop) touched a given pin.

Writes to a SEPARATE file so the main routed_all.gds stays untouched.

Usage:
    python3 gen_err_report2.py
"""
import os
import re
import sys
from collections import defaultdict

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402
from gen_gds_placement import PHYSICAL_ROWS  # noqa: E402
import route_channel as rc  # noqa: E402

ROW_HEIGHT = rc.ROW_HEIGHT
M1_LAYER = rc.M1_LAYER
V1_LAYER = rc.V1_LAYER
M2_LAYER = rc.M2_LAYER
GC_LAYER = rc.GC_LAYER
CO_LAYER = rc.CO_LAYER
PIN_TEXT_LAYER = rc.PIN_TEXT_LAYER
GC_KEEPOUT_UM = rc.GC_KEEPOUT_UM
CO_KEEPOUT_UM = rc.CO_KEEPOUT_UM
VIA_MARGIN_UM = rc.VIA_MARGIN_UM
DRC_GRID = rc.DRC_GRID
STDCELL_DIR = rc.STDCELL_DIR
GDS_LIB = rc.GDS_LIB
NET_FILE = rc.NET_FILE

IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_all.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_with_err2.gds"
ANNOT_LAYER = (250, 0)

ERR_OPEN_PIN_LAYER = (252, 0)
ERR_UNCONNECTED_NET_LAYER = (252, 1)
ERR_DEST_LAYER = (252, 2)


def _parse_nets():
    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: rc.parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

    src = open(NET_FILE).read()
    port_width = {}
    for m in re.finditer(r'^\s*(input|output|inout)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;', src, re.M):
        kind, _, msb, lsb, name = m.groups()
        port_width[name] = (int(msb) - int(lsb) + 1) if msb else 1
    wire_width = {}
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

    net_pins = defaultdict(list)
    inst_typ_all = {}
    for typ, name, conns in instances:
        inst_typ_all[name] = typ
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':
                continue
            net_pins[canon(expr)].append((name, typ, pin))
    return net_pins, sym_pins, inst_typ_all


def main():
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)
    phys_of_row = {}
    for i, e in enumerate(PHYSICAL_ROWS):
        if e is not None:
            phys_of_row[e] = i
    row_of = {}
    for i, row in enumerate(rows):
        for n, t, w in row:
            row_of[n] = i

    net_pins, sym_pins, inst_typ_all = _parse_nets()
    print(f"{len(net_pins)} nets total")

    # ---------- cell library: pin polygons + GC/CO forbidden regions ----------
    lib = db.Layout()
    lib.read(GDS_LIB)
    ldbu = lib.dbu
    lib_pin_text_idx = lib.layer(*PIN_TEXT_LAYER)
    lib_m1_idx = lib.layer(*M1_LAYER)
    lib_gc_idx = lib.layer(*GC_LAYER)
    lib_co_idx = lib.layer(*CO_LAYER)
    pr_layer_idx = lib.layer(*PR_LAYER)

    gc_cache, co_cache, pr_bbox_cache, pin_cache = {}, {}, {}, {}

    def cell_gc_forbidden(celltype):
        if celltype not in gc_cache:
            c = lib.cell(celltype)
            gc_region = db.Region(c.begin_shapes_rec(lib_gc_idx))
            gc_cache[celltype] = gc_region.sized(int(round(GC_KEEPOUT_UM / ldbu)))
        return gc_cache[celltype]

    def cell_co_forbidden(celltype):
        if celltype not in co_cache:
            c = lib.cell(celltype)
            co_region = db.Region(c.begin_shapes_rec(lib_co_idx))
            co_cache[celltype] = co_region.sized(int(round(CO_KEEPOUT_UM / ldbu)))
        return co_cache[celltype]

    def get_pr_bbox(celltype):
        if celltype not in pr_bbox_cache:
            c = lib.cell(celltype)
            pr_bbox_cache[celltype] = db.Region(c.begin_shapes_rec(pr_layer_idx)).bbox()
        return pr_bbox_cache[celltype]

    def get_cell_pin_data(celltype):
        c = lib.cell(celltype)
        if c is None:
            raise RuntimeError(f"cell {celltype} not in library")
        net_polys = list(db.Region(c.begin_shapes_rec(lib_m1_idx)).merged().each())
        pins = {}
        it = c.begin_shapes_rec(lib_pin_text_idx)
        while not it.at_end():
            s = it.shape()
            if s.is_text():
                tx, ty = s.text_dtrans.disp.x, s.text_dtrans.disp.y
                px, py = int(round(tx / ldbu)), int(round(ty / ldbu))
                cand = [p for p in net_polys
                        if p.bbox().left <= px <= p.bbox().right and p.bbox().bottom <= py <= p.bbox().top]
                best = min(cand, key=lambda p: p.bbox().area()) if cand else \
                    min(net_polys, key=lambda p: (p.bbox().center().x - px) ** 2 + (p.bbox().center().y - py) ** 2)
                pins[s.text_string.lower()] = best
            it.next()
        return pins

    def cell_pin_poly(celltype, pinname):
        if celltype not in pin_cache:
            pin_cache[celltype] = get_cell_pin_data(celltype)
        d = pin_cache[celltype]
        key = pinname.lower()
        if key not in d:
            raise RuntimeError(f"pin {pinname!r} not found for {celltype} (have {list(d)})")
        return d[key]

    # ---------- absolute instance origin for EVERY instance ----------
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell("i2c_slave_async_layout")
    annot_idx = layout.layer(*ANNOT_LAYER)
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)

    needed_insts = set()
    for net, pins in net_pins.items():
        for instname, typ, pinname in pins:
            needed_insts.add(instname)

    row_cx = {}
    it = top.begin_shapes_rec(annot_idx)
    while not it.at_end():
        s = it.shape()
        if s.is_text() and s.text_string in needed_insts:
            row_cx[s.text_string] = s.text_dtrans.disp.x
        it.next()
    missing = needed_insts - set(row_cx)
    if missing:
        print(f"WARNING: {len(missing)} instances missing annotation (skipped): {sorted(missing)[:5]}")

    inst_origin = {}
    for instname in needed_insts:
        if instname not in row_cx or instname not in row_of:
            continue
        logical_row_idx = row_of[instname]
        phys_row_index = phys_of_row[logical_row_idx]
        mirrored = (phys_row_index % 2 == 1)
        typ = inst_typ_all[instname]
        bbox = get_pr_bbox(typ)
        bleft, bbottom, btop = bbox.left * ldbu, bbox.bottom * ldbu, bbox.top * ldbu
        width = bbox.width() * ldbu
        cx = row_cx[instname]
        tx = cx - (bleft + width / 2.0)
        ty = (phys_row_index * ROW_HEIGHT - bbottom) if not mirrored else (phys_row_index * ROW_HEIGHT + btop)
        inst_origin[instname] = (tx, ty, mirrored, typ)

    def abs_pin_anchor(instname, pinname):
        if instname not in inst_origin:
            return None
        tx, ty, mirrored, typ = inst_origin[instname]
        try:
            poly = cell_pin_poly(typ, pinname)
        except RuntimeError:
            return None
        forbid = cell_gc_forbidden(typ) + cell_co_forbidden(typ)
        margin_ldbu = int(round(VIA_MARGIN_UM / ldbu))

        def safe_region(region):
            return region.sized(-margin_ldbu) - forbid

        base = db.Region(poly)
        eroded = safe_region(base)
        used = base
        if eroded.is_empty():
            for grow_um in (0.02, 0.05, 0.08, 0.12, 0.2, 0.3, 0.5, 0.8, 1.2):
                grown = base.sized(int(round(grow_um / ldbu)))
                eroded = safe_region(grown)
                if not eroded.is_empty():
                    used = grown
                    break
        bb = (eroded if not eroded.is_empty() else used).bbox()
        cx_l, cy_l = bb.center().x, bb.center().y
        if not mirrored:
            ax, ay = tx + cx_l * ldbu, ty + cy_l * ldbu
        else:
            ax, ay = tx + cx_l * ldbu, ty - cy_l * ldbu
        return (ax, ay)

    print("computing pin anchors for all nets...")
    pin_anchor = {}
    for net, pins in net_pins.items():
        for instname, typ, pinname in pins:
            key = (instname, pinname)
            if key in pin_anchor:
                continue
            pin_anchor[key] = abs_pin_anchor(instname, pinname)

    # ---------- global M1/M2/V1 connectivity (full core, no scan box) ----------
    print("building global connectivity graph...")
    m1_region = db.Region(top.begin_shapes_rec(m1_idx)).merged()
    m2_region = db.Region(top.begin_shapes_rec(m2_idx)).merged()
    v1_region = db.Region(top.begin_shapes_rec(v1_idx)).merged()
    m1_polys = list(m1_region.each())
    m2_polys = list(m2_region.each())
    print(f"{len(m1_polys)} M1 components, {len(m2_polys)} M2 components, {v1_region.count()} V1 vias")

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

    for via in v1_region.each():
        vbox = via.bbox()
        vreg = db.Region(via)
        m1_hits = [i for i, p in enumerate(m1_polys) if p.bbox().overlaps(vbox) or p.bbox().touches(vbox)]
        m1_hits = [i for i in m1_hits if vreg.interacting(db.Region(m1_polys[i])).count() > 0]
        m2_hits = [i for i, p in enumerate(m2_polys) if p.bbox().overlaps(vbox) or p.bbox().touches(vbox)]
        m2_hits = [i for i in m2_hits if vreg.interacting(db.Region(m2_polys[i])).count() > 0]
        for i in m1_hits:
            for j in m2_hits:
                union(("M1", i), ("M2", j))
        for i in m1_hits[1:]:
            union(("M1", m1_hits[0]), ("M1", i))
        for j in m2_hits[1:]:
            union(("M2", m2_hits[0]), ("M2", j))

    # spatial index for locate_m1: bucket by bbox for speed
    m1_bboxes = [p.bbox() for p in m1_polys]

    def locate_m1(x_um, y_um):
        xi, yi = int(round(x_um / dbu)), int(round(y_um / dbu))
        probe = db.Region(db.Box(xi - 2, yi - 2, xi + 2, yi + 2))
        for i, bb in enumerate(m1_bboxes):
            if bb.left - 5 <= xi <= bb.right + 5 and bb.bottom - 5 <= yi <= bb.top + 5:
                if probe.interacting(db.Region(m1_polys[i])).count() > 0:
                    return find(("M1", i))
        return None

    print("locating each pin's connectivity component...")
    pin_component = {}
    for key, anchor in pin_anchor.items():
        if anchor is None:
            pin_component[key] = None
            continue
        pin_component[key] = locate_m1(*anchor)

    # ---------- classify ----------
    open_pins = []       # (net, instname, pinname, x, y, dest_x, dest_y)
    unconn_pins = []     # (net, instname, pinname, x, y, dest_x, dest_y)

    def dist2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    for net, pins in net_pins.items():
        members = [(instname, pinname) for instname, typ, pinname in pins]
        comp_of = {k: pin_component.get(k) for k in members}
        by_comp = defaultdict(list)
        for k, c in comp_of.items():
            by_comp[c].append(k)
        n_comps = len(by_comp)
        if n_comps <= 1:
            continue  # fully connected (or single pin net, nothing to show)
        comp_sizes = {c: len(v) for c, v in by_comp.items()}
        max_size = max(comp_sizes.values())
        if max_size == 1:
            # fully disconnected net -- every pin isolated
            for instname, pinname in members:
                a = pin_anchor.get((instname, pinname))
                if a is None:
                    continue
                others = [pin_anchor[k] for k in members if k != (instname, pinname) and pin_anchor.get(k)]
                if not others:
                    continue
                dest = min(others, key=lambda o: dist2(a, o))
                unconn_pins.append((net, instname, pinname, a[0], a[1], dest[0], dest[1]))
        else:
            main_comp = max(by_comp.keys(), key=lambda c: comp_sizes[c])
            main_pins = [pin_anchor[k] for k in by_comp[main_comp] if pin_anchor.get(k)]
            for c, ks in by_comp.items():
                if c == main_comp:
                    continue
                for instname, pinname in ks:
                    a = pin_anchor.get((instname, pinname))
                    if a is None or not main_pins:
                        continue
                    dest = min(main_pins, key=lambda o: dist2(a, o))
                    open_pins.append((net, instname, pinname, a[0], a[1], dest[0], dest[1]))

    print(f"open pins (net partially connected): {len(open_pins)}")
    print(f"unconnected-net pins (net fully disconnected): {len(unconn_pins)}")
    unconn_nets = set(n for n, *_ in unconn_pins)
    print(f"  -> {len(unconn_nets)} fully-disconnected nets")

    # ---------- draw ERR layers ----------
    err_open_idx = top.layer(*ERR_OPEN_PIN_LAYER) if False else layout.layer(*ERR_OPEN_PIN_LAYER)
    err_unconn_idx = layout.layer(*ERR_UNCONNECTED_NET_LAYER)
    err_dest_idx = layout.layer(*ERR_DEST_LAYER)

    def um(v):
        return int(round(round(v / DRC_GRID) * DRC_GRID / dbu))

    MARK = 6.0

    def mark(x, y, label, layer_idx):
        box = db.Box(um(x - MARK / 2), um(y - MARK / 2), um(x + MARK / 2), um(y + MARK / 2))
        top.shapes(layer_idx).insert(box)
        t = db.Text(label, db.Trans(um(x), um(y + MARK)))
        t.size = um(2.0)
        top.shapes(layer_idx).insert(t)

    def link(x0, y0, x1, y1, layer_idx):
        top.shapes(layer_idx).insert(db.Box(um(min(x0, x1) - 0.4), um(y0 - 0.4), um(max(x0, x1) + 0.4), um(y0 + 0.4)))
        top.shapes(layer_idx).insert(db.Box(um(x1 - 0.4), um(min(y0, y1) - 0.4), um(x1 + 0.4), um(max(y0, y1) + 0.4)))

    for net, instname, pinname, x, y, dx, dy in open_pins:
        mark(x, y, f"{net}:{instname}.{pinname}", err_open_idx)
        mark(dx, dy, f"->{net}", err_dest_idx)
        link(x, y, dx, dy, err_dest_idx)

    for net, instname, pinname, x, y, dx, dy in unconn_pins:
        mark(x, y, f"{net}:{instname}.{pinname}", err_unconn_idx)
        mark(dx, dy, f"->{net}", err_dest_idx)
        link(x, y, dx, dy, err_dest_idx)

    layout.write(OUT_GDS)
    print("wrote", OUT_GDS)
    print(f"layers: {ERR_OPEN_PIN_LAYER}=open pins, {ERR_UNCONNECTED_NET_LAYER}=unconnected-net pins, "
          f"{ERR_DEST_LAYER}=destination markers/links (non-fab, reference only)")

    # ---------- text detail report, for manual-fix triage without opening KLayout ----------
    import os as _os
    txt_path = _os.path.join(_os.path.dirname(OUT_GDS), "err_report2_details.txt")
    with open(txt_path, "w") as f:
        f.write(f"open pins (net partially connected): {len(open_pins)}\n")
        f.write(f"unconnected-net pins (net fully disconnected): {len(unconn_pins)} across {len(unconn_nets)} nets\n\n")
        f.write("=== open pins (net has a main connected group; these pins are isolated from it) ===\n")
        by_net_open = defaultdict(list)
        for net, instname, pinname, x, y, dx, dy in open_pins:
            by_net_open[net].append((instname, pinname, x, y))
        for net in sorted(by_net_open):
            f.write(f"net {net}:\n")
            for instname, pinname, x, y in sorted(by_net_open[net]):
                f.write(f"  {instname}.{pinname}  ({x:.2f},{y:.2f})\n")
        f.write("\n=== fully-disconnected nets (no pin pair connected at all) ===\n")
        by_net_unconn = defaultdict(list)
        for net, instname, pinname, x, y, dx, dy in unconn_pins:
            by_net_unconn[net].append((instname, pinname, x, y))
        for net in sorted(by_net_unconn):
            f.write(f"net {net}:\n")
            for instname, pinname, x, y in sorted(by_net_unconn[net]):
                f.write(f"  {instname}.{pinname}  ({x:.2f},{y:.2f})\n")
    print("wrote", txt_path)


if __name__ == "__main__":
    main()
