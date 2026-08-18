"""run_route_v6_checkpoints.py (section 43, user request)

Re-runs route_channels_nrow_fm.main() for the v6 netlist/placement with
checkpoint_dir set, so each of the router's 5 internal drawing passes
(TAP power mesh; pass 0 per-row-local; pass 1 high-FO+row-only+
adjacent-pair; pass 2 spanning; pass 3 FORCE_JOG_NETS) is saved as its
own GDS snapshot under Layout/steps_v6/, in addition to the normal
final output. Parameters below are the exact v6 priority-net
configuration from design_notes.md 42.6/42.9 (unchanged from the
known-good run: 0 DRC, 161/162 nets verified, single shreg[1]/_071_
short remaining).
"""
import sys
sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

import route_channels_nrow_fm as r

PLACEMENT_JSON = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/LEF/placement_nrow_fm_v6.json"
IN_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_v6_placement.gds"
OUT_GDS = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/i2c_slave_async_nrow_fm_v6_routed.gds"
CHECKPOINT_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/Layout/steps_v6"

PER_ROW_LOCAL_NETS = {"RSTB1", "RSTB2", "sda_in", "scl", "addr_ok", "_071_", "_086_"}
FORCE_JOG_NETS = {
    "_009_", "scl_n_row1", "_134_[3]", "scl_row2", "bit_cnt[3]",
    "_053_", "bit_cnt[0]", "_073_", "_133_[0]", "shreg[0]", "shreg[6]",
    "shreg[1]", "rx_data_r[6]", "shreg[2]", "rx_data_r[4]", "_037_",
}
CH_HEIGHTS = [98.0, 260.0, 240.0, 224.0, 100.0]

if __name__ == "__main__":
    r.main(
        placement_json=PLACEMENT_JSON,
        in_gds=IN_GDS,
        out_gds=OUT_GDS,
        force_jog_nets=FORCE_JOG_NETS,
        per_row_local_nets=PER_ROW_LOCAL_NETS,
        ch_heights=CH_HEIGHTS,
        pin_map_path="/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/pin_map_nrow_fm_v6.json",
        net_shapes_path="/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/net_shapes_nrow_fm_v6.json",
        force_jog_events_path="/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/force_jog_events_nrow_fm_v6.json",
        channel_usage_path="/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script/channel_usage_nrow_fm_v6.json",
        checkpoint_dir=CHECKPOINT_DIR,
        checkpoint_prefix="v6_step",
    )
