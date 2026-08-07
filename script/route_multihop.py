"""
route_multihop.py

Final routing pass for "multi-hop" nets (design_notes.md section 33):
nets whose pins sit in non-adjacent rows, or span 3+ rows, which
route_all_channels.py explicitly does NOT handle -- its channel routers
(route_channel.py / route_channel_shared.py) only connect pins within a
single channel's scope (one row, or one adjacent row pair sharing a
channel). A net like `scl_buf0` (rows [0,1,2,3]) has no single channel
that touches all its pins.

Each multi-hop net's pins are sorted by absolute Y and connected pairwise
(bottom to top) with a Lee/BFS maze-searched path on a coarse grid.

design_notes.md section 34.12: the grid is layer-aware. A vertical move
is always on M2 (crossing through a cell row -- no via needed against
that row's own M1, since there's no electrical overlap, same principle
already used by the old route_cross_row.py, section 23.5). A horizontal
move is only legal, and only ever drawn, on M1, and only while inside a
channel band (a filler-only physical row between/around the real cell
rows) -- mirroring the channel routers' own M1-trunk-at-track-height
convention, just generalized across multiple channels instead of one.
Every interior bend in the simplified path is therefore a genuine
M1<->M2 transition and gets a real via.

This runs as a genuinely FINAL pass, reading
Layout/i2c_slave_async_layout_routed_all.gds (the fully accumulated
6-channel output) and writing back to the same file, so its obstruction
scan sees every channel's already-drawn geometry.

Usage:
    python3 script/route_multihop.py
"""
import os
import re
import sys
import json
from collections import defaultdict

import klayout.db as db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402
from gen_gds_placement import PHYSICAL_ROWS  # noqa: E402
import route_channel as rc  # noqa: E402

ROW_HEIGHT = rc.ROW_HEIGHT
M1_MIN_SPACE = rc.M1_MIN_SPACE
M2_MIN_SPACE = rc.M2_MIN_SPACE
VIA_SIZE = rc.VIA_SIZE
VIA_MARGIN_UM = rc.VIA_MARGIN_UM
M2_CORE_WIDTH = rc.M2_CORE_WIDTH
M2_PAD_SIZE = rc.M2_PAD_SIZE
GC_KEEPOUT_UM = rc.GC_KEEPOUT_UM
CO_KEEPOUT_UM = rc.CO_KEEPOUT_UM
DRC_GRID = rc.DRC_GRID
M1_LAYER = rc.M1_LAYER
V1_LAYER = rc.V1_LAYER
M2_LAYER = rc.M2_LAYER
GC_LAYER = rc.GC_LAYER
CO_LAYER = rc.CO_LAYER
PIN_TEXT_LAYER = rc.PIN_TEXT_LAYER
STDCELL_DIR = rc.STDCELL_DIR
GDS_LIB = rc.GDS_LIB
NET_FILE = rc.NET_FILE

IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_all.gds"
OUT_GDS = IN_GDS  # write back in place -- this is the final pass
ANNOT_LAYER = (250, 0)  # per-instance name annotation, written by gen_gds_placement.py
MULTIHOP_ANNOT_LAYER = (250, 4)


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
    for typ, name, conns in instances:
        for pin, expr in conns.items():
            d = sym_pins[typ].get(pin)
            if d == 'inout':
                continue
            net_pins[canon(expr)].append((name, typ, pin))
    return net_pins, sym_pins


