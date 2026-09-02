// =============================================================================
// i2c_slave_async_net_v9_rowbuf_tb_debug.v
//
// DIAGNOSTIC variant of i2c_slave_async_net_tb.v, targeting
// i2c_slave_async_net_v9_rowbuf.v specifically (2026-09-02).
//
// Context: i2c_slave_async_net_tb.v (with its existing #2 SCL/SDA stagger,
// design_notes.md section 19) FAILS 6/14 checks against v9_rowbuf --
// "busy asserted after START" fails at the very first check, along with
// addr_match/rx_data/rw-during-read/read-byte/wrong-address-NACK. This is
// the SAME category of failure (all "internal state" checks fail while
// plain wire-level SDA/ACK checks pass) as the original section-19 bug, but
// note section 19's own fix was calibrated against the netlist BEFORE
// buffer/row-buffer insertion; that section's own "next step" note says a
// re-verification against the buffer-inserted netlist was planned but its
// outcome/margin was apparently never fed back into the #2 constant used
// here. Meanwhile the ACTUAL v9_rowbuf-derived chip, verified directly in
// SPICE (ngspice/TB/tb_chip_i2c.spice, real transistor delays + the
// T_HOLD=300ns testbench fix) DOES pass -- so this is very likely a
// unit-delay-model-specific margin problem in THIS Verilog gate simulation,
// not a real design defect. This debug testbench exists to see directly
// (from real iverilog output) whether phase/bit_cnt/shreg/addr_ok/rw_bit
// actually glitch mid-transaction (confirming the same start_pulse-detector
// race, just needing a bigger margin at this unit-delay scale) or whether
// something else is going on.
//
// Run:
//   iverilog -o sim_dbg9 i2c_slave_async_net_v9_rowbuf.v stdcell_behavioral_stubs.v i2c_slave_async_net_v9_rowbuf_tb_debug.v && vvp sim_dbg9 | head -150
// =============================================================================
`timescale 1ns/1ps

module i2c_slave_async_net_v9_rowbuf_tb_debug;

    localparam [6:0] SLAVE_ADDR = 7'h50;
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
    // 2026-09-02 fix: same stale active-high sda_oe sense bug as
    // i2c_slave_async_net_tb.v -- see that file's fix comment for the full
    // diagnosis. sda_oe is active-low (0 = drive low, 1 = release) since
    // RTL v3.
    assign sda = s_oe ? 1'bz : 1'b0;

    // ---- diagnostic monitor: prints on ANY change of any listed signal ----
    // 2026-09-02: added start_pulse/busy_clr/qn/rst_scl_domain/scl_gated --
    // both SPICE (tr_1um_i2c_slave_async_sim_ready.spice, real transistors)
    // and IRSIM (switch-level, irsim_tb.cmd 14/14 PASS) confirm the actual
    // v9_rowbuf-derived chip works correctly, so this iverilog-only failure
    // (busy never asserts, addr_ok/rw_bit never update, despite bit_cnt
    // counting 0..7 with no visible glitch) is suspected to be a unit-delay/
    // 4-state-X-propagation artifact specific to this behavioral-stub
    // simulation, not a real wiring defect. Tracing start_pulse (net _167_)
    // and the busy SR latch's own two nodes directly to see whether
    // start_pulse ever pulses HIGH at all for the real START event, and
    // whether busy_clr is unexpectedly stuck asserted (blocking the SET).
    initial begin
        $monitor("t=%0t scl=%b sda=%b m_oe=%b s_oe=%b | phase=%b bit_cnt=%0d shreg=%b addr_ok=%b rw_bit=%b | busy=%b addr_match=%b rw=%b | start_pulse=%b busy_clr=%b qn=%b scl_gated=%b | scl_row2=%b sda_in_row2=%b sda_d=%b nand_n083=%b sda_oe_r=%b sda_oe=%b",
                 $time, scl, sda, m_oe, s_oe, dut.phase, dut.bit_cnt, dut.shreg, dut.addr_ok, dut.rw_bit, busy, addr_match, rw,
                 dut.start_pulse, dut.busy_clr, dut.qn, dut.scl_gated,
                 dut.scl_row2, dut.sda_in_row2, dut.sda_d, dut._083_, dut.sda_oe_r, dut.sda_oe);
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

    // Same #2 stagger as the current i2c_slave_async_net_tb.v (section 19's
    // fix) -- reproducing the SAME stimulus that just failed, so this trace
    // is directly comparable.
    task send_bit(input bitval);
        begin
            #T scl = 0;
            #2 m_oe = ~bitval;
            #(T-2) scl = 1;
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
            #T scl = 0;
            #2 m_oe = 0;
            #(T-2) scl = 1;
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
