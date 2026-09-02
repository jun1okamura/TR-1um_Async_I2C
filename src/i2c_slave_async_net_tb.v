// =============================================================================
// i2c_slave_async_net_tb.v
//
// Testbench for i2c_slave_async_net.v (the Yosys-synthesized gate-level
// netlist, now including the scl/sda_in/_126_/_127_ buffer-tree insertion
// from design_notes.md section 18). Identical to i2c_slave_async_tb.v
// (same 3 scenarios) except for ONE difference: the DUT instantiation does
// NOT pass #(.SLAVE_ADDR(...)) -- Yosys resolves parameters at synthesis
// time and does not emit a `parameter` declaration in the netlist module,
// so `i2c_slave_async_net #(.SLAVE_ADDR(...))` fails elaboration
// ("parameter SLAVE_ADDR not found"). i2c_slave_async_net.v's SLAVE_ADDR is
// hardwired to the same 7'h50 used here (see i2c_slave_async.v's default
// parameter value and the localparam below), so simply omitting the
// override is functionally equivalent.
//
// Run:
//   iverilog -o sim_net i2c_slave_async_net.v stdcell_behavioral_stubs.v i2c_slave_async_net_tb.v && vvp sim_net
// =============================================================================
`timescale 1ns/1ps

module i2c_slave_async_net_tb;

    localparam [6:0] SLAVE_ADDR = 7'h50;
    localparam [6:0] WRONG_ADDR = 7'h11;
    localparam T = 20; // arbitrary bit-time unit; correctness must not
                        // depend on this value for an async design.

    wire VDD = 1'b1;
    wire GND = 1'b0;

    reg  rst_n;
    reg  scl;
    reg  m_oe;      // master pulls SDA low when 1
    wire sda;       // resolved open-drain bus (pullup1 below)
    wire s_oe;

    reg  [7:0] tx_data;
    wire [7:0] rx_data;
    wire       rx_valid;
    wire       addr_match;
    wire       rw;
    wire       busy;

    integer errors = 0;

    // open-drain bus: pulled up, either side can pull low
    pullup(sda);
    assign sda = m_oe ? 1'b0 : 1'bz;

    // NOTE: no #(.SLAVE_ADDR(...)) here -- see file header.
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
    // 2026-09-02 fix: sda_oe is active-low (0 = drive low, 1 = release) as
    // of RTL v3 (section 77.3, matching the real HIZ13 pad convention) --
    // this file still had the pre-v3 (active-high) sense, which was never
    // updated when the RTL's sda_oe polarity flipped. Consequence: sda_oe_r
    // resets to 0 -> sda_oe=~0=1 -> under the OLD (wrong) sense here that
    // read as "drive low", so the slave held SDA low from just after reset,
    // masking the real START condition's 1->0 transition and preventing
    // start_pulse from ever firing (busy/addr_ok/rw_bit then never update,
    // matching the observed 6/14 failure signature). i2c_slave_async_tb.v
    // (RTL-level) already had the correct sense; only this netlist-level
    // copy was stale. The real DUT/netlist was never at fault -- confirmed
    // separately via SPICE (tr_1um_i2c_slave_async_sim_ready.spice) and
    // IRSIM (irsim_tb.cmd, 14/14 PASS), both of which use the correct
    // electrical/switch-level sense natively.
    assign sda = s_oe ? 1'bz : 1'b0;

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
            #T scl = 0;
            #2 m_oe = ~bitval;  // stagger from scl's edge: avoids a same-
                                 // instant race between the sda_in (1-gate)
                                 // and scl (2-gate, via _105_) paths into the
                                 // synthesized start/stop-pulse detector,
                                 // which otherwise glitches rst_scl_domain
                                 // (see design_notes.md section 19).
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

    // master, as receiver, reads the ack bit driven by the slave
    task read_ack(output ack);
        begin
            #T scl = 0;
            #2 m_oe = 0;
            #(T-2) scl = 1;
            #T ack = sda;
            #T scl = 0;
        end
    endtask

    // master, as receiver of a data byte, samples 8 bits MSB first
    task read_byte(output [7:0] val);
        integer i;
        reg bit_v;
        begin
            val = 8'h00;
            for (i = 0; i < 8; i = i + 1) begin
                #T scl = 0;
                #2 m_oe = 0;
                #(T-2) scl = 1;
                #T bit_v = sda;
                val = {val[6:0], bit_v};
                #T ;
            end
        end
    endtask

    // master drives ack(0)/nack(1) after reading a byte
    task send_ack(input nack);
        begin
            #T scl = 0;
            #2 m_oe = ~nack;
            #(T-2) scl = 1;
            #(2*T);
            scl = 0;
            #2 m_oe = 0;
        end
    endtask

    reg ack_bit;
    reg [7:0] rd_byte;

    initial begin
        // NOTE: in real (4-state) Verilog simulation every reg starts at X.
        // Unlike the MyHDL reference model (whose Signals are explicitly
        // initialized in Python and therefore never X), this DUT's
        // registers only reach a defined value via the `if (!rst_n)`
        // branch in i2c_slave_async.v. A reset pulse is therefore mandatory
        // here -- without it, sda_oe/state/scl_q/sda_q stay X forever and
        // every check fails.
        rst_n = 1; scl = 1; m_oe = 0; tx_data = 8'h00;
        rst_n = 0;
        #(4*T);
        rst_n = 1;
        #(5*T);

        // ================= Scenario 1: write 0xA5 to SLAVE_ADDR =========
        scl = 1; m_oe = 0; #T;
        m_oe = 1;                       // START (SDA 1->0 while SCL=1)
        #(2*T);
        check(busy, "busy asserted after START");

        send_byte({SLAVE_ADDR, 1'b0});  // address + W
        read_ack(ack_bit);
        check(ack_bit == 1'b0, "slave ACKed matching address (write)");
        check(addr_match, "addr_match asserted");
        check(rw == 1'b0, "rw indicates WRITE");

        send_byte(8'hA5);
        read_ack(ack_bit);
        check(ack_bit == 1'b0, "slave ACKed data byte");
        #T;
        check(rx_data == 8'hA5, "rx_data == 0xA5");

        // 2026-09-02 fix (design_notes.md section 108.6, same fix applied
        // to i2c_slave_async_tb.v): drive SDA low BEFORE raising SCL, not
        // after -- the old ordering briefly changed SDA while SCL was
        // already high (a protocol violation except for genuine START/
        // STOP), which also breaks the new transparent-latch sda_d
        // detector (section 108.5) once this netlist is resynthesized from
        // the v6 RTL.
        m_oe = 1; #2 scl = 1; #(T-2);
        m_oe = 0;                       // STOP (SDA 0->1 while SCL=1)
        #(2*T);
        check(!busy, "busy cleared after STOP");

        // ================= Scenario 2: read one byte, then NACK ==========
        tx_data = 8'h3C;
        #(2*T);

        scl = 1; m_oe = 0; #T;
        m_oe = 1;                       // START
        #(2*T);

        send_byte({SLAVE_ADDR, 1'b1});  // address + R
        read_ack(ack_bit);
        check(ack_bit == 1'b0, "slave ACKed matching address (read)");
        check(rw == 1'b1, "rw indicates READ");

        read_byte(rd_byte);
        check(rd_byte == 8'h3C, "read byte == 0x3C");
        send_ack(1'b1);                 // master NACKs -> ends read

        // 2026-09-02 fix (design_notes.md section 108.6): see the identical
        // fix's comment earlier in this file (first STOP sequence).
        m_oe = 1; #2 scl = 1; #(T-2);
        m_oe = 0;                       // STOP
        #(2*T);
        check(!busy, "busy cleared after final STOP");

        // ================= Scenario 3: wrong address -> NACK =============
        scl = 1; m_oe = 0; #T;
        m_oe = 1;                       // START
        #(2*T);

        send_byte({WRONG_ADDR, 1'b0});
        read_ack(ack_bit);
        check(ack_bit == 1'b1, "unmatched address -> NACK (no slave ack)");
        check(!addr_match, "addr_match not asserted for foreign address");

        // 2026-09-02 fix (design_notes.md section 108.6): see the identical
        // fix's comment earlier in this file (first STOP sequence).
        m_oe = 1; #2 scl = 1; #(T-2);
        m_oe = 0;                       // STOP
        #(2*T);
        check(!busy, "busy cleared after STOP following NACK");

        #(5*T);
        if (errors == 0) $display("\n---- RESULT ----\nAll checks PASSED");
        else $display("\n---- RESULT ----\n%0d check(s) FAILED", errors);
        $finish;
    end

    initial begin
        $dumpfile("i2c_slave_async_net_tb.vcd");
        $dumpvars(0, i2c_slave_async_net_tb);
    end

endmodule
