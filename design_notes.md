# I2Cスレーブ 非同期ロジック回路 設計ノート

参照仕様: NXP `UM10204` *I2C-bus specification and user manual*, Rev. 5.0J（2012年、日本語版）

> **v2アーキテクチャへの更新（本ノート全体に影響）**: `i2c_slave_async.v` は
> Yosysでの論理合成不能（`ERROR: Found non-synthesizable event list!`）を機に
> ゲート合成可能な構成へ全面的に書き直した（以下 v2）。本ノートの §2/§3 は
> v2の実装に合わせて更新済み。v2の合成結果・検証方法は §7.5 を参照。

## 1. 設計方針

本設計にはシステムクロック（`clk`）が一切ない。すべての状態遷移は SCL / SDA
そのもののエッジによって駆動される（バスタイムド／自己タイミング回路）。これは
仕様書が定義しているプロトコルの構造そのものと一致する。

| 仕様書の規定 | 対応する回路動作 |
|---|---|
| 3.1.3 データの有効性 — SCL=HIGH中はSDA安定、変化はSCL=LOW中のみ | ビットのサンプルはSCL立上りエッジ、出力の変更はSCL立下りエッジで行う |
| 3.1.4 START/STOPコンディション — SCL=HIGH中のSDA遷移で定義 | SDAのエッジをSCLレベルでゲートして検出（NANDラッチ相当、図5） |
| 3.1.5 バイトフォーマット — 8bit・MSBファースト | 8bitシフトレジスタ、ビットカウンタでMSBファーストを保証 |
| 3.1.6 ACK/NACK — 9番目のクロックでレシーバがSDAをLOWに保持 | ACK/NACK専用ステート（ADDR_ACK / DATA_WR_ACK / DATA_RD_ACK） |
| 3.1.9 クロックストレッチ（オプション） | 未実装（本スレーブはSCLを駆動しない）。実装する場合は §5 参照 |

## 2. ステートマシン（v2: `phase` エンコーディング）

```
PH_ADDR --[8bit]--> PH_ADDR_ACK --+--(addr match, R/W=0)--> PH_DATA_WR --[8bit]--> PH_DATA_WR_ACK --> PH_DATA_WR ...
                                   +--(addr match, R/W=1)--> PH_DATA_RD --[8bit]--> PH_DATA_RD_ACK --(master ACK)--> PH_DATA_RD ...
                                   +--(no match)------------> PH_IGNORE                              --(master NACK)--> PH_IGNORE
任意のphase --(start_pulse)--> PH_ADDR（非同期RESET, §3参照）
busy=0（STOP後）--> sda_oeドメインも非同期リセット
```

- `PH_ADDR`（=リセット値 `3'b000`）: アドレス+R/Wビット（8bit）をSCL立上りで
  シフトイン。8bit目でアドレス一致判定（`addr_ok`）とR/Wビット（`rw_bit`）を
  確定し `PH_ADDR_ACK` へ。
- `PH_ADDR_ACK` / `PH_DATA_WR_ACK`: SCL立下りで`sda_oe`をLOWに駆動（ACK）。
  アドレス不一致時は駆動せず`PH_IGNORE`へ（NACK、STOP待ち）。
- `PH_DATA_WR`: マスタ→スレーブのデータ8bitをシフトイン。8bit目で`rx_data`
  確定、`rx_valid`は`phase==PH_DATA_WR_ACK`の間アサート。
- `PH_DATA_RD`: スレーブ→マスタ。SCL立下りごとに`tx_data`（アプリ側が用意
  した値）をMSBファーストでシフトアウト。
- `PH_DATA_RD_ACK`: マスタが返すACK/NACKをSCL立上りでサンプルし、ACK
  （`sda_in==0`）なら`PH_DATA_RD`へ戻って次バイト送出、NACKなら
  `PH_IGNORE`へ（仕様3.1.6の条件5と一致）。
- `PH_IGNORE`: アドレス不一致／NACK後、次のSTOPまたはSTARTを待つだけの状態。

