"""
place_opensusi_logo_dots.py

User request (this session, 2026-09-01): "OpenSUSIのロゴを修正します。
M2の3um角のドットでPNGファイルを表現したロゴを作成して配置してください。
大きさは現状のサイズで大丈夫です。"

The existing OPENSUSI_LOGO cell (created by script/place_opensusi_logo.py,
design_notes.md 103.14) renders each ON grid-cell as a FILLED 5.0x5.0um
square (PITCH = Wmin+Smin = 5.0um), so adjacent ON cells merge into solid
blocky regions -- not visually a "dot" pattern. This script re-renders
the SAME digitized grid (same source PNG, same GRID_COLS x GRID_ROWS =
319x65, same PITCH=5.0um, same placement envelope/centering -- i.e. the
same overall logo size/position, per the user's "size is fine as-is")
but draws each ON cell as an isolated 3.0x3.0um square CENTERED within
its 5.0um pitch cell (1.0um margin on all four sides), producing a true
halftone/stipple dot pattern instead of merged blocks.

DRC safety, by construction, same reasoning as before but tighter (exact
minimums, not comfortable margins):
  - Each dot is exactly 3.0um x 3.0um -- meets Wmin=3.0um exactly (a
    width_check(<3.0um) flags STRICTLY less than 3.0, so an exact-3.0um
    width is not a violation -- same "meets the minimum exactly is legal"
    convention used throughout this project's own routing, e.g. V1.S1/
    M1.S1 rule definitions).
  - Two orthogonally-adjacent ON cells (sharing a pitch-cell edge) leave
    an exact 2.0um gap between their dots ((5-3)=2.0, split evenly as
    1.0um margin per side) -- meets Smin=2.0um exactly, same "exact
    minimum is legal" reasoning.
  - Two diagonally-adjacent ON cells (checkerboard corner-touch) leave a
    corner-to-corner Euclidean gap of sqrt(2^2+2^2)=2.83um -- safely
    ABOVE Smin, so unlike the original filled-block rendering (where a
    diagonal touch is a zero-width/coincident-corner DRC ambiguity that
    needed an explicit patch), the dot rendering has no diagonal-touch
    problem at all -- no patching needed. Confirmed by re-digitizing:
    the source PNG produces exactly 1 diagonal-only touch in this grid
    (same as the original design_notes.md 103.14 finding), left
    UNpatched here (patching was a block-rendering-only workaround) and
    verified DRC-clean below anyway.
  - Verified numerically (self_check_logo_only, same width_check/
    space_check methodology as the original script) before touching the
    real chip GDS.

Replaces the existing OPENSUSI_LOGO cell's shapes IN PLACE (same cell
name, same top-level instance transform -- so the logo's placement/size
in the chip is unchanged, only its own internal M2 geometry is redrawn)
inside the CURRENT, DRC/LVS/rsim-verified
ring_osc/tr_1um_i2c_slave_async_reassigned.gds (not the older pre-
reassignment ringosc_clean.gds the original logo script targeted), so
the pad-reassignment routing work stays intact. Written to a NEW output
file (does not overwrite reassigned.gds) per this project's convention
of never blindly overwriting a verified master file.
"""
import numpy as np
from PIL import Image
import klayout.db as db

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SRC_PNG = "/sessions/dreamy-ecstatic-heisenberg/mnt/uploads/OPENSUSIcolor_a.png"
IN_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_reassigned.gds"
OUT_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_reassigned_logodots.gds"
TOP_CELL = "tr_1um_i2c_slave_async"
LOGO_CELL_NAME = "OPENSUSI_LOGO"

M2_LAYER = (20, 0)
M2_WMIN = 3.0
M2_SMIN = 2.0
PITCH = M2_WMIN + M2_SMIN  # 5.0um -- same grid pitch as the original logo
DOT = 3.0                  # user-specified dot size: 3.0 x 3.0um
MARGIN = (PITCH - DOT) / 2.0  # 1.0um -- centers the dot in its pitch cell

GRID_COLS = 319
GRID_ROWS = 65

# Same DRC-safe placement envelope as the original logo (design_notes.md
# 103.14) -- core/RING_OSC bboxes and power-column/tap-riser geometry in
# this gap are unaffected by the GIO pad reassignment (that only touched
# the GIO<->core routing at the chip perimeter), so this envelope is
# still valid; not re-measured here.
ENV_X0, ENV_X1 = -798.2, 798.2
ENV_Y0, ENV_Y1 = -525.2, -148.7


