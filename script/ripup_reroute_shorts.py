"""
ripup_reroute_shorts.py

General-purpose, net-name-agnostic post-route short fixer (design_notes,
this session: "自動での修正を検討してください。今までの方針を放棄して
新たな提案も歓迎します。今回のNET以外にも応用を広げたいので、汎用に
応用可能なアルゴリズムを提案ください").

WHY THIS EXISTS (replaces the pass-by-pass patching approach):
route_channels_nrow_fm.py's collision avoidance is spread across 4 drawing
passes (per-row-local trunks+spine, high-fo/row-only/adjacent-pair stubs,
spanning nets, FORCE_JOG_NETS), each with a DIFFERENT, hand-tuned live-
collision-check policy. Patching one pass's check (e.g. re-enabling/
generalizing overlap_zone in pass 1, this session) fixes some shorts but
has no effect on others whose true cause lives in a different pass; trying
the same idea in pass 2 caused a severe, non-converging regression (see
design_notes for the full story). The fragility comes from checking for
collisions BEFORE geometry exists (prospectively, pass by pass, using
partial/static assumptions) instead of checking the FINAL, ground-truth
result.

NEW ALGORITHM (industry-standard rip-up & reroute, adapted to this
project's box/via primitives):
  1. Run the router exactly as-is (no changes to route_channels_nrow_fm.py
     needed -- this script is a pure post-process).
  2. Detect every cross-net, same-layer geometric overlap directly from
     net_shapes_*.json (the router's own per-net drawn-box log) -- this is
     layer-exact, net-name-agnostic, and pass-agnostic: it doesn't care
     which pass drew the offending box, only that two DIFFERENT nets'
     metal physically overlaps.
  3. For each conflict, rip up ONE side's offending box (the "mover",
     chosen as whichever net has less total routed metal -- cheaper/safer
     to move) and redraw it via a small local detour that preserves both
     of the box's original electrical endpoints exactly:
       - VERTICAL (M2) box: a "detour-in-X" jog inserted mid-span (two
         M2 legs + one M1 run + two vias), reusing the exact via_1 +
         M1-run pattern route_channels_nrow_fm.py's own draw_jog already
         uses -- just applied locally, after the fact, checked against
         the REAL final geometry instead of a partial pass-time picture.
       - HORIZONTAL (M1) box: the mover's entire track (trunk + every
         stub tapping into it) is relocated to an adjacent, live-checked-
         clear track index in the same channel -- the only safe way to
         move a trunk without breaking the vias along its length.
  4. Re-detect and repeat until 0 conflicts (or a net has been tried as
     both mover and can't be fixed, in which case it is reported, not
     silently dropped).

This never touches route_channels_nrow_fm.py's track-claiming bookkeeping
for any OTHER net, so it cannot cascade into the kind of regression the
in-pass pass-2 experiment produced -- each fix is local, verified against
live geometry, and iterated to a fixed point.

Usage:
    python3 ripup_reroute_shorts.py <in_gds> <pin_map_json> <net_shapes_json> \
        <placement_json> <ch_heights_csv> <out_gds> <out_pin_map_json> \
        <out_net_shapes_json> [max_iters]

Example (v7v2 state, this session):
    python3 ripup_reroute_shorts.py \
        Layout/i2c_slave_async_nrow_fm_v7v2_routed.gds \
        script/pin_map_nrow_fm_v7v2.json \
        script/net_shapes_nrow_fm_v7v2.json \
        LEF/placement_nrow_fm_v7_priomch.json \
        98,332,300,280,100 \
        Layout/i2c_slave_async_nrow_fm_v7rr_routed.gds \
        script/pin_map_nrow_fm_v7rr.json \
        script/net_shapes_nrow_fm_v7rr.json
"""
import json
import sys

import klayout.db as db

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
TECH_PY_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/klayout/tech/python"
sys.path.insert(0, TECH_PY_DIR)
import pya  # noqa: E402
from cells import tr_1um  # noqa: E402

TOP_CELL_NAME = "i2c_slave_async_nrow_fm"
M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
V1_LAYER = (19, 0)

M1_TRUNK_WIDTH = 1.8
M1_PAD_SIZE = 3.4
PAD_HALF = M1_PAD_SIZE / 2.0
TRACK_PITCH = 5.4  # v17 (design_notes 47/48): must match
                    # route_channels_nrow_fm.py's TRACK_PITCH exactly --
                    # this script's track-index math (find_own_trunk,
                    # try_fix_vertical's track relocation) only makes
                    # sense against the SAME pitch the input GDS was
                    # actually routed with.
