// =============================================================================
// i2c_slave_async.v
//
// Asynchronous (bus-timed, unclocked) I2C slave core.
//
// There is NO free-running system clock anywhere in this module. Every state
// change is triggered directly by an edge on SCL or SDA, exactly as the
// protocol itself is defined in NXP UM10204 ("I2C-bus specification and user
// manual", Rev. 5.0J):
//
//   3.1.3 Data validity   : SDA may change only while SCL = LOW; SDA must be
//                           stable while SCL = HIGH.
//                             -> sample bits when SCL rises
//                             -> drive  bits when SCL falls
//   3.1.4 START/STOP      : a HIGH->LOW transition of SDA while SCL = HIGH is
//                           START; LOW->HIGH while SCL = HIGH is STOP.
//   3.1.5 Byte format     : 8 bits, MSB first, one ACK/NACK bit per byte.
//   3.1.6 ACK/NACK        : receiver pulls SDA low during the 9th clock.
//   3.1.9 Clock stretch   : optional; NOT implemented here (this slave never
//                           drives SCL). See design_notes.md if you need it.
//
// Implementation note on "asynchronous" style
// ---------------------------------------------
// All state is kept in a single always block sensitive to *level changes* of
// scl and sda_in (plus async reset) -- there is no separate always block per
// edge, which would otherwise give every register more than one driver (an
// illegal / non-synthesizable construct). Instead this block keeps one-cycle
// shadow copies of the bus lines (scl_q, sda_q) and derives START/STOP and
// SCL-posedge/negedge purely combinationally from "old vs new" level, i.e.
// exactly the behavior of a small set of transparent latches / an SR latch
// gated by the bus itself (UM10204 Fig. 5), described at the RTL level.
//
// Functionally verified against a bus-functional master model in
// test_i2c_slave_async.py (MyHDL) -- see i2c_slave_async_model.py, which
// implements the identical state machine and was simulated because no
// Verilog simulator (iverilog/Verilator) was available in the build
// sandbox. Re-verify this file with i2c_slave_async_tb.v before relying on
// it in silicon/FPGA.
//
// SDA is modeled as an open-drain pad: this module only ever asserts LOW
// (sda_oe=1) or releases (sda_oe=0); the external pull-up (or the bus master)
// is responsible for the HIGH level.
// =============================================================================

