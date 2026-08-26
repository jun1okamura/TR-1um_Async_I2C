"""run_route_v7_step7_squeeze.py

STEP7 CORRECTED (user request, this session -- original attempt in
run_route_v7_step7_compress.py was WRONG, per user's own visual review
of the resulting GDS: large fully-empty M1 bands remained clearly
visible inside channels 1/2/3, contradicting that script's claim of
"used == budget, zero slack" for those channels).

Root cause of the original mistake: `run_route_v7_step7_compress.py`
measured "used_tracks" from route_channels_nrow_fm.py's
channel_usage_path, which reports `next_free_idx` -- a MONOTONIC
HIGH-WATER-MARK counter. `claim_track()`'s `while collides(...)` loop
permanently advances this counter past every track index it TRIES and
REJECTS during a collision-avoidance search, even though a rejected
index is never actually assigned any geometry (`channel_used_x` is
only populated for the index that finally succeeds). So a channel with
heavy jog activity (many spanning-net pins needing a fresh track late
in the pipeline, near-collision-checked against many already-claimed
via Xs) can rack up a `next_free_idx` far higher than the number of
track indices that ever received real metal -- exactly the gap between
"used_tracks" (85/77/72 for channels 1/2/3) and the TRUE geometric
picture, confirmed by direct GDS query on i2c_slave_async_nrow_fm_v7rr_
routed.gds:
  channel1: 85 budget, only 44 indices have ANY real M1 -- one 40-track
            contiguous EMPTY gap (idx 42-81)
  channel2: 77 budget, only 37 real -- one 40-track gap (idx 29-68)
  channel3: 72 budget, only 30 real -- one 42-track gap (idx 29-70)
This is precisely the failure mode route_channels_nrow_fm.py's own
checkpoint() function (v3, design_notes section 43.5) already
identified and fixed for the (258,N) review-layer visualization
years ago ("v2 marked a track free purely from channel_used_x
BOOKKEEPING... over-counts used") -- compress_channels_nrow_fm.py
(section 41) never got the same fix, and this session's STEP7 v1
inherited that same stale metric by reusing it.

Correct fix: this design needs squeeze_channels_nrow_fm.py (section
44) -- a POST-ROUTE geometric compaction that removes each genuinely-
empty INTERIOR track and shifts everything above it down, rather than
compress_channels_nrow_fm.py's simpler "truncate the channel height"
approach (which can only reclaim space ABOVE the highest-used track,
useless here since channels 1-3 each have one straggler jog claimed
near the very TOP of their budget, e.g. channel1's highest real-M1
index is 84 out of 85 -- truncation finds ~0 slack even though 40 of
the 85 tracks below it are completely empty).

squeeze_channels_nrow_fm.py needs a compaction_info JSON (guard_idx +
per-index via-X registry, `used_x`) to safely decide which indices are
removable and re-validate MIN_VIA_X_SEP at every newly-created
adjacency. route_channels_nrow_fm.py's own compaction_info_path dumps
exactly this -- but ONLY as of the state right after its own pass 0-3,
BEFORE ripup_reroute_shorts.py's post-process fixes run. Since ripup/
reroute can and does relocate a handful of nets (fixing the 7 residual
shorts), any track it newly touches wouldn't be reflected in that
snapshot. Fix: regenerate `used_x` from the FINAL (post-ripup) GDS's
REAL drawn M1 geometry (same per-track merged-region probe checkpoint()
already uses for (258,N)) instead of trusting the pre-ripup bookkeeping
registry -- `guard_idx` alone is still safe to reuse as-is from the
pre-ripup dump, since ripup_reroute_shorts.py's complex-net protection
rule never touches per-row-local trunks (the only thing guard_idx
protects).

Pipeline:
  1. route_channels_nrow_fm.py at the ORIGINAL (uncompressed) v7rr
     CH_HEIGHTS, with compaction_info_path set -- same recipe as
     run_route_v7_from_scratch.py.
  2. ripup_reroute_shorts.py -- same as always.
  3. DRC + connectivity sanity check (must reproduce 0 shorts, DRC
     0/0/0, exactly like the established v7rr recipe).
  4. Rebuild `used_x` per channel/index from REAL M1 geometry on the
     post-ripup GDS (not from step 1's bookkeeping).
  5. squeeze_channels_nrow_fm.py using the corrected compaction_info.
  6. DRC + connectivity on the squeezed GDS (new, smaller core_h).
  7. Recompute the new per-channel heights from the same y_map the
     squeeze used (needed so route_top_pins_nrow_fm.py can correctly
     reconstruct row Y positions), then re-run STEP6's top-pin-to-BBOX
     wiring against the squeezed GDS.
  8. DRC + connectivity on the final squeezed + top-pin-routed GDS.
"""
import json
import subprocess
import sys

