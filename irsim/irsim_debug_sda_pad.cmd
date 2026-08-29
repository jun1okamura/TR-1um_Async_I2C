| irsim_debug_sda_pad.cmd -- follow-up diagnostic.
| irsim_reset_check.cmd (no more "h SDA" override, weak pull-up gated by
| sda_oe=N45) now resolves EVERYTHING cleanly (no X at all!) but N58
| settles to 0 while N45(sda_oe)=0 -- the OPPOSITE of what was assumed
| ("sda_oe=1 drives SDA low, sda_oe=0 releases -> pull-up should win ->
| SDA=1"). The pad cell (OSS_ESD_5V_DIO, a 5V-tolerant ESD I/O buffer
| with ~16 internal pre-driver transistors between HIZ/OUT and the
| actual PAD-driving PMOS/NMOS) is too complex to fully hand-trace
| reliably -- testing the real polarity directly instead, bypassing the
| DFFRB/reset chain entirely by forcing N45 (sda_oe) straight to each
| value and watching what the pad (N58) actually does. This also
| verifies the gated pull-up (gate=N45) is wired the way intended.

stepsize 20
h Vdd
l Gnd
l N106
h N102
l N26
l N19
l N21
l N22
l N57
l N103
l N72
l N68
l N45
x N58
s 200
| ---- N45(sda_oe) forced l(0) -- if the old "sda_oe=1 drives low, ----
| ---- sda_oe=0 releases" assumption is right, N58 should be 1 here ----
d N45 N58
h N45
s 200
| ---- N45(sda_oe) forced h(1) -- should be 0 here under the old ----
| ---- assumption ----
d N45 N58
l N45
s 200
| ---- back to N45=0 -- confirm it's repeatable, not just a transient ----
d N45 N58

| end of irsim_debug_sda_pad.cmd
