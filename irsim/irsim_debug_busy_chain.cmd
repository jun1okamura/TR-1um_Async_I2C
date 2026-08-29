| irsim_debug_busy_chain.cmd -- hand-written, one-off diagnostic.
| N58 is now solid (forced h throughout), yet busy/sda_oe still go back
| to X right after rst_n releases. This watches every intermediate node
| on the traced fan-in chain (design_notes.md 76.11) so we can see
| exactly which one is the first to go X, instead of guessing further:
|
|   busy = NOR2(XN3.N695, XN3.N707)          [XN3.X367]
|   XN3.N707 = NOR2(XN3.N813, busy)          [XN3.X368]
|   XN3.N695 = NAND2(rst_n, XN3.N696)        [XN3.X348]
|   XN3.N813 = NOR2(XN3.N697, XN3.N703)      [XN3.X369]
|   XN3.N696 = NAND3(XN3.N817, XN3.N666, XN3.N697)  [XN3.X214]
|   XN3.N817 = INV_X1(XN3.N704)              [XN3.X383]
|   XN3.N704 = DEL1(XN3.N697)                [XN3.X312]   <- intentional
|              delay device, real L=2u transistor -- could plausibly
|              need more than 8000ns to settle with a mismatched
|              generic .prm; watch this one closely.
|   XN3.N697 = BUF_X1(XN3.N37)               [XN3.X167]
|   XN3.N37  = BUFTH(sda_in)                 [XN3.X166]
|   XN3.N666 = BUF_X1(XN3.N712)              [XN3.X307]
|   XN3.N712 = BUFTH(scl)                    [XN3.X311]
|   XN3.N227 (RSTB2, sda_oe's own DFFRB's clear) = AND2_X1(busy, rst_n) [XN3.X356]
|
| XN3.N703 not yet traced -- watching it too in case it's the actual gap.

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
d N106 N102 N58 XN3.N37 XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.busy N45 XN3.N227
s 8000
| ---- t=8000ns, reset still asserted ----
d N106 N102 N58 XN3.N37 XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.busy N45 XN3.N227
h N106
s 20
| ---- t=8020ns, 20ns after release ----
d N106 N102 N58 XN3.N37 XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.busy N45 XN3.N227
s 200
| ---- t=8220ns, 220ns after release ----
d N106 N102 N58 XN3.N37 XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.busy N45 XN3.N227
s 5000
| ---- t=13220ns, 5220ns after release (in case DEL1 just needs more time) ----
d N106 N102 N58 XN3.N37 XN3.N697 XN3.N704 XN3.N817 XN3.N712 XN3.N666 XN3.N696 XN3.N695 XN3.N703 XN3.N813 XN3.N707 XN3.busy N45 XN3.N227

| end of irsim_debug_busy_chain.cmd
