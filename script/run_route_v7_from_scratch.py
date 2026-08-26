"""run_route_v7_from_scratch.py

THE definitive, from-scratch reproduction recipe for the v7 (priority-M2-
corridor placement) route. Supersedes the original v7v2/v7rr baseline --
see design_notes.md sections 47/48 for the full history. Three structural
fixes accumulated on top of the originally-recovered v7v2 recipe:

  - TRACK_PITCH 4.0 -> 5.4um (route_channels_nrow_fm.py /
    ripup_reroute_shorts.py): adjacent-track via_1 M1 pads
    (M1_PAD_SIZE=3.4) at the same X only cleared by 4.0-3.4=0.6um, well
    under the 1.4um M1 min-space DRC rule. At 5.4um pitch the same-X
    adjacent-track gap becomes 5.4-3.4=2.0um, always clearing 1.4um.
  - CH_HEIGHTS snapped via route_channels_nrow_fm.snap_channel_height():
    a channel's OWN tracks are always TRACK_PITCH apart, but the gap from
    the LAST track to the channel's outer boundary (the adjacent row's
    edge) is whatever's left over from floor-dividing -- effectively
    random, and confirmed (via GDS audit) to sometimes shrink below the
    M1 min-space margin against a row-crossing net's boundary-crossing
    via. Snapping each height to TRACK0_OFFSET + K*TRACK_PITCH exactly
    makes that gap a full TRACK_PITCH (5.4um) for every channel, not just
    the one where this was first found.
  - ripup_reroute_shorts.py's clear_excluding() margin: was margin=0.0
    (literal-overlap-only) at every call site, so two vias/runs that came
    within the DRC minimum spacing but never literally touched were
    never flagged. Now passes M1_MIN_GAP(1.4)/M2_MIN_GAP(2.0) as the
    margin, matching the real DRC rules.
  - route_channels_nrow_fm.py pass 2 (spanning nets): the row-crossing
    leg's draw_jog call now passes near_y (was omitted, routing every
    row-crossing jog through an UNBOUNDED, budget-unchecked claim_track
    fallback); the final channel-entry leg now has its own
    channel_clear/via_x_clear live check (previously unchecked entirely,
    the direct cause of most of the 7 residual v7rr shorts).

FORCE_JOG_NETS / PER_ROW_LOCAL_NETS / placement source are unchanged from
the original recovered v7v2 recipe (see git history of this file for that
derivation). CH_HEIGHTS below are the pre-snap targets (approximately
scaled from the known-good TRACK_PITCH=4.0 usage counts); snap_channel_height()
computes the actual heights used.

Pipeline:
  1. gen_placement_gds_nrow_fm.py  -- placement GDS from LEF json
  2. route_channels_nrow_fm.py     -- full router (pass0..pass3)
  3. ripup_reroute_shorts.py       -- post-process fixer
  4. drc_check_nrow_fm.py + verify_connectivity_nrow_fm.py -- verification

Expected result (design_notes.md section 48): DRC 0 violations, 5 shorts
remaining (all pairs where at least one side is an intentionally-
unmovable complex/high-fanout net -- see ripup_reroute_shorts.py's
complex-net protection rule), vs. the original v7rr's DRC 0 / 7 shorts.

Run: python3 run_route_v7_from_scratch.py
"""
import json
import subprocess
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SCRIPT = BASE + "/script"

PLACEMENT_JSON = BASE + "/LEF/placement_nrow_fm_v7_priomch.json"
CH_HEIGHTS_TARGET = [130.0, 460.0, 416.0, 390.0, 150.0]  # pre-snap targets
# v19 (design_notes, this session): tried +3 tracks' headroom per tight
# channel (1/2/3) to see if the via_x_clear/channel_clear self-collision
# fixes' cascading short-count regression (5->9) was a simple capacity
# issue -- it was NOT: usage still landed exactly at the new, larger
# budget (same "usage scales with budget" pathology documented earlier
# this session), and the exact same 9 short pairs persisted. Reverted to
# the original targets; the regression is a deeper track-allocation-
# order interdependency, not fixable by more headroom alone.

