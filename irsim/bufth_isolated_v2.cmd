| bufth_isolated_v2.cmd -- follow-up to bufth_isolated.cmd.
| Isolated BUFTH also stuck at X (Y=N2=N6=X even with A=1 held 2000ns+),
| contradicting the hand-trace (XM$7/XM$8, both gated only by the known
| value A, form a determinate series pulldown Gnd-N6-N2, independent of
| N6's own value). The likely explanation: N2 also feeds back into N6
| through XM$9 (n N2 N6 Vdd, gated by N2 itself) -- a genuine regenerative
| loop (this is a Schmitt trigger; the hysteresis IS the feedback). From a
| cold X start, IRSIM's ternary solver may treat the mutual N2<->N6
| dependency as a fixed point at X and never break the symmetry, even
| though a one-shot graph walk (ignoring the feedback edge) proves N2=0.
|
| This script tests that theory directly: momentarily FORCE N2 to break
| the symmetry once, then release it and see whether the surrounding
| network (which we've shown is fully determinate given A) holds it there
| on its own, or whether it reverts to X.

stepsize 20
h Vdd
l Gnd
h A
s 100
| ---- A=1 held 100ns, before any forcing (expect X, matches bufth_isolated.cmd) ----
d A Y N2 N6
l N2
s 20
| ---- N2 forced l, 20ns later ----
d A Y N2 N6
x N2
s 20
| ---- N2 released (x), 20ns later -- does it hold or revert to X? ----
d A Y N2 N6
s 500
| ---- 500ns after release ----
d A Y N2 N6

| end of bufth_isolated_v2.cmd
