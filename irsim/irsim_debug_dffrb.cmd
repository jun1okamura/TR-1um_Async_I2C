| irsim_debug_dffrb.cmd -- follow-up to irsim_debug_rw_addrmatch.cmd.
| With the BUFTH fix, $28 (rw/addr_match's RSTB) now genuinely resolves
| to a defined 1 (released) after rst_n releases -- but rw/addr_match
| themselves stay X even 15000ns later. Traced DFFRB's (X$2, instance
| XN2) internal structure by hand:
|
|   Q(=rw)  = driven by QB via a plain inverter (XM$1/XM$14) -- fully
|             deterministic once QB is known.
|   QB(=N4) = NOT(QS), once RSTB=1 (via XM$10 keeper PMOS gated by QS,
|             and XM$24/XM$23 gated-by-RSTB pass-to-$14-then-to-QB path)
|             -- fully deterministic once QS is known. (During RSTB=0,
|             QB is instead force-driven to 1 directly by XM$11 --
|             that's why Q read a clean 0 throughout the whole assert
|             window.)
|   QS      = the actual master-slave "slave" storage node. Fed by TWO
|             transmission gates: one from QM (gate=CKB/CKP), one from
|             $10=INV(QB) i.e. effectively QS itself (gate=CKP/CKB,
|             opposite phase) -- the classic TG-latch hold loop. RSTB
|             never touches QS/QM/$10 directly, only QB/Q. Since this
|             design's clock (XN2.CKB/CKP, derived from N34) has never
|             toggled since cold start (no protocol activity yet), both
|             TGs feeding QS are gated by X-valued clock phases -- same
|             category of unresolvable cold-X fixed point as BUFTH's
|             N2<->N6 loop, just one level removed (through QB/$10 too).
|
| This tests whether a one-time force/release of QS (the actual root,
| analogous to BUFTH's N2) breaks the deadlock the same way it did for
| BUFTH. Only testing rw's own DFFRB (X$2/XN2) here -- if this works,
| the same treatment will need to be scripted for however many of the
| other 32 DFFRB instances turn out to need it (design_notes.md 76.13
| once we know more).

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
s 100
| ---- t=8120ns, 100ns after release, BEFORE forcing QS (expect rw=X, ----
| ---- matches irsim_debug_rw_addrmatch.cmd) ----
d N106 XN3.N28 XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
l XN3.XN2.QS
s
| ---- QS forced l ----
d XN3.XN2.QS XN3.N4 XN3.rw
x XN3.XN2.QS
s 100
| ---- QS released, 100ns later -- does it hold? ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s 2000
| ---- 2000ns after release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match

| end of irsim_debug_dffrb.cmd
