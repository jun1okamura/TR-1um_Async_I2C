# 標準セルライブラリ（TR-1um_5_stdcell）調査結果と非同期I2Cスレーブへの適用

参照元（現行）: `LEF/TR-1um_STDCELL.lef`（物理LEF、`gen_lef.py`で`LEF/TR-1um_STDCELL.gds`
から自動生成）＋ 同ディレクトリ配下の各セルの`.sch`/`.sym`/`.extracted`
（xschem回路図・シンボル・LVS用抽出ネットリスト）。ネットリスト側の参照元は
`src/i2c_slave_async_net_v9_rowbuf.v`（現行v9、row buffer＋BUFTH挿入後、135
インスタンス、`schematic/tr_1um_i2c_slave_async_v9_lvs.spice`のLVS基準）。
`LEF/`配下のセットが唯一の正（物理GDS/LEF/schが完全に同期している）。

## 1. 収録セル一覧（LEFの`PIN`定義・現行29マクロ）

| カテゴリ | セル | ピン | 備考 |
|---|---|---|---|
| インバータ | INV_X1 | A(in), Y(out), VDD/GND(inout) | 駆動力バリアントはX1のみ |
| バッファ | BUF_X1/X2/X4/X16 | A(in), Y(out), VDD/GND(inout) | 非反転。**X2/X4/X16は現行v9ネットリストで未使用**（予備） |
| シュミットトリガ・バッファ | BUFTH | A(in), Y(out), VDD/GND(inout) | ヒステリシス付き入力バッファ。トップの`scl`/`sda_in`直後に2個挿入（`insert_bufth_scl_sda.py`）。**実チップ・回路図上は実在するが、IRSIMのternaryスイッチレベルソルバでは帰還ループを正しく解けないことが確認済みの恒久的制限**（design_notes §76.12-76.15）のため、`gen_irsim_sim_v9.py`のIRSIM用`.sim`生成時のみ`BUF_X1`へ機械的置換している（実レイアウト/LVSネットリスト自体は変更なし） |
| AND | AND2_X1 | A,B(in), Y(out), VDD/GND(inout) | 2入力のみ実使用（AND3_X1/AND4_X1は物理LEF/GDSまで存在するが現行ネットリストでは未使用、§3参照） |
| OR | OR2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| NAND | NAND2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| NOR | NOR2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| XOR/XNOR | XOR2/XNOR2 | A,B(in), Y(out), VDD/GND(inout) | 物理LEF/GDSは存在するが**現行ネットリストで未使用** |
| マルチプレクサ | MUX2 | S,A,B(in), Y(out), VDD/GND(inout) | 2:1セレクタ（`Y=S?B:A`） |
| 遅延セル | DEL1 | A(in), Y(out), VDD/GND(inout) | 非反転バッファ相当だが意図的遅延線として使用（DEL2/DEL4は依然Liberty上のプレースホルダのみ、物理LEF/GDSなし） |
| フリップフロップ | DFFRB | CK(clock in), D,RSTB(in), Q,QB(out), VDD/GND(inout) | **非同期リセット付きD-FF、`RSTB`はActive-LOW確定**（§2参照）。現行ネットリストで33個使用（§4） |
| フリップフロップ | DFF | CK(clock in), D(in), Q,QB(out), VDD/GND(inout) | リセット無しの素のD-FF。**現行v9ネットリストで未使用** |
| フリップフロップ | DFFS | CK(clock in), D,SETB(in), Q,QB(out), VDD/GND(inout) | セット付きD-FF。v8実験（`i2c_slave_async_net_v8dffs.v`）で物理LEF/GDSまで作成されたが、**現行v9ネットリストでは未使用**（極性は`SETB`側もActive-LOW、v8dffs時に確認） |
| 電源タップ | TAP2/TAP3 | VDD/GND(inout)のみ | 信号ピン無し。行内電源メッシュ用。現行v9ネットリストには登場しない（物理配置時にタップとして別途挿入） |
| フィラー | FILL2/FILL3 | VDD/GND(inout)のみ | 配置の隙間埋め |

このライブラリには依然として**SR/RSラッチに相当する専用セルは存在しない**。
本設計では`NOR2`2個の交差結合で代替している（§2参照、実装確定済み）。

## 2. `DFFRB`のリセット極性

実SPICE/回路図トレースにより**`RSTB`はActive-LOWであることが確定**している
（`TR1um_5_stdcell.lib`: `clear: "!RSTB"`）。これは本設計の`rst_n`
（Active-LOW）とそのまま極性が一致するため、**インバータを挟まず
`DFFRB.RSTB`に`rst_n`を直結できる**。

`DFFRB`は内部にマスタ側`QM`／スレーブ側`QS`の2つの記憶ノードを持つ
master-slaveトポロジーで、**QMはCK=0の間D入力に対して常時透過**（自己
保持ループが無い）のに対し、**QSはCK=0の間`net5=NOT(QB)`帰還ループで
自己保持される**という非対称構造を持つ。この違いはIRSIMでの実行時
force/releaseリセット手法に直接影響する重要な特性（design_notes
§89-96、`script/gen_irsim_cmd_v9.py`の`force_release_gated()`docstring
参照）。

## 3. Liberty上にのみ存在し、物理セル（LEF/GDS）がまだ無いセル

`script/gen_liberty.py`の`COMB_CELLS`/`FF_CELLS`には、Yosys合成が万一これらを
要求した場合にエラーで止まらないよう、以下がプレースホルダとして登録されている
（**LEF/GDSの裏付けが無いため、実際に合成結果に出現した場合は追加の物理セル作成が
必要**）:

