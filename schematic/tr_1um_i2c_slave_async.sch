v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 340 -600 370 -600 {lab=VDD}
N 340 -580 370 -580 {lab=RSTN}
N 340 -560 370 -560 {lab=IN7}
N 340 -540 370 -540 {lab=SDA}
N 340 -520 370 -520 {lab=IN0}
N 340 -500 370 -500 {lab=IN1}
N 340 -440 370 -440 {lab=NET_5}
N 340 -400 370 -400 {lab=NET_6}
N 340 -380 370 -380 {lab=NET_4}
N 340 -360 370 -360 {lab=NET_2}
N 340 -340 370 -340 {lab=NET_3}
N 340 -260 370 -260 {lab=NET_1}
N 340 -240 370 -240 {lab=NET_0}
N 340 -220 370 -220 {lab=VSS}
N 340 -200 370 -200 {lab=NET_7}
N 190 -600 220 -600 {lab=IN5}
N 190 -580 220 -580 {lab=SCL}
N 190 -560 220 -560 {lab=IN6}
N 190 -540 220 -540 {lab=IN4}
N 190 -520 220 -520 {lab=IN2}
N 190 -500 220 -500 {lab=IN3}
N 190 -480 220 -480 {lab=DIS}
N 190 -460 220 -460 {lab=VSS}
N 190 -440 220 -440 {lab=DIS}
N 190 -420 220 -420 {lab=VDD}
N 190 -400 220 -400 {lab=DIS}
N 190 -380 220 -380 {lab=DIS}
N 190 -360 220 -360 {lab=DIS}
N 190 -340 220 -340 {lab=DIS}
N 190 -320 220 -320 {lab=VDD}
N 190 -300 220 -300 {lab=VSS}
N 190 -280 220 -280 {lab=VSS}
N 190 -260 220 -260 {lab=DIS}
N 190 -240 220 -240 {lab=DIS}
N 190 -600 220 -600 {lab=IN5}
N 190 -220 220 -220 {lab=SDA_O}
N 190 -200 220 -200 {lab=DIS}
N 190 -180 220 -180 {lab=VDD}
N 580 -500 610 -500 {lab=#net1}
N 580 -480 610 -480 {lab=#net2}
N 580 -460 610 -460 {lab=#net3}
N 580 -440 610 -440 {lab=#net4}
N 580 -420 610 -420 {lab=#net5}
N 580 -400 610 -400 {lab=#net6}
N 580 -380 610 -380 {lab=#net7}
N 580 -360 610 -360 {lab=#net8}
N 580 -340 610 -340 {lab=#net9}
N 580 -320 610 -320 {lab=#net10}
N 580 -300 610 -300 {lab=#net11}
N 950 -520 980 -520 {lab=#net12}
N 580 -500 610 -500 {lab=#net1}
N 950 -500 980 -500 {lab=#net13}
N 950 -480 980 -480 {lab=#net14}
N 950 -460 980 -460 {lab=#net15}
N 950 -440 980 -440 {lab=#net16}
N 950 -420 980 -420 {lab=#net17}
N 950 -400 980 -400 {lab=#net18}
N 950 -380 980 -380 {lab=#net19}
N 950 -360 980 -360 {lab=#net20}
C {schematic/i2c_slave_async_nrow_fm.sym} 780 -400 0 0 {name=x2}
C {devices/lab_wire.sym} 220 -600 0 0 {name=p1 sig_type=std_logic lab=IN5}
C {devices/lab_wire.sym} 620 -480 0 0 {name=p2 sig_type=std_logic lab=SCL}
C {devices/lab_wire.sym} 220 -580 0 0 {name=p3 sig_type=std_logic lab=SCL}
C {devices/lab_wire.sym} 620 -460 0 0 {name=p4 sig_type=std_logic lab=SDA}
C {devices/lab_wire.sym} 940 -520 0 1 {name=p7 sig_type=std_logic lab=SDA_O}
C {devices/lab_wire.sym} 940 -500 0 1 {name=p8 sig_type=std_logic lab=NET_0}
C {devices/lab_wire.sym} 940 -480 0 1 {name=p9 sig_type=std_logic lab=NET_1}
C {devices/lab_wire.sym} 940 -460 0 1 {name=p10 sig_type=std_logic lab=NET_2}
C {devices/lab_wire.sym} 940 -440 0 1 {name=p11 sig_type=std_logic lab=NET_3}
C {devices/lab_wire.sym} 940 -420 0 1 {name=p12 sig_type=std_logic lab=NET_4}
C {devices/lab_wire.sym} 940 -400 0 1 {name=p13 sig_type=std_logic lab=NET_5}
C {devices/lab_wire.sym} 940 -380 0 1 {name=p14 sig_type=std_logic lab=NET_6}
C {devices/lab_wire.sym} 940 -360 0 1 {name=p15 sig_type=std_logic lab=NET_7}
C {devices/lab_wire.sym} 220 -560 0 0 {name=p16 sig_type=std_logic lab=IN6}
C {devices/lab_wire.sym} 220 -540 0 0 {name=p17 sig_type=std_logic lab=IN4}
C {devices/lab_wire.sym} 220 -520 0 0 {name=p18 sig_type=std_logic lab=IN2}
C {devices/lab_wire.sym} 220 -500 0 0 {name=p19 sig_type=std_logic lab=IN3}
C {devices/lab_wire.sym} 340 -580 0 1 {name=p21 sig_type=std_logic lab=RSTN}
C {devices/lab_wire.sym} 340 -560 0 1 {name=p22 sig_type=std_logic lab=IN7}
C {devices/lab_wire.sym} 340 -540 0 1 {name=p23 sig_type=std_logic lab=SDA}
C {devices/lab_wire.sym} 340 -520 0 1 {name=p24 sig_type=std_logic lab=IN0}
C {devices/lab_wire.sym} 340 -600 0 1 {name=p25 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 620 -500 0 0 {name=p26 sig_type=std_logic lab=RSTN}
C {devices/lab_wire.sym} 620 -440 0 0 {name=p27 sig_type=std_logic lab=IN0}
C {devices/lab_wire.sym} 620 -420 0 0 {name=p28 sig_type=std_logic lab=IN1}
C {devices/lab_wire.sym} 620 -400 0 0 {name=p29 sig_type=std_logic lab=IN2}
C {devices/lab_wire.sym} 620 -380 0 0 {name=p30 sig_type=std_logic lab=IN3}
C {devices/lab_wire.sym} 620 -360 0 0 {name=p31 sig_type=std_logic lab=IN4}
C {devices/lab_wire.sym} 620 -340 0 0 {name=p32 sig_type=std_logic lab=IN5}
C {devices/lab_wire.sym} 620 -320 0 0 {name=p33 sig_type=std_logic lab=IN6}
C {devices/lab_wire.sym} 620 -300 0 0 {name=p34 sig_type=std_logic lab=IN7}
C {devices/lab_wire.sym} 340 -400 0 1 {name=p35 sig_type=std_logic lab=NET_6}
C {devices/lab_wire.sym} 340 -380 0 1 {name=p36 sig_type=std_logic lab=NET_4}
C {devices/lab_wire.sym} 340 -360 0 1 {name=p37 sig_type=std_logic lab=NET_2}
C {devices/lab_wire.sym} 340 -340 0 1 {name=p38 sig_type=std_logic lab=NET_3}
C {devices/lab_wire.sym} 340 -200 0 1 {name=p40 sig_type=std_logic lab=NET_7}
C {devices/lab_wire.sym} 340 -240 0 1 {name=p42 sig_type=std_logic lab=NET_0}
C {devices/lab_wire.sym} 340 -500 0 1 {name=p43 sig_type=std_logic lab=IN1}
C {devices/lab_wire.sym} 220 -400 0 0 {name=p44 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -380 0 0 {name=p45 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -360 0 0 {name=p46 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -340 0 0 {name=p47 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -240 0 0 {name=p48 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -220 0 0 {name=p49 sig_type=std_logic lab=SDA_O}
C {devices/lab_wire.sym} 220 -200 0 0 {name=p50 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -320 0 0 {name=p54 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 220 -300 0 0 {name=p55 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 220 -280 0 0 {name=p56 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 220 -460 0 0 {name=p57 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 340 -440 0 1 {name=p58 sig_type=std_logic lab=NET_5}
C {devices/lab_wire.sym} 340 -260 0 1 {name=p59 sig_type=std_logic lab=NET_1}
C {devices/lab_wire.sym} 220 -480 0 0 {name=p60 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 340 -220 0 1 {name=p61 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 220 -420 0 0 {name=p6 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 220 -260 0 0 {name=p20 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -440 0 0 {name=p5 sig_type=std_logic lab=DIS}
C {devices/lab_wire.sym} 220 -180 0 0 {name=p39 sig_type=std_logic lab=VDD}
C {OSS_FRAME_GIO.sym} 280 -530 0 0 {name=x1}
C {devices/lab_wire.sym} 780 -560 0 1 {name=p41 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 780 -240 0 0 {name=p51 sig_type=std_logic lab=VSS}
C {devices/title.sym} 160 0 0 0 {name=l1 author="Stefan Schippers"}
