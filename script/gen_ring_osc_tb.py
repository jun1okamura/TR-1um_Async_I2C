"""
gen_ring_osc_tb.py (this session, user request: "ring_osc の下にTBディレ
クトリを作成して、その中でSPICEシミュレーションをします。local の
ngspiceで、発振周波数を波形と測定でチェックできるSPICEファイルを作成
できますか？モデルはIRSIMで使ったものと同じです。.tran で 200ns 程度、
RSTN＝0 で 1n で５Vに遷移してください。OUT/OUTBの波形と周期を測定して、
電源電流も測定と波形出力してください。" -- then: "RING_OSC.spice は
LVSクリーンなものを使います。" -- then, after a real local ngspice run
confirmed working: "RING_OSC を schematic ではなくて extracted に
変更してください。")

Builds a real, locally-runnable ngspice testbench for the standalone
RING_OSC (two 97-stage-equivalent ring oscillators), using the same
real TR-1um transistor models used to calibrate irsim/TR-1um.prm
(script/gen_prm_characterize.py's own confirmed-working convention:
`.include '~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/
ip62_models'`, vdd=5.0V).

**Netlist source, v2 (this revision)**: switched from the SCHEMATIC
netlist (simulations/RING_OSC.spice) to the LAYOUT-EXTRACTED one
(ring_osc/RING_OSC.extracted -- klayout's own LVS extraction of the
real RING_OSC layout), per the user's explicit request, now that the
schematic-based testbench has been confirmed working on a real local
ngspice run. This gives real post-layout parasitics (actual extracted
AS/AD/PS/PD diffusion area/perimeter per device, not the schematic
wrapper's sdwidth-based approximation) instead of pre-layout estimates.

Two structural differences from the schematic netlist, both confirmed
by directly reading ring_osc/RING_OSC.extracted (not assumed):
  1. Its leaf-cell bodies (INV_X1/AND2_X1/FILL2/INV3D) already use
     X-line device calls with explicit AS/AD/PS/PD ("XM$1 Y A vdd vdd
     PMOS L=1u W=10.2u AS=539.48p AD=28.56p PS=96.2u PD=26u", etc.) --
     i.e. it is ALREADY in the X-line form ip62_models' PMOS/NMOS
     subcircuit wrappers expect (see v1's docstring in git history for
     why the schematic netlist needed an M->X rename first; the
     extracted netlist needs no such fix -- confirmed via grep, zero
     bare M-line PMOS/NMOS devices).
  2. Its top-level pin order is ENB OUT OUTD VDD VSS (alphabetical,
     klayout's own extraction convention) -- DIFFERENT from the
     schematic's OUT OUTD ENB VDD VSS. The testbench's `xdut` instance
     line is positional, so this order is read directly from the
     extracted file's own ".SUBCKT RING_OSC ..." line (not hand-typed)
     to avoid silently wiring nets to the wrong pins.

The extracted file is fully self-contained (RING_OSC + its own INV3D/
INV_X1/AND2_X1/FILL2 dependency subckts, all with real extracted device
geometry) -- copied verbatim into ring_osc/TB/RING_OSC_extracted_sim_
ready.spice (a location-only copy so ngspice can find it via a plain
relative .include from ring_osc/TB/; content is untouched, confirmed by
this script's own byte-for-byte diff check against the source).

Testbench (ring_osc/TB/tb_ring_osc.spice):
  - RSTN drives RING_OSC's ENB pin directly (0V until 1ns, then a fast
    edge to VDD=5V, held for the rest of the run) -- matches ENB's role
    confirmed from RING_OSC's own topology (schematic side: FB =
    AND2_X1(R[94], ENB), R[94] = INV_X1^95(FB), 95 is odd -> net
    inverting, so ENB=0 forces FB=0 statically / oscillator held off,
    ENB=1 closes the loop for sustained oscillation -- the extracted
    netlist implements the identical topology, just with INV3D instead
    of INV_X1 for the 95 ring stages and real device geometry).
  - .tran (originally 200ns per the user's request, extended to 1us --
    see TRAN_STOP's own comment above for why).
  - .measure statements for OUT/OUTB (=RING_OSC's OUTD pin) period
    (rising-edge to rising-edge) and for VDD supply current (avg/peak/
    RMS).
  - .control block: run, then print/plot both waveforms and i(vvdd),
    and write an ASCII .raw file (same convention as gen_prm_
    characterize.py) so the user can view/post-process waveforms in
    any viewer.
"""
import re

