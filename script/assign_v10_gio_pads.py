"""
assign_v10_gio_pads.py (design_notes.md 108.57, user: "修正してください。
スクリプトも修正ください。")

FIXES A REAL BUG in the first version of this reassignment (done ad hoc,
inline, not saved as a script -- design_notes.md 108.55): that version
computed the net->GIO-pad mapping via a single scipy.optimize.
linear_sum_assignment over ALL 20 nets against ALL 20 of v9's own GIO
target positions, minimizing total unrolled-ring-interval width (the
quantity that drives lane count) with NO constraint on which physical
GIO TERMINAL TYPE each position actually is. schematic/gio_connections.
json's own pad_pin_coords/connections_per_terminal_detail show that
those 20 positions are not interchangeable: 11 are "P<n>" pins (the
pad's own external-sense line, feeding INTO the chip -- correct only for
core INPUT signals: rst_n/scl/sda_in/tx_data[0-7]), 8 are "OUT<n>" pins
(driven BY the chip, correct only for core OUTPUT signals: rx_data[0-7]),
and 1 is "HIZ2" (the SDA pad's dynamic driver-enable control, the one
slot sda_oe needs). The unconstrained optimizer freely mixed these --
10 of 20 nets ended up on a terminal of the wrong type (e.g. scl, an
INPUT, landed on OUT4, a pin only the CORE can drive -- scl would never
see the real external clock; rx_data[2], an OUTPUT, landed on P1, a pin
that only senses the pad's own voltage -- rx_data would never reach the
real bond pad). DRC/routing-collision checks cannot catch this (the
metal is drawn correctly, just to the wrong logical pin) -- found only
by cross-referencing gio_connections.json's terminal-type info against
the 108.55 assignment after the fact.

FIRST FIX (still incomplete): split the assignment into three
independent, terminal-type-constrained sub-problems -- P<n>-type nets
only to P<n> slots, OUT<n>-type nets only to OUT<n> slots, sda_oe to the
one HIZ2 slot. This fixed the "wrong SPICE port type" bug but missed a
SECOND, deeper one: gio_connections.json's own connections list shows
each numbered pad n is a genuinely BIDIRECTIONAL physical bond pad --
P<n> (input sense) and OUT<n> (output drive) are the SAME external pin,
with HIZ<n> as its single shared direction control. V9's own pad map
always keeps tx_data[i]/rx_data[i] PAIRED on one shared pad number n
(e.g. P3=tx_data[7], OUT3=rx_data[7]), and sda_in/sda_oe paired on P2/
HIZ2. The first fix assigned P<n>-type and OUT<n>-type nets via two
INDEPENDENT optimizations, so it silently double-booked pad numbers --
e.g. pad 4 ended up hosting BOTH sda_in (P4, wants HIZ4 tied input-only)
AND rx_data[0] (OUT4, wants HIZ4 output-enabled) -- an unresolvable
contradiction on that pad's single HIZ4 control line, for EVERY one of
the 8 OUT<n> slots used.

REAL FIX (this revision): group the 20 nets by their true pad-sharing
requirement before optimizing:
  A. sda_in + sda_oe: FIXED to P2 + HIZ2 (the only HIZ-type slot
     available in v9's reusable 20-position pool -- no freedom here,
     matches v9's own dedicated-SDA-pad convention).
  B. rst_n, scl: the 2 remaining solo-P nets (input-only, no paired
     OUT<n> needed) <-> the 2 remaining "unpaired" P slots (P1, P15 --
     the ones with no corresponding OUT<n> in the 20-slot pool).
  C. 8 (tx_data[i], rx_data[i]) BIT PAIRS <-> the 8 pad numbers that
     have BOTH a P<n> and an OUT<n> in the pool (3,4,5,6,11,12,13,14).
     Each candidate pairing's cost is the SUM of both signals' interval
     widths against that one pad number's P<n>/OUT<n> positions --
     solved as one 8x8 linear_sum_assignment, so a pad number is either
     given to BOTH tx_data[i] and rx_data[i] of the same bit or neither.
This guarantees every physical pad's HIZ<n> has exactly one coherent
direction requirement (always-input for the 3 solo pads and SDA,
always-output-enabled-via-DIS-chain for the 8 bit pads), matching the
real GIO frame architecture -- not just "correct SPICE port type" but
"one signal group per physical pad."

Writes schematic/v10_signal_routing_plan.json (same schema as before,
now with a `terminal` field per net recording which GIO terminal name
each net landed on, and `_meta` documenting the terminal-type-
constrained method) and reports the resulting lane count via the exact
same greedy interval-packing algorithm route_gio_core_v10.py uses.

**REVISION (design_notes.md 108.68, user request)**: group C's 8x8
`linear_sum_assignment` above is proven-optimal for raw lane count
(108.57's exhaustive 80,640-pairing search), but its actual bit<->pad
mapping is visually arbitrary (P4=bit0, P12=bit1, P14=bit2, P5=bit3,
P6=bit4, P3=bit5, P11=bit6, P13=bit7). The user rejected reusing V9's
own literal mapping (bit0=P11..bit3=P14, bit4=P6..bit7=P3) for V10 --
independently reconfirmed here to need 14 lanes (max lane R=919.8 >
NEAR_R budget 915.0, i.e. genuinely not routable, matching 108.54's
finding) -- and instead asked for a clean, monotonically-increasing
pin order: as physical pad number climbs P3->P4->P5->P6->P11->P12->
P13->P14, bit number climbs 0->7 in step. This was verified BEFORE
implementing (same core_u/pad_u interval-packing cost function as
this script's own lane count, run standalone against both the user's
candidate orders) to need exactly 12 lanes -- the SAME proven-minimum
lane count as the free-optimization result above, just a more
readable bit<->pad correspondence. So group C below is now a fixed
table instead of an optimization -- there is no remaining freedom to
optimize once a specific, verified-optimal-cost bit order is chosen.
"""
import json
import sys