`phase`の値を`PH_ADDR = 3'b000`（＝レジスタのリセット値そのもの）に選んで
あるのがv2の設計上の要点で、これにより START検出時は「非同期RESETを1本
かけるだけ」で `PH_ADDR` に戻せる（§3参照、DFFRが非同期SETを持たないため）。

## 3. 実装上の重要な注意（v2: 非同期部と同期部の分離）

v1（旧版）は START/STOP検出とビット処理を単一の`always`ブロックに統合し、
SCL/SDAの1つ前の値をシャドウレジスタとして保持するレベル比較方式だったが、
Yosysはこれを合成不能と判定した（`always @(scl or sda_in or negedge rst_n)`
のようにレベル感度とエッジ感度が混在する`always`は、純粋な`@*`組合せ回路
としても単一エッジの同期回路としても認識されないため）。

v2ではこれを次の3つのドメインに明確に分離した:

1. **非同期のSTART/STOP検出**（クロックなし）: `DEL1`遅延セルでSDAの
   遅延コピー`sda_d`を作り、`scl & sda_d & ~sda_in`（SDA 1→0 かつ SCL=1）
   / `scl & ~sda_d & sda_in`（SDA 0→1 かつ SCL=1）の組合せ論理だけで
   `start_pulse`/`stop_pulse`を検出する。これはUM10204 3.1.4の定義その
   ものであり、レジスタを一切使わない。
2. **`busy`ラッチ**: `NOR2`を2個クロスカップルしたSRラッチ
   （`start_pulse`でSET、`stop_pulse | ~rst_n`でCLEAR）。ゲートレベルで
   非同期回路として素直に書ける形。**旧`logic_cells_mapping.md`のNAND2案
   から、実装ではNOR2クロスカップルに変更されている**（両方式とも
   UM10204図5相当のSRラッチだが、極性の都合でNOR2を採用）。
3. **SCLエッジ駆動の同期部**: `phase`/`bit_cnt`/`shreg`/`addr_ok`/`rw_bit`
   /`rx_data`はSCL立上りエッジ（`posedge scl`）で駆動される`DFFR`
   （非同期RESET付きD-FF）バンク。`sda_oe`/`txreg`はSCL立下りエッジ
   （`INV_X1`で`scl`を反転した`scl_n`の`posedge`）で駆動される別の
   `DFFR`バンク。SCLそのものが「クロック」であり、これはバスタイムド
   設計の本質と一致する。START時は`rst_scl_domain = ~rst_n | start_pulse`
   で`PH_ADDR`（＝リセット値）へ非同期に戻し、STOP後（`busy`落下）は
   `rst_sdaoe_domain = ~rst_n | ~busy`で`sda_oe`側をリセットする。

この分離により、各`always`ブロックは「純粋な非同期組合せ」または「単一
エッジ+単一非同期リセットのDFFRパターン」のいずれかとなり、Yosysの
`proc`/`dfflegalize`/`dfflibmap`/`abc`パスで問題なく合成できることを
確認済み（§7.5）。

## 4. タイミング仕様との関係（表10, Standard/Fast/Fast-mode Plus）

本FSMの正しさはクロック周波数に依存しない（イベント駆動のため）。しかし
実際にゲート/ラッチで実装する際は、以下の値より内部遅延（ゲート伝搬遅延の
合計）が十分短いことを確認する必要がある。

| パラメータ | Standard-mode (最小) | Fast-mode (最小) | Fast-mode Plus (最小) |
|---|---|---|---|
| tHD;STA（START保持時間） | 4.0 µs | 0.6 µs | 0.26 µs |
| tLOW（SCL LOW期間） | 4.7 µs | 1.3 µs | 0.5 µs |
| tHIGH（SCL HIGH期間） | 4.0 µs | 0.6 µs | 0.26 µs |
| tSU;DAT（データセットアップ） | 250 ns | 100 ns | 50 ns |
| tSU;STA / tSU;STO | 4.7 µs / 4.0 µs | 0.6 µs / 0.6 µs | 0.26 µs / 0.26 µs |