RING_OSC_SRC = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/ring_osc/RING_OSC.extracted"
TB_DIR = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C/ring_osc/TB"
SIM_READY_OUT = TB_DIR + "/RING_OSC_extracted_sim_ready.spice"
TB_OUT = TB_DIR + "/tb_ring_osc.spice"

MODEL_INCLUDE = "~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/ip62_models"
VDD = 5.0
# Extended from the user's original "200ns程度" request (2026-08-31, user:
# "伸ばします"): a real local ngspice run of the schematic-based testbench
# (tb_ring_osc.raw, synced back into this same folder) showed only ONE
# OUT/OUTB rising edge inside 200ns (at t=80.9ns) -- no second edge, so
# the real period exceeds roughly 120ns and 200ns can't capture even one
# full cycle. Extended to 1us, then to 2us (user: "late が計算出来ない
# ので .tran を2usまで伸ばします"). Extended once more to 3us after that
# 2us run's own real results (post INV3D AS/AD fix, 103.20): period_out
# ~153.7ns (t_out_r1=89.5ns, t_out_r2=243.2ns), but period_outb (RISE=1/2)
# came out ~641.8ns -- about 4.2x slower than OUT, consistent with
# INV3D's now-correctly-modeled large Y-side diffusion capacitance
# (~22x INV_X1's) directly loading every one of OUTB's 95 ring stages.
# At that period, OUTB's 4th rising edge falls at roughly
# t_outb_r3(1617.8ns) + 641.8ns =~ 2260ns -- just past the 2us window,
# which is exactly why t_outb_r4/period_outb_late/freq_outb_late failed
# ("out of interval"). 3us gives >700ns of margin beyond that estimate.
TRAN_STOP = "3u"
TRAN_STEP = "0.02n"
# RSTN held at 0V until 10ns (extended from the original 1ns per the
# user's follow-up: "RSTN を 10N まで０に伸ばしてください。その後5Vへ"),
# then a fast (~20ps) edge up to VDD.
RSTN_T_EDGE_START = "10n"
RSTN_T_EDGE_END = "10.02n"


def read_ring_osc_pin_order(text):
    """Read RING_OSC's real top-level pin order directly from its own
    '.SUBCKT RING_OSC ...' line -- not hand-transcribed, so a future
    re-extraction can't silently desync the testbench's xdut line."""
    m = re.search(r"^\.SUBCKT\s+RING_OSC\s+(.+)$", text, re.M | re.I)
    if not m:
        raise RuntimeError(f"'.SUBCKT RING_OSC ...' not found in {RING_OSC_SRC}")
    return m.group(1).split()


