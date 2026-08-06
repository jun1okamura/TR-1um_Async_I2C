"""
route_channel.py

Generalization of route_channel_pilot.py (design_notes.md section 22): routes
the row-internal nets of ANY single logical row into ITS OWN dedicated M1
channel (bottom margin below row 0, or top margin above row 3), not just row
3. Row 3's pilot result is reproduced exactly by calling
route_row_channel(**ROW3_PILOT) (see __main__ below) -- this is the
regression check that the generalization didn't change any behavior for the
already-validated case before trusting it for row 0.

Row 1/2's SHARED channel (both rows escape into the same channel from
opposite sides, and both rows are Y-mirrored in this design) is a separate,
harder case -- NOT handled by this script (see route_channel_shared.py).

Everything below is the same algorithm as route_channel_pilot.py (via anchor
search with GC avoidance, shared-obstacle/same-instance/exact-X direction
splitting, M2 jog escape routing, left-edge track packing) -- see that file's
comments and design_notes.md section 22 for the full rationale of each piece.
The only real generalization is:
  - which physical row index / logical row / mirror orientation to place from
    (mirror matters for recovering each instance's true absolute origin AND
    for transforming each pin's local polygon into absolute coordinates --
    row 0/row 3 both happen to be unmirrored, but the function accepts
    mirrored=True too, for row 1/2's later use)
  - which side of the row the channel is on (escape_dir='up': channel above,
    row 3's case; escape_dir='down': channel below, row 0's case) -- this
    changes the direction obstruction-search and jog-search look, but the
    actual M2 core/pad drawing already worked in either direction unchanged
    (it always sorts y0/y1 by min/max)
"""
import re
import os
import sys
import json

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
GDS_LIB = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/libraries/TR-1um_STDCELL.gds"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout.gds"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"

M1_LAYER = (13, 0)
V1_LAYER = (19, 0)
M2_LAYER = (20, 0)
GC_LAYER = (8, 1)
CO_LAYER = (11, 0)  # Contact (poly/diffusion-to-M1) -- real DRC deck rule
                     # 'V1.CO:V1 overlap CO' / 'V1.CO:V1-CO Smin < 1.0'
                     # (tech/drc/run.drc line 234-235), not checked by this
                     # project's own simplified drc_check_full.py -- found
                     # via the user's actual KLayout DRC run (8 violations,
                     # design_notes.md section 28).
PIN_TEXT_LAYER = (48, 0)

V1_GC_MIN_SPACE = 1.2
V1_CO_MIN_SPACE = 1.0
VIA_SIZE = 1.4
GC_KEEPOUT_UM = V1_GC_MIN_SPACE + VIA_SIZE / 2.0
CO_KEEPOUT_UM = V1_CO_MIN_SPACE + VIA_SIZE / 2.0
VIA_PAD = 4.0
M2_CORE_WIDTH = 3.1
M2_PAD_SIZE = VIA_SIZE + 2.0

ROW_HEIGHT = 55.0
M1_MIN_WIDTH = 1.8
M1_MIN_SPACE = 1.4
M2_MIN_WIDTH = 3.0
M2_MIN_SPACE = 2.0
TRACK_WIDTH = VIA_PAD
TRACK_PITCH = TRACK_WIDTH + M1_MIN_SPACE + 1.0
VIA_MARGIN_UM = VIA_SIZE / 2.0 + 1.0
DRC_GRID = 0.05


def parse_sym(path):
    pins = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'^B \S+ (\S+) (\S+) (\S+) (\S+) \{name=(\w+) dir=(\w+)\}', line)
            if m:
                _x1, _y1, _x2, _y2, name, direction = m.groups()
                pins[name] = direction
    return pins