sys.path.insert(0, "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/script")

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
SCRIPT = BASE + "/script"

PLACEMENT_JSON = BASE + "/LEF/placement_nrow_fm_v7_priomch.json"
PER_ROW_LOCAL_NETS = {"RSTB1", "RSTB2", "sda_in_buf", "scl_buf", "addr_ok", "_071_", "_086_"}
FORCE_JOG_NETS = {
    "_009_", "scl_n_row1", "_134_[3]", "scl_row2", "bit_cnt[3]",
    "_053_", "bit_cnt[0]", "_073_", "_133_[0]", "shreg[0]", "shreg[6]",
    "shreg[1]", "rx_data_r[6]", "shreg[2]", "rx_data_r[4]", "_037_",
}
CH_HEIGHTS = [131.60000000000002, 461.00000000000006, 417.8, 390.8, 153.20000000000002]

PLACEMENT_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7sq_placement.gds"
ROUTED_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7sq_routed.gds"
RR_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7sqrr_routed.gds"
PIN_MAP = SCRIPT + "/pin_map_nrow_fm_v7sq.json"
NET_SHAPES = SCRIPT + "/net_shapes_nrow_fm_v7sq.json"
FORCE_JOG_EVENTS = SCRIPT + "/force_jog_events_nrow_fm_v7sq.json"
CHANNEL_USAGE = SCRIPT + "/channel_usage_nrow_fm_v7sq.json"
RR_PIN_MAP = SCRIPT + "/pin_map_nrow_fm_v7sqrr.json"
RR_NET_SHAPES = SCRIPT + "/net_shapes_nrow_fm_v7sqrr.json"
PRE_COMPACTION_INFO = SCRIPT + "/compaction_info_nrow_fm_v7sq_pre.json"
POST_COMPACTION_INFO = SCRIPT + "/compaction_info_nrow_fm_v7sq_post.json"

SQUEEZED_GDS = BASE + "/Layout/i2c_slave_async_nrow_fm_v7sq_squeezed.gds"
SQUEEZED_PIN_MAP = SCRIPT + "/pin_map_nrow_fm_v7sq_squeezed.json"
SQUEEZED_NET_SHAPES = SCRIPT + "/net_shapes_nrow_fm_v7sq_squeezed.json"

TOP_PINS_OUT_GDS = BASE + "/Layout/steps_v7_v2/v7v2_step_7_squeezed_top_pins_routed.gds"

TOP_CELL_NAME = "i2c_slave_async_nrow_fm"
M1_LAYER = (13, 0)
M1_TRUNK_WIDTH = 1.8


def step1_placement(ch_heights):
    import gen_placement_gds_nrow_fm as G
    G.main(placement_json=PLACEMENT_JSON, out_gds=PLACEMENT_GDS, ch_heights=ch_heights)
    print(f"[1/9] placement GDS -> {PLACEMENT_GDS}")


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
        compaction_info_path=PRE_COMPACTION_INFO,
    )
    print(f"[2/9] routed GDS -> {ROUTED_GDS}")


def step3_ripup_reroute(ch_heights):
    subprocess.run([
        "python3", SCRIPT + "/ripup_reroute_shorts.py",
        ROUTED_GDS, PIN_MAP, NET_SHAPES, PLACEMENT_JSON,
        ",".join(str(h) for h in ch_heights),
        RR_GDS, RR_PIN_MAP, RR_NET_SHAPES,
    ], check=True, cwd=SCRIPT)
    print(f"[3/9] ripup/reroute GDS -> {RR_GDS}")


