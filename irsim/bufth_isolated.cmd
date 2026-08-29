stepsize 20
h Vdd
l Gnd
h A
d A Y N2 N6
s 100
| ---- A=1 held 100ns ----
d A Y N2 N6
s 2000
| ---- A=1 held 2100ns total ----
d A Y N2 N6
l A
s 100
| ---- A=0 (100ns after falling) ----
d A Y N2 N6
s 2000
| ---- A=0 held 2100ns ----
d A Y N2 N6
h A
s 100
| ---- A=1 again (100ns after rising) ----
d A Y N2 N6