特に重要: ACK駆動（SCL立下り→`sda_oe`変化）の内部遅延は、次のSCL立上り
（マスタがACKをサンプルする瞬間）までに収まっていなければならない
（`tSU;DAT`/`tVD;ACK`相当）。

## 5. パワーオンリセット必須（重要）

このFSMは`clk`を持たないため、内部レジスタ（`state`, `sda_oe`, `scl_q`,
`sda_q`, `busy`など）が確定値を持つ経路は`if (!rst_n)`分岐のみである。
実機・実シミュレーションでは全レグが不定値（X）で起動するため、**`rst_n`の
ローパルスを必ず与えること**。これを怠ると`scl_q`/`sda_q`がXのまま伝播し、
STARTすら検出できず全機能が停止する（4-state Verilogシミュレータで実際に
発生し、`i2c_slave_async_tb.v`で修正済み）。

MyHDLモデル側で最初の検証がこの問題を検出できなかったのは、MyHDLの
`Signal(...)`がPython側で明示的な初期値を持ち、Xに相当する不定状態が
存在しない2値（état）シミュレーションだったため。実チップでは相当する
パワーオンリセット（POR）回路が必須であることを`i2c_slave_async.v`利用時の
前提条件として明記する。

## 6. 既知の制限と拡張ポイント

- 7bitアドレッシングのみ（10bitアドレッシング未対応、§3.1.11参照）
- クロックストレッチ未対応（`scl`は入力のみ、スレーブはSCLを駆動しない）
- データ受信は常にACKする設計（アプリ側でNACKしたい場合は`DATA_WR_ACK`の
  `sda_oe`駆動を外部フラグでゲートする）
- マルチマスタ調停（§3.1.7/3.1.8）はスレーブロジックの範囲外のため未実装
- SDA/SCL入力にはUM10204 §3.1.2のスパイクフィルタ（50ns未満を抑制）を
  本モジュールの手前に別途置くことを推奨（本モジュールはすでに整形された
  信号を受け取る前提）

## 7. 検証方法

開発時のサンドボックスには `iverilog` / `Verilator` が無かったため、同一の
ステートマシンを MyHDL（Python）で2種類実装し、Pythonのイベント駆動
シミュレータ上でバス機能モデル（マスタBFM）と接続してまず検証した。

- `i2c_slave_async_model.py` : 複数always-block構成での初期モデル
  （`test_i2c_slave_async.py`, `test_i2c_slave_async_negative.py` で検証）
- `i2c_slave_async_model_v2.py` : `i2c_slave_async.v` と同一の単一プロセス
  ／シャドウレジスタ構成（実際に納品するRTLの構造そのもの）
  （`test_v2_positive.py`, `test_v2_negative.py` で同一シナリオを再検証）
- 両モデルとも以下すべてPASS:
  - 書き込み: START→ADDR+W→ACK→0xA5→ACK→STOP、`rx_data`確認
  - 読み出し: START→ADDR+R→ACK→0x3Cシフトアウト→マスタNACK→STOP
  - アドレス不一致: START→誤アドレス→NACK確認、`addr_match`が立たないこと

その後 `i2c_slave_async_tb.v` をローカル環境の`iverilog`で実行したところ、
全項目FAILとなった。原因は**テストベンチが`rst_n`のリセットパルスを
一度も発行していなかったこと**（§5参照）。MyHDLは2値シミュレーションの
ため問題が表面化しなかったが、4-state Verilogでは全レジスタがXのまま
デッドロックし、STARTすら検出できなかった。テストベンチにリセットパルスを
追加して修正。

リセットパルス追加後も、STARTに依存する項目のみ再びFAILした（`busy`が
一度も1にならない等）。原因は`i2c_slave_async.v`側の**レースコンディション**:
`start_cond`/`stop_cond`/`scl_rise`/`scl_fall`を独立した`wire = ...`の連続
代入として宣言していたが、その`always`ブロック自体も同じ`scl`/`sda_in`の
変化で起動するため、「wireの再評価」と「always内でそのwireを読む」の間の
実行順序はIEEE Verilogの仕様上保証されない。一部のシミュレータ（iverilogを
含む）では、always側が遷移前（stale）の値を読んでしまい、START/STOP検出が
恒常的に失敗する。MyHDLモデルはこれらの条件を`@always`関数内でPythonの
ローカル変数として直接計算していたため、この種のレースが最初から存在せず、
再現できなかった。

