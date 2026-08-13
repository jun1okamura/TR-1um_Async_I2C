"""
gen_placement_nrow_fm.py

Section 38: N-row (target N=4, to fit the user's ~1700um row-width goal)
generalization of gen_placement_2row_fm.py. Changes from the 2-row FM
trial:

  1. Row assignment comes from fm_partition.fm_multiway_partition()
     (recursive bisection, N must be a power of 2) instead of a single
     bipartition -- see fm_partition.py's docstring for why recursive
     bisection was chosen over a direct k-way FM.
  2. FILL2/FILL3 cells are no longer packed as one block at the end of
     each TAP gap -- they're split into several smaller chunks and
     interspersed every INSERT_PERIOD real cells (`pack_row_distributed`
     replaces `pack_row`). This is a user request: spreading FILL columns
     across the row means their X positions -- guaranteed free of any
     real cell's M1/M2 (FILL2/3 carry only a VDD/GND M1 rail, section
     35.10) -- are available throughout the row as safe M2 jog corridors
     for the channel router (route_channels_nrow_fm.py), rather than
     being clumped in a few widely-spaced locations.
  3. (v2, user request) Fixed row width TARGET_ROW_WIDTH_UM = 5.4*300 =
     1620um (was a computed 1436.4um). The user observed spanning nets
     jogging outside the actual standard-cell area on the left edge --
     traced to route_channels_nrow_fm.py's find_row_clear_x search
     wandering to negative X when the area right around a pin's own
     position was too crowded (a real bug there, fixed separately), but
     also motivated by wanting more legitimate on-grid FILL real estate
     near the row edges for that search to land on instead. Two related
     changes here:
       a. FILL insertion now includes position 0 of every gap (right
          after the TAP cell, before the first real cell) -- previously
          FILL only ever appeared *between or after* groups of real
          cells, never at a gap's leading edge.
       b. Each row gets a small row-specific extra FILL block
          (STAGGER_TRACKS[r]) at position 0 of its first gap, on top of
          the normal even split. This is also aimed at the row-only/
          adjacent-pair nets' known "case 2" short pattern (design_notes
          37.4/37.6, 38.5): those nets are routed with a live-geometry-
          unchecked straight stub, so two different rows' pins that
          happen to land on the exact same absolute X (very common for,
          e.g., "the first real cell after TAP_0", since every row's
          packing starts from x=0 the same way) can short in a shared
          channel. Giving each row a different amount of leading FILL
          shifts its entire cell sequence by a row-specific offset,
          which is a placement-only, no-live-routing-changes way to
          break the systematic (not just coincidental) source of those
          collisions. This does not chase every individual coincidence
          (two rows could still align by chance elsewhere), so it is a
          mitigation, not a proof of zero case-2 shorts -- verify via
          the connectivity checker same as always.

Output schema changes from the 2-row trial's {"row1":[...],"row2":[...]}
to {"rows": [[...row0 items...], [...row1...], ...]} (a list, so N is not
hardcoded in the consumer scripts).
"""
import json
import sys
from collections import deque

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from lef_parser import parse_lef  # noqa: E402
from netlist_parser import parse_netlist  # noqa: E402
from fm_partition import fm_multiway_partition, classify_multirow_nets  # noqa: E402
from gen_placement_2row import fill_combo, TRACK_UM, TAP_CELL  # noqa: E402

N_ROWS = 4
INSERT_PERIOD = 6  # real cells between FILL insertion points, within a gap
OUT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm.json"

# Fixed row width target (user request): 5.4um x 300 grid steps.
TARGET_ROW_WIDTH_UM = 5.4 * 300  # 1620.0um
N_GAPS = 2  # 3 TAP columns; unchanged from the 1436.4um version -- more
            # room per gap only makes packing easier, never harder.
TAP_WIDTH_UM = 10.8  # TAP2's own width

# Derived so N_GAPS gaps of TAP_INTERVAL_TRACKS tracks each, plus
# (N_GAPS+1) TAP columns, land on TARGET_ROW_WIDTH_UM exactly:
# 1620 = 3*10.8 + 2*TAP_INTERVAL_TRACKS*5.4  ->  TAP_INTERVAL_TRACKS = 147
TAP_INTERVAL_TRACKS = round((TARGET_ROW_WIDTH_UM - (N_GAPS + 1) * TAP_WIDTH_UM) / N_GAPS / TRACK_UM)
assert abs(3 * TAP_WIDTH_UM + N_GAPS * TAP_INTERVAL_TRACKS * TRACK_UM - TARGET_ROW_WIDTH_UM) < 1e-6

# Row-specific extra leading FILL (see point 3b above). 2 tracks/row is
# an arbitrary but simple, distinct-per-row stagger (0, 2, 4, 6 tracks =
# 0, 10.8, 21.6, 32.4um) -- each individually a legal fill_combo (>=2).
STAGGER_TRACKS = [2 * r for r in range(N_ROWS)]


