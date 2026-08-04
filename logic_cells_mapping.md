# 標準セルライブラリ（xschem）調査結果と非同期I2Cスレーブへの適用

参照元: `/TR-1um/libs.tech/xschem/TR-1um_5_stdcell`（`.sch`/`.sym`一式。xschem上の回路図・シンボルとして存在する標準セル一次
ソース。L=1U/1umプロセス）

## 1. 収録セル一覧

`.sym`の`dir=in/out/inout`属性から確認したピン方向。

| カテゴリ | セル | ピン | 備考 |
|---|---|---|---|
| インバータ | INV_X1/X2/X4/X8/X12/X16 | A(in), Y(out), VDD/GND(inout) | Xは駆動力違い |
| バッファ | BUF_X1/X2/X4/X8/X12/X16 | A(in), Y(out), VDD/GND(inout) | 非反転 |
| クロックバッファ | CLKBUF_X1/X2/X4/X8/X12/X16 | A(in), Y(out), VDD/GND(inout) | BUFと同ピン構成、クロックツリー用に別区分 |
| AND | AND2/3/4_X1 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| OR | OR2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| NAND | NAND2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| NOR | NOR2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| XOR/XNOR | XOR2, XNOR2 | A,B(in), Y(out), VDD/GND(inout) | |
| マルチプレクサ | MUX2 | A,B,S(in), Y(out), VDD/GND(inout) | 2:1セレクタ（S=選択） |
| 遅延セル | DEL1/2/4 | A(in), Y(out), VDD/GND(inout) | 段数違いで遅延量が異なる非反転バッファ |
| フリップフロップ | DFFR | CK,D,RST(in), Q,QB(out), VDD/GND(inout) | 非同期リセット付きD-FF（マスタスレーブ、CK正エッジ） |
| フリップフロップ | DFFS | CK,D,SET(in), Q,QB(out), VDD/GND(inout) | 非同期セット付きD-FF |

このライブラリには**SR/RSラッチに相当するセルは存在しない**
（`RS`という名前のセルは`STDLIB/LogicCells`側のGDSにのみ見えたが、
xschemの`.sch`/`.sym`には無く、回路図すら起票されていない未完成のセルと
判断し、以降は無視する）。

> **更新（v2実装確定後）**: 本章は当初「NAND2交差結合」で書いていたが、
> `i2c_slave_async.v`のv2実装では実際には**NOR2交差結合**を採用した
> （下記参照）。また、この章で提案していたマッピング方針は、Yosysによる
> 実際の論理合成（design_notes.md §7.5）で**そのまま実現可能であることを
> 確認済み**——DEL1・NOR2・INV_X1・DFFR・AND2/OR2/NAND2-4/NOR2-4/MUX2が
> 実際にYosys+ABCの合成結果に登場し、ラッチ推論や未マッピングセルは
> 一つも無かった。

## 2. 非同期I2Cスレーブ（`src/i2c_slave_async.v`）への適用

v2の`i2c_slave_async.v`は、非同期のSTART/STOP検出部とSCLエッジ駆動の
同期部を明確に分離した構成になっており、このライブラリへ素直にマッピング
できる（design_notes.md §3参照）。

### START/STOPコンディション検出（design_notes.md §3）

- 専用のSR/RSラッチセルが無いため、**NOR2 2個の交差結合**で標準的な
  NOR-SRラッチ（`busy`ラッチ、`start_pulse`でSET・`stop_pulse | ~rst_n`で
  CLEAR）を組んでいる。SCLがHIGH中のSDA立下り/立上りの検出自体は
  `DEL1`（SDAの遅延コピー`sda_d`を作る）＋組合せ論理
  （`scl & sda_d & ~sda_in`／`scl & ~sda_d & sda_in`）で構成し、レジスタは
  使わない。
  （当初案の「NAND2交差結合」でも論理的には等価な構成が可能だが、実装では
  極性の都合上NOR2交差結合を採用した。）

### ビットサンプル／シフトレジスタ／ビットカウンタ（ADDR, DATA_WR, DATA_RDの各ステート）

- Verilog上は「SCL立上りエッジでサンプル」としているが、ゲートレベルでは
  **`DFFR`のCKピンにSCLを直接接続**すれば、まさにその通りの動作になる
  （SCL自体がクロック — バスタイムド設計の本質そのもの）。
