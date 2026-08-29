"""
test_v4_1620_route.py -- STEP1+STEP2 feasibility probe for the NEW v4 RTL
(bit_cnt + last_bit_pending, 168 instances vs v3's 186, design_notes
77.24) at row_width EXACTLY 1620.0um (N_GAPS=2, TAP_INTERVAL_TRACKS=147),
N_ROWS=4 (the original, simplest row count -- this exact config was the
first one tried and FAILED with the old 186-instance v3 netlist).
"""
import os
import subprocess
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SCRIPT = BASE + "/script"
OUT = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs"

N_ROWS = int(os.environ.get("V4_NROWS", "4"))
N_GAPS = 2
TAP_WIDTH_UM = 10.8
TRACK_UM = 5.4
TRACKS = 147
ROW_WIDTH_UM = (N_GAPS + 1) * TAP_WIDTH_UM + N_GAPS * TRACKS * TRACK_UM
assert abs(ROW_WIDTH_UM - 1620.0) < 1e-9, ROW_WIDTH_UM

_suffix = "" if N_ROWS == 4 else f"_r{N_ROWS}"
NET_FILE = OUT + f"/i2c_slave_async_net_v4_final{_suffix}.v"
PART_JSON = OUT + f"/row_assignment_v4_final{_suffix}.json"
PLACEMENT_JSON = OUT + f"/placement_nrow_fm_v4_1620_r{N_ROWS}.json"

CH_HEIGHTS_TARGET = [130.0] + [380.0] * (N_ROWS - 1) + [150.0]

PLACEMENT_GDS = OUT + f"/v4_1620_r{N_ROWS}_step1_placement.gds"
ROUTED_GDS = OUT + f"/v4_1620_r{N_ROWS}_step2_routed.gds"
PIN_MAP = OUT + f"/pin_map_v4_1620_r{N_ROWS}.json"
NET_SHAPES = OUT + f"/net_shapes_v4_1620_r{N_ROWS}.json"
FORCE_JOG_EVENTS = OUT + f"/force_jog_events_v4_1620_r{N_ROWS}.json"
CHANNEL_USAGE = OUT + f"/channel_usage_v4_1620_r{N_ROWS}.json"


def snapped_heights():
    import route_channels_nrow_fm as R
    return [R.snap_channel_height(h) for h in CH_HEIGHTS_TARGET]


def step0_gen_placement_json():
    import importlib
    import gen_placement_nrow_fm as P
    importlib.reload(P)
    P.N_ROWS = N_ROWS
    P.N_GAPS = N_GAPS
    P.TAP_INTERVAL_TRACKS = TRACKS
    P.TARGET_ROW_WIDTH_UM = ROW_WIDTH_UM
    P.main(net_file=NET_FILE, out_json=PLACEMENT_JSON, part_json=PART_JSON)
    print(f"[0/3] placement JSON -> {PLACEMENT_JSON}  (row_width={ROW_WIDTH_UM:.1f}um, N_ROWS={N_ROWS})")


def step1_placement(ch_heights):
    import gen_placement_gds_nrow_fm as G
    G.main(placement_json=PLACEMENT_JSON, out_gds=PLACEMENT_GDS, ch_heights=ch_heights)
    print(f"[1/3] placement GDS -> {PLACEMENT_GDS}")


def step2_route(ch_heights):
    import route_channels_nrow_fm as R
    R.ROW_WIDTH_UM = ROW_WIDTH_UM
    try:
        R.main(
            placement_json=PLACEMENT_JSON,
            in_gds=PLACEMENT_GDS,
            out_gds=ROUTED_GDS,
            force_jog_nets=set(),
            per_row_local_nets=set(),
            ch_heights=ch_heights,
            pin_map_path=PIN_MAP,
            net_shapes_path=NET_SHAPES,
            force_jog_events_path=FORCE_JOG_EVENTS,
            channel_usage_path=CHANNEL_USAGE,
        )
        print(f"[2/3] routed GDS -> {ROUTED_GDS}  ROUTING COMPLETED (no SystemExit)")
        return True
    except SystemExit as e:
        print(f"[2/3] ROUTING FAILED (SystemExit): {e}")
        return False


def step3_quick_check(ch_heights):
    core_h = sum(ch_heights) + N_ROWS * 64.8
    print("[3/3] quick DRC + connectivity read:")
    subprocess.run(["python3", SCRIPT + "/drc_check_nrow_fm.py", ROUTED_GDS], check=False)
    subprocess.run(["python3", SCRIPT + "/verify_connectivity_nrow_fm.py",
                     ROUTED_GDS, PIN_MAP, "0", str(core_h), str(ROW_WIDTH_UM)], check=False)


if __name__ == "__main__":
    ch_heights = snapped_heights()
    print("snapped CH_HEIGHTS:", ch_heights)
    step0_gen_placement_json()
    step1_placement(ch_heights)
    ok = step2_route(ch_heights)
    if ok:
        step3_quick_check(ch_heights)
