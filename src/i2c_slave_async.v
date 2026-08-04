// =============================================================================
// i2c_slave_async.v  (v2 -- gate-synthesizable)
//
// Asynchronous (bus-timed, unclocked) I2C slave core, restructured so that
// it maps cleanly onto TR-1um_5_stdcell via Yosys + a custom Liberty file
// (see ../TR1um_5_stdcell.lib, ../logic_cells_mapping.md).
//
// The original single-always-block description (bus_edge-triggered shadow
// registers) simulated fine but Yosys rejected it outright:
//   ERROR: Found non-synthesizable event list!
// (a level-sensitive always block mixing scl/sda_in with negedge rst_n is
// neither a recognized single-clock sequential pattern nor a pure @* block).
//
// This version has no such block. Instead:
//
//   - START/STOP is a genuine unclocked async circuit: a DEL1 delay line
//     creates a lagging copy of SDA, and simple combinational logic detects
//     "SDA moved while SCL was already high" without any register at all
//     (UM10204 3.1.4). A NOR2 cross-coupled SR latch (busy) is SET by
//     start_pulse and CLEARed by stop_pulse/reset.
//   - Everything else is edge-triggered on scl / ~scl -- SCL literally IS
//     the clock, which is the essence of a bus-timed design, and is exactly
//     what DFFR (async-reset D-FF) wants to see on its CK pin.
//   - The phase encoding deliberately puts "collecting an address byte"
//     (PH_ADDR) at the reset value (3'b000), so a START pulse can force the
//     whole SCL-domain register bank back into that state with a single
//     asynchronous RESET (rst_scl_domain = ~rst_n | start_pulse) instead of
//     needing an async SET to an arbitrary pattern, which DFFR cannot do
//     (it has RST only, no SET; DFFS is the opposite -- there is no single
//     cell with both, see logic_cells_mapping.md).
//
// Synthesis (verified in this repo's toolchain):
//   yowasp-yosys -p "
//     read_verilog i2c_slave_async.v
//     hierarchy -top i2c_slave_async -keep_portwidths
//     proc; opt
//     techmap; opt
//     dfflegalize -cell \$_DFF_PP0_ 0
//     dfflibmap -liberty TR1um_5_stdcell.lib
//     abc -liberty TR1um_5_stdcell.lib
//     write_verilog i2c_slave_async_net.v"
// produces a clean netlist: 33 DFFR + a mix of AND2_X1/NAND2-4/NOR2-4/OR2-4/
// MUX2/INV_X1 plus the hand-instantiated DEL1/NOR2 x2/INV_X1 -- no latches,
// no unmapped cells. See i2c_slave_async_net.v and design_notes.md section 8.
//
// Functionally re-verified for this architecture with a matching MyHDL model
// (script/i2c_slave_async_model_v3.py, script/test_v3_positive.py /
// test_v3_negative.py) against the same write/read/wrong-address scenarios
// used throughout this project -- all pass. Re-run i2c_slave_async_tb.v with
// iverilog after any further change (see design_notes.md for why MyHDL alone
// is not sufficient: it caught neither the missing-reset-pulse bug nor the
// wire/always race found earlier in v1).
//
// Open items (see logic_cells_mapping.md / design_notes.md for detail):
//   - DFFR.RST / DFFS.SET are assumed active-HIGH from a partial transistor
//     trace of DFFR.sch, not yet SPICE-confirmed.
//   - Liberty timing (TR1um_5_stdcell.lib) is placeholder/nominal, not
//     characterized -- fine for a functional netlist, not for STA/tapeout.
//   - sda_oe is logic-level open-drain (0 = drive low, released otherwise);
//     the actual pull-down/pad transistor is outside this module's scope.
// =============================================================================

