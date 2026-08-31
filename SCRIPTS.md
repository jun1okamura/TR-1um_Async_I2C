# script/ ガイド

`script/`配下の現行スクリプト（全59本）の説明資料。RTL設計からIRSIMチップ
レベル動作検証までの再現可能なパイプラインを構成するスクリプトを中心に、
v7→v8→v9の版遺産として今も参照される一部の旧版スクリプトも残している
（該当箇所に明記）。開発過程で使われた真に一回限りのデバッグ・実験用
スクリプトは削除済み（最新の削除分は末尾「削除したスクリプトについて」
参照）。各スクリプトのコメント冒頭に、より詳しい設計判断の背景
（design_notes.mdの節番号）が記載されている。

現行の最終ネットリスト/レイアウトは**v9**（`src/i2c_slave_async_net_v9_rowbuf.v`
137インスタンス、`src/tr_1um_i2c_slave_async.gds`、チップレベルDRC/LVS
クリーン確認済み、design_notes.md §86）。v7/v8はその前段の版で、
一部スクリプト（配置・配線の共通基盤、`gen_schematic_v7.py`等）はv9でも
そのまま再利用されている。

## 1. RTL・機能検証

| スクリプト | 役割 |
|---|---|
| `i2c_slave_async_model.py` | I2Cスレーブの非同期ロジックをMyHDLでモデル化した本体。`test_i2c_slave_async*.py`から参照される。 |
| `test_i2c_slave_async.py` | MyHDLイベント駆動シミュレータによる機能検証（write/readトランザクション、UM10204 3.1.4〜3.1.6準拠チェック）。 |
| `test_i2c_slave_async_negative.py` | 誤アドレスへのアクセスがNACKし、スレーブがidleに戻ることを確認する追加チェック。 |

実行方法はREADME.mdの「Python（MyHDL）による機能検証」参照。RTL/ゲート
レベルのVerilogテストベンチ（`src/i2c_slave_async_tb.v`／
`i2c_slave_async_net_tb.v`、iverilog/vvpで実行）も同じ3シナリオ・14
チェックで検証しており、そのIRSIM側の等価物が§10の`irsim_tb.cmd`。

## 2. 論理合成後ネットリスト加工

| スクリプト | 役割 |
|---|---|
| `insert_row_buffers.py` | Yosys合成直後のネットリストに対し、指定ネット（既定はscl/scl_n）へ配置行毎のBUF_X1バッファを挿入。`main(in_path=, out_path=, row_assignment_json=, target_nets=)`で引数化済み、任意のネットリストに再利用可能（v8/v9でも再利用）。 |
| `insert_bufth_scl_sda.py` | 上記の出力に対し、トップレベルの`scl`/`sda_in`にBUFTH（シュミットトリガ・バッファ）を挿入するネットリスト変換。`main(in_path=, out_path=, row_assignment_json=, tmp_stage1_path=)`で引数化済み、v8/v9でも再利用。 |
| `dedup_gates.py` | ABC合成後の共通部分式（CSE）除去パス（design_notes §77.29）。v9世代のネットリスト（`i2c_slave_async_net_v9*.v`系列）のインスタンス数削減に使用。 |
| `gen_liberty.py` | Yosys/ABC合成用のプレースホルダLiberty（`TR1um_5_stdcell.lib`）を生成。**タイミング値は全てプレースホルダ**（実SPICE特性化なし）。 |

## 3. LEF・標準セルライブラリ

| スクリプト | 役割 |
|---|---|
| `lef_parser.py` | `LEF/TR-1um_STDCELL.lef`を読む最小限のパーサ（MACRO SIZE・PIN形状）。配置・配線スクリプトの共通依存モジュール。 |
| `gen_lef.py` | セルの物理GDS（`LEF/TR-1um_STDCELL.gds`）からLEFを自動生成。prBoundary(235/0)でSIZE、M1PIN(48/1)/M2PIN(49/1)でピン境界、TXM1(48/0)/TXM2(49/0)のテキストラベルでピン名を決定する規約。`LEF/OSS_FRAME_GIO.lef`もこれと同じ考え方（テキストラベル一致方式）で生成した（元スクリプトは一時ファイルとして作業し保存されなかったため、再生成が必要な場合は本スクリプトの規約を`FRAME/TR-1um_frame_25x25.gds`のOSS_FRAME_GIOセル向けに適用する）。 |

