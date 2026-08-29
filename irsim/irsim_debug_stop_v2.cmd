| irsim_debug_stop_v2.cmd -- follow-up to irsim_debug_stop.cmd.
| busy never cleared after STOP even 7960ns later -- ruled out as a
| simple "just needs more settling time AFTER the edge" issue. Next
| hypothesis: STOP is edge-detected through a chain that includes DEL1
| (N704=DEL1(N697), a real intentional delay element -- see design_notes
| 76.10/76.13's fan-in trace notes, which already flagged DEL1 as
| possibly needing much more than a few T=20ns stepsizes to settle).
| gen_irsim_cmd.py's stop() only holds SDA low for ONE stepsize (20ns)
| before releasing it back high -- if DEL1's delay is much longer than
| that, the falling edge may never even finish propagating through DEL1
| before we release SDA again, "swallowing" the edge the STOP-detector
| needs to see. This test holds SDA low for 2000ns before releasing (vs.
| the normal 20ns) to see if a properly-settled STOP edge clears busy.
|
| This does NOT replay the WRITE transaction's data phase -- it takes a
| shortcut: assert+release reset and the DFFRB fixes as usual, then
| directly force busy HIGH via the standard START sequence (skipping
| address/data), then attempt STOP with a long SDA-low hold, to isolate
| the STOP/busy-clear mechanism specifically without the noise of a full
| transaction. (Uses the exact same node names/fixes as irsim_test_main.cmd.)

stepsize 20
h Vdd
l Gnd
x N58
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
s 3000
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
h N106
s 100
| ---- reset released, idle ----
d N58 N45 XN3.busy
| ---- START ----
h N102
x N58
s
l N58
s 40
| ---- check: busy set after START ----
d XN3.busy
| ---- (skip address/data -- go straight for a STOP-shaped edge) ----
| ---- hold SDA low for 2000ns this time (vs. the normal 20ns) ----
l N58
h N102
s 2000
| ---- SDA held low 2000ns, SCL high -- about to release (STOP edge) ----
d N58 N102 XN3.busy
x N58
s 40
| ---- +40ns after STOP edge ----
d N58 XN3.busy
s 460
| ---- +500ns after STOP edge ----
d XN3.busy
s 2500
| ---- +3000ns after STOP edge ----
d XN3.busy
s 5000
| ---- +8000ns after STOP edge ----
d XN3.busy

| end of irsim_debug_stop_v2.cmd