**修正**: `start_cond`等の外部wireを廃止し、`scl_q`/`sda_q`/`scl`/`sda_in`を
always内で直接読んでインライン評価するように変更（同じプロセスが所有する
レジスタ／トリガ信号を直接読むだけなので、レース条件が原理的に発生しない）。

この2件はいずれも実際に`iverilog`で実行して初めて判明したバグであり、
MyHDL（2値・Python内オブジェクト直接評価）だけでは検出できなかった。
修正後、ユーザー環境（実機`iverilog`）で以下コマンドを実行し、
**14項目全てPASS**を確認済み（write/read/アドレス不一致の3シナリオ全て）。

```
cd src
iverilog -o sim i2c_slave_async.v i2c_slave_async_tb.v && vvp sim
```

MyHDLモデルはPythonの2値シミュレーションであるため、今後この設計を変更する
際はMyHDLでの動作確認だけでなく、**必ず実際のVerilogシミュレータ（iverilog等）
で再実行して確認すること**。X不定値の伝播やイベント順序に依存するレース
条件は2値シミュレーションでは原理的に再現できない。

## 7.5 v2: Yosys論理合成とその検証

`i2c_slave_async.v`（v2）を実スタンダードセル（`TR1um_5_stdcell`）へ
論理合成できることを、`yowasp-yosys`（WebAssembly版Yosys、`pip install
yowasp-yosys`でネットワーク制限下でも導入可能）を用いて確認した。

```
yowasp-yosys -p "
  read_verilog i2c_slave_async.v
  hierarchy -top i2c_slave_async -keep_portwidths
  proc; opt
  techmap; opt
  dfflegalize -cell \$_DFF_PP0_ 0
  dfflibmap -liberty TR1um_5_stdcell.lib
  abc -liberty TR1um_5_stdcell.lib
  write_verilog i2c_slave_async_net.v"
```

- `techmap; opt` を `dfflegalize`/`dfflibmap` の前に挟む必要がある。
  Yosysの`proc`直後は粗粒度の`$adff`/`$adffe`セルのままで、`dfflegalize`
  /`dfflibmap`は細粒度の`$_DFF_*`セルしか見ないため、techmapで一度
  細粒度化しないと`DFFR`へのマッピングが（エラーなく）失敗する。
- ABC (`abc -liberty ...`) はYosys本体の`read_liberty`より厳格なLiberty
  パーサを持ち、`intrinsic_rise`/`intrinsic_fall`のようなスカラー遅延
  記法を受け付けない。`lu_table_template`＋`cell_rise`/`cell_fall`/
  `rise_transition`/`fall_transition`のテーブル形式で書き直す必要が
  あった（`TR1um_5_stdcell.lib`参照）。
- 合成結果（`i2c_slave_async_net.v`, 1604行）: **33×DFFR**（`phase`/
  `bit_cnt`/`shreg`/`addr_ok`/`rw_bit`/`rx_data_r`/`sda_oe_r`/`txreg`の
  合計ビット数と一致）、組合せ部は7×AND2_X1・30×NAND2・6×NAND3・
  2×NAND4・18×NOR2・3×NOR3・5×NOR4・6×OR2・2×OR3・1×OR4・19×MUX2・
  11×INV_X1、および元RTLで直接インスタンス化していた1×DEL1・2×NOR2
  （busyラッチ）・1×INV_X1。ラッチ（インファード）や未マッピングセルは
  ゼロ。XOR2/XNOR2/BUF_X1/DFFSは今回未使用。
