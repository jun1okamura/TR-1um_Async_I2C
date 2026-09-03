v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 570 -280 580 -280 {lab=QB}
N 330 -540 380 -540 {lab=R}
N 400 -460 430 -460 {lab=VSS}
N 430 -340 460 -340 {lab=VDD}
N 510 -520 580 -520 {lab=Q}
N 510 -280 570 -280 {lab=QB}
N 350 -500 350 -420 {lab=QB}
N 550 -380 550 -280 {lab=QB}
N 550 -520 550 -420 {lab=Q}
N 330 -300 380 -300 {lab=S}
N 350 -260 380 -260 {lab=Q}
N 350 -270 350 -260 {lab=Q}
N 350 -380 350 -270 {lab=Q}
N 350 -500 380 -500 {lab=QB}
N 350 -420 550 -380 {lab=QB}
N 350 -380 550 -420 {lab=Q}
C {devices/ipin.sym} 330 -540 0 0 {name=p1 lab=R}
C {devices/ipin.sym} 330 -300 0 0 {name=p2 lab=S}
C {devices/opin.sym} 580 -520 0 0 {name=p4 lab=Q}
C {devices/opin.sym} 580 -280 0 0 {name=p5 lab=QB}
C {devices/iopin.sym} 430 -580 0 0 {name=p6 lab=VDD}
C {devices/iopin.sym} 430 -220 2 0 {name=p7 lab=VSS}
C {devices/title.sym} 160 0 0 0 {name=l1 author="Stefan Schippers"}
C {devices/lab_wire.sym} 420 -460 0 0 {name=p3 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 460 -340 0 0 {name=p8 sig_type=std_logic lab=VDD}
C {./NOR2.sym} 400 -520 0 0 {name=x1}
C {./NOR2.sym} 400 -280 0 0 {name=x2}
