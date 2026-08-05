"""
route_cross_row.py

Routes nets that cross a ZERO-GAP row boundary (row 0 / row 1, or row 2 /
row 3 -- design_notes.md section 15: these pairs abut directly with no
filler channel between them, sharing a power rail at the boundary, unlike
row 1/2's dedicated shared channel). There is therefore no empty M1 region
to host a horizontal M1 trunk the way route_channel.py / route_channel_shared
.py do.

Key difference from the channel routers: the "trunk" here is drawn on M2,
not M1. M2 has no electrical interaction with M1 it merely crosses over (no
via = no connection), so an M2 wire can freely cross the shared power rail
(and any other row's own M1) with zero DRC/connectivity concern -- only
OTHER M2 (existing library/filler M2, or this same pass's own previously-
drawn nets) needs to be avoided, via the exact same _m2_run_clear jog-search
machinery already used by route_channel.py. Each pin therefore only needs
ONE via (its own pin M1 -> M2), not two (pin->M2->trunk M1 as in the
channel case) -- the per-pin M2 escape cores and the horizontal joining bar
are all the same physical M2 shape once merged, which IS the electrical
connection.

"Track" slots here are a handful of Y offsets straddling the boundary
(spaced by TRACK_PITCH, same constant as the channel routers) rather than
the many slots available in an actual empty channel -- multiple cross-
boundary nets are packed onto these via the same left-edge interval-packing
algorithm as route_channel.py, so two nets whose X-ranges overlap land on
different Y offsets instead of colliding.

Everything else (GC-avoiding via anchor search, shared-obstacle/same-
instance/exact-X forced-direction jog splitting, DRC-grid snapping) is
identical to route_channel.py -- see that file and design_notes.md section
22 for the full rationale.
"""
import os
import re
import sys
import json

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402
import route_channel as rc

ROW_HEIGHT = rc.ROW_HEIGHT
M1_MIN_SPACE = rc.M1_MIN_SPACE
M2_MIN_SPACE = rc.M2_MIN_SPACE
TRACK_WIDTH = rc.TRACK_WIDTH
TRACK_PITCH = rc.TRACK_PITCH
VIA_SIZE = rc.VIA_SIZE
VIA_MARGIN_UM = rc.VIA_MARGIN_UM
M2_CORE_WIDTH = rc.M2_CORE_WIDTH
M2_PAD_SIZE = rc.M2_PAD_SIZE
GC_KEEPOUT_UM = rc.GC_KEEPOUT_UM
DRC_GRID = rc.DRC_GRID
M1_LAYER = rc.M1_LAYER
V1_LAYER = rc.V1_LAYER
M2_LAYER = rc.M2_LAYER
GC_LAYER = rc.GC_LAYER
PIN_TEXT_LAYER = rc.PIN_TEXT_LAYER
STDCELL_DIR = rc.STDCELL_DIR
GDS_LIB = rc.GDS_LIB
IN_GDS = rc.IN_GDS
NET_FILE = rc.NET_FILE


def _parse_netlist(sym_pins):
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

    net_pins = {}
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':
                continue
            net_pins.setdefault(find(expr), []).append((name, typ, pin))
    return net_pins