TRACK0_OFFSET = 2.0
M2_MIN_GAP = 2.0
M1_MIN_GAP = 1.4  # v18 (design_notes 47/48): M1 min-space DRC rule
                   # (matches drc_check_nrow_fm.py's check((13,0), 1.8,
                   # 1.4, 'M1')). via_pad_clear was calling
                   # clear_excluding with margin=0.0 (literal-overlap-
                   # only), so a candidate via pad that merely came
                   # within 1.4um of another net's via pad or trunk --
                   # without literally touching it -- was never flagged.
                   # Confirmed via GDS audit as the exact mechanism
                   # behind 20 new DRC violations this script introduced
                   # after the TRACK_PITCH=5.4 fix (e.g. scl_row0's and
                   # _134_[3]'s own via pads landing only ~0.5um apart).
X_GRID = 5.4

EPS = 1e-6
VIA_MATCH_EPS_UM = 0.06


def overlap_1d(a0, a1, b0, b1):
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return hi - lo


def find_conflicts(net_shapes):
    """All (netA, idxA, netB, idxB) pairs whose boxes share a layer and
    truly overlap (positive area in both X and Y -- exact touching at a
    boundary is legal and not flagged, matching channel_clear's
    `_overlapping` convention elsewhere in this codebase)."""
    nets = list(net_shapes.keys())
    conflicts = []
    for i, na in enumerate(nets):
        for nb in nets[i + 1:]:
            for ia, (lyr_a, ax0, ay0, ax1, ay1) in enumerate(net_shapes[na]):
                for ib, (lyr_b, bx0, by0, bx1, by1) in enumerate(net_shapes[nb]):
                    if lyr_a != lyr_b:
                        continue
                    ox = overlap_1d(ax0, ax1, bx0, bx1)
                    oy = overlap_1d(ay0, ay1, by0, by1)
                    if ox > EPS and oy > EPS:
                        conflicts.append((na, ia, nb, ib, lyr_a))
    return conflicts


