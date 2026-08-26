# 標準セルライブラリ（TR-1um_5_stdcell）調査結果と非同期I2Cスレーブへの適用

参照元（現行）: `LEF/TR-1um_STDCELL.lef`（物理LEF、`gen_lef.py`で`LEF/TR-1um_STDCELL.gds`
から自動生成）＋ 同ディレクトリ配下の各セルの`.sch`/`.sym`/`.extracted`
（xschem回路図・シンボル・LVS用抽出ネットリスト）。旧版はxschemライブラリ
`TR-1um_5_stdcell`を直接調査した内容だったが、その後セット自体が再構築されており
（design_notes.md §35以降）、現在は`LEF/`配下のこのセットが唯一の正（物理GDS/LEF/
schが完全に同期している）。

## 1. 収録セル一覧（LEFの`PIN`定義・現行23マクロ）

| カテゴリ | セル | ピン | 備考 |
|---|---|---|---|
| インバータ | INV_X1 | A(in), Y(out), VDD/GND(inout) | 駆動力バリアントはX1のみ |
| バッファ | BUF_X1/X2/X4/X16 | A(in), Y(out), VDD/GND(inout) | 非反転。**X2/X4/X16は現行v7ネットリストで未使用**（予備） |
| シュミットトリガ・バッファ | BUFTH | A(in), Y(out), VDD/GND(inout) | ヒステリシス付き入力バッファ。トップの`scl`/`sda_in`直後に挿入（design_notes BUFTH章、`insert_bufth_scl_sda.py`） |
| AND | AND2_X1 | A,B(in), Y(out), VDD/GND(inout) | 2入力のみ物理セル化済み（AND3/AND4はLiberty上のプレースホルダのみ、§3参照） |
| OR | OR2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| NAND | NAND2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| NOR | NOR2/3/4 | A,B[,C[,D]](in), Y(out), VDD/GND(inout) | |
| マルチプレクサ | MUX2 | S,A,B(in), Y(out), VDD/GND(inout) | 2:1セレクタ（`Y=S?B:A`） |
| 遅延セル | DEL1 | A(in), Y(out), VDD/GND(inout) | 非反転バッファ相当だが意図的遅延線として使用（DEL2/DEL4はLiberty上のプレースホルダのみ） |
| フリップフロップ | DFFRB | CK(clock in), D,RSTB(in), Q,QB(out), VDD/GND(inout) | **非同期リセット付きD-FF、`RSTB`はActive-LOW確定**（§2参照。旧`DFFR`から改名） |
| フリップフロップ | DFF | CK(clock in), D(in), Q,QB(out), VDD/GND(inout) | リセット無しの素のD-FF。**現行v7ネットリストで未使用** |
| 電源タップ | TAP2/TAP3 | VDD/GND(inout)のみ | 信号ピン無し。行内電源メッシュ用。現行v7ネットリストには登場しない（物理配置時にタップとして別途挿入） |
| フィラー | FILL2/FILL3 | VDD/GND(inout)のみ | 配置の隙間埋め（design_notes §61でスキーマティックにも追加） |

このライブラリには依然として**SR/RSラッチに相当する専用セルは存在しない**。
本設計では`NOR2`2個の交差結合で代替している（§2参照、実装確定済み）。

## 2. `DFFRB`のリセット極性（旧版の未確認事項を解消）

旧版では`DFFR.sch`のトランジスタレベル追跡が不完全で、リセット極性
（Active-HIGH/LOW）を「要確認」としていた。その後の実SPICE/回路図トレースにより
**`RSTB`はActive-LOWであることが確定**している
（`TR1um_5_stdcell.lib`: `clear: "!RSTB"`、`script/gen_liberty.py`のコメント
「DFFR.RSTB confirmed active-low from the real schematic/SPICE trace」）。

これは本設計の`rst_n`（Active-LOW）とそのまま極性が一致するため、
**インバータを挟まず`DFFRB.RSTB`に`rst_n`を直結できる**（旧版で懸念していた
反転挿入は不要と判明）。

## 3. Liberty上にのみ存在し、物理セル（LEF/GDS）がまだ無いセル

`script/gen_liberty.py`の`COMB_CELLS`/`FF_CELLS`には、Yosys合成が万一これらを
要求した場合にエラーで止まらないよう、以下がプレースホルダとして登録されている
（**LEF/GDSの裏付けが無いため、実際に合成結果に出現した場合は追加の物理セル作成が
必要**）:

- `AND3_X1` / `AND4_X1`
- `XOR2` / `XNOR2`
- `DEL2` / `DEL4`（DEL1の多段版）
- `DFFS`（セット付きD-FF。旧ライブラリ再構築時に脱落。極性未確認）

現行v7ネットリスト（`src/i2c_slave_async_net_v7.v`、154インスタンス）は
これらを一切使用しておらず、実在する物理セルのみで合成が閉じている
（下記§4参照）。

## 4. 非同期I2Cスレーブ（`src/i2c_slave_async_net_v7.v`）での実使用状況

Yosys+ABCによる実際の論理合成結果（154インスタンス）でのセル使用数:

| セル | 使用数 | セル | 使用数 |
|---|---:|---|---:|
| DFFRB | 33 | NOR3 | 3 |
| NAND2 | 29 | OR3 | 2 |
| NOR2 | 19 | NAND4 | 2 |
| MUX2 | 19 | BUFTH | 2 |
| INV_X1 | 11 | OR4 | 1 |
| BUF_X1 | 8 | DEL1 | 1 |
| AND2_X1 | 8 | | |
| NAND3 | 6 | | |
| OR2 | 5 | | |
| NOR4 | 5 | | |

ラッチ推論・未マッピングセルは無く、§3のプレースホルダセルへの依存も無い。
BUF_X2/X4/X16・DFF（無リセット版）・TAP2/TAP3も未使用（TAP2/TAP3は論理合成の
対象外で、物理配置時に電源タップとして別途挿入される）。

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
  （design_notes BUFTH章、`insert_bufth_scl_sda.py`）。

### 次状態・出力ロジック（組合せ回路部分）

- `AND2_X1`, `OR2/3/4`, `NAND2/3/4`, `NOR2/3/4`, `MUX2`, `INV_X1`が実際の
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
- **SR/RSラッチセルは依然として存在しない**: `NOR2`交差結合での代替は
  実装確定済みだが、専用ラッチセルとして正式に起票するかは未定。
