v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 490 1190 570 1190 {lab=IN}
N 620 1230 620 1250 {lab=VSS}
N 620 1250 640 1250 {lab=VSS}
N 640 1250 730 1250 {lab=VSS}
N 690 1190 730 1190 {lab=OUT}
C {devices/vdd.sym} 620 1150 0 0 {name=l1 lab=VDD}
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
vin  in  0 pwl(0n vss 5 vdd 10 vss)
"}
C {devices/lab_wire.sym} 540 1190 0 0 {name=p2 sig_type=std_logic lab=IN}
C {devices/lab_wire.sym} 720 1190 0 0 {name=p3 sig_type=std_logic lab=OUT}
C {devices/lab_wire.sym} 710 1250 0 0 {name=p4 sig_type=std_logic lab=VSS}
C {devices/netlist_at_end.sym} 750 1070 0 0 {name=s1 value="
*----
.temp 25
.tran .01 10
"}
C {BUFTH_X1.sym} 590 1190 0 0 {name=x1}
