"""
fix_v8_remaining_shorts.py

Targeted, verified manual fix for the 3 SHORT SUSPECTED pairs remaining in
the DFFS-less V8 route (layout/step8/v8_step_3_ripup_reroute.gds) that
ripup_reroute_shorts.py's own automatic pass refused to touch (every pair
has BOTH sides classified "complex": high-fanout and/or per-row-local
spine nets, so the safety rule declines to move either one).

Root-cause analysis this session (see design_notes.md, new section) found
each conflict is a straightforward same-column (vertical M2) or
same-track (horizontal M1 trunk) collision with real free space nearby --
confirmed via klayout region queries against the FULL routed GDS (not
just net_shapes.json, which does not record via_1 PCells' own M1/M2 pad
footprints or real standard-cell pin geometry).

This script reuses ripup_reroute_shorts.py's Fixer class (same
clear_excluding/via_pad_clear/find_own_trunk live-geometry checks,
same GDS mutation primitives) so every move is checked against the exact
same DRC-aware rules the automatic pass uses -- only the "which net is
allowed to move" gate is bypassed, and only for these 3 hand-verified
cases.

Extra wrinkle found this session: two of the three conflicting nets
(_177_ at pair 1, scl_row1 at pair 2) are recorded in net_shapes.json as
MULTIPLE separate M2 boxes stacked on the same column with no via between
them (an artifact of route_channels_nrow_fm.py logging one box per
channel crossed, even when physically contiguous). Fixer.try_fix_vertical
only deletes/moves ONE box at a time and would silently no-op (delete_box
finds no match) if given a synthetic merged span, leaving stale geometry
behind -- so this script's move_multi_piece_vertical() generalizes the
same algorithm to delete N exact, verified-existing pieces and redraw one
merged replacement leg.

Conflicts fixed (mover chosen as whichever side turned out to have a
clean, verified move -- see design_notes for the alternatives that were
tried and rejected):
  1. scl_row0 <-> _177_        : move _177_'s 3-piece column (X 881.2,
     Y 77.6->830.2) sideways; scl_row0 is left untouched.
  2. scl_n_row1 <-> scl_row1   : move scl_row1's 3-piece column (X 989.2,
     Y 1107.6->2022.2) sideways; scl_n_row1 is left untouched.
  3. sda_in_buf <-> scl_row0   : move scl_row0's per-row-local M1 trunk
     (channel 1, track_y ~452.2) to an adjacent track index via
     Fixer.try_fix_horizontal (handles every stub/via on that track
     already, no multi-piece issue).
"""
import json
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from ripup_reroute_shorts import (  # noqa: E402
    Fixer, X_GRID, PAD_HALF, M1_TRUNK_WIDTH, M2_MIN_GAP, M1_MIN_GAP,
)

IN_GDS = "../layout/step8/v8_step_3_ripup_reroute.gds"
PIN_MAP_JSON = "pin_map_nrow_fm_v8rr.json"
NET_SHAPES_JSON = "net_shapes_nrow_fm_v8rr.json"
PLACEMENT_JSON = "../LEF/placement_nrow_fm_v8.json"
CH_HEIGHTS = [174.8, 601.4, 542.0, 515.0, 196.4]

OUT_GDS = "../layout/step8/v8_step_4_manual_short_fix.gds"
OUT_PIN_MAP_JSON = "pin_map_nrow_fm_v8final.json"
OUT_NET_SHAPES_JSON = "net_shapes_nrow_fm_v8final.json"


