| irsim_reset_check.cmd -- does reset alone resolve busy/sda_oe/
| addr_match/rw out of X? Run this BEFORE the transaction tests
| (much faster to read than the full write/read trace for the
| same check). See design_notes.md 76.10 for why reset needs to
| be held this long: busy is a cross-coupled NOR2 SR latch (not
| a DFFRB) that must itself resolve out of X, since 9 of the 33
| DFFRBs (incl. sda_oe's) gate their clear as "busy AND rst_n".
| SDA is just released ("x") to the sda_oe-gated weak pull-up (see
| gen_irsim_sim.py) -- no explicit "h" override needed: sda_oe is held
| at a genuinely DEFINED 0 throughout by AND-domination alone (RSTB2=
| busy AND rst_n=0 while rst_n=0, and stays 0 after release as long as
| busy hasn't gone high yet), so the pull-up's gate is never X and SDA
| resolves cleanly on its own (see 76.11/76.16, supersedes an earlier
| version of this script that forced SDA high here).
| DFFRB (33x, incl. rw/addr_match's own registers) has a similar cold-X
| problem via its internal QS node -- see 76.13. One-time force/release
| below. (BUFTH had a related issue but is now substituted with BUF_X1
| in the .sim itself, see 76.15 -- no BUFTH-specific handling needed here.)
| DIS (P7, N2) is forced H -- normal operation, not the write/read-
| register loopback test mode (76.19).
| settle 50: see preamble()'s comment / design_notes.md 76.32.
stepsize 20
settle 50
h Vdd
l Gnd
x N58
h N102
h N2
l N26
l N19
l N21
l N22
l N57
l N103
l N72
l N68
l N106
d N58 N45 XN3.busy XN3.rw XN3.addr_match
s 100
| ---- t=100ns since reset asserted ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match
s 400
| ---- t=500ns since reset asserted ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match
s 500
| ---- t=1000ns since reset asserted ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match
s 2000
| ---- t=3000ns since reset asserted ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match
s 5000
| ---- t=8000ns since reset asserted ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match
h N106
s
| ---- $28-group DFFRBs (24 incl. rw/addr_match) force/release ----
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
s
s 100
| ---- reset released ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match
| (sda_oe stays a legitimate 0 here, not from resolving -- its own
| DFFRB is in the $227=busy AND rst_n group, still held in reset
| since busy hasn't gone high yet. That group's force/release happens
| in start(), after the first real START condition -- see 76.13.)

| end of irsim_reset_check.cmd