def verify(gds, pin_map, core_h, row_w, label):
    print(f"-- DRC ({label}) --")
    subprocess.run(["python3", SCRIPT + "/drc_check_nrow_fm.py", gds], check=True)
    print(f"-- connectivity ({label}) --")
    subprocess.run(["python3", SCRIPT + "/verify_connectivity_nrow_fm.py",
                     gds, pin_map, "0", str(core_h), str(row_w)], check=True)


def rebuild_used_x_from_geometry(gds, pre_info):
    """v41 (this session, STEP7 fix): regenerate compaction_info's
    per-channel `used_x` from the FINAL (post-ripup) GDS's real drawn M1
    geometry, instead of trusting route_channels_nrow_fm.py's own
    pre-ripup channel_used_x bookkeeping dump -- see this file's module
    docstring for why (ripup_reroute_shorts.py can move nets after that
    dump was taken)."""
    import klayout.db as db
    layout = db.Layout()
    layout.read(gds)
    dbu = layout.dbu
    top = None
    for c in layout.each_cell():
        if c.name == TOP_CELL_NAME:
            top = c
            break

    def um(v):
        return int(round(v / dbu))

    m1_idx = layout.layer(*M1_LAYER)
    half_w = M1_TRUNK_WIDTH / 2.0
    row_width = pre_info["row_width_um"]
    track0_offset, track_pitch = pre_info["track0_offset"], pre_info["track_pitch"]

    new_channels = []
    for ch in pre_info["channels"]:
        c = ch["channel"]
        budget = ch["budget"]
        band_lo = pre_info["ch_y0"][c]
        used_x = {}
        for idx in range(budget):
            track_y = band_lo + track0_offset + idx * track_pitch
            band = db.Box(um(0.0), um(track_y - half_w), um(row_width), um(track_y + half_w))
            hits = db.Region(top.begin_shapes_rec_touching(m1_idx, band)).merged()
            if hits.is_empty():
                continue
            xs = []
            for poly in hits.each():
                bbox = poly.bbox()
                cx = (bbox.left + bbox.right) / 2.0 * dbu
                xs.append(cx)
            used_x[str(idx)] = xs
        new_channels.append({"channel": c, "budget": budget,
                              "guard_idx": ch["guard_idx"], "used_x": used_x})
        n_real = len(used_x)
        n_bookkeeping = len(ch["used_x"])
        print(f"  channel{c}: real-geometry used indices = {n_real} "
              f"(pre-ripup bookkeeping said {n_bookkeeping})")

    post_info = dict(pre_info)
    post_info["channels"] = new_channels
    return post_info


def step4_rebuild_compaction_info():
    pre_info = json.load(open(PRE_COMPACTION_INFO))
    post_info = rebuild_used_x_from_geometry(RR_GDS, pre_info)
    with open(POST_COMPACTION_INFO, "w") as f:
        json.dump(post_info, f, indent=1)
    print(f"[4/9] wrote {POST_COMPACTION_INFO}")
    return post_info


def step5_squeeze():
    import squeeze_channels_nrow_fm as SQ
    new_core_h = SQ.main(RR_GDS, POST_COMPACTION_INFO, SQUEEZED_GDS,
                          pin_map_in=RR_PIN_MAP, pin_map_out=SQUEEZED_PIN_MAP,
                          net_shapes_in=RR_NET_SHAPES, net_shapes_out=SQUEEZED_NET_SHAPES)
    print(f"[5/9] squeezed GDS -> {SQUEEZED_GDS} (new core_h={new_core_h:.1f}um)")
    return new_core_h


