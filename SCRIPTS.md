# script/ ガイド

`script/`配下の現行スクリプト（全27本＋本セッションで追加した`reassemble_top.py`）の
説明資料。RTL設計からトップレベルLVSクリーン化までの再現可能なパイプラインを構成する
スクリプトのみを残しており、開発過程で使われた旧世代・重複・一回限りのデバッグ用
スクリプトは削除済み（削除対象は主にv2/v3・row/2row/2row_fm世代の予測定器・配置器・
ルータ、および解消済みバグ専用のハイライト/デバッグスクリプト）。各スクリプトの
コメント冒頭に、より詳しい設計判断の背景（design_notes.mdの節番号）が記載されている。

## 1. RTL・機能検証

| スクリプト | 役割 |
|---|---|
| `i2c_slave_async_model.py` | I2Cスレーブの非同期ロジックをMyHDLでモデル化した本体。`test_i2c_slave_async*.py`から参照される。 |
| `test_i2c_slave_async.py` | MyHDLイベント駆動シミュレータによる機能検証（write/readトランザクション、UM10204 3.1.4〜3.1.6準拠チェック）。 |
| `test_i2c_slave_async_negative.py` | 誤アドレスへのアクセスがNACKし、スレーブがidleに戻ることを確認する追加チェック。 |

実行方法はREADME.mdの「Python（MyHDL）による機能検証」参照。

## 2. 論理合成後ネットリスト加工

| スクリプト | 役割 |
|---|---|
| `insert_bufth_scl_sda.py` | Yosys合成直後のネットリストに対し、トップレベルの`scl`/`sda_in`にBUFTH（シュミットトリガ・バッファ）を挿入するネットリスト変換（現行`src/i2c_slave_async_net_v7.v`を作った最終ステップ）。一度限りの変換で、出力ファイルは`src/`に保存済みのため、通常の再現手順では再実行不要。 |
| `gen_liberty.py` | Yosys/ABC合成用のプレースホルダLiberty（`TR1um_5_stdcell.lib`）を生成。**タイミング値は全てプレースホルダ**（実SPICE特性化なし）。 |

## 3. LEF・標準セルライブラリ

| スクリプト | 役割 |
|---|---|
| `lef_parser.py` | `LEF/TR-1um_STDCELL.lef`を読む最小限のパーサ（MACRO SIZE・PIN形状）。配置・配線スクリプトの共通依存モジュール。 |
| `gen_lef.py` | セルの物理GDS（`LEF/TR-1um_STDCELL.gds`）からLEFを自動生成。prBoundary(235/0)でSIZE、M1PIN(48/1)/M2PIN(49/1)でピン境界、TXM1(48/0)/TXM2(49/0)のテキストラベルでピン名を決定する規約（design_notes §35）。`LEF/OSS_FRAME_GIO.lef`もこれと同じ考え方（テキストラベル一致方式）で生成した（元スクリプトは一時ファイルとして作業し保存されなかったため、再生成が必要な場合は本スクリプトの規約を`FRAME/TR-1um_frame_25x25.gds`のOSS_FRAME_GIOセル向けに適用する）。 |

## 4. 配置（Placement）

| スクリプト | 役割 |
|---|---|
| `netlist_parser.py` | `src/i2c_slave_async_net_v7.v`（Yosys出力）を読む最小限の構造Verilogパーサ。`assign`エイリアスの解決を含む。 |
| `fm_partition.py` | Fiduccia-Mattheysesハイパーグラフ分割（再帰二分割によるNウェイ）。クロス行ネット数を最小化する行割り当てに使用。 |
| `gen_placement_2row.py` | 2行配置のセル詰め込みヘルパー（`fill_combo`/`TRACK_UM`/`TAP_CELL`）。現行の`gen_placement_nrow_fm.py`から直接importされる共通依存。 |
| `gen_placement_nrow_fm.py` | 現行のN行配置ジェネレータ（`fm_partition`による行割り当て＋FILL2/FILL3の分散配置）。`LEF/placement_nrow_fm_v7_priomch.json`を生成。 |
| `gen_placement_gds_nrow_fm.py` | 配置JSON（`placement_nrow_fm_v7_priomch.json`）からセルインスタンスを並べた配置済みGDSを生成。 |

