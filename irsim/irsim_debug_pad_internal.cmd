| irsim_debug_pad_internal.cmd -- follow-up to irsim_debug_sda_pad.cmd.
| N58 reads 0 regardless of N45(sda_oe/HIZ13), which contradicts the
| assumption "sda_oe=1 drives SDA low, sda_oe=0 releases" AND a by-hand
| trace of OSS_ESD_5V_DIO's ~16-transistor pre-driver network (too
| complex/error-prone to fully hand-verify reliably -- see notes in
| irsim_debug_sda_pad.cmd). This dumps every internal pre-driver node
| directly instead of guessing further:
|
|   PAD(=N58) driven by:
|     XM$23 (PMOS, gate=$8=XN1.XN16.N8,  drain=PAD, source=Vdd) -- pulls
|           PAD high when N8=0
|     XM$36 (NMOS, gate=$9=XN1.XN16.N9,  drain=PAD, source=Gnd) -- pulls
|           PAD low  when N9=1
|     (XM$19/XM$29, gate=source=Vdd/Gnd respectively, are permanently
|      OFF ESD clamp elements -- not relevant to normal operation)
|   N8 = INV(NI6), N9 = INV(NI7)   [XM$7/$12, XM$4/$15]
|   NI6 driven by: HIZ (XM$5 PMOS to NI8, XM$10 NMOS to Gnd) AND NI5
|                  (XM$11 NMOS to Gnd)
|   NI7 driven by: NI5 (XM$3 PMOS to Vdd) AND NI4/NI9 (XM$2 PMOS to Vdd,
|                  XM$13 NMOS to NI9)
|   NI4 = INV(HIZ)              [XM$1/$16]
|   NI5 = INV(OUT), OUT=Gnd (fixed wiring) -> NI5 should be a constant 1
|         [XM$8/$9]
|   NI8 driven by NI5 (XM$6 PMOS to Vdd) and NI7 (?) -- not fully traced
|   NI9 driven by NI6 (?) -- not fully traced
|
| Watching all of these for both HIZ=N45=0 and HIZ=N45=1.

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
| ---- N45(HIZ)=0 ----
d N45 N58 XN1.XN16.N8 XN1.XN16.N9 XN1.XN16.NI4 XN1.XN16.NI5 XN1.XN16.NI6 XN1.XN16.NI7 XN1.XN16.NI8 XN1.XN16.NI9
h N45
s 200
| ---- N45(HIZ)=1 ----
d N45 N58 XN1.XN16.N8 XN1.XN16.N9 XN1.XN16.NI4 XN1.XN16.NI5 XN1.XN16.NI6 XN1.XN16.NI7 XN1.XN16.NI8 XN1.XN16.NI9

| end of irsim_debug_pad_internal.cmd