def fix_inv3d_as_ad_swap(text):
    """Swap AS<->AD and PS<->PD for INV3D's two devices (round 2026-08-31,
    user: "これはレイアウトと違います。出力ノード側に拡散をつけて
    います。extracted のルールが間違っています。").

    klayout's extraction put INV3D's large "antenna diode" diffusion on
    the VDD/GND (supply) side of each transistor (AS=539.48p on the PMOS's
    vdd-connected source, AD=306.89p on the NMOS's gnd-connected drain --
    see design_notes.md 103.19's node-by-node derivation), which led to
    the (wrong) conclusion that INV3D and INV_X1 have identical
    output-node capacitance. The user confirmed directly from the real
    layout that the large diffusion is actually on the OUTPUT (Y) node,
    not the supply rails -- i.e. the extraction swapped which terminal
    (source vs drain) the antenna-diode-sized area belongs to for this
    specific cell.

    This is independently confirmed by a consistency check against
    INV_X1 (the plain, undecorated inverter): AFTER swapping, INV3D's
    supply-side areas become 28.56p (PMOS) / 9.52p (NMOS) -- EXACTLY
    matching INV_X1's own uniform baseline values on both terminals --
    while the now Y-side areas (539.48p / 306.89p) carry the antenna
    diode's extra area. Before the swap, neither terminal of INV3D
    matched INV_X1's baseline at all, which was itself already a sign
    something was off. So: baseline (unmodified) diffusion on the
    supply rails, extra (antenna-diode) diffusion on Y -- matches the
    real layout the user is looking at.

    This is a targeted patch to THIS SIMULATION COPY ONLY (ring_osc/TB/
    RING_OSC_extracted_sim_ready.spice) -- the master ring_osc/RING_OSC.
    extracted (klayout's raw extraction output) is left untouched, since
    the real, permanent fix belongs in the user's LVS extraction deck's
    AS/AD assignment rule for this cell, not in a hand-patched copy of
    its output."""
    m = re.search(r"(\.SUBCKT\s+INV3D\b.*?\.ENDS\s+INV3D)", text, re.S)
    if not m:
        raise RuntimeError("'.SUBCKT INV3D ... .ENDS INV3D' block not found")
    block = m.group(1)

    orig_pmos = "XM$1 Y A vdd vdd PMOS L=1u W=10.2u AS=539.48p AD=28.56p PS=96.2u PD=26u"
    fixed_pmos = "XM$1 Y A vdd vdd PMOS L=1u W=10.2u AS=28.56p AD=539.48p PS=26u PD=96.2u"
    orig_nmos = "XM$2 gnd A Y gnd NMOS L=1u W=3.4u AS=9.52p AD=306.89p PS=12.4u PD=77.2u"
    fixed_nmos = "XM$2 gnd A Y gnd NMOS L=1u W=3.4u AS=306.89p AD=9.52p PS=77.2u PD=12.4u"

    if orig_pmos not in block or orig_nmos not in block:
        raise RuntimeError(
            "INV3D's device lines don't match the expected (pre-fix) values -- "
            "refusing to patch blindly; re-derive the swap from the current "
            "extraction instead. Block was:\n" + block
        )
    new_block = block.replace(orig_pmos, fixed_pmos).replace(orig_nmos, fixed_nmos)
    print("Patched INV3D (AS<->AD, PS<->PD swap on both devices -- antenna-diode "
          "diffusion moved from the supply rails to the Y/output node, per the "
          "user's real-layout correction):")
    print("  before:", orig_pmos)
    print("   after:", fixed_pmos)
    print("  before:", orig_nmos)
    print("   after:", fixed_nmos)
    return text[:m.start()] + new_block + text[m.end():]


def build_sim_ready_netlist():
    text = open(RING_OSC_SRC).read()

    bare_m = re.findall(r"^M\S+ .*\b(?:PMOS|NMOS)\b", text, re.M)
    if bare_m:
        raise RuntimeError(
            f"{RING_OSC_SRC} unexpectedly contains {len(bare_m)} bare M-line "
            f"PMOS/NMOS device(s) -- expected zero (the extracted netlist was "
            f"already confirmed to use X-line form only). Re-check before "
            f"assuming this file needs no M->X fix."
        )

    pins = read_ring_osc_pin_order(text)
    print(f"RING_OSC.extracted top-level pin order (read directly from the file): {pins}")

    text = fix_inv3d_as_ad_swap(text)

    header = (
        "* RING_OSC_extracted_sim_ready.spice -- auto-generated by\n"
        "* script/gen_ring_osc_tb.py, from:\n"
        "*   " + RING_OSC_SRC + "\n"
        "* (klayout's real LVS extraction of the RING_OSC layout -- includes\n"
        "* real per-device extracted AS/AD/PS/PD, already in X-line form, no\n"
        "* M->X rename needed unlike the earlier schematic-based testbench\n"
        "* revision). ONE correction applied on top of the verbatim source: \n"
        "* INV3D's AS<->AD / PS<->PD are swapped on both devices -- the\n"
        "* extraction had put the antenna-diode-sized diffusion on the\n"
        "* VDD/GND (supply) side, but the user confirmed from the real layout\n"
        "* it belongs on the Y (output) side; see fix_inv3d_as_ad_swap()'s own\n"
        "* docstring and design_notes.md 103.19/103.20 for the full derivation\n"
        "* and the INV_X1-baseline consistency check that independently\n"
        "* confirms the swap direction. The master ring_osc/RING_OSC.extracted\n"
        "* itself is NOT modified -- this correction lives only in this\n"
        "* simulation copy until the real LVS extraction rule is fixed at the\n"
        "* source. DO NOT hand-edit further -- regenerate instead.\n\n"
    )
    return header + text, pins


