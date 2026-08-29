// =============================================================================
// i2c_slave_async.v  (v4 -- V8世代: last_bit_pendingパイプライン方式 +
//                     sda_oe極性修正)
//
// v3で加えた2件の根本修正（design_notes.md §77、実TR-1um.prm下のIRSIM
// チップレベル検証で発見。詳細は design_notes.md §76.43-76.47/§76.17-76.18）
// のうち、(1)のレース解消手段をv4で置き換えた（design_notes §77.24
// ユーザー提案・承認）:
//
//   1. [v3で採用、v4で置き換え] bit_cnt（4bit二値カウンタ+`==7`比較器）を、
//      shregと対称的な8bitウォーキングワン（one-hot）シフトレジスタ
//      `bit_walk`に置換 -- 「最終ビットか」の判定を組み合わせ比較器から
//      単純なレジスタ出力（`bit_walk[0]`）に変えることで、`rw_bit`/
//      `addr_ok`の取り込みが`bit_cnt`自身の同一エッジ内遷移と組み合わせ
//      パスを共有しなくなり、同一エッジ内レースを解消した（design_notes
//      §77.2）。ただしbit_cnt(3-4bit)→bit_walk(8bit)でDFFが正味+4〜5個
//      増え、V8のインスタンス数増加（186 vs v7の154、+20.8%）の一因と
//      なり、OSS_FRAME_GIO接続に必須の行幅1620.0um制約（design_notes
//      §77.23）を満たせない事態を招いた。
//   2. [v4、本セッション] bit_walkを廃止し、元のbit_cnt（3bit二値
//      カウンタ）に戻した上で、新規1bitレジスタ`last_bit_pending`を
//      追加。「次のエッジで最終ビットになる」ことを1エッジ前倒しで
//      `bit_cnt==3'd6`から先読み登録し、実際のキャプチャ判定
//      （`is_last_bit`）はこの`last_bit_pending`の値のみを見る。
//      `last_bit_pending`はbit_cntの1エッジ前の安定値から生成される
//      通常のD入力ロジック（他の同期回路と同じ）であり、bit_cnt自身が
//      同じエッジで新しい値へ更新されることとは物理的に競合しない
//      （bit_walk[0]が「別の確定済みFF」だったのと同じ原理を、8bit化
//      ではなく1bit追加のみで再現）。DFF正味増加は僅か+1個で済み、
//      bit_walk比でDFF-3〜4個の削減（design_notes §77.24）。
//   3. `sda_oe`出力の極性を反転（`0=LOW駆動, 1=解放`）。SDAパッドの
//      `HIZ13`ピンの実仕様（`HIZ=L→駆動, HIZ=H→解放`）に、コア出力
//      そのものが直接一致するようにした。従来（v2）は`1=LOW駆動`という
//      逆センスで出力しており、パッドと直結の配線ではリセット直後・
//      アイドル時にSDAを能動的にLOW駆動し続けてしまうバグがあった
//      （design_notes §77.3）。
//
// v4は未検証（RTLレベルのMyHDL/iverilogテストのみ、design_notes §77.24）
// -- 同一エッジレース解消そのものの確認には、v3同様IRSIM実機デバッグ
// （またはSPICEレベル）での再検証が必要。
//
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
// Functionally verified for the v2 architecture with a MyHDL model and
// iverilog testbench (write/read/wrong-address scenarios) -- see
// design_notes.md. v3's bit_walk/sda_oe-polarity changes are NOT YET
// re-verified against script/i2c_slave_async_model.py (which was also found,
// during this v3 pass, to predate even the v2 DEL1-based START/STOP
// architecture -- see design_notes.md section 77, "Verilog検証" step);
// re-running iverilog + an updated MyHDL model is the mandatory next step
// before synthesis.
//
// Open items (see logic_cells_mapping.md / design_notes.md for detail):
//   - DFFR.RST / DFFS.SET are assumed active-HIGH from a partial transistor
//     trace of DFFR.sch, not yet SPICE-confirmed.
//   - Liberty timing (TR1um_5_stdcell.lib) is placeholder/nominal, not
//     characterized -- fine for a functional netlist, not for STA/tapeout.
//   - sda_oe is logic-level open-drain, ACTIVE-LOW as of v3
//     (0 = drive low, 1 = release) -- matches the SDA pad's HIZ13 pin
//     convention directly (design_notes.md section 77.3); the actual
//     pull-down/pad transistor itself is outside this module's scope.
// =============================================================================