- **ABCが生成した144個のセルインスタンスには`.VDD`/`.GND`接続が一切付与
  されない**（ABCのブール最適化は電源ピンを意識しないため）。これは
  Pythonの正規表現post-processスクリプトで全インスタンスに
  `.VDD(VDD), .GND(GND)`を追記して補完済み（`i2c_slave_async_net.v`は
  補完後の版）。
- `TR1um_5_stdcell.lib` は**タイミング未特性化のプレースホルダ**
  （固定値の2x2テーブル）。論理・接続の正しさの確認が目的で、STA/
  タイムクロージャ/テープアウト用途には使えない。実SPICE特性化後に
  差し替えが必要。
- 形式的等価性検証（合成前後のSAT/帰納法によるequivalenceチェック、
  Yosysの`equiv_make`/`equiv_induct`）はサンドボックスのbashツールが
  45秒のハードタイムアウトを持ち、かつバックグラウンドプロセスが
  ツール呼び出しをまたいで維持できない制約のため、**未実施・断念**。
  代わりに以下の2点を合成の妥当性の根拠とする:
  1. v2アーキテクチャと同一構造のMyHDLモデル
     （`script/i2c_slave_async_model_v3.py`）による機能検証
     （`script/test_v3_positive.py` / `test_v3_negative.py`、write/read/
     アドレス不一致の3シナリオ全てPASS）。
  2. Yosys合成がエラー・ラッチ推論・未マッピングセルなしでクリーンに
     完了していること。
- ローカル`iverilog`での実4値シミュレーション確認は、v2の
  `i2c_slave_async.v`本体に対しても**実施済み**（14項目全PASS、§7.6）。
  v1同様、MyHDLの2値シミュレーションでは検出できない実バグ（今回は
  `DEL1`/`NOR2`遅延が同値だったことによるSETパルス競合、§7.6）が実
  `iverilog`実行で初めて発覚しており、この種の確認がこの設計にとって
  引き続き重要であることが再確認された。実行するには
  `src/stdcell_behavioral_stubs.v`（DEL1/NOR2/INV_X1/DFFR等の
  ビヘイビアモデル、タイミング精度なし）を`i2c_slave_async.v`・
  `i2c_slave_async_tb.v`と一緒にコンパイルする:
  ```
  cd src
  iverilog -o sim i2c_slave_async.v stdcell_behavioral_stubs.v i2c_slave_async_tb.v && vvp sim
  ```
  同じ`stdcell_behavioral_stubs.v`を使えば、合成後の`i2c_slave_async_net.v`
  自体をiverilogで直接シミュレートすることも可能（ゲートレベル確認）。

## 7.6 v2: iverilog実機シミュレーションで発覚したbusyラッチのパルス競合

`stdcell_behavioral_stubs.v`（全セル一律 `#1` 遅延）で `i2c_slave_async.v`
（v2）を実際に`iverilog`実行したところ、以下5項目がFAILした
（addr_match/rw/rx_data等は全てOK）:

```
FAIL: busy asserted after START
FAIL: slave ACKed matching address (write)
FAIL: slave ACKed data byte
FAIL: slave ACKed matching address (read)
FAIL: read byte == 0x3C
```

**根本原因**: `start_pulse`/`stop_pulse`は`DEL1`の遅延時間ぶんだけの幅を
持つワンショットパルスである（`sda_d`が`sda_in`に追いつくまでの間だけ
`scl & sda_d & ~sda_in`等が真になる）。このパルスが`busy`ラッチ
（`NOR2`2個の交差結合、`u_lat_qn`→`u_lat_q`で1往復＝ゲート2段）を
確実にSET/RESETするには、**パルス幅がラッチの帰還ループ遅延より
十分広い**必要がある。ところがスタブモデルは`DEL1`も`NOR2`もどちらも
`#1`と同じ遅延値にしていたため、パルス幅（=DEL1遅延）とラッチ内部の
1ゲート遅延がちょうど一致し、Verilogのinertial delay（幅がdelay値と
同程度以下のパルスは出力に伝播しないことがある）により**SETパルスが
ラッチに届く前に消えてしまい、`busy`が一度もHIGHにならない**という
競合が発生した。

