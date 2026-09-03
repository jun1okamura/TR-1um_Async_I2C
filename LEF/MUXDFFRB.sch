v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 420 -310 480 -310 {lab=#net1}
N 390 -370 390 -350 {lab=VDD}
N 390 -370 410 -370 {lab=VDD}
N 410 -370 480 -370 {lab=VDD}
N 480 -370 480 -340 {lab=VDD}
N 390 -270 390 -200 {lab=VSS}
N 390 -200 440 -200 {lab=VSS}
N 440 -200 480 -200 {lab=VSS}
N 480 -220 480 -200 {lab=VSS}
N 370 -270 370 -250 {lab=S}
N 540 -310 550 -310 {lab=Q}
N 540 -270 550 -270 {lab=QB}
N 510 -240 510 -220 {lab=RSTB}
C {./DFFRB.sym} 510 -280 0 0 {name=x1}
C {./MUX2.sym} 350 -310 0 0 {name=x2}
C {devices/ipin.sym} 330 -330 0 0 {name=p1 lab=A}
C {devices/ipin.sym} 330 -290 0 0 {name=p2 lab=B}
C {devices/ipin.sym} 480 -270 0 0 {name=p3 lab=CK}
C {devices/opin.sym} 550 -310 0 0 {name=p4 lab=Q}
C {devices/opin.sym} 550 -270 0 0 {name=p5 lab=QB}
C {devices/iopin.sym} 480 -370 0 0 {name=p6 lab=VDD}
C {devices/iopin.sym} 390 -200 1 0 {name=p7 lab=VSS}
C {devices/ipin.sym} 370 -250 1 1 {name=p8 lab=S}
C {devices/title.sym} 160 0 0 0 {name=l1 author="Stefan Schippers"}
C {devices/ipin.sym} 510 -220 1 1 {name=p9 lab=RSTB}
