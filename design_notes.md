# I2Cスレーブ 非同期ロジック回路 設計ノート

参照仕様: NXP `UM10204` *I2C-bus specification and user manual*, Rev. 5.0J（2012年、日本語版）

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

## 2. ステートマシン

```
IDLE --(START)--> ADDR --[8bit]--> ADDR_ACK --+--(addr match, R/W=0)--> DATA_WR --[8bit]--> DATA_WR_ACK --> DATA_WR ...
                                               +--(addr match, R/W=1)--> DATA_RD --[8bit]--> DATA_RD_ACK --(master ACK)--> DATA_RD ...
                                               +--(no match)------------> IDLE                              --(master NACK)--> IDLE
任意の状態 --(STOP)--> IDLE
```

- `ADDR`: アドレス+R/Wビット（8bit）をSCL立上りでシフトイン。8bit目でアドレス
  一致判定（`addr_ok`）とR/Wビット（`rw_bit`）を確定。
- `ADDR_ACK` / `DATA_WR_ACK`: SCL立下りでSDAをLOWに駆動（ACK）。アドレス不一致
  時は駆動せずNACKとしてIDLEへ戻る。
- `DATA_WR`: マスタ→スレーブのデータ8bitをシフトイン。8bit目で`rx_data`確定、
  `rx_valid`を1バスクロック分パルス。
- `DATA_RD`: スレーブ→マスタ。SCL立下りごとに`tx_data`（アプリ側が用意した値）
  をMSBファーストでシフトアウト。
- `DATA_RD_ACK`: マスタが返すACK/NACKをSCL立上りでサンプルし、ACKなら
  `DATA_RD`へ戻って次バイト送出、NACKなら`IDLE`へ（仕様3.1.6の条件5と一致）。

## 3. 実装上の重要な注意（Verilogの合法性）

START/STOP検出（SDAエッジ・SCLゲート）とビット処理（SCLエッジ）を別々の
`always`ブロックで書くと、`state`や`sda_oe`などのレジスタに複数ドライバが
生じ、論理合成では不正となる。これを避けるため、`i2c_slave_async.v` では
**単一の`always`ブロック**に統合し、SCL/SDAの1クロック前の値（`scl_q`,
`sda_q`）をシャドウレジスタとして保持し、レベル比較でSTART/STOP/立上り/立下り
を導出している。これは論理的には「バスがゲートするラッチ」そのものであり、
ゲートレベルで実装する場合はUM10204図5のNAND-SRラッチに対応する。

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

## 8. ファイル一覧

- `i2c_slave_async.v` — 納品RTL本体（非同期・単一always構成）
- `i2c_slave_async_tb.v` — ローカルシミュレータ用テストベンチ
- `i2c_slave_async_model.py` / `i2c_slave_async_model_v2.py` — 検証用MyHDLモデル
- `test_i2c_slave_async.py` / `test_i2c_slave_async_negative.py` — model.py用テスト（実行済み・全PASS）
- `test_v2_positive.py` / `test_v2_negative.py` — model_v2.py用の同一テスト（実行済み・全PASS）
