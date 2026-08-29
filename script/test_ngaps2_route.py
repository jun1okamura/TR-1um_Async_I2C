"""
test_ngaps2_route.py -- STEP2 (routing) feasibility probe, following up
test_ngaps2_placement.py's result: N_GAPS=2 / TAP_INTERVAL_TRACKS=147
(row_width=1620.0um, EXACTLY v7's own width) already PACKS successfully
(no SystemExit from gen_placement_nrow_fm's gap-capacity checks). This
script tests whether it also ROUTES -- the actual open question, since
the historical N_GAPS=4/TAP_INTERVAL_TRACKS=73 attempt (row_width=
1630.8um, design_notes 77.11) failed specifically at routing (SystemExit
"no clear X found"), not at placement.

Pipeline (bare first attempt, no FORCE_JOG_NETS/PER_ROW_LOCAL_NETS
customization -- same "try it plain first" approach 77.11/77.12 used):
  1. gen_placement_gds_nrow_fm.py -- placement GDS
  2. route_channels_nrow_fm.py    -- full router (pass0..pass3)
  3. drc_check_nrow_fm.py + verify_connectivity_nrow_fm.py -- quick signal
     (just enough to count shorts, mirroring 77.12's feasibility read --
     NOT a full ripup-reroute/squeeze/top-pin run, this is a feasibility
     check only per the user's request).
"""
import subprocess
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SCRIPT = BASE + "/script"
OUT = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs"

import os
TRACKS = int(os.environ.get("NGAPS2_TRACKS", "147"))
TAP_WIDTH_UM = 10.8
TRACK_UM = 5.4
N_GAPS = 2
ROW_WIDTH_UM = (N_GAPS + 1) * TAP_WIDTH_UM + N_GAPS * TRACKS * TRACK_UM
PLACEMENT_JSON = OUT + f"/placement_nrow_fm_v8_ngaps2_t{TRACKS}_test.json"
CH_HEIGHTS_TARGET = [130.0, 460.0, 416.0, 390.0, 150.0]  # same conservative
                                                          # first-attempt
                                                          # target 77.11 used

PLACEMENT_GDS = OUT + f"/v8_ngaps2_t{TRACKS}_step1_placement.gds"
ROUTED_GDS = OUT + f"/v8_ngaps2_t{TRACKS}_step2_routed.gds"
PIN_MAP = OUT + f"/pin_map_v8_ngaps2_t{TRACKS}.json"
NET_SHAPES = OUT + f"/net_shapes_v8_ngaps2_t{TRACKS}.json"
FORCE_JOG_EVENTS = OUT + f"/force_jog_events_v8_ngaps2_t{TRACKS}.json"
CHANNEL_USAGE = OUT + f"/channel_usage_v8_ngaps2_t{TRACKS}.json"


def snapped_heights():
    import route_channels_nrow_fm as R
    return [R.snap_channel_height(h) for h in CH_HEIGHTS_TARGET]


def step0_gen_placement_json():
    import importlib
    import gen_placement_nrow_fm as P
    importlib.reload(P)
    P.N_GAPS = N_GAPS
    P.TAP_INTERVAL_TRACKS = TRACKS
    P.TARGET_ROW_WIDTH_UM = ROW_WIDTH_UM
    NET_FILE = OUT + "/i2c_slave_async_net_v8_test.v"
    PART_JSON = OUT + "/row_assignment_v8_final_test.json"
    P.main(net_file=NET_FILE, out_json=PLACEMENT_JSON, part_json=PART_JSON)
    print(f"[0/3] placement JSON -> {PLACEMENT_JSON}  (row_width={ROW_WIDTH_UM:.1f}um)")


def step1_placement(ch_heights):
    import gen_placement_gds_nrow_fm as G
    G.main(placement_json=PLACEMENT_JSON, out_gds=PLACEMENT_GDS, ch_heights=ch_heights)
    print(f"[1/3] placement GDS -> {PLACEMENT_GDS}")


def step2_route(ch_heights):
    import route_channels_nrow_fm as R
    R.ROW_WIDTH_UM = ROW_WIDTH_UM  # module-attribute override, same
                                    # pattern design_notes 77.11 used
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
    core_h = sum(ch_heights) + 4 * 64.8  # row_h -- confirmed 64.8um throughout this design
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
