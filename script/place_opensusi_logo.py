"""
place_opensusi_logo.py (this session, user request: "コアとRINGOSCの間の
スペースにOpenSUSIのロゴを配置します。添付のM2のDRCに違反しないように
デジタイズしたCellを作り配置してください。大きさはスペースをはみ出さない
最大サイズとしてください。")

Digitizes the attached OpenSUSI logo (uploads/OPENSUSIcolor_a.png) into a
pixel-art M2 metal-fill cell and places it centered in the empty gap
between the core (i2c_slave_async_nrow_fm) and RING_OSC, at the largest
size that (a) fits inside the real clear space and (b) is DRC-safe by
construction on M2 (Wmin=3.0um, Smin=2.0um -- same constants used
throughout this project's own M2 routing, e.g. route_ring_osc_signals_v9.
py).

**Step 1 -- real clear-space measurement (not assumed)**: directly
queried ring_osc/tr_1um_i2c_slave_async_ringosc_signals.gds via
klayout.db:
  - core (i2c_slave_async_nrow_fm) bbox: (-816.3,-140.0)-(816.3,796.1)
  - RING_OSC bbox: (-816.3,-770.0)-(816.3,-525.2)
  - merged M2 in the gap (Y -770..-140) shows the chip's VDD/VSS power
    columns at X~[-809,-800.2] and [800.2,809] running the full Y
    range, PLUS the core's own per-column power-tap risers dropping
    from the core's bottom edge down to as low as Y=-146.7 (deepest
    ones at X=[-274.4,-271.0] and [260.2,263.6] -- confirmed via a
    direct Region query, not assumed). RING_OSC's own top-edge M2/M1
    stays below Y=-553.2/-531.7 respectively -- confirmed clear, no
    intrusion into the gap from below.
  - Applying Smin=2.0um clearance from all of the above gives the real
    DRC-safe placement envelope:
      X: [-798.2, 798.2]  (clear of the left/right power columns)
      Y: [-525.2, -148.7] (clear of the deepest core power-tap riser;
                           RING_OSC's own top edge needs no extra
                           margin -- its real metal is already >25um
                           further away)
    i.e. 1596.4 x 376.5 um of real, DRC-safe clear space.

**Step 2 -- logo digitization**: the source PNG's actual ink bounding
box (non-white, alpha>10 pixels) is 2489x509 px (aspect ratio 4.89:1),
NOT the on-screen thumbnail's apparent ~2.2:1 -- measured directly via
numpy, not assumed from the displayed image. Fitting that aspect ratio
into the 1596.4x376.5um envelope is WIDTH-constrained (max continuous
scale = 1596.4/2489 = 0.6414 um/px, giving height 509*0.6414=326.5um,
comfortably under the 376.5um budget) -- so this script maximizes width
usage.

Digitized as a uniform "pixel-art" grid, one filled M2 square per ON
cell, PITCH = Wmin + Smin = 5.0um: any isolated single ON cell is then
5.0um wide (> Wmin), and any two ON regions separated by at least one
full OFF cell are at least 5.0um apart (> Smin) -- both DRC rules are
satisfied *by construction*, without depending on font/stroke details
in the source art surviving the scale-down. Diagonal-only ON-cell
touches (a checkerboard corner touch, which some DRC engines still flag
as coincident/zero-width) are patched by filling one of the two
orthogonal bridge cells before generating geometry.

At PITCH=5.0um, the widest grid that fits the 1596.4um budget is 319
columns (1595.0um); matching the source aspect ratio gives 65 rows
(325.0um) -- comfortably inside the 376.5um height budget (51.5um of
slack, expected since width is the binding constraint). This is the
maximum size this envelope and grid resolution allow.

The resulting cell is centered in both X and Y within the DRC-safe
envelope (not the raw core/RING_OSC gap) and instantiated once into the
top cell as "OPENSUSI_LOGO".
"""
import numpy as np
from PIL import Image
import klayout.db as db

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SRC_PNG = "/sessions/dreamy-ecstatic-heisenberg/mnt/uploads/OPENSUSIcolor_a.png"
IN_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_ringosc_signals.gds"
OUT_GDS = BASE + "/ring_osc/tr_1um_i2c_slave_async_ringosc_logo.gds"
TOP_CELL = "tr_1um_i2c_slave_async"
LOGO_CELL_NAME = "OPENSUSI_LOGO"