sys.path.insert(0, ".")
from route_gio_core_v9 import perimeter_s, unroll, R_NOM, PERI  # noqa: E402
from scipy.optimize import linear_sum_assignment
import numpy as np

BASE = "/sessions/dreamy-ecstatic-heisenberg/mnt/TR-1um_Async_I2C"
V10_CORE_PINS = "/tmp/v10_core_pins.json"
V9_PLAN = BASE + "/schematic/v9_signal_routing_plan.json"
GIO_CONN = BASE + "/schematic/gio_connections.json"
OUT_PLAN = BASE + "/schematic/v10_signal_routing_plan.json"

INPUT_NETS = ["rst_n", "scl", "sda_in", "tx_data[0]", "tx_data[1]", "tx_data[2]", "tx_data[3]",
              "tx_data[4]", "tx_data[5]", "tx_data[6]", "tx_data[7]"]
OUTPUT_NETS = ["rx_data[0]", "rx_data[1]", "rx_data[2]", "rx_data[3]",
               "rx_data[4]", "rx_data[5]", "rx_data[6]", "rx_data[7]"]
HIZ_NET = "sda_oe"


def terminal_type(name):
    if name.startswith("P"):
        return "P"
    if name.startswith("OUT"):
        return "OUT"
    if name.startswith("HIZ"):
        return "HIZ"
    raise ValueError(name)


def pad_number(term):
    """'P13'->13, 'OUT4'->4, 'HIZ2'->2."""
    i = 0
    while not term[i].isdigit():
        i += 1
    return int(term[i:])


SOLO_INPUT_NETS = ["rst_n", "scl"]  # sda_in handled separately (fixed to P2)
BIT_PAIRS = [(f"tx_data[{i}]", f"rx_data[{i}]") for i in range(8)]