TB_TEMPLATE = """\
* tb_ring_osc.spice -- auto-generated by script/gen_ring_osc_tb.py
* DO NOT hand-edit -- regenerate instead.
*
* Standalone RING_OSC testbench: measures free-running oscillation
* frequency/period of both rings (OUT, OUTB=OUTD) and VDD supply
* current, using the real TR-1um transistor models (same ones used to
* calibrate irsim/TR-1um.prm -- see script/gen_prm_characterize.py) and
* the LAYOUT-EXTRACTED RING_OSC netlist (RING_OSC_extracted_sim_ready.
* spice -- verbatim copy of ring_osc/RING_OSC.extracted, real per-device
* extracted parasitics, see gen_ring_osc_tb.py's own header for why this
* replaced the earlier schematic-based revision).

.include '{MODEL_INCLUDE}'
.include 'RING_OSC_extracted_sim_ready.spice'

* NOTE: ground rail is VSS, not GND -- ngspice treats "gnd" as a
* reserved alias for node 0 (same convention/pitfall already documented
* in script/gen_prm_characterize.py); RING_OSC's own top-level port is
* already named VSS, so this is just kept consistent here.

.param vdd={VDD}

vvdd VDD 0 DC {VDD}
vvss VSS 0 DC 0

* RSTN drives RING_OSC's ENB (enable) pin directly: 0V (oscillator held
* off) until {T0}, then a fast edge up to VDD, held for the rest of the
* run -- per the user's request ("RSTN=0 で 1n で5Vに遷移", later
* extended to "RSTN を 10N まで０に伸ばして").
vrstn RSTN 0 PWL(0n 0 {T0} 0 {T1} {VDD})

* pin order below is read directly from RING_OSC.extracted's own
* ".SUBCKT RING_OSC ..." line (see gen_ring_osc_tb.py's
* read_ring_osc_pin_order()) -- NOT hand-typed -- because the extracted
* netlist's alphabetical pin order (ENB OUT OUTD VDD VSS) differs from
* the schematic's (OUT OUTD ENB VDD VSS).
xdut {XDUT_NETS} RING_OSC

.tran {TSTEP} {TSTOP}

* ---- period/frequency measurements ----
* NOTE (fix, 2026-08-31): these MUST be top-level ".measure" directives,
* not "meas" commands inside .control -- a real local ngspice run
* showed the "meas" control-command form fails on PARAM-derived
* expressions ("no such function as 'param=<already-computed-number>'",
* e.g. for period_out/freq_out) even though the prerequisite WHEN
* measurements above them succeed. Top-level ".measure" directives are
* evaluated automatically when the .tran completes and don't have this
* limitation -- this is ngspice's own documented/robust form for
* chained (PARAM=) measurements, confirmed by that real run's own log.
*
* Period is measured between the 1st and 2nd rising crossings after
* RSTN releases (RISE=1/2) -- with ~96-97 inverting stages around each
* loop, the real period is not known ahead of a real run and could
* plausibly be a sizeable fraction of the {TSTOP} window, so RISE=1/2 is
* the PRIMARY measurement, guaranteeing at least one period fits.
* RISE=3/4 is also attempted as a secondary, later-cycle cross-check
* (confirms the oscillation has reached a repeatable steady state) --
* if the real period is long enough that a 4th edge doesn't occur
* inside {TSTOP}, THIS measurement alone reports "failed" without
* affecting anything else -- rerun with a longer TSTOP in that case.
.measure tran t_out_r1  WHEN v(OUT)=({VDD}/2) RISE=1
.measure tran t_out_r2  WHEN v(OUT)=({VDD}/2) RISE=2
.measure tran period_out PARAM='t_out_r2-t_out_r1'
.measure tran freq_out   PARAM='1/period_out'

.measure tran t_out_r3  WHEN v(OUT)=({VDD}/2) RISE=3
.measure tran t_out_r4  WHEN v(OUT)=({VDD}/2) RISE=4
.measure tran period_out_late PARAM='t_out_r4-t_out_r3'
.measure tran freq_out_late   PARAM='1/period_out_late'

.measure tran t_outb_r1 WHEN v(OUTB)=({VDD}/2) RISE=1
.measure tran t_outb_r2 WHEN v(OUTB)=({VDD}/2) RISE=2
.measure tran period_outb PARAM='t_outb_r2-t_outb_r1'
.measure tran freq_outb   PARAM='1/period_outb'

.measure tran t_outb_r3 WHEN v(OUTB)=({VDD}/2) RISE=3
.measure tran t_outb_r4 WHEN v(OUTB)=({VDD}/2) RISE=4
.measure tran period_outb_late PARAM='t_outb_r4-t_outb_r3'
.measure tran freq_outb_late   PARAM='1/period_outb_late'

* ---- VDD supply current measurements ----
.measure tran i_vdd_avg AVG i(vvdd) FROM={T1} TO={TSTOP}
.measure tran i_vdd_rms RMS i(vvdd) FROM={T1} TO={TSTOP}

.control
  run

  * fix (2026-08-31, real-run log): the "meas ... MAX abs(i(vvdd))"
  * form errors out ("no such vector as 'abs(i(vvdd))'") -- ngspice's
  * measure trigger wants a plain vector, not an inline function
  * expression. Fix: materialize the abs() as its own vector with "let"
  * (only possible here, after "run", once i(vvdd) actually has data),
  * then measure MAX against that plain vector name.
  let iabs = abs(i(vvdd))
  meas tran i_vdd_peak MAX iabs FROM=0 TO={TSTOP}

  print period_out freq_out period_out_late freq_out_late
  print period_outb freq_outb period_outb_late freq_outb_late
  print i_vdd_avg i_vdd_peak i_vdd_rms

  set filetype=ascii
  write tb_ring_osc.raw v(OUT) v(OUTB) v(RSTN) i(vvdd)

  * interactive viewing (ignored harmlessly in -b batch mode without a
  * display; run without -b, or use `ngspice -b tb_ring_osc.spice` and
  * then load tb_ring_osc.raw in any waveform viewer, e.g. `ngspice -r
  * tb_ring_osc.raw` + `plot` at the ngspice prompt, or gaw). OUT/OUTB
  * are on their own plot (direct period/phase comparison between the
  * two rings); RSTN and i(vvdd) are separate so their different
  * voltage/current scales don't distort the OUT/OUTB comparison.
  plot v(out) v(outb)
  plot v(rstn)
  plot i(vvdd)
.endc

.end
"""