class Fixer:
    def __init__(self, in_gds, pin_map, net_shapes, ch_y0, ch_heights, row_width):
        self.layout = db.Layout()
        self.layout.read(in_gds)
        self.dbu = self.layout.dbu
        self.top = self.layout.cell(TOP_CELL_NAME)
        self.m1_idx = self.layout.layer(*M1_LAYER)
        self.m2_idx = self.layout.layer(*M2_LAYER)
        tr_1um("TR-1um")
        via_lib = pya.Library.library_by_name("TR-1um", "*")
        self.via_lib = via_lib
        self.via_decl = via_lib.layout().pcell_declaration("via_1")
        self.pin_map = pin_map
        self.net_shapes = net_shapes
        self.ch_y0 = ch_y0
        self.ch_heights = ch_heights
        self.row_width = row_width
        self.fixed_vertical = 0
        self.fixed_horizontal = 0
        self.failed = []

    def um(self, v):
        return int(round(v / self.dbu))

    def layer_idx(self, layer_name):
        return self.m1_idx if layer_name == "M1" else self.m2_idx

    # ---- live geometry queries (mirrors route_channels_nrow_fm.py's
    # channel_clear -- same _overlapping (not _touching) semantics, so a
    # candidate at exactly the legal minimum spacing is not falsely
    # rejected) ----
    def region_in_box(self, layer_name, x0, y0, x1, y1, margin=0.0):
        probe = db.Box(self.um(min(x0, x1) - margin), self.um(min(y0, y1) - margin),
                        self.um(max(x0, x1) + margin), self.um(max(y0, y1) + margin))
        return db.Region(self.top.begin_shapes_rec_overlapping(self.layer_idx(layer_name), probe)).merged()

    def clear_excluding(self, layer_name, x0, y0, x1, y1, exclude_net, margin=0.0):
        """Is box (x0,y0,x1,y1) [+margin] free of every OTHER net's metal
        (and free of real cell/TAP geometry) on `layer_name`? `exclude_net`'s
        OWN currently-remaining boxes on this layer are subtracted first, so
        a net's already-deleted-and-not-yet-replaced segment never self-
        blocks its own replacement search.

        Also subtracts a via_1-pad-sized (M1_PAD_SIZE^2) box at every
        endpoint of every one of exclude_net's OWN shapes (any layer) --
        via_1 PCell instances draw their own M1+M2 pads as part of the
        PCell's internal geometry (see place_via/route_channels_
        nrow_fm.py), which is NOT recorded in net_shapes (only the plain
        m1_box/m2_box calls are). Without this, a candidate that starts
        exactly at a net's own existing via (e.g. bending right at the
        pin end, which may itself already be a jog landing from the
        original router, not a raw cell pin) always self-collides with
        that via's own unrecorded pad and every candidate direction
        looks blocked."""
        region = self.region_in_box(layer_name, x0, y0, x1, y1, margin)
        if region.is_empty():
            return True
        own = db.Region()
        half = M1_PAD_SIZE / 2.0
        for lyr, bx0, by0, bx1, by1 in self.net_shapes.get(exclude_net, []):
            if lyr == layer_name:
                own.insert(db.Box(self.um(bx0), self.um(by0), self.um(bx1), self.um(by1)))
            # via_1 pad centers sit on this box's OWN centerline, not its
            # raw corners -- a vertical (M2) box's via's are at
            # (mid-x, y0) and (mid-x, y1); a horizontal (M1) box's are at
            # (x0, mid-y) and (x1, mid-y). Using raw corners here (an
            # earlier version of this fix) put the excluded pad ~PAD_HALF
            # off from the real via, leaving a sliver of the via's own
            # pad unexcluded -- which then blocked every single detour
            # candidate near a net's own via, no matter which direction
            # it searched.
            if (bx1 - bx0) >= (by1 - by0):
                mid = (by0 + by1) / 2.0
                pts = ((bx0, mid), (bx1, mid))
            else:
                mid = (bx0 + bx1) / 2.0
                pts = ((mid, by0), (mid, by1))
            for ex, ey in pts:
                own.insert(db.Box(self.um(ex - half), self.um(ey - half),
                                   self.um(ex + half), self.um(ey + half)))
        if not own.is_empty():
            region -= own.merged()
        return region.is_empty()

    # ---- GDS mutation helpers ----
    def delete_box(self, layer_name, box):
        x0, y0, x1, y1 = box
        target = db.Box(self.um(x0), self.um(y0), self.um(x1), self.um(y1))
        idx = self.layer_idx(layer_name)
        for shape in list(self.top.shapes(idx).each()):
            if shape.box == target:
                shape.delete()
                return True
        return False

    def add_box(self, layer_name, x0, y0, x1, y1):
        self.top.shapes(self.layer_idx(layer_name)).insert(
            db.Box(self.um(x0), self.um(y0), self.um(x1), self.um(y1)))

    def add_via(self, x, y):
        pcell_idx = self.layout.add_pcell_variant(
            self.via_lib, self.via_decl.id(), {"x": M1_PAD_SIZE, "y": M1_PAD_SIZE, "x0": "c", "y0": "c"})
        self.top.insert(db.CellInstArray(pcell_idx, db.Trans(db.Vector(self.um(x), self.um(y)))))

    def remove_via_at(self, x, y):
        target = db.Vector(self.um(x), self.um(y))
        eps = self.um(VIA_MATCH_EPS_UM)
        removed = 0
        for inst in list(self.top.each_inst()):
            if inst.cell.name != "via_1":
                continue
            d = inst.trans.disp
            if abs(d.x - target.x) <= eps and abs(d.y - target.y) <= eps:
                inst.delete()
                removed += 1
        return removed

    # ---- fix strategies ----
    def via_pad_clear(self, net, x, y):
        """Explicit clearance check for a via_1's full (M1_PAD_SIZE x
        M1_PAD_SIZE) pad footprint at (x,y), on BOTH layers. Added after
        finding (via GDS forensics, this session) that the "leg"/"ext"
        box checks alone under-cover a via pad at the END of a run: a
        leg box's Y-range stops exactly AT the via's nominal Y, but the
        via's own pad extends M1_PAD_SIZE/2=1.7um further OUTWARD from
        that point (M1_TRUNK_WIDTH/2=0.9 or the leg's own half-width
        don't reach that far) -- so a via landing right at the edge of
        an otherwise-clear leg could still have its pad overlap
        something just beyond what was checked. Confirmed as the exact
        mechanism behind a txreg[4]/scl_row3 short that survived an
        earlier version of this fix (txreg[4]'s new trunk-side via's pad
        overlapped scl_row3's trunk, one edge case the leg check missed)."""
        half = M1_PAD_SIZE / 2.0
        # v18: margin=M1_MIN_GAP/M2_MIN_GAP (was margin=0.0, the
        # clear_excluding default) -- a via pad footprint check with no
        # margin only rejects LITERAL overlap, not a too-close-but-not-
        # touching neighbor. Expanding the probe box by the actual DRC
        # min-space rule for each layer means clear_excluding's overlap
        # test is equivalent to a real space-check, not just a touch test.
        return (self.clear_excluding("M1", x - half, y - half, x + half, y + half,
                                      exclude_net=net, margin=M1_MIN_GAP)
                and self.clear_excluding("M2", x - half, y - half, x + half, y + half,
                                          exclude_net=net, margin=M2_MIN_GAP))

    def find_own_trunk(self, net, y_target):
        """This net's own horizontal M1 trunk box whose track level
        (y-midpoint) matches y_target -- identifies which end of a stub
        is the "trunk end" (an M1 trunk can be safely extended in X,
        since it's this SAME net's own metal -- unlike the pin end,
        which is a real standard-cell pin and can never move)."""
        for lyr, bx0, by0, bx1, by1 in self.net_shapes.get(net, []):
            if lyr != "M1":
                continue
            if abs((by0 + by1) / 2.0 - y_target) < EPS and (bx1 - bx0) >= (by1 - by0):
                return (bx0, by0, bx1, by1)
        return None

    def try_fix_vertical(self, net, box):
        """box = (x0,y0,x1,y1), a vertical M2 run at cx=(x0+x1)/2 between
        two endpoints, each either (a) this net's own OTHER metal (an M1
        trunk/run at that Y level -- movable, since it's this SAME net's
        metal and can be extended sideways to meet a new via without
        touching any other net) or (b) a true standard-cell pin (fixed,
        can never move). Moves the ENTIRE span to a new column clear_x:
        each (a)-type end gets its own connector extended to clear_x
        (no new via needed beyond the one at the new landing point);
        each (b)-type end gets a short via-M1-via stub bending from the
        fixed pin at cx over to clear_x.

        v2 (this session): originally this only ever treated ONE end as
        movable (whichever matched find_own_trunk) and assumed the OTHER
        was a real pin, bending back to its exact original (cx, y)
        unconditionally. That produced a NEW via at that exact point --
        which, for case-2-style conflicts (the two nets' vias land at
        the *same* X), can itself still sit inside the other net's
        still-unmoved box, since the conflict often reaches all the way
        to that endpoint. Confirmed via GDS forensics: a via re-created
        at the assumed-safe "pin" end was found sharing a component with
        the very net this fix was resolving. Both ends are now checked
        symmetrically -- most of this design's stubs turn out to have an
        own-net connector (an earlier jog's M1 run) at BOTH ends anyway,
        not just the trunk end, so both can move."""
        x0, y0, x1, y1 = box
        cx = (x0 + x1) / 2.0
        ylo, yhi = min(y0, y1), max(y0, y1)
        half_w = M1_TRUNK_WIDTH / 2.0

        conn_lo = self.find_own_trunk(net, ylo)
        conn_hi = self.find_own_trunk(net, yhi)
        if conn_lo is None and conn_hi is None:
            return False  # both ends look like real pins -- can't move either

        ends = [(ylo, conn_lo), (yhi, conn_hi)]

        for k in range(1, 300):
            for clear_x in (cx + k * X_GRID, cx - k * X_GRID):
                leg = (clear_x - PAD_HALF, ylo, clear_x + PAD_HALF, yhi)
                if not self.clear_excluding("M2", *leg, exclude_net=net, margin=M2_MIN_GAP):
                    continue
                ok = True
                per_end = []  # (y_here, conn, run_box_or_None, ext_box_or_None)
                for y_here, conn in ends:
                    if not self.via_pad_clear(net, clear_x, y_here):
                        ok = False
                        break
                    if conn is not None:
                        cb0, cb1 = conn[0], conn[2]
                        ext = None
                        if clear_x < cb0 or clear_x > cb1:
                            ext = (min(clear_x, cb0), y_here - half_w, max(clear_x, cb1), y_here + half_w)
                            if not self.clear_excluding("M1", *ext, exclude_net=net, margin=M1_MIN_GAP):
                                ok = False
                                break
                        per_end.append((y_here, conn, None, ext))
                    else:
                        # a real standard-cell pin: its own copper is
                        # necessarily right at (cx, y_here) already (not
                        # recorded in net_shapes, since it's the cell's
                        # own LEF geometry, not something this router
                        # drew) -- never collision-checked here, exactly
                        # like the ORIGINAL router never checks it either
                        # (m2_box's very first call always starts flush
                        # against the pin's own pad). Only the M1 run
                        # departing from it needs checking.
                        run = (min(cx, clear_x), y_here - half_w, max(cx, clear_x), y_here + half_w)
                        if not self.clear_excluding("M1", *run, exclude_net=net, margin=M1_MIN_GAP):
                            ok = False
                            break
                        per_end.append((y_here, conn, run, None))
                if not ok:
                    continue

                # commit
                self.delete_box("M2", box)
                self.net_shapes[net] = [s for s in self.net_shapes[net] if tuple(s) != ("M2",) + box]
                self.add_box("M2", *leg)
                self.net_shapes[net].append(["M2", *leg])
                for y_here, conn, run, ext in per_end:
                    if conn is not None:
                        self.remove_via_at(cx, y_here)
                        if ext is not None:
                            self.delete_box("M1", conn)
                            self.net_shapes[net] = [s for s in self.net_shapes[net] if tuple(s) != ("M1",) + conn]
                            self.add_box("M1", *ext)
                            self.net_shapes[net].append(["M1", *ext])
                        self.add_via(clear_x, y_here)
                    else:
                        self.add_box("M1", *run)
                        self.net_shapes[net].append(["M1", *run])
                        self.add_via(cx, y_here)
                        self.add_via(clear_x, y_here)
                if net in self.pin_map:
                    updated = []
                    for inst, pname, vx, vy in self.pin_map[net]:
                        if abs(vx - cx) < EPS and (abs(vy - ylo) < EPS or abs(vy - yhi) < EPS):
                            vx = clear_x
                        updated.append([inst, pname, vx, vy])
                    self.pin_map[net] = updated
                self.fixed_vertical += 1
                return True
        return False

    def channel_of(self, y):
        for c, y0 in enumerate(self.ch_y0):
            if y0 - EPS <= y <= y0 + self.ch_heights[c] + EPS:
                return c
        return None

    def try_fix_horizontal(self, net, box):
        """box = the net's M1 trunk (or a horizontal run at some fixed
        track_y). Relocate the WHOLE net (trunk + every stub tapping into
        it, + their vias) to an adjacent, live-checked-clear track index
        in the same channel -- the only way to move a trunk without
        breaking any via along its length."""
        x0, y0, x1, y1 = box
        old_track_y = (y0 + y1) / 2.0
        c = self.channel_of(old_track_y)
        if c is None:
            return False
        idx_hi = int((self.ch_heights[c] - 2 * TRACK0_OFFSET) // TRACK_PITCH)
        old_idx = int(round((old_track_y - self.ch_y0[c] - TRACK0_OFFSET) / TRACK_PITCH))

        # every one of this net's boxes/vias that sit at old_track_y --
        # these are what must move together. An M1 box "sits" there if
        # its OWN track level (y-midpoint) matches (it's the trunk
        # itself, or a jog run on that same track); an M2 box "sits"
        # there if either of its Y endpoints matches (it's a stub or
        # spine leg landing on that track).
        tol = 1e-3
        touching = []
        for s in self.net_shapes.get(net, []):
            lyr, bx0, by0, bx1, by1 = s
            if lyr == "M1":
                if abs((by0 + by1) / 2.0 - old_track_y) < tol:
                    touching.append(tuple(s))
            else:
                if abs(by0 - old_track_y) < tol or abs(by1 - old_track_y) < tol:
                    touching.append(tuple(s))
        if not touching:
            return False

        for offset in range(1, idx_hi + 2):
            for new_idx in (old_idx + offset, old_idx - offset):
                if new_idx < 0 or new_idx > idx_hi or new_idx == old_idx:
                    continue
                new_track_y = self.ch_y0[c] + TRACK0_OFFSET + new_idx * TRACK_PITCH
                delta = new_track_y - old_track_y
                new_boxes = []
                ok = True
                for lyr, bx0, by0, bx1, by1 in touching:
                    if lyr == "M1":
                        # the whole trunk (or jog run) moves by delta
                        nby0, nby1 = by0 + delta, by1 + delta
                    else:
                        # only the endpoint AT the track moves; the far
                        # endpoint (a real pin edge, or another track's
                        # landing) stays exactly where it is
                        nby0 = new_track_y if abs(by0 - old_track_y) < tol else by0
                        nby1 = new_track_y if abs(by1 - old_track_y) < tol else by1
                    cand = (bx0, nby0, bx1, nby1)
                    cand_margin = M1_MIN_GAP if lyr == "M1" else M2_MIN_GAP
                    if not self.clear_excluding(lyr, *cand, exclude_net=net, margin=cand_margin):
                        ok = False
                        break
                    new_boxes.append((lyr, cand))
                if not ok:
                    continue
                # commit: delete old boxes + vias, insert relocated ones
                via_xs = set()
                for lyr, bx0, by0, bx1, by1 in touching:
                    self.delete_box(lyr, (bx0, by0, bx1, by1))
                    self.net_shapes[net] = [s for s in self.net_shapes[net]
                                             if tuple(s) != (lyr, bx0, by0, bx1, by1)]
                    if lyr == "M2":
                        cx = (bx0 + bx1) / 2.0
                        via_xs.add(round(cx, 6))
                for cx in via_xs:
                    self.remove_via_at(cx, old_track_y)
                for lyr, cand in new_boxes:
                    self.add_box(lyr, *cand)
                    self.net_shapes[net].append([lyr, *cand])
                for cx in via_xs:
                    self.add_via(cx, new_track_y)
                # update pin_map entries whose via sat at old_track_y for this net
                if net in self.pin_map:
                    updated = []
                    for inst, pname, vx, vy in self.pin_map[net]:
                        if abs(vy - old_track_y) < EPS:
                            vy = new_track_y
                        updated.append([inst, pname, vx, vy])
                    self.pin_map[net] = updated
                self.fixed_horizontal += 1
                return True
        return False


def main():
    args = sys.argv[1:]
    in_gds, pin_map_json, net_shapes_json, placement_json, ch_heights_csv, \
        out_gds, out_pin_map_json, out_net_shapes_json = args[:8]
    max_iters = int(args[8]) if len(args) > 8 else 40

    ch_heights = [float(v) for v in ch_heights_csv.split(",")]
    placement = json.load(open(placement_json))
    row_h = placement["row_height"]
    n_rows = len(placement["rows"])
    assert len(ch_heights) == n_rows + 1
    ch_y0 = []
    y = 0.0
    for i in range(n_rows):
        ch_y0.append(y)
        y += ch_heights[i]
        y += row_h
    ch_y0.append(y)
    row_width = placement["row_width"]

    pin_map = json.load(open(pin_map_json))
    net_shapes = json.load(open(net_shapes_json))

    # classify each net, ONCE, from its ORIGINAL (pre-fix) geometry: does
    # it have M1 trunk-like boxes at more than one distinct track level?
    # If so it's a multi-segment/high-fanout "spine" net (per-row-local
    # trunks, high-FO dedicated nets, etc.) -- moving or extending ANY
    # single piece of a net like that risks the exact kind of cascade
    # this session found the hard way (RSTB1, a 23-pin reset spine
    # spanning 4 channels, picked as a fallback mover, ended up
    # physically touching an unrelated net's track far from the
    # original conflict -- confirmed via GDS forensics after the fact).
    # Only genuinely simple, single-track nets are ever moved; a
    # conflict where BOTH sides are "complex" is left unresolved and
    # reported, rather than risking a new, harder-to-diagnose short.
    # a net is "complex" if it's genuinely high-fanout (many pins -- same
    # threshold the router itself uses, HIGH_FO_THRESHOLD=8) OR it has
    # REAL trunk segments (wide M1, >30um -- long enough to actually
    # connect multiple far-apart pins) at more than one distinct track
    # level (a per-row-local/spine net with its own multi-channel
    # structure). Width-filtered so an ordinary net that merely picked
    # up a short local jog dogleg somewhere (5-15um, a single detour
    # step, common even for a simple 2-pin net) is NOT misclassified as
    # complex just because that dogleg happens to sit at a different Y
    # than its own trunk -- an earlier version of this check used ANY
    # horizontal M1 box regardless of width and over-flagged 34 of this
    # design's ~165 nets, most of which were perfectly simple.
    TRUNK_WIDTH_THRESHOLD = 30.0

    def classify_complex(net, shapes):
        if len(pin_map.get(net, [])) > 8:
            return True
        levels = set()
        for lyr, x0, y0, x1, y1 in shapes:
            if lyr != "M1":
                continue
            if (x1 - x0) < (y1 - y0) or (x1 - x0) < TRUNK_WIDTH_THRESHOLD:
                continue  # not a real trunk (a short jog dogleg, not a track)
            levels.add(round((y0 + y1) / 2.0, 1))
        return len(levels) > 1
    complex_nets = {n for n, shapes in net_shapes.items() if classify_complex(n, shapes)}
    if complex_nets:
        print(f"{len(complex_nets)} multi-segment/high-fanout net(s) excluded from ever being "
              f"moved (moved only if the OTHER side of a conflict is simple): {sorted(complex_nets)}")

    fixer = Fixer(in_gds, pin_map, net_shapes, ch_y0, ch_heights, row_width)

    permanently_failed = set()
    it = 0
    while it < max_iters:
        it += 1
        conflicts = find_conflicts(fixer.net_shapes)
        conflicts = [c for c in conflicts if (c[0], c[2]) not in permanently_failed
                     and (c[2], c[0]) not in permanently_failed]
        if not conflicts:
            print(f"iteration {it}: 0 conflicts remain -- converged")
            break
        na, ia, nb, ib, lyr = conflicts[0]
        box_a = tuple(fixer.net_shapes[na][ia][1:])
        box_b = tuple(fixer.net_shapes[nb][ib][1:])
        a_ok, b_ok = na not in complex_nets, nb not in complex_nets
        if not a_ok and not b_ok:
            print(f"iteration {it}: {na} <-> {nb} on {lyr} -- BOTH sides are multi-segment/"
                  f"high-fanout nets, refusing to move either (too high a cascade risk) -- "
                  f"unresolved")
            permanently_failed.add((na, nb))
            continue
        if a_ok and b_ok:
            area_a = sum((abs(s[3] - s[1]) * abs(s[4] - s[2])) for s in fixer.net_shapes[na])
            area_b = sum((abs(s[3] - s[1]) * abs(s[4] - s[2])) for s in fixer.net_shapes[nb])
            mover, box, fallback, fbox = (na, box_a, nb, box_b) if area_a <= area_b else (nb, box_b, na, box_a)
            try_fallback = True
        elif a_ok:
            mover, box, fallback, fbox = na, box_a, None, None
            try_fallback = False
        else:
            mover, box, fallback, fbox = nb, box_b, None, None
            try_fallback = False

        x0, y0, x1, y1 = box
        vertical = (y1 - y0) >= (x1 - x0)
        print(f"iteration {it}: {na} <-> {nb} on {lyr}, moving {mover} "
              f"({'vertical' if vertical else 'horizontal'} box {tuple(round(v,2) for v in box)})")

        if vertical:
            fixed = fixer.try_fix_vertical(mover, box)
        else:
            fixed = fixer.try_fix_horizontal(mover, box)

        if not fixed and try_fallback:
            print(f"  {mover}'s side could not be fixed -- trying {fallback} instead")
            fx0, fy0, fx1, fy1 = fbox
            f_vertical = (fy1 - fy0) >= (fx1 - fx0)
            fixed = fixer.try_fix_vertical(fallback, fbox) if f_vertical else fixer.try_fix_horizontal(fallback, fbox)

        if not fixed:
            print(f"  could not fix {na}<->{nb} without touching a multi-segment/high-fanout "
                  f"net -- giving up on this pair, will still report as unresolved")
            permanently_failed.add((na, nb))
    else:
        print(f"reached max_iters={max_iters} without full convergence")

    remaining = find_conflicts(fixer.net_shapes)
    print(f"\nfixed {fixer.fixed_vertical} vertical + {fixer.fixed_horizontal} horizontal segment(s), "
          f"{len(remaining)} raw box conflict(s) remain")
    if remaining:
        pairs = {(c[0], c[2]) for c in remaining}
        print("unresolved net pairs:", pairs)

    fixer.layout.write(out_gds)
    with open(out_pin_map_json, "w") as f:
        json.dump(fixer.pin_map, f, indent=1)
    with open(out_net_shapes_json, "w") as f:
        json.dump(fixer.net_shapes, f)
    print(f"wrote {out_gds}")
    print(f"wrote {out_pin_map_json}")
    print(f"wrote {out_net_shapes_json}")


if __name__ == "__main__":
    main()
