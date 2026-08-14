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
       b. (superseded by v3, point 4 below) Originally each row got a
          small row-specific extra leading FILL block (STAGGER_TRACKS)
          to shift its cell sequence by a row-specific offset. Kept
          only in git history now.

  4. (v3, user request) Left/right anchored packing by row parity, to
     directly attack the "case 2" short pattern (design_notes 37.4,
     38.5, 38.6) at its structural source rather than just perturbing
     it. Root-caused with the user in this session: row-only/
     adjacent-pair nets' straight M2 stubs are only ever checked for
     collision against their OWN net/channel bookkeeping, never against
     OTHER nets -- so two nets in DIFFERENT rows that happen to share
     both an absolute pin X (common on a shared 5.4um grid with ~50%
     occupancy) AND a channel (i.e. the rows are adjacent -- row r and
     row r+1 always share channel r+1) will have their stubs physically
     merge into one polygon, an invisible-to-DRC short.

     Measured before this change: adjacent (channel-sharing) row pairs
     had just as much X overlap as non-adjacent pairs (e.g. row0/row1:
     99/124 shared X, vs row0/row2 non-adjacent: 104 shared X) --
     confirming the overlap is essentially the statistical consequence
     of independent ~50%-dense placements on a shared 300-slot grid,
     not a systematic pattern the old leading-stagger could meaningfully
     touch.

     Fix: since TAP column X positions are fixed by construction
     (TAP_INTERVAL_TRACKS is constant per gap regardless of gap
     content), each of the N_GAPS gaps has a fixed [TAP_i, TAP_(i+1)]
     span for every row. Within each gap, EVEN rows (0, 2, ...) now
     pack all their real cells contiguously right after the leading TAP
     ("anchor=left"), with all of that gap's slack FILL trailing before
     the next TAP; ODD rows (1, 3, ...) do the mirror image
     ("anchor=right"): slack FILL leads, real cells trail contiguously
     up to the next TAP. Adjacent rows always differ in parity, so this
     puts their real-cell (and hence real-pin) X ranges at opposite
     ends of every gap. Per gap, if the two rows' real-cell demand in
     that gap sums to <= TAP_INTERVAL_TRACKS, their real-pin X sets
     become provably disjoint (no shared X is even possible, regardless
     of internal cell content) -- eliminating case 2 between that row
     pair for that gap entirely, not just reducing its odds. Where
     combined demand exceeds the gap budget, only the excess is forced
     to overlap in the middle.

     This replaces the old `insert_period`-based multi-point FILL
     distribution (spreading small FILL chunks every 6 real cells) with
     one contiguous FILL block per gap -- trading the "FILL corridors
     scattered throughout the row" property (§38.1) for the stronger
     interval-separation guarantee, since the router's row-crossing
     search (ROW_X_TRIES=200, i.e. +-1080um) has ample range to reach a
     large contiguous FILL block instead of a nearby small one. The
     user considered and declined per-cell X-mirroring as an additional
     measure (design_notes 38.7): plain interval separation already
     gives the provable guarantee for gaps where it applies, and
     per-cell mirroring has a documented history of causing new,
     unrelated DRC/short problems elsewhere (design_notes 22.6)
     for no proven benefit on top of that guarantee.

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


def pack_row_distributed(cell_queue, widths, n_gaps, anchor="left"):
    """Pack a row's cells into n_gaps TAP-bounded gaps of fixed size
    (TAP_INTERVAL_TRACKS each, so TAP column X positions are identical
    for every row regardless of content -- required for the TAP power
    mesh straps in route_channels_nrow_fm.py to line up across rows).

    anchor="left": within every gap, real cells are packed contiguously
    right after the leading TAP cell; all of that gap's slack FILL2/3
    trails afterward, right up to the next TAP.
    anchor="right": the mirror image -- slack FILL leads (right after
    the TAP), real cells are packed contiguously up to the next TAP.

    Calling this with anchor="left" for even rows and anchor="right"
    for odd rows (see main()) is this module's v3 case-2 mitigation --
    see the module docstring, point 4, for the full rationale."""
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

    # Consume the cell queue gap-by-gap, but in an order that fills the
    # anchor-preferred END OF THE WHOLE ROW first: left anchor consumes
    # gap 0, 1, ... (as before); right anchor consumes the LAST gap
    # first, spilling overflow backward into earlier gaps. Consuming
    # gap-by-gap in row order (0, 1, ...) regardless of anchor would
    # always saturate gap 0 first (whichever end it's anchored to
    # within that gap) and leave gap 1+ nearly empty -- wasting the
    # far gap's capacity and defeating the whole-row interval
    # separation this is meant to provide (measured: this bug made the
    # first version of this function barely move the needle -- see
    # design_notes 38.7).
    gap_order = list(range(n_gaps)) if anchor == "left" else list(reversed(range(n_gaps)))
    gap_segs = {}
    gap_slack = {}
    for gap_i in gap_order:
        gap_tracks_left = TAP_INTERVAL_TRACKS
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

        gap_segs[gap_i] = seg
        gap_slack[gap_i] = gap_tracks_left

    # Emit in true left-to-right gap order regardless of consumption
    # order above, so TAP columns stay at their fixed row-wide X
    # positions.
    for gap_i in range(n_gaps):
        place(TAP_CELL, f"TAP_{tap_idx}", widths[TAP_CELL])
        tap_idx += 1

        seg = gap_segs[gap_i]
        slack = gap_slack[gap_i]
        if anchor == "right" and slack > 0:
            place_fill_combo(slack)
        for typ, name, pins in seg:
            place(typ, name, widths[typ], pins)
        if anchor == "left" and slack > 0:
            place_fill_combo(slack)

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
        anchor = "left" if r % 2 == 0 else "right"
        placed, w = pack_row_distributed(deque(cells), widths, N_GAPS, anchor=anchor)
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
