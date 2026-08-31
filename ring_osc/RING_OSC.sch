v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 220 -440 280 -440 {lab=FB,R[0:93]}
N 400 -440 480 -440 {lab=R[0:94]}
N 520 -440 580 -440 {lab=R[94]}
N 710 -420 780 -420 {lab=FB}
N 330 -480 380 -480 {lab=VDD}
N 330 -400 380 -400 {lab=VSS}
N 830 -460 880 -460 {lab=VDD}
N 830 -380 880 -380 {lab=VSS}
N 630 -480 680 -480 {lab=VDD}
N 630 -360 680 -360 {lab=VSS}
N 220 -240 280 -240 {lab=FD,D[0:93]}
N 400 -240 480 -240 {lab=D[0:94]}
N 520 -240 580 -240 {lab=D[94]}
N 710 -220 780 -220 {lab=FD}
N 330 -280 380 -280 {lab=VDD}
N 330 -200 380 -200 {lab=VSS}
N 830 -260 880 -260 {lab=VDD}
N 830 -180 880 -180 {lab=VSS}
N 630 -280 680 -280 {lab=VDD}
N 630 -160 680 -160 {lab=VSS}
N 500 -400 580 -400 {lab=ENB}
N 500 -200 580 -200 {lab=ENB}
N 500 -400 500 -200 {lab=ENB}
N 1130 -100 1180 -100 {lab=VSS}
N 1130 -220 1180 -220 {lab=VDD}
N 1130 -320 1180 -320 {lab=VSS}
N 1130 -440 1180 -440 {lab=VDD}
C {devices/title.sym} 160 0 0 0 {name=l1 author="Stefan Schippers"}
C {INV_X1.sym} 300 -440 0 0 {name=x1[0:94]
}
C {devices/lab_wire.sym} 261.091527917967 -440 0 0 {name=p1 sig_type=std_logic lab=FB,R[0:93]}
C {devices/lab_wire.sym} 471.091527917967 -440 0 0 {name=p2 sig_type=std_logic lab=R[0:94]}
C {AND2_X1.sym} 600 -420 0 0 {name=x1}
C {devices/lab_wire.sym} 751.091527917967 -420 0 0 {name=p3 sig_type=std_logic lab=FB}
C {INV_X1.sym} 800 -420 0 0 {name=x3

}
C {devices/opin.sym} 900 -420 0 0 {name=p4 lab=OUT}
C {devices/lab_wire.sym} 561.091527917967 -440 0 0 {name=p5 sig_type=std_logic lab=R[94]}
C {devices/lab_wire.sym} 370 -480 0 0 {name=p6 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 370 -400 0 0 {name=p7 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 870 -460 0 0 {name=p8 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 870 -380 0 0 {name=p9 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 670 -480 0 0 {name=p10 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 670 -360 0 0 {name=p11 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 261.091527917967 -240 0 0 {name=p12 sig_type=std_logic lab=FD,D[0:93]}
C {devices/lab_wire.sym} 471.091527917967 -240 0 0 {name=p13 sig_type=std_logic lab=D[0:94]}
C {AND2_X1.sym} 600 -220 0 0 {name=x2}
C {devices/lab_wire.sym} 751.091527917967 -220 0 0 {name=p14 sig_type=std_logic lab=FD}
C {INV_X1.sym} 800 -220 0 0 {name=x4

}
C {devices/opin.sym} 900 -220 0 0 {name=p15 lab=OUTD}
C {devices/lab_wire.sym} 561.091527917967 -240 0 0 {name=p16 sig_type=std_logic lab=D[94]}
C {devices/lab_wire.sym} 370 -280 0 0 {name=p17 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 370 -200 0 0 {name=p18 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 870 -260 0 0 {name=p19 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 870 -180 0 0 {name=p20 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 670 -280 0 0 {name=p21 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 670 -160 0 0 {name=p22 sig_type=std_logic lab=VSS}
C {devices/ipin.sym} 500 -330 0 0 {name=p23 lab=ENB}
C {devices/iopin.sym} 880 -460 0 0 {name=p24 lab=VDD}
C {devices/iopin.sym} 880 -380 0 0 {name=p25 lab=VSS}
C {/Users/okamura/Dropbox/98_LSI_Design/TR-1um_Async_I2C/LEF/FILL2.sym} 1130 -160 0 0 {name=x5[0:15]}
C {devices/lab_wire.sym} 1170 -100 0 0 {name=p26 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 1170 -220 0 0 {name=p27 sig_type=std_logic lab=VDD}
C {/Users/okamura/Dropbox/98_LSI_Design/TR-1um_Async_I2C/LEF/FILL2.sym} 1130 -380 0 0 {name=x3[0:189]}
C {devices/lab_wire.sym} 1170 -320 0 0 {name=p28 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 1170 -440 0 0 {name=p29 sig_type=std_logic lab=VDD}
C {INV3D.sym} 300 -240 0 0 {name=x54[0:94]}