module i2c_slave_async #(
    parameter [6:0] SLAVE_ADDR = 7'h50
) (
    input  wire       VDD, GND,   // needed by the structural DEL1/NOR2/INV_X1 instances
    input  wire       rst_n,      // async reset, active low
    input  wire       scl,        // bus SCL (already deglitched to a clean level)
    input  wire       sda_in,     // sensed SDA line level
    output wire       sda_oe,     // v3: 0 = drive SDA low, 1 = release (Hi-Z)
                                   // (active-low; matches SDA pad HIZ13 directly,
                                   // design_notes.md section 77.3)

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
    // v4: bit_cnt is a plain 3bit binary counter again (v3's 8bit
    // walking-one bit_walk is gone). The race it existed to fix is now
    // solved differently: last_bit_pending is a dedicated 1bit register
    // that latches "bit_cnt was 6 as of the PREVIOUS edge" -- a completely
    // ordinary D-input decode of bit_cnt's already-settled, pre-edge value
    // (exactly like bit_cnt's own "+1" logic is), so on the edge where it
    // is actually USED (is_last_bit), it has already been stable for a
    // full SCL period and shares no combinational path with bit_cnt's own
    // simultaneous 7->0 transition on that same edge -- eliminating the
    // same-clock-edge race between bit_cnt's self-reset and rw_bit/
    // addr_ok's capture found in design_notes.md section 76.43-76.47, at
    // a cost of +1 DFF instead of v3's bit_walk (+4~5 DFF net vs a binary
    // counter) -- design_notes.md section 77.24 (user-proposed circuit,
    // this session).
    reg [2:0] bit_cnt;
    reg       last_bit_pending;
    reg [7:0] shreg;
    reg       addr_ok, rw_bit;
    reg [7:0] rx_data_r;

    wire [7:0] shreg_next  = {shreg[6:0], sda_in};
    wire       is_last_bit = last_bit_pending;

    always @(posedge scl or posedge rst_scl_domain) begin
        if (rst_scl_domain) begin
            phase            <= PH_ADDR;
            bit_cnt          <= 3'd0;
            last_bit_pending <= 1'b0;
            shreg            <= 8'd0;
            addr_ok          <= 1'b0;
            rw_bit           <= 1'b0;
            rx_data_r        <= 8'd0;
        end else begin
            shreg <= shreg_next;
            // Precompute next edge's "is_last_bit" from bit_cnt's current
            // (pre-edge, stable) value -- bit_cnt only ever reaches 6
            // while actively counting bits in PH_ADDR/PH_DATA_WR/
            // PH_DATA_RD (every phase-entry branch below resets it to 0),
            // so this unconditional per-edge update is safe in every
            // phase, mirroring how bit_walk[0] was valid regardless of
            // which counting phase was active.
            last_bit_pending <= (bit_cnt == 3'd6);
            case (phase)
                PH_ADDR: begin
                    if (is_last_bit) begin
                        addr_ok <= (shreg_next[7:1] == SLAVE_ADDR);
                        rw_bit  <= shreg_next[0];
                        phase   <= PH_ADDR_ACK;
                        bit_cnt <= 3'd0;
                    end else bit_cnt <= bit_cnt + 3'd1;
                end
                PH_ADDR_ACK: begin
                    phase   <= addr_ok ? (rw_bit ? PH_DATA_RD : PH_DATA_WR) : PH_IGNORE;
                    bit_cnt <= 3'd0;
                end
                PH_DATA_WR: begin
                    if (is_last_bit) begin
                        rx_data_r <= shreg_next;
                        phase     <= PH_DATA_WR_ACK;
                        bit_cnt   <= 3'd0;
                    end else bit_cnt <= bit_cnt + 3'd1;
                end
                PH_DATA_WR_ACK: begin
                    phase   <= PH_DATA_WR;
                    bit_cnt <= 3'd0;
                end
                PH_DATA_RD: begin
                    if (is_last_bit) phase <= PH_DATA_RD_ACK;
                    bit_cnt <= bit_cnt + 3'd1;
                end
                PH_DATA_RD_ACK: begin
                    phase   <= (sda_in == 1'b0) ? PH_DATA_RD : PH_IGNORE;
                    bit_cnt <= 3'd0;
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

    // sda_oe_r keeps the same internal sense it always had (1 = drive
    // low), for readability -- only the final output assign (below)
    // flips to the pad's real (active-low) convention (v3, section 77.3).
    //
    // v4: back to bit_cnt==0 ("first bit of this byte", the original v2
    // mechanism) and an arithmetic index txreg[7-bit_cnt], since bit_walk
    // (and its one-hot AND-OR bit-select convenience) no longer exists --
    // bit_cnt/phase are read here exactly as in v2, a genuine cross-domain
    // combinational read of a posedge-clocked register (same as always).
    // This block was never part of the same-edge race (design_notes
    // section 77.24) -- only the posedge-domain is_last_bit decode was --
    // so it needs no race-avoidance change of its own, just the mechanical
    // bit_walk->bit_cnt rewrite.
    always @(posedge scl_n or posedge rst_sdaoe_domain) begin
        if (rst_sdaoe_domain) begin
            sda_oe_r <= 1'b0;
            txreg    <= 8'd0;
        end else begin
            case (phase)
                PH_ADDR_ACK:    sda_oe_r <= addr_ok;
                PH_DATA_WR_ACK: sda_oe_r <= 1'b1;
                PH_DATA_RD: begin
                    if (bit_cnt == 3'd0) begin
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
    // v3: output polarity flipped to match the SDA pad's HIZ13 pin
    // directly (0 = drive low, 1 = release) -- see section 77.3 /
    // design_notes.md section 77.3. sda_oe_r's own internal sense is
    // unchanged (1 = drive low); only this final assign inverts.
    assign sda_oe = ~sda_oe_r;

endmodule