def route_boundary_pair(row_a, row_b, boundary_y, out_gds, pin_map_json,
                         n_slots=20, annot_layer=(250, 4), row_annot_layer=(250, 0),
                         net_filter=None):
    """row_a, row_b: dicts with logical_row_idx, phys_row_index, mirrored,
    escape_dir ('up' for the row below the boundary, 'down' for the row
    above it). boundary_y: the shared/abutting Y where the two rows meet
    (row_a's near edge == row_b's near edge == this Y). Routes every net
    whose pins lie ENTIRELY within row_a's + row_b's instances and touch
    BOTH rows (nets fully internal to just one row are route_channel.py's
    job). net_filter(net_name)->bool can restrict to a subset (e.g. only
    the two-row-exactly nets, leaving 3+-row nets for a later pass)."""
    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: rc.parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

    lib = db.Layout()
    lib.read(GDS_LIB)
    ldbu = lib.dbu
    lib_pin_text_idx = lib.layer(*PIN_TEXT_LAYER)
    lib_m1_idx = lib.layer(*M1_LAYER)
    lib_gc_idx = lib.layer(*GC_LAYER)

    gc_cache = {}

    def cell_gc_forbidden(celltype):
        if celltype not in gc_cache:
            c = lib.cell(celltype)
            gc_region = db.Region(c.begin_shapes_rec(lib_gc_idx))
            keepout_ldbu = int(round(GC_KEEPOUT_UM / ldbu))
            gc_cache[celltype] = gc_region.sized(keepout_ldbu)
        return gc_cache[celltype]

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
                if cand:
                    best = min(cand, key=lambda p: p.bbox().area())
                else:
                    best = min(net_polys, key=lambda p: (p.bbox().center().x - px) ** 2 + (p.bbox().center().y - py) ** 2)
                pins[s.text_string.lower()] = best
            it.next()
        return pins

    pin_cache = {}

    def cell_pin_poly(celltype, pinname):
        if celltype not in pin_cache:
            pin_cache[celltype] = get_cell_pin_data(celltype)
        d = pin_cache[celltype]
        key = pinname.lower()
        if key not in d:
            raise RuntimeError(f"pin {pinname!r} not found for {celltype} (have {list(d)})")
        return d[key]

    net_pins = _parse_netlist(sym_pins)

    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)

    pr_bbox_cache = {}

    def get_pr_bbox(celltype):
        if celltype not in pr_bbox_cache:
            c = lib.cell(celltype)
            pr_idx = lib.layer(*PR_LAYER)
            pr_bbox_cache[celltype] = db.Region(c.begin_shapes_rec(pr_idx)).bbox()
        return pr_bbox_cache[celltype]

    _annot_layout = db.Layout()
    _annot_layout.read(IN_GDS)
    _annot_top = _annot_layout.cell("i2c_slave_async_layout")
    _annot_idx = _annot_layout.layer(*row_annot_layer)

    _rail_scan = db.Layout()
    _rail_scan.read(IN_GDS)
    _rail_dbu = _rail_scan.dbu
    _rail_top = _rail_scan.cell("i2c_slave_async_layout")
    _rail_m2_idx = _rail_scan.layer(*M2_LAYER)

    row_y_los = [row_a["phys_row_index"] * ROW_HEIGHT, row_b["phys_row_index"] * ROW_HEIGHT]
    row_y_his = [(row_a["phys_row_index"] + 1) * ROW_HEIGHT, (row_b["phys_row_index"] + 1) * ROW_HEIGHT]
    scan_y_lo, scan_y_hi = min(row_y_los), max(row_y_his)
    _row_scan_box = db.Box(0, int(round(scan_y_lo / _rail_dbu)),
                            int(round(ROW_WIDTH_UM / _rail_dbu)),
                            int(round(scan_y_hi / _rail_dbu)))
    _existing_m2 = db.Region(_rail_top.begin_shapes_rec_touching(_rail_m2_idx, _row_scan_box)).merged()
    _existing_m2_original_polys = list(_existing_m2.each())

    def _box_clear(l_um, b_um, r_um, t_um):
        box = db.Box(int(round(l_um / _rail_dbu)), int(round(b_um / _rail_dbu)),
                      int(round(r_um / _rail_dbu)), int(round(t_um / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        return db.Region(box).sized(clearance_ldbu).interacting(_existing_m2).count() == 0

    def _m2_run_clear(x_um, y0_um, y1_um, half_width_um):
        ylo, yhi = (y0_um, y1_um) if y0_um <= y1_um else (y1_um, y0_um)
        run = db.Box(int(round((x_um - half_width_um) / _rail_dbu)), int(round(ylo / _rail_dbu)),
                      int(round((x_um + half_width_um) / _rail_dbu)), int(round(yhi / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        return db.Region(run).sized(clearance_ldbu).interacting(_existing_m2).count() == 0

    row_names = {}
    inst_origin = {}
    inst_type = {}
    for cfg in (row_a, row_b):
        li = cfg["logical_row_idx"]
        pri = cfg["phys_row_index"]
        mirrored = cfg["mirrored"]
        row = rows[li]
        names = set(n for n, t, w in row)
        row_names[li] = names
        ROW_CY = pri * ROW_HEIGHT + ROW_HEIGHT / 2.0
        row_cx = {}
        it = _annot_top.begin_shapes_rec(_annot_idx)
        while not it.at_end():
            s = it.shape()
            if s.is_text():
                ay = s.text_dtrans.disp.y
                if abs(ay - ROW_CY) < 0.01:
                    row_cx[s.text_string] = s.text_dtrans.disp.x
            it.next()
        missing = [n for n, t, w in row if n not in row_cx]
        if missing:
            raise RuntimeError(f"{len(missing)} row{li} instances have no annotation match: {missing[:5]}...")
        for name, typ, w in row:
            bbox = get_pr_bbox(typ)
            bleft = bbox.left * ldbu
            bbottom = bbox.bottom * ldbu
            btop = bbox.top * ldbu
            width = bbox.width() * ldbu
            cx = row_cx[name]
            tx = cx - (bleft + width / 2.0)
            ty = (pri * ROW_HEIGHT - bbottom) if not mirrored else (pri * ROW_HEIGHT + btop)
            inst_origin[name] = (tx, ty)
            inst_type[name] = typ

    inst_row = {}
    inst_escape = {}
    for cfg in (row_a, row_b):
        for n in row_names[cfg["logical_row_idx"]]:
            inst_row[n] = cfg["logical_row_idx"]
            inst_escape[n] = cfg["escape_dir"]
    mirrored_of = {row_a["logical_row_idx"]: row_a["mirrored"], row_b["logical_row_idx"]: row_b["mirrored"]}
    row_names_union = row_names[row_a["logical_row_idx"]] | row_names[row_b["logical_row_idx"]]

    def abs_pin_anchor(instname, pinname):
        typ = inst_type[instname]
        poly = cell_pin_poly(typ, pinname)
        ox, oy = inst_origin[instname]
        mirrored = mirrored_of[inst_row[instname]]
        gc_forbid = cell_gc_forbidden(typ)
        margin_ldbu = int(round(VIA_MARGIN_UM / ldbu))

        def safe_region(region):
            return region.sized(-margin_ldbu) - gc_forbid

        base = db.Region(poly)
        eroded = safe_region(base)
        grown_um = 0.0
        used = base
        if eroded.is_empty():
            for grow_um in (0.02, 0.05, 0.08, 0.12, 0.2, 0.3, 0.5, 0.8, 1.2):
                grow_ldbu = int(round(grow_um / ldbu))
                cand = base.sized(grow_ldbu)
                cand_eroded = safe_region(cand)
                if not cand_eroded.is_empty():
                    used, eroded, grown_um = cand, cand_eroded, grow_um
                    break
            else:
                raise RuntimeError(f"{instname}.{pinname}: no safe via anchor even after growth")

        pieces = list(eroded.each())
        best = max(pieces, key=lambda p: p.bbox().area())
        bb = best.bbox()
        local_x = bb.center().x * ldbu
        local_y = bb.center().y * ldbu
        if not mirrored:
            vx, vy = local_x + ox, local_y + oy
        else:
            vx, vy = local_x + ox, -local_y + oy

        patch_polys_abs = []
        if grown_um > 0.0:
            for p in used.each():
                pts = []
                for pt in p.each_point_hull():
                    lx, ly = pt.x * ldbu, pt.y * ldbu
                    if not mirrored:
                        pts.append(db.DPoint(lx + ox, ly + oy))
                    else:
                        pts.append(db.DPoint(lx + ox, -ly + oy))
                patch_polys_abs.append(pts)
        return vx, vy, patch_polys_abs, grown_um > 0.0

    boundary_nets = []
    for net, pins in net_pins.items():
        inst_names = set(p[0] for p in pins)
        if not inst_names:
            continue
        touched_rows = set(inst_row[n] for n in inst_names if n in inst_row)
        if not (inst_names <= row_names_union):
            continue  # touches a row outside this pair -- not our job
        if touched_rows != {row_a["logical_row_idx"], row_b["logical_row_idx"]}:
            continue  # single-row-internal (route_channel.py's job), or doesn't touch this pair at all
        if net_filter is not None and not net_filter(net):
            continue
        boundary_nets.append((net, pins))

    print(f"row{row_a['logical_row_idx']}<->row{row_b['logical_row_idx']} boundary (y={boundary_y}): "
          f"{len(boundary_nets)} nets")

    all_pins = []
    net_stub_pts = {}
    net_pin_names = {}
    for net, pins in boundary_nets:
        pts = []
        names = []
        for instname, typ, pinname in pins:
            vx, vy, patch_polys, padded = abs_pin_anchor(instname, pinname)
            pts.append((vx, vy, patch_polys, padded))
            names.append((instname, pinname))
            all_pins.append((instname, pinname, vx, vy, inst_escape[instname]))
        net_stub_pts[net] = pts
        net_pin_names[net] = names

    # ---------- shared-obstacle / same-instance / exact-X pre-pass ----------
    HALF_PAD = M2_PAD_SIZE / 2.0

    def _blocking_obstruction_index(x, y_center, escape_dir):
        y_near = y_center - HALF_PAD if escape_dir == "up" else y_center + HALF_PAD
        if _m2_run_clear(x, y_near, boundary_y, HALF_PAD):
            return None
        ylo, yhi = (y_near, boundary_y) if y_near <= boundary_y else (boundary_y, y_near)
        run = db.Box(int(round((x - HALF_PAD) / _rail_dbu)), int(round(ylo / _rail_dbu)),
                      int(round((x + HALF_PAD) / _rail_dbu)), int(round(yhi / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        grown = db.Region(run).sized(clearance_ldbu)
        for i, p in enumerate(_existing_m2_original_polys):
            if grown.interacting(db.Region(p)).count() > 0:
                return i
        return None

    blocked_by = {}
    for instname, pinname, x, y, escape_dir in all_pins:
        idx = _blocking_obstruction_index(x, y, escape_dir)
        if idx is not None:
            blocked_by[(instname, pinname)] = idx

    uf_parent = {}

    def uf_find(k):
        uf_parent.setdefault(k, k)
        while uf_parent[k] != k:
            uf_parent[k] = uf_parent[uf_parent[k]]
            k = uf_parent[k]
        return k

    def uf_union(a, b):
        ra, rb = uf_find(a), uf_find(b)
        if ra != rb:
            uf_parent[ra] = rb

    by_obstruction = {}
    for key, idx in blocked_by.items():
        by_obstruction.setdefault(idx, []).append(key)
    for idx, keys in by_obstruction.items():
        for k in keys[1:]:
            uf_union(keys[0], k)

    SAME_INST_LINK_DIST_UM = 20.0
    by_inst = {}
    for instname, pinname, x, y, _ed in all_pins:
        by_inst.setdefault(instname, []).append((pinname, x, y))
    for instname, pins_here in by_inst.items():
        if len(pins_here) < 2:
            continue
        for i in range(len(pins_here)):
            for j in range(i + 1, len(pins_here)):
                if abs(pins_here[i][1] - pins_here[j][1]) < SAME_INST_LINK_DIST_UM:
                    uf_union((instname, pins_here[i][0]), (instname, pins_here[j][0]))

    ADJACENT_LINK_DIST_UM = 20.0
    all_pins_sorted = sorted(all_pins, key=lambda t: t[2])
    for i in range(len(all_pins_sorted)):
        ni, pi, xi, yi = all_pins_sorted[i][:4]
        for j in range(i + 1, len(all_pins_sorted)):
            nj, pj, xj, yj = all_pins_sorted[j][:4]
            if xj - xi >= ADJACENT_LINK_DIST_UM:
                break
            if abs(yi - yj) < 2.0:
                uf_union((ni, pi), (nj, pj))

    groups = {}
    for instname, pinname, x, y, _ed in all_pins:
        key = (instname, pinname)
        if key in blocked_by or key in uf_parent:
            groups.setdefault(uf_find(key), []).append((x, instname, pinname))

    EXACT_X_EPS = 0.01
    _pins_by_x = {}
    for instname, pinname, x, y, _ed in all_pins:
        _pins_by_x.setdefault(round(x / EXACT_X_EPS), []).append((instname, pinname))
    must_jog = set()
    for _bucket, plist in _pins_by_x.items():
        if len(plist) >= 2:
            must_jog.update(plist)
    if must_jog:
        print(f"exact-X pin pairs forced to always jog: {sorted(must_jog)}")

    forced_dir = {}
    forced_rank = {}
    for root, members in groups.items():
        if len(members) < 2:
            continue
        members.sort()
        side_count = {-1: 0, 1: 0}
        for i, (x, instname, pinname) in enumerate(members):
            d = -1 if i % 2 == 0 else 1
            forced_dir[(instname, pinname)] = d
            forced_rank[(instname, pinname)] = side_count[d]
            side_count[d] += 1
        print(f"shared-obstacle/same-instance group: "
              + ", ".join(f"{n}.{p}(x={x:.1f},dir={'L' if forced_dir[(n, p)] < 0 else 'R'}"
                          f"{'' if forced_rank[(n, p)] == 0 else f'#{forced_rank[(n, p)]}'})"
                          for x, n, p in members))

    net_priority = {net: (0 if any((n, p) in forced_dir for n, p in net_pin_names[net]) else 1)
                    for net in net_stub_pts}

    # ---------- track (Y-offset) slots straddling the boundary ----------
    track_slots = [boundary_y + (k - n_slots // 2) * TRACK_PITCH for k in range(n_slots)]
    print(f"boundary track slots (um): {[round(t, 2) for t in track_slots]}")

    net_intervals = []
    for net, pts in net_stub_pts.items():
        xs = [p[0] for p in pts]
        net_intervals.append((min(xs), max(xs), net))
    net_intervals.sort()

    # Unlike route_channel.py's channel (uniformly empty filler space, so
    # ANY track slot is equally cheap to reach), these slots span deep into
    # BOTH rows' real, densely-populated cell bodies -- a slot far from the
    # boundary forces a pin's M2 core to traverse a much longer, more
    # obstructed path (potentially the entire opposite row) to reach it.
    # Greedily filling slots in fixed left-to-right order (as the channel
    # router does) was found to route some pins to a slot ~50-80um past
    # the boundary and deep into the FAR row purely by accident of packing
    # order, which then failed to find any clear jog at all. Fix: always
    # prefer the slot CLOSEST to the boundary that is still free (by X)
    # for a given net, only reaching further out once the close-in slots
    # are already claimed by an X-overlapping net.
    slot_order = sorted(range(len(track_slots)), key=lambda i: abs(track_slots[i] - boundary_y))
    slot_right_edge = {i: float("-inf") for i in range(len(track_slots))}
    net_track = {}
    MARGIN = TRACK_WIDTH + M1_MIN_SPACE * 2
    for lo, hi, net in net_intervals:
        for i in slot_order:
            if lo - slot_right_edge[i] >= MARGIN:
                slot_right_edge[i] = hi
                net_track[net] = i
                break
        else:
            raise RuntimeError(f"net {net} could not be packed onto any of {len(track_slots)} "
                                f"boundary track slots -- increase n_slots")

    n_tracks = len(set(net_track.values()))
    print(f"tracks used: {n_tracks} (of {len(track_slots)} slots)")
    if os.environ.get("DEBUG_TRACKS"):
        for net, ti in net_track.items():
            print(f"DEBUG_TRACK net={net} track_y={track_slots[ti]:.2f}")

    # ---------- emit geometry (pure M2 net shape + 1 via per pin) ----------
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell("i2c_slave_async_layout")
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)
    annot_idx = layout.layer(*annot_layer)

    def um(v):
        return int(round(round(v / DRC_GRID) * DRC_GRID / dbu))

    def pad(cx, cy, size):
        h = size / 2.0
        return db.Box(um(cx - h), um(cy - h), um(cx + h), um(cy + h))

    def _find_jog_x(vx, y_center, track_y, preferred_dir=None, skip_rank=0, must_jog=False):
        half = M2_PAD_SIZE / 2.0
        if not must_jog and _m2_run_clear(vx, y_center - half, track_y + half, half):
            return vx
        mags = (2, 4, 6, 8, 10, 14, 18, 24, 30, 40, 50, 60, 80, 100)
        if preferred_dir == -1:
            offsets = [-d for d in mags[skip_rank:]] + [d for d in mags]
        elif preferred_dir == 1:
            offsets = [d for d in mags[skip_rank:]] + [-d for d in mags]
        else:
            offsets = []
            for d in mags:
                offsets += [d, -d]
        for off in offsets:
            jx = vx + off
            if jx < 2.0 or jx > ROW_WIDTH_UM - 2.0:
                continue
            if not _m2_run_clear(jx, y_center - half, track_y + half, half):
                continue
            lo, hi = (vx, jx) if vx <= jx else (jx, vx)
            if not _box_clear(lo, y_center - half, hi, y_center + half):
                continue
            return jx
        return None

    shapes_drawn = 0
    unrouted_pins = []  # (net, instname, pinname) -- left OPEN, not drawn, rather than
                         # falling back to an unjogged/likely-colliding stub. In the dense
                         # cell-row case (unlike an empty channel) an unjogged fallback
                         # was found to actively pollute _existing_m2 for later nets,
                         # cascading into a much higher failure rate overall (see
                         # design_notes.md 23.5) -- an open pin is a visible, honestly-
                         # reported gap; a colliding fallback is a silent short.
    net_order = sorted(net_stub_pts.keys(), key=lambda n: (net_priority[n], n))
    for net in net_order:
        pts = net_stub_pts[net]
        names = net_pin_names[net]
        ti = net_track[net]
        track_y = track_slots[ti]

        resolved = []
        for (instname, pinname), (x, y_center, patch_polys, padded) in zip(names, pts):
            pref = forced_dir.get((instname, pinname))
            rank = forced_rank.get((instname, pinname), 0)
            mj = (instname, pinname) in must_jog
            top_x = _find_jog_x(x, y_center, track_y, preferred_dir=pref, skip_rank=rank, must_jog=mj)
            if top_x is None:
                print(f"WARNING: net {net} pin {instname}.{pinname} at ({x:.2f},{y_center:.2f}): "
                      f"no clear M2 jog found within search range; leaving OPEN (not drawn)")
                unrouted_pins.append((net, instname, pinname))
                continue
            resolved.append((x, y_center, patch_polys, padded, top_x))

        if not resolved:
            print(f"WARNING: net {net}: ALL pins failed to jog; net not drawn at all")
            continue

        top_xs = [r[4] for r in resolved]
        x_lo, x_hi = min(top_xs), max(top_xs)

        # M2 horizontal joining bar (NOT M1 -- see module docstring)
        top.shapes(m2_idx).insert(db.Box(um(x_lo - TRACK_WIDTH / 2), um(track_y - TRACK_WIDTH / 2),
                                          um(x_hi + TRACK_WIDTH / 2), um(track_y + TRACK_WIDTH / 2)))
        shapes_drawn += 1

        for x, y_center, patch_polys, padded, top_x in resolved:
            if padded:
                for pts_um in patch_polys:
                    poly = db.Polygon([db.Point(um(p.x), um(p.y)) for p in pts_um])
                    top.shapes(m1_idx).insert(poly)
                    shapes_drawn += 1
            # ONE via per pin: pin's own M1 -> M2 (no second via, no M1
            # trunk -- the M2 core+bridge+bar below merge into one shape
            # that IS the electrical connection all the way across).
            top.shapes(v1_idx).insert(pad(x, y_center, VIA_SIZE))

            if top_x != x:
                lo, hi = (x, top_x) if x <= top_x else (top_x, x)
                if x <= top_x:
                    hi += M2_CORE_WIDTH / 2
                else:
                    lo -= M2_CORE_WIDTH / 2
                top.shapes(m2_idx).insert(db.Box(um(lo), um(y_center - M2_PAD_SIZE / 2),
                                                  um(hi), um(y_center + M2_PAD_SIZE / 2)))
                shapes_drawn += 1

            y0, y1 = (y_center, track_y) if y_center <= track_y else (track_y, y_center)
            top.shapes(m2_idx).insert(db.Box(um(top_x - M2_CORE_WIDTH / 2), um(y0 - 0.3),
                                              um(top_x + M2_CORE_WIDTH / 2), um(y1 + 0.3)))
            top.shapes(m2_idx).insert(pad(x, y_center, M2_PAD_SIZE))
            shapes_drawn += 3

        label = db.Text(net, db.Trans(um((x_lo + x_hi) / 2), um(track_y)))
        label.size = um(1.5)
        top.shapes(annot_idx).insert(label)

        _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _row_scan_box)).merged()

    print(f"drew {shapes_drawn} shapes (M2 net shapes + V1 vias) for {len(net_stub_pts)} nets")
    if unrouted_pins:
        print(f"{len(unrouted_pins)} pin(s) left OPEN (unrouted): {unrouted_pins}")

    os.makedirs(os.path.dirname(out_gds), exist_ok=True)
    layout.write(out_gds)

    pin_map = {}
    for net in net_stub_pts:
        pin_map[net] = [
            (instname, pinname, vx, vy)
            for (instname, pinname), (vx, vy, _patch, _padded) in zip(net_pin_names[net], net_stub_pts[net])
        ]
    with open(pin_map_json, "w") as f:
        json.dump(pin_map, f, indent=1)
    print("wrote", pin_map_json)
    print("wrote", out_gds)


ROW01_BOUNDARY = dict(
    row_a=dict(logical_row_idx=0, phys_row_index=2, mirrored=False, escape_dir="up"),
    row_b=dict(logical_row_idx=1, phys_row_index=3, mirrored=True, escape_dir="down"),
    boundary_y=3 * ROW_HEIGHT,  # 165.0
    out_gds="/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_row01x.gds",
    pin_map_json="/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/row01x_pin_map.json",
    net_filter=lambda net: True,  # exactly-2-row nets only, by construction of route_boundary_pair
)

if __name__ == "__main__":
    route_boundary_pair(**ROW01_BOUNDARY)