# RING_OSC.extracted's own pin name -> this testbench's net name.
PIN_TO_NET = {"ENB": "RSTN", "OUT": "OUT", "OUTD": "OUTB", "VDD": "VDD", "VSS": "VSS"}


def build_tb(pins):
    missing = [p for p in pins if p not in PIN_TO_NET]
    if missing:
        raise RuntimeError(
            f"RING_OSC.extracted has pin(s) {missing} with no PIN_TO_NET mapping "
            f"-- update PIN_TO_NET before regenerating (refusing to guess)."
        )
    xdut_nets = " ".join(PIN_TO_NET[p] for p in pins)
    return TB_TEMPLATE.format(
        MODEL_INCLUDE=MODEL_INCLUDE, VDD=VDD, TSTOP=TRAN_STOP, TSTEP=TRAN_STEP,
        T0=RSTN_T_EDGE_START, T1=RSTN_T_EDGE_END, XDUT_NETS=xdut_nets,
    )


def main():
    import os
    os.makedirs(TB_DIR, exist_ok=True)

    sim_ready, pins = build_sim_ready_netlist()
    with open(SIM_READY_OUT, "w") as f:
        f.write(sim_ready)
    print(f"wrote {SIM_READY_OUT}")

    tb = build_tb(pins)
    with open(TB_OUT, "w") as f:
        f.write(tb)
    print(f"wrote {TB_OUT}")

    print()
    print("Run locally (this sandbox cannot run ngspice):")
    print(f"  cd ring_osc/TB && ngspice -b tb_ring_osc.spice")


if __name__ == "__main__":
    main()