## 5. 配線（Routing）— コアセル本体

| スクリプト | 役割 |
|---|---|
| `route_channels_nrow_fm.py` | **現行の中核ルータ**（v3、約140KB）。N行/(N+1)チャネル構成で、TAP電源メッシュ→行内ローカル配線→高FO/隣接ペア配線→複数行またぎ配線→強制ジョグ処理の4パス方式。全viaは`via_1`PCellインスタンス。 |
| `ripup_reroute_shorts.py` | 汎用（ネット名非依存）のポストルート短絡自動修正。パスごとに異なる衝突回避ロジックを持つ`route_channels_nrow_fm.py`の限界を補う後処理。 |
| `route_top_pins_nrow_fm.py` | STEP6: 全トップレベルポートをコアのBBOX端まで引き出し、M1PIN/M2PINマーカーを配置（フレーム結線の準備）。 |
| `highlight_top_pins_nrow_fm.py` | `route_top_pins_nrow_fm.py`が使う、各トップレベルポートの物理位置をハイライトする補助関数群。 |
| `compress_channels_nrow_fm.py` | チャネル高さを縮めて配置・配線を再実行するポストプロセス（実測トラック使用量に基づく）。 |
| `squeeze_channels_nrow_fm.py` | 既存の配線済みGDSに対し、未使用のYスライスを幾何学的に除去してチャネル高さを圧縮（再配線なし）。STEP7で使用、コア高さを1813.6um→988.2um（45.5%削減）。 |

## 6. 配線 — 実行エントリポイント

| スクリプト | 役割 |
|---|---|
| `run_route_v7_from_scratch.py` | **v7レシピの配置→配線→リップアップ&リルート→DRC/接続性検証**を一気通貫で実行する、ゼロから再現するための決定版スクリプト。 |
| `run_route_v7_step7_squeeze.py` | STEP7（チャネル圧縮→トップピン引き出し→再検証）の**正しい**実装。`compress_channels_nrow_fm.py`・`route_channels_nrow_fm.py`・`squeeze_channels_nrow_fm.py`・`route_top_pins_nrow_fm.py`を順に呼び出す。 |

再現手順はREADME.mdの「配置配線（v7レシピの再現）」参照。

## 7. 検証（DRC・接続性・診断）

| スクリプト | 役割 |
|---|---|
| `drc_check_nrow_fm.py` | M1/M2幅・スペース、V1関連ルールのDRCチェック。 |
| `verify_connectivity_nrow_fm.py` | レイヤ別Union-Findによる短絡・未接続検出。ネットリストの`pin_map`と実ジオメトリを突き合わせる。 |
| `gen_err_report_nrow_fm.py` | 配線済みGDSに、検出済みの短絡・未接続ピンを可視化する非製造用ERRレイヤ（253/0-2）を追加したレビュー用コピーを生成。`route_channels_nrow_fm.py`から参照される。 |
| `detect_loops_jogs.py` | `net_shapes_nrow_fm_*.json`を対象に、各ネットの冗長な配線ループとM1ジョグ迂回を客観的に監査する診断ツール。 |

## 8. LVS・スキーマティック

| スクリプト | 役割 |
|---|---|
| `gen_schematic_v7.py` | 現行のv7ネットリスト（`src/i2c_slave_async_net_v7.v`）からLVS用xschemスキーマティック（`schematic/i2c_slave_async_nrow_fm.sch`）を生成。DFFRB/BUFTHは`LEF/`配下のプロジェクト固有sch/symを、他は`TR-1um_5_stdcell`を参照。 |
| `verify_schematic_v7.py` | xschem不要の独立幾何学的接続検証。生成された`.sch`が元のVerilogネットリストと接続等価であることを確認。 |

