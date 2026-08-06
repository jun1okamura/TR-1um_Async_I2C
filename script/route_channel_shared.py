"""
route_channel_shared.py

Routes the SHARED M1 channel between logical row 1 (below) and logical row 2
(above) -- design_notes.md section 15/22. Unlike route_channel.py's single-
row channels (row 0's dedicated bottom margin, row 3's dedicated top
margin), this channel is fed from BOTH sides: row 1's pins escape UPWARD
into it, row 2's pins escape DOWNWARD into it, and their M1 trunks must
share the SAME set of horizontal track slots -- so track (Y-slot) assignment
has to consider both rows' nets TOGETHER, not independently (two independent
per-row assignments could easily hand both rows overlapping X-ranges the
same track_y, which would only show up as a merged-shape short once the
output is combined, exactly like the same-X-pin/adjacent-pin problem in
route_channel_pilot.py -- see design_notes.md section 22.5).

Both row 1 and row 2 are ALSO Y-mirrored (gen_gds_placement.py's
PHYSICAL_ROWS: row1=physical index 3, row2=physical index 7, both odd ->
mirrored=True) -- so, unlike row 0/row 3, recovering each instance's real
placement AND transforming each pin's local polygon into absolute
coordinates must use the M0 (mirror-Y) branch throughout
(route_channel.py's route_row_channel already added this as a general
`mirrored` parameter; this script reuses that same math, just for two rows
at once instead of one).

Otherwise the underlying per-pin algorithm (GC-avoidance via anchor search,
shared-obstacle/same-instance/exact-X forced-direction M2 jog escape
routing, DRC-grid-snapped geometry) is identical to route_channel.py /
route_channel_pilot.py -- see those files' comments and design_notes.md
section 22 for the full rationale of each piece. This script only adds the
"two rows feeding one shared channel" combination logic on top.
"""
import os
import sys
import json

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402
import route_channel as rc  # reuse constants + parse_sym + netlist-parse helpers

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


