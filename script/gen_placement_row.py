"""
gen_placement_row.py

First placement pass for the new (design_notes.md section 35) cell
library: a SINGLE row of the full synthesized netlist
(src/i2c_slave_async_net.v, 152 instances), sandwiched by a channel
above and below (row-local Y: channel height CH at the bottom, then
the 64.8um cell row, then another channel of height CH at the top --
CH is filled in later once script/estimate_channel_tracks.py has a
number). Cells are placed left-to-right in netlist file order (a
locality-aware ordering is a possible later refinement; this first
pass only needs to prove the channel-cell-channel + full-height power
strap architecture is routable at all).

TAP2 power-tap cells (design_notes.md section 35.9) are inserted at
the start, the end, and at roughly TAP_INTERVAL_UM spacing in between
-- not tied to any specific instance count, just cumulative placed
width, so tap density stays roughly uniform regardless of the local
mix of narrow/wide cells.

Output: LEF/placement_row.json -- a flat list of placed instances
(name, cell type, x, y, width, height, and for real (non-TAP) netlist
instances, the absolute (x,y) of every pin, computed from the LEF pin
table). Row-local Y=0 is the bottom of the cell row; channel Y offset
is applied by the GDS-writing step, not baked in here.
"""
import json
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from lef_parser import parse_lef  # noqa: E402
from netlist_parser import parse_netlist  # noqa: E402

OUT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_row.json"

TAP_INTERVAL_UM = 600.0
TAP_CELL = "TAP2"


def main():
    macros = parse_lef()
    net = parse_netlist()
    instances = net["instances"]

    row_h = macros["INV_X1"]["size"][1]
    for name, m in macros.items():
        assert m["size"][1] == row_h, f"{name} height {m['size'][1]} != {row_h}"

    placed = []
    x = 0.0
    since_last_tap = 0.0
    tap_idx = 0

    def place_tap():
        nonlocal x, tap_idx, since_last_tap
        w, h = macros[TAP_CELL]["size"]
        placed.append({
            "name": f"TAP_{tap_idx}", "type": TAP_CELL,
            "x": x, "y": 0.0, "width": w, "height": h, "pins": {},
        })
        tap_idx += 1
        x += w
        since_last_tap = 0.0

    place_tap()  # mandatory tap at the row start

    for typ, name, pinmap in instances:
        if since_last_tap >= TAP_INTERVAL_UM:
            place_tap()

        w, h = macros[typ]["size"]
        inst_x = x
        pins_abs = {}
        for pname, pinfo in macros[typ]["pins"].items():
            net_name = pinmap.get(pname)
            if net_name is None:
                continue
            rects = [(layer, inst_x + x0, y0, inst_x + x1, y1) for layer, x0, y0, x1, y1 in pinfo["rects"]]
            pins_abs[pname] = {"net": net_name, "direction": pinfo["direction"],
                                "use": pinfo["use"], "rects": rects}

        placed.append({
            "name": name, "type": typ,
            "x": inst_x, "y": 0.0, "width": w, "height": h,
            "pins": pins_abs,
        })
        x += w
        since_last_tap += w

    place_tap()  # mandatory tap at the row end

    row_width = x
    with open(OUT_JSON, "w") as f:
        json.dump({"row_height": row_h, "row_width": row_width, "instances": placed}, f, indent=1)

    n_tap = sum(1 for p in placed if p["type"] == TAP_CELL)
    n_real = len(placed) - n_tap
    print(f"wrote {OUT_JSON}")
    print(f"row width = {row_width:.1f} um, {len(placed)} placed instances "
          f"({n_real} netlist cells + {n_tap} TAP2)")


if __name__ == "__main__":
    main()