def move_multi_piece_vertical(fixer, net, pieces, max_k=300):
    """Generalization of Fixer.try_fix_vertical for a net whose column is
    recorded as multiple contiguous M2 boxes (no via between them).
    `pieces` = exact ["M2",x0,y0,x1,y1] entries (as currently present in
    fixer.net_shapes[net]) forming one continuous run on a single column.
    Deletes all of them, draws one merged replacement leg on a new,
    live-checked-clear column, and reconnects both true endpoints exactly
    like try_fix_vertical does (own-trunk extension, or a short M1
    pin-jog + new via, for whichever end isn't this net's own trunk)."""
    tuples = [tuple(p) for p in pieces]
    x0 = pieces[0][1]
    cx = (pieces[0][1] + pieces[0][3]) / 2.0
    ylo = min(min(p[2], p[4]) for p in pieces)
    yhi = max(max(p[2], p[4]) for p in pieces)
    half_w = M1_TRUNK_WIDTH / 2.0

    conn_lo = fixer.find_own_trunk(net, ylo)
    conn_hi = fixer.find_own_trunk(net, yhi)
    if conn_lo is None and conn_hi is None:
        return False
    ends = [(ylo, conn_lo), (yhi, conn_hi)]

    for k in range(1, max_k):
        for clear_x in (cx + k * X_GRID, cx - k * X_GRID):
            leg = (clear_x - PAD_HALF, ylo, clear_x + PAD_HALF, yhi)
            if not fixer.clear_excluding("M2", *leg, exclude_net=net, margin=M2_MIN_GAP):
                continue
            ok = True
            per_end = []
            for y_here, conn in ends:
                if not fixer.via_pad_clear(net, clear_x, y_here):
                    ok = False
                    break
                if conn is not None:
                    cb0, cb1 = conn[0], conn[2]
                    ext = None
                    if clear_x < cb0 or clear_x > cb1:
                        ext = (min(clear_x, cb0), y_here - half_w, max(clear_x, cb1), y_here + half_w)
                        if not fixer.clear_excluding("M1", *ext, exclude_net=net, margin=M1_MIN_GAP):
                            ok = False
                            break
                    per_end.append((y_here, conn, None, ext))
                else:
                    run = (min(cx, clear_x), y_here - half_w, max(cx, clear_x), y_here + half_w)
                    if not fixer.clear_excluding("M1", *run, exclude_net=net, margin=M1_MIN_GAP):
                        ok = False
                        break
                    per_end.append((y_here, conn, run, None))
            if not ok:
                continue

            # commit: delete every real piece, add ONE merged leg
            for t in tuples:
                fixer.delete_box(t[0], t[1:])
                fixer.net_shapes[net] = [s for s in fixer.net_shapes[net] if tuple(s) != t]
            fixer.add_box("M2", *leg)
            fixer.net_shapes[net].append(["M2", *leg])
            for y_here, conn, run, ext in per_end:
                if conn is not None:
                    fixer.remove_via_at(cx, y_here)
                    if ext is not None:
                        fixer.delete_box("M1", conn)
                        fixer.net_shapes[net] = [s for s in fixer.net_shapes[net] if tuple(s) != ("M1",) + conn]
                        fixer.add_box("M1", *ext)
                        fixer.net_shapes[net].append(["M1", *ext])
                    fixer.add_via(clear_x, y_here)
                else:
                    fixer.add_box("M1", *run)
                    fixer.net_shapes[net].append(["M1", *run])
                    fixer.add_via(cx, y_here)
                    fixer.add_via(clear_x, y_here)
            if net in fixer.pin_map:
                updated = []
                for inst, pname, vx, vy in fixer.pin_map[net]:
                    if abs(vx - cx) < 1e-6 and (abs(vy - ylo) < 1e-6 or abs(vy - yhi) < 1e-6):
                        vx = clear_x
                    updated.append([inst, pname, vx, vy])
                fixer.pin_map[net] = updated
            fixer.fixed_vertical += 1
            return True
    return False


