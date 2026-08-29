| irsim_debug_dffrb2.cmd -- fine-grained trace of rw's DFFRB (QS/QB/Q)
| around its $28-group force/release, under the REAL TR-1um.prm. See
| design_notes.md 76.29/76.30.
stepsize 20
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
s 3000
| ---- t=3000ns, still in reset ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match XN3.XN2.QS XN3.N4
s 5000
| ---- t=8000ns, still in reset ----
d N58 N45 XN3.busy XN3.rw XN3.addr_match XN3.XN2.QS XN3.N4
h N106
s
| ---- rst_n released, +1 stepsize, BEFORE QS force/release ----
d N106 XN3.N28 XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
| ---- forcing QS=0 for all $28-group instances ----
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
| ---- QS forced, before release ----
d XN3.XN2.QS XN3.N4 XN3.rw
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
| ---- +20ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +40ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +60ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +80ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +100ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +120ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +140ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +160ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +180ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +200ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +220ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +240ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +260ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +280ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +300ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +320ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +340ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +360ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +380ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match
s
| ---- +400ns after QS release ----
d XN3.XN2.QS XN3.N4 XN3.rw XN3.addr_match

| end of irsim_debug_dffrb2.cmd
