"""
fix_v9_remaining_shorts.py

Targeted, verified fix for the SHORT SUSPECTED pairs remaining in the v9
route (layout/step8/v9_step_3_ripup_reroute.gds, design_notes.md section
77.29-77.40 -- bit_cnt+last_bit_pending RTL, dedup_gates.py-cleaned
netlist, N_ROWS=4, N_GAPS=3 unequal-split TAP_INTERVAL_TRACKS=
[97,97,98], row_width=1620.0um exactly) that ripup_reroute_shorts.py's
own automatic pass refuses to touch (every pair has BOTH sides
classified "complex" by classify_complex -- see that function's
docstring in ripup_reroute_shorts.py:main() for why).

v2 (this session, supersedes the original version of this script):
the original version worked around a bug in Fixer.clear_excluding's
"own"-geometry exclusion by manually injecting a synthetic real-pin-
rectangle box into net_shapes[net] before calling try_fix_horizontal,
then removing it again afterward. That bug (and a second, related one
found while chasing the SAME remaining short down to its true root
cause) is now fixed PERMANENTLY in ripup_reroute_shorts.Fixer itself
(design_notes.md 77.37-77.40: Fixer.__init__ accepts a `placement`
dict and builds self.pin_geom; clear_excluding/_endpoint_pad_region
now exclude a net's own real pin rectangles by direct geometric
proximity, not by trusting pin_map's live/mutable via-position
bookkeeping). This script therefore no longer needs any manual
net_shapes patching -- it just constructs Fixer(..., placement=...)
and calls try_fix_horizontal/try_fix_vertical directly, bypassing only
the classify_complex net-selection gate (same as the v8 precedent,
fix_v8_remaining_shorts.py).

Conflicts (2 of 3 fixed; find_conflicts() on net_shapes_nrow_fm_v9.json
for exact boxes):
  1. _051_ <-> scl_row0   (M2, same column X~1221.4-1224.8) -- NOT a
     modeling artifact. Re-verified this session with the corrected
     Fixer (both nets, both directions, still fail across the full
     +/-300-candidate search). Root cause, confirmed by direct GDS
     query: scl_row0's row0-interior pin sits in a Y-band packed with
     ~40 other cells' M1 pin/internal geometry every 5-15um across
     X=[900,1300] -- there is no clear horizontal detour path for its
     fixed-pin-end jog, in either direction, for hundreds of um. This
     is a genuine row-interior routing-density limit, not a tool
     artifact. Left as-is; see design_notes.md 77.39/77.40 for the
     full diagnostic trail (including the two now-fixed Fixer bugs
     that had to be ruled out first).
  2. scl_row0 <-> _111_   (M1, same track_y~354.1-355.9) -- FIXED
     automatically via Fixer.try_fix_horizontal("_111_", ...), no
     manual patch needed.
  3. sda_in_buf <-> _009_ (M1, same track_y~359.5-361.3) -- FIXED
     automatically via Fixer.try_fix_horizontal("sda_in_buf", ...), no
     manual patch needed.

Result: 3 shorts -> 1 short (scl_row0<->_051_, genuine, see above).
DRC 0 violations maintained throughout (independently re-verified via
drc_check_nrow_fm.py + verify_connectivity_nrow_fm.py after writing the
output GDS, not just trusted from this script's own live-geometry
checks).
"""
import json

from ripup_reroute_shorts import Fixer, find_conflicts

IN_GDS = "../layout/step8/v9_step_3_ripup_reroute.gds"
PIN_MAP_JSON = "pin_map_nrow_fm_v9.json"
NET_SHAPES_JSON = "net_shapes_nrow_fm_v9.json"
PLACEMENT_JSON = "../LEF/placement_nrow_fm_v9.json"
CH_HEIGHTS = [131.6, 380.0, 380.0, 380.0, 153.2]

OUT_GDS = "../layout/step8/v9_step_4_manual_short_fix.gds"
OUT_PIN_MAP_JSON = "pin_map_nrow_fm_v9final.json"
OUT_NET_SHAPES_JSON = "net_shapes_nrow_fm_v9final.json"

# (net, M1_trunk_box_track_y_hint) -- identifies which of the net's M1
# boxes is the one actually touching the conflict, since a net can have
# more than one M1 box at different track levels.
HORIZONTAL_FIXES = [
    ("_111_", 355.0),
    ("sda_in_buf", 360.4),
]


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

    conflicts_before = find_conflicts(net_shapes)
    print(f"{len(conflicts_before)} conflict(s) before fix:")
    for na, ia, nb, ib, lyr in conflicts_before:
        print(f"  {na} <-> {nb} on {lyr}")

    fixer = Fixer(IN_GDS, pin_map, net_shapes, ch_y0, CH_HEIGHTS, row_width, placement=placement)

    for net, track_y_hint in HORIZONTAL_FIXES:
        box = next(tuple(s[1:]) for s in fixer.net_shapes[net]
                   if s[0] == "M1" and abs((s[2] + s[4]) / 2 - track_y_hint) < 1.0)
        ok = fixer.try_fix_horizontal(net, box)
        print(f"{net} (permanent Fixer, no manual patch) fixed: {ok}")
        if not ok:
            print(f"  WARNING: {net} fix failed -- leaving as-is")

    conflicts_after = find_conflicts(fixer.net_shapes)
    print(f"\n{len(conflicts_after)} conflict(s) remain (box-level):")
    for na, ia, nb, ib, lyr in conflicts_after:
        print(f"  {na} <-> {nb} on {lyr}")

    fixer.layout.write(OUT_GDS)
    json.dump(fixer.pin_map, open(OUT_PIN_MAP_JSON, "w"), indent=1)
    json.dump(fixer.net_shapes, open(OUT_NET_SHAPES_JSON, "w"), indent=1)
    print(f"\nfixed {fixer.fixed_vertical} vertical + {fixer.fixed_horizontal} horizontal -- wrote {OUT_GDS}")


if __name__ == "__main__":
    main()
