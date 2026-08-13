"""
gen_placement_2row_fm.py

Section 37 placement, FM-partitioned variant: identical TAP-first,
shared-X-grid packing to gen_placement_2row.py, but the row1/row2 net
split now comes from fm_partition.fm_bipartition() (min-cut, width-
balanced) instead of the naive cumulative-width bisection. Cut cross-row
nets: 78 -> 16 on this netlist (fm_partition.py). Relative (file) order
within each row is preserved from the original naive split's instance
order, since pack_row's TAP-gap packing is order-sensitive and there is
no natural physical-adjacency order FM produces on its own.
"""
import json
import sys
from collections import deque

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")
from lef_parser import parse_lef  # noqa: E402
from netlist_parser import parse_netlist  # noqa: E402
from fm_partition import fm_bipartition  # noqa: E402
from gen_placement_2row import _gaps_needed, pack_row  # noqa: E402

OUT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_2row_fm.json"


def main():
    macros = parse_lef()
    net = parse_netlist()
    instances = net["instances"]

    row_h = macros["INV_X1"]["size"][1]
    widths = {name: m["size"][0] for name, m in macros.items()}
    for name, m in macros.items():
        assert m["size"][1] == row_h, f"{name} height {m['size'][1]} != {row_h}"

    total_w = sum(widths[typ] for typ, _n, _p in instances)
    half = total_w / 2.0
    seed = {}
    acc = 0.0
    for typ, name, _pins in instances:
        seed[name] = 0 if acc < half else 1
        acc += widths[typ]

    part = fm_bipartition(instances, widths, seed)

    row1_cells = [(typ, name, pins) for typ, name, pins in instances if part[name] == 0]
    row2_cells = [(typ, name, pins) for typ, name, pins in instances if part[name] == 1]
    print(f"row1: {len(row1_cells)} cells, row2: {len(row2_cells)} cells "
          f"(natural width {sum(widths[t] for t,_,_ in row1_cells):.1f} / "
          f"{sum(widths[t] for t,_,_ in row2_cells):.1f} um)")

    n_gaps = max(_gaps_needed(row1_cells, widths), _gaps_needed(row2_cells, widths))
    placed1, w1 = pack_row(deque(row1_cells), widths, n_gaps)
    placed2, w2 = pack_row(deque(row2_cells), widths, n_gaps)
    assert abs(w1 - w2) < 1e-6, f"row width mismatch after TAP-aligned packing: {w1} != {w2}"

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

    def attach_pins(placed_list, cell_list):
        by_name = {name: pins for _typ, name, pins in cell_list}
        for item in placed_list:
            if item["type"] in ("TAP2", "FILL2", "FILL3"):
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

    placed1 = attach_pins(placed1, row1_cells)
    placed2 = attach_pins(placed2, row2_cells)

    result = {
        "row_height": row_h,
        "row_width": w1,
        "row1": with_pins(placed1, 1),
        "row2": with_pins(placed2, 2),
    }
    with open(OUT_JSON, "w") as f:
        json.dump(result, f, indent=1)

    n_tap1 = sum(1 for p in placed1 if p["type"] == "TAP2")
    n_tap2 = sum(1 for p in placed2 if p["type"] == "TAP2")
    n_fill1 = sum(1 for p in placed1 if p["type"] in ("FILL2", "FILL3"))
    n_fill2 = sum(1 for p in placed2 if p["type"] in ("FILL2", "FILL3"))
    print(f"wrote {OUT_JSON}")
    print(f"row width (both rows, by construction) = {w1:.1f} um")
    print(f"row1: {len(placed1)} placed ({len(row1_cells)} cells + {n_tap1} TAP2 + {n_fill1} FILL)")
    print(f"row2: {len(placed2)} placed ({len(row2_cells)} cells + {n_tap2} TAP2 + {n_fill2} FILL)")


if __name__ == "__main__":
    main()