def digitize_logo():
    im = Image.open(SRC_PNG).convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3].astype(int)
    white_mask = np.all(rgb > 245, axis=2)
    ink = (~white_mask) & (alpha > 10)

    ys, xs = np.where(ink)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    margin = 10
    x0 = max(0, x0 - margin)
    y0 = max(0, y0 - margin)
    x1 = min(ink.shape[1] - 1, x1 + margin)
    y1 = min(ink.shape[0] - 1, y1 + margin)
    crop = ink[y0:y1 + 1, x0:x1 + 1]

    crop_img = Image.fromarray((crop * 255).astype(np.uint8))
    small = crop_img.resize((GRID_COLS, GRID_ROWS), Image.BOX)
    grid_on = (np.array(small).astype(float) / 255.0) >= 0.5

    n_diag = 0
    for j in range(GRID_ROWS - 1):
        for i in range(GRID_COLS - 1):
            a, b = grid_on[j, i], grid_on[j, i + 1]
            c, d = grid_on[j + 1, i], grid_on[j + 1, i + 1]
            if (a and d and not b and not c) or (b and c and not a and not d):
                n_diag += 1
    print(f"Digitized grid: {GRID_COLS}x{GRID_ROWS}, {grid_on.sum()} ON cells, "
          f"{n_diag} diagonal-only touches (left unpatched -- see module docstring)")
    return grid_on


def build_dot_cell(grid_on):
    ly = db.Layout()
    ly.dbu = 0.001
    cell = ly.create_cell(LOGO_CELL_NAME)
    li_m2 = ly.layer(*M2_LAYER)

    rows, cols = grid_on.shape
    width_um = cols * PITCH
    height_um = rows * PITCH

    region = db.Region()
    for j in range(rows):
        gds_j = rows - 1 - j  # flip vertically: image row 0 (top) -> highest Y
        for i in range(cols):
            if not grid_on[j, i]:
                continue
            x0 = i * PITCH + MARGIN
            x1 = x0 + DOT
            y0 = gds_j * PITCH + MARGIN
            y1 = y0 + DOT
            box = db.DBox(x0, y0, x1, y1).to_itype(ly.dbu)
            region.insert(box)

    # NOTE: no .merged() here -- unlike the block rendering, dots are
    # meant to stay as separate polygons (merging would be a no-op for
    # non-touching dots anyway, but keep it explicit that these are
    # deliberately isolated shapes, not a merged fill).
    cell.shapes(li_m2).insert(region)
    return ly, cell, width_um, height_um, region


def self_check_logo_only(ly, cell, li_m2):
    region = db.Region(cell.begin_shapes_rec(li_m2))
    w_viol = region.width_check(int(M2_WMIN / ly.dbu))
    s_viol = region.space_check(int(M2_SMIN / ly.dbu))
    print(f"Logo-only self-check: width_check(<{M2_WMIN}um) violations = {w_viol.count()}, "
          f"space_check(<{M2_SMIN}um) violations = {s_viol.count()}")
    return w_viol.count(), s_viol.count()


def main():
    grid_on = digitize_logo()
    logo_ly, logo_cell, width_um, height_um, dot_region = build_dot_cell(grid_on)
    li_m2_logo = logo_ly.layer(*M2_LAYER)

    wv, sv = self_check_logo_only(logo_ly, logo_cell, li_m2_logo)
    if wv or sv:
        raise SystemExit(f"dot logo cell alone fails DRC self-check: width={wv}, space={sv}")

    place_x0 = (ENV_X0 + ENV_X1) / 2 - width_um / 2
    place_y0 = (ENV_Y0 + ENV_Y1) / 2 - height_um / 2
    print(f"\nLogo footprint: {width_um:.1f} x {height_um:.1f} um (unchanged from original)")
    print(f"Placement origin (bottom-left): ({place_x0:.2f}, {place_y0:.2f})")
    assert ENV_X0 <= place_x0 and place_x0 + width_um <= ENV_X1
    assert ENV_Y0 <= place_y0 and place_y0 + height_um <= ENV_Y1

    # ---- load the CURRENT (post-pad-reassignment, DRC/LVS/rsim-clean)
    # chip GDS, and replace the existing OPENSUSI_LOGO cell's shapes IN
    # PLACE (same cell, same top-level instance transform already in the
    # file -- placement/size unchanged, only the cell's own M2 content
    # is redrawn) ----
    ly = db.Layout()
    ly.read(IN_GDS)
    dbu = ly.dbu
    assert logo_ly.dbu == dbu

    logo_cell_in_chip = ly.cell(LOGO_CELL_NAME)
    if logo_cell_in_chip is None:
        raise SystemExit(f"cell {LOGO_CELL_NAME!r} not found in {IN_GDS} -- "
                          f"expected it to already exist (carried over from "
                          f"ringosc_clean.gds via reroute_gio_pads_2026.py)")
    li_m2 = ly.layer(*M2_LAYER)

    old_region = db.Region(logo_cell_in_chip.begin_shapes_rec(li_m2))
    old_bbox = old_region.bbox()
    print(f"Existing OPENSUSI_LOGO cell: {old_region.count()} old shapes, "
          f"bbox {old_bbox.to_s()} um-equivalent (dbu={dbu})")

    logo_cell_in_chip.shapes(li_m2).clear()
    for poly in dot_region.each():
        logo_cell_in_chip.shapes(li_m2).insert(poly)

    new_region_in_chip = db.Region(logo_cell_in_chip.begin_shapes_rec(li_m2))
    print(f"New OPENSUSI_LOGO cell: {new_region_in_chip.count()} dot shapes, "
          f"bbox {new_region_in_chip.bbox().to_s()}")

    ly.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")


if __name__ == "__main__":
    main()
