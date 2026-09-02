// =============================================================================
// i2c_slave_async_tb.v
//
// Testbench for i2c_slave_async.v (v4: bit_cnt + last_bit_pending pipelined
// terminal-count flag + active-low sda_oe, design_notes.md section 77.24).
// Not run in the delivery sandbox (no iverilog/Verilator available there);
// run it locally, e.g.:
//
//   iverilog -o sim i2c_slave_async.v stdcell_behavioral_stubs.v i2c_slave_async_tb.v && vvp sim
//   (or) verilator --binary -j 0 i2c_slave_async_tb.v i2c_slave_async.v stdcell_behavioral_stubs.v --top-module i2c_slave_async_tb
//
// NOTE: this testbench needs behavioral models for DEL1/NOR2/INV_X1 (v2/v3
// instantiate them structurally) to be visible to the simulator --
// stdcell_behavioral_stubs.v (in this same directory) provides them, along
// with every other TR1um_5_stdcell cell used anywhere in this project.
// iverilog will report "Unknown module type: DEL1/NOR2/INV_X1" if it is
// left out of the compile command.
//
// Exercises the same three scenarios verified throughout this project
// (script/test_v3_positive.py / test_v3_negative.py against the matching
// MyHDL model):
//   1. write transaction  : S, ADDR+W(0x50), ACK, 0xA5, ACK, P
//   2. read transaction    : S, ADDR+R(0x50), ACK, slave drives 0x3C, NACK, P
//   3. wrong-address write : S, ADDR+W(0x11), NACK, P
// =============================================================================
`timescale 1ns/1ps

module i2c_slave_async_tb;

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

    i2c_slave_async #(.SLAVE_ADDR(SLAVE_ADDR)) dut (
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
    // v3: sda_oe is now active-low (0 = drive low, 1 = release), matching
    // the SDA pad's HIZ13 convention directly -- see i2c_slave_async.v
    // header and design_notes.md section 77.3.
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
            #2 m_oe = ~bitval;  // stagger from scl's edge: keeps parity with
                                 // i2c_slave_async_net_tb.v, which needs this
                                 // to avoid a same-instant race in the
                                 // synthesized start/stop-pulse detector
                                 // (see design_notes.md section 19). Harmless
                                 // here (RTL has no such hazard) but keeps
                                 // both testbenches' stimulus identical.
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

        // 2026-09-02 fix (design_notes.md section 108.6): drive SDA low
        // BEFORE raising SCL (was: scl=1 first, then m_oe=1 2ns later --
        // that briefly changes SDA while SCL is already high, a protocol
        // violation UM10204 3.1.3 forbids except for a genuine START/STOP,
        // and it also confuses the new transparent-latch sda_d detector
        // (section 108.5), which freezes at whatever SDA was AT THE INSTANT
        // SCL rose and only re-arms once SCL next goes low -- with the old
        // ordering it froze at "released/high" a moment too early, then
        // never re-latched onto the intentionally-driven-low value, so the
        // later real STOP transition went undetected). Same safe ordering
        // send_bit() already uses: SDA changes while SCL=0, then SCL rises.
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
        // fix's comment earlier in this file (first STOP sequence) -- SDA
        // must be driven low BEFORE SCL rises, not after.
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
        // fix's comment earlier in this file (first STOP sequence) -- SDA
        // must be driven low BEFORE SCL rises, not after.
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
        $dumpfile("i2c_slave_async_tb.vcd");
        $dumpvars(0, i2c_slave_async_tb);
    end

endmodule