セル一覧・実使用状況・DFFRBリセット極性等は[`logic_cells_mapping.md`](./logic_cells_mapping.md)参照。

## 4. 配置（Placement）

| スクリプト | 役割 |
|---|---|
| `netlist_parser.py` | Yosys出力の構造Verilログを読む最小限の構造Verilogパーサ。`assign`エイリアスの解決を含む。 |
| `fm_partition.py` | Fiduccia-Mattheysesハイパーグラフ分割（再帰二分割によるNウェイ）。クロス行ネット数を最小化する行割り当てに使用。 |
| `gen_placement_2row.py` | 2行配置のセル詰め込みヘルパー（`fill_combo`/`TRACK_UM`/`TAP_CELL`）。現行の`gen_placement_nrow_fm.py`から直接importされる共通依存。 |
| `gen_placement_nrow_fm.py` | 現行のN行配置ジェネレータ（`fm_partition`による行割り当て＋FILL2/FILL3の分散配置）。バージョンごとの`placement_nrow_fm_*.json`を生成。 |
| `gen_placement_gds_nrow_fm.py` | 配置JSONからセルインスタンスを並べた配置済みGDSを生成。 |

## 5. 配線（Routing）— コアセル本体

| スクリプト | 役割 |
|---|---|
| `route_channels_nrow_fm.py` | **現行の中核ルータ**（N行/(N+1)チャネル構成、約140KB）。TAP電源メッシュ→行内ローカル配線→高FO/隣接ペア配線→複数行またぎ配線→強制ジョグ処理の4パス方式。全viaは`via_1`PCellインスタンス。v7/v8/v9共通で使用。 |
| `ripup_reroute_shorts.py` | 汎用（ネット名非依存）のポストルート短絡自動修正。パスごとに異なる衝突回避ロジックを持つ`route_channels_nrow_fm.py`の限界を補う後処理。 |
| `fix_v8_remaining_shorts.py` | V8（DFFSなし版）でripup_reroute_shorts.pyが「両側複雑ネット」として自動修正を拒否した残り短絡3件を手動修正するワンオフスクリプト（design_notes §77.16）。`Fixer`クラス（ripup_reroute_shorts.py）のライブ衝突チェックを再利用しつつ、(1) 複数チャネルにまたがり分割記録された同一ネットの縦配線をまとめて1本として移設する`move_multi_piece_vertical`、(2) 行内部を貫通する未チェック区間まで毎回再検証してしまう`try_fix_horizontal`の限界を避け、旧track_yと新track_yの差分帯のみをチェックする`try_fix_horizontal_incremental`、の2つの汎用ヘルパーを追加。 |
| `fix_v9_remaining_shorts.py` | V9版の同種ワンオフ修正（design_notes §77.29-77.40、bit_cnt+last_bit_pending RTL・dedup_gates.py適用後ネットリスト・N_ROWS=4・N_GAPS=3不等分割）。`ripup_reroute_shorts.py`の自動パスが「両側複雑」として拒否した短絡をターゲット修正。 |
| `route_top_pins_nrow_fm.py` | STEP6: 全トップレベルポートをコアのBBOX端まで引き出し、M1PIN/M2PINマーカーを配置（フレーム結線の準備）。 |
| `add_power_pins_v8.py` | STEP6拡張（v8）：TAPセルのVDD/GND M2ストラップがBBOX上下端（Y=0/core_h）に達する箇所、およびM1電源パッドがBBOX左右端に達する箇所（最左右列のみ）に、信号ピンと同じM1PIN/M2PINマーカー規約でVDD/GNDトップピンを追加（design_notes §77.20）。 |
| `add_power_pins_nrow_fm.py` | v9版・汎用化した後継（design_notes 83.x付近）：チップ/コアBBOX端に実PINアノテーション（M1PIN/M2PIN＋TXM1/TXM2テキストラベル）が無くVDD/GNDだけ欠落していた問題を修正。TAP2/TAP3自体のセルレベルpinとメタルは既に正しくBBOX端に到達していることを確認した上で、信号ポートと同じ規約でVDD/GNDのチップレベルPINを追加。 |
| `highlight_top_pins_nrow_fm.py` | `route_top_pins_nrow_fm.py`が使う、各トップレベルポートの物理位置をハイライトする補助関数群（診断専用レイヤ260/2-3、実LVS/抽出フローでは参照されない）。 |
| `compress_channels_nrow_fm.py` | チャネル高さを縮めて配置・配線を再実行するポストプロセス（実測トラック使用量に基づく）。 |
| `squeeze_channels_nrow_fm.py` | 既存の配線済みGDSに対し、未使用のYスライスを幾何学的に除去してチャネル高さを圧縮（再配線なし）。 |
| `verify_connectivity_nrow_fm.py` | レイヤ別Union-Findによる短絡・未接続検出。ネットリストの`pin_map`と実ジオメトリを突き合わせる。 |
| `verify_connectivity_nrow_fm_m1m2.py` | 上記のM1優先・M2フォールバック版。トップレベルM2オンリーのスタブネットピン（M1探索のみの原版では「PIN NOT FOUND」誤検出）にも対応（design_notes §77.17）。 |
| `run_v8_step7_squeeze_step6_toppins.py` | V8向けSTEP7（チャネル圧縮）+STEP6（トップピン引き出し）統合ドライバ。ルータ実行ログが残っていないV8の配線実績からcompaction_infoを実測ベースで導出（design_notes §77.18）。 |
| `run_v9_step7_squeeze_step6_toppins.py` | V9向けの同種統合ドライバ（design_notes §77.41/77.42）。V9の最終収束済み配線（DRC 0違反・短絡0件）に対しSTEP7→STEP6を実行。 |