`busy`がHIGHにならないと、`rst_sdaoe_domain = ~rst_n | ~busy`が
トランザクション中ずっとアサートされたままになり、`sda_oe`/`txreg`用の
DFFRバンク（ACK駆動・読み出しデータ駆動を担当）が常時非同期リセット
状態に固定される。一方`phase`/`shreg`/`addr_ok`等のSCL(posedge)ドメインは
`busy`に依存しないため正常に動作し続けた——これが「addr_match/rw/rx_data
は正しいのに、ACK駆動と読み出しデータ駆動だけが軒並み失敗する」という
FAILパターンの説明になる（`busy cleared after STOP`等のチェックは、
`busy`が最初から一度もHIGHにならないため見かけ上OKになっただけで、
実際にはSET/CLEAR動作を検証できていなかった）。

**対策**: `stdcell_behavioral_stubs.v`の`DEL1`遅延を`#1`→`#4`
（`DEL2`/`DEL4`もそれぞれ`#8`/`#16`に）拡大し、パルス幅をラッチの
ゲート遅延（`#1`のまま）に対して十分（4倍）広く確保した。これはRTL
（`i2c_slave_async.v`）自体の構成は変更せず、シミュレーション用スタブの
遅延値のみを実際の設計意図（ヘッダコメント「real DEL1 is intentionally
slower than a plain buffer」）に合わせて修正したもの。

**確認**: 修正後、ユーザー環境の`iverilog`で`i2c_slave_async.v` +
`stdcell_behavioral_stubs.v` + `i2c_slave_async_tb.v`を再実行し、
**write/read/アドレス不一致の3シナリオ・14項目全てPASS**を確認済み
（`busy asserted after START`を含む、上記でFAILしていた5項目も全てOK
に変わったことを確認）。これによりv2 RTLはMyHDL(model_v3)・Yosys合成
（クリーン、ラッチ推論なし）・実iverilog4値シミュレーションの3方面
すべてで検証済みとなった。

**重要（実シリコンへの申し送り事項）**: これは単なるシミュレーション上の
アーティファクトではなく、**実際の物理設計でも成立させる必要がある
タイミング制約**である——`DEL1`の実遅延は、`busy`ラッチを構成する
`NOR2`2段の帰還ループ遅延に対して十分なマージン（目安: 数倍以上）を
持つ必要がある。`TR1um_5_stdcell.lib`が実SPICE特性値に置き換わった際、
`DEL1`と`NOR2`の実遅延比を確認し、このマージンが確保されているかを
再検証すること。不足していれば`DEL1`のインスタンスを`DEL2`/`DEL4`に
変更するなどして対応する。

## 8. ファイル一覧

- `i2c_slave_async.v` — 納品RTL本体（v2: 非同期SR部＋SCLエッジ同期部）
- `i2c_slave_async_net.v` — Yosys+ABC合成済み構造Verilogネットリスト
  （`TR1um_5_stdcell.lib`ベース、VDD/GND補完済み）
- `i2c_slave_async_tb.v` — ローカルシミュレータ用テストベンチ（VDD/GND配線済み）
- `stdcell_behavioral_stubs.v` — iverilogで`i2c_slave_async.v`/
  `i2c_slave_async_net.v`をコンパイルするためのセルビヘイビアモデル
  （非タイミング精度）