M2_LAYER = (20, 0)
M2_WMIN = 3.0
M2_SMIN = 2.0
PITCH = M2_WMIN + M2_SMIN  # 5.0um -- see module docstring

GRID_COLS = 319
GRID_ROWS = 65

# DRC-safe placement envelope (see module docstring step 1)
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

    # patch diagonal-only touches (corner-touch DRC ambiguity) by
    # filling one orthogonal bridge cell wherever a 2x2 block has ON
    # cells only on one diagonal.
    patched = grid_on.copy()
    n_patches = 0
    for j in range(GRID_ROWS - 1):
        for i in range(GRID_COLS - 1):
            a, b = grid_on[j, i], grid_on[j, i + 1]
            c, d = grid_on[j + 1, i], grid_on[j + 1, i + 1]
            if a and d and not b and not c:
                patched[j, i + 1] = True
                n_patches += 1
            elif b and c and not a and not d:
                patched[j, i] = True
                n_patches += 1
    print(f"Digitized grid: {GRID_COLS}x{GRID_ROWS}, "
          f"{grid_on.sum()} ON cells, {n_patches} diagonal-touch patches applied")
    return patched


def build_logo_cell(grid_on):
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
            x0 = i * PITCH
            x1 = x0 + PITCH
            y0 = gds_j * PITCH
            y1 = y0 + PITCH
            box = db.DBox(x0, y0, x1, y1).to_itype(ly.dbu)
            region.insert(box)

    merged = region.merged()
    cell.shapes(li_m2).insert(merged)
    return ly, cell, width_um, height_um, merged


def self_check_logo_only(ly, cell, li_m2):
    region = db.Region(cell.begin_shapes_rec(li_m2)).merged()
    w_viol = region.width_check(int(M2_WMIN / ly.dbu))
    s_viol = region.space_check(int(M2_SMIN / ly.dbu))
    print(f"Logo-only self-check: width_check(<{M2_WMIN}um) violations = {w_viol.count()}, "
          f"space_check(<{M2_SMIN}um) violations = {s_viol.count()}")
    return w_viol.count(), s_viol.count()


def main():
    grid_on = digitize_logo()
    logo_ly, logo_cell, width_um, height_um, merged_logo_region = build_logo_cell(grid_on)
    li_m2_logo = logo_ly.layer(*M2_LAYER)

    wv, sv = self_check_logo_only(logo_ly, logo_cell, li_m2_logo)
    if wv or sv:
        raise SystemExit(f"logo cell alone fails DRC self-check: width={wv}, space={sv}")

    # centered placement within the DRC-safe envelope
    place_x0 = (ENV_X0 + ENV_X1) / 2 - width_um / 2
    place_y0 = (ENV_Y0 + ENV_Y1) / 2 - height_um / 2
    print(f"\nLogo footprint: {width_um:.1f} x {height_um:.1f} um")
    print(f"Envelope: {ENV_X1-ENV_X0:.1f} x {ENV_Y1-ENV_Y0:.1f} um "
          f"(slack: {ENV_X1-ENV_X0-width_um:.1f} x {ENV_Y1-ENV_Y0-height_um:.1f} um)")
    print(f"Placement origin (bottom-left): ({place_x0:.2f}, {place_y0:.2f})")
    assert ENV_X0 <= place_x0 and place_x0 + width_um <= ENV_X1
    assert ENV_Y0 <= place_y0 and place_y0 + height_um <= ENV_Y1

    # ---- load full chip, copy logo cell in, instantiate, save ----
    ly = db.Layout()
    ly.read(IN_GDS)
    dbu = ly.dbu
    top = None
    for c in ly.top_cells():
        if c.name == TOP_CELL:
            top = c
    if top is None:
        raise SystemExit(f"top cell {TOP_CELL!r} not found in {IN_GDS}")

    new_logo_cell = ly.create_cell(LOGO_CELL_NAME)
    li_m2 = ly.layer(*M2_LAYER)
    # re-derive the merged region's polygons directly in the chip layout's
    # own dbu space (both are 0.001, so this is an exact copy, not a
    # lossy re-quantization).
    assert logo_ly.dbu == dbu
    for poly in merged_logo_region.each():
        new_logo_cell.shapes(li_m2).insert(poly)

    trans = db.Trans(db.DVector(place_x0, place_y0).to_itype(dbu))
    top.insert(db.CellInstArray(new_logo_cell.cell_index(), trans))

    ly.write(OUT_GDS)
    print(f"\nwrote {OUT_GDS}")


if __name__ == "__main__":
    main()