PER_ROW_LOCAL_NETS = {"RSTB1", "RSTB2", "sda_in_buf", "scl_buf", "addr_ok", "_071_", "_086_"}
FORCE_JOG_NETS = {
    "_009_", "scl_n_row1", "_134_[3]", "scl_row2", "bit_cnt[3]",
    "_053_", "bit_cnt[0]", "_073_", "_133_[0]", "shreg[0]", "shreg[6]",
    "shreg[1]", "rx_data_r[6]", "shreg[2]", "rx_data_r[4]", "_037_",
}

PLACEMENT_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7fresh_placement.gds"
ROUTED_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7fresh_routed.gds"
RR_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7freshrr_routed.gds"
PIN_MAP = SCRIPT + "/pin_map_nrow_fm_v7fresh.json"
NET_SHAPES = SCRIPT + "/net_shapes_nrow_fm_v7fresh.json"
FORCE_JOG_EVENTS = SCRIPT + "/force_jog_events_nrow_fm_v7fresh.json"
CHANNEL_USAGE = SCRIPT + "/channel_usage_nrow_fm_v7fresh.json"
RR_PIN_MAP = SCRIPT + "/pin_map_nrow_fm_v7freshrr.json"
RR_NET_SHAPES = SCRIPT + "/net_shapes_nrow_fm_v7freshrr.json"


def snapped_heights():
    import route_channels_nrow_fm as R
    return [R.snap_channel_height(h) for h in CH_HEIGHTS_TARGET]


def step1_placement(ch_heights):
    import gen_placement_gds_nrow_fm as G
    G.main(placement_json=PLACEMENT_JSON, out_gds=PLACEMENT_GDS, ch_heights=ch_heights)
    print(f"[1/4] placement GDS -> {PLACEMENT_GDS}")


def step2_route(ch_heights):
    import route_channels_nrow_fm as R
    R.main(
        placement_json=PLACEMENT_JSON,
        in_gds=PLACEMENT_GDS,
        out_gds=ROUTED_GDS,
        force_jog_nets=FORCE_JOG_NETS,
        per_row_local_nets=PER_ROW_LOCAL_NETS,
        ch_heights=ch_heights,
        pin_map_path=PIN_MAP,
        net_shapes_path=NET_SHAPES,
        force_jog_events_path=FORCE_JOG_EVENTS,
        channel_usage_path=CHANNEL_USAGE,
    )
    print(f"[2/4] routed GDS -> {ROUTED_GDS}")


def step3_ripup_reroute(ch_heights):
    subprocess.run([
        "python3", SCRIPT + "/ripup_reroute_shorts.py",
        ROUTED_GDS, PIN_MAP, NET_SHAPES, PLACEMENT_JSON,
        ",".join(str(h) for h in ch_heights),
        RR_GDS, RR_PIN_MAP, RR_NET_SHAPES,
    ], check=True, cwd=SCRIPT)
    print(f"[3/4] ripup/reroute GDS -> {RR_GDS}")


def step4_verify(ch_heights):
    print("[4/4] verification:")
    placement = json.load(open(PLACEMENT_JSON))
    row_h = placement["row_height"]
    row_w = placement["row_width"]
    core_h = sum(ch_heights) + 4 * row_h
    print("-- DRC (v7fresh, pre-ripup) --")
    subprocess.run(["python3", SCRIPT + "/drc_check_nrow_fm.py", ROUTED_GDS], check=True)
    print("-- DRC (v7freshrr, post-ripup) --")
    subprocess.run(["python3", SCRIPT + "/drc_check_nrow_fm.py", RR_GDS], check=True)
    print("-- connectivity (v7freshrr) --")
    # v19 (design_notes, this session): scan_w MUST be passed explicitly --
    # verify_connectivity_nrow_fm.py defaults scan_w to 1500um when
    # omitted, but this design's actual row_width is 1620um, so every pin
    # past X=1500 was silently excluded from the scan region and reported
    # as spurious "PIN NOT FOUND ON M1" / phantom "NET SPLIT" (found via
    # GDS audit: re-running with the correct width made all of those
    # disappear, leaving only genuine SHORT SUSPECTED entries).
    subprocess.run(["python3", SCRIPT + "/verify_connectivity_nrow_fm.py",
                     RR_GDS, RR_PIN_MAP, "0", str(core_h), str(row_w)], check=True)


if __name__ == "__main__":
    ch_heights = snapped_heights()
    print("snapped CH_HEIGHTS:", ch_heights)
    step1_placement(ch_heights)
    step2_route(ch_heights)
    step3_ripup_reroute(ch_heights)
    step4_verify(ch_heights)
