"""
route_channel_pilot.py

PILOT: route the top-margin M1 channel (above logical row 3, the topmost
standard-cell row) for nets that are FULLY CONTAINED within row 3 (i.e. every
pin of the net is on a row-3 instance -- no M2/via crossing into another row
needed). This is the smallest, most self-contained of the 3 channels
(design_notes.md section 15), chosen as a proof-of-concept before attempting
the other two channels or any cross-row M2 trunk routing.

Pipeline:
  1. Recompute row 3's exact placement (same logic as gen_gds_placement.py,
     row 3 = physical row 8, unmirrored) to get each instance's absolute
     origin in the final layout.
  2. Pull each cell type's real pin locations from the TR-1um_STDCELL.gds
     library (layer 48/0 TEXT = pin name, matched to the nearest M1 (13/0)
     shape for that pin's real box extent) -- NOT the abstract xschem
     symbol coordinates, which are a different, schematic-only coordinate
     system.
  3. For each of the 32 row-3-internal nets (identified separately via
     analyze_row3.py-style net/instance-membership analysis), compute the
     absolute (x, top-of-pinbox-y) for every pin.
  4. Assign each net a horizontal M1 track in the channel using the classic
     left-edge interval-scheduling algorithm (packs non-X-overlapping nets
     onto the same track), then draw: one horizontal trunk per net on its
     assigned track, plus one vertical stub per pin connecting the pin's own
     M1 box up to that trunk.
  5. Insert the new M1 shapes into a copy of the placement GDS and write
     Layout/i2c_slave_async_layout_routed_pilot.gds.

Real DRC (klayout tech/drc/run.drc) and connectivity re-extraction are done
as separate follow-up steps after this script, not inline here.
"""
import re
import os
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from plan_placement import compute_rows, ROW_WIDTH_UM, NROWS, PR_LAYER  # noqa: E402

STDCELL_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_5_stdcell"
GDS_LIB = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/libraries/TR-1um_STDCELL.gds"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_layout_routed_pilot.gds"
PIN_MAP_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs/pilot_pin_map.json"
NET_FILE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/src/i2c_slave_async_net.v"

M1_LAYER = (13, 0)
V1_LAYER = (19, 0)
M2_LAYER = (20, 0)
GC_LAYER = (8, 1)  # gate contact (tech/TR-1um.lyp) -- see V1.GC below
PIN_TEXT_LAYER = (48, 0)
ANNOT_LAYER = (250, 1)  # non-fab: routed-net-name annotation for this pilot (250/0 already used for inst names)

# tech/drc/run.drc V1.GC: V1-GC Smin < 1.2 -- a rule this pilot's own
# hand-rolled drc_check.py did NOT reproduce (it only covered M1/M2 W/S and
# V1-M1/M2 enclosure). Found via the REAL klayout DRC run (DRC_Error.lyrdb,
# provided by the user): 6 of this pilot's pin-side vias landed within
# 1.2um of a GC (gate contact) shape inside their own standard cell -- the
# M1-enclosure-safe anchor search never considered this layer at all.
V1_GC_MIN_SPACE = 1.2

# DRC constants (klayout tech/drc/run.drc): V1 is a fixed 1.4x1.4um square,
# enclosed by M1 and by M2 by >=1.0um on each side -> a via landing pad on
# either layer must be >=3.4x3.4um. M2 min width 3.0/min space 2.0 (run.drc
# M2.W1/M2.S1).
VIA_SIZE = 1.4
GC_KEEPOUT_UM = V1_GC_MIN_SPACE + VIA_SIZE / 2.0  # = 1.9: via CENTER must stay this far from any GC edge
VIA_PAD = 4.0  # landing pad on M1/M2 at each via (>= 1.4 + 2*1.0, with margin)
M2_STUB_WIDTH = 4.0  # unused for the vertical run itself now -- see M2_CORE_WIDTH/M2_PAD_SIZE below
# A uniformly-4.0-wide M2 stub for the ENTIRE pin-to-trunk vertical run was
# found to cause 21 M2.S1 space violations: many row-3 pins sit at nearly
# the same Y (most pin y-centers cluster around 462-473um), so two
# neighboring pins only ~5.5um apart in X (common in this dense library --
# see the M1 pin-erosion notes above) have their full-width stubs' via-pad
# regions collide at that shared height. Fix: keep the long vertical run
# THIN (M2_CORE_WIDTH, just above the M2.W1 minimum) and only widen to a
# full via landing pad in a small square LOCALLY at each of the two via
# endpoints -- this halves the effective center-to-center clearance needed
# almost everywhere along the run, while the (still occasionally close)
# endpoint pads use the bare DRC-minimum size (M2_PAD_SIZE=3.4) with exact,
# self-consistent (not library-derived) grid-snapped coordinates, so unlike
# the library's own pin shapes this has zero rounding risk at the boundary.
M2_CORE_WIDTH = 3.1
M2_PAD_SIZE = VIA_SIZE + 2.0  # = 3.4, the bare V1-M2 enclosure minimum