- `shreg`（8bitシフトレジスタ）、`bit_cnt`（4bitカウンタ）、`state`（3bit）は
  いずれも`DFFR`を並べて構成（リセットで0に落とす設計なので相性が良い）。
  `scl_q`/`sda_q`をリセットで1にする必要がある2本だけは`DFFS`を使うか、
  `DFFR`+出力INVで極性反転して1リセットを模擬する。
- SCLを複数の`DFFR`のCKに分配するファンアウトには`CLKBUF_X*`を使うのが適切
  （クロックツリー用セルなので、通常の`BUF`よりデューティ/スキュー特性が
  揃っている前提）。

### 次状態・出力ロジック（大きなcase文の組合せ回路部分）

- `AND2/3/4`, `OR2/3/4`, `NAND2/3/4`, `NOR2/3/4`, `XOR2`, `XNOR2`, `MUX2`,
  `INV_X*` が揃っており、標準的な論理合成（あるいは手マッピング）に必要な
  基本ゲートセットとして十分。
- アドレス一致判定（`shreg_next[7:1] == SLAVE_ADDR`）は、ビットごとの
  **XNOR2 + 7入力AND**（`AND4`+`AND3`等の組合せ）で構成する一致検出器が
  標準的な作り方。
- `DATA_RD`でのビット選択・ACK/NACK後の分岐は`MUX2`が使える
  （例: `state==DATA_RD_ACK`時の次状態選択など）。

### ACK駆動・SDA出力段

- `sda_oe`のオープンドレイン駆動は本ライブラリのロジックセルだけでは完結
  しない（NMOSプルダウンのみのIOバッファ/パッドセルが別途必要）。この
  xschemライブラリにはIOパッド/プルアップセルが無いため、パッドライブラリ
  側の確認が必要。

### スパイクフィルタ（UM10204 §3.1.2、50ns未満のノイズ抑制）／ACKタイミング調整

- `DEL1/DEL2/DEL4`が使える。単純な遅延線と現在値の比較（XNOR等での一致検出）
  でデグリッチ回路を構成するか、ACK駆動から次のSCL立上りまでの
  マージン調整（design_notes.md §4のtSU;DAT/tVD;ACK対応）に使う。

## 3. 気になった点（要確認）

- **`DFFR`の`RST`極性に注意**: `DFFR.sch`を追ってみたところ、`RST`ネットは
  ラッチの保持段に直接ゲートされたNMOS（M22）を1個追加する形で入っており、
  `RST=1（HIGH）`でノードをGND側に引く構成に見える。つまり**`RST`はActive-
  HIGHの可能性が高い**（`RSTB`のような反転ネーミングではない）。本設計の
  `i2c_slave_async.v`は`rst_n`（Active-LOW）前提なので、`DFFR`に直結する場合は
  `RST = ~rst_n`とインバータを挿む必要がある。トランジスタレベルの完全な
  追跡はしていないため、実際に使う前に簡単なSPICEシミュレーションで極性を
  確認することを推奨する。この仮定（Active-HIGH）は
  `src/stdcell_behavioral_stubs.v`のDFFRモデルおよび`TR1um_5_stdcell.lib`の
  `clear`定義にそのまま反映されており、Yosys合成・MyHDL検証はいずれもこの
  前提で通っている。SPICE確認の結果Active-LOWだった場合は、
  `i2c_slave_async.v`側で`DFFR.RST`への接続を`~rst_scl_domain`のように反転
  すれば追従できる（本体ロジックの変更は不要）。
- **DEL1の遅延マージン要件（iverilog実機シミュレーションで発覚）**:
  `busy`ラッチ（NOR2交差結合）をSETする`start_pulse`は`DEL1`の遅延幅ぶんの
  ワンショットパルスであり、これが`NOR2`2段の帰還ループ遅延と同程度だと
  パルスが競合で消えてSETに失敗しうることが実際に確認された
  （design_notes.md §7.6）。`DEL1`の実遅延は`NOR2`の実遅延に対し十分な
  マージン（目安数倍以上）を持つ必要があり、実SPICE特性化後に必ず
  再確認すること。
- **SR/RSラッチセルが存在しない**: `RS`という名前のセルはGDS
  （`STDLIB/LogicCells`側）にのみ存在し、xschemの回路図・シンボルとしては
  未起票。今後正式なラッチセルとして整備するか、NAND2交差結合で代替するかを
  決めておくとよい。
