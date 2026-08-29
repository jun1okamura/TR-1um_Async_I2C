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
| IRSIM用`.sim`ファイル準備（チップレベル） | 完了（`irsim/tr_1um_i2c_slave_async.sim`、2082トランジスタ、design_notes §76） |
| IRSIMチップレベル動作検証（実`TR-1um.prm`下） | WRITEトランザクション（START〜STOP）完全動作確認済み。READトランザクションで`rw`/`addr_match`取り込みの同一エッジレース、および`sda_oe`⇔パッド`HIZ13`間の極性不一致を発見——**V8**でRTLレベルの根本修正へ（design_notes §76.29〜76.48, §77） |
| **V8**（RTL根本修正: ウォーキングワン化 + sda_oe極性反転） | Verilog検証（iverilog+MyHDL）・NET合成 完了。**DFFSなし版**（`i2c_slave_async_net_v8.v`系、186インスタンス、DFFRB×37/DFFS×0）を正式版として採用。配置配線STEP1〜3完了＋残り短絡3件を手動修正し`v8_step_4_manual_short_fix.gds`でDRC 0・短絡0を達成（design_notes §77.16）。STEP6（トップピン引き出し）・STEP7（チャネル圧縮、圧縮スクリプト自体の3件のバグを根本修正）も完了、`layout/step8/v8_step_8_squeezed_top_pins_routed.gds`でDRC 0・短絡0・コア高さ-41.8%（2288.8→1333.0um）（design_notes §77.17〜77.18）。VDD/VSSトップピン追加（TAPセルM2/M1のBBOX端、5列20個のM2ピン＋左右列16個のM1ピン）も完了、**`layout/step8/v8_step_9_power_pins_added.gds`でDRC 0・信号短絡0・電源net（VDD/GND各1連結成分、共有0）を確認**（design_notes §77.20）。DFFS許可版（行幅2538um、短絡5件）は保留。 |
| **V9**（DFFS許可・コア再配置配線、GIO再結線） | コアの配置配線をやり直し（`route_gio_core_v9.py`によるGIO⇔コア結線・電源メッシュ再構築）。DRC 0違反を達成した最終物理設計を`src/tr_1um_i2c_slave_async.gds`に確定（design_notes §79）。チップレベルLVS用SPICE生成（GIO実SPICE＋コアLVSクリーンSPICE＋`gio_connections.json`から機械生成、design_notes §80〜82）を経て、以下3つの実バグを発見・修正: (1) スキーマティック・レイアウト双方でチップTOP PIN（P1〜P7/VSS/P9〜P15/VDD、16本）が未宣言だった問題（design_notes §82〜83）、(2) `route_gio_core_v9.py`の電源配線書き直しでHIZ2/HIZ7/HIZ9/HIZ10/HIZ15/OUT13のVDD/VSS固定タイ結線が丸ごと欠落していた問題（design_notes §84）、(3) `gio_connections.json`のP11記載ミス（実際はcore.tx_data[1]に接続済みなのに誤って未接続と記載）でLVS参照ネットリストが実レイアウトと食い違っていた問題（design_notes §85）。**これら全ての修正後、ユーザー実機KLayoutでのチップレベルDRC/LVS確認で最終的にクリーンを達成**（design_notes §85.6, §86）。 |
| **IRSIMチップレベル動作検証（V9最終チップnetlist）** | DRC/LVSクリーン済みの`tr_1um_i2c_slave_async.extracted`をトランジスタレベルまでフラット化（2077トランジスタ・845ノード、design_notes §87）。`DFFRB`のQM（マスタ）/QS（スレーブ）両記憶ノードをクロックHIGH時に強制する実行時リセット手法を確立し、READトランザクションの不具合を根本解決（design_notes §89〜96）。`src/i2c_slave_async_tb.v`と1対1対応する自己検証型IRSIMテストベンチ（WRITE 0xA5／READ 0x3C／誤アドレスNACKの3シナリオ・14チェック）を実チップ上で実行し、**Verilog版と完全一致する`All 14 checks PASSED`を実機IRSIMで確認**（design_notes §97〜100）。実行は`irsim/run_tb.sh`一発で完結（詳細は[`irsim/README.md`](./irsim/README.md)）。 |