## 6. 配線 — 実行エントリポイント（v7レシピ、歴史的）

| スクリプト | 役割 |
|---|---|
| `run_route_v7_from_scratch.py` | v7レシピの配置→配線→リップアップ&リルート→DRC/接続性検証を一気通貫で実行する、ゼロから再現するための決定版スクリプト。 |
| `run_route_v7_step7_squeeze.py` | v7のSTEP7（チャネル圧縮→トップピン引き出し→再検証）の正しい実装。 |

v8/v9はこの一気通貫スクリプトを持たず、§5の各スクリプトを都度呼び出して
反復的に配置・配線を収束させている（design_notes §77.10以降）。

## 7. 検証（DRC・接続性・診断）

| スクリプト | 役割 |
|---|---|
| `drc_check_nrow_fm.py` | M1/M2幅・スペース、V1関連ルールのDRCチェック。 |
| `gen_err_report_nrow_fm.py` | 配線済みGDSに、検出済みの短絡・未接続ピンを可視化する非製造用ERRレイヤ（253/0-2）を追加したレビュー用コピーを生成。`route_channels_nrow_fm.py`から参照される。 |
| `detect_loops_jogs.py` | `net_shapes_nrow_fm_*.json`を対象に、各ネットの冗長な配線ループとM1ジョグ迂回を客観的に監査する診断ツール。 |

## 8. LVS・スキーマティック

| スクリプト | 役割 |
|---|---|
| `gen_schematic_v7.py` | v7ネットリスト（`src/i2c_slave_async_net_v7.v`）からLVS用xschemスキーマティック（`schematic/i2c_slave_async_nrow_fm.sch`）を生成。DFFRB/BUFTHは`LEF/`配下のプロジェクト固有sch/symを、他は`TR-1um_5_stdcell`を参照。`verify_schematic_v7.py`が動的importで直接依存しているため現役。 |
| `verify_schematic_v7.py` | xschem不要の独立幾何学的接続検証。生成された`.sch`が元のVerilogネットリストと接続等価であることを確認。 |
| `gen_lvs_spice_v9.py` | v9版の直接生成アプローチ：`src/i2c_slave_async_net_v9_rowbuf.v`から、xschemを経由せず直接フラットな構造SPICEネットリスト（コア単体、トップセル`i2c_slave_async_nrow_fm`）を生成。RING_OSC統合後のLVSでコアのVDD/GNDピン不一致（`FILL2`がレイアウト側では36個のサブサーキットインスタンス、スキーマティック側はバラ素子表記で不一致）が発覚し、FILL2のみサブサーキット呼び出し（`xFILL2_i VDD GND FILL2`）で生成するよう修正（FILL3はバラ素子表記のまま、design_notes §103.13）。 |
| `gen_lvs_spice_top_v9.py` | チップレベル（コア＋GIOフレーム）のLVS参照ネットリストを、コアLVSクリーン済みspice＋GIOスキーマティック＋`schematic/gio_connections.json`から合成生成。 |

