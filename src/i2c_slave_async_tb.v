// =============================================================================
// i2c_slave_async_tb.v
//
// Testbench for i2c_slave_async.v (v2, gate-synthesizable architecture).
// Not run in the delivery sandbox (no iverilog/Verilator available there);
// run it locally, e.g.:
//
//   iverilog -o sim i2c_slave_async.v i2c_slave_async_tb.v && vvp sim
//   (or) verilator --binary -j 0 i2c_slave_async_tb.v i2c_slave_async.v --top-module i2c_slave_async_tb
//
// NOTE: this testbench needs behavioral models for DEL1/NOR2/INV_X1 (v2
// instantiates them structurally) to be visible to the simulator. iverilog
// will treat them as undefined-module errors unless you either (a) also
// compile ../TR1um_5_stdcell behavioral/gate models alongside this file, or
// (b) compile a quick behavioral stub library for iverilog-only simulation
// (DEL1: Y=A with a small #delay; NOR2: Y=~(A|B); INV_X1: Y=~A). This repo
// does not yet include such stubs -- add them before running this TB.
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
    assign sda = s_oe ? 1'b0 : 1'bz;

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

    // master, as receiver, reads the ack bit driven by the slave
    task read_ack(output ack);
        begin
            #T scl = 0; m_oe = 0;
            #T scl = 1;
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
                #T scl = 0; m_oe = 0;
                #T scl = 1;
                #T bit_v = sda;
                val = {val[6:0], bit_v};
                #T ;
            end
        end
    endtask

    // master drives ack(0)/nack(1) after reading a byte
    task send_ack(input nack);
        begin
            #T scl = 0; m_oe = ~nack;
            #T scl = 1;
            #(2*T);
            scl = 0; m_oe = 0;
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

        m_oe = 1; scl = 1; #T;
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

        m_oe = 1; scl = 1; #T;
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

        m_oe = 1; scl = 1; #T;
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
