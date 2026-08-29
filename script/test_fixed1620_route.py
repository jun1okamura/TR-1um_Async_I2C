"""
test_fixed1620_route.py -- STEP1+STEP2 feasibility probe with row_width
HARD-PINNED to exactly 1620.0um (5.4*300), per user requirement: this
core cell must plug into OSS_FRAME_GIO, which fixes the row width.

1620.0um divides evenly ONLY for N_GAPS=2 (TAP_INTERVAL_TRACKS=147,
32.4+10.8*147=1620.0 exactly) -- N_GAPS=3/4 both leave a non-integer
TRACKS solution (97.33/72.5), so this uses N_GAPS=2 (v7's own TAP
column count) and varies N_ROWS to find the smallest row count that
still routes at this exact width.

For a given N_ROWS, regenerates a fresh 186-instance netlist/
row_assignment pair (insert_row_buffers.py + insert_bufth_scl_sda.py,
both N_ROWS-parametrized via module-attribute override) from the raw
src/i2c_slave_async_net.v, then runs gen_placement_nrow_fm.py (N_GAPS=2,
TAP_INTERVAL_TRACKS=147) -> gen_placement_gds_nrow_fm.py ->
route_channels_nrow_fm.py (bare first attempt, no FORCE_JOG_NETS/
PER_ROW_LOCAL_NETS).
"""
import os
import subprocess
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SCRIPT = BASE + "/script"
OUT = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs"

N_ROWS = int(os.environ.get("F1620_NROWS", "5"))
N_GAPS = 2
TAP_WIDTH_UM = 10.8
TRACK_UM = 5.4
TRACKS = 147
ROW_WIDTH_UM = (N_GAPS + 1) * TAP_WIDTH_UM + N_GAPS * TRACKS * TRACK_UM
assert abs(ROW_WIDTH_UM - 1620.0) < 1e-9, ROW_WIDTH_UM

RAW_NET = BASE + "/src/i2c_slave_async_net.v"
ROWBUF_V = OUT + f"/i2c_slave_async_net_v8_rowbuf_r{N_ROWS}.v"
ROWBUF_RA = OUT + f"/row_assignment_v8_r{N_ROWS}.json"
NET_FILE = OUT + f"/i2c_slave_async_net_v8_r{N_ROWS}.v"
PART_JSON = OUT + f"/row_assignment_v8_final_r{N_ROWS}.json"
PLACEMENT_JSON = OUT + f"/placement_nrow_fm_v8_1620_r{N_ROWS}.json"

# conservative first guess; N_ROWS+1 channels
CH_HEIGHTS_TARGET = [130.0] + [380.0] * (N_ROWS - 1) + [150.0]

PLACEMENT_GDS = OUT + f"/v8_1620_r{N_ROWS}_step1_placement.gds"
ROUTED_GDS = OUT + f"/v8_1620_r{N_ROWS}_step2_routed.gds"
PIN_MAP = OUT + f"/pin_map_v8_1620_r{N_ROWS}.json"
NET_SHAPES = OUT + f"/net_shapes_v8_1620_r{N_ROWS}.json"
FORCE_JOG_EVENTS = OUT + f"/force_jog_events_v8_1620_r{N_ROWS}.json"
CHANNEL_USAGE = OUT + f"/channel_usage_v8_1620_r{N_ROWS}.json"


def regen_netlist():
    import insert_row_buffers as RB
    import insert_bufth_scl_sda as BT
    RB.N_ROWS = N_ROWS
    BT.N_ROWS = N_ROWS
    RB.main(in_path=RAW_NET, out_path=ROWBUF_V, row_assignment_json=ROWBUF_RA,
            target_nets=["scl", "scl_n"])
    try:
        BT.main(in_path=ROWBUF_V, out_path=NET_FILE, row_assignment_json=PART_JSON,
                tmp_stage1_path=OUT + f"/.stage1_tmp_r{N_ROWS}.v")
    except PermissionError:
        pass  # tmp cleanup only, harmless in this sandbox mount
    print(f"[regen] netlist -> {NET_FILE}, row_assignment -> {PART_JSON}")


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
    regen_netlist()
    ch_heights = snapped_heights()
    print("snapped CH_HEIGHTS:", ch_heights)
    step0_gen_placement_json()
    step1_placement(ch_heights)
    ok = step2_route(ch_heights)
    if ok:
        step3_quick_check(ch_heights)