def compute_new_ch_heights(post_info):
    import squeeze_channels_nrow_fm as SQ
    ch_y0 = post_info["ch_y0"]
    ch_heights = post_info["ch_heights"]
    row_y0 = post_info["row_y0"]
    row_h = post_info["row_h"]
    n_rows = post_info["n_rows"]
    n_ch = post_info["n_ch"]
    track_pitch = post_info["track_pitch"]
    track0_offset = post_info["track0_offset"]
    min_via_x_sep = post_info["min_via_x_sep"]

    kept_by_channel = {}
    for ch in post_info["channels"]:
        c = ch["channel"]
        kept_by_channel[c] = SQ.compute_kept_indices(
            ch["budget"], ch["guard_idx"], ch["used_x"], min_via_x_sep)

    y_map, new_core_h = SQ.build_y_map(ch_y0, ch_heights, row_y0, row_h, n_rows, n_ch,
                                        track_pitch, track0_offset, kept_by_channel)
    # v42 (this session, STEP7 fix): build_y_map's breakpoint list is only
    # correctly ordered/queryable at points a PRECEDING row/channel's own
    # identity-extension breakpoint already closes off -- true for every
    # internal channel boundary (each one coincides with some row's own
    # row_lo/row_hi, added to the breakpoints list before that channel's
    # own tracks are processed, so the scan finds the correct pair first).
    # The one exception is the very first point, old-Y=0.0 (the design's
    # absolute bottom edge): nothing precedes it, so if channel0's own
    # first kept track's slice dips below Y=0.0 (happens whenever
    # TRACK0_OFFSET < TRACK_PITCH/2, true here: 2.0 < 2.7), the scan falls
    # through to the SAME corrupted, non-monotonic breakpoint pair that
    # also causes this dip, and returns a wrong (too-large) value --
    # confirmed via direct GDS query: y_map(0.0) returned 0.7 here, but
    # the REAL squeezed geometry's row0 instances start at exactly 86.4
    # (matching the trustworthy y_map(131.6) call), i.e. the TRUE
    # channel0 height is 86.4, not y_map(131.6)-y_map(0.0)=85.7. Since
    # Y=0.0 is by definition the design's true bottom edge regardless of
    # what y_map(0.0) miscomputes, substitute 0.0 directly instead of
    # calling y_map for channel0's lower bound specifically.
    new_ch_heights = []
    for c in range(n_ch):
        lo = 0.0 if c == 0 else y_map(ch_y0[c])
        new_ch_heights.append(y_map(ch_y0[c] + ch_heights[c]) - lo)
    return new_ch_heights, new_core_h


def step7_top_pins(new_ch_heights):
    import route_top_pins_nrow_fm as T
    T.main(placement_json=PLACEMENT_JSON, in_gds=SQUEEZED_GDS, out_gds=TOP_PINS_OUT_GDS,
           ch_heights=new_ch_heights, net_shapes_json=SQUEEZED_NET_SHAPES)
    print(f"[7/9] top-pin-routed GDS -> {TOP_PINS_OUT_GDS}")


if __name__ == "__main__":
    placement = json.load(open(PLACEMENT_JSON))
    row_h = placement["row_height"]
    row_w = placement["row_width"]
    orig_core_h = sum(CH_HEIGHTS) + 4 * row_h

    print("=== [1-3/9] base v7 recipe (original CH_HEIGHTS, with compaction_info) ===")
    step1_placement(CH_HEIGHTS)
    step2_route(CH_HEIGHTS)
    step3_ripup_reroute(CH_HEIGHTS)

    print("\n=== sanity check: base recipe still 0-short / DRC-clean ===")
    verify(RR_GDS, RR_PIN_MAP, orig_core_h, row_w, "v7sqrr (pre-squeeze)")

    print("\n=== [4/9] rebuild used_x from real post-ripup geometry ===")
    post_info = step4_rebuild_compaction_info()

    print("\n=== [5/9] squeeze away genuinely-empty interior tracks ===")
    new_core_h = step5_squeeze()

    print("\n=== [6/9] verify squeezed result ===")
    verify(SQUEEZED_GDS, SQUEEZED_PIN_MAP, new_core_h, row_w, "v7sq squeezed")

    print("\n=== recompute new per-channel heights for STEP6 top-pin re-routing ===")
    new_ch_heights, new_core_h2 = compute_new_ch_heights(post_info)
    print(f"new CH_HEIGHTS: {new_ch_heights}  (core_h={new_core_h2:.1f}um)")

    print("\n=== [7/9] re-route top pins to the new (squeezed) BBOX ===")
    step7_top_pins(new_ch_heights)

    print("\n=== [8-9/9] verify top-pin-routed squeezed result ===")
    verify(TOP_PINS_OUT_GDS, SQUEEZED_PIN_MAP, new_core_h2, row_w, "v7sq step7 top-pins")

    print(f"\ncore_h: {orig_core_h:.1f} -> {new_core_h2:.1f} um "
          f"(-{orig_core_h - new_core_h2:.1f} um, "
          f"-{100*(orig_core_h-new_core_h2)/orig_core_h:.1f}%)")