# A straight M1 stub from a buried cell pin up through the row was found (via
# the width/space DRC check below) to cross OTHER M1 shapes belonging to the
# same/neighboring cells along the way (their own internal signal routing,
# not just the VDD/GND power rail that spans the full row width at the top
# of every row) -- i.e. a same-layer stub is not obstacle-safe in general.
# Fixed by escaping on M2 instead: M2 has no electrical interaction with any
# M1 shape it merely crosses over (only an explicit via connects the two
# layers), so the vertical run from a buried pin up into the M1 channel
# trunk is done as M1(pin) -V1-> M2 (vertical run) -V1-> M1(trunk), exactly
# the standard-cell "escape routing" technique real place & route uses for
# this same reason.

ROW_HEIGHT = 55.0
# Physical row index of logical row 3 in gen_gds_placement.py's PHYSICAL_ROWS
# ([None,None, 0,1, None,None,None, 2,3, None,None]) -- row 3 is physical
# index 8, mirrored = (8 % 2 == 1) = False.
PHYS_ROW3_INDEX = 8
CHANNEL_BOTTOM_Y = (PHYS_ROW3_INDEX + 1) * ROW_HEIGHT  # top edge of row 3 = bottom of the channel above it
CHANNEL_HEIGHT = 110.0  # 2 filler rows

