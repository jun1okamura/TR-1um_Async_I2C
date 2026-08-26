# TR-1um_Async_I2C

I2Cインターフェース（スレーブ）を **システムクロックを持たない非同期ロジック回路**
として実装し、RTLからゲートレベル論理合成・スタンダードセルによる配置配線・
DRC/接続性検証・LVS準備までを一貫して行っているプロジェクト。すべての状態遷移は
バス信号 SCL / SDA のエッジのみで駆動される（自己タイミング／バスタイムド設計）。

仕様準拠元: NXP `UM10204` *I2C-bus specification and user manual* Rev. 5.0J

`script/`配下の各スクリプトの役割・使いどころは [`SCRIPTS.md`](./SCRIPTS.md) を参照。

## 現在の状態

| フェーズ | 状態 |
|---|---|
| RTL設計・MyHDL/iverilog機能検証 | 完了 |
| Yosys論理合成（TR-1um_5_stdcellへのゲートマッピング） | 完了（`src/i2c_slave_async_net_v7.v`、154インスタンス） |
| 配置配線（v7「優先M2コリドー」レシピ） | 完了（**DRC 0違反・短絡0件**） |
| チャネル空き領域のBBOX圧縮（STEP7） | 完了（コア高さ 1813.6um → 988.2um、**45.5%削減**） |
| トップレベルポートのBBOX端引き出し（STEP6） | 完了（DRC 0違反・短絡0件） |
| LVS用スキーマティック生成（v7ネットリスト→xschem） | 完了（幾何学的接続検証604/604一致） |
| コアセル単体LVS（レイアウト抽出netlist vs スキーマティック） | 完了（**クリーン**、design_notes §60〜74） |
| トップレベル統合（FRAME/GIO⇔コア結線） | 完了（`script/route_gio_core.py`、design_notes §75） |
| トップレベルLVS（`tr_1um_i2c_slave_async` vs schematic） | 完了（**クリーン**、design_notes §75.8） |
| IRSIM用`.sim`ファイル準備 | 未着手 |

最終レイアウト成果物（トップレベル、チップ全体）:
[`src/tr_1um_i2c_slave_async_routed.gds`](./src/tr_1um_i2c_slave_async_routed.gds)
（FRAME/GIO + コアセル `i2c_slave_async_nrow_fm` を結線済み、LVSクリーン）
コアセル単体の最終レイアウト:
[`layout/i2c_slave_async_nrow_fm_v7rr_routed.gds`](./layout/i2c_slave_async_nrow_fm_v7rr_routed.gds)
LVS用スキーマティック: [`schematic/i2c_slave_async_nrow_fm.sch`](./schematic/i2c_slave_async_nrow_fm.sch)
（Top Cell名`i2c_slave_async_nrow_fm`をレイアウトと統一）、
トップレベルスキーマティック: [`schematic/tr_1um_i2c_slave_async.sch`](./schematic/tr_1um_i2c_slave_async.sch)

## 構成

