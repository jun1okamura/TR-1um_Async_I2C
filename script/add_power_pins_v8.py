"""
add_power_pins_v8.py

User request (this session, verbatim): "TOPピンをつける時にTAPのM2のBBOX端と
M1のBBOX端にVDD/VSSのピンを追加ください" -- add VDD/GND top-level pin
markers at (a) each TAP column's M2 strap, where it reaches the BBOX
top/bottom edge (Y=0 / Y=core_h), and (b) the TAP column's M1 rail, where
it reaches the BBOX left/right edge (X=0 / X=row_width) -- mirroring the
same M2PIN/M1PIN marker convention route_top_pins_nrow_fm.py already uses
for signal ports (PIN_SIZE_UM=3.0 box + centered text label on the
M1PIN(48,1)/M2PIN(49,1)/TXM1(48,0)/TXM2(49,0) layers).

Topology (confirmed empirically via direct GDS query on
v8_step_8_squeezed_top_pins_routed.gds, not assumed from the LEF alone,
since row/column mirroring could in principle swap which physical X a
LEF-named pin lands at -- see design_notes.md for the query log):
  - 5 TAP columns (TAP2/TAP3 instances, one per placement "gap" column),
    each with TWO vertical M2 straps that already run the full core
    height (Y=0 to Y=core_h) as ONE continuous merged polygon per strap:
      - low-X sub-strap  (col_x0+1.0 .. col_x0+4.4) = GND
      - high-X sub-strap (col_x0+6.4 .. col_x0+9.8) = VDD
    (independently confirmed for all 5 columns; NOT just assumed from
    TAP2's own LEF, which only documents ONE instance's local pin
    geometry.)
  - Only the LEFTMOST column (col_x0=0.0) actually touches the BBOX left
    edge (X=0), and only the RIGHTMOST column (col_x0+10.8=row_width)
    touches the BBOX right edge (X=row_width) -- the 3 interior TAP
    columns never reach either X edge, so they get M2 (top/bottom) pins
    only, never M1 (left/right) pins.
  - Each of those two edge-touching columns has a REAL, via-connected M1
    power pad at 8 distinct Y positions (one per row-boundary channel,
    alternating GND/VDD), not one continuous rail -- each is a genuine,
    separate physical pin instance of the same net (same "several
    disjoint marker polygons, one logical pin" pattern gen_lef.py's own
    comment already documents for TAP2/TAP3's LEF pins). All 8 per edge
    get their own M1PIN marker.

Output: v8_step_9_power_pins_added.gds (from v8_step_8_squeezed_top_pins_
routed.gds, STEP6+7's final verified-clean output). Verified after the
fact via drc_check_nrow_fm.py (DRC must stay 0/0/0) and a standalone
power-net connectivity check (below) since VDD/GND aren't tracked by
pin_map/net_shapes_log (those only cover SIGNAL nets).
"""
import json
import sys

import klayout.db as db

TOP_CELL_NAME = "i2c_slave_async_nrow_fm"
M1_LAYER = (13, 0)
V1_LAYER = (19, 0)
M2_LAYER = (20, 0)
M1PIN_LAYER = (48, 1)
M2PIN_LAYER = (49, 1)
TXM1_LAYER = (48, 0)
TXM2_LAYER = (49, 0)

PIN_SIZE_UM = 3.0  # matches route_top_pins_nrow_fm.py's own signal-pin convention
TAP_CELL_NAMES = {"TAP2", "TAP3"}
PWR_CELL_NAMES = {"TAP2", "TAP3", "FILL2", "FILL3"}  # FILL2/3 abut TAP's own M1 pad,
                                                       # widening the merged pad box
                                                       # (per gen_lef.py's FILL2/3 comment)

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SCRIPT = BASE + "/script"
PLACEMENT_JSON = BASE + "/LEF/placement_nrow_fm_v8.json"
IN_GDS = BASE + "/layout/step8/v8_step_8_squeezed_top_pins_routed.gds"
OUT_GDS = BASE + "/layout/step8/v8_step_9_power_pins_added.gds"


def um(dbu, v):
    return int(round(v / dbu))