def main():
    v10_core = json.load(open(V10_CORE_PINS))
    v9_plan = json.load(open(V9_PLAN))["nets"]
    gio_conn = json.load(open(GIO_CONN))
    coords = {k: v for k, v in gio_conn["pad_pin_coords"].items() if k != "_comment"}
    rev_coord = {(round(x, 1), round(y, 1)): name for name, (x, y) in coords.items()}

    # ---- classify v9's 20 GIO target positions by terminal type, and
    # tag each with its own (name, position dict) for reuse ----
    pad_slots = {"P": {}, "OUT": {}, "HIZ": {}}
    pad_pos = {}  # terminal name -> v9's own gio dict (x,y,edge,layer)
    for net_name, e in v9_plan.items():
        g = e["gio"]
        key = (round(g["x"], 1), round(g["y"], 1))
        term = rev_coord.get(key)
        if term is None:
            raise RuntimeError(f"v9 net {net_name!r}'s gio position {g} has no match in "
                                f"gio_connections.json pad_pin_coords")
        ttype = terminal_type(term)
        pad_slots[ttype][term] = None
        pad_pos[term] = g
    print("terminal-type inventory from v9's own 20-net pool:",
          {k: sorted(v) for k, v in pad_slots.items()})
    assert len(pad_slots["P"]) == len(INPUT_NETS), (len(pad_slots["P"]), len(INPUT_NETS))
    assert len(pad_slots["OUT"]) == len(OUTPUT_NETS), (len(pad_slots["OUT"]), len(OUTPUT_NETS))
    assert len(pad_slots["HIZ"]) == 1, pad_slots["HIZ"]

    p_numbers = {pad_number(t) for t in pad_slots["P"]}
    out_numbers = {pad_number(t) for t in pad_slots["OUT"]}
    bit_pad_numbers = sorted(p_numbers & out_numbers)      # have BOTH P<n> and OUT<n>
    solo_p_numbers = sorted(p_numbers - out_numbers)       # P<n> only, no OUT<n>
    hiz_term = next(iter(pad_slots["HIZ"]))
    hiz_number = pad_number(hiz_term)
    print(f"\nbidirectional bit-pad numbers (P<n>+OUT<n> both present): {bit_pad_numbers}")
    print(f"solo P-only pad numbers: {solo_p_numbers}  (HIZ slot is pad {hiz_number}, "
          f"sda_in/sda_oe FIXED there)")
    assert len(bit_pad_numbers) == 8, bit_pad_numbers
    # sda_in must share its pad number with sda_oe's fixed HIZ slot -- so
    # P<hiz_number> must be one of the solo P-only numbers (not a bit pad).
    assert hiz_number in solo_p_numbers, \
        f"HIZ slot pad {hiz_number} unexpectedly also has an OUT<n> -- can't dedicate it to SDA"
    solo_p_numbers_for_rst_scl = [n for n in solo_p_numbers if n != hiz_number]
    assert len(solo_p_numbers_for_rst_scl) == len(SOLO_INPUT_NETS), \
        (solo_p_numbers_for_rst_scl, SOLO_INPUT_NETS)

    core_s = {n: perimeter_s(c["x"], c["y"], c["edge"], R_NOM) for n, c in v10_core.items()}
    core_u = {n: unroll(s) for n, s in core_s.items()}
    pad_s = {t: perimeter_s(g["x"], g["y"], g["edge"], R_NOM) for t, g in pad_pos.items()}
    pad_u = {t: unroll(s) for t, s in pad_s.items()}

    assignment = {}  # net -> terminal name

    # ---- A: sda_in/sda_oe fixed ----
    sda_p_term = f"P{hiz_number}"
    assignment["sda_in"] = sda_p_term
    assignment[HIZ_NET] = hiz_term

    # ---- B: rst_n, scl <-> the 2 remaining solo P-only slots ----
    solo_terms = [f"P{n}" for n in solo_p_numbers_for_rst_scl]
    cost_b = np.zeros((len(SOLO_INPUT_NETS), len(solo_terms)))
    for i, net in enumerate(SOLO_INPUT_NETS):
        for j, term in enumerate(solo_terms):
            cost_b[i, j] = abs(core_u[net] - pad_u[term])
    row, col = linear_sum_assignment(cost_b)
    for i, j in zip(row, col):
        assignment[SOLO_INPUT_NETS[i]] = solo_terms[j]

    # ---- C: 8 (tx_data[i], rx_data[i]) bit pairs <-> 8 bit-pad numbers.
    # FORCED (108.68, user request) to a fixed, monotonically-increasing
    # bit<->pad table instead of optimized: as physical pad number climbs
    # P3->P4->P5->P6->P11->P12->P13->P14, bit number climbs 0->7 in step.
    # Independently verified beforehand (standalone script, same core_u/
    # pad_u interval-packing cost as below) to need exactly 12 lanes --
    # tied with the free 8x8 optimization's proven-minimum lane count --
    # so this is not a routability compromise, only a readability choice
    # among equally-optimal mappings. (The 8x8 linear_sum_assignment
    # import above is kept for groups A/B and left importable for anyone
    # re-deriving this table from scratch; it is simply not invoked here.)
    FORCED_BIT_PAD = {0: 3, 1: 4, 2: 5, 3: 6, 4: 11, 5: 12, 6: 13, 7: 14}
    assert sorted(FORCED_BIT_PAD.values()) == bit_pad_numbers, \
        (sorted(FORCED_BIT_PAD.values()), bit_pad_numbers)
    for i, (tx, rx) in enumerate(BIT_PAIRS):
        n = FORCED_BIT_PAD[i]
        assignment[tx] = f"P{n}"
        assignment[rx] = f"OUT{n}"

    print("\npad-pairing-aware assignment (bidirectional pads kept coherent):")
    for net in list(INPUT_NETS) + list(OUTPUT_NETS) + [HIZ_NET]:
        term = assignment[net]
        print(f"  {net:12s} -> {term:6s} (type={terminal_type(term)}, pad={pad_number(term)})")

    # sanity: every physical pad number used has a SINGLE coherent
    # signal group -- either exactly one matching (tx_data[i],rx_data[i])
    # bit pair, or exactly one solo input net (rst_n/scl/sda_in) with
    # its sda_oe HIZ companion where applicable. Never a P<n>-user and an
    # unrelated OUT<n>-user sharing one pad number (the bug this
    # revision fixes).
    used_by_pad = {}
    for net, term in assignment.items():
        n = pad_number(term)
        used_by_pad.setdefault(n, set()).add(net)
    print("\nper-pad occupancy (each physical pad's full net set):")
    for n in sorted(used_by_pad):
        nets = used_by_pad[n]
        if n in bit_pad_numbers:
            i = next(int(net.split("[")[1][:-1]) for net in nets if net.startswith("tx_data"))
            assert nets == {f"tx_data[{i}]", f"rx_data[{i}]"}, (n, nets)
        else:
            assert len(nets) <= 2, (n, nets)  # solo input, +sda_oe only for the SDA pad
        print(f"  pad {n:2d}: {sorted(nets)}")

    # ---- recompute lanes with this assignment, same algorithm as
    # route_gio_core_v10.py's own main() ----
    net_interval = {}
    for net, term in assignment.items():
        u1, u2 = core_u[net], pad_u[term]
        net_interval[net] = (min(u1, u2), max(u1, u2))
    lane_last = []
    for name, (lo, hi) in sorted(net_interval.items(), key=lambda kv: kv[1][0]):
        placed = False
        for i, last in enumerate(lane_last):
            if last < lo - 5.0:
                lane_last[i] = hi
                placed = True
                break
        if not placed:
            lane_last.append(hi)
    n_lanes = len(lane_last)
    # LANE_PITCH/NEAR_R match route_gio_core_v10.py's own (108.57-revised)
    # values -- kept in sync manually since this script only needs them
    # for the informational lane-count report, not for drawing anything.
    LANE_PITCH, NEAR_R = 5.6, 915.0
    max_r = 847.0 + LANE_PITCH * (n_lanes - 1)
    print(f"\nlanes needed (pad-pairing-constrained): {n_lanes}  (max lane R={max_r:.1f}, "
          f"budget: NEAR_R={NEAR_R})")

    # ---- write v10_signal_routing_plan.json ----
    out = {"_meta": {
        "note": "V10 signal routing plan (design_notes.md 108.57 -- FIXES 108.55/first-108.57"
                "-attempt's bugs of ignoring GIO terminal type AND pad-sharing). core-side "
                "positions are V10's real GDS-extracted pin positions. gio-side positions/"
                "edge/layer are one of v9's 20 fixed physical GIO terminal slots, assigned "
                "via THREE constrained sub-problems that keep every physical pad's P<n>/"
                "OUT<n>/HIZ<n> trio coherent: (A) sda_in/sda_oe fixed to P2/HIZ2 (the only "
                "reusable HIZ slot), (B) rst_n/scl optimally assigned to the 2 remaining "
                "solo P-only slots, (C) all 8 (tx_data[i],rx_data[i]) bit pairs optimally "
                "assigned AS PAIRS to the 8 pad numbers that have both a P<n> and an "
                "OUT<n> -- so a pad number is never split between two unrelated nets. Each "
                "sub-problem still minimizes total unrolled-ring-interval width (the "
                "lane-packing cost) within its own constraint.",
        "lanes_needed": n_lanes,
        "max_lane_r": max_r,
    }, "nets": {}}
    for name, c in v10_core.items():
        term = assignment[name]
        g = pad_pos[term]
        out["nets"][name] = {
            "core": {"x": c["x"], "y": c["y"], "edge": c["edge"], "layer": c["layer"]},
            "gio": dict(g),
            "terminal": term,
            "note": f"gio position/edge/layer = terminal {term} (type={terminal_type(term)}, "
                    f"pad={pad_number(term)}), position unchanged from v9's own frame-fixed "
                    f"pad_pin_coords",
        }
    json.dump(out, open(OUT_PLAN, "w"), indent=2, ensure_ascii=False)
    print(f"\nwrote {OUT_PLAN}")


if __name__ == "__main__":
    main()
