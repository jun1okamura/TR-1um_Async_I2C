"""
gen_lef_ring_osc.py (this session, user: "RING_OSCのLEFを作ってから再度
挑戦ください。" -- after a real DRC run on the first geometric-routing
attempt found width/spacing violations, e.g. M2 wires drawn at 1.8um
where the real rule needs >=3.0um, and after ad-hoc GDS text-scanning for
RING_OSC's pin locations proved error-prone.)

Generates ring_osc/RING_OSC.lef, following this project's own established
LEF convention (script/gen_lef.py, used for LEF/TR-1um_STDCELL.lef):
prBoundary (235/0) gives SIZE, M1PIN (48/1) / M2PIN (49/1) mark real pin
ports, TXM1 (48/0) / TXM2 (49/0) text labels give pin names (matched by
point-in-polygon), OBS = all real M1/M2 metal that is NOT inside a pin
marker.

DIFFERENCES from gen_lef.py's std-cell flow (RING_OSC is a hard macro,
not a row-height CORE cell):
  - CLASS BLOCK, no SITE line (matches the project's other non-CORE
    precedent, LEF/OSS_FRAME_GIO.lef's CLASS COVER -- BLOCK is LEF's
    standard class for a placed-but-not-row-snapped macro).
  - RING_OSC's own prBoundary bbox is (0,-120.0)-(1620.0,124.8) in its
    native GDS frame -- NOT starting at Y=0 like the std cells' own PR
    boundaries do. Rather than remap to a (0,0)-origin frame (which
    would require translating every downstream consumer too), this LEF
    keeps RECT/SIZE coordinates in RING_OSC.gds's own native local frame
    verbatim, so script/route_ring_osc_*_v9.py's existing
    ORIGIN_X_UM/ORIGIN_Y_UM=(-810,-650) placement-offset convention
    applies unchanged when reading pins back out via lef_parser.py.
  - Direct inspection this session found RING_OSC.gds's own M1PIN/M2PIN
    markers ALREADY properly back VDD, VSS, OUT, OUTD, and (on M2PIN)
    ENB -- i.e. RING_OSC was built following the same marker convention
    as the std cell library, no manual coordinate entry needed for any
    of the 5 real ports. Net-name aliasing here maps lower-case
    "vdd"/"gnd" (RING_OSC's own internal per-instance labels, inherited
    from the std-cell sub-instances' own GND-named pins) to this
    macro's OWN port names "VDD"/"VSS" (RING_OSC's schematic uses "VSS",
    not "GND" -- confirmed via schematic/ring_osc_connections.json's own
    ring_osc_pins table) -- this differs from gen_lef.py's own
    NAME_ALIASES (which maps "gnd"->"GND") precisely because RING_OSC's
    top-level port is named VSS, unlike the std-cell library's own GND.

Output: ring_osc/RING_OSC.lef
"""
import klayout.db as db

GDS_PATH = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/ring_osc/RING_OSC.gds"
LEF_OUT = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/ring_osc/RING_OSC.lef"
CELL_NAME = "RING_OSC"

M1_LAYER = (13, 0)
M2_LAYER = (20, 0)
M1PIN_LAYER = (48, 1)
M2PIN_LAYER = (49, 1)
TXM1_LAYER = (48, 0)
TXM2_LAYER = (49, 0)
PR_LAYER = (235, 0)

NAME_ALIASES = {"vdd": "VDD", "gnd": "VSS"}  # see docstring -- VSS, not GND

PIN_META = {
    "OUT":  ("OUTPUT", "SIGNAL"),
    "OUTD": ("OUTPUT", "SIGNAL"),
    "ENB":  ("INPUT",  "SIGNAL"),
    "VDD":  ("INOUT",  "POWER"),
    "VSS":  ("INOUT",  "GROUND"),
}


def texts(cell, layer_idx):
    out = []
    it = cell.begin_shapes_rec(layer_idx)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            t = s.text
            out.append((t.string, t.x, t.y))
        it.next()
    return out


def direct_texts(cell, layer_idx):
    # NON-recursive: only shapes drawn directly in this cell's own body,
    # not inherited from sub-instances. RING_OSC is hierarchical (built
    # from ~400 std-cell instances), and EVERY one of those sub-instances
    # carries its own internal A/Y M1PIN/M2PIN markers + text (that's how
    # the std-cell library itself is built, per gen_lef.py). A recursive
    # scan picks up hundreds of those internal, per-instance pins along
    # with RING_OSC's own 5 real top-level ports, and there is no name-
    # based way to tell them apart (many share the generic "A"/"Y" text).
    # RING_OSC's own top-level ports, by contrast, were drawn directly in
    # its own cell body (confirmed this session: exactly 22 M1PIN + 1
    # M2PIN + 18 TXM1 + 1 TXM2 shapes at the top level, vs. hundreds more
    # only visible recursively) -- so pins/names use direct (non-
    # recursive) scanning, while OBS below still needs the full recursive
    # metal footprint.
    out = []
    for s in cell.each_shape(layer_idx):
        if s.is_text():
            t = s.text
            out.append((t.string, t.x, t.y))
    return out


def direct_region(cell, layer_idx):
    r = db.Region()
    for s in cell.each_shape(layer_idx):
        if s.is_polygon():
            r.insert(s.polygon)
        elif s.is_box():
            r.insert(s.box)
        elif s.is_path():
            r.insert(s.polygon)
    return r.merged()


def region(cell, layer_idx):
    return db.Region(cell.begin_shapes_rec(layer_idx)).merged()