def find_tap_m2_columns(layout, top, m2_idx, dbu, core_h):
    """Recursively collect M2 shapes belonging to TAP2/TAP3 cell instances,
    cluster by X, and return a list of dicts describing each TAP column's
    two vertical straps (gnd/vdd), keyed by their confirmed global X
    range. Verifies each strap spans the FULL Y=0..core_h range (as one
    merged polygon) before trusting it -- if any column's strap is NOT
    full-height, this raises so we never silently mislabel a partial
    strap as a valid BBOX-edge pin site."""
    boxes = []
    for shp in top.begin_shapes_rec(m2_idx):
        cn = layout.cell(shp.cell_index()).name
        if cn not in TAP_CELL_NAMES:
            continue
        b = shp.shape().bbox().transformed(shp.trans())
        boxes.append((b.left * dbu, b.right * dbu))

    # cluster left/right edges into distinct sub-straps by X (TAP2's own
    # LEF: two straps per instance, 5.4um apart, so a 1um-tolerance
    # clustering on (left,right) pairs safely separates them)
    uniq = sorted(set(boxes))
    clusters = []
    for lo, hi in uniq:
        placed = False
        for c in clusters:
            if abs(c["lo"] - lo) < 0.5 and abs(c["hi"] - hi) < 0.5:
                placed = True
                break
        if not placed:
            clusters.append({"lo": lo, "hi": hi})

    m2_region_all = db.Region(top.begin_shapes_rec_touching(
        m2_idx, db.Box(-10**9, -10**9, 10**9, 10**9)))

    strap_info = []
    for c in clusters:
        probe = db.Box(um(dbu, c["lo"] + 0.05), 0, um(dbu, c["hi"] - 0.05), um(dbu, core_h))
        reg = db.Region(top.begin_shapes_rec_touching(m2_idx, probe)).merged()
        polys = list(reg.each())
        assert len(polys) == 1, (c, [p.bbox().to_s() for p in polys])
        b = polys[0].bbox()
        y0, y1 = b.bottom * dbu, b.top * dbu
        assert abs(y0 - 0.0) < 0.01 and abs(y1 - core_h) < 0.01, (c, y0, y1)
        strap_info.append({"x_lo": c["lo"], "x_hi": c["hi"], "cx": (c["lo"] + c["hi"]) / 2.0})

    strap_info.sort(key=lambda s: s["cx"])
    # group consecutive pairs into columns: (gnd=low-x, vdd=high-x)
    assert len(strap_info) % 2 == 0, len(strap_info)
    columns = []
    for i in range(0, len(strap_info), 2):
        gnd, vdd = strap_info[i], strap_info[i + 1]
        col_x0 = gnd["x_lo"] - 1.0  # TAP2 LEF: gnd strap starts at local x=1.0
        columns.append({"col_x0": col_x0, "gnd_cx": gnd["cx"], "vdd_cx": vdd["cx"]})
    columns.sort(key=lambda c: c["col_x0"])
    return columns


def find_edge_m1_pads(layout, top, m1_idx, v1_idx, dbu, col_x0, col_width, core_h):
    """For the TAP column at [col_x0, col_x0+col_width), find its real
    (via-connected) M1 power pads and, for each, the net (GND/VDD) --
    determined directly from which sub-strap the underlying via touches,
    not assumed from Y position (robust to any row-to-row mirroring)."""
    probe = db.Box(um(dbu, col_x0), 0, um(dbu, col_x0 + col_width), um(dbu, core_h))
    m1reg = db.Region(top.begin_shapes_rec_touching(m1_idx, probe)).merged()
    v1reg = db.Region(top.begin_shapes_rec_touching(v1_idx, probe)).merged()
    vias = [v.bbox() for v in v1reg.each()]

    pads = []
    for poly in m1reg.each():
        b = poly.bbox()
        width_um = (b.right - b.left) * dbu
        if width_um > col_width + 15.0:
            continue  # a signal-net M1 trunk merged in by touching -- not a power pad
        py0, py1 = b.bottom * dbu, b.top * dbu
        net = None
        for v in vias:
            vy0, vy1 = v.bottom * dbu, v.top * dbu
            if vy0 >= py0 - 0.1 and vy1 <= py1 + 0.1:
                vx_um = (v.left + v.right) / 2.0 * dbu
                local_x = vx_um - col_x0
                net = "GND" if local_x < col_width / 2.0 else "VDD"
                break
        if net is None:
            continue  # no via under this box -> not a real power pad
        pads.append({"y0": py0, "y1": py1, "cy": (py0 + py1) / 2.0, "net": net})
    pads.sort(key=lambda p: p["cy"])
    return pads


