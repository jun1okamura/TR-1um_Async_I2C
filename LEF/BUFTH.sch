v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 430 -260 450 -260 {
lab=VDD}
N 430 -160 450 -160 {
lab=VDD}
N 430 -60 450 -60 {
lab=GND}
N 450 -60 450 -10 {
lab=GND}
N 380 -60 390 -60 {
lab=MID}
N 430 -30 430 0 {
lab=GND}
N 380 -160 390 -160 {
lab=MID}
N 380 -160 380 -60 {
lab=MID}
N 450 -210 450 -160 {
lab=VDD}
N 430 -220 430 -190 {
lab=VDD}
N 430 -110 480 -110 {
lab=Y}
N 330 -110 380 -110 {
lab=MID}
N 320 -260 470 -260 {
lab=VDD}
N 430 -130 430 -90 {
lab=Y}
N 110 -110 160 -110 {
lab=MID}
N 110 -130 110 -90 {
lab=MID}
N 110 -160 130 -160 {
lab=VDD}
N 110 -60 130 -60 {
lab=GND}
N 60 -160 70 -160 {
lab=A}
N 60 -160 60 -60 {
lab=A}
N 60 -60 70 -60 {
lab=A}
N 30 -110 60 -110 {
lab=A}
N 160 -110 220 -110 {lab=MID}
N 220 -150 220 -80 {lab=MID}
N 60 -220 60 -160 {lab=A}
N 60 -220 70 -220 {lab=A}
N 60 -60 60 0 {lab=A}
N 110 -260 320 -260 {lab=VDD}
N 110 -260 110 -250 {lab=VDD}
N 110 -190 190 -190 {lab=#net1}
N 220 -260 220 -190 {lab=VDD}
N 110 30 110 40 {lab=GND}
N 110 40 120 40 {lab=GND}
N 120 40 320 40 {lab=GND}
N 110 -30 190 -30 {lab=#net2}
N 220 -30 220 40 {lab=GND}
N 220 -80 220 -70 {lab=MID}
N 130 -60 130 40 {lab=GND}
N 110 -0 130 -0 {lab=GND}
N 130 -260 130 -160 {lab=VDD}
N 110 -220 130 -220 {lab=VDD}
N 470 -260 480 -260 {lab=VDD}
N 320 40 480 40 {lab=GND}
N 430 -260 430 -220 {lab=VDD}
N 450 -260 450 -210 {lab=VDD}
N 450 -10 450 40 {lab=GND}
N 430 0 430 40 {lab=GND}
N 220 -110 330 -110 {lab=MID}
N 250 -190 260 -190 {lab=GND}
N 260 -190 280 -190 {lab=GND}
N 250 -30 280 -30 {lab=VDD}
N 280 -30 320 -190 {lab=VDD}
N 280 -190 320 -30 {lab=GND}
N 320 -30 320 40 {lab=GND}
N 320 -260 320 -190 {lab=VDD}
N 60 0 70 0 {lab=A}
C {devices/ipin.sym} 30 -110 0 0 {name=p1 lab=A}
C {devices/opin.sym} 480 -110 0 0 {name=p2 lab=Y}
C {devices/iopin.sym} 480 -260 0 0 {name=p3 lab=VDD}
C {devices/iopin.sym} 480 40 0 0 {name=p5 lab=GND}
C {MP.sym} 70 -160 0 0 {name=M9 model=PMOS w=5.1u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MP.sym} 390 -160 0 0 {name=M2 model=PMOS w=10.2u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 70 -60 0 0 {name=M8 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 390 -60 0 0 {name=M1 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MP.sym} 220 -150 3 0 {name=M6 model=PMOS w=10.2u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 220 -70 1 0 {name=M3 model=NMOS w=6.8u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 70 0 0 0 {name=M5 model=NMOS w=3.4u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MP.sym} 70 -220 0 0 {name=M4 model=PMOS w=5.1u l=1u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {devices/lab_wire.sym} 270 -110 0 0 {name=p4 sig_type=std_logic lab=MID}