- `../TR1um_5_stdcell.lib` — プレースホルダLiberty（未特性化、論理合成用）
- `i2c_slave_async_model.py` / `i2c_slave_async_model_v2.py` — 旧版（v1）検証用MyHDLモデル
- `i2c_slave_async_model_v3.py` — v2アーキテクチャに対応するMyHDLモデル
- `test_i2c_slave_async.py` / `test_i2c_slave_async_negative.py` — model.py用テスト（実行済み・全PASS）
- `test_v2_positive.py` / `test_v2_negative.py` — model_v2.py用の同一テスト（実行済み・全PASS）
- `test_v3_positive.py` / `test_v3_negative.py` — model_v3.py用の同一テスト（実行済み・全PASS）
- `../schematic/i2c_slave_async_net.sch` — `i2c_slave_async_net.v`から自動生成したxschem回路図、ネットラベル方式（§9参照）
- `gen_schematic.py` — 上記（ラベル方式）回路図の生成スクリプト
- `../schematic/i2c_slave_async_net_routed.sch` — 同、実配線版（§10参照）
- `gen_schematic_routed.py` — 上記（配線版）回路図の生成スクリプト
- `gen_liberty.py` — `../TR1um_5_stdcell.lib`の生成スクリプト。セルごとの
  面積・遅延・論理関数を`COMB_CELLS`/`FF_CELLS`のテーブルで管理しており、
  実SPICE特性化後は該当セルの数値を書き換えて`python3 script/gen_liberty.py
  > TR1um_5_stdcell.lib`を再実行すれば反映できる（現行の`.lib`と
  バイト単位で一致することを確認済み）。

## 9. xschem回路図の自動生成（P&R環境が無いため手作業レイアウト用）

P&Rツールが無い環境のため、レイアウトは手作業で進める前提。その参照用に、
合成済みネットリスト `i2c_slave_async_net.v` から xschem 形式の回路図
（`schematic/i2c_slave_async_net.sch`）を `script/gen_schematic.py` で自動生成した。

- **配線方式**: 見た目の引き回し（ratsnest配線）は行わず、**ネットラベル方式**
  を採用。各セルインスタンスの各ピンに20単位の短いスタブ配線を生やし、
  そこへ `{lab=NETNAME}` を付与する。同じ`lab`を持つ配線はxschem上で
  電気的に同一ネットとして扱われる——これは`TR-1um_5_stdcell`ライブラリ
  自身の各セルの内部`.sch`（例: `NOR2.sch`）で使われているのと同じ手法で、
  VDD/GNDの电源網も含め全て`lab=`一致だけで正しく接続される。見た目には
  引き回されていないが、接続情報としては完全に正しい。
  手動レイアウト時の「このピンとこのピンは同じネットか」の確認に使うことを
  想定しており、美しく整った回路図ではない点に注意。
- **セル配置**: `i2c_slave_async_net.v`中のインスタンス順に12列のグリッドへ
  機械的に配置しただけで、論理的なまとまり（例: SCLドメインのDFFR群）を
  意識したレイアウトにはなっていない。手動レイアウトの参考にする際は、
  design_notes.md §2/§3のブロック構造（非同期SR部／SCL posedgeドメイン／
  SCL negedgeドメイン）を併読することを推奨する。
- **ネット名の解決**: Yosysが生成した`i2c_slave_async_net.v`には
  `assign _040_ = bit_cnt[0];`のような大量のネットエイリアス（同一の電気的
  ネットに複数のVerilog上の名前が付いている）が含まれる。スクリプトは
  Union-Findでこれらを一つのネットにまとめた上で、可能な限り
  `phase[0]`/`addr_ok`/`rst_n`のような意味のある名前を優先して表示し、
  該当がない場合のみYosysの`_NNN_`形式の名前にフォールバックしている。
  なお、どのセルにも接続されていない未使用の内部バス（`_322_`等、`case`文
  合成の副産物でロジックには寄与しないdead net）は回路図から除外済み。
- **セルシンボルの参照パス**: 各スタンダードセルは絶対パス
  （`/Users/okamura/Dropbox/91_OpenPDK/TR-1um/libs.tech/xschem/TR-1um_5_stdcell/*.sym`）
  で参照している。I/Oピン（`devices/ipin.sym`等）はxschem標準ライブラリを
  相対参照しており、`TR-1um_5_stdcell`内の既存`.sch`ファイルと同じ書き方
  （§2冒頭で確認したNOR2.schの記法）に合わせてある。