**最終レイアウト成果物（V9、トップレベル・チップ全体）**:
[`src/tr_1um_i2c_slave_async.gds`](./src/tr_1um_i2c_slave_async.gds)
（FRAME/GIO + コアセル `i2c_slave_async_nrow_fm` を結線済み、実機KLayoutでの
チップレベル**DRC/LVSクリーン確認済み**、design_notes §79〜86）。
チップレベルLVS用参照SPICE:
[`schematic/tr_1um_i2c_slave_async_v9_lvs.spice`](./schematic/tr_1um_i2c_slave_async_v9_lvs.spice)
（`script/gen_lvs_spice_top_v9.py`で機械生成、`schematic/gio_connections.json`が
一次データソース）。
コアセル単体の最終レイアウト:
[`layout/i2c_slave_async_nrow_fm_v7rr_routed.gds`](./layout/i2c_slave_async_nrow_fm_v7rr_routed.gds)
LVS用スキーマティック: [`schematic/i2c_slave_async_nrow_fm.sch`](./schematic/i2c_slave_async_nrow_fm.sch)
（Top Cell名`i2c_slave_async_nrow_fm`をレイアウトと統一）、
トップレベルスキーマティック: [`schematic/tr_1um_i2c_slave_async.sch`](./schematic/tr_1um_i2c_slave_async.sch)

（`src/tr_1um_i2c_slave_async_routed.gds`はV7時代の成果物として履歴保存のため
残置。V9以降の正式な最終成果物は上記`src/tr_1um_i2c_slave_async.gds`。）

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
  route_gio_core_v9.py        v9版GIO⇔コア間の結線ルータ（24信号+VDD/VSS、再現可能）
  assemble_top_v9.py          v9トップレベルGDSの骨格構築（GIO+コア+PTECT配置）
  gen_irsim_sim_v9.py         DRC/LVSクリーン済みチップ全体をトランジスタレベルまで
                              再帰フラット化しIRSIM用`.sim`を生成（design_notes §87）
  gen_irsim_cmd_v9.py         IRSIM刺激スクリプト生成の共通基盤（force/release手法含む）
  gen_irsim_verilog_equiv_tb.py
                              Verilog版テストベンチと1対1対応する自己検証型IRSIM
                              テストベンチを生成（design_notes §98）
  他、配置配線・DRC/接続性検証・LVS準備・IRSIM検証スクリプト一式（全52本、
  詳細は[`SCRIPTS.md`](./SCRIPTS.md)）。開発過程の旧世代・重複・解消済み
  バグの一回限りデバッグスクリプトは削除済み（v7版のGDS/GIOルータ等、
  一部は現行v9パイプラインの前例・依存として残置）。
irsim/                        IRSIMチップレベル動作検証一式（`.sim`/`.cmd`、自己検証型
                              テストベンチ`irsim_tb.cmd`＋一発実行`run_tb.sh`、詳細は
                              [`irsim/README.md`](./irsim/README.md)）
references/                  UM10204仕様書、DRCサマリ資料
TR1um_5_stdcell.lib          Yosys用Liberty（タイミング未特性化のプレースホルダ）
logic_cells_mapping.md       RTL論理→スタンダードセル対応表（v9現行ネットリスト基準）
design_notes.md              設計ノート本体（RTL設計からv9チップレベルIRSIM動作検証
                              完了まで全100節、詳細記録）
