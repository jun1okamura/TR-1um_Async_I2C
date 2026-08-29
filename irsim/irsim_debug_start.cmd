| irsim_debug_start.cmd -- follow-up diagnostic.
| irsim_reset_check.cmd (static hold only, no START) now resolves and
| HOLDS N58/N45/busy/rw/addr_match all correctly after reset release.
| But irsim_test_main.cmd (which immediately does an actual START
| condition right after the preamble) shows N45(sda_oe) and XN3.busy
| going/staying X (hatched) once the real SDA 1->0-while-SCL=1 edge
| happens, even though busy is a plain NOR2 SR latch (not a DFFRB) that
| should SET cleanly on a real edge. This watches every step of start()
| individually -- h(SCL), x(SDA) [release to pullup], l(SDA) [the actual
| START edge], plus the full busy fan-in chain from irsim_debug_busy_chain.cmd
| -- to find exactly which step first introduces X.
|
| Reminder of the fan-in chain (design_notes.md 76.10/76.12/76.13):
|   busy = NOR2(N695, N707)          [X369->X367 SR latch cross-couple]
|   N707 = NOR2(N813, busy)          [X368]
|   N695 = NAND2(rst_n, N696)        [X348]
|   N813 = NOR2(N697, N703)          [X369]
|   N696 = NAND3(N817, N666, N697)   [X214]
|   N817 = INV_X1(N704)              [X383]
|   N704 = DEL1(N697)                [X312]
|   N697 = BUF_X1(N37=BUFTH(sda_in)) [X167]
|   N666 = BUF_X1(N712=BUFTH(scl))   [X307]
|   N227 (sda_oe's own RSTB2) = AND2_X1(busy, rst_n) [X356]

stepsize 20
h Vdd
l Gnd
h N58
h N102
l N26
l N19
l N21
l N22
l N57
l N103
l N72
l N68
l N106
l XN3.XN166.N2
l XN3.XN311.N2
s
x XN3.XN166.N2
x XN3.XN311.N2
s 8000
h N106
s
l XN3.XN2.QS
l XN3.XN16.QS
l XN3.XN32.QS
l XN3.XN46.QS
l XN3.XN104.QS
l XN3.XN105.QS
l XN3.XN106.QS
l XN3.XN107.QS
l XN3.XN108.QS
l XN3.XN109.QS
l XN3.XN110.QS
l XN3.XN111.QS
l XN3.XN112.QS
l XN3.XN113.QS
l XN3.XN114.QS
l XN3.XN115.QS
l XN3.XN116.QS
l XN3.XN117.QS
l XN3.XN118.QS
l XN3.XN119.QS
l XN3.XN120.QS
l XN3.XN121.QS
l XN3.XN122.QS
l XN3.XN123.QS
s
x XN3.XN2.QS
x XN3.XN16.QS
x XN3.XN32.QS
x XN3.XN46.QS
x XN3.XN104.QS
x XN3.XN105.QS
x XN3.XN106.QS
x XN3.XN107.QS
x XN3.XN108.QS
x XN3.XN109.QS
x XN3.XN110.QS
x XN3.XN111.QS
x XN3.XN112.QS
x XN3.XN113.QS
x XN3.XN114.QS
x XN3.XN115.QS
x XN3.XN116.QS
x XN3.XN117.QS
x XN3.XN118.QS
x XN3.XN119.QS
x XN3.XN120.QS
x XN3.XN121.QS
x XN3.XN122.QS
x XN3.XN123.QS
s 100
| ---- reset fully released, before any START activity (matches ----
| ---- irsim_reset_check.cmd's final state -- should all be defined) ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match

| ==== now replicate start()'s exact sequence, one step at a time ====
h N102
s
| ---- SCL forced h (no-op, already 1) ----
x N58
s
| ---- SDA released to weak pullup (no START edge yet -- SCL still 1, ----
| ---- SDA hasn't fallen) ----
d N58 N45 XN3.busy XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.N227
l N58
s
| ---- SDA forced l -- THE ACTUAL START EDGE (SDA 1->0 while SCL=1) ----
d N58 N45 XN3.busy XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.N227
s 40
| ---- 40ns after the START edge ----
d N58 N45 XN3.busy XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.N227
s 1000
| ---- 1000ns after the START edge (in case it's just slow) ----
d N58 N45 XN3.busy XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.N227

| end of irsim_debug_start.cmd