コアセル単体のLVS実行そのもの（実機xschem/KLayout環境）、およびトップレベル
（`tr_1um_i2c_slave_async`）のLVSクリーン化の経緯は design_notes.md §60〜86
を参照（v9でのVDD/VSSポート認識・グローバルネット・GIO/OUT2誤配線・
HIZ端子未結線の修正を含む、チップレベルDRC/LVSクリーン確認は§86）。

## 9. トップレベル統合（FRAME/GIO⇔コア）

| スクリプト | 役割 |
|---|---|
| `assemble_top_v9.py` | v9トップレベルGDS（`src/tr_1um_i2c_slave_async.gds`）の骨格を新規構築：OSS_FRAME_GIOを`FRAME/TR-1um_frame_25x25.gds`から(0,0)に配置、コアをv7比でYオフセット調整して配置、PTECTエリアを設定。配線前に停止する設計（レビュー用）。 |
| `route_gio_core_v9.py` | v9版のGIO⇔コア結線ルータ（v7の`route_gio_core.py`の後継）。24信号＋VDD/GNDを、同じ周回座標（リング座標）レーン割り当てアルゴリズムで配線し、v9固有の入力（`assemble_top_v9.py`の配置、`schematic/v9_signal_routing_plan.json`等）に対応。 |
| `add_top_pins_gio_v9.py` | チップレベルTOP PIN（レイアウト側）を`src/tr_1um_i2c_slave_async.gds`に追加。16実ボンドパッドネット（P1-P7,VSS,P9-P15,VDD）を実際のPORT/PINとして露出（design_notes §82.x/83.x）。 |
| `add_hiz_vss_ties_v9.py` | v9の電源配線見直しで欠落していた、スキーマティック上必須の6本のVDD/VSSタイ（OSS_FRAME_GIOのHIZ2/HIZ7/HIZ15→VDD、HIZ9/HIZ10/OUT13→VSS）を復元するパッチスクリプト（design_notes §83.x/84.x）。 |
| `set_top_pin_text_size.py` | チップレベル16トップピンラベル（TXM2レイヤ49/0）のテキストサイズを20umに設定するレイアウト可読性向上の小ユーティリティ。位置・文字列・レイヤは変更しない。 |
| `reassemble_top.py` | FRAME GDS編集後に、トップレベルGDS内のOSS_FRAME_GIOインスタンスを最新のFRAME GDSのものに差し替える（v7版の`route_gio_core.py`実行前に使用）。 |
| `route_gio_core.py` | （v7版、歴史的）GIO⇔コア間の20信号＋VDD/VSSを結線する独自ルータ。`route_gio_core_v9.py`の設計上の前例として参照されている（コードとしては現行v9パイプラインから直接呼ばれない）。 |

v9の再現手順:
```sh
cd script
python3 assemble_top_v9.py       # コア+GIO+PTECT配置（配線前で停止）
python3 route_gio_core_v9.py     # GIO⇔コア結線
python3 add_top_pins_gio_v9.py   # チップレベルTOP PIN追加
python3 add_hiz_vss_ties_v9.py   # 欠落VDD/VSSタイの復元
```

## 10. IRSIMチップレベル動作検証（v9）

