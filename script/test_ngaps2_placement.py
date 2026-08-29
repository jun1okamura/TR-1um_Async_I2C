"""
test_ngaps2_placement.py -- feasibility probe (STEP1/placement only).

User request: try N_GAPS=2 (v7's 3-TAP-column power mesh, reverting from
V8's current N_GAPS=4/5 columns) to see if V8's row width can shrink back
toward v7's ~1620-1632.6um. Reuses the SAME row assignment V8's accepted
baseline used (LEF/row_assignment_v8_final.json, 186 instances, 110/112/
94/106 per row) so this isolates the effect of N_GAPS/TAP_INTERVAL_TRACKS
alone -- no re-partitioning.

Iterates TAP_INTERVAL_TRACKS upward from v7's own value (147) until
gen_placement_nrow_fm.main() succeeds (no SystemExit from _gaps_needed's
"row content needs more gaps" assertion or pack_row_distributed's "no
room" checks), to find the SMALLEST width that even PACKS (before
attempting the much more expensive routing step).
"""
import importlib
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
OUT = "/sessions/dreamy-ecstatic-heisenberg/mnt/outputs"
# NOTE: the canonical src/i2c_slave_async_net_v8.v on disk was found to be
# the RAW 174-cell pre-row-buffer/pre-BUFTH netlist (not the documented
# 186-cell final one design_notes 77.10 describes under that same
# filename) -- LEF/row_assignment_v8_final.json's 186 instance names don't
# match it (missing _400_.._405_ etc). Freshly regenerated a consistent
# (net_file, row_assignment) pair via insert_row_buffers.py +
# insert_bufth_scl_sda.py from src/i2c_slave_async_net.v (the true raw
# source), written to OUT/ -- this doesn't touch/overwrite any canonical
# file, just gives this experiment a self-consistent 186-instance pair.
NET_FILE = OUT + "/i2c_slave_async_net_v8_test.v"
PART_JSON = OUT + "/row_assignment_v8_final_test.json"
OUT_JSON = OUT + "/placement_nrow_fm_v8_ngaps2_test.json"


def try_tracks(tracks):
    import gen_placement_nrow_fm as P
    importlib.reload(P)
    P.N_GAPS = 2
    P.TAP_INTERVAL_TRACKS = tracks
    P.TARGET_ROW_WIDTH_UM = (P.N_GAPS + 1) * P.TAP_WIDTH_UM + P.N_GAPS * tracks * P.TRACK_UM
    try:
        P.main(net_file=NET_FILE, out_json=OUT_JSON, part_json=PART_JSON)
        return True, P.TARGET_ROW_WIDTH_UM
    except SystemExit as e:
        return False, str(e)


if __name__ == "__main__":
    # v7 itself used 147 tracks (N_GAPS=2) for 154 instances; V8 has 186
    # (+20.8%) via the SAME fixed row assignment as the accepted 100-track/
    # N_GAPS=4 baseline -- start at v7's own value and step up.
    for tracks in [147, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280]:
        ok, info = try_tracks(tracks)
        status = "OK" if ok else "FAIL"
        print(f"TAP_INTERVAL_TRACKS={tracks:4d}  {status}  {info}")
        if ok:
            print(f"\n=> smallest packable width so far: TAP_INTERVAL_TRACKS={tracks}, "
                  f"row_width={info:.1f}um")
            break