def main():
    layout = db.Layout()
    layout.read(GDS_PATH)
    dbu = layout.dbu
    cell = layout.cell(CELL_NAME)
    if cell is None:
        raise SystemExit(f"cell {CELL_NAME} not found in {GDS_PATH}")

    pr = region(cell, layout.layer(*PR_LAYER))
    bbox = pr.bbox()
    x0b, y0b = bbox.left * dbu, bbox.bottom * dbu
    w = bbox.width() * dbu
    h = bbox.height() * dbu
    print(f"prBoundary bbox (um): ({x0b:.3f},{y0b:.3f}) size {w:.3f} x {h:.3f}")

    m1 = region(cell, layout.layer(*M1_LAYER))
    m2 = region(cell, layout.layer(*M2_LAYER))
    # pins: DIRECT (non-recursive) scan -- see direct_texts()'s docstring
    m1pin = direct_region(cell, layout.layer(*M1PIN_LAYER))
    m2pin = direct_region(cell, layout.layer(*M2PIN_LAYER))

    t1 = direct_texts(cell, layout.layer(*TXM1_LAYER))
    t2 = direct_texts(cell, layout.layer(*TXM2_LAYER))

    def name_for_polygon(poly, text_list):
        names = set()
        for name, x, y in text_list:
            if poly.inside(db.Point(x, y)):
                names.add(NAME_ALIASES.get(name, name))
        # a marker polygon may have BOTH a lower-case internal label and
        # an upper-case top-level one inside it (e.g. RING_OSC's VDD/VSS
        # rail markers) -- after aliasing they must agree.
        if len(names) > 1:
            raise SystemExit(f"ambiguous pin marker matched multiple names: {names}")
        return names.pop() if names else None

    pins = []  # (name, layer_name, x0,y0,x1,y1) in um, native RING_OSC frame
    for poly in m1pin.each():
        name = name_for_polygon(poly, t1)
        b = poly.bbox()
        pins.append((name, "M1", b.left * dbu, b.bottom * dbu, b.right * dbu, b.top * dbu))
    for poly in m2pin.each():
        name = name_for_polygon(poly, t2)
        b = poly.bbox()
        pins.append((name, "M2", b.left * dbu, b.bottom * dbu, b.right * dbu, b.top * dbu))

    unmatched = [p for p in pins if p[0] is None]
    if unmatched:
        raise SystemExit(f"could not match every pin marker to a text label: {unmatched}")

    missing = set(PIN_META) - {p[0] for p in pins}
    if missing:
        raise SystemExit(f"expected ports not found via marker+text scan: {missing}")

    obs_m1 = m1 - m1pin
    obs_m2 = m2 - m2pin

    indent = "    "
    lines = [f"MACRO {CELL_NAME}"]
    lines.append(f"{indent}CLASS BLOCK ;")
    lines.append(f"{indent}FOREIGN {CELL_NAME} 0.0 0.0 ;")
    lines.append(f"{indent}ORIGIN 0.0 0.0 ;")
    lines.append(f"{indent}SIZE {w:.3f} BY {h:.3f} ;")
    lines.append("")

    by_name = {}
    for name, layer_name, px0, py0, px1, py1 in pins:
        by_name.setdefault(name, []).append((layer_name, px0, py0, px1, py1))

    for name in PIN_META:  # fixed, deterministic order
        frags = by_name[name]
        direction, use = PIN_META[name]
        lines.append(f"{indent}PIN {name}")
        lines.append(f"{indent*2}DIRECTION {direction} ;")
        lines.append(f"{indent*2}USE {use} ;")
        lines.append(f"{indent*2}PORT")
        for layer_name, px0, py0, px1, py1 in frags:
            lines.append(f"{indent*3}LAYER {layer_name} ;")
            lines.append(f"{indent*4}RECT {px0:.3f} {py0:.3f} {px1:.3f} {py1:.3f} ;")
        lines.append(f"{indent*2}END")
        lines.append(f"{indent}END {name}")
        lines.append("")
        print(f"{name}: {direction}/{use}, {len(frags)} fragment(s), "
              f"e.g. {frags[0][0]} ({frags[0][1]:.1f},{frags[0][2]:.1f})-({frags[0][3]:.1f},{frags[0][4]:.1f})")

    obs_lines = []
    for layer_name, obs_region in (("M1", obs_m1), ("M2", obs_m2)):
        if obs_region.count() == 0:
            continue
        obs_lines.append(f"{indent*2}LAYER {layer_name} ;")
        for poly in obs_region.each():
            pts = [(pt.x * dbu, pt.y * dbu) for pt in poly.each_point_hull()]
            pts_str = "  ".join(f"{x:.3f} {y:.3f}" for x, y in pts)
            obs_lines.append(f"{indent*3}POLYGON {pts_str} ;")
    if obs_lines:
        lines.append(f"{indent}OBS")
        lines.extend(obs_lines)
        lines.append(f"{indent}END")
        lines.append("")

    lines.append(f"END {CELL_NAME}")

    header = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
MANUFACTURINGGRID 0.05 ;

UNITS
    DATABASE MICRONS 1000 ;
END UNITS

"""
    footer = "\nEND LIBRARY\n"
    out = header + "\n".join(lines) + footer
    with open(LEF_OUT, "w") as f:
        f.write(out)
    print(f"\nwrote {LEF_OUT}")
    print(f"OBS: M1 {obs_m1.count()} polygon(s), M2 {obs_m2.count()} polygon(s)")


if __name__ == "__main__":
    main()