def try_fix_horizontal_incremental(fixer, net, box, max_offset=200):
    """Variant of Fixer.try_fix_horizontal for a track whose touching M2
    stubs include long runs that already sit at the DRC-margin edge of
    some OTHER fixed geometry along their UNCHANGED far portion (real
    standard-cell pin drops through a densely-packed row body, which
    route_channels_nrow_fm.py's own per-row-local pass 0 deliberately
    never live-checks -- see its "leg 1... same never-checked assumption"
    comment). try_fix_horizontal's full-box clear_excluding re-litigates
    that already-accepted, unchanged far portion on every candidate
    index and always fails, regardless of target -- confirmed this
    session via direct clear_excluding probing (same net, same box,
    unmoved, already fails the margin check; every one of ~15-20 tried
    offsets in both directions fails identically).

    Only the geometry that is actually NEW needs to be checked: for each
    M2 stub, that's the strip between old_track_y and new_track_y (the
    far endpoint doesn't move and was already validated -- or at least
    already accepted -- when the router originally drew it). The M1
    trunk itself (this net's own metal, genuinely relocating in full) is
    still checked as a whole, same as the original tool."""
    from ripup_reroute_shorts import EPS, TRACK0_OFFSET, TRACK_PITCH, M1_MIN_GAP, M2_MIN_GAP

    x0, y0, x1, y1 = box
    old_track_y = (y0 + y1) / 2.0
    c = fixer.channel_of(old_track_y)
    if c is None:
        return False
    idx_hi = int((fixer.ch_heights[c] - 2 * TRACK0_OFFSET) // TRACK_PITCH)
    old_idx = int(round((old_track_y - fixer.ch_y0[c] - TRACK0_OFFSET) / TRACK_PITCH))

    tol = 1e-3
    touching = []
    for s in fixer.net_shapes.get(net, []):
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
            new_track_y = fixer.ch_y0[c] + TRACK0_OFFSET + new_idx * TRACK_PITCH
            delta = new_track_y - old_track_y
            new_boxes = []
            ok = True
            for lyr, bx0, by0, bx1, by1 in touching:
                margin = M1_MIN_GAP if lyr == "M1" else M2_MIN_GAP
                if lyr == "M1":
                    nby0, nby1 = by0 + delta, by1 + delta
                    cand = (bx0, nby0, bx1, nby1)
                    if not fixer.clear_excluding(lyr, *cand, exclude_net=net, margin=margin):
                        ok = False
                        break
                else:
                    nby0 = new_track_y if abs(by0 - old_track_y) < tol else by0
                    nby1 = new_track_y if abs(by1 - old_track_y) < tol else by1
                    cand = (bx0, nby0, bx1, nby1)
                    lo, hi = sorted([old_track_y, new_track_y])
                    probe = (bx0, lo, bx1, hi)
                    if not fixer.clear_excluding("M2", *probe, exclude_net=net, margin=margin):
                        ok = False
                        break
                new_boxes.append((lyr, cand))
            if not ok:
                continue
            # commit (identical to Fixer.try_fix_horizontal's own commit)
            via_xs = set()
            for lyr, bx0, by0, bx1, by1 in touching:
                fixer.delete_box(lyr, (bx0, by0, bx1, by1))
                fixer.net_shapes[net] = [s for s in fixer.net_shapes[net]
                                          if tuple(s) != (lyr, bx0, by0, bx1, by1)]
                if lyr == "M2":
                    cx = (bx0 + bx1) / 2.0
                    via_xs.add(round(cx, 6))
            for cx in via_xs:
                fixer.remove_via_at(cx, old_track_y)
            for lyr, cand in new_boxes:
                fixer.add_box(lyr, *cand)
                fixer.net_shapes[net].append([lyr, *cand])
            for cx in via_xs:
                fixer.add_via(cx, new_track_y)
            if net in fixer.pin_map:
                updated = []
                for inst, pname, vx, vy in fixer.pin_map[net]:
                    if abs(vy - old_track_y) < EPS:
                        vy = new_track_y
                    updated.append([inst, pname, vx, vy])
                fixer.pin_map[net] = updated
            fixer.fixed_horizontal += 1
            return True
    return False


def main():
    placement = json.load(open(PLACEMENT_JSON))
    row_h = placement["row_height"]
    n_rows = len(placement["rows"])
    row_width = placement["row_width"]
    assert len(CH_HEIGHTS) == n_rows + 1

    ch_y0 = []
    y = 0.0
    for i in range(n_rows):
        ch_y0.append(y)
        y += CH_HEIGHTS[i]
        y += row_h
    ch_y0.append(y)

    pin_map = json.load(open(PIN_MAP_JSON))
    net_shapes = json.load(open(NET_SHAPES_JSON))

    fixer = Fixer(IN_GDS, pin_map, net_shapes, ch_y0, CH_HEIGHTS, row_width)

    # --- pair 1: move _177_'s 3-piece column off X=881.2 ---
    pieces_177 = [s for s in fixer.net_shapes["_177_"] if s[0] == "M2" and abs(s[1] - 881.2) < 0.1]
    assert len(pieces_177) == 3, pieces_177
    ok1 = move_multi_piece_vertical(fixer, "_177_", pieces_177)
    print(f"pair 1 (_177_ column move): {'OK' if ok1 else 'FAILED'}")
    if not ok1:
        sys.exit(1)

    # --- pair 2: move scl_row1's 3-piece column off X=989.2 ---
    pieces_row1 = [s for s in fixer.net_shapes["scl_row1"] if s[0] == "M2" and abs(s[1] - 989.2) < 0.1
                   and s[2] >= 1000.0]
    assert len(pieces_row1) == 3, pieces_row1
    ok2 = move_multi_piece_vertical(fixer, "scl_row1", pieces_row1)
    print(f"pair 2 (scl_row1 column move): {'OK' if ok2 else 'FAILED'}")
    if not ok2:
        sys.exit(1)

    # --- pair 3: relocate scl_row0's channel-1 per-row-local trunk ---
    trunk_box = next(
        (tuple(s[1:]) for s in fixer.net_shapes["scl_row0"] if s[0] == "M1" and abs((s[2] + s[4]) / 2 - 452.2) < 0.5),
        None,
    )
    assert trunk_box is not None
    ok3 = try_fix_horizontal_incremental(fixer, "scl_row0", trunk_box)
    print(f"pair 3 (scl_row0 trunk relocation): {'OK' if ok3 else 'FAILED'}")
    if not ok3:
        sys.exit(1)

    fixer.layout.write(OUT_GDS)
    json.dump(fixer.pin_map, open(OUT_PIN_MAP_JSON, "w"), indent=1)
    json.dump(fixer.net_shapes, open(OUT_NET_SHAPES_JSON, "w"), indent=1)
    print(f"\nfixed {fixer.fixed_vertical} vertical + {fixer.fixed_horizontal} horizontal -- wrote {OUT_GDS}")


if __name__ == "__main__":
    main()