```

## 特徴 / 既知の制限（RTL）

- `clk`ポートなし。SCL立上りでビットサンプル、SCL立下りで出力更新、SDAエッジ
  （SCL=HIGH中）でSTART/STOP検出（詳細は `design_notes.md` §1〜4参照）
- 7bitアドレッシングのみ（10bit未対応）
- クロックストレッチ未対応（本スレーブはSCLを駆動しない）
- 受信データは常にACKする設計（アプリ側NACKは未実装、拡張ポイントとして記載）
- **v7時点で発見され、V8/V9で修正済みの問題**（design_notes §77）:
  - READアドレスバイト取り込み時、`bit_cnt`の自己リセットと`rw`/
    `addr_match`の取り込みが同一SCLエッジ・同一組み合わせパスを共有する
    同一エッジレースがあった（実測`TR-1um.prm`下のIRSIM検証で発見、
    §76.43〜76.47）。ウォーキングワン方式への置き換えで根本解消。
  - コアの`sda_oe`出力とSDAパッド`HIZ13`入力の間で極性が逆だった
    （§76.17〜76.18）。RTL側での出力極性反転で修正済み。
  - V9チップレベルのIRSIM実機検証（design_notes §87〜100）で、
    WRITE/READ/誤アドレスNACKの3シナリオ・14チェック全てが
    Verilog版と一致することを確認済み。現時点で既知の未解決バグは無い。

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
コアセル単体・トップレベルとも**完了しクリーン**（design_notes §60〜75、v7時点）。
主な経緯:
- コアセル単体LVS: VDD/GND浮き・命名不一致・短絡等を段階的に修正し、
  §74までにクリーン化。
- トップレベルLVS（`tr_1um_i2c_slave_async` = FRAME/GIO + コア、v7）:
  GIO⇔コアの結線を独自ルータ（`script/route_gio_core.py`）で実装後、
  VDDポート未認識（境界隣接M1PIN/M2PINマーカー不足）、VSSのグローバルネット
  扱い、コアsymbolのGND/VSS命名不一致、GIOの`OUT2`ピンの誤配線（VSSへの
  誤接続）を順に発見・修正し、最終的にLVSクリーンを達成（design_notes §75）。

**V9チップレベルLVS**（コア再配置配線後、`src/tr_1um_i2c_slave_async.gds`が
最終成果物）も**クリーン**（design_notes §79〜86）。v7からのコア変更に伴い
再度LVSを通す過程で、v7では潜んでいなかった／顕在化しなかった3つの実バグを
新たに発見・修正:
- チップTOP PIN（P1〜P7/VSS/P9〜P15/VDD、16本）がスキーマティック・
  レイアウトの両方で未宣言だった（§82〜83）。
- `route_gio_core_v9.py`の電源配線再実装で、HIZ2/HIZ7/HIZ9/HIZ10/HIZ15/
  OUT13の（スキーマティック上意図的な）VDD/VSS固定タイ結線が丸ごと
  欠落していた（§84）。
- `gio_connections.json`のP11の記載が誤り（実際は`core.tx_data[1]`に
  接続済みなのに未接続と記載）で、LVS参照ネットリストが実レイアウトと
  食い違っていた（§85）。

## 実行方法

### Verilogシミュレーション（ローカル環境、iverilog/Verilator推奨）

```sh
cd src
iverilog -o sim i2c_slave_async.v stdcell_behavioral_stubs.v i2c_slave_async_tb.v && vvp sim
```

（`i2c_slave_async.v`はDEL1/NOR2/INV_X1をゲート単位で構造的にインスタンス化
しているため、`stdcell_behavioral_stubs.v`の同時コンパイルが必須。省略すると
`Unknown module type: DEL1`等のエラーになる。）

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

**注意**: `yowasp-yosys`（WASM/WASI版）は`abc`ステップでエラー無く異常
終了することが確認されている（design_notes.md §77.9）。ネイティブ版
（例: macOSなら`brew install yosys`、コマンドは`yosys`）の使用を推奨。

```sh
pip install yowasp-yosys   # または brew install yosys（推奨）
yowasp-yosys -p "           # ネイティブ版なら `yosys -p "` に読み替え
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

### IRSIMチップレベル動作検証（v9、実機実行）

DRC/LVSクリーン済みチップ全体netlistをそのままトランジスタレベルで
IRSIM実行し、Verilog版テストベンチと同じ3シナリオ・14チェックを
自動判定できる。実行環境（IRSIM本体）が必要なため、`.sim`/`.cmd`は
事前生成済みのものを使い、実行そのものはローカルで行う:

```sh
cd irsim
./run_tb.sh              # 実行＋自動PASS/FAIL判定を1コマンドで
```

詳細・波形（アナライザ）の見方は[`irsim/README.md`](./irsim/README.md)参照。

## 参考

- 設計・実装の全記録（RTLのステートマシン設計、UM10204各節との対応、
  論理合成、配置配線の全試行錯誤、DRC/LVSクリア化、トップレベル統合、
  v9チップレベルIRSIM動作検証完了まで）は
  [`design_notes.md`](./design_notes.md)（全100節）を参照。主な区切り:
  - §1〜11: RTL設計・検証・xschem回路図
  - §12〜38: 物理実装環境の構築、配置配線の試行錯誤（複数世代）
  - §39〜46: セル再構築、バッファ挿入、DRC/短絡の系統的解消
  - §47〜58: v7「優先M2コリドー」レシピの確立、短絡ゼロ化、
    トップピン引き出し（STEP6）、チャネル圧縮（STEP7）
  - §59: LVS準備（スキーマティック生成）
  - §60〜74: コアセル単体LVSのクリーン化（VDD/GND浮き、短絡、
    スイッチレベルシミュレーションによる検証）
  - §75: トップレベル統合（FRAME/GIO⇔コア結線）とトップレベルLVSクリーン化（v7）
  - §76: IRSIMチップレベル動作検証（実`TR-1um.prm`下でWRITEパス完全動作
    確認、READ側同一エッジレース・sda_oe極性不一致を発見）
  - §77: **V8計画**（ウォーキングワン方式によるレース解消、sda_oe極性
    反転、Verilog検証→NET合成→配置配線→DRC/LVS検証→IRSIM検証の
    フル再実行フロー）
  - §78: `gio_connections.json`（GIO⇔コア結線マップ、v9チップレベル
    LVS作業の一次データソース）の導出とv7実配線との相互検証
  - §79: **V9**コア再配置配線（DFFS許可、GIO再結線、電源メッシュ再構築）
    のDRCクリーン化
  - §80〜81: v9チップレベルLVS用参照SPICE生成、最終レイアウトの`src/`確定
  - §82〜83: チップTOP PIN未宣言バグの発見・修正（スキーマティック側
    ・レイアウト側の両方、P1〜P7/VSS/P9〜P15/VDDの16ポート）
  - §84: HIZ2/HIZ7/HIZ9/HIZ10/HIZ15/OUT13のVDD/VSS固定タイ結線が
    v9の電源配線書き直しで欠落していたバグの発見・修正
  - §85: `gio_connections.json`のP11記載ミス（実際は`core.tx_data[1]`
    に接続済みなのに誤って未接続と記載）の発見・修正、**チップレベル
    DRC/LVSクリーン達成**
  - §86: TOP PINラベルのテキストサイズ調整
  - §87〜88: v9チップレベルIRSIM再検証（新`.sim`/`.cmd`生成、ノード名
    再導出）
  - §89〜96: READトランザクション不具合の根本原因調査・修正——
    `DFFRB`のQM（マスタ）/QS（スレーブ）両記憶ノードをクロックHIGH時に
    強制する実行時リセット手法の確立
  - §97: WRITE(0xA5)＋READ(0x3C)＋誤アドレスNACKのフルトランザクション
    end-to-end成功
  - §98〜99: `src/i2c_slave_async_tb.v`と1対1対応する自己検証型IRSIM
    テストベンチの構築・実機確認（`All 14 checks PASSED`）
  - §100: 検証結果表示のVerilog版書式統一、一発実行`run_tb.sh`追加
- 論理セル対応表: [`logic_cells_mapping.md`](./logic_cells_mapping.md)（v9
  現行ネットリスト基準に更新済み）
