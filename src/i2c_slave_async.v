// =============================================================================
// i2c_slave_async.v  (v8 -- sda_dラッチをMUX2フィードバック(ダイナミック)
//                     からNOR2クロス結合(スタティック)方式へ再構成)
//
// v8（2026-09-02、design_notes.md §108.8）: v7のsda_dラッチ（MUX2×2の
// 自己フィードバック）は、実SPICEで検証したところダイナミック
// （漏れ電流で電位が劣化しうる）ラッチであることが判明した。
// 理想化されたVerilogモデルではwireが永久に値を保持するため区別が
// つかなかったが、実際には5us（SCL-high半周期）×バイト内複数ビット
// という長時間の保持が必要で、これがMUX2のトランスミッションゲート
// 経由の保持（能動的な再生駆動を持たない、ノード自身の寄生容量頼み）
// では持たず、addr_match/rx_data/read byteが軒並み不正な値になった
// （busy自体は別回路の真にスタティックなNOR2クロス結合SRラッチなので
// 正しく動作し続けた）。既存のbusy/rst_scl_domain_heldと同じ実績ある
// スタティック（再生型）SRラッチ方式のゲート付きDラッチ（NOR2×2 +
// AND2_X1×2 + NAND2×1 + INV_X1×1、全て既存セル種）に再構成した。
// 詳細は下記u_sda_target/u_sda_lat_en/u_sda_q/u_sda_qnのコメント参照。
//
// =============================================================================
// i2c_slave_async.v  (v7 -- sda_dラッチをbusyゲート方式に変更し、
//                     アイドル中の再アーム不能バグを解消)
//
// v7（2026-09-02、design_notes.md §108.6/108.7）: v6のsda_dラッチ
// （scl=0で透過・scl=1で保持）はSTOP検出のRC律速問題は解決したが、
// 「実際のI2Cバスは、STOPから次のSTARTまでの間SCLがずっとHighのまま
// アイドルし続け、Lowに戻る保証がない」という現実に対応できていな
// かった：一度SCL=1で凍結されると、SCLが二度とLowにならない限り
// 再アームされず、STOP後の"SDAはリリースされてHigh"という状態を
// 反映できないまま、次のSTARTを検出し損ねる（`i2c_slave_async_tb.v`
// のシナリオ2で実際に再現・確認）。修正：sda_dの保持条件を`scl`
// ではなく`busy`でゲートする2段構成に変更。`busy=0`（アイドル中・
// リセット中）は常に`sda_d=1`へ強制し、`busy=1`（トランザクション中、
// SCLが毎ビット必ずトグルする）の間だけ、既存のscl透過ラッチ
// （v6のu_lat_sda）を通す。`busy`はstop_pulse発火の瞬間に即座に
// クリアされるため、SCLが二度とLowにならなくても`sda_d`は正しく
// 再アームされる。リセット中も`busy_clr`の`~rst_n`項で`busy=0`が
// 保証されるため、v6で必要だった`rst_n`個別コールドスタート対策も
// 不要になった（削除）。詳細は下記u_lat_sda/u_force_sdaのコメント
// 参照。
//
// =============================================================================
// i2c_slave_async.v  (v6 -- start_pulse/stop_pulse検出器をDEL1固定遅延
//                     から透過ラッチ(MUX2フィードバック)方式へ再設計)
//
// v6（2026-09-02、ngspice実機バッチ14項目検証(script/gen_chip_tb_batch14_
// v9.py)で発見・修正。詳細はdesign_notes.md §108.4/108.5）:
// stop_pulse = scl & ~sda_d & sda_in（sda_d = DEL1(sda_in)）は、STOP1
// イベント周辺をSPICEで5ns刻み実測した結果、busy_clrが最大でも0.05V
// (VDDの1%)しか振れず、下流ゲートの論理しきい値(2.5V)に一度も届かない
// ことが判明した。原因：sda_in(SDAの立上り、10kΩ外部プルアップによる
// 受動的RC充電)の実測遷移時間が約15-20nsなのに対し、DEL1の実効遅延は
// 約2nsしかなく、この2ns窓の間にsda_inとsda_dの間に生じる電位差は
// フルスイングの5Vではなくアナログランプの一部（~1%）にしかならない。
// start_pulseが検出するSDAの立下り(アクティブなプルダウン駆動、高速・
// ほぼステップ状)とstop_pulseが検出するSDAの立上り(受動的RC充電、
// 原理的に低速)は電気的に非対称であり、「固定遅延幅で少し前の自分の
// 値と比較する」DEL1方式は、比較対象の遷移がその固定遅延幅より十分
// 速い(=遅延窓の間にフルスイング分の電位差が生じる)ことを暗黙に仮定
// している。この仮定は高速な立下り(START)には成立するが、低速な
// RC律速の立上り(STOP)には（プルアップ抵抗値やバス容量次第で）一般に
// 成立しない、という設計原理上の欠陥だった（IRSIM/Verilogは共に
// アナログ電圧を扱わないためこの種の不具合を検出できず、実トランジスタ
// SPICEで初めて顕在化した）。
//
// 修正：DEL1（固定遅延線）を、SCL=0の間はsda_inに透過追従し、SCL=1の
// 間はSCLが立ち上がった瞬間の値を保持し続ける「透過ラッチ」
// （MUX2 + 自己フィードバック、下記u_lat_sda参照）に置き換えた。
// SCLが1の間、sda_dはSCL立ち上がり時点の値に完全にラッチされた
// （正規のデジタルレベルへ再生された）状態で固定されるため、sda_inが
// その後どれほどゆっくり遷移しても、両者の電位差は遷移完了後は必ず
// フルスイングになる——DEL1のような固定時間窓に依存しないため、
// バスのRC時定数（プルアップ抵抗・寄生容量）に対して原理的に頑健。
// MUX2は既存セルライブラリで既に使用中（rx_data_r/shregのMUX等）で
// あり、STDCELL側の変更はゼロ。sda_dの用途はstart_pulse/stop_pulse
// のみ（他箇所からの参照なし、design_notes.md §108.4で確認済み）で
// あり、この置き換えの影響範囲はこの2本のwireの生成方法だけに閉じる。
//
// =============================================================================
// i2c_slave_async.v  (v5 -- rst_scl_domainストレッチ方式でDFFRBマスター
//                     ラッチ不定値レースを解消)
//
// v5（2026-09-02、実ngspice全体チップ検証で発見・修正。詳細はdesign_notes.md）:
// DFFRBの非同期RSTBはスレーブ段出力（QB）のみをクリアし、マスターラッチ
// （net2/QM/net4、CK=1のトランスミッションゲート経由のクロス結合ループで
// 保持）には一切届かないことがトランジスタレベルのトレースとSPICE
// .measureで確定した。CKがHIGHのままrst_scl_domainが解除されると、
// マスターラッチが一度も書き込まれていない（電源投入時のSPICE動作点解析
// が任意に決めた）不定値がスレーブ段にそのまま透過し、QがリセットN値を
// 無視してその不定値へスナップする。しかもこれは電源投入リセットに限らず、
// start_pulseによる毎回のrst_scl_domainリセットでも必ず起きる（実際の
// STARTは定義上「SCL=1のままSDAが1→0」であり、解除の瞬間CKは常にHIGH）。
// STDCELL（DFFRB）は変更せず、既存のNOR2クロス結合busyラッチと同じ手法
// でrst_scl_domainを「sclが実際に一度LOWになるまで」ストレッチすること
// で解決（下記rst_scl_domain_held）。これにより(a)リセットアサート中は
// CKが常にLOWになりマスターラッチが安全にD値へ落ち着き、(b)リセット解除
// は必ずCK=LOWのタイミングでのみ起こるため、解除直後の最初のCK立ち上がり
// は通常通りの同期キャプチャになる。副次症状（is_last_bit判定より前に
// bit_cntが1から始まってしまう「幽霊カウント」）も同時に解消される。
//
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

    // ---- START/STOP edge detector: transparent latch, no clock at all ----
    // v7 (2026-09-02, design_notes.md section 108.7; supersedes the v6
    // single-latch attempt, section 108.5): sda_d used to be a DEL1 (fixed
    // delay line) copy of sda_in -- replaced in v6 with a plain SCL-gated
    // transparent latch (transparent while scl=0, holds while scl=1) to
    // get full analog margin against stop_pulse's RC-limited SDA rise time
    // (immune to bus loading, unlike DEL1's fixed short window). That v6
    // latch is still used here (u_lat_sda below) -- it correctly solves
    // the RC-timing problem WITHIN an active transaction, since SCL toggles
    // every bit, naturally re-arming the latch each time.
    //
    // v6 regression (i2c_slave_async_tb.v scenario 2): a real I2C bus idles
    // with SCL held continuously HIGH between a STOP and the next START --
    // there is no protocol obligation for SCL to ever go low during idle.
    // A latch gated purely by scl=0/1 never gets a transparent window after
    // STOP (scl stays 1 straight through the idle gap into the next
    // START), so it stays frozen at the LAST bit's value from before STOP
    // and misses the next START entirely. (v6 also needed a separate
    // rst_n-gated cold-start special case for the same underlying reason,
    // applied only to the very first power-up -- this v7 design subsumes
    // that case too, see below.)
    //
    // Fix: gate a SECOND stage by `busy` instead of `scl`. While busy=0
    // (idle -- including the whole reset period, since busy_clr's own
    // ~rst_n term already forces busy=0 through reset) sda_d is forced to
    // 1 ("SDA assumed released/high"), regardless of scl. Only once busy=1
    // (a real transaction is underway, so scl is guaranteed to toggle
    // every bit) does sda_d follow u_lat_sda's normal scl-gated behavior.
    // Because the force condition is `busy` (which clears the INSTANT
    // stop_pulse fires) rather than `scl` (which may not toggle again for
    // an arbitrarily long idle period), sda_d re-arms to a correct value
    // immediately when a transaction ends, with no dependency on scl ever
    // going low again -- correct regardless of how long the following idle
    // lasts. (Verified glitch-free at the START instant: start_pulse's own
    // computation uses sda_d's value from BEFORE busy reacts to it, since
    // busy is downstream of start_pulse through the SR latch below --  no
    // combinational race between forcing and using sda_d.) sda_d/sda_lat
    // are used nowhere else (confirmed via grep), so this substitution is
    // fully self-contained.
    //
    // v8 (2026-09-02, design_notes.md section 108.8): v7's hold mechanism
    // (two MUX2 gates wired back into each other, sda_lat<->sda_d) is a
    // DYNAMIC latch -- the transmission-gate-based MUX2 "hold" path has no
    // active regenerative drive of its own; it relies on the node's own
    // parasitic capacitance to retain charge while the gate is open. In
    // the idealized Verilog model a wire holds its value forever with no
    // decay, so this looked identical to a real (static) latch there --
    // but confirmed via real SPICE (script/gen_chip_tb_batch14_v9.py) that
    // it does NOT hold reliably for the multi-microsecond durations needed
    // here (5us SCL-high half-period, repeated every bit of every byte),
    // especially with two such dynamic nodes chained together: addr_match/
    // rx_data/read-byte all failed even though busy itself (a separate,
    // genuinely static NOR2-cross-coupled SR latch) still asserted/cleared
    // correctly. Rebuilt using the SAME proven static (regenerative)
    // SR-latch topology as busy/rst_scl_domain_held above, generalized to
    // a gated D-latch (2 NOR2 + 2 AND2_X1 + 1 NAND2 + 1 INV_X1, all
    // existing cell types): transparent (tracks sda_target) whenever
    // ~(busy & scl); holds (statically, via real cross-coupled regenerative
    // feedback, immune to charge decay over any timescale) whenever
    // busy & scl. sda_target itself is a plain combinational mux (no
    // memory, so no decay concern): 1 when busy=0 (idle -- forces the
    // "released" reference the same way v7 did), sda_in when busy=1.
    wire sda_target;
    MUX2 u_sda_target (.A(1'b1), .B(sda_in), .S(busy), .Y(sda_target), .VDD(VDD), .GND(GND));

    wire sda_lat_en;   // active-HIGH transparent-enable = ~(busy & scl)
    NAND2 u_sda_lat_en (.A(busy), .B(scl), .Y(sda_lat_en), .VDD(VDD), .GND(GND));

    wire sda_target_n;
    INV_X1 u_sda_target_n (.A(sda_target), .Y(sda_target_n), .VDD(VDD), .GND(GND));

    wire s_in, r_in;
    AND2_X1 u_sda_s (.A(sda_target),   .B(sda_lat_en), .Y(s_in), .VDD(VDD), .GND(GND));
    AND2_X1 u_sda_r (.A(sda_target_n), .B(sda_lat_en), .Y(r_in), .VDD(VDD), .GND(GND));

    wire sda_d, qn_sda;
    NOR2 u_sda_q  (.A(r_in), .B(qn_sda), .Y(sda_d),  .VDD(VDD), .GND(GND));
    NOR2 u_sda_qn (.A(s_in), .B(sda_d),  .Y(qn_sda), .VDD(VDD), .GND(GND));

    wire start_pulse = scl &  sda_d & ~sda_in;   // SDA 1->0 while SCL=1
    wire stop_pulse  = scl & ~sda_d &  sda_in;   // SDA 0->1 while SCL=1

    // ---- busy latch: NOR2 cross-coupled SR latch -------------------------
    wire busy_clr = stop_pulse | ~rst_n;
    wire qn;
    NOR2 u_lat_q  (.A(busy_clr),    .B(qn),   .Y(busy), .VDD(VDD), .GND(GND));
    NOR2 u_lat_qn (.A(start_pulse), .B(busy), .Y(qn),   .VDD(VDD), .GND(GND));

    // ---- SCL(posedge)-domain registers: phase/bit_cnt/shreg/addr/rw ------
    //
    // v5 (2026-09-02, real ngspice full-chip verification -- see
    // design_notes.md for the full transistor-level trace and the
    // .measure evidence): DFFRB's async RSTB only clears the SLAVE-stage
    // output, never the MASTER latch. The master latch is only ever
    // WRITTEN while CK=0 (it statically holds its last value through a
    // CK=1 transmission-gate feedback loop whenever CK=1), and RSTB never
    // touches it. So if CK(=scl here, since this bus-timed design clocks
    // straight off SCL) is already HIGH at the exact instant
    // rst_scl_domain releases, Q snaps to whatever value the never-yet-
    // written master latch happened to settle to at power-up, bypassing
    // the intended reset value entirely -- not just a corner case: this
    // is guaranteed to happen on EVERY start_pulse-triggered reset too,
    // since a real START is BY DEFINITION "SDA falls while SCL=1", so CK
    // is unavoidably HIGH at that release instant as well.
    //
    // Fix (gate-level only, no DFFRB/STDCELL change -- mirrors the
    // existing NOR2 cross-coupled "busy" SR latch above): stretch
    // rst_scl_domain so it stays asserted, even after its own raw
    // trigger condition (~rst_n | start_pulse) clears, until scl has
    // genuinely gone LOW at least once. This guarantees (a) CK is LOW
    // for the flops' *entire* reset-asserted window, giving the master
    // latch time to settle onto a real, defined D well before any clock
    // edge, and (b) reset only ever *releases* while CK is already LOW,
    // so the very next CK edge is an ordinary, well-defined rising edge,
    // never coincident with release itself. (b) also kills a second,
    // independent symptom found alongside the race: without the
    // stretch, "bit_cnt <= bit_cnt + 1"'s combinational D-logic (always
    // live, phase/bit_cnt/last_bit_pending all being simultaneously
    // reset) gets clocked in for free exactly at a release that
    // coincides with CK already being high, so bit_cnt reads 1 instead
    // of 0 before the very first real address bit even arrives; with
    // the stretch, no clock edge ever lands on the release instant, so
    // there is no such phantom count either.
    wire rst_scl_domain_raw = (~rst_n) | start_pulse;
    wire rst_stretch_clr    = (~rst_scl_domain_raw) & (~scl);
    wire rst_stretch_qn;
    wire rst_scl_domain_held;
    NOR2 u_rst_stretch_q  (.A(rst_stretch_clr),    .B(rst_stretch_qn),      .Y(rst_scl_domain_held), .VDD(VDD), .GND(GND));
    NOR2 u_rst_stretch_qn (.A(rst_scl_domain_raw), .B(rst_scl_domain_held), .Y(rst_stretch_qn),      .VDD(VDD), .GND(GND));
    // (SET=rst_scl_domain_raw, CLR=rst_stretch_clr are mutually exclusive
    // by construction -- CLR requires raw=0, SET requires raw=1 -- so this
    // SR latch never sees both active at once, same safety property as
    // the busy latch above; at t=0, rst_n=0 forces raw=1 unconditionally,
    // which alone resolves qn=0 and held=1 with no symmetric/ambiguous
    // initial condition, regardless of the latch's own power-up state.)

    wire rst_scl_domain = rst_scl_domain_raw | rst_scl_domain_held;   // active-high -> DFFR.RST
    wire scl_gated      = scl & (~rst_scl_domain);                    // -> DFFR.CK (reset-stretched scl)

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

    always @(posedge scl_gated or posedge rst_scl_domain) begin
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