```
src/
  i2c_slave_async.v          RTL本体（非同期・単一always構成、7bitアドレッシング）
  i2c_slave_async_tb.v       ローカルシミュレータ用テストベンチ（iverilog/Verilator向け）
  i2c_slave_async_net_v7.v   現行ゲートレベルネットリスト（Yosys合成、154インスタンス）
  stdcell_behavioral_stubs.v 標準セルのビヘイビアモデル（iverilogでのゲートレベル確認用）
  tr_1um_i2c_slave_async.gds トップレベルGDS（FRAME/GIO + コアセル、結線前のベース）
  tr_1um_i2c_slave_async_routed.gds
                              トップレベル最終成果物（GIO⇔コア結線済み、LVSクリーン）
LEF/
  OSS_FRAME_GIO.lef          GIOセルのLEF（`script/gen_lef.py`と同じ文字ラベル一致方式で
                              FRAME GDSから自動生成。詳細はSCRIPTS.md参照）
  TR-1um_STDCELL.lef/.gds    スタンダードセルライブラリ（LEF/GDS）
  placement_*.json           各世代の配置情報（v7系: placement_nrow_fm_v7_priomch.json）
  DFFR.sch/.sym, BUFTH.sch/.sym, DFF.sch/.sym, DEL1.sym, *.extracted
                              本プロジェクト固有のセル（LVS基準として使用）
layout/                      コアセル（`i2c_slave_async_nrow_fm`）単体の配置配線GDS一式
  i2c_slave_async_nrow_fm_v7rr_routed.gds
                              v7ベースレシピの最終ルーティング結果（DRC 0/0/0・短絡0件）
                              ※このコアセルを`src/tr_1um_i2c_slave_async_routed.gds`へ
                              統合したものが最終チップレベル成果物
  steps_v7_v2/                STEP1〜7のチェックポイントGDS（TAP電源メッシュ→配線パス0〜3→
                               トップピンBBOX引き出し→チャネル圧縮）
  （v4/v6系など他のファイルは開発過程の履歴保存用）
schematic/
  i2c_slave_async_nrow_fm.sch v7ネットリストから生成したLVS用xschemスキーマティック（コア）
  tr_1um_i2c_slave_async.sch  トップレベルスキーマティック（FRAME/GIO + コアの結線）
FRAME/
  TR-1um_frame_25x25.gds     チップフレーム（IOパッド・ESD・GIOセル等）のGDS
script/
  route_gio_core.py          GIO⇔コア間の結線ルータ（20信号+VDD/VSS、再現可能）
  reassemble_top.py           FRAME GDS変更を反映してトップGDSのGIOセルを差し替え
  他、配置配線・DRC/接続性検証・LVS準備スクリプト一式（全28本、詳細は
  [`SCRIPTS.md`](./SCRIPTS.md)）。開発過程の旧世代・重複スクリプトは削除済み。
references/                  UM10204仕様書、DRCサマリ資料
TR1um_5_stdcell.lib          Yosys用Liberty（タイミング未特性化のプレースホルダ）
logic_cells_mapping.md       RTL論理→スタンダードセル対応表
design_notes.md              設計ノート本体（RTL設計からトップレベルLVSクリーン化まで
                              全75節、詳細記録）
```

## 特徴 / 既知の制限（RTL）

- `clk`ポートなし。SCL立上りでビットサンプル、SCL立下りで出力更新、SDAエッジ
  （SCL=HIGH中）でSTART/STOP検出（詳細は `design_notes.md` §1〜4参照）
- 7bitアドレッシングのみ（10bit未対応）
- クロックストレッチ未対応（本スレーブはSCLを駆動しない）
- 受信データは常にACKする設計（アプリ側NACKは未実装、拡張ポイントとして記載）

## 物理設計（配置配線）の概要

- **スタンダードセルライブラリ**: `TR-1um_5_stdcell`（AND/OR/NAND/NOR/MUX/INV/BUF等）に
  加え、本プロジェクト専用の`DFFR`（非同期リセット付きDFF）・`BUFTH`（しきい値バッファ、
  scl/sda_in の行またぎ分配用）を`LEF/`配下に保持。
- **配置**: nrow（複数行）構成、行間に配線チャネルを設ける方式。行内セルの
  クロス行ネットを最小化するFMハイパーグラフ分割で最適化（design_notes §24）。
  現行の配置バリアントは「優先M2コリドー」（8本の構造的に常時クリアなM2縦帯を
  スペア経路として用意）方式（v7、design_notes §47以降）。
- **配線**: 独自Pythonルータ（`script/route_channels_nrow_fm.py`）による4パス方式
  （TAP電源メッシュ→行内ローカル配線→高FO/隣接ペア配線→複数行またぎ配線→
  強制ジョグ処理）＋汎用リップアップ&リルート後処理（`script/ripup_reroute_shorts.py`）。
  現行v7レシピは**DRC違反0・短絡0件**を達成（design_notes §51〜58）。
- **チャネル圧縮（STEP7）**: 配線済みGDSを一切再配線せず、真に未使用な配線
  トラックだけを幾何学的に除去してチャネル高さを圧縮する後処理
  （`script/squeeze_channels_nrow_fm.py` + `script/run_route_v7_step7_squeeze.py`）。
  コア全体のBBOX高さを1813.6um→988.2um（45.5%削減）まで圧縮（design_notes §58）。
- **トップレベルポート引き出し（STEP6）**: 全トップレベルポートをBBOX端まで
  M1/M2で延伸し、M1PIN/M2PINマーカーを配置（`script/route_top_pins_nrow_fm.py`、
  design_notes §56）。
- **検証**: `script/drc_check_nrow_fm.py`（M1/M2幅・スペース、V1関連ルール）、
  `script/verify_connectivity_nrow_fm.py`（Union-Findによる短絡・未接続検出、
  ネットリストの`pin_map`と実ジオメトリを突き合わせ）。

## LVS