| スクリプト | 役割 |
|---|---|
| `gen_irsim_sim_v9.py` | `src/tr_1um_i2c_slave_async.extracted`（チップ全体、DRC/LVSクリーン済みv9）を再帰的にトランジスタレベルまでフラット化し、IRSIM用`.sim`（`irsim/tr_1um_i2c_slave_async.sim`、2077トランジスタ・845ノード）を生成。BUFTHはIRSIMのternaryスイッチレベルソルバでは正しく解けない恒久的制限があるため、`.sim`生成時のみBUF_X1へ機械的置換（`substitute_bufth_with_buf_x1()`、実レイアウトは変更なし、logic_cells_mapping.md §1参照）。SDAパッドへの外付けプルアップ抵抗も追加。 |
| `gen_irsim_cmd_v9.py` | v9の`.sim`ノード名に対応したIRSIM刺激スクリプト生成の共通基盤（`CmdGen`クラス）。`send_byte`/`read_ack`/`recv_bit`/`stop`等のバス手順に加え、`DFFRB`のQM（マスタ）/QS（スレーブ）両ノードをクロックHIGH時に強制する`force_release_gated()`（実行時リセット、design_notes §89-96で確立）を提供。`gen_main()`/`gen_negative()`/`gen_reset_check()`で`irsim_test_main.cmd`/`irsim_test_negative.cmd`/`irsim_reset_check.cmd`/`irsim_test_main_noforce.cmd`を生成。 |
| `gen_irsim_verilog_equiv_tb.py` | `src/i2c_slave_async_tb.v`と1対1対応する3シナリオ・14チェックを1本の`.cmd`にまとめた自己検証型テストベンチ`irsim/irsim_tb.cmd`＋期待値`irsim_tb_expected.json`を生成（design_notes §98）。`gen_irsim_cmd_v9.py`の`CmdGen.checked_dump()`を使用。 |
| `check_irsim_tb_log.py` | `irsim_tb.cmd`実行後の実ログを`irsim_tb_expected.json`と自動照合し、Verilogテストベンチの`$display("[t=%0t] %s: %s", ...)`と同じ書式でPASS/FAILレポートを出力（design_notes §98/§100）。IRSIM自体の`.cmd`言語に条件分岐・算術演算が無いため、この照合はオフライン後処理として実装。`-v`で個別ビットサンプルも表示。 |
| `gen_prm_characterize.py` | IRSIM公式のキャリブレーション手順（irsimソースツリー`lib/calibrate_spice3/`）に基づき、実TR-1um BSIM3モデルをngspiceで特性化するためのSPICEデッキを生成（実行はローカルのngspiceで行う）。 |
| `build_tr1um_prm.py` | `gen_prm_characterize.py`のngspice実行結果（`prm_char_L1/L2.raw`）とBSIM3モデル自身のパラメータ（tox/cj）から、実測フィット済みの`irsim/TR-1um.prm`を組み立てる。 |
| `gen_dffrb_reset_tb.py` | （歴史的診断）DFFRBのリセット解除直後の実アナログ挙動を、実TR-1umモデルでトランジスタレベルのngspiceテストベンチとして直接観測。QM/QS force/release手法確立（§89-96）の前段の調査（design_notes §76.30）。 |
| `analyze_dffrb_reset_tb.py` | 上記ngspice実行結果（`irsim/dffrb_reset_tb.raw`）からV(qs)/V(qb)/V(q)/V(rstb)の時系列とロジック閾値通過タイミングを report。 |

再現手順:
```sh
cd script
python3 gen_irsim_sim_v9.py            # チップ全体 → irsim/tr_1um_i2c_slave_async.sim
python3 gen_irsim_cmd_v9.py            # → irsim_test_main.cmd等
python3 gen_irsim_verilog_equiv_tb.py  # → irsim_tb.cmd, irsim_tb_expected.json
cd ../irsim
./run_tb.sh                            # 実行＋自動PASS/FAIL判定を1コマンドで
```
詳しい実行方法・信号対応表・波形（アナライザ）の見方は
[`irsim/README.md`](./irsim/README.md)を参照。

## 11. RING_OSC統合

コア（`i2c_slave_async_nrow_fm`）横にリング発振器`RING_OSC`を追加配置・
配線・LVS統合したパイプライン（design_notes §103）。実機KLayoutでの
チップレベルDRC/LVSクリーンを確認済み。