def route_row_channel(logical_row_idx, phys_row_index, mirrored, channel_bottom_y,
                       channel_height, escape_dir, out_gds, pin_map_json,
                       annot_layer=(250, 1), row_annot_layer=(250, 0), allowed_nets=None,
                       in_gds=None):
    """Route the logical_row_idx-internal nets into the dedicated channel
    described by (channel_bottom_y, channel_height), whose near edge touches
    the row at phys_row_index (physical row index in gen_gds_placement.py's
    PHYSICAL_ROWS). escape_dir is 'up' (channel above the row) or 'down'
    (channel below). mirrored must match gen_gds_placement.py's own
    orientation for this row (design_notes.md section 27: alternating
    Y-mirror by physical row index, phys_row_index % 2 == 1, is back for
    every physical row -- real and filler alike -- to keep VDD/GND rail
    polarity and N-well/P-well banding continuous; route_all_channels.py
    computes this per row, not hardcoded).

    allowed_nets, if given, restricts routing to that net-name subset --
    used by route_all_channels.py to split a row's own internal nets
    between its two candidate channels (every row now touches two shared
    channels, one on each side) so the same net isn't routed twice.

    in_gds, if given, overrides the module-level IN_GDS (the pristine
    placement-only GDS) as the starting point -- route_all_channels.py
    chains this to the PREVIOUS channel's out_gds so each channel's
    obstruction-avoidance scan can see whatever a channel sharing one of
    its rows already routed (design_notes.md section 26.8: routing every
    channel independently against the same pristine base left each one
    blind to a sibling channel touching the same row from the other side,
    which showed up as real M1/M2 collisions once all 6 outputs were
    merged into one GDS)."""
    assert escape_dir in ("up", "down")
    IN_GDS_EFF = in_gds if in_gds is not None else IN_GDS

    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

    # ---------- library: real pin (x,y) + M1 box per (celltype, pinname) ----------
    lib = db.Layout()
    lib.read(GDS_LIB)
    ldbu = lib.dbu
    lib_pin_text_idx = lib.layer(*PIN_TEXT_LAYER)
    lib_m1_idx = lib.layer(*M1_LAYER)
    lib_gc_idx = lib.layer(*GC_LAYER)
    lib_co_idx = lib.layer(*CO_LAYER)

    gc_cache = {}
    co_cache = {}

    def cell_gc_forbidden(celltype):
        if celltype not in gc_cache:
            c = lib.cell(celltype)
            gc_region = db.Region(c.begin_shapes_rec(lib_gc_idx))
            keepout_ldbu = int(round(GC_KEEPOUT_UM / ldbu))
            gc_cache[celltype] = gc_region.sized(keepout_ldbu)
        return gc_cache[celltype]

    def cell_co_forbidden(celltype):
        if celltype not in co_cache:
            c = lib.cell(celltype)
            co_region = db.Region(c.begin_shapes_rec(lib_co_idx))
            keepout_ldbu = int(round(CO_KEEPOUT_UM / ldbu))
            co_cache[celltype] = co_region.sized(keepout_ldbu)
        return co_cache[celltype]

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

    # ---------- netlist parse ----------
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

    # ---------- row placement ----------
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)
    row = rows[logical_row_idx]
    row_names = set(n for n, t, w in row)

    pr_bbox_cache = {}

    def get_pr_bbox(celltype):
        if celltype not in pr_bbox_cache:
            c = lib.cell(celltype)
            pr_idx = lib.layer(*PR_LAYER)
            pr_bbox_cache[celltype] = db.Region(c.begin_shapes_rec(pr_idx)).bbox()
        return pr_bbox_cache[celltype]

    _annot_layout = db.Layout()
    _annot_layout.read(IN_GDS_EFF)
    _annot_top = _annot_layout.cell("i2c_slave_async_layout")
    _annot_idx = _annot_layout.layer(*row_annot_layer)
    ROW_CY = phys_row_index * ROW_HEIGHT + ROW_HEIGHT / 2.0

    row_cx = {}
    it = _annot_top.begin_shapes_rec(_annot_idx)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            ax = s.text_dtrans.disp.x
            ay = s.text_dtrans.disp.y
            if abs(ay - ROW_CY) < 0.01:
                row_cx[s.text_string] = ax
        it.next()

    missing = [n for n, t, w in row if n not in row_cx]
    if missing:
        raise RuntimeError(f"{len(missing)} row{logical_row_idx} instances have no annotation "
                            f"match in {IN_GDS_EFF}: {missing[:5]}...")

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

    # ---------- existing M2 obstructions within the row + channel ----------
    _rail_scan = db.Layout()
    _rail_scan.read(IN_GDS_EFF)
    _rail_dbu = _rail_scan.dbu
    _rail_top = _rail_scan.cell("i2c_slave_async_layout")
    _rail_m1_idx = _rail_scan.layer(*M1_LAYER)
    _rail_m2_idx = _rail_scan.layer(*M2_LAYER)
    # NOTE: the row's own M2 usage (not just the channel's) can block a pin's
    # escape path too -- extend the scan down/up to cover the row itself as
    # well as the channel, on whichever side the row sits.
    if escape_dir == "up":
        _row_scan_box = db.Box(0, int(round((phys_row_index * ROW_HEIGHT) / _rail_dbu)),
                                int(round(ROW_WIDTH_UM / _rail_dbu)),
                                int(round((channel_bottom_y + channel_height) / _rail_dbu)))
    else:
        _row_scan_box = db.Box(0, int(round(channel_bottom_y / _rail_dbu)),
                                int(round(ROW_WIDTH_UM / _rail_dbu)),
                                int(round(((phys_row_index + 1) * ROW_HEIGHT) / _rail_dbu)))
    _existing_m2 = db.Region(_rail_top.begin_shapes_rec_touching(_rail_m2_idx, _row_scan_box)).merged()
    _existing_m2_original = _existing_m2
    _existing_m2_original_polys = list(_existing_m2_original.each())

    # _current_reserved_excl holds "every OTHER pin's reserved anchor slot"
    # (design_notes.md section 31: two-pass anchor reservation) -- set once
    # per pin (not per jog candidate) just before that pin's path search, so
    # a jog path can never be routed on top of a spot another pin (already
    # drawn OR not yet drawn) needs for its own via/pad. Held in a 1-element
    # list so the closures below see live updates without a `nonlocal`.
    _current_reserved_excl = [db.Region()]

    def _box_clear(l_um, b_um, r_um, t_um):
        box = db.Box(int(round(l_um / _rail_dbu)), int(round(b_um / _rail_dbu)),
                      int(round(r_um / _rail_dbu)), int(round(t_um / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        grown = db.Region(box).sized(clearance_ldbu)
        if grown.interacting(_existing_m2).count() > 0:
            return False
        if grown.interacting(_current_reserved_excl[0]).count() > 0:
            return False
        return True

    def _m2_run_clear(x_um, y0_um, y1_um, half_width_um):
        ylo, yhi = (y0_um, y1_um) if y0_um <= y1_um else (y1_um, y0_um)
        run = db.Box(int(round((x_um - half_width_um) / _rail_dbu)), int(round(ylo / _rail_dbu)),
                      int(round((x_um + half_width_um) / _rail_dbu)), int(round(yhi / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        grown = db.Region(run).sized(clearance_ldbu)
        if grown.interacting(_existing_m2).count() > 0:
            return False
        if grown.interacting(_current_reserved_excl[0]).count() > 0:
            return False
        return True

    def abs_pin_anchor(instname, pinname):
        typ = dict((n, t) for n, t, w in row)[instname]
        poly = cell_pin_poly(typ, pinname)
        ox, oy = inst_origin[instname]
        forbid = cell_gc_forbidden(typ) + cell_co_forbidden(typ)

        margin_ldbu = int(round(VIA_MARGIN_UM / ldbu))

        def safe_region(region):
            return region.sized(-margin_ldbu) - forbid

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

    # ---------- identify row-internal nets ----------
    internal_nets = []
    for net, pins in net_pins.items():
        inst_names = set(p[0] for p in pins)
        if not inst_names:
            continue
        if inst_names & row_names and inst_names <= row_names:
            if allowed_nets is not None and net not in allowed_nets:
                continue
            internal_nets.append((net, pins))

    print(f"row{logical_row_idx} instances: {len(row_names)}, nets in scope: {len(internal_nets)}")

    net_stub_pts = {}
    net_pin_names = {}
    for net, pins in internal_nets:
        pts = []
        names = []
        for instname, typ, pinname in pins:
            vx, vy, patch_polys, padded = abs_pin_anchor(instname, pinname)
            pts.append((vx, vy, patch_polys, padded))
            names.append((instname, pinname))
        net_stub_pts[net] = pts
        net_pin_names[net] = names

    # ---------- two-pass anchor reservation (design_notes.md section 31) ----------
    # Reserve every pin's own via/pad anchor slot BEFORE any routing starts,
    # so no net's jog geometry can ever be drawn on top of a spot a LATER
    # net's pin still needs. This directly targets the dominant failure mode
    # found in section 29.4: ~80% of unrouted pins failed not because no jog
    # path existed, but because the pin's own anchor position was already
    # covered by an earlier-processed net's M2 (a resource-contention /
    # net-ordering problem, not a path-search problem).
    _pin_own_box = {}
    _reserved_region_all = db.Region()
    _RESV_HALF = M2_PAD_SIZE / 2.0
    for net, names in net_pin_names.items():
        for (instname, pinname), (vx, vy, _patch, _padded) in zip(names, net_stub_pts[net]):
            b = db.Box(int(round((vx - _RESV_HALF) / _rail_dbu)), int(round((vy - _RESV_HALF) / _rail_dbu)),
                       int(round((vx + _RESV_HALF) / _rail_dbu)), int(round((vy + _RESV_HALF) / _rail_dbu)))
            _pin_own_box[(instname, pinname)] = b
            _reserved_region_all.insert(b)
    _reserved_region_all = _reserved_region_all.merged()

    # ---------- pre-pass: shared-obstacle / same-instance / exact-X grouping ----------
    HALF_PAD = M2_PAD_SIZE / 2.0
    # The row's own near-channel edge (where pre-existing M2 obstructions
    # are searched up/down to) -- row's near edge facing the channel.
    ROW_NEAR_EDGE_Y = (phys_row_index + 1) * ROW_HEIGHT if escape_dir == "up" else phys_row_index * ROW_HEIGHT

    def _blocking_obstruction_index(x, y_center):
        y_near = y_center - HALF_PAD if escape_dir == "up" else y_center + HALF_PAD
        if _m2_run_clear(x, y_near, ROW_NEAR_EDGE_Y, HALF_PAD):
            return None
        ylo, yhi = (y_near, ROW_NEAR_EDGE_Y) if y_near <= ROW_NEAR_EDGE_Y else (ROW_NEAR_EDGE_Y, y_near)
        run = db.Box(int(round((x - HALF_PAD) / _rail_dbu)), int(round(ylo / _rail_dbu)),
                      int(round((x + HALF_PAD) / _rail_dbu)), int(round(yhi / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        grown = db.Region(run).sized(clearance_ldbu)
        for i, p in enumerate(_existing_m2_original_polys):
            if grown.interacting(db.Region(p)).count() > 0:
                return i
        return None

    all_pins = []
    blocked_by = {}
    for net, names in net_pin_names.items():
        for (instname, pinname), (vx, vy, _patch, _padded) in zip(names, net_stub_pts[net]):
            all_pins.append((instname, pinname, vx, vy))
            idx = _blocking_obstruction_index(vx, vy)
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
    for instname, pinname, x, y in all_pins:
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
        ni, pi, xi, yi = all_pins_sorted[i]
        for j in range(i + 1, len(all_pins_sorted)):
            nj, pj, xj, yj = all_pins_sorted[j]
            if xj - xi >= ADJACENT_LINK_DIST_UM:
                break
            if abs(yi - yj) < 2.0:
                uf_union((ni, pi), (nj, pj))

    groups = {}
    for n, p, x, y in all_pins:
        key = (n, p)
        if key in blocked_by or key in uf_parent:
            groups.setdefault(uf_find(key), []).append((x, n, p))

    EXACT_X_EPS = 0.01
    _pins_by_x = {}
    for n, p, x, y in all_pins:
        _pins_by_x.setdefault(round(x / EXACT_X_EPS), []).append((n, p))
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

    # ---------- available track Y slots ----------
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

    # ---------- left-edge track assignment ----------
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
    assert n_tracks <= len(track_slots), f"row{logical_row_idx} channel overflowed its track budget"

    # ---------- emit geometry ----------
    layout = db.Layout()
    layout.read(IN_GDS_EFF)
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

    ALL_MAGS = (2, 4, 6, 8, 10, 14, 18, 24, 30, 40, 50, 60, 80, 100,
                130, 160, 200, 250, 300, 400, 500, 650, 800)

    def _find_jog_x_range(vx, y0, y1, preferred_dir=None, skip_rank=0, must_jog=False, mags=ALL_MAGS):
        """Single-bend (L-shape) search: find an x where the vertical run
        [y0,y1] at that x is clear, AND the horizontal traverse from vx to
        that x (at y0) is clear. Used both for the simple pin->track case
        and, with an arbitrary (y0,y1) sub-span, as a building block for
        the two-bend fallback below."""
        half = M2_PAD_SIZE / 2.0
        if not must_jog and _m2_run_clear(vx, y0 - half, y1 + half, half):
            return vx
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
            if not _m2_run_clear(jx, y0 - half, y1 + half, half):
                continue
            lo, hi = (vx, jx) if vx <= jx else (jx, vx)
            if not _box_clear(lo, y0 - half, hi, y0 + half):
                continue
            return jx
        return None

    LOCAL_MAGS = ALL_MAGS[:14]  # up to 24um -- "just clear the immediate obstruction" scale

    def _find_jog_path(vx, y_center, track_y, preferred_dir=None, skip_rank=0, must_jog=False):
        """Returns a waypoint list [(x0,y0), (x1,y1), ...] from the pin to
        the track, or None if unroutable. Tries the plain single-bend
        (L-shape) path first (unchanged behavior); if every x in that
        search collides SOMEWHERE along the full pin->track run, that
        means the straight path is blocked no matter where it jogs to --
        widening the search magnitude or the channel can't fix that (both
        were tried and made zero difference: design_notes.md section 29).
        Falls back to a two-bend (Z-shape) path: a short local escape jog
        near the pin, then a full jog search from that intermediate point
        to the track -- lets the path route AROUND a mid-run obstruction
        instead of requiring one straight vertical run to be entirely
        clear."""
        top_x = _find_jog_x_range(vx, y_center, track_y, preferred_dir, skip_rank, must_jog)
        if top_x is not None:
            return [(vx, y_center), (top_x, y_center), (top_x, track_y)]

        span = track_y - y_center
        for frac in (0.25, 0.4, 0.5, 0.6, 0.75):
            y_mid = y_center + span * frac
            jx1 = _find_jog_x_range(vx, y_center, y_mid, preferred_dir, skip_rank,
                                     must_jog=True, mags=LOCAL_MAGS)
            if jx1 is None:
                continue
            jx2 = _find_jog_x_range(jx1, y_mid, track_y, preferred_dir, 0, must_jog=True)
            if jx2 is None:
                continue
            return [(vx, y_center), (jx1, y_center), (jx1, y_mid), (jx2, y_mid), (jx2, track_y)]
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
        zshape_count = 0
        for (instname, pinname), (x, y_center, patch_polys, padded) in zip(names, pts):
            pref = forced_dir.get((instname, pinname))
            rank = forced_rank.get((instname, pinname), 0)
            mj = (instname, pinname) in must_jog
            if os.environ.get("ROUTE_DEBUG_PIN") == f"{instname}.{pinname}":
                print(f"DEBUG {instname}.{pinname}: x={x} y_center={y_center} track_y={track_y} "
                      f"pref={pref} rank={rank} must_jog={mj}", file=sys.stderr)
            own_box = _pin_own_box.get((instname, pinname))
            _current_reserved_excl[0] = (_reserved_region_all - db.Region(own_box)) \
                if own_box is not None else _reserved_region_all
            path = _find_jog_path(x, y_center, track_y, preferred_dir=pref, skip_rank=rank, must_jog=mj)
            if path is None:
                # Do NOT fall back to an unjogged (top_x=x) stub here: the
                # jog search already proved the direct run isn't clear, so
                # drawing it anyway guarantees a collision -- and that bad
                # geometry then gets folded into _existing_m2 for later nets,
                # cascading failures (see design_notes.md route_cross_row.py
                # discussion). Leave the pin OPEN (unrouted) instead; a known
                # open is far cheaper to fix than a cascading short.
                print(f"WARNING: net {net} pin {instname}.{pinname} at ({x:.2f},{y_center:.2f}): "
                      f"no clear M2 jog found within search range (incl. 2-bend fallback); "
                      f"leaving UNROUTED (open)")
                unrouted_pins.append((net, instname, pinname, x, y_center))
                continue
            top_x = path[-1][0]
            if len(path) > 3:
                zshape_count += 1
            resolved.append((x, y_center, patch_polys, padded, top_x))

            # Draw this pin's own M2/V1 shapes immediately (not after the
            # whole net) and refresh _existing_m2 right away -- this lets
            # the NEXT pin's jog search see it even within the SAME net.
            # Two pins of one net (e.g. a shared-obstacle/forced-direction
            # sibling pair) previously could both be resolved against the
            # same pre-net _existing_m2 snapshot and land close enough to
            # violate M2 spacing against EACH OTHER without either check
            # catching it (design_notes.md section 28.2) -- this was the
            # root cause of a handful of persistent residual M2 violations.
            if padded:
                for pts_um in patch_polys:
                    poly = db.Polygon([db.Point(um(p.x), um(p.y)) for p in pts_um])
                    top.shapes(m1_idx).insert(poly)
                    shapes_drawn += 1
            top.shapes(v1_idx).insert(pad(x, y_center, VIA_SIZE))
            top.shapes(m2_idx).insert(pad(x, y_center, M2_PAD_SIZE))

            # Walk the path (2 waypoints for a plain L-shape, 4 for a
            # 2-bend Z-shape fallback), drawing each segment and a pad at
            # every intermediate bend (no via needed -- same M2 layer).
            for i in range(len(path) - 1):
                (xa, ya), (xb, yb) = path[i], path[i + 1]
                if xa == xb:
                    y0, y1 = (ya, yb) if ya <= yb else (yb, ya)
                    top.shapes(m2_idx).insert(db.Box(um(xa - M2_CORE_WIDTH / 2), um(y0 - 0.3),
                                                      um(xa + M2_CORE_WIDTH / 2), um(y1 + 0.3)))
                else:
                    lo, hi = (xa, xb) if xa <= xb else (xb, xa)
                    lo -= M2_CORE_WIDTH / 2
                    hi += M2_CORE_WIDTH / 2
                    top.shapes(m2_idx).insert(db.Box(um(lo), um(ya - M2_PAD_SIZE / 2),
                                                      um(hi), um(ya + M2_PAD_SIZE / 2)))
                shapes_drawn += 1
                if 0 < i < len(path) - 1:
                    top.shapes(m2_idx).insert(pad(xa, ya, M2_PAD_SIZE))
                    shapes_drawn += 1

            top.shapes(m2_idx).insert(pad(top_x, track_y, M2_PAD_SIZE))
            top.shapes(v1_idx).insert(pad(top_x, track_y, VIA_SIZE))
            shapes_drawn += 2

            _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _row_scan_box)).merged()

        if not resolved:
            print(f"WARNING: net {net}: ALL pins failed to route; net left fully unrouted")
            continue
        if zshape_count:
            print(f"  net {net}: {zshape_count} pin(s) used the 2-bend Z-shape fallback path")

        top_xs = [r[4] for r in resolved]
        x_lo, x_hi = min(top_xs), max(top_xs)

        trunk = db.Box(um(x_lo - TRACK_WIDTH / 2), um(track_y - TRACK_WIDTH / 2),
                        um(x_hi + TRACK_WIDTH / 2), um(track_y + TRACK_WIDTH / 2))
        top.shapes(m1_idx).insert(trunk)
        shapes_drawn += 1

        label = db.Text(net, db.Trans(um((x_lo + x_hi) / 2), um(track_y)))
        label.size = um(1.5)
        top.shapes(annot_idx).insert(label)

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


# NOTE: the old fixed ROW3_PILOT/ROW0_CHANNEL configs (4-row/mirrored-pair
# era) were removed in design_notes.md section 26's rearchitecture -- the
# two dedicated end-margin channels (below row0, above row4) now have their
# phys_row_index/channel_bottom_y/channel_height built dynamically by
# route_all_channels.py from gen_gds_placement.py's PHYSICAL_ROWS. Run this
# module via route_all_channels.py, not standalone.