def main(in_gds=IN_GDS, out_gds=OUT_GDS, placement_json=PLACEMENT_JSON):
    placement = json.load(open(placement_json))
    row_width = placement["row_width"]

    layout = db.Layout()
    layout.read(in_gds)
    dbu = layout.dbu
    top = layout.cell(TOP_CELL_NAME)
    m1_idx = layout.layer(*M1_LAYER)
    v1_idx = layout.layer(*V1_LAYER)
    m2_idx = layout.layer(*M2_LAYER)
    m1pin_idx = layout.layer(*M1PIN_LAYER)
    m2pin_idx = layout.layer(*M2PIN_LAYER)
    txm1_idx = layout.layer(*TXM1_LAYER)
    txm2_idx = layout.layer(*TXM2_LAYER)

    core_h = top.bbox().top * dbu
    print(f"core_h={core_h:.3f}um  row_width={row_width:.3f}um")

    def add_m2_pin(cx, cy, label):
        half = PIN_SIZE_UM / 2.0
        top.shapes(m2pin_idx).insert(db.Box(um(dbu, cx - half), um(dbu, cy - half),
                                             um(dbu, cx + half), um(dbu, cy + half)))
        top.shapes(txm2_idx).insert(db.Text(label, db.Trans(um(dbu, cx), um(dbu, cy))))

    def add_m1_pin(cx, cy, label):
        half = PIN_SIZE_UM / 2.0
        top.shapes(m1pin_idx).insert(db.Box(um(dbu, cx - half), um(dbu, cy - half),
                                             um(dbu, cx + half), um(dbu, cy + half)))
        top.shapes(txm1_idx).insert(db.Text(label, db.Trans(um(dbu, cx), um(dbu, cy))))

    columns = find_tap_m2_columns(layout, top, m2_idx, dbu, core_h)
    print(f"found {len(columns)} TAP columns: "
          f"{[round(c['col_x0'], 1) for c in columns]}")

    m2_pins_added = []
    for col in columns:
        for net, cx in (("GND", col["gnd_cx"]), ("VDD", col["vdd_cx"])):
            y_bot = PIN_SIZE_UM / 2.0
            add_m2_pin(cx, y_bot, net)
            m2_pins_added.append((net, cx, y_bot))
            y_top = core_h - PIN_SIZE_UM / 2.0
            add_m2_pin(cx, y_top, net)
            m2_pins_added.append((net, cx, y_top))
    print(f"added {len(m2_pins_added)} M2 (top/bottom BBOX edge) power pins")

    col_width = 10.8  # TAP2/TAP3 cell width (design_notes 35.3/35.9)
    left_col = min(columns, key=lambda c: c["col_x0"])
    right_col = max(columns, key=lambda c: c["col_x0"])
    assert abs(left_col["col_x0"] - 0.0) < 0.01, left_col
    assert abs(right_col["col_x0"] + col_width - row_width) < 0.01, (right_col, row_width)

    m1_pins_added = []
    left_pads = find_edge_m1_pads(layout, top, m1_idx, v1_idx, dbu,
                                   left_col["col_x0"], col_width, core_h)
    for pad in left_pads:
        cx = PIN_SIZE_UM / 2.0
        add_m1_pin(cx, pad["cy"], pad["net"])
        m1_pins_added.append((pad["net"], cx, pad["cy"], "left"))

    right_pads = find_edge_m1_pads(layout, top, m1_idx, v1_idx, dbu,
                                    right_col["col_x0"], col_width, core_h)
    for pad in right_pads:
        cx = row_width - PIN_SIZE_UM / 2.0
        add_m1_pin(cx, pad["cy"], pad["net"])
        m1_pins_added.append((pad["net"], cx, pad["cy"], "right"))

    print(f"added {len(m1_pins_added)} M1 (left/right BBOX edge) power pins "
          f"({len(left_pads)} left, {len(right_pads)} right)")

    layout.write(out_gds)
    print(f"wrote {out_gds}")

    return {
        "m2_pins": m2_pins_added,
        "m1_pins": m1_pins_added,
        "columns": columns,
        "core_h": core_h,
        "row_width": row_width,
    }


if __name__ == "__main__":
    main()