- **未検証事項**: このリポジトリのサンドボックスにはxschem本体が無いため、
  生成した`.sch`ファイルを実際にxschemで開いて構文・接続の妥当性を
  確認する作業は**未実施**。まずユーザー環境のxschemで開き、エラーが
  出ないこと、`i2c_slave_async_net.v`と同じ144セル＋4個の手動配置セル
  （`u_del_sda`/`u_inv_scl`/`u_lat_q`/`u_lat_qn`）が過不足なく存在すること、
  ネットリスト書き出し（xschem→spice/verilog netlist機能）で元の
  `i2c_slave_async_net.v`と接続が一致することを確認してから、レイアウト
  作業のリファレンスとして使うことを推奨する。
- ネットリスト（`i2c_slave_async_net.v`）を将来再合成した場合は、
  `python3 script/gen_schematic.py`を再実行すれば`schematic/`以下の
  `.sch`を再生成できる（パスはこのリポジトリ構成前提でスクリプト内に
  ハードコードされているため、環境が変わった場合は`STDCELL_ABS_DIR`等の
  定数を書き換える必要がある）。

## 10. 配線済み回路図（`i2c_slave_async_net_routed.sch`）

§9のラベル方式に加え、実際に配線を引いた版を`script/gen_schematic_routed.py`
で追加生成した（`schematic/i2c_slave_async_net_routed.sch`）。VDD/GNDのみ
§9と同様ラベル方式のままとし（電源網は一般的なスキーマティックでも配線せず
ラベルで表現するのが通例のため）、信号ネットは実際にドライバピンから
各レシーバピンまで直交（L字/コの字）配線で結線している。

- **セル配置アルゴリズム**: ネットリスト中の接続関係からセル間の
  依存グラフを構築し、各セルに「論理段数（レベル）」を割り当てて
  左→右にレベル順で配置する簡易Sugiyama式階層レイアウトを実装した
  （列内の並び順は前後列との接続本数を見たbarycenter法で4回反復し、
  交差をある程度低減）。
  - 重要な設計判断: **`DFFR`の`Q`/`QB`出力は、下流の組合せ論理段数を
    数える際は常にレベル0（一次入力と同様の「新しい起点」）として扱う**。
    これを入れないと、`phase`/`bit_cnt`等の相互に依存し合うFSMレジスタ群
    を素朴に辿った際、実際には1クロックで並列に決まる論理が見かけ上
    最大49段もの直列チェーンに積み上がってしまう不具合が最初に発生した
    （レジスタの出力を「前クロックの結果」として扱わず、そのレジスタ自身の
    D入力側の論理段数をそのまま下流に伝播させてしまっていたのが原因）。
    修正後は最大論理段数9段（レベル1〜9に144セルが分布）という、この
    回路の規模として妥当な深さに収まった。
  - `u_lat_q`/`u_lat_qn`（busyラッチの交差結合NOR2）は`DFFR`を介さない
    真の組合せフィードバックループのため、レベル計算時にDFS的な
    サイクル検出で該当エッジをスキップして無限再帰を回避している
    （配線自体はスキップせず正しく結線される。レベル計算だけの特例）。
- **信号配線**: 各ネットについて、ドライバから各レシーバへ3線分（横→縦→横）
  の直交経路を生成。複数レシーバを持つ高ファンアウト信号（`scl`/`rst_n`/
  `phase[i]`等、最大20〜30本規模）は、経路の折れ曲がり位置をネットごとに
  少しずつずらして完全な重なりは避けているが、**144セル規模の平坦な
  ゲートレベル回路を1枚のシートに収めている以上、高ファンアウト信号の
  交差密集は避けられない**。実用的な"読める"回路図というよりは、
  「どのピンとどのピンが実際に線で結ばれているかを目で追える」ことを
  目的とした参考図として扱ってほしい。手作業レイアウトでは、design_notes.md
  §2/§3のブロック単位（非同期SR部／SCL posedge・negedgeドメイン）で
  領域を分けて進める方が実務的に見通しが良い。
- §9同様、xschem本体でのオープン確認・接続整合性の確認は**未実施**。
  まずお手元のxschemで開いてエラーが無いことを確認してほしい。
- 再生成: `python3 script/gen_schematic_routed.py`
  （こちらもパスがハードコードされているため、環境が変わった場合は
  スクリプト冒頭の定数を書き換えること）。