def main():
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)
    phys_of_row = {}
    for i, e in enumerate(PHYSICAL_ROWS):
        if e is not None:
            phys_of_row[e] = i

    row_of = {}
    inst_typ = {}
    for i, row in enumerate(rows):
        for n, t, w in row:
            row_of[n] = i
            inst_typ[n] = t

    net_pins, sym_pins = _parse_nets()
    net_rows = {}
    for net, pins in net_pins.items():
        rs = set(row_of[p[0]] for p in pins if p[0] in row_of)
        net_rows[net] = rs

    multi_hop_nets = []
    for net, rs in net_rows.items():
        if len(rs) < 2:
            continue
        rs_sorted = sorted(rs)
        is_adjacent_pair = len(rs) == 2 and rs_sorted[1] == rs_sorted[0] + 1
        if not is_adjacent_pair:
            multi_hop_nets.append((net, rs))

    print(f"{len(multi_hop_nets)} multi-hop net(s) to route:")
    for net, rs in multi_hop_nets:
        print(f"  net={net} rows={sorted(rs)}")

    # ---------- cell library: pin polygons + GC/CO forbidden regions ----------
    lib = db.Layout()
    lib.read(GDS_LIB)
    ldbu = lib.dbu
    lib_pin_text_idx = lib.layer(*PIN_TEXT_LAYER)
    lib_m1_idx = lib.layer(*M1_LAYER)
    lib_gc_idx = lib.layer(*GC_LAYER)
    lib_co_idx = lib.layer(*CO_LAYER)
    pr_layer_idx = lib.layer(*PR_LAYER)

    gc_cache = {}
    co_cache = {}
    pr_bbox_cache = {}

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

    # ---------- absolute instance origin for EVERY row (not just one channel's) ----------
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell("i2c_slave_async_layout")
    annot_idx = layout.layer(*ANNOT_LAYER)
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)
    mh_annot_idx = layout.layer(*MULTIHOP_ANNOT_LAYER)

    needed_insts = set()
    for net, rs in multi_hop_nets:
        for instname, typ, pinname in net_pins[net]:
            needed_insts.add(instname)

    row_cx = {}
    it = top.begin_shapes_rec(annot_idx)
    while not it.at_end():
        s = it.shape()
        # Unlike before section 34.13, this scan is NOT restricted to
        # needed_insts -- every placed instance (real cells AND filler
        # cells alike) is annotated by gen_gds_placement.py, and the new
        # inter-cell-FILL-gap computation below needs every REAL cell's
        # absolute X across every row, not just the ones that happen to
        # own a multi-hop net's pin.
        if s.is_text():
            row_cx[s.text_string] = s.text_dtrans.disp.x
        it.next()
    missing = needed_insts - set(row_cx)
    if missing:
        raise RuntimeError(f"{len(missing)} instances missing annotation: {sorted(missing)[:5]}...")

    inst_origin = {}  # instname -> (tx, ty, mirrored)
    for instname in needed_insts:
        logical_row_idx = row_of[instname]
        phys_row_index = phys_of_row[logical_row_idx]
        mirrored = (phys_row_index % 2 == 1)
        typ = inst_typ[instname]
        bbox = get_pr_bbox(typ)
        bleft = bbox.left * ldbu
        bbottom = bbox.bottom * ldbu
        btop = bbox.top * ldbu
        width = bbox.width() * ldbu
        cx = row_cx[instname]
        tx = cx - (bleft + width / 2.0)
        if not mirrored:
            ty = phys_row_index * ROW_HEIGHT - bbottom
        else:
            ty = phys_row_index * ROW_HEIGHT + btop
        inst_origin[instname] = (tx, ty, mirrored, typ)

    # ---------- per-row real-cell X extents + inter-cell FILL gaps ----------
    # design_notes.md section 34.13: outside a channel band, M2 may run
    # horizontally only as far as the FILL slot immediately next to a
    # cell -- never directly over another real (non-filler) cell. Build
    # every real cell's absolute [left,right] extent (X placement doesn't
    # depend on the mirrored flag, only Y does -- same tx formula as
    # inst_origin above) so the gaps between consecutive real cells in a
    # row -- which the "always >=1 FILL between cells" placement policy
    # guarantees are filler-only -- can be precomputed once, up front,
    # for every row (not just rows touched by a multi-hop net's pins).
    _row_of_phys = {v: k for k, v in phys_of_row.items()}

    def _cell_x_extent(instname):
        typ = inst_typ[instname]
        bbox = get_pr_bbox(typ)
        bleft = bbox.left * ldbu
        width = bbox.width() * ldbu
        cx = row_cx[instname]
        tx = cx - (bleft + width / 2.0)
        left = tx + bleft
        return left, left + width

    _gap_ranges_by_row = {}
    for _ridx, _row in enumerate(rows):
        _names = [n for n, t, w in _row if n in row_cx]
        _extents = sorted((_cell_x_extent(n) for n in _names), key=lambda e: e[0])
        _gaps = []
        for (l0, r0), (l1, r1) in zip(_extents, _extents[1:]):
            if r0 < l1 - 1e-6:
                _gaps.append((r0, l1))
        _gap_ranges_by_row[_ridx] = _gaps

    def _row_at_y(y_um):
        pidx = int(y_um // ROW_HEIGHT)
        return _row_of_phys.get(pidx)

    def _h_leg_layer(y_um, x0_um, x1_um):
        """Which layer (if any) a horizontal run at y_um from x0_um to
        x1_um is allowed to use. 'M1' inside a channel band (any X).
        'M2' inside a single cell row's inter-cell FILL gap -- the WHOLE
        span must stay within one gap, never crossing onto a real cell.
        None if neither applies (not legal at all)."""
        if _is_channel_y(y_um):
            return 'M1'
        ridx = _row_at_y(y_um)
        if ridx is None:
            return None
        xlo, xhi = (x0_um, x1_um) if x0_um <= x1_um else (x1_um, x0_um)
        for l, r in _gap_ranges_by_row.get(ridx, ()):
            if l - 1e-6 <= xlo and xhi <= r + 1e-6:
                return 'M2'
        return None

    def abs_pin_anchor(instname, pinname):
        tx, ty, mirrored, typ = inst_origin[instname]
        poly = cell_pin_poly(typ, pinname)
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
            vx, vy = local_x + tx, local_y + ty
        else:
            vx, vy = local_x + tx, -local_y + ty

        patch_polys_abs = []
        if grown_um > 0.0:
            for p in used.each():
                pts = []
                for pt in p.each_point_hull():
                    lx, ly = pt.x * ldbu, pt.y * ldbu
                    if not mirrored:
                        pts.append(db.DPoint(lx + tx, ly + ty))
                    else:
                        pts.append(db.DPoint(lx + tx, -ly + ty))
                patch_polys_abs.append(pts)
        return vx, vy, patch_polys_abs, grown_um > 0.0

    # ---------- existing M1/M2 obstruction: the WHOLE accumulated layout ----------
    core_h = len(PHYSICAL_ROWS) * ROW_HEIGHT
    _full_box = db.Box(0, 0, int(round(ROW_WIDTH_UM / dbu)), int(round(core_h / dbu)))
    _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _full_box)).merged()
    _existing_m1 = db.Region(top.begin_shapes_rec_touching(m1_idx, _full_box)).merged()

    # ---------- channel Y-bands: where a horizontal run is allowed to switch
    # to M1 (design_notes.md section 34.12). PHYSICAL_ROWS[i] is None for a
    # filler-only physical row (an empty routing channel between/around the
    # real cell rows) and an int (logical row index) for a row that's full
    # of standard cells -- same convention gen_gds_placement.py/
    # route_channel_shared.py already use. A pin always sits inside a
    # non-None (cell) row, so this never classifies a pin's own anchor Y as
    # "channel".
    _channel_bands = []
    _i = 0
    while _i < len(PHYSICAL_ROWS):
        if PHYSICAL_ROWS[_i] is None:
            _j = _i
            while _j < len(PHYSICAL_ROWS) and PHYSICAL_ROWS[_j] is None:
                _j += 1
            _channel_bands.append((_i * ROW_HEIGHT, _j * ROW_HEIGHT))
            _i = _j
        else:
            _i += 1

    def _is_channel_y(y_um, tol=1e-6):
        return any(lo - tol <= y_um <= hi + tol for lo, hi in _channel_bands)

    M1_CORE_WIDTH = 2.0  # comfortably above M1_MIN_WIDTH=1.8

    def _box_clear_region(l_um, b_um, r_um, t_um, region, min_space_um):
        box = db.Box(int(round(l_um / dbu)), int(round(b_um / dbu)),
                      int(round(r_um / dbu)), int(round(t_um / dbu)))
        clearance_ldbu = int(round(min_space_um / dbu))
        return db.Region(box).sized(clearance_ldbu).interacting(region).count() == 0

    def _vrun_clear(x_um, y0_um, y1_um, half_width_um):
        # Vertical run -- always M2 (crosses through cell rows, no
        # horizontal drift while doing so).
        ylo, yhi = (y0_um, y1_um) if y0_um <= y1_um else (y1_um, y0_um)
        return _box_clear_region(x_um - half_width_um, ylo, x_um + half_width_um, yhi,
                                  _existing_m2, M2_MIN_SPACE)

    half_m2 = M2_PAD_SIZE / 2.0
    half_m1 = M1_CORE_WIDTH / 2.0 + 0.15  # same +0.15 check-vs-draw margin as M2 (PAD_SIZE/2=1.7 vs CORE_WIDTH/2=1.55)

    def _hrun_clear(y_um, x0_um, x1_um):
        # Horizontal run -- design_notes.md section 34.13: 'M1' if y is
        # inside a channel band (any X -- inter-cell connections switch to
        # M1 there, section 34.12), 'M2' if y is inside a cell row AND the
        # WHOLE [x0,x1] span stays within a single inter-cell FILL gap
        # (never crossing onto a real cell). Neither -> not legal at all.
        layer = _h_leg_layer(y_um, x0_um, x1_um)
        if layer is None:
            return False
        xlo, xhi = (x0_um, x1_um) if x0_um <= x1_um else (x1_um, x0_um)
        if layer == 'M1':
            return _box_clear_region(xlo, y_um - half_m1, xhi, y_um + half_m1,
                                      _existing_m1, M1_MIN_SPACE)
        else:
            return _box_clear_region(xlo, y_um - half_m2, xhi, y_um + half_m2,
                                      _existing_m2, M2_MIN_SPACE)

    def _bend_pad_clear(x_um, y_um):
        # A genuine M1<->M2 transition bend draws a M2_PAD_SIZE guarantee
        # pad on BOTH layers (plus a V1 via) -- section 34.14 root-caused
        # 5 new "M1 space<1.4" violations to exactly this pad landing too
        # close (by as little as 0.2um) to already-existing M1, either a
        # channel router's own 4.0um-wide trunk or a standard cell's own
        # M1 pin shape, because this pad was drawn completely unchecked,
        # unlike every other pad-drawing site in this project. Require
        # BOTH layers clear before allowing a bend here at all.
        half = M2_PAD_SIZE / 2.0
        return (_box_clear_region(x_um - half, y_um - half, x_um + half, y_um + half,
                                   _existing_m1, M1_MIN_SPACE)
                and _box_clear_region(x_um - half, y_um - half, x_um + half, y_um + half,
                                       _existing_m2, M2_MIN_SPACE))

    # A simple 2-3 segment elbow/Z-shape (fixed-height horizontal runs at
    # each pin's own Y, single free-X vertical trunk) was tried first and
    # failed 100% of the time: a full sweep confirmed that a handful of
    # columns ARE clear for the FULL chip height (~14 out of 900), but
    # reaching them requires a horizontal run at the pin's OWN Y -- and
    # that row-edge Y band is exactly the densest, most congested part of
    # the layout (same finding as section 29.4/32), so a single unbroken
    # horizontal bridge at fixed Y almost always hits something along the
    # way, even when the destination column is globally clear. This is the
    # same "single-bend jog can't dodge a mid-run obstruction" problem
    # from section 29, just at chip scale instead of channel scale.
    #
    # Fix: a real bounded maze search (Lee/BFS on a coarse grid) instead of
    # a fixed-shape heuristic -- exactly the "true fix" flagged as future
    # work since section 22.5. Only 15 nets / ~100 segments need this, so
    # the cost of a proper grid search here is small (unlike retrofitting
    # it into the channel routers, which each resolve hundreds of pins).
    #
    # design_notes.md section 34.12: the grid is now LAYER-AWARE -- a
    # horizontal move is only legal from a grid row whose Y falls inside a
    # channel band (and is checked/drawn on M1); a vertical move is always
    # legal (checked/drawn on M2). This forces every net to switch to M1
    # before making any lateral progress, instead of running M2 straight
    # across cell rows the way the single-layer version did.
    GRID_STEP = 3.0  # um (down from 6.0 -- section 34.12's layer-restricted
    # search has much less freedom per step than the old single-layer one
    # (no horizontal escape outside a channel band), so a coarser grid's
    # conservative bbox-rasterization dead-ends far more easily right next
    # to a pin, where nearby M2 is densest)
    core_h_i = core_h
    nx = int(ROW_WIDTH_UM // GRID_STEP) + 1
    ny = int(core_h_i // GRID_STEP) + 1

    # design_notes.md section 34.13: per-grid-cell horizontal-move
    # eligibility, precomputed once. 0 = forbidden (over a real cell,
    # outside any channel/gap). 1 = M1 (inside a channel band -- any X).
    # 2 = M2 (inside a cell row's inter-cell FILL gap at this X).
    _h_layer_grid = bytearray(nx * ny)
    for _gy in range(ny):
        _y_um = _gy * GRID_STEP
        _base = _gy * nx
        if _is_channel_y(_y_um):
            for _gx in range(nx):
                _h_layer_grid[_base + _gx] = 1
        else:
            _ridx = _row_at_y(_y_um)
            _gaps = _gap_ranges_by_row.get(_ridx, ()) if _ridx is not None else ()
            if _gaps:
                for _gx in range(nx):
                    _x_um = _gx * GRID_STEP
                    for _l, _r in _gaps:
                        if _l - 1e-6 <= _x_um <= _r + 1e-6:
                            _h_layer_grid[_base + _gx] = 2
                            break

    def _rasterize_blocked(region, min_space_um):
        """Bbox-per-polygon rasterization of a (clearance-grown) Region
        onto the coarse grid -- conservative (a polygon's bbox can exceed
        its own area for non-rectangular merged shapes) but fast, and
        erring toward "blocked" only costs a slightly less direct path,
        never a DRC violation."""
        blocked = bytearray(nx * ny)
        clearance_ldbu = int(round(min_space_um / dbu))
        grown = region.sized(clearance_ldbu)
        for poly in grown.each():
            bb = poly.bbox()
            l, b, r, t = bb.left * dbu, bb.bottom * dbu, bb.right * dbu, bb.top * dbu
            gx0 = max(0, int(l // GRID_STEP))
            gx1 = min(nx - 1, int(r // GRID_STEP))
            gy0 = max(0, int(b // GRID_STEP))
            gy1 = min(ny - 1, int(t // GRID_STEP))
            for gy in range(gy0, gy1 + 1):
                base = gy * nx
                for gx in range(gx0, gx1 + 1):
                    blocked[base + gx] = 1
        return blocked

    def _bfs_path(x0, y0, x1, y1, blocked_m1, blocked_m2):
        from collections import deque
        gx0 = min(nx - 1, max(0, int(round(x0 / GRID_STEP))))
        gy0 = min(ny - 1, max(0, int(round(y0 / GRID_STEP))))
        gx1 = min(nx - 1, max(0, int(round(x1 / GRID_STEP))))
        gy1 = min(ny - 1, max(0, int(round(y1 / GRID_STEP))))
        start = gy0 * nx + gx0
        goal = gy1 * nx + gx1
        if start == goal:
            return [(x0, y0), (x1, y1)]
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == goal:
                break
            cy, cx = divmod(cur, nx)[0], cur % nx
            for dgx, dgy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ngx, ngy = cx + dgx, cy + dgy
                if ngx < 0 or ngx >= nx or ngy < 0 or ngy >= ny:
                    continue
                nxt = ngy * nx + ngx
                if nxt in prev:
                    continue
                if dgy == 0:
                    # Horizontal move -- design_notes.md section 34.13:
                    # legal on M1 inside a channel band, or on M2 inside a
                    # cell row's inter-cell FILL gap; forbidden elsewhere
                    # (directly over a real cell). Both endpoints must
                    # agree on the same layer/region -- moving from a gap
                    # straight onto a real cell (or between two different
                    # rows' gaps in one step) is not legal.
                    cur_layer = _h_layer_grid[cur]
                    nxt_layer = _h_layer_grid[nxt]
                    if cur_layer == 0 or nxt_layer != cur_layer:
                        continue
                    if cur_layer == 1:
                        if blocked_m1[nxt] and nxt != goal and cur != start:
                            continue
                    else:
                        if blocked_m2[nxt] and nxt != goal and cur != start:
                            continue
                else:
                    # Vertical move -- always legal (crosses cell rows on
                    # M2, no via needed against cell M1 since no electrical
                    # overlap). Checked against the M2 obstruction map.
                    # `cur != start` grants the pin's own anchor cell the
                    # same one-hop exemption `goal` already gets: at
                    # GRID_STEP=6.0um the coarse blocked-rasterization
                    # routinely marks a pin's immediate neighbor cell as
                    # blocked (nearby M2 within clearance of the pin's own
                    # via, not a real corridor obstruction), and -- unlike
                    # the pre-34.12 single-layer search -- there's no
                    # sideways escape available outside a channel band, so
                    # without this the search dead-ends at the very first
                    # step almost every time (found empirically: reached=1
                    # for ~100% of segments before this fix).
                    if blocked_m2[nxt] and nxt != goal and cur != start:
                        continue
                prev[nxt] = cur
                q.append(nxt)
        if goal not in prev:
            return None
        # reconstruct
        cells = []
        cur = goal
        while cur is not None:
            cy, cx = divmod(cur, nx)[0], cur % nx
            cells.append((cx * GRID_STEP, cy * GRID_STEP))
            cur = prev[cur]
        cells.reverse()
        # collapse collinear runs into a minimal orthogonal polyline
        pts = [(x0, y0)]
        for i in range(1, len(cells) - 1):
            xa, ya = cells[i - 1]
            xb, yb = cells[i]
            xc, yc = cells[i + 1]
            d1 = (xb - xa, yb - ya)
            d2 = (xc - xb, yc - yb)
            if d1 != d2:
                pts.append((xb, yb))
        pts.append((x1, y1))
        return pts

    def _find_path(x0, y0, x1, y1, blocked_m1, blocked_m2):
        return _bfs_path(x0, y0, x1, y1, blocked_m1, blocked_m2)

    def _simplify_path(path):
        """Greedy 'string pulling' shortcut pass: replace as much of the
        raw BFS staircase as possible with long single-bend hops, checked
        against the EXACT (non-grid-quantized) obstruction region -- the
        BFS grid is only needed to discover a route exists at all; once
        found, most of its zigzag detail is usually unnecessary and only
        risked introducing corner-notch DRC issues (section 33.2)."""
        if len(path) <= 2:
            return path
        result = [path[0]]
        i = 0
        n = len(path)
        while i < n - 1:
            xa, ya = path[i]
            advanced = False
            for j in range(n - 1, i, -1):
                xb, yb = path[j]
                # Option A: vertical (xa,ya)->(xa,yb) then horizontal
                # (xa,yb)->(xb,yb). The horizontal leg only exists if
                # xb != xa -- _hrun_clear itself now determines whether
                # that leg is legal at all (channel band -> M1, or a
                # single inter-cell FILL gap -> M2, section 34.13) and
                # picks the right layer/clearance check internally.
                if xb == xa:
                    if _vrun_clear(xa, ya, yb, half_m2):
                        result.append((xa, yb))
                        i = j
                        advanced = True
                        break
                elif _vrun_clear(xa, ya, yb, half_m2) and _hrun_clear(yb, xa, xb):
                    result.append((xa, yb))
                    result.append((xb, yb))
                    i = j
                    advanced = True
                    break
                # Option B: horizontal (xa,ya)->(xb,ya) then vertical
                # (xb,ya)->(xb,yb).
                if not advanced and xb != xa \
                        and _hrun_clear(ya, xa, xb) and _vrun_clear(xb, ya, yb, half_m2):
                    result.append((xb, ya))
                    result.append((xb, yb))
                    i = j
                    advanced = True
                    break
            if not advanced:
                result.append(path[i + 1])
                i += 1
        return result

    def um(v):
        return int(round(round(v / DRC_GRID) * DRC_GRID / dbu))

    def pad(cx, cy, size):
        h = size / 2.0
        return db.Box(um(cx - h), um(cy - h), um(cx + h), um(cy + h))

    shapes_drawn = 0
    unresolved_segments = []
    fully_routed_nets = []
    partially_routed_nets = []

    for net, rs in sorted(multi_hop_nets, key=lambda t: t[0]):
        # Snapshot of M2 from OTHER nets only, taken BEFORE this net draws
        # anything -- used (not the continuously-refreshed _existing_m2)
        # when clearance-checking this net's OWN touched-pin pads below.
        # A pin's pad is SUPPOSED to touch/overlap the end of its own
        # net's just-drawn trunk (that's how they electrically connect);
        # checking the pad against the live _existing_m2 (which by then
        # includes that trunk) made _box_clear reject the pad as
        # "colliding" purely because of this intentional self-overlap --
        # a false positive that, in the first version of the fix below,
        # caused far more pads to be skipped than were actually violating
        # anything (design_notes.md section 34.10).
        _other_nets_m2 = _existing_m2
        pins = net_pins[net]
        anchors = []
        for instname, typ, pinname in pins:
            vx, vy, patch_polys, padded = abs_pin_anchor(instname, pinname)
            anchors.append((vy, vx, instname, pinname, patch_polys, padded))
        anchors.sort()  # bottom to top

        # Plan+draw segments ONE AT A TIME, refreshing the blocked grid
        # after each -- two segments of the SAME net (e.g. a 4-pin net has
        # 3 chained segments) planned against a single stale snapshot could
        # otherwise cross each other undetected (same class of bug as
        # section 28.2's same-net sibling-pin collision in the channel
        # routers). Pin pads/vias are still deferred to the very end of
        # the net: drawing a pin's own pad before ITS OWN path is planned
        # would make the pin block its own outgoing search (the path
        # necessarily starts exactly at the pad's location) -- since a
        # pin can be the shared endpoint of two consecutive segments, this
        # would misfire even with per-segment interleaving. BFS separately
        # exempts the exact start/goal grid cell from the blocked check,
        # so a later segment CAN still start from a point an earlier
        # segment's path passed through/ended at.
        seg_paths = []
        for i in range(len(anchors) - 1):
            y0, x0, inst0, pin0, _p0, _pad0 = anchors[i]
            y1, x1, inst1, pin1, _p1, _pad1 = anchors[i + 1]
            blocked_m2 = _rasterize_blocked(_existing_m2, M2_MIN_SPACE)
            blocked_m1 = _rasterize_blocked(_existing_m1, M1_MIN_SPACE)
            path = _find_path(x0, y0, x1, y1, blocked_m1, blocked_m2)
            seg_paths.append(path)
            if path is None:
                print(f"WARNING: net {net}: segment {inst0}.{pin0} -> {inst1}.{pin1} "
                      f"({x0:.2f},{y0:.2f})->({x1:.2f},{y1:.2f}): no clear M1/M2 path found; "
                      f"leaving this segment UNROUTED (open)")
                unresolved_segments.append((net, inst0, pin0, inst1, pin1))
                continue
            # Simplify the raw BFS grid path (which can bend at every grid
            # step) into the minimal number of orthogonal segments before
            # drawing: greedily try to shortcut each waypoint by testing
            # whether the two segments around it can be replaced by a
            # single L-bend between its neighbors, using the EXACT (non-
            # grid-quantized) clearance check. This both produces cleaner
            # geometry (fewer corners = fewer chances for a sub-clearance
            # notch, the cause of section 33.2's negative first attempt)
            # and mirrors the channel routers' own proven box-drawing
            # style, which is already known DRC-clean for low-bend-count
            # paths.
            # NOTE: no separate bend pads are drawn at interior waypoints --
            # each segment already extends by `half` beyond its nominal
            # endpoint in its own run direction (checked: at a shared
            # corner, this gives a full M2_CORE_WIDTH x M2_CORE_WIDTH
            # overlap between the two meeting segments' boxes on its own).
            # Adding a M2_PAD_SIZE square pad on top of that was tried and
            # found to be the actual source of the one residual spacing
            # violation in section 33.2's second attempt: the pad's own
            # half-width (1.7um) is slightly WIDER than M2_CORE_WIDTH/2
            # (1.55um), so it silently protruded 0.15um past the region
            # the exact clearance check had actually verified, occasionally
            # clipping an unrelated nearby shape that the segment checks
            # alone would have avoided.
            path = _simplify_path(path)
            # Final exact-clearance verification: _simplify_path's fallback
            # (when no shortcut exists for a waypoint) passes the raw BFS
            # step through unverified, trusting the grid-based blocked
            # mask -- which is only a bbox-per-cell APPROXIMATION and can
            # occasionally be too optimistic right at a cell boundary
            # (found empirically: one segment slipped through 0.25um from
            # a real obstacle, well under the 2.0um clearance rule). Re-
            # check every segment with the exact (non-grid) test before
            # drawing anything; if any segment fails, drop the whole hop
            # as unrouted rather than draw geometry known to violate DRC
            # (same "leave open, don't draw a colliding fallback"
            # convention as every other router in this project).
            # Each leg's actual layer -- vertical legs are always M2;
            # horizontal legs are M1 (channel band) or M2 (inter-cell FILL
            # gap, section 34.13), decided by _h_leg_layer. Tracked per-leg
            # so only a genuine layer CHANGE between two consecutive legs
            # needs a via -- e.g. a vertical-M2 leg meeting a horizontal-M2
            # gap leg is already the same layer and needs no via, unlike a
            # vertical-M2 leg meeting a horizontal-M1 channel leg.
            leg_layers = [
                'M2' if path[k][0] == path[k + 1][0] else _h_leg_layer(path[k][1], path[k][0], path[k + 1][0])
                for k in range(len(path) - 1)
            ]
            legs_clear = all(
                (_vrun_clear(path[k][0], path[k][1], path[k + 1][1], half_m2)
                 if path[k][0] == path[k + 1][0] else
                 _hrun_clear(path[k][1], path[k][0], path[k + 1][0]))
                for k in range(len(path) - 1)
            )
            # Every genuine layer-transition bend draws a real via + M1/M2
            # guarantee pad (section 34.14) -- verify BEFORE drawing
            # anything that each such bend point actually has room for
            # that pad on both layers, same "leave open, don't draw
            # colliding geometry" discipline as every other check here.
            bends_clear = all(
                _bend_pad_clear(path[k][0], path[k][1])
                for k in range(1, len(path) - 1)
                if leg_layers[k - 1] != leg_layers[k]
            )
            path_clear = legs_clear and bends_clear
            if not path_clear:
                print(f"WARNING: net {net}: segment {inst0}.{pin0} -> {inst1}.{pin1}: "
                      f"grid path found but failed exact re-verification; "
                      f"leaving this segment UNROUTED (open)")
                seg_paths[-1] = None
                unresolved_segments.append((net, inst0, pin0, inst1, pin1))
                continue
            for j in range(len(path) - 1):
                (xa, ya), (xb, yb) = path[j], path[j + 1]
                if xa == xb:
                    # Vertical run -- always M2 (crosses cell rows).
                    ylo, yhi = (ya, yb) if ya <= yb else (yb, ya)
                    top.shapes(m2_idx).insert(db.Box(um(xa - M2_CORE_WIDTH / 2), um(ylo - half_m2),
                                                      um(xa + M2_CORE_WIDTH / 2), um(yhi + half_m2)))
                else:
                    layer = leg_layers[j]
                    xlo, xhi = (xa, xb) if xa <= xb else (xb, xa)
                    if layer == 'M1':
                        top.shapes(m1_idx).insert(db.Box(um(xlo - half_m1), um(ya - M1_CORE_WIDTH / 2),
                                                          um(xhi + half_m1), um(ya + M1_CORE_WIDTH / 2)))
                    else:
                        top.shapes(m2_idx).insert(db.Box(um(xlo - half_m2), um(ya - M2_CORE_WIDTH / 2),
                                                          um(xhi + half_m2), um(ya + M2_CORE_WIDTH / 2)))
                shapes_drawn += 1
            # Only a genuine M1<->M2 layer transition between two
            # consecutive legs needs a via + guarantee pads (sized to the
            # bare V1 enclosure minimum, M2_PAD_SIZE = VIA_SIZE+2.0, same
            # pattern as the touched-pin offset fix in section 34.10;
            # clearance for each already verified above via bends_clear).
            for k in range(1, len(path) - 1):
                if leg_layers[k - 1] == leg_layers[k]:
                    continue
                bx, by = path[k]
                top.shapes(m1_idx).insert(pad(bx, by, M2_PAD_SIZE))
                top.shapes(m2_idx).insert(pad(bx, by, M2_PAD_SIZE))
                top.shapes(v1_idx).insert(pad(bx, by, VIA_SIZE))
                shapes_drawn += 3
            label = db.Text(net, db.Trans(um((x0 + x1) / 2), um((y0 + y1) / 2)))
            label.size = um(1.5)
            top.shapes(mh_annot_idx).insert(label)
            _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _full_box)).merged()
            _existing_m1 = db.Region(top.begin_shapes_rec_touching(m1_idx, _full_box)).merged()

        touched = set()
        for i, path in enumerate(seg_paths):
            if path is not None:
                touched.add(i)
                touched.add(i + 1)

        # Each touched pin's own via/pad is drawn HERE, unconditionally, in
        # every prior version of this loop -- with no _box_clear check
        # against _existing_m2 first. That was safe by chance in the 5-row
        # configurations tried so far (residual violations there traced to
        # other causes), but the 6-row + always-at-least-1-FILL trial
        # (design_notes.md section 34.9/34.10) exposed it directly: two
        # DIFFERENT multi-hop nets' touched-pin pads ended up within
        # M2_MIN_SPACE of each other and were both drawn anyway, producing
        # 6 of 7 new M2 violations. Add the same clear-before-draw
        # discipline every other shape in this project already follows,
        # with a small local-offset retry (the pin's OWN via placement has
        # a few um of slack via VIA_MARGIN_UM already, so nudging the pad
        # slightly is safe) before giving up and leaving the pin's pad
        # undrawn (which also means its adjoining segment(s) are not truly
        # connected -- logged so it's visible, not silently accepted).
        def _pad_clear(cx, cy, half_um):
            box = db.Box(int(round((cx - half_um) / dbu)), int(round((cy - half_um) / dbu)),
                         int(round((cx + half_um) / dbu)), int(round((cy + half_um) / dbu)))
            clearance_ldbu = int(round(M2_MIN_SPACE / dbu))
            return db.Region(box).sized(clearance_ldbu).interacting(_other_nets_m2).count() == 0

        for idx in touched:
            vy, vx, instname, pinname, patch_polys, padded = anchors[idx]
            pad_half = M2_PAD_SIZE / 2.0
            placed_vx, placed_vy = None, None
            if _pad_clear(vx, vy, pad_half):
                placed_vx, placed_vy = vx, vy
            else:
                for off in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
                    for dx, dy in ((off, 0), (-off, 0), (0, off), (0, -off)):
                        cx, cy = vx + dx, vy + dy
                        if _pad_clear(cx, cy, pad_half):
                            placed_vx, placed_vy = cx, cy
                            break
                    if placed_vx is not None:
                        break
            if placed_vx is None:
                print(f"WARNING: net {net}: pin {instname}.{pinname}'s own via/pad at "
                      f"({vx:.2f},{vy:.2f}) collides with existing M2 even after local offset "
                      f"retry; leaving this pin's pad UNDRAWN (open)")
                continue
            offset_applied = (placed_vx, placed_vy) != (vx, vy)
            if offset_applied:
                print(f"DEBUG OFFSET net={net} pin={instname}.{pinname}: "
                      f"({vx:.2f},{vy:.2f}) -> ({placed_vx:.2f},{placed_vy:.2f})", file=sys.stderr)
            if padded:
                for pts_um in patch_polys:
                    poly = db.Polygon([db.Point(um(p.x), um(p.y)) for p in pts_um])
                    top.shapes(m1_idx).insert(poly)
                    shapes_drawn += 1
            if offset_applied:
                # abs_pin_anchor() only guarantees V1-M1 enclosure (>=1.0um,
                # via VIA_MARGIN_UM erosion) at the ORIGINAL (vx,vy) anchor
                # -- patch_polys, when present, also only cover that
                # original spot. Moving the via to (placed_vx,placed_vy) to
                # dodge an M2 collision leaves it outside that guaranteed
                # region, which is exactly what produced 48 "V1 enclosed by
                # M1<1.0" violations the first time this offset retry was
                # tried (design_notes.md section 34.11). Fix: draw an
                # explicit M1 guarantee-pad at the new location, same size
                # as the M2 pad (M2_PAD_SIZE = VIA_SIZE+2.0), which is
                # exactly the bare V1-M1 enclosure minimum -- mirrors what
                # the M2 pad already does for V1-M2 enclosure.
                top.shapes(m1_idx).insert(pad(placed_vx, placed_vy, M2_PAD_SIZE))
                shapes_drawn += 1
            top.shapes(v1_idx).insert(pad(placed_vx, placed_vy, VIA_SIZE))
            top.shapes(m2_idx).insert(pad(placed_vx, placed_vy, M2_PAD_SIZE))
            shapes_drawn += 2
            _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _full_box)).merged()

        seg_ok = sum(1 for p in seg_paths if p is not None)
        _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _full_box)).merged()

        if seg_ok == len(anchors) - 1:
            fully_routed_nets.append(net)
        elif seg_ok > 0:
            partially_routed_nets.append(net)
        else:
            print(f"WARNING: net {net}: ALL segments failed to route")

    print(f"\ndrew {shapes_drawn} shapes for {len(multi_hop_nets)} multi-hop nets")
    print(f"fully routed: {len(fully_routed_nets)}  partially routed: {len(partially_routed_nets)}  "
          f"fully failed: {len(multi_hop_nets) - len(fully_routed_nets) - len(partially_routed_nets)}")
    if unresolved_segments:
        print(f"{len(unresolved_segments)} segment(s) left UNROUTED (open):")
        for net, i0, p0, i1, p1 in unresolved_segments:
            print(f"  - net={net} {i0}.{p0} -> {i1}.{p1}")

    layout.write(OUT_GDS)
    print("wrote", OUT_GDS)


if __name__ == "__main__":
    main()