ゲートレベルネットリスト（`src/i2c_slave_async_net_v7.v`）から、LVSの
「スキーマティック側」ネットリストとなるxschem回路図を生成済み
（`script/gen_schematic_v7.py`）。`DFFR`/`BUFTH`は`LEF/`配下の
プロジェクト固有sch/symを、それ以外の全セルタイプは`TR-1um_5_stdcell`を参照。
生成結果は、xschemを使わない独立幾何学的接続検証スクリプト
（`script/verify_schematic_v7.py`）で、604件の接続（インスタンスピン＋
トップレベルポート）全てがVerilogネットリストと一致することを確認済み
（design_notes §59）。

**LVS本実行**（実機xschem/KLayout環境でのレイアウト抽出ネットリストとの比較）は
コアセル単体・トップレベルとも**完了しクリーン**（design_notes §60〜75）。
主な経緯:
- コアセル単体LVS: VDD/GND浮き・命名不一致・短絡等を段階的に修正し、
  §74までにクリーン化。
- トップレベルLVS（`tr_1um_i2c_slave_async` = FRAME/GIO + コア）:
  GIO⇔コアの結線を独自ルータ（`script/route_gio_core.py`）で実装後、
  VDDポート未認識（境界隣接M1PIN/M2PINマーカー不足）、VSSのグローバルネット
  扱い、コアsymbolのGND/VSS命名不一致、GIOの`OUT2`ピンの誤配線（VSSへの
  誤接続）を順に発見・修正し、最終的にLVSクリーンを達成（design_notes §75）。

## 実行方法

### Verilogシミュレーション（ローカル環境、iverilog/Verilator推奨）

```sh
cd src
iverilog -o sim i2c_slave_async.v i2c_slave_async_tb.v && vvp sim
```

ゲートレベル（合成後ネットリスト）のシミュレーションも同じスタブで可能:

```sh
cd src
iverilog -o sim_net i2c_slave_async_net_v7.v stdcell_behavioral_stubs.v i2c_slave_async_net_tb.v && vvp sim_net
```

### Python（MyHDL）による機能検証

RTLと同一のロジックをMyHDL上で動かし、バス機能モデル（マスタ）を使って
書き込み/読み出し/アドレス不一致の3シナリオを検証済み（`design_notes.md` §6）。

```sh
cd script
pip install myhdl
python3 test_i2c_slave_async.py
python3 test_i2c_slave_async_negative.py
```

### Yosys論理合成（RTL → ゲートレベルネットリスト）

```sh
pip install yowasp-yosys
yowasp-yosys -p "
  read_verilog src/i2c_slave_async.v
  hierarchy -top i2c_slave_async -keep_portwidths
  proc; opt
  techmap; opt
  dfflegalize -cell \$_DFF_PP0_ 0
  dfflibmap -liberty TR1um_5_stdcell.lib
  abc -liberty TR1um_5_stdcell.lib
  write_verilog i2c_slave_async_net.v"
```

（v7ネットリストはこの後、BUFTH挿入等の追加ネットリスト加工を経ている。詳細は
design_notes.md §18, §39〜42参照）

### 配置配線（v7レシピの再現）

```sh
cd script
python3 run_route_v7_from_scratch.py   # 配置→配線→リップアップ&リルート→DRC/接続性検証
python3 run_route_v7_step7_squeeze.py  # チャネル圧縮→トップピン引き出し→再検証
```

### LVSスキーマティック生成

```sh
cd script
python3 gen_schematic_v7.py       # v7ネットリスト → schematic/i2c_slave_async_nrow_fm.sch
python3 verify_schematic_v7.py    # 幾何学的接続検証（xschem不要）
```

## 参考

- 設計・実装の全記録（RTLのステートマシン設計、UM10204各節との対応、
  論理合成、配置配線の全試行錯誤、DRC/LVSクリア化、トップレベル統合まで）は
  [`design_notes.md`](./design_notes.md)（全75節）を参照。主な区切り:
  - §1〜11: RTL設計・検証・xschem回路図
  - §12〜38: 物理実装環境の構築、配置配線の試行錯誤（複数世代）
  - §39〜46: セル再構築、バッファ挿入、DRC/短絡の系統的解消
  - §47〜58: v7「優先M2コリドー」レシピの確立、短絡ゼロ化、
    トップピン引き出し（STEP6）、チャネル圧縮（STEP7）
  - §59: LVS準備（スキーマティック生成）
  - §60〜74: コアセル単体LVSのクリーン化（VDD/GND浮き、短絡、
    スイッチレベルシミュレーションによる検証）
  - §75: トップレベル統合（FRAME/GIO⇔コア結線）とトップレベルLVSクリーン化
- 論理セル対応表: [`logic_cells_mapping.md`](./logic_cells_mapping.md)