M1_MIN_WIDTH = 1.8
M1_MIN_SPACE = 1.4
M2_MIN_WIDTH = 3.0
M2_MIN_SPACE = 2.0
TRACK_WIDTH = VIA_PAD  # 4.0um: the M1 trunk must be this wide wherever a via lands on it, so just use it throughout
# Vertically-adjacent tracks (different Y) need >= TRACK_WIDTH + M1_MIN_SPACE
# center-pitch to clear M1.S1; pad up for margin.
TRACK_PITCH = TRACK_WIDTH + M1_MIN_SPACE + 1.0
FIRST_TRACK_Y = CHANNEL_BOTTOM_Y + TRACK_PITCH  # leave one pitch of margin off the row-3/channel boundary


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
    celltypes = [f[:-4] for f in os.listdir(STDCELL_DIR) if f.endswith(".sym")]
    sym_pins = {ct: parse_sym(os.path.join(STDCELL_DIR, ct + ".sym")) for ct in celltypes}

    # ---------- library: real pin (x,y) + M1 box per (celltype, pinname) ----------
    lib = db.Layout()
    lib.read(GDS_LIB)
    ldbu = lib.dbu
    lib_pin_text_idx = lib.layer(*PIN_TEXT_LAYER)
    lib_m1_idx = lib.layer(*M1_LAYER)
    lib_gc_idx = lib.layer(*GC_LAYER)

    gc_cache = {}

    def cell_gc_forbidden(celltype):
        """Region (library dbu units, cell-local) of points where a V1 via
        CENTER may not land, to keep >=V1_GC_MIN_SPACE clear of every GC
        (gate contact) shape in this cell type. GC is not net-specific, so
        (unlike the M1 pin polygons) all of a cell's GC shapes are treated
        as one flat obstacle set."""
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
        # Group the cell's M1 shapes into per-net polygons first: shapes
        # belonging to the SAME net touch/overlap (that's how they connect),
        # while DIFFERENT nets never touch on the same layer in a DRC-clean
        # library cell -- so Region.merged() over ALL of a cell's M1 shapes
        # correctly separates it into one polygon per electrical net. This
        # matters because several real pins are NOT solid rectangles: they
        # are comb/interdigitated shapes (e.g. two adjacent traces threaded
        # together to save width), so a naive bounding-box of "the M1 shape
        # under the pin text" can include empty notches that a via must NOT
        # be centered on (found via V1-M1 enclosure DRC violations that
        # traced back to a via sitting exactly in such a notch).
        net_polys = list(db.Region(c.begin_shapes_rec(lib_m1_idx)).merged().each())
        pins = {}
        it = c.begin_shapes_rec(lib_pin_text_idx)
        while not it.at_end():
            s = it.shape()
            if s.is_text():
                tx, ty = s.text_dtrans.disp.x, s.text_dtrans.disp.y
                px, py = int(round(tx / ldbu)), int(round(ty / ldbu))
                # Prefer an actual polygon whose bbox contains the text point
                # (cheap prefilter -- good enough here since pin labels are
                # always placed directly on their own net's shape in this
                # library); fall back to nearest-by-bbox-center if none does.
                cand = [p for p in net_polys
                        if p.bbox().left <= px <= p.bbox().right and p.bbox().bottom <= py <= p.bbox().top]
                if cand:
                    best = min(cand, key=lambda p: p.bbox().area())
                else:
                    best = min(net_polys, key=lambda p: (p.bbox().center().x - px) ** 2 + (p.bbox().center().y - py) ** 2)
                pins[s.text_string.lower()] = best  # db.Polygon (library dbu units) -- the pin's REAL net shape
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
        return d[key]  # klayout db.Polygon, in library dbu units -- the pin's actual (possibly notched) net shape

    # ---------- netlist parse (same pattern as the rest of the project's scripts) ----------
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

    # ---------- row 3 placement ----------
    # IMPORTANT: do NOT recompute row 3's cell sequence/cursor_x independently
    # from plan_placement.compute_rows() -- gen_gds_placement.py does not
    # place compute_rows()'s raw row list directly. It first runs each cell
    # row through distribute_paired_row_fillers() (design_notes.md section
    # 16/17), which splices extra FILL1/"corrB3_*" corridor-alignment filler
    # cells INTO the middle of the row's cell sequence. Recomputing cursor_x
    # over the raw (filler-free) row list therefore silently drifts out of
    # sync with the real placement after each such insertion point, giving
    # every subsequent real cell a wrong absolute X -- this was found (via
    # cross-referencing V1-M1 enclosure DRC violations against the actual M1
    # shapes at each violation site) to be the true root cause of a batch of
    # "false" enclosure violations, NOT a rounding/grid issue.
    #
    # Fix: read each row-3 real instance's ACTUAL absolute X directly back
    # out of the already-correctly-placed input GDS, via the per-instance
    # name annotation layer (250/0) gen_gds_placement.py itself draws at
    # (cx, cy) = (tx + bleft + width/2, row_bottom_abs + row_height/2) for
    # every placed cell (real or filler). Row 3's cy is a fixed, filler-
    # independent constant (PHYS_ROW3_INDEX*ROW_HEIGHT + ROW_HEIGHT/2), so
    # matching on cy picks out exactly this row's annotations regardless of
    # filler content, and solving tx = cx - bleft - width/2 recovers the
    # real placement exactly (no independent re-derivation needed).
    rows, cell_width, row_height = compute_rows(nrows=NROWS, row_width_um=ROW_WIDTH_UM)
    row3 = rows[3]
    row3_names = set(n for n, t, w in row3)

    annot_src_idx = layout_in_annot_idx = None  # set below, after IN_GDS is opened for real geometry too

    pr_bbox_cache = {}

    def get_pr_bbox(celltype):
        if celltype not in pr_bbox_cache:
            c = lib.cell(celltype)
            pr_idx = lib.layer(*PR_LAYER)
            pr_bbox_cache[celltype] = db.Region(c.begin_shapes_rec(pr_idx)).bbox()
        return pr_bbox_cache[celltype]

    _annot_layout = db.Layout()
    _annot_layout.read(IN_GDS)
    _annot_dbu = _annot_layout.dbu
    _annot_top = _annot_layout.cell("i2c_slave_async_layout")
    _annot_idx = _annot_layout.layer(250, 0)
    ROW3_CY = PHYS_ROW3_INDEX * ROW_HEIGHT + ROW_HEIGHT / 2.0

    row3_cx = {}  # instname -> actual annotation-center x (um), from the real placed GDS
    it = _annot_top.begin_shapes_rec(_annot_idx)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            ax = s.text_dtrans.disp.x
            ay = s.text_dtrans.disp.y
            if abs(ay - ROW3_CY) < 0.01:
                row3_cx[s.text_string] = ax
        it.next()

    missing = [n for n, t, w in row3 if n not in row3_cx]
    if missing:
        raise RuntimeError(f"{len(missing)} row3 instances have no annotation match in {IN_GDS}: {missing[:5]}...")

    inst_origin = {}  # instname -> (abs_x0, abs_y0) of the cell's prBoundary-left/bottom in this row
    for name, typ, w in row3:
        bbox = get_pr_bbox(typ)
        bleft = bbox.left * ldbu
        bbottom = bbox.bottom * ldbu
        width = bbox.width() * ldbu
        cx = row3_cx[name]
        tx = cx - (bleft + width / 2.0)
        ty = PHYS_ROW3_INDEX * ROW_HEIGHT - bbottom  # unmirrored (R0): same as gen_gds_placement.py's non-mirrored branch
        inst_origin[name] = (tx, ty)

    # Required clearance from the via's OWN edge out to the metal edge, in
    # every direction: via half-width (VIA_SIZE/2) + V1.M1 enclosure minimum
    # (1.0um) = the via center must lie in the pin's real net-shape ERODED
    # by this amount for the via to legally land there.
    VIA_MARGIN_UM = VIA_SIZE / 2.0 + 1.0

    # ---------- existing M2 obstructions within row3 (real cell/filler M2 usage) ----------
    # Row-3 standard cells and FILL1 filler cells (used for the distributed
    # in-row M2-corridor filler, design_notes.md section 16) were found to
    # carry their OWN M2 shapes (e.g. FILL1's internal density/strap
    # pattern) -- i.e. M2 is NOT uniformly empty within the row the way the
    # M1 channel bands were (mostly) assumed to be. A first version of this
    # pilot's M2 escape stubs ignored this and got M2.S1 space violations
    # wherever a pin's fixed via-pad position happened to land close to one
    # of these pre-existing shapes. Fix: read them back from the real
    # placed GDS (same principle as the row3-placement and channel-rail
    # fixes above) and route the M2 escape stub around them with a jog
    # (see _m2_run_clear() and its use in the emission loop below) --
    # NOT by moving the via/M1 anchor itself, which was tried first and
    # found to trade M2.S1 violations for new M1.S1 ones instead.
    _rail_scan = db.Layout()
    _rail_scan.read(IN_GDS)
    _rail_dbu = _rail_scan.dbu
    _rail_top = _rail_scan.cell("i2c_slave_async_layout")
    _rail_m1_idx = _rail_scan.layer(*M1_LAYER)
    _rail_m2_idx = _rail_scan.layer(*M2_LAYER)
    # Scan the full row3+channel height (not just row3) -- our OWN routing's
    # M2 runs all the way up through the channel, and (after each net is
    # drawn) this same box is re-scanned to fold that net's M2 into the
    # obstruction set for subsequent nets, so it must cover that area too.
    _m2_scan_box = db.Box(0, 0, int(round(ROW_WIDTH_UM / _rail_dbu)),
                           int(round((CHANNEL_BOTTOM_Y + CHANNEL_HEIGHT) / _rail_dbu)))
    _existing_m2 = db.Region(_rail_top.begin_shapes_rec_touching(_rail_m2_idx, _m2_scan_box)).merged()
    _existing_m2_original = _existing_m2  # snapshot before any of OUR routing accumulates into _existing_m2 below
    _existing_m2_original_polys = list(_existing_m2_original.each())

    def _box_clear(l_um, b_um, r_um, t_um):
        box = db.Box(int(round(l_um / _rail_dbu)), int(round(b_um / _rail_dbu)),
                      int(round(r_um / _rail_dbu)), int(round(t_um / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        return db.Region(box).sized(clearance_ldbu).interacting(_existing_m2).count() == 0

    def _m2_run_clear(x_um, y0_um, y1_um, half_width_um):
        # Does a vertical M2 run at x_um from y0 to y1, of the given
        # half-width, stay >=M2_MIN_SPACE clear of existing M2? Checked as
        # one region query instead of point sampling since the run is a
        # simple rectangle.
        run = db.Box(int(round((x_um - half_width_um) / _rail_dbu)), int(round(y0_um / _rail_dbu)),
                      int(round((x_um + half_width_um) / _rail_dbu)), int(round(y1_um / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        return db.Region(run).sized(clearance_ldbu).interacting(_existing_m2).count() == 0

    def abs_pin_anchor(instname, pinname):
        """Returns (vx, vy, patch_polys_abs_um, padded) for the via anchor
        of one pin: (vx, vy) is a point guaranteed (by construction, via
        Region erosion) to have >=VIA_MARGIN_UM of real M1 metal around it
        in every direction -- safe against BOTH DRC (V1-M1 enclosure) and
        connectivity (the point is only ever inside THIS pin's own net
        polygon, never a neighboring net's, since same-layer shapes from
        different nets never touch in a DRC-clean library cell) -- AND
        >=V1_GC_MIN_SPACE clear of any GC (gate contact) shape in the same
        cell (a rule this pilot's own DRC check never modeled; found via a
        real klayout DRC run flagging 6 vias too close to GC).
        patch_polys_abs_um is a (possibly empty) list of extra M1 polygons
        (already in absolute um) that must be drawn for the anchor to be
        real metal -- non-empty only when the pin's native shape had to be
        grown to find a safe point (the handful of pins sized exactly at
        the 3.4um V1-M1 minimum, zero native slack, or pins whose only
        native-safe spot was too close to GC)."""
        typ = dict((n, t) for n, t, w in row3)[instname]
        poly = cell_pin_poly(typ, pinname)  # library dbu units, cell-local
        ox, oy = inst_origin[instname]  # um
        gc_forbid = cell_gc_forbidden(typ)  # library dbu units, cell-local -- fixed per cell type, doesn't grow

        margin_ldbu = int(round(VIA_MARGIN_UM / ldbu))

        def safe_region(region):
            return region.sized(-margin_ldbu) - gc_forbid

        base = db.Region(poly)
        eroded = safe_region(base)
        grown_um = 0.0
        used = base
        if eroded.is_empty():
            # Zero/negative native slack (e.g. exactly-3.4um-wide pins, or a
            # pin whose only wide-enough spot sits too close to GC) -- grow
            # the REAL polygon (not its bounding box, to avoid inventing
            # metal over an actual notch/neighbor gap) by the smallest
            # amount that opens up a valid interior point clear of both
            # constraints.
            for grow_um in (0.02, 0.05, 0.08, 0.12, 0.2, 0.3, 0.5, 0.8, 1.2):
                grow_ldbu = int(round(grow_um / ldbu))
                cand = base.sized(grow_ldbu)
                cand_eroded = safe_region(cand)
                if not cand_eroded.is_empty():
                    used, eroded, grown_um = cand, cand_eroded, grow_um
                    break
            else:
                raise RuntimeError(f"{instname}.{pinname}: no safe via anchor even after growth")

        # Pick the largest eroded piece and use its bbox center -- the
        # traces here are close enough to rectangular per-finger that this
        # is reliably inside the piece. (M2-side obstacle avoidance for the
        # escape stub is handled separately, in the emission loop, via a
        # jog -- NOT here: an earlier attempt to steer this M1-side anchor
        # away from existing M2 by growing further traded M2.S1 violations
        # for new M1.S1 ones, because a bigger grown patch on a bent/
        # notched pin shape can cross into a neighboring net's M1. Moving
        # the via itself is the wrong tool for an M2-layer obstruction.)
        pieces = list(eroded.each())
        best = max(pieces, key=lambda p: p.bbox().area())
        bb = best.bbox()
        vx = bb.center().x * ldbu + ox
        vy = bb.center().y * ldbu + oy

        patch_polys_abs = []
        if grown_um > 0.0:
            for p in used.each():
                pts = [db.DPoint(pt.x * ldbu + ox, pt.y * ldbu + oy) for pt in p.each_point_hull()]
                patch_polys_abs.append(pts)
        return vx, vy, patch_polys_abs, grown_um > 0.0

    # ---------- identify row-3-fully-internal nets ----------
    internal_nets = []
    for net, pins in net_pins.items():
        inst_names = set(p[0] for p in pins)
        if not inst_names:
            continue
        if inst_names & row3_names and inst_names <= row3_names:
            internal_nets.append((net, pins))

    print(f"row3 instances: {len(row3_names)}, fully-internal nets: {len(internal_nets)}")

    # ---------- per-net: via anchor point (safe interior point of the pin's real net shape) ----------
    net_stub_pts = {}  # net -> [(vx, vy, patch_polys_abs, padded), ...]
    net_pin_names = {}  # net -> [(instname, pinname), ...] -- same order as net_stub_pts[net], for connectivity verification
    for net, pins in internal_nets:
        pts = []
        names = []
        for instname, typ, pinname in pins:
            vx, vy, patch_polys, padded = abs_pin_anchor(instname, pinname)
            pts.append((vx, vy, patch_polys, padded))
            names.append((instname, pinname))
        net_stub_pts[net] = pts
        net_pin_names[net] = names

    # ---------- pre-pass: detect pins sharing the same pre-existing M2 obstruction ----------
    # If two (or more) pins' straight-up M2 escape paths are all blocked by
    # the SAME existing obstruction polygon, letting each pick its own
    # "nearest clear side" independently can send all of them to the SAME
    # side when they're roughly centered on the same obstacle -- the first
    # one processed occupies that detour space and later ones can fail to
    # find any clear jog at all within the search range. This is exactly
    # what happened for _377_.Y/_377_.B (net _018_/rx_data_r[6]): both
    # needed to dodge the same ~23um-wide filler M2 strip, both ended up
    # wanting the right side, and Y's search then found the right side
    # already occupied by B's own detour with nothing clear on either side
    # within +/-100um. Fix: detect such shared-obstacle groups BEFORE any
    # routing happens, and force alternating (opposite) detour directions
    # within each group instead of leaving it to processing order/chance.
    HALF_PAD = M2_PAD_SIZE / 2.0
    ROW3_TOP_Y = CHANNEL_BOTTOM_Y  # pre-existing M2 obstructions are all within row3 itself (y<=495), never above

    def _blocking_obstruction_index(x, y_center):
        if _m2_run_clear(x, y_center - HALF_PAD, ROW3_TOP_Y, HALF_PAD):
            return None
        run = db.Box(int(round((x - HALF_PAD) / _rail_dbu)), int(round((y_center - HALF_PAD) / _rail_dbu)),
                      int(round((x + HALF_PAD) / _rail_dbu)), int(round(ROW3_TOP_Y / _rail_dbu)))
        clearance_ldbu = int(round(M2_MIN_SPACE / _rail_dbu))
        grown = db.Region(run).sized(clearance_ldbu)
        for i, p in enumerate(_existing_m2_original_polys):
            if grown.interacting(db.Region(p)).count() > 0:
                return i
        return None

    # All 65 pins, flattened, with which existing-obstruction (if any) each
    # one's straight path hits.
    all_pins = []  # (instname, pinname, x, y_center)
    blocked_by = {}  # (instname, pinname) -> existing-obstruction polygon index
    for net, names in net_pin_names.items():
        for (instname, pinname), (vx, vy, _patch, _padded) in zip(names, net_stub_pts[net]):
            all_pins.append((instname, pinname, vx, vy))
            idx = _blocking_obstruction_index(vx, vy)
            if idx is not None:
                blocked_by[(instname, pinname)] = idx

    # Union-Find over pin keys: two pins are linked (and must therefore
    # detour to OPPOSITE sides) if EITHER (a) they are both blocked by the
    # very same pre-existing obstruction, OR (b) they belong to the SAME
    # standard-cell instance and sit close together in X. (b) is needed on
    # top of (a) because a pin can be individually clear of any
    # pre-existing obstacle yet still collide with a same-instance
    # neighbor's OWN detour once OTHER nets' routing has accumulated --
    # found via _400_.A/_400_.B and _410_.A/_410_.Y, neither of which
    # shared a pre-existing obstruction but both of which are same-
    # instance pin pairs only ~10-15um apart.
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

    # Also link ANY two pins (regardless of instance) that sit close
    # together at nearly the same Y -- congestion in this dense library
    # isn't limited to siblings of one instance: two ADJACENT instances'
    # pins can be just as close (found via _395_.A/_396_.B, two different
    # instances only ~16um apart, whose independently-chosen detours still
    # collided once both needed to jog). Y-gating avoids linking pins that
    # are merely at similar X but on different physical rows/heights.
    ADJACENT_LINK_DIST_UM = 20.0
    all_pins_sorted = sorted(all_pins, key=lambda t: t[2])
    for i in range(len(all_pins_sorted)):
        ni, pi, xi, yi = all_pins_sorted[i]
        for j in range(i + 1, len(all_pins_sorted)):
            nj, pj, xj, yj = all_pins_sorted[j]
            if xj - xi >= ADJACENT_LINK_DIST_UM:
                break  # sorted by x -- no further j can be close enough
            if abs(yi - yj) < 2.0:
                uf_union((ni, pi), (nj, pj))

    groups = {}
    x_of = {(n, p): x for n, p, x, _y in all_pins}
    for n, p, x, y in all_pins:
        key = (n, p)
        if key in blocked_by or key in uf_parent:
            groups.setdefault(uf_find(key), []).append((x, n, p))

    forced_dir = {}  # (instname, pinname) -> -1 (detour left) / +1 (detour right)
    forced_rank = {}  # (instname, pinname) -> how many EARLIER same-side members in its group (0, 1, 2, ...)
    for root, members in groups.items():
        if len(members) < 2:
            continue
        members.sort()  # by x (ties broken by instname/pinname, since tuple compare falls through)
        # A plain "left half / right half by mean X" split is not enough
        # once a group has 3+ members (or ties at the same X, e.g. two
        # pins of one instance stacked at the same X but different Y,
        # found via _404_.A/_404_.B): with an odd split or a tie, two
        # members can still land on the SAME side, and since both then
        # search outward from nearly the same starting X, they gravitate
        # to the SAME nearest clear offset and collide with each other.
        # Fix: alternate sides strictly by sorted index (not by which half
        # of the mean each falls in), AND track each member's rank among
        # same-side siblings so _find_jog_x can force later-ranked ones to
        # skip past earlier ones' offsets instead of competing for the
        # same nearest spot.
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

    # Nets containing a forced-direction pin get routed FIRST, so the
    # (already correctly split) detours claim their space before other,
    # unrelated nets crowd the same corridor.
    net_priority = {net: (0 if any((n, p) in forced_dir for n, p in net_pin_names[net]) else 1)
                    for net in net_stub_pts}

    # ---------- available track Y slots: the channel is NOT one clear span ----------
    # The two FILL1 filler rows that make up this channel are placed just
    # like any other physical row, so they carry their OWN full-width M1
    # power rail at their own row boundary too -- the channel is cut in half
    # by a rail running through its middle (plus the block's own top-edge
    # rail at the very top). A first version of this pilot assumed the whole
    # 110um channel was uniformly clear and got 238 M1.S1 space violations
    # from trunks routed straight across this rail. Fix: read the actual
    # full-width M1 rail bands back out of the real placed GDS (not
    # re-derived from row_height arithmetic, for the same reason row3's own
    # placement is read back rather than recomputed -- see above) and only
    # place tracks in the gaps between them. (_rail_scan/_rail_top/_rail_dbu
    # were already opened above, for the M2-obstruction check.)
    _scan_box = db.Box(0, int(round(CHANNEL_BOTTOM_Y / _rail_dbu)),
                        int(round(ROW_WIDTH_UM / _rail_dbu)),
                        int(round((CHANNEL_BOTTOM_Y + CHANNEL_HEIGHT) / _rail_dbu)))
    _m1_in_channel = db.Region(_rail_top.begin_shapes_rec_touching(_rail_m1_idx, _scan_box)).merged()
    rail_bands = []  # (bottom_um, top_um) of each full-row-width obstruction in the channel
    for p in _m1_in_channel.each():
        bb = p.bbox()
        if bb.width() * _rail_dbu > ROW_WIDTH_UM * 0.5:  # full-width rail, not a routed stub
            rail_bands.append((bb.bottom * _rail_dbu, bb.top * _rail_dbu))
    rail_bands.sort()
    print(f"rail bands found in channel: {[(round(b,2), round(t,2)) for b, t in rail_bands]}")

    RAIL_MARGIN = M1_MIN_SPACE + TRACK_WIDTH / 2.0  # keep a trunk's near edge >=M1_MIN_SPACE clear of the rail
    # Build the list of clear Y sub-spans between/around the rail bands.
    clear_spans = []
    cursor = CHANNEL_BOTTOM_Y
    top_limit = CHANNEL_BOTTOM_Y + CHANNEL_HEIGHT
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
    # interval = [min_x, max_x] per net (the trunk's horizontal extent);
    # nets are sorted by min_x and packed onto the first track whose current
    # right edge (+ M1 spacing margin) is left of this net's min_x.
    net_intervals = []
    for net, pts in net_stub_pts.items():
        xs = [p[0] for p in pts]
        net_intervals.append((min(xs), max(xs), net))
    net_intervals.sort()

    tracks = []  # list of current right-edge x per used slot (parallel to track_slots prefix)
    net_track = {}
    MARGIN = TRACK_WIDTH + M1_MIN_SPACE * 2  # keep well clear of DRC min space between adjacent trunks' stubs
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
    assert n_tracks <= len(track_slots), "pilot channel overflowed its track budget"

    # ---------- emit geometry: M1 trunk + (M1 pad -V1-> M2 stub -V1-> M1 pad) ----------
    layout = db.Layout()
    layout.read(IN_GDS)
    dbu = layout.dbu
    top = layout.cell("i2c_slave_async_layout")
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)
    annot_idx = layout.layer(*ANNOT_LAYER)

    DRC_GRID = 0.05  # tech/drc/run.drc ERR01: M1/V1/M2 must be on a 0.050um grid

    def um(v):
        # snap to the DRC grid first, THEN convert to database units -- this
        # also removes float-accumulation drift (from chained um-space
        # instance-offset + library-box arithmetic) that was causing V1
        # enclosure margins to compute as very slightly under 1.0um on the
        # tightest (exactly-3.4um-wide) pin boxes.
        return int(round(round(v / DRC_GRID) * DRC_GRID / dbu))

    def pad(cx, cy, size):
        h = size / 2.0
        return db.Box(um(cx - h), um(cy - h), um(cx + h), um(cy + h))

    if os.environ.get("DEBUG_PINS"):
        for net, pts in net_stub_pts.items():
            for x, y_center, patch_polys, padded in pts:
                print(f"ALLPINS net={net} x={x:.3f} y={y_center:.3f} n_patch_polys={len(patch_polys)} padded={padded}")

    def _find_jog_x(vx, y_center, track_y, preferred_dir=None, skip_rank=0):
        """Find an X (possibly == vx) at which the M2 escape run from
        y_center up to track_y clears existing M2 (real cell/filler M2
        usage -- see above). Tries vx itself first (the common case, no jog
        needed); if that's obstructed, searches outward for a nearby X
        where BOTH the vertical run AND the horizontal connector (a wide,
        M2.W1-legal foot at y_center height, from vx to the new X) are
        clear. If preferred_dir is -1 or +1 (see the shared-obstacle
        pre-pass above), the ENTIRE preferred side is tried first, at
        increasing distance, before ever trying the other side -- so two
        pins forced to opposite sides never compete for the same detour
        space. skip_rank additionally skips that many of the SMALLEST
        preferred-side offsets (only meaningful together with
        preferred_dir): when 2+ pins in a group must share the same side
        (an odd-sized group, or ties at the same starting X), each later-
        ranked one starts its search further out instead of gravitating to
        the exact same nearest clear offset as an earlier-ranked sibling.
        Returns None if nothing within the search range works (caller
        falls back to vx with a warning)."""
        half = M2_PAD_SIZE / 2.0
        if _m2_run_clear(vx, y_center - half, track_y + half, half):
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
    # Route nets with a forced-direction pin (see the shared-obstacle
    # pre-pass above) first, so their already-correctly-split detours claim
    # their space before other, unrelated nets add clutter to the same
    # corridor.
    net_order = sorted(net_stub_pts.keys(), key=lambda n: (net_priority[n], n))
    for net in net_order:
        pts = net_stub_pts[net]
        names = net_pin_names[net]
        ti = net_track[net]
        track_y = track_slots[ti]

        # Resolve each pin's actual top (trunk-side) X first -- usually
        # just its own vx, but jogged sideways on M2 if the straight run
        # would cross existing M2 (see _find_jog_x above). The M1 trunk's
        # extent must be based on these FINAL top-side X's, not the raw pin
        # X's, since a jogged via can land outside the pins' own X-span.
        resolved = []  # (x, y_center, patch_polys, padded, top_x)
        for (instname, pinname), (x, y_center, patch_polys, padded) in zip(names, pts):
            pref = forced_dir.get((instname, pinname))
            rank = forced_rank.get((instname, pinname), 0)
            top_x = _find_jog_x(x, y_center, track_y, preferred_dir=pref, skip_rank=rank)
            if top_x is None:
                print(f"WARNING: net {net} pin {instname}.{pinname} at ({x:.2f},{y_center:.2f}): "
                      f"no clear M2 jog found within search range; DRC may still flag this via")
                top_x = x
            resolved.append((x, y_center, patch_polys, padded, top_x))

        top_xs = [r[4] for r in resolved]
        x_lo, x_hi = min(top_xs), max(top_xs)

        # horizontal trunk (M1, in the channel -- clear of every row's power
        # rail and every cell's internal M1 by construction, since the
        # channel is otherwise-empty filler space)
        trunk = db.Box(um(x_lo - TRACK_WIDTH / 2), um(track_y - TRACK_WIDTH / 2),
                        um(x_hi + TRACK_WIDTH / 2), um(track_y + TRACK_WIDTH / 2))
        top.shapes(m1_idx).insert(trunk)
        shapes_drawn += 1

        # per-pin escape: V1 via onto the pin's OWN M1 box (widened slightly
        # by abs_pin_anchor() wherever the pin's native shape was exactly at
        # the 3.4um V1 enclosure minimum, with a matching M1 patch drawn so
        # the extra margin is actually real geometry) -> M2 vertical run
        # (crosses the row's power rail + any other cell M1 with no
        # interaction, since it's a different layer; jogged sideways around
        # any pre-existing M2 usage -- see _find_jog_x) -> V1 onto the trunk
        # (trunk thickness TRACK_WIDTH=VIA_PAD already satisfies M1
        # enclosure the same way).
        for x, y_center, patch_polys, padded, top_x in resolved:
            # Only draw extra M1 patch geometry when abs_pin_anchor() had to
            # grow the pin's real net polygon to find a safe via point (the
            # handful of pins with zero native V1-M1 enclosure slack). The
            # patch is the actual grown polygon (not a bbox), so it can
            # never invent metal over a real notch/neighbor gap. For every
            # other pin the library's own pin shape already provides a safe
            # landing point -- no redraw needed.
            if padded:
                for pts_um in patch_polys:
                    poly = db.Polygon([db.Point(um(p.x), um(p.y)) for p in pts_um])
                    top.shapes(m1_idx).insert(poly)
                    shapes_drawn += 1
            top.shapes(v1_idx).insert(pad(x, y_center, VIA_SIZE))

            if top_x != x:
                # Bridge from the pin's own via (at x) over to the jogged X:
                # ONE box spanning the full pad height AND padded out in X
                # by the core's own half-width on the far (top_x) end, so
                # the thin core starting right above it is fully NESTED
                # (flush, same X-range) rather than offset -- an earlier
                # version drew a thin foot flush with top_x and let the
                # (wider) core start right above it slightly off-center,
                # which created a small concave step at the junction that
                # klayout's width_check flagged as a local M2.W1 violation
                # (the notch's own indent, not a true routing-width issue).
                lo, hi = (x, top_x) if x <= top_x else (top_x, x)
                # extend whichever end is the jog (top_x) side outward by
                # the core's own half-width, so the core nests flush
                if x <= top_x:
                    hi += M2_CORE_WIDTH / 2
                else:
                    lo -= M2_CORE_WIDTH / 2
                top.shapes(m2_idx).insert(db.Box(um(lo), um(y_center - M2_PAD_SIZE / 2),
                                                  um(hi), um(y_center + M2_PAD_SIZE / 2)))
                shapes_drawn += 1

            # extend the M2 run slightly past both via centers (not just
            # exactly to them) so each via sits safely INSIDE the M2 shape
            # rather than exactly on its edge (avoids a boundary-exact
            # enclosure DRC failure the same way the M1 pin-box padding
            # above does for V1-M1).
            y0, y1 = (y_center, track_y) if y_center <= track_y else (track_y, y_center)
            # thin core for the long run (just above M2.W1 minimum -- keeps
            # neighboring stubs' clearance close to their full nominal X
            # separation instead of eating 4.0um of it everywhere)
            top.shapes(m2_idx).insert(db.Box(um(top_x - M2_CORE_WIDTH / 2), um(y0 - 0.3),
                                              um(top_x + M2_CORE_WIDTH / 2), um(y1 + 0.3)))
            # full via-pad-sized square ONLY locally at each via endpoint
            top.shapes(m2_idx).insert(pad(x, y_center, M2_PAD_SIZE))
            top.shapes(m2_idx).insert(pad(top_x, track_y, M2_PAD_SIZE))
            top.shapes(v1_idx).insert(pad(top_x, track_y, VIA_SIZE))
            shapes_drawn += 4

        # non-fab annotation (net name at trunk midpoint) for debugging/cross-ref
        label = db.Text(net, db.Trans(um((x_lo + x_hi) / 2), um(track_y)))
        label.size = um(1.5)
        top.shapes(annot_idx).insert(label)

        # Fold this net's own just-drawn M2 (core/bridge/pads) into the
        # obstruction set _find_jog_x checks against, before moving on to
        # the next net. Without this, two DIFFERENT nets' M2 stubs can
        # legally clear the pre-existing (library/filler) M2 yet still land
        # on top of EACH OTHER -- found via a real short: net _018_ (pin
        # _377_.Y) and net rx_data_r[6] (pin _377_.B, the SAME instance's
        # neighboring pin, only 7um away in X) both drew M2 that ended up
        # merged into one physical shape. Ordinary DRC space_check did NOT
        # catch this: two overlapping shapes have zero "gap" between them,
        # so space_check reports 0 violations for an outright short just as
        # readily as for a clean design -- this was only caught by a
        # separate connectivity extraction (verify_pilot_connectivity.py)
        # that traces actual via-to-shape membership per net.
        _existing_m2 = db.Region(top.begin_shapes_rec_touching(m2_idx, _m2_scan_box)).merged()

    print(f"drew {shapes_drawn} shapes (M1 trunks+pads, V1 vias, M2 stubs) for {len(net_stub_pts)} nets")

    os.makedirs(os.path.dirname(OUT_GDS), exist_ok=True)
    layout.write(OUT_GDS)

    # Sidecar JSON: net -> [(instname, pinname, anchor_x_um, anchor_y_um), ...]
    # -- lets a separate connectivity-verification pass re-extract each
    # pin's known net membership and its exact via anchor point (guaranteed
    # to sit inside that pin's own real M1 net polygon) without having to
    # re-derive placement/anchor logic a second time.
    import json
    pin_map = {}
    for net in net_stub_pts:
        pin_map[net] = [
            (instname, pinname, vx, vy)
            for (instname, pinname), (vx, vy, _patch, _padded) in zip(net_pin_names[net], net_stub_pts[net])
        ]
    with open(PIN_MAP_JSON, "w") as f:
        json.dump(pin_map, f, indent=1)
    print("wrote", PIN_MAP_JSON)
    print("wrote", OUT_GDS)


if __name__ == "__main__":
    main()
