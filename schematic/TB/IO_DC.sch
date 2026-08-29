v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 480 1170 560 1170 {lab=ENB}
N 480 1210 560 1210 {lab=LO}
N 625 1220 625 1230 {lab=VSS}
N 680 1190 700 1190 {lab=IOL}
N 700 1190 730 1190 {lab=IOL}
N 625 1230 625 1250 {lab=VSS}
N 625 1250 730 1250 {lab=VSS}
N 480 1300 560 1300 {lab=ENB}
N 480 1340 560 1340 {lab=HI}
N 625 1350 625 1360 {lab=VSS}
N 680 1320 700 1320 {lab=IOH}
N 700 1320 730 1320 {lab=IOH}
N 625 1360 625 1380 {lab=VSS}
N 625 1380 730 1380 {lab=VSS}
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
venb enb 0 dc vdd
*----
vHI  HI  0 dc vdd
vLO  LO  0 dc vss
*----
vIOH IOH  0 dc vdd
vIOL IOL  0 dc vdd
"}
C {devices/lab_wire.sym} 530 1170 0 0 {name=p1 sig_type=std_logic lab=ENB}
C {devices/lab_wire.sym} 530 1210 0 0 {name=p2 sig_type=std_logic lab=LO}
C {devices/lab_wire.sym} 720 1190 0 0 {name=p3 sig_type=std_logic lab=IOL}
C {devices/lab_wire.sym} 710 1250 0 0 {name=p4 sig_type=std_logic lab=VSS}
C {/Users/okamura/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_frame/OSS_ESD_5V_DIO.sym} 640 1320 0 1 {name=x2}
C {devices/vdd.sym} 640 1290 0 0 {name=l2 lab=VDD}
C {devices/lab_wire.sym} 530 1300 0 0 {name=p5 sig_type=std_logic lab=ENB}
C {devices/lab_wire.sym} 530 1340 0 0 {name=p6 sig_type=std_logic lab=HI}
C {devices/lab_wire.sym} 720 1320 0 0 {name=p7 sig_type=std_logic lab=IOH}
C {devices/lab_wire.sym} 710 1380 0 0 {name=p8 sig_type=std_logic lab=VSS}
*
C {devices/netlist_at_end.sym} 750 1070 0 0 {name=s1 value="
*----
.temp 25
*.dc vIOL 5     0 -0.01
*.dc vIOH 0     5  0.01
"}
