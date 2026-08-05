// =============================================================================
// stdcell_behavioral_stubs.v
//
// Purely-behavioral, functional-only Verilog models of the TR1um_5_stdcell
// cells used by i2c_slave_async.v / i2c_slave_async_net.v, for simulation
// ONLY (iverilog/Verilator). These are NOT gate-level models and carry NO
// timing information beyond a single nominal `#1` delay per cell -- do not
// use them for anything but functional (logic-correctness) simulation.
//
// Function/pin directions taken from the xschem symbol library
// (~/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_5_stdcell, .sym
// dir=in/out/inout) -- see logic_cells_mapping.md.
//
// DFFR/DFFS RST/SET polarity is modeled active-HIGH per the partial
// transistor trace of DFFR.sch documented in design_notes.md /
// logic_cells_mapping.md. This is NOT yet SPICE-confirmed; if it turns out
// to be active-LOW in silicon, invert the DFFR.RST connection at the call
// site (i2c_slave_async.v) and re-simulate, no change needed here.
//
// Only the cells actually instantiated by this project are included:
// INV_X1, DEL1, NOR2, NOR3, NOR4, NAND2, NAND3, NAND4, AND2_X1, OR2, OR3,
// OR4, MUX2, DFFR. Add more here (matching TR1um_5_stdcell.lib) if future
// synthesis runs pull in others (BUF_X*, XOR2, XNOR2, DFFS, ...).
// =============================================================================
`timescale 1ns/1ps

module INV_X1 (input A, output Y, input VDD, input GND);
    assign #1 Y = ~A;
endmodule

// DEL1/2/4 delay must be comfortably larger than a single NOR2/NAND2 gate
// delay (#1 below), NOT roughly equal to it. i2c_slave_async.v generates
// start_pulse/stop_pulse as a one-shot of width == this delay, which then
// has to propagate around the busy latch's own NOR2-NOR2 regenerative loop
// (u_lat_qn -> u_lat_q, 2 gate delays) before the SET/RESET has fully taken
// hold. A pulse only as wide as one downstream gate delay is a genuine
// hazard: it was originally modeled here as #1 (== the NOR2 delay), and
// iverilog simulation showed the SET pulse gets swallowed/raced away
// entirely -- `busy` never asserts, which silently holds the whole
// scl_n-domain register bank (sda_oe/txreg) in permanent reset for the rest
// of the transaction (see design_notes.md section 7.6). Widened to #4 here
// (4x the NOR2 delay) to give reliable margin; re-confirmed against
// i2c_slave_async_tb.v after the change (see section 7.6 for the full
// failure signature this fixes). This margin requirement is a real
// constraint on the physical DEL1-vs-NOR2 timing relationship, not just a
// simulation artifact -- re-verify once TR1um_5_stdcell.lib carries real
// SPICE-characterized delays.
module DEL1 (input A, output Y, input VDD, input GND);
    assign #4 Y = A;
endmodule

module DEL2 (input A, output Y, input VDD, input GND);
    assign #8 Y = A;
endmodule

module DEL4 (input A, output Y, input VDD, input GND);
    assign #16 Y = A;
endmodule

module NOR2 (input A, B, output Y, input VDD, input GND);
    assign #1 Y = ~(A | B);
endmodule

module NOR3 (input A, B, C, output Y, input VDD, input GND);
    assign #1 Y = ~(A | B | C);
endmodule

module NOR4 (input A, B, C, D, output Y, input VDD, input GND);
    assign #1 Y = ~(A | B | C | D);
endmodule

module NAND2 (input A, B, output Y, input VDD, input GND);
    assign #1 Y = ~(A & B);
endmodule

module NAND3 (input A, B, C, output Y, input VDD, input GND);
    assign #1 Y = ~(A & B & C);
endmodule

module NAND4 (input A, B, C, D, output Y, input VDD, input GND);
    assign #1 Y = ~(A & B & C & D);
endmodule

module AND2_X1 (input A, B, output Y, input VDD, input GND);
    assign #1 Y = A & B;
endmodule

module AND3_X1 (input A, B, C, output Y, input VDD, input GND);
    assign #1 Y = A & B & C;
endmodule

module AND4_X1 (input A, B, C, D, output Y, input VDD, input GND);
    assign #1 Y = A & B & C & D;
endmodule

module OR2 (input A, B, output Y, input VDD, input GND);
    assign #1 Y = A | B;
endmodule

module OR3 (input A, B, C, output Y, input VDD, input GND);
    assign #1 Y = A | B | C;
endmodule

module OR4 (input A, B, C, D, output Y, input VDD, input GND);
    assign #1 Y = A | B | C | D;
endmodule

module XOR2 (input A, B, output Y, input VDD, input GND);
    assign #1 Y = A ^ B;
endmodule

module XNOR2 (input A, B, output Y, input VDD, input GND);
    assign #1 Y = ~(A ^ B);
endmodule

module BUF_X1 (input A, output Y, input VDD, input GND);
    assign #1 Y = A;
endmodule

// BUF_X2/X4/X8/X16: added for the SCL/SDA-input and rst_scl_domain (net
// _126_) staged buffer-chain insertion (design_notes.md section 18). Same
// placeholder #1 nominal delay as every other stub in this file -- these
// are functional-only models, not real characterized buffer delays (a real
// BUF_X16 is faster than a BUF_X2 under the same load, but that distinction
// isn't modeled here; see the file header).
module BUF_X2 (input A, output Y, input VDD, input GND);
    assign #1 Y = A;
endmodule

module BUF_X4 (input A, output Y, input VDD, input GND);
    assign #1 Y = A;
endmodule

module BUF_X8 (input A, output Y, input VDD, input GND);
    assign #1 Y = A;
endmodule

module BUF_X16 (input A, output Y, input VDD, input GND);
    assign #1 Y = A;
endmodule

module MUX2 (input A, B, S, output Y, input VDD, input GND);
    assign #1 Y = S ? B : A;
endmodule

// Async-reset D flip-flop, RST active-HIGH (see header note on polarity).
module DFFR (input CK, D, RST, output reg Q, output QB, input VDD, input GND);
    assign #1 QB = ~Q;
    always @(posedge CK or posedge RST)
        if (RST) Q <= 1'b0;
        else     Q <= D;
endmodule

// Async-set D flip-flop, SET active-HIGH (unused by the current design but
// included for completeness / future use).
module DFFS (input CK, D, SET, output reg Q, output QB, input VDD, input GND);
    assign #1 QB = ~Q;
    always @(posedge CK or posedge SET)
        if (SET) Q <= 1'b1;
        else     Q <= D;
endmodule