module i2c_slave_async #(
    parameter [6:0] SLAVE_ADDR = 7'h50
) (
    input  wire       rst_n,      // async reset, active low
    input  wire       scl,        // bus SCL (already deglitched to a clean level)
    input  wire       sda_in,     // sensed SDA line level
    output reg        sda_oe,     // 1 = drive SDA low, 0 = release (Hi-Z)

    input  wire [7:0] tx_data,    // byte to shift out on a master read
    output reg  [7:0] rx_data,    // last byte received from master
    output reg        rx_valid,   // pulses (~1 SCL HIGH phase) when rx_data is new
    output wire       addr_match, // this slave was addressed in current xfer
    output wire       rw,         // 0 = master write, 1 = master read
    output reg        busy        // high from START until STOP
);

    // ---------------------------------------------------------------------
    // State encoding
    // ---------------------------------------------------------------------
    localparam [2:0] IDLE        = 3'd0,
                      ADDR        = 3'd1,
                      ADDR_ACK    = 3'd2,
                      DATA_WR     = 3'd3,
                      DATA_WR_ACK = 3'd4,
                      DATA_RD     = 3'd5,
                      DATA_RD_ACK = 3'd6;

    reg [2:0] state;
    reg [3:0] bit_cnt;
    reg [7:0] shreg;      // address/data shift-in register
    reg [7:0] txreg;      // data shift-out register
    reg       addr_ok;
    reg       rw_bit;

    reg       scl_q, sda_q;   // shadow copies -> used only to derive edges
    reg [7:0] shreg_next;     // scratch: shift-in result for the current bit

    assign addr_match = addr_ok;
    assign rw          = rw_bit;

    wire start_cond = scl_q & scl & sda_q & ~sda_in; // SDA 1->0 while SCL=1
    wire stop_cond  = scl_q & scl & ~sda_q & sda_in; // SDA 0->1 while SCL=1
    wire scl_rise   = ~scl_q & scl;
    wire scl_fall   = scl_q & ~scl;

    always @(scl or sda_in or negedge rst_n) begin
        if (!rst_n) begin
            state    <= IDLE;
            bit_cnt  <= 4'd0;
            sda_oe   <= 1'b0;
            busy     <= 1'b0;
            rx_valid <= 1'b0;
            scl_q    <= 1'b1;
            sda_q    <= 1'b1;
        end else begin
            rx_valid <= 1'b0;   // default; overridden below when a byte lands

            if (start_cond) begin
                // ---- START condition (3.1.4) --------------------------
                state   <= ADDR;
                bit_cnt <= 4'd0;
                busy    <= 1'b1;
                sda_oe  <= 1'b0;

            end else if (stop_cond) begin
                // ---- STOP condition (3.1.4) ----------------------------
                state  <= IDLE;
                sda_oe <= 1'b0;
                busy   <= 1'b0;

            end else if (scl_rise) begin
                // ---- sample bit / decide next state (3.1.3, 3.1.5/6) ---
                shreg_next = {shreg[6:0], sda_in};
                case (state)
                    ADDR: begin
                        shreg <= shreg_next;
                        if (bit_cnt == 4'd7) begin
                            addr_ok <= (shreg_next[7:1] == SLAVE_ADDR);
                            rw_bit  <= shreg_next[0];
                            state   <= ADDR_ACK;
                            bit_cnt <= 4'd0;
                        end else begin
                            bit_cnt <= bit_cnt + 4'd1;
                        end
                    end

                    ADDR_ACK: begin
                        if (addr_ok)
                            state <= rw_bit ? DATA_RD : DATA_WR;
                        else
                            state <= IDLE;
                        bit_cnt <= 4'd0;
                    end

                    DATA_WR: begin
                        shreg <= shreg_next;
                        if (bit_cnt == 4'd7) begin
                            rx_data  <= shreg_next;
                            rx_valid <= 1'b1;
                            state    <= DATA_WR_ACK;
                            bit_cnt  <= 4'd0;
                        end else begin
                            bit_cnt <= bit_cnt + 4'd1;
                        end
                    end

                    DATA_WR_ACK: begin
                        state   <= DATA_WR;
                        bit_cnt <= 4'd0;
                    end

                    DATA_RD: begin
                        if (bit_cnt == 4'd7)
                            state <= DATA_RD_ACK;
                        bit_cnt <= bit_cnt + 4'd1;
                    end

                    DATA_RD_ACK: begin
                        if (sda_in == 1'b0) begin  // master ACK -> more data
                            state   <= DATA_RD;
                            bit_cnt <= 4'd0;
                        end else begin             // master NACK -> done
                            state <= IDLE;
                        end
                    end

                    default: state <= IDLE;
                endcase

            end else if (scl_fall) begin
                // ---- drive next output bit (3.1.3, 3.1.6) --------------
                case (state)
                    ADDR:        sda_oe <= 1'b0;
                    ADDR_ACK:    sda_oe <= addr_ok;
                    DATA_WR:     sda_oe <= 1'b0;
                    DATA_WR_ACK: sda_oe <= 1'b1;   // always ACK a written byte
                    DATA_RD: begin
                        if (bit_cnt == 4'd0) begin
                            txreg  <= tx_data;
                            sda_oe <= ~tx_data[7];
                        end else begin
                            sda_oe <= ~txreg[7 - bit_cnt];
                        end
                    end
                    DATA_RD_ACK: sda_oe <= 1'b0;
                    default:     sda_oe <= 1'b0;
                endcase
            end

            scl_q <= scl;
            sda_q <= sda_in;
        end
    end

endmodule
