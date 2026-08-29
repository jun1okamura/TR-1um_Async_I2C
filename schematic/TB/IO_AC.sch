v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 480 1170 560 1170 {lab=HIZ}
N 480 1210 560 1210 {lab=OUT}
N 625 1220 625 1230 {lab=VSS}
N 680 1190 700 1190 {lab=PAD}
N 700 1190 730 1190 {lab=PAD}
N 625 1230 625 1250 {lab=VSS}
N 625 1250 730 1250 {lab=VSS}
N 730 1190 770 1190 {lab=PAD}
N 830 1190 880 1190 {lab=VT}
C {/Users/okamura/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_frame/OSS_ESD_5V_DIO.sym} 640 1190 0 1 {name=x1}
C {devices/vdd.sym} 640 1160 0 0 {name=l1 lab=VDD}
C {devices/simulator_commands.sym} 470 1020 0 0 {name=COMMANDS
simulator=ngspice
only_toplevel=false 
value="
* ngspice commands
.include '~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/models/ip62_models'
.param vdd=5.0
.param vss=0
*----
vdd  vdd 0 dc vdd
vss  vss 0 dc vss
vtt  vt  0 dc 'vdd / 2.0'
.param cload='20p'
.param trf=100p
vout out 0 pwl(0n vss 100n vss '100n+trf' vdd  200n vdd  '200n+trf' vss R)
vhiz hiz 0 pwl(0n vss 500n vss '500n+trf' vdd 1000n vdd '1000n+trf' vss R)
"}
C {devices/lab_wire.sym} 530 1170 0 0 {name=p1 sig_type=std_logic lab=HIZ}
C {devices/lab_wire.sym} 530 1210 0 0 {name=p2 sig_type=std_logic lab=OUT}
C {devices/lab_wire.sym} 720 1190 0 0 {name=p3 sig_type=std_logic lab=PAD}
C {devices/lab_wire.sym} 710 1250 0 0 {name=p4 sig_type=std_logic lab=VSS}
C {devices/capa.sym} 730 1220 0 0 {name=C1
m=1
value=cload
footprint=1206
device="ceramic capacitor"}
C {devices/netlist_at_end.sym} 750 1070 0 0 {name=s1 value="
*----
.temp 25
.tran 10p 600n
.print tran v(out) v(hiz) v(pad) 
.plot v(out) v(pad)
"}
C {devices/res.sym} 800 1190 1 0 {name=R1
value=1k
footprint=1206
device=resistor
m=1}
C {devices/lab_wire.sym} 870 1190 0 0 {name=p5 sig_type=std_logic lab=VT}