| スクリプト | 役割 |
|---|---|
| `place_ring_osc.py` | STEP1: `ring_osc/RING_OSC.gds`を単一セルインスタンスとしてv9最終チップGDSへ配置のみ実施（配線前、レビュー用のステージング出力）。 |
| `gen_lef_ring_osc.py` | RING_OSCのLEF生成。`gen_lef.py`と同じテキストラベル一致方式（prBoundary/M1PIN・M2PIN/TXM1・TXM2）だが、RING_OSCはハードマクロのためCLASS BLOCK・SITE無し、かつ座標系はRING_OSC.gds自身のネイティブローカル座標のまま（原点(0,0)への詰め替えはしない）。実DRCでM2幅違反（1.8um、実ルールは3.0um以上）が出た後に導入し、以降のピン位置取得はGDSテキストの目視スキャンではなく本LEFを正とする。 |
| `route_ring_osc_power_v9.py` | コア両端のTAP2 M2ストラップをRING_OSCまで延伸するVDD/VSS電源配線。当初案にあったRING_OSC上下M1(10um)バスは実DRCでショートが発覚しユーザー指示で撤去済み（design_notes §103.3）。 |
| `route_ring_osc_signals_v9.py` | RING_OSCのOUT/OUTD/ENB信号配線。実DRC39件（M2幅1.8um誤り等）を`gen_lef_ring_osc.py`のLEF導入とM1/M2/PAD幅統一（3.4um、via_1ランドパッド幅に合わせフラットな接続に）で解消。以降複数ラウンドの実DRC/目視確認でP15配線・ENB-VSSショート等を修正（design_notes §103.5〜103.8）。 |
| `gen_lvs_spice_ringosc_v9.py` | RING_OSC統合後のチップ全体LVS参照SPICEを生成。RING_OSC/INV3D/FILL2を独立サブサーキットとして保持するネスト構造（実LVS比較で正しいことを確認済み、design_notes §103.9〜103.12）。 |
| `place_opensusi_logo.py` | コア〜RING_OSC間の空きスペースに、添付PNGをピクセルアート的にデジタイズしたOpenSUSIロゴをM2アートとして配置。PITCH=Wmin+Sminのグリッドで幅・スペースDRCを構造的に満たし、スペースをはみ出さない最大サイズ（319×65セル）で中央配置。配置前後でDRC違反差分0を自己検証（design_notes §103.14）。 |
| `gen_ring_osc_tb.py` | RING_OSC単体の自己検証用ngspiceテストベンチ（`ring_osc/TB/`）を生成。LVSクリーンな`ring_osc/RING_OSC.extracted`（レイアウト抽出netlist）を使用し、実行はローカルngspiceで行う。INV3DのAS/AD抽出誤り（アンテナダイオード拡散が実レイアウトでは出力ノード側なのに抽出netlistでは電源側になっていた）を発見し、シミュレーション用コピー`RING_OSC_extracted_sim_ready.spice`のみ修正（マスタの`.extracted`は無改変、design_notes §103.16〜103.22）。 |

実測確認済み（ローカルngspice、`.tran`3us）: `OUT`周期153.661ns/6.508MHz、
`OUTB`周期641.844ns/1.558MHz（RISE1/2とRISE3/4のクロスチェックが完全一致、
定常発振を確認）。再現手順:
```sh
cd script
python3 gen_ring_osc_tb.py     # → ring_osc/TB/tb_ring_osc.spice 一式
cd ../ring_osc/TB
ngspice -b tb_ring_osc.spice   # 実行はローカル環境で（本サンドボックスにngspice無し）
```

## 削除したスクリプトについて

開発過程で使われた以下のカテゴリのスクリプトは、現行パイプラインから
参照されておらず、対応するデータ成果物も既に削除済みのためまとめて
削除した。git履歴には残っているので、経緯を辿りたい場合は`git log`を
参照。

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
- **（今回追加）** v7時代のIRSIM `.sim`/`.cmd`生成器（`gen_irsim_sim.py`,
  `gen_irsim_cmd.py`） — v9ネットリスト対応の`gen_irsim_sim_v9.py`/
  `gen_irsim_cmd_v9.py`に置換済み
- **（今回追加）** v7時代のIRSIM READトランザクション/SDA/BUFTHバグ調査で
  使った一回限り診断スクリプト15本（`gen_irsim_debug_addrmatch.py`,
  `addrmatch2`, `bitcnt`, `dffrb2`, `n123n235`, `n23`, `n697`, `phase`,
  `rstb`, `rw2`, `rwmargin`, `sdaoe`, `shreg`, `shregclk`, `stop`の各
  `gen_irsim_debug_*.py`）と、v9でのREADバグ調査に使った
  `gen_irsim_debug_read_addr.py` — いずれも根本原因は解消済みで
  design_notes.mdに経緯を記録済み（v7側は§76、v9側は§89-96）。対応する
  `irsim/irsim_debug_*.cmd`/`.log`一式、BUFTH単体切り分け用の
  `irsim/bufth_isolated*.cmd/.sim`、`irsim/sanity_check.sim`も同時に削除
- **（今回追加）** v9配置配線パラメータ（N_GAPS/N_ROWS）の実現可能性を
  探る一回限りの実験スクリプト5本（`test_fixed1620_route.py`,
  `test_ngaps2_placement.py`, `test_ngaps2_route.py`,
  `test_nrows5_route.py`, `test_v4_1620_route.py`） — 最終的に採用された
  パラメータはdesign_notes §77.x系列に記録済みで、`gen_placement_nrow_fm.py`
  等の現行スクリプトへの引数として反映されている
