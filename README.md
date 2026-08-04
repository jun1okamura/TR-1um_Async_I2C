# TR-1um_Async_I2C

I2Cインターフェース（スレーブ）を **システムクロックを持たない非同期ロジック回路**
として実装したプロジェクト。すべての状態遷移はバス信号 SCL / SDA のエッジのみで
駆動される（自己タイミング／バスタイムド設計）。

仕様準拠元: NXP `UM10204` *I2C-bus specification and user manual* Rev. 5.0J

## 構成

```
src/
  i2c_slave_async.v      RTL本体（非同期・単一always構成、7bitアドレッシング）
  i2c_slave_async_tb.v   ローカルシミュレータ用テストベンチ（iverilog/Verilator向け）
script/
  i2c_slave_async_model.py     初期検証モデル（MyHDL、複数always-block構成）
  i2c_slave_async_model_v2.py  i2c_slave_async.v と同一構造の検証モデル（単一プロセス）
  test_i2c_slave_async.py           model.py 用テスト（書き込み/読み出し）
  test_i2c_slave_async_negative.py  model.py 用テスト（アドレス不一致→NACK）
  test_v2_positive.py               model_v2.py 用テスト（書き込み/読み出し）
  test_v2_negative.py               model_v2.py 用テスト（アドレス不一致→NACK）
design_notes.md          FSM設計、UM10204各節との対応、タイミング仕様、既知の制限
```

## 特徴 / 既知の制限

- `clk`ポートなし。SCL立上りでビットサンプル、SCL立下りで出力更新、SDAエッジ
  （SCL=HIGH中）でSTART/STOP検出（詳細は `design_notes.md` 参照）
- 7bitアドレッシングのみ（10bit未対応）
- クロックストレッチ未対応（本スレーブはSCLを駆動しない）
- 受信データは常にACKする設計（アプリ側NACKは未実装、拡張ポイントとして記載）

## 実行方法

### Verilogシミュレーション（ローカル環境、iverilog/Verilator推奨）

```sh
cd src
iverilog -o sim i2c_slave_async.v i2c_slave_async_tb.v && vvp sim
```

### Python（MyHDL）による機能検証

RTLと同一のロジックをMyHDL上で動かし、バス機能モデル（マスタ）を使って
書き込み/読み出し/アドレス不一致の3シナリオを検証済み（`design_notes.md` §6）。

```sh
cd script
pip install myhdl
python3 test_i2c_slave_async.py
python3 test_i2c_slave_async_negative.py
python3 test_v2_positive.py
python3 test_v2_negative.py
```

## 参考

- 設計の詳細（ステートマシン、UM10204各節との対応、Table 10タイミング仕様との
  関係、検証結果）は [`design_notes.md`](./design_notes.md) を参照。