- `DEL2` / `DEL4`（DEL1の多段版）

`AND3_X1`/`AND4_X1`・`XOR2`/`XNOR2`・`DFFS`は当初この節のプレースホルダ
だったが、その後の作業で物理LEF/GDSまで作成済み（§1参照）。ただし
いずれも現行v9ネットリストの合成結果には一度も出現していない
（§4参照、実使用は無い）。

現行v9ネットリスト（`src/i2c_slave_async_net_v9_rowbuf.v`、135インスタンス）は
`DEL2`/`DEL4`を一切使用しておらず、実在する物理セルのみで合成が閉じている。

## 4. 非同期I2Cスレーブ（`src/i2c_slave_async_net_v9_rowbuf.v`）での実使用状況

構造Verilog（row buffer＋BUFTH挿入後、135インスタンス）でのセル使用数:

| セル | 使用数 | セル | 使用数 |
|---|---:|---|---:|
| DFFRB | 33 | NAND3 | 3 |
| MUX2 | 24 | OR4 | 2 |
| NAND2 | 22 | NOR4 | 2 |
| NOR2 | 15 | BUFTH | 2 |
| NOR3 | 8 | AND2_X1 | 2 |
| BUF_X1 | 8 | OR3 | 1 |
| INV_X1 | 6 | DEL1 | 1 |
| OR2 | 5 | AND4_X1 | 1 |

ラッチ推論・未マッピングセルは無く、§3のプレースホルダセルへの依存も無い。
BUF_X2/X4/X16・DFF（無リセット版）・DFFS・XOR2/XNOR2・AND3_X1・
TAP2/TAP3も未使用（TAP2/TAP3は論理合成の対象外で、物理配置時に電源
タップとして別途挿入される）。

`DFFRB`33個は非同期リセットグループが2系統に分かれる（design_notes
§89以降で構造確認済み）: Group-A（24個、`RSTB`=`NOR2(~rst_n,
start_pulse)`）／Group-B（9個、`RSTB`=`busy AND rst_n`）。24+9=33で一致。

### START/STOPコンディション検出（design_notes.md §3）

- 専用のSR/RSラッチセルが無いため、**NOR2 2個の交差結合**で標準的な
  NOR-SRラッチ（`busy`ラッチ、`start_pulse`でSET・`stop_pulse | ~rst_n`で
  CLEAR）を組んでいる。SCLがHIGH中のSDA立下り/立上りの検出自体は
  `DEL1`（SDAの遅延コピー`sda_d`を作る）＋組合せ論理
  （`scl & sda_d & ~sda_in`／`scl & ~sda_d & sda_in`）で構成し、レジスタは
  使わない。

### ビットサンプル／シフトレジスタ／ビットカウンタ

- `DFFRB`のCKピンに（バッファ経由で）SCLを直接接続することで、SCL自体が
  クロックとして働くバスタイムド設計を実現している。`RSTB`には`rst_n`を
  極性反転なしで直結（§2）。
- `shreg`（8bitシフトレジスタ）、`bit_cnt`（4bitカウンタ）、`state`は
  いずれも`DFFRB`を並べて構成。
- トップの`scl`/`sda_in`はまず`BUFTH`（シュミットトリガ）を通し、その後
  各行ごとに`BUF_X1`でファンアウトしてから配線する構成
  （`insert_bufth_scl_sda.py`／`insert_row_buffers.py`）。

### 次状態・出力ロジック（組合せ回路部分）

- `MUX2`, `NAND2/3`, `NOR2/3/4`, `INV_X1`, `OR2/3/4`, `AND2_X1/4_X1`が実際の
  合成結果の大半を占める（上記使用数表）。XOR/XNORは合成結果に一度も
  現れていない（アドレス一致判定等もAND/OR/NAND/NORの組合せに帰着している）。

### ACK駆動・SDA出力段

- `sda_oe`のオープンドレイン駆動そのものは本ライブラリの論理セルだけでは
  完結せず、GIO（`OSS_FRAME_GIO`、`FRAME/`配下）側のIOバッファ/パッドセルで
  実現している（トップレベル統合、design_notes §75）。

### スパイクフィルタ／タイミング調整

- `DEL1`が実際に1個使用されている（意図的遅延線、`sda_d`生成用）。

## 5. 既知の注意点

- **DEL1の遅延マージン要件**（iverilog実機シミュレーションで発覚）:
  `busy`ラッチ（NOR2交差結合）をSETする`start_pulse`は`DEL1`の遅延幅ぶんの
  ワンショットパルスであり、これが`NOR2`2段の帰還ループ遅延と同程度だと
  パルスが競合で消えてSETに失敗しうることが実際に確認された
  （design_notes.md §7.6）。`DEL1`の実遅延は`NOR2`の実遅延に対し十分な
  マージン（目安数倍以上）を持つ必要があり、`TR1um_5_stdcell.lib`は
  現状プレースホルダ値（実SPICE特性化なし、`script/gen_liberty.py`冒頭の
  注記参照）なので、実SPICE特性化後に必ず再確認すること。
- **BUFTHはIRSIM上でのみBUF_X1へ置換される**（§1参照）: 実レイアウト・LVS
  ネットリストには本物のBUFTHが2個存在する。IRSIMのチップレベル動作
  検証結果を見る際は、この置換がシミュレーションモデル限定の措置である
  ことを常に念頭に置くこと（実シリコンの欠陥ではない）。
- **SR/RSラッチセルは依然として存在しない**: `NOR2`交差結合での代替は
  実装確定済みだが、専用ラッチセルとして正式に起票するかは未定。