def route_shared_channel(row_cfgs, channel_bottom_y, channel_height, out_gds, pin_map_json,
                          annot_layer=(250, 3), row_annot_layer=(250, 0)):
    """row_cfgs: list of dicts, one per row feeding this channel, each with
    keys logical_row_idx, phys_row_index, mirrored, escape_dir ('up' if the
    channel is ABOVE this row, 'down' if BELOW)."""
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

    # ---------- netlist parse (identical logic to route_channel.py) ----------
    import re
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

    net_pins = {}
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':
                continue
            net_pins.setdefault(canon(expr), []).append((name, typ, pin))

    # ---------- placement + per-row pin anchors ----------
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
    _rail_m1_idx = _rail_scan.layer(*M1_LAYER)
    _rail_m2_idx = _rail_scan.layer(*M2_LAYER)

    # Combined obstruction-scan box: spans from the LOWER row's own bottom
    # edge up through the channel to the UPPER row's own top edge, so both
    # rows' own pre-existing M2 usage (filler patterns etc.) is captured,
    # not just the empty channel itself.
    row_y_los = [cfg["phys_row_index"] * ROW_HEIGHT for cfg in row_cfgs]
    row_y_his = [(cfg["phys_row_index"] + 1) * ROW_HEIGHT for cfg in row_cfgs]
    scan_y_lo = min(row_y_los)
    scan_y_hi = max(row_y_his)
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

    all_pins = []          # (instname, pinname, x, y_center, escape_dir, near_edge_y)
    net_stub_pts = {}      # net -> [(vx, vy, patch_polys, padded), ...]
    net_pin_names = {}     # net -> [(instname, pinname), ...]
    row_names_all = set()

    for cfg in row_cfgs:
        logical_row_idx = cfg["logical_row_idx"]
        phys_row_index = cfg["phys_row_index"]
        mirrored = cfg["mirrored"]
        escape_dir = cfg["escape_dir"]

        row = rows[logical_row_idx]
        row_names = set(n for n, t, w in row)
        row_names_all |= row_names
        ROW_CY = phys_row_index * ROW_HEIGHT + ROW_HEIGHT / 2.0

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
            raise RuntimeError(f"{len(missing)} row{logical_row_idx} instances have no annotation "
                                f"match in {IN_GDS}: {missing[:5]}...")

        inst_origin = {}
        for name, typ, w in row:
            bbox = get_pr_bbox(typ)
            bleft = bbox.left * ldbu
            bbottom = bbox.bottom * ldbu
            btop = bbox.top * ldbu
            width = bbox.width() * ldbu
            cx = row_cx[name]
            tx = cx - (bleft + width / 2.0)
            if not mirrored:
                ty = phys_row_index * ROW_HEIGHT - bbottom
            else:
                ty = phys_row_index * ROW_HEIGHT + btop
            inst_origin[name] = (tx, ty)

        inst_type = dict((n, t) for n, t, w in row)

        def abs_pin_anchor(instname, pinname, mirrored=mirrored, inst_origin=inst_origin, inst_type=inst_type):
            typ = inst_type[instname]
            poly = cell_pin_poly(typ, pinname)
            ox, oy = inst_origin[instname]
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

        internal_nets = []
        for net, pins in net_pins.items():
            inst_names = set(p[0] for p in pins)
            if not inst_names:
                continue
            if inst_names & row_names and inst_names <= row_names:
                internal_nets.append((net, pins))

        print(f"row{logical_row_idx} (phys {phys_row_index}, mirrored={mirrored}, escape={escape_dir}): "
              f"{len(row_names)} instances, {len(internal_nets)} fully-internal nets")

        near_edge_y = (phys_row_index + 1) * ROW_HEIGHT if escape_dir == "up" else phys_row_index * ROW_HEIGHT

        for net, pins in internal_nets:
            pts = []
            names = []
            for instname, typ, pinname in pins:
                vx, vy, patch_polys, padded = abs_pin_anchor(instname, pinname)
                pts.append((vx, vy, patch_polys, padded))
                names.append((instname, pinname))
                all_pins.append((instname, pinname, vx, vy, escape_dir, near_edge_y))
            net_stub_pts[net] = pts
            net_pin_names[net] = names

    print(f"combined: {len(net_stub_pts)} fully-internal nets across {len(row_cfgs)} rows, {len(all_pins)} pins")

    # ---------- pre-pass: shared-obstacle / same-instance / exact-X grouping ----------
    HALF_PAD = M2_PAD_SIZE / 2.0

    def _blocking_obstruction_index(x, y_center, escape_dir, near_edge_y):
        y_near = y_center - HALF_PAD if escape_dir == "up" else y_center + HALF_PAD
        if _m2_run_clear(x, y_near, near_edge_y, HALF_PAD):
            return None
        ylo, yhi = (y_near, near_edge_y) if y_near <= near_edge_y else (near_edge_y, y_near)
        run = db.Box(int(round((x - HALF_PAD) / _rail_dbu)), int(round(ylo / _rail_dbu)),
                      int(round((x + HALF_PAD) / _rail_dbu)), int(round(yhi / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        grown = db.Region(run).sized(clearance_ldbu)
        for i, p in enumerate(_existing_m2_original_polys):
            if grown.interacting(db.Region(p)).count() > 0:
                return i
        return None

    blocked_by = {}
    for instname, pinname, x, y, escape_dir, near_edge_y in all_pins:
        idx = _blocking_obstruction_index(x, y, escape_dir, near_edge_y)
        if idx is not None:
            blocked_by[(instname, pinname)] = idx

    SAME_INST_LINK_DIST_UM = 20.0
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

    by_inst = {}
    for instname, pinname, x, y, _ed, _ne in all_pins:
        by_inst.setdefault(instname, []).append((pinname, x, y))
    for instname, pins_here in by_inst.items():
        if len(pins_here) < 2:
            continue
        for i in range(len(pins_here)):
            for j in range(i + 1, len(pins_here)):
                if abs(pins_here[i][1] - pins_here[j][1]) < SAME_INST_LINK_DIST_UM:
                    uf_union((instname, pins_here[i][0]), (instname, pins_here[j][0]))

    # Adjacent-pin linking is Y-gated at <2.0um in the single-row scripts
    # (same physical row => comparable Y). Here two DIFFERENT rows can share
    # similar X while sitting ~165-275um apart in Y (row1 vs row2), which
    # must NOT be linked -- their M2 runs go to opposite tracks in opposite
    # directions and don't compete for the same detour space the way same-
    # row neighbors do. Keep the same <2.0um Y gate; it naturally excludes
    # cross-row pairs since they're never that close in Y.
    ADJACENT_LINK_DIST_UM = 20.0
    all_pins_sorted = sorted(all_pins, key=lambda t: t[2])
    for i in range(len(all_pins_sorted)):
        ni, pi, xi, yi = all_pins_sorted[i][0], all_pins_sorted[i][1], all_pins_sorted[i][2], all_pins_sorted[i][3]
        for j in range(i + 1, len(all_pins_sorted)):
            nj, pj, xj, yj = all_pins_sorted[j][0], all_pins_sorted[j][1], all_pins_sorted[j][2], all_pins_sorted[j][3]
            if xj - xi >= ADJACENT_LINK_DIST_UM:
                break
            if abs(yi - yj) < 2.0:
                uf_union((ni, pi), (nj, pj))

    groups = {}
    for instname, pinname, x, y, _ed, _ne in all_pins:
        key = (instname, pinname)
        if key in blocked_by or key in uf_parent:
            groups.setdefault(uf_find(key), []).append((x, instname, pinname))

    EXACT_X_EPS = 0.01
    _pins_by_x = {}
    for instname, pinname, x, y, _ed, _ne in all_pins:
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

    # ---------- available track Y slots (channel itself, shared by both rows) ----------
    _scan_box = db.Box(0, int(round(channel_bottom_y / _rail_dbu)),
                        int(round(ROW_WIDTH_UM / _rail_dbu)),
                        int(round((channel_bottom_y + channel_height) / _rail_dbu)))
    _m1_in_channel = db.Region(_rail_top.begin_shapes_rec_touching(_rail_m1_idx, _scan_box)).merged()
    rail_bands = []
    for p in _m1_in_channel.each():
        bb = p.bbox()
        if bb.width() * _rail_dbu > ROW_WIDTH_UM * 0.5:
            rail_bands.append((bb.bottom * _rail_dbu, bb.top * _rail_dbu))
    rail_bands.sort()
    print(f"rail bands found in channel: {[(round(b,2), round(t,2)) for b, t in rail_bands]}")

    RAIL_MARGIN = M1_MIN_SPACE + TRACK_WIDTH / 2.0
    clear_spans = []
    cursor = channel_bottom_y
    top_limit = channel_bottom_y + channel_height
    for b, t in rail_bands:
        if b - cursor > 2 * RAIL_MARGIN:
            clear_spans.append((cursor + RAIL_MARGIN, b - RAIL_MARGIN))
        cursor = max(cursor, t)
    if top_limit - cursor > 2 * RAIL_MARGIN:
        clear_spans.append((cursor + RAIL_MARGIN, top_limit - RAIL_MARGIN))

    track_slots = []
    for lo, hi in clear_spans:
        y = lo
        while y <= hi:
            track_slots.append(y)
            y += TRACK_PITCH
    print(f"clear Y spans: {[(round(a,2), round(b,2)) for a,b in clear_spans]}, "
          f"{len(track_slots)} track slots available")

    # ---------- left-edge track assignment (ALL nets from BOTH rows, combined) ----------
    net_intervals = []
    for net, pts in net_stub_pts.items():
        xs = [p[0] for p in pts]
        net_intervals.append((min(xs), max(xs), net))
    net_intervals.sort()

    tracks = []
    net_track = {}
    MARGIN = TRACK_WIDTH + M1_MIN_SPACE * 2
    for lo, hi, net in net_intervals:
        placed = False
        for ti, right in enumerate(tracks):
            if lo - right >= MARGIN:
                tracks[ti] = hi
                net_track[net] = ti
                placed = True
                break
        if not placed:
            tracks.append(hi)
            net_track[net] = len(tracks) - 1

    n_tracks = len(tracks)
    print(f"tracks used: {n_tracks} (of {len(track_slots)} available slots)")
    assert n_tracks <= len(track_slots), "shared channel overflowed its track budget"

    # ---------- emit geometry ----------
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
    unrouted_pins = []
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
                # Leave OPEN rather than drawing an unjogged fallback that's
                # already known to collide -- avoids cascading obstruction
                # pollution into _existing_m2 for subsequent nets (same fix
                # as route_channel.py / route_cross_row.py).
                print(f"WARNING: net {net} pin {instname}.{pinname} at ({x:.2f},{y_center:.2f}): "
                      f"no clear M2 jog found within search range; leaving UNROUTED (open)")
                unrouted_pins.append((net, instname, pinname, x, y_center))
                continue
            resolved.append((x, y_center, patch_polys, padded, top_x))

        if not resolved:
            print(f"WARNING: net {net}: ALL pins failed to route; net left fully unrouted")
            continue

        top_xs = [r[4] for r in resolved]
        x_lo, x_hi = min(top_xs), max(top_xs)

        trunk = db.Box(um(x_lo - TRACK_WIDTH / 2), um(track_y - TRACK_WIDTH / 2),
                        um(x_hi + TRACK_WIDTH / 2), um(track_y + TRACK_WIDTH / 2))
        top.shapes(m1_idx).insert(trunk)
        shapes_drawn += 1

        for x, y_center, patch_polys, padded, top_x in resolved:
            if padded:
                for pts_um in patch_polys:
                    poly = db.Polygon([db.Point(um(p.x), um(p.y)) for p in pts_um])
                    top.shapes(m1_idx).insert(poly)
                    shapes_drawn += 1
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
            top.shapes(m2_idx).insert(pad(top_x, track_y, M2_PAD_SIZE))
            top.shapes(v1_idx).insert(pad(top_x, track_y, VIA_SIZE))
            shapes_drawn += 4

        label = db.Text(net, db.Trans(um((x_lo + x_hi) / 2), um(track_y)))
        label.size = um(1.5)
        top.shapes(annot_idx).insert(label)

        _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _row_scan_box)).merged()

    print(f"drew {shapes_drawn} shapes (M1 trunks+pads, V1 vias, M2 stubs) for {len(net_stub_pts)} nets")
    if unrouted_pins:
        print(f"{len(unrouted_pins)} pin(s) left UNROUTED (open) to avoid drawing colliding fallback geometry:")
        for net, instname, pinname, x, y_center in unrouted_pins:
            print(f"  - net={net} {instname}.{pinname} at ({x:.2f},{y_center:.2f})")

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


ROW12_SHARED = dict(
    row_cfgs=[
        dict(logical_row_idx=1, phys_row_index=3, mirrored=True, escape_dir="up"),
        dict(logical_row_idx=2, phys_row_index=11, mirrored=True, escape_dir="down"),
    ],
    channel_bottom_y=4 * ROW_HEIGHT,   # 220.0
    channel_height=7 * ROW_HEIGHT,     # 385.0
    out_gds="/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_row12.gds",
    pin_map_json="/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/row12_pin_map.json",
)


if __name__ == "__main__":
    route_shared_channel(**ROW12_SHARED)
