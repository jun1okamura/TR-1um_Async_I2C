| irsim_reset_check.cmd -- does reset alone resolve busy/sda_oe/
| addr_match/rw out of X? Run this BEFORE the transaction tests
| (much faster to read than the full write/read trace for the
| same check). See design_notes.md 76.10 for why reset needs to
| be held this long: busy is a cross-coupled SR latch (not
| a DFFRB) that must itself resolve out of X, since 9 of the 33
| DFFRBs (incl. sda_oe's) gate their clear as "busy AND rst_n".
| SDA is just released ("x") to the sda_oe-gated weak pull-up (see
| gen_irsim_sim_v9.py) -- no explicit "h" override needed: sda_oe is
| held at a genuinely DEFINED 0 throughout by AND-domination alone
| (Group-B RSTB=busy AND rst_n=0 while rst_n=0, and stays 0 after
| release as long as busy hasn't gone high yet), so the pull-up's
| gate is never X and SDA resolves cleanly on its own (76.11/76.16).
| DFFRB (33x, incl. rw/addr_match's own registers) has a similar cold-X
| problem via its internal QS node -- see 76.13. One-time force/release
| below. (BUFTH had a related issue but is substituted with BUF_X1 in
| the .sim itself, see 76.15/87.2 -- no BUFTH-specific handling here.)
| DIS (P7) is forced H -- normal operation, not the write/read-register
| loopback test mode (76.19).
| settle 50: see preamble()'s comment / design_notes.md 76.32.
stepsize 20
settle 50
h Vdd
l Gnd
x P13
h P2
h P7
l P12
l P11
l P5
l P6
l P4
l P1
l P3
l P14
l P15
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
s 100
| ---- t=100ns since reset asserted ----
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
s 400
| ---- t=500ns since reset asserted ----
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
s 500
| ---- t=1000ns since reset asserted ----
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
s 2000
| ---- t=3000ns since reset asserted ----
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
s 5000
| ---- t=8000ns since reset asserted ----
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
h P15
s
| ---- Group-A DFFRBs (24 incl. rw/addr_match) force/release ----
l x2.x_269_.QS
l x2.x_270_.QS
l x2.x_271_.QS
l x2.x_272_.QS
l x2.x_273_.QS
l x2.x_274_.QS
l x2.x_275_.QS
l x2.x_276_.QS
l x2.x_285_.QS
l x2.x_286_.QS
l x2.x_287_.QS
l x2.x_288_.QS
l x2.x_289_.QS
l x2.x_290_.QS
l x2.x_291_.QS
l x2.x_292_.QS
l x2.x_294_.QS
l x2.x_295_.QS
l x2.x_296_.QS
l x2.x_297_.QS
l x2.x_298_.QS
l x2.x_299_.QS
l x2.x_300_.QS
l x2.x_301_.QS
s
x x2.x_269_.QS
x x2.x_270_.QS
x x2.x_271_.QS
x x2.x_272_.QS
x x2.x_273_.QS
x x2.x_274_.QS
x x2.x_275_.QS
x x2.x_276_.QS
x x2.x_285_.QS
x x2.x_286_.QS
x x2.x_287_.QS
x x2.x_288_.QS
x x2.x_289_.QS
x x2.x_290_.QS
x x2.x_291_.QS
x x2.x_292_.QS
x x2.x_294_.QS
x x2.x_295_.QS
x x2.x_296_.QS
x x2.x_297_.QS
x x2.x_298_.QS
x x2.x_299_.QS
x x2.x_300_.QS
x x2.x_301_.QS
s
s 100
| ---- reset released ----
d P13 SDA_O NC_CORE_busy NC_CORE_rw NC_CORE_addr_match
| (sda_oe stays a legitimate 0 here, not from resolving -- its own
| DFFRB is in Group B (busy AND rst_n), still held in reset since
| busy hasn't gone high yet. That group's force/release happens in
| start(), after the first real START condition -- see 76.13.)

| end of irsim_reset_check.cmd
