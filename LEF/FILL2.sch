v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 190 -290 190 -270 {
lab=VDD}
N 140 -270 190 -270 {
lab=VDD}
N 140 -290 140 -270 {
lab=VDD}
N 140 -170 140 -150 {
lab=GND}
N 90 -150 140 -150 {
lab=GND}
N 90 -170 90 -150 {
lab=GND}
N 80 -170 90 -170 {
lab=GND}
N 190 -290 200 -290 {
lab=VDD}
N 170 -290 190 -290 {
lab=VDD}
N 90 -170 110 -170 {
lab=GND}
N 170 -170 170 -150 {lab=GND}
N 140 -150 170 -150 {lab=GND}
N 110 -290 110 -270 {lab=VDD}
N 110 -270 140 -270 {lab=VDD}
N 90 -330 90 -170 {lab=GND}
N 90 -330 140 -330 {lab=GND}
N 140 -210 190 -210 {lab=VDD}
N 190 -270 190 -210 {lab=VDD}
C {devices/iopin.sym} 80 -170 2 0 {name=p3 lab=GND}
C {devices/iopin.sym} 200 -290 0 0 {name=p4 lab=VDD}
C {MP.sym} 140 -330 1 0 {name=M7 model=PMOS w=21.2u l=3.2u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
C {MN.sym} 140 -210 1 0 {name=M2 model=NMOS w=13.1u l=3.2u m=1 as=0 ad=0 ps=0 pd=0 nrd=0 nrs=0 spiceprefix=X}