コアセル単体のLVS実行そのもの（実機xschem/KLayop環境）、およびトップレベル
（`tr_1um_i2c_slave_async`）のLVSクリーン化の経緯は design_notes.md §60〜75 を参照
（本セッションで発見・修正したVDD/VSSポート認識・グローバルネット・GIO/OUT2誤配線の
問題を含む）。

## 9. トップレベル統合（FRAME/GIO⇔コア）

| スクリプト | 役割 |
|---|---|
| `reassemble_top.py` | FRAME GDS編集後に、トップレベルGDS（`src/tr_1um_i2c_slave_async.gds`）内のOSS_FRAME_GIOインスタンスを最新のFRAME GDSのものに差し替える。実行後`src/tr_1um_i2c_slave_async_newgio.gds`を出力。 |
| `route_gio_core.py` | GIO⇔コア間の20信号＋VDD/VSSを結線する独自ルータ。周回座標（リング座標）上での区間スケジューリングによるレーン割り当て、VDD/VSSは専用半径での個別ルーティング。`src/tr_1um_i2c_slave_async_routed.gds`（最終トップレベル成果物）を出力。 |

再現手順:
```sh
cd script
python3 reassemble_top.py    # FRAME GDS変更を反映
python3 route_gio_core.py    # GIO⇔コア結線 → 最終トップレベルGDS
```

## 削除したスクリプトについて

開発過程で使われた以下のカテゴリのスクリプト（計52本）は、現行パイプラインから
参照されておらず、対応するデータ成果物（`layout/`旧世代GDS等）も既に削除済みのため
まとめて削除した。git履歴には残っているので、経緯を辿りたい場合は`git log`を参照。

- row/2row/2row_fm世代の配置・配線・検証スクリプト（`gen_placement_2row_fm.py`,
  `gen_placement_gds_2row*.py`, `route_channels_2row*.py`,
  `verify_connectivity_2row*.py`等） — nrow_fm世代に統合・置換済み
- 旧世代の汎用ルータ（`route_channel.py`, `route_channel_pilot.py`,
  `route_channel_shared.py`, `route_all_channels.py`, `route_cross_row.py`,
  `route_multihop.py`, `route_row_channels.py`, `plan_placement.py`） —
  `route_channels_nrow_fm.py`に統合済み
- v2/v3世代のRTLモデル・テスト（`i2c_slave_async_model_v2/v3.py`,
  `test_v2_*.py`, `test_v3_*.py`） — `i2c_slave_async_model.py` /
  `test_i2c_slave_async*.py`に統合済み
- 解消済みバグの一回限りデバッグ・ハイライトスクリプト
  （`gen_055_bitcnt1_highlight_nrow_fm.py`, `gen_priority_net_highlight_nrow_fm.py`,
  `gen_spine_step_highlight_nrow_fm.py`, `gen_shreg_subset_sch.py`等）
- 旧世代のスキーマティック生成・LVSチェッカー（`gen_schematic.py`,
  `gen_schematic_routed.py`, `lvs_check.py`, `verify_spice.py`） —
  `gen_schematic_v7.py` / `verify_schematic_v7.py`に置換済み
- STEP7の誤った初期実装（`run_route_v7_step7_compress.py`、
  `run_route_v7_step7_squeeze.py`のコメントに詳細） — 正しい実装に置換済み
- その他、事前見積もりツール（`estimate_*.py`）、旧チェックポイント実行器
  （`run_route_v6/v7_checkpoints.py`）、旧世代DRC/接続性チェッカー
  （`drc_check_2row*.py`, `drc_check_full.py`, `verify_channel_connectivity.py`,
  `verify_pilot_connectivity.py`）、RTL fanoutツール（`fanout_net.py`,
  `fanout_rtl.py`, `trace_cone.py`）
