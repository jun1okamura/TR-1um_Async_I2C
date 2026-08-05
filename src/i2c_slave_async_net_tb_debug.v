// =============================================================================
// i2c_slave_async_net_tb_debug.v
//
// DIAGNOSTIC variant of i2c_slave_async_net_tb.v. Identical stimulus, but
// adds a $monitor on the DUT's internal phase/bit_cnt/shreg/addr_ok/rw_bit
// signals (all still visible as plain hierarchical wire references, since
// Yosys keeps these names in the synthesized netlist -- see
// `grep -n "wire \[.*\] phase\|wire \[.*\] bit_cnt" i2c_slave_async_net.v`).
//
// Purpose: a from-scratch Python gate-level simulator (built because
// iverilog isn't available in the analysis sandbox) shows all 14 checks
// PASSING on this exact netlist, but real iverilog on the user's machine
// shows 7 FAILing (all address/data-forwarding checks, all consistent with
// addr_ok/rw_bit never leaving their reset value of 0). This trace is meant
// to show, from REAL iverilog, whether bit_cnt actually counts 0..7 during
// the address byte and whether addr_ok/rw_bit ever update -- data the
// sandbox currently has no way to obtain directly.
//
// Run:
//   iverilog -o sim_dbg i2c_slave_async_net.v stdcell_behavioral_stubs.v i2c_slave_async_net_tb_debug.v && vvp sim_dbg | head -100
//
// (the interesting window is roughly t=180 to t=1000, i.e. reset release
// through the end of the first address byte + ACK of scenario 1 -- `head
// -100` should comfortably cover it; increase if truncated)
// =============================================================================
`timescale 1ns/1ps

module i2c_slave_async_net_tb_debug;

    localparam [6:0] SLAVE_ADDR = 7'h50;
    localparam [6:0] WRONG_ADDR = 7'h11;
    localparam T = 20;

    wire VDD = 1'b1;
    wire GND = 1'b0;

    reg  rst_n;
    reg  scl;
    reg  m_oe;
    wire sda;
    wire s_oe;

    reg  [7:0] tx_data;
    wire [7:0] rx_data;
    wire       rx_valid;
    wire       addr_match;
    wire       rw;
    wire       busy;

    integer errors = 0;

    pullup(sda);
    assign sda = m_oe ? 1'b0 : 1'bz;

    i2c_slave_async dut (
        .VDD        (VDD),
        .GND        (GND),
        .rst_n      (rst_n),
        .scl        (scl),
        .sda_in     (sda),
        .sda_oe     (s_oe),
        .tx_data    (tx_data),
        .rx_data    (rx_data),
        .rx_valid   (rx_valid),
        .addr_match (addr_match),
        .rw         (rw),
        .busy       (busy)
    );
    assign sda = s_oe ? 1'b0 : 1'bz;

    // ---- diagnostic monitor: prints on ANY change of any listed signal ----
    initial begin
        $monitor("t=%80t scl=%b sda=%b m_oe=%b | rst_scl_domain=%b phase=%b bit_cnt=%0d shreg=%b addr_ok=%b rw_bit=%b | busy=%b",
                 $time, scl, sda, m_oe, dut.rst_scl_domain, dut.phase, dut.bit_cnt, dut.shreg, dut.addr_ok, dut.rw_bit, busy);
    end

    task check(input cond, input [511:0] msg);
        begin
            if (cond) $display("[t=%0t] OK: %s", $time, msg);
            else begin
                $display("[t=%0t] FAIL: %s", $time, msg);
                errors = errors + 1;
            end
        end
    endtask

    task send_bit(input bitval);
        begin
            #T scl = 0; m_oe = ~bitval;
            #T scl = 1;
            #(2*T);
        end
    endtask

    task send_byte(input [7:0] b);
        integer i;
        begin
            for (i = 7; i >= 0; i = i - 1)
                send_bit(b[i]);
        end
    endtask

    task read_ack(output ack);
        begin
            #T scl = 0; m_oe = 0;
            #T scl = 1;
            #T ack = sda;
            #T scl = 0;
        end
    endtask

    reg ack_bit;

    initial begin
        rst_n = 1; scl = 1; m_oe = 0; tx_data = 8'h00;
        rst_n = 0;
        #(4*T);
        rst_n = 1;
        #(5*T);

        // ================= Scenario 1 (address byte only) ================
        scl = 1; m_oe = 0; #T;
        m_oe = 1;                       // START
        #(2*T);
        check(busy, "busy asserted after START");

        send_byte({SLAVE_ADDR, 1'b0});  // address + W
        read_ack(ack_bit);
        check(ack_bit == 1'b0, "slave ACKed matching address (write)");
        check(addr_match, "addr_match asserted");
        check(rw == 1'b0, "rw indicates WRITE");

        #(5*T);
        $display("\n---- stopping after address-phase diagnostic window ----");
        $finish;
    end

endmodule