def _gaps_needed(cell_queue, widths):
    """Local copy of gen_placement_2row.py's dry-run gap counter, using
    THIS file's TAP_INTERVAL_TRACKS (that function reads its own module's
    global, so importing it directly would silently use 111 tracks, not
    130 -- see the note above)."""
    q = deque(cell_queue)
    n_gaps = 0
    while q:
        gap_tracks_left = TAP_INTERVAL_TRACKS
        seg = []
        while q:
            typ, name, pins = q[0]
            w_tracks = round(widths[typ] / TRACK_UM)
            if w_tracks > gap_tracks_left:
                break
            seg.append(q.popleft())
            gap_tracks_left -= w_tracks
        if not seg:
            raise SystemExit("a single cell is wider than one TAP gap -- widen TAP_INTERVAL_TRACKS")
        if gap_tracks_left == 1:
            typ, name, pins = seg.pop()
            q.appendleft((typ, name, pins))
        n_gaps += 1
    return n_gaps


def split_fill_evenly(total_tracks, n_parts):
    """Split total_tracks into n_parts chunks, each individually fillable
    by fill_combo (0 or >=2 -- never exactly 1), as evenly as possible.

    PRIOR VERSION (buggy): built an n_parts-way even split first (which,
    whenever total_tracks < 2*n_parts, necessarily contains several 1's),
    then tried to fix each 1 by borrowing from a neighbor in a single
    forward pass. That pass could shove a 1 rightward past an
    already-visited index and never revisit it -- confirmed in practice
    (3 tracks / 7 parts produced [0,2,0,0,0,1,0], and since fill_combo(1)
    is None, that track silently vanished, shrinking the row's total
    width by one track without any error). Fixed by only ever using as
    many active (non-zero) slots as total_tracks can support at >=2
    each -- constructed directly, so a 1 can never appear in the first
    place instead of being patched up after the fact."""
    n_parts = max(1, n_parts)
    if total_tracks <= 0:
        return [0] * n_parts
    assert total_tracks != 1, "cannot split exactly 1 track across FILL2/3 combos"
    active = max(1, min(n_parts, total_tracks // 2))
    base, rem = divmod(total_tracks, active)
    parts = [base + (1 if i < rem else 0) for i in range(active)]
    parts += [0] * (n_parts - active)
    return parts


def pack_row_distributed(cell_queue, widths, n_gaps, stagger_tracks=0, insert_period=INSERT_PERIOD):
    """Like gen_placement_2row.pack_row, but spreads each gap's FILL2/3
    padding across several insertion points (every insert_period real
    cells) instead of one block at the gap's end -- INCLUDING position 0
    (right after the TAP cell, before the first real cell), so FILL can
    land at a gap's leading edge too, not just between/after real cells.

    stagger_tracks: extra FILL tracks reserved and placed at position 0
    of the row's very first gap only, on top of the normal even split --
    a row-specific constant shift of this row's entire cell sequence
    (see this module's docstring, point 3b)."""
    placed = []
    x = 0.0
    tap_idx = 0
    fill_idx = 0

    def place(typ, name, w, pins=None):
        nonlocal x
        placed.append({"name": name, "type": typ, "x": x, "width": w, "pins": pins or {}})
        x += w

    def place_fill_combo(tracks):
        nonlocal fill_idx
        combo = fill_combo(tracks)
        assert combo is not None, (
            f"fill_combo({tracks}) is None -- an unfillable amount was requested; "
            f"this must never happen (see split_fill_evenly's docstring for the "
            f"bug this guards against)")
        for fill_typ in combo:
            place(fill_typ, f"FILL_{fill_idx}", widths[fill_typ])
            fill_idx += 1

    for gap_i in range(n_gaps):
        place(TAP_CELL, f"TAP_{tap_idx}", widths[TAP_CELL])
        tap_idx += 1

        gap_tracks_left = TAP_INTERVAL_TRACKS
        if gap_i == 0 and stagger_tracks > 0:
            place_fill_combo(stagger_tracks)
            gap_tracks_left -= stagger_tracks

        seg = []
        while cell_queue:
            typ, name, pins = cell_queue[0]
            w_tracks = round(widths[typ] / TRACK_UM)
            if w_tracks > gap_tracks_left:
                break
            seg.append(cell_queue.popleft())
            gap_tracks_left -= w_tracks

        if gap_tracks_left == 1 and seg:
            typ, name, pins = seg.pop()
            cell_queue.appendleft((typ, name, pins))
            gap_tracks_left += round(widths[typ] / TRACK_UM)

        insertion_positions = sorted(set(
            [0] + list(range(insert_period, len(seg), insert_period)) + ([len(seg)] if seg else [])
        ))
        parts = split_fill_evenly(gap_tracks_left, len(insertion_positions))

        idx_ptr = 0
        for pos, part_tracks in zip(insertion_positions, parts):
            while idx_ptr < pos:
                typ, name, pins = seg[idx_ptr]
                place(typ, name, widths[typ], pins)
                idx_ptr += 1
            if part_tracks > 0:
                place_fill_combo(part_tracks)
        while idx_ptr < len(seg):
            typ, name, pins = seg[idx_ptr]
            place(typ, name, widths[typ], pins)
            idx_ptr += 1

    place(TAP_CELL, f"TAP_{tap_idx}", widths[TAP_CELL])
    assert not cell_queue, f"{len(cell_queue)} cells left over -- n_gaps too small for this row"

    return placed, x


def main():
    macros = parse_lef()
    net = parse_netlist()
    instances = net["instances"]

    row_h = macros["INV_X1"]["size"][1]
    widths = {name: m["size"][0] for name, m in macros.items()}
    for name, m in macros.items():
        assert m["size"][1] == row_h, f"{name} height {m['size'][1]} != {row_h}"

    part = fm_multiway_partition(instances, widths, N_ROWS)
    counts = classify_multirow_nets(instances, part, N_ROWS)
    print(f"net classification: row-only={counts['row_only']}, "
          f"adjacent-pair={counts['adjacent_pair']}, spanning(3+ or non-adjacent)={counts['spanning']}")

    rows_cells = [[] for _ in range(N_ROWS)]
    for typ, name, pins in instances:
        rows_cells[part[name]].append((typ, name, pins))
    for r, cells in enumerate(rows_cells):
        w = sum(widths[t] for t, _n, _p in cells)
        print(f"row{r}: {len(cells)} cells, natural width {w:.1f} um")

    n_gaps = max(_gaps_needed(cells, widths) for cells in rows_cells)
    assert n_gaps <= N_GAPS, (
        f"row content needs {n_gaps} gaps but TAP_INTERVAL_TRACKS was derived for "
        f"N_GAPS={N_GAPS} to hit TARGET_ROW_WIDTH_UM={TARGET_ROW_WIDTH_UM} -- "
        f"either raise TARGET_ROW_WIDTH_UM or raise N_GAPS")
    placed_rows = []
    widths_out = []
    for r, cells in enumerate(rows_cells):
        placed, w = pack_row_distributed(deque(cells), widths, N_GAPS, stagger_tracks=STAGGER_TRACKS[r])
        placed_rows.append(placed)
        widths_out.append(w)
    for r, w in enumerate(widths_out):
        assert abs(w - widths_out[0]) < 1e-6, f"row{r} width {w} != row0 width {widths_out[0]}"
        assert abs(w - TARGET_ROW_WIDTH_UM) < 1e-6, f"row{r} width {w} != target {TARGET_ROW_WIDTH_UM}"
    row_width = widths_out[0]

    def attach_pins(placed_list, cell_list):
        by_name = {name: pins for _typ, name, pins in cell_list}
        for item in placed_list:
            if item["type"] in (TAP_CELL, "FILL2", "FILL3"):
                item["pins"] = {}
                continue
            pinmap = by_name[item["name"]]
            lef_pins = macros[item["type"]]["pins"]
            resolved = {}
            for pname, pinfo in lef_pins.items():
                net_name = pinmap.get(pname)
                if net_name is None:
                    continue
                resolved[pname] = {"net": net_name, "direction": pinfo["direction"],
                                    "use": pinfo["use"], "rects": pinfo["rects"]}
            item["pins"] = resolved
        return placed_list

    def with_pins(placed, row_idx):
        out = []
        for item in placed:
            pins_abs = {}
            for pname, pinfo in item["pins"].items():
                rects = [(layer, item["x"] + x0, y0, item["x"] + x1, y1)
                         for layer, x0, y0, x1, y1 in pinfo["rects"]]
                pins_abs[pname] = {"net": pinfo["net"], "direction": pinfo["direction"],
                                    "use": pinfo["use"], "rects": rects}
            out.append({"name": item["name"], "type": item["type"], "row": row_idx,
                        "x": item["x"], "width": item["width"], "height": row_h,
                        "pins": pins_abs})
        return out

    rows_out = []
    for r, (placed, cells) in enumerate(zip(placed_rows, rows_cells)):
        placed = attach_pins(placed, cells)
        rows_out.append(with_pins(placed, r))

    result = {"row_height": row_h, "row_width": row_width, "n_rows": N_ROWS, "rows": rows_out}
    with open(OUT_JSON, "w") as f:
        json.dump(result, f, indent=1)

    print(f"wrote {OUT_JSON}")
    print(f"row width (all rows, by construction) = {row_width:.1f} um")
    for r, placed in enumerate(rows_out):
        n_tap = sum(1 for p in placed if p["type"] == TAP_CELL)
        n_fill = sum(1 for p in placed if p["type"] in ("FILL2", "FILL3"))
        n_real = len(placed) - n_tap - n_fill
        print(f"row{r}: {len(placed)} placed ({n_real} cells + {n_tap} TAP2 + {n_fill} FILL, "
              f"in {n_fill} FILL instance(s) spread across the row)")


if __name__ == "__main__":
    main()