module i2c_slave_async #(
    parameter [6:0] SLAVE_ADDR = 7'h50
) (
    input  wire       VDD, GND,   // needed by the structural DEL1/NOR2/INV_X1 instances
    input  wire       rst_n,      // async reset, active low
    input  wire       scl,        // bus SCL (already deglitched to a clean level)
    input  wire       sda_in,     // sensed SDA line level
    output wire       sda_oe,     // 1 = drive SDA low, 0 = release (Hi-Z)

    input  wire [7:0] tx_data,    // byte to shift out on a master read
    output wire [7:0] rx_data,    // last byte received from master
    output wire       rx_valid,   // high while phase == PH_DATA_WR_ACK
    output wire       addr_match, // this slave was addressed in current xfer
    output wire       rw,         // 0 = master write, 1 = master read
    output wire       busy        // high from START until STOP
);

    localparam [2:0]
        PH_ADDR        = 3'b000,   // == reset value: START can just async-reset here
        PH_ADDR_ACK    = 3'b001,
        PH_DATA_WR     = 3'b010,
        PH_DATA_WR_ACK = 3'b011,
        PH_DATA_RD     = 3'b100,
        PH_DATA_RD_ACK = 3'b101,
        PH_IGNORE      = 3'b110;   // address mismatch / NACK -> wait for STOP

    // ---- START/STOP edge detector: DEL1 delay line, no clock at all -----
    wire sda_d;
    DEL1 u_del_sda (.A(sda_in), .Y(sda_d), .VDD(VDD), .GND(GND));

    wire start_pulse = scl &  sda_d & ~sda_in;   // SDA 1->0 while SCL=1
    wire stop_pulse  = scl & ~sda_d &  sda_in;   // SDA 0->1 while SCL=1

    // ---- busy latch: NOR2 cross-coupled SR latch -------------------------
    wire busy_clr = stop_pulse | ~rst_n;
    wire qn;
    NOR2 u_lat_q  (.A(busy_clr),    .B(qn),   .Y(busy), .VDD(VDD), .GND(GND));
    NOR2 u_lat_qn (.A(start_pulse), .B(busy), .Y(qn),   .VDD(VDD), .GND(GND));

    // ---- SCL(posedge)-domain registers: phase/bit_cnt/shreg/addr/rw ------
    wire rst_scl_domain = (~rst_n) | start_pulse;   // active-high -> DFFR.RST

    reg [2:0] phase;
    reg [3:0] bit_cnt;
    reg [7:0] shreg;
    reg       addr_ok, rw_bit;
    reg [7:0] rx_data_r;

    wire [7:0] shreg_next = {shreg[6:0], sda_in};

    always @(posedge scl or posedge rst_scl_domain) begin
        if (rst_scl_domain) begin
            phase     <= PH_ADDR;
            bit_cnt   <= 4'd0;
            shreg     <= 8'd0;
            addr_ok   <= 1'b0;
            rw_bit    <= 1'b0;
            rx_data_r <= 8'd0;
        end else begin
            shreg <= shreg_next;
            case (phase)
                PH_ADDR: begin
                    if (bit_cnt == 4'd7) begin
                        addr_ok <= (shreg_next[7:1] == SLAVE_ADDR);
                        rw_bit  <= shreg_next[0];
                        phase   <= PH_ADDR_ACK;
                        bit_cnt <= 4'd0;
                    end else bit_cnt <= bit_cnt + 4'd1;
                end
                PH_ADDR_ACK: begin
                    phase   <= addr_ok ? (rw_bit ? PH_DATA_RD : PH_DATA_WR) : PH_IGNORE;
                    bit_cnt <= 4'd0;
                end
                PH_DATA_WR: begin
                    if (bit_cnt == 4'd7) begin
                        rx_data_r <= shreg_next;
                        phase     <= PH_DATA_WR_ACK;
                        bit_cnt   <= 4'd0;
                    end else bit_cnt <= bit_cnt + 4'd1;
                end
                PH_DATA_WR_ACK: begin
                    phase   <= PH_DATA_WR;
                    bit_cnt <= 4'd0;
                end
                PH_DATA_RD: begin
                    if (bit_cnt == 4'd7) phase <= PH_DATA_RD_ACK;
                    bit_cnt <= bit_cnt + 4'd1;
                end
                PH_DATA_RD_ACK: begin
                    phase   <= (sda_in == 1'b0) ? PH_DATA_RD : PH_IGNORE;
                    bit_cnt <= 4'd0;
                end
                default: phase <= PH_IGNORE;
            endcase
        end
    end

    assign addr_match = addr_ok;
    assign rw          = rw_bit;
    assign rx_data      = rx_data_r;
    assign rx_valid      = (phase == PH_DATA_WR_ACK);

    // ---- SCL(negedge)-domain registers: sda_oe/txreg ----------------------
    wire scl_n;
    INV_X1 u_inv_scl (.A(scl), .Y(scl_n), .VDD(VDD), .GND(GND));

    wire rst_sdaoe_domain = (~rst_n) | (~busy);

    reg sda_oe_r;
    reg [7:0] txreg;

    always @(posedge scl_n or posedge rst_sdaoe_domain) begin
        if (rst_sdaoe_domain) begin
            sda_oe_r <= 1'b0;
            txreg    <= 8'd0;
        end else begin
            case (phase)
                PH_ADDR_ACK:    sda_oe_r <= addr_ok;
                PH_DATA_WR_ACK: sda_oe_r <= 1'b1;
                PH_DATA_RD: begin
                    if (bit_cnt == 4'd0) begin
                        txreg    <= tx_data;
                        sda_oe_r <= ~tx_data[7];
                    end else begin
                        sda_oe_r <= ~txreg[7 - bit_cnt];
                    end
                end
                default: sda_oe_r <= 1'b0;
            endcase
        end
    end
    assign sda_oe = sda_oe_r;

endmodule
