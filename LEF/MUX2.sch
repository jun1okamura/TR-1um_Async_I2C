v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 590 -280 620 -280 {
lab=VDD}
N 590 -310 620 -310 {
lab=VDD}
N 590 -120 620 -120 {
lab=GND}
N 540 -280 550 -280 {
lab=S}
N 540 -280 540 -120 {
lab=S}
N 540 -120 550 -120 {
lab=S}
N 590 -250 590 -150 {
lab=SB}
N 440 -480 630 -480 {
lab=Y}
N 590 -200 620 -200 {lab=SB}
N 590 -340 590 -310 {lab=VDD}
N 620 -310 620 -280 {lab=VDD}
N 590 -90 620 -90 {lab=GND}
N 620 -120 620 -90 {lab=GND}
N 590 -90 590 -60 {lab=GND}
N 150 -400 180 -400 {
lab=VDD}
N 150 -430 180 -430 {
lab=VDD}
N 150 -240 180 -240 {
lab=GND}
N 100 -400 110 -400 {
lab=B}
N 100 -400 100 -240 {
lab=B}
N 100 -240 110 -240 {
lab=B}
N 150 -370 150 -270 {
lab=#net1}
N 150 -320 180 -320 {lab=#net1}
N 150 -460 150 -430 {lab=VDD}
N 180 -430 180 -400 {lab=VDD}
N 150 -210 180 -210 {lab=GND}
N 180 -240 180 -210 {lab=GND}
N 150 -210 150 -180 {lab=GND}
N 150 -720 180 -720 {
lab=VDD}
N 150 -750 180 -750 {
lab=VDD}
N 150 -560 180 -560 {
lab=GND}
N 100 -720 110 -720 {
lab=A}
N 100 -720 100 -560 {
lab=A}
N 100 -560 110 -560 {
lab=A}
N 150 -690 150 -590 {
lab=#net2}
N 150 -640 180 -640 {lab=#net2}
N 150 -780 150 -750 {lab=VDD}
N 180 -750 180 -720 {lab=VDD}
N 150 -530 180 -530 {lab=GND}
N 180 -560 180 -530 {lab=GND}
N 150 -530 150 -500 {lab=GND}
N 340 -680 360 -680 {lab=#net3}
N 340 -600 360 -600 {lab=#net3}
N 360 -680 360 -600 {lab=#net3}
N 260 -600 280 -600 {lab=#net2}
N 260 -610 260 -600 {lab=#net2}
N 260 -680 280 -680 {lab=#net2}
N 260 -680 260 -670 {lab=#net2}
N 260 -670 260 -610 {lab=#net2}
N 180 -640 260 -640 {lab=#net2}
N 340 -360 360 -360 {lab=#net3}
N 340 -280 360 -280 {lab=#net3}
N 360 -360 360 -280 {lab=#net3}
N 260 -280 280 -280 {lab=#net1}
N 260 -290 260 -280 {lab=#net1}
N 260 -360 280 -360 {lab=#net1}
N 260 -360 260 -350 {lab=#net1}
N 260 -350 260 -290 {lab=#net1}
N 180 -320 260 -320 {lab=#net1}
N 430 -560 460 -560 {
lab=VDD}
N 430 -590 460 -590 {
lab=VDD}
N 430 -400 460 -400 {
lab=GND}
N 380 -560 390 -560 {
lab=#net3}
N 380 -560 380 -400 {
lab=#net3}
N 380 -400 390 -400 {
lab=#net3}
N 430 -530 430 -430 {
lab=Y}
N 430 -620 430 -590 {lab=VDD}
N 460 -590 460 -560 {lab=VDD}
N 430 -370 460 -370 {lab=GND}
N 460 -400 460 -370 {lab=GND}
N 430 -370 430 -340 {lab=GND}
N 360 -640 380 -640 {lab=#net3}
N 380 -640 380 -560 {lab=#net3}
N 360 -320 380 -320 {lab=#net3}
N 380 -400 380 -320 {lab=#net3}
N 310 -560 310 -400 {lab=SB}
N 430 -480 440 -480 {lab=Y}
C {devices/ipin.sym} 540 -200 0 0 {name=p2 lab=S}
C {devices/opin.sym} 630 -480 0 0 {name=p3 lab=Y}
C {devices/iopin.sym} 430 -620 0 0 {name=p4 lab=VDD}
C {devices/iopin.sym} 430 -340 0 0 {name=p5 lab=GND}
C {MP.sym} 550 -280 0 0 {name=M13 model=PMOS w=6.8u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MP.sym} 310 -720 1 0 {name=M8 model=PMOS w=6.8u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 550 -120 0 0 {name=M12 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 310 -560 3 0 {name=M6 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {devices/lab_wire.sym} 620 -200 0 0 {name=p7 sig_type=std_logic lab=SB}
C {devices/lab_wire.sym} 590 -340 0 0 {name=p8 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 590 -60 0 0 {name=p9 sig_type=std_logic lab=GND}
C {devices/ipin.sym} 100 -320 0 0 {name=p10 lab=B}
C {MP.sym} 110 -400 0 0 {name=M11 model=PMOS w=6.8u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 110 -240 0 0 {name=M14 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {devices/lab_wire.sym} 150 -460 0 0 {name=p12 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 150 -180 0 0 {name=p13 sig_type=std_logic lab=GND}
C {devices/ipin.sym} 100 -640 0 0 {name=p14 lab=A}
C {MP.sym} 110 -720 0 0 {name=M15 model=PMOS w=6.8u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 110 -560 0 0 {name=M16 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {devices/lab_wire.sym} 150 -780 0 0 {name=p16 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 150 -500 0 0 {name=p17 sig_type=std_logic lab=GND}
C {devices/lab_wire.sym} 310 -680 1 1 {name=p11 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 310 -600 1 0 {name=p15 sig_type=std_logic lab=GND}
C {MP.sym} 310 -400 1 0 {name=M3 model=PMOS w=6.8u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 310 -240 3 0 {name=M5 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {devices/lab_wire.sym} 310 -360 1 1 {name=p18 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 310 -280 1 0 {name=p19 sig_type=std_logic lab=GND}
C {MP.sym} 390 -560 0 0 {name=M1 model=PMOS w=11.2u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 390 -400 0 0 {name=M2 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {devices/lab_wire.sym} 310 -480 0 0 {name=p6 sig_type=std_logic lab=SB}
C {devices/lab_wire.sym} 310 -240 2 1 {name=p20 sig_type=std_logic lab=S}
C {devices/lab_wire.sym} 310 -720 0 0 {name=p21 sig_type=std_logic lab=S}
