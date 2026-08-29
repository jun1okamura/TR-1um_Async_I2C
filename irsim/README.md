# IRSIM チップレベル動作検証

**✅ 2026-08-30更新（design_notes.md §87-97、v9世代）**:
`tr_1um_i2c_slave_async.sim`はチップレベルDRC/LVSクリーン確認済みの
`schematic/tr_1um_i2c_slave_async_v9_lvs.spice`から
[`script/gen_irsim_sim_v9.py`](../script/gen_irsim_sim_v9.py)で生成。
`.cmd`群は[`script/gen_irsim_cmd_v9.py`](../script/gen_irsim_cmd_v9.py)
で生成（両方とも旧v7世代の`gen_irsim_sim.py`/`gen_irsim_cmd.py`を
置き換え）。**実機IRSIM 9.7.121で`irsim_test_main.cmd`
（WRITE 0xA5 → READ 0x3C）をエンドツーエンドで実行し、START/ADDR+ACK/
DATA+ACK/rx_data一致/STOP/busy解除まで全チェックが正しいことを確認
済み**（design_notes.md §97）。`irsim_test_negative.cmd`（不一致
アドレスNACK）も確認済み（§90.1）。

新`.sim`のトップレベル信号名（§87.4）：
`rst_n`=`P15`、`scl`=`P2`、`sda_in`=`P13`、`sda_oe`=`SDA_O`、`DIS`=`P7`、
`tx_data[0..7]`=`P12 P11 P5 P6 P4 P1 P3 P14`、`rx_data[0..7]`=
`NET_0..NET_7`、`busy`/`rw`/`addr_match`/`rx_valid`=
`NC_CORE_busy`/`NC_CORE_rw`/`NC_CORE_addr_match`/`NC_CORE_rx_valid`
（電源/GNDは従来通り`Vdd`/`Gnd`）。33個の`DFFRB`インスタンスの
リセットグループ構成（24＋9、4本の行クロックnet）は旧設計と完全に
同じ構造。

`start()`の非初回呼び出し（2回目以降のSTART）で使う`QM`/`QS`両方の
force/release、およびクロックnetを**HIGH**（LOWではない）で強制する
必要があることが分かった経緯は§89-96参照——`QM`（マスタ側記憶ノード）
はCK=0の間`D`に対して常時透過（ラッチされない）ため、CK=0のまま
フォースしても無意味で、CK=1でフォースする必要があった。

**旧版（v7世代）の到達点（このセクション以降は旧`.sim`ベースの記録、
参考用に残してある）**:
`script/test_i2c_slave_async.py`と同じ
シナリオ（WRITE 0xA5 → READ 0x3C）が`irsim_test_main.cmd`でチップレベルの
ゲートレベルネットリスト上、実機IRSIM実行で**エンドツーエンドに完全成功**
することを確認済み（design_notes.md §76.27）。それまでに解決した問題群
（`BUFTH`の帰還ループデッドロック、`DFFRB`のコールドスタート/リセット後
の`QM`/`QS`未更新問題、SDAパッドのHIZ極性・プルアップゲート、`sda_oe`↔
`HIZ13`間の欠落インバータ、`DIS`信号の未制約、`STOP`/`START`の`DEL1`
セトリング不足）は下記参照。

**`TR-1um.prm`（実TR-1umモデルベース、`scmos100.prm`プレースホルダの代替）**:
`script/gen_prm_characterize.py` → ローカルで`ngspice -b prm_char_L1.spi`/
`prm_char_L2.spi` → `script/build_tr1um_prm.py`の3段階で生成。実測フィット
済みTR-1umのBSIM3モデル（`~/Dropbox/91_OpenPDK/TR-1um/libs.tech/spice/
models/ip62_models`、vdd=5.0V）をIRSIM公式のキャリブレーション手順
（irsimソースツリー`lib/calibrate_spice3/`）でngspice特性化し、抵抗テーブル
（L=1u/2uの2点、design_notes.md §76.29）と`capga`/`capda`/`cappda`
（モデルの`tox`/`cj`から直接計算）を実データから求めた`.prm`。使い方:
`irsim TR-1um.prm tr_1um_i2c_slave_async.sim`。それ以外の点（配線層容量、
接合容量の側壁成分）はこのプロジェクトの`.sim`が層/面積注釈を持たないため
未対応（詳細はdesign_notes.md 76.29とスクリプト内コメント参照）。

`tr_1um_i2c_slave_async.sim`：チップ全体（コア`i2c_slave_async_nrow_fm` +
GIOパッドリング`OSS_FRAME_GIO`の全16個の`OSS_ESD_5V_DIO`/`VDD`/`VSS`パッドセル
まで含む）をトランジスタレベルまで再帰的にフラット化したIRSIM用`.sim`ファイル。
LVSクリーン済みの`src/tr_1um_i2c_slave_async.extracted`から
[`script/gen_irsim_sim.py`](../script/gen_irsim_sim.py)で機械的に生成。
`BUFTH`（scl/sda_inのSchmitt-trigger入力バッファ）のみ、実機で確認された
恒久的な問題（帰還ループのターナリ・デッドロック、§76.12/76.14）によりピン
互換の`BUF_X1`へ置換済み（`DEL1`も同種の仮説で一時的にBUF_X1カスケードへ
置換して検証したが、原因はDEL1ではなくIRSIM自体のモデル粒度と判明したため
実回路へ復元済み——§76.23/76.24）。実トランジスタ2074個＋SDAパッド用の
ゲート付き弱プルアップ1個＋`sda_oe`↔`HIZ13`間の合成インバータ2個＝計2077
トランジスタ、ノード数863。

`irsim_test_main.cmd` / `irsim_test_negative.cmd`：
[`script/gen_irsim_cmd.py`](../script/gen_irsim_cmd.py)が
`script/test_i2c_slave_async.py` / `script/test_i2c_slave_async_negative.py`
（既存のMyHDL機能検証）と全く同じバス上のトランザクションを機械的に翻訳して
生成したIRSIM刺激スクリプト。

## ノード名の注意（"$" → "N"、電源/GNDは"Vdd"/"Gnd"に固定）

`src/tr_1um_i2c_slave_async.extracted`はKLayoutの慣習で無名ネットを`$N`と
命名するが、IRSIM 9.7の（Tcl由来の）コマンドインタプリタは先頭の`$`を変数展開
記号として扱うため、`$58`のようなノード名をそのまま使うと実機で
`subcircuit "$58" is not defined!`のようなエラーになることを実際の実行結果で
確認した。そのため`gen_irsim_sim.py`は全ノード名の`$`を機械的に`N`へ置換して
いる（例: `$1`→`N1`、`X$3.busy`→`XN3.busy`）。

さらに、チップ全体のVDD/GND供給ノード（`$1`/`VSS`、置換後`N1`/`VSS`）は
**`Vdd`/`Gnd`という文字通りの名前へ追加でリネーム**している。理由: IRSIMは
デフォルトで電源/GNDネットを`Vdd`/`Gnd`という名前で自動検出しようとし
（`Using default name "Vdd" for power net`等のメッセージ）、この名前が
見つからない状態で`.sim`を読み込ませたところ**実機でセグメンテーション
フォールト**が発生することを確認した。`Vdd`/`Gnd`へリネームしたことで
この問題を回避している。以下は最終的な（置換・リネーム後の）名前。

## 実行方法

コマンドライン引数`-@ cmdfile`は環境によって解釈が異なりうる（手元の
IRSIM 9.7.121では`.cmd`が通常のネットリストとして誤って読み込まれ、多数の
構文エラーになることを確認済み）。**まずインタラクティブに起動し、プロンプト
上で`@`コマンドを使う方法を推奨**:

```sh
irsim <your-scmos.prm> tr_1um_i2c_slave_async.sim
irsim> @ irsim_reset_check.cmd    # まずこれで良い（リセットのみ、数秒で終わる）
irsim> @ irsim_test_main.cmd
irsim> @ irsim_test_negative.cmd
```

**バッチ（非対話）実行**: `-@`フラグではなく、上と同じ`@ file`コマンド列を
**stdinリダイレクト**で流し込む方法。実機で動作確認済み（末尾の`quit`
コマンドだけこのirsimビルドでは未対応と分かったため`run_batch.sh`からは
削除済み——それ以外は正常動作）:

```sh
cd irsim
./run_batch.sh [prm-file]     # 省略時 TR-1um.prm
# irsim_batch_run.log に全出力が残る
```

中身は`irsim <prm> tr_1um_i2c_slave_async.sim`をstdinヒアドキュメントで
`@ irsim_reset_check.cmd` → `@ irsim_test_main.cmd` →
`@ irsim_test_negative.cmd` → `quit`と流すだけ。もしこれも`-@`と同様に
うまく解釈されない場合は、従来通りインタラクティブ起動＋手入力にフォール
バックすること。

`irsim_reset_check.cmd`はリセットのみを100/500/1000/3000/8000ns時点で
チェックポイントdumpする軽量診断スクリプト。`sda_oe`/`busy`/`rw`/
`addr_match`がXのまま収束しない場合、トランザクションテストを実行しても
意味の無い結果になるため、まずこちらで確認すること
（design_notes.md §76.10、"ゲート型リセット"の説明参照——このチップの
`busy`はDFFRBではなくNOR2交差結合SRラッチで、33個のDFFRBのうち9個
（`sda_oe`含む）は`busy AND rst_n`というゲート済みリセットを使っているため、
`busy`ラッチ自体が収束するまでリセット解除直後は一時的にXへ戻りうる)。

さらに実機での検証で、`scl`/`sda_in`双方の入力バッファ`BUFTH`（Schmitt trigger）
自体に**内部帰還ループの問題**があることが判明した（design_notes.md §76.12）:
`BUFTH`内部の`N2`ノードは正帰還構造上`N6`と相互依存しており、入力`A`を
どれだけ長く確定値で保持してもIRSIMのternaryソルバーが冷起動状態からこの
ループの対称性を自発的に破れず、出力がXのまま収束しない。しかもこの問題は
冷起動時だけでなく**`scl`/`sda_in`が遷移する度に毎回再発する**ことも実機で
判明した（§76.14）。一度きりのforce/releaseも、恒久的な弱いバイアス
トランジスタの追加も実機では効果が無かった（§76.14で反証済み）ため、
**ユーザーの明示判断でBUFTHを`BUF_X1`（帰還の無い単純な2段インバータバッファ、
ピンリストが偶然完全一致）へ置換**した（`gen_irsim_sim.py`の
`substitute_bufth_with_buf_x1()`、§76.15）。BUFTHのSchmitt-trigger特性
（ノイズ耐性・ヒステリシス）はアナログ的な性質で、本検証の目的（デジタル
プロトコル論理の正しさ）にとっては本質的でないという判断による、意図的かつ
記録済みの例外。

さらに、SDAパッドのプルアップも弱いPMOSに変更している（常時ONの独立プルアップ
から変更）。ゲートは当初`sda_oe`(`N45`)に直結していたが、実機トレースで
`N45=0`＝「パッドが能動的にLOWを駆動中」（RTL意図の逆）と判明したため
（§76.17）、最終的にパッド自身の内部駆動インジケータ`XN1.XN16.N9`をゲートに
使う形へ変更した——`sda_oe`が実際に何を「意味する」かに関わらず、パッド自身の
実際のドライブ状態と構造的に必ず相補になる（`p XN1.XN16.N9 Vdd N58 20 1`）。

加えて、ユーザー指摘により実配線では`sda_oe`(`N45`)とSDAパッドの`HIZ13`
入力の間に本来あるべきインバータが**存在しない**（直結）ことが判明した
（`N45=0`＝Hi-Z解放ではなく能動LOW駆動になってしまい、アイドル時にSDAが
Hi-Zへ戻らずLOWに張り付く）。検証専用の対策として、`N45`とパッド内部の
実際のHIZゲート4トランジスタとの間にシミュレーション上の2トランジスタ
インバータを挿入した（`gen_irsim_sim.py`の`insert_sda_hiz_inverter()`、
§76.17/76.18）。これは実シリコンの修正ではなく、実配線に欠落インバータが
ある可能性を示す設計上の知見として記録している——実チップ側の対応が
別途必要。

BUFTH/DFFRB/SDA HIZの根本原因を修正した結果、`sda_oe`はブリングアップ期間中
`RSTB2=busy AND rst_n`のAND優勢則だけでSDAの値と無関係に確定した0を維持
できることも判明したため、当初導入した「SDAを`h`で強制」というワークアラウンド
は不要になり撤去した（`preamble()`は単に`x SDA`で解放するだけ）。

### DFFRB のリセット問題（コールドスタート時・実行中の両方）

チップ内33インスタンスの`DFFRB`（フリップフロップ標準セル）には、`BUFTH`と
同種のターナリ・デッドロックが一段深いところにある：`RSTB`ピンは`Q`/`QB`を
**アサートされている間だけ**直接force-driveするが、内部のマスタ/スレーブ
記憶ノード（`QM`/`QS`）には一切触れない。そのため(a)電源投入直後、一度も
クロックが来ていない状態で`RSTB`が解放されると`Q`はXのまま収束しないことが
あり（§76.13）、(b)実行中盤でも、`RSTB`ネット自体を一時的に外部force/release
しただけでは`QM`/`QS`が更新されないため`Q`はすぐ旧値に戻ってしまう（§76.26）。
唯一恒久的に効く対策は、各フロップ自身の`QS`ノードを直接force/releaseする
こと（`QB`はRSTB解放後`QS`の単純なインバータ、`Q`はさらにその単純なインバータ
という構造を利用）。`gen_irsim_cmd.py`の`CmdGen.force_release()`と
`dffrb_qs()`がこれを実装しており、(1)`preamble()`でRSTB=`$28`グループ24個
（電源投入時）、(2)`start(first=True)`でRSTB=`$227`グループ9個（`busy`が
初めて1になった直後）、(3)**`start()`（毎回のSTART条件ごと）**でも`$28`
グループ24個を再度force/release——RTLの`start_pulse`によるリセットパルス
（`$813`）がIRSIM上では原理的に発火しない（§76.23/76.24）ことの代替。

（`irsim_test_negative.cmd`も同様。`.cmd`ファイルはこの`irsim/`ディレクトリ内で
実行する前提のパス指定は無いので、`cd irsim`してから起動するか、`@`にフルパスを
渡すこと。）

`irsim -h`や`man irsim`でお使いのビルドにおける`-@`／コマンドスクリプトの
正確な仕様を確認できればそちらを優先して構わない。

`sanity_check.sim`：IRSIM公式チュートリアルのトランジスタ6個のAOIゲート例
（本プロジェクトとは無関係）。環境そのものが動くかどうかを切り分けたい時に
`irsim <prm> sanity_check.sim`でまず試すと良い。

`.prm`（電気パラメータファイル）はTR-1um実測の特性化データがまだ無いため、
このプロジェクトでは同梱していない。ローカルで動作確認済みのIRSIM環境が既に
使っている`scmos.prm`（インストール先の`prm/`ディレクトリ配下）をそのまま流用
すること。論理機能の検証（本スクリプトの目的）はそれで十分だが、遅延・タイミング
の絶対値はTR-1umの実特性を反映しない。実測データが揃い次第、専用`.prm`を作成する
こと（design_notes.md参照）。

## 信号→フラットノード対応表

| 信号 | ノード | 信号 | ノード |
|---|---|---|---|
| VDD | `Vdd` | rx_data[0] | `N32` |
| VSS | `Gnd` | rx_data[1] | `N15` |
| rst_n | `N106` | rx_data[2] | `N34` |
| scl | `N102` | rx_data[3] | `N13` |
| sda_in（SDAパッド） | `N58` | rx_data[4] | `N42` |
| sda_oe（内部、監視専用） | `N45` | rx_data[5] | `N78` |
| DIS（P7、通常H固定） | `N2` | rx_data[6] | `N83` |
| tx_data[0]（＝P12パッド生電圧） | `N26` | rx_data[7] | `N64` |
| tx_data[1]（＝P11） | `N19` | busy（内部） | `XN3.busy` |
| tx_data[2]（＝P5） | `N21` | rw（内部） | `XN3.rw` |
| tx_data[3]（＝P6） | `N22` | addr_match（内部） | `XN3.addr_match` |
| tx_data[4]（＝P4） | `N57` | rx_valid（内部） | `XN3.rx_valid` |
| tx_data[5]（＝P1） | `N103` | RSTB（`$28`グループ） | `XN3.N28` |
| tx_data[6]（＝P3） | `N72` | | |
| tx_data[7]（＝P14） | `N68` | | |

`XN3`はトップレベルにおけるコアセルのインスタンス名（元は`X$3`、
`src/tr_1um_i2c_slave_async.extracted`の`X$3 ... i2c_slave_async_nrow_fm`）。
busy/rw/addr_match/rx_validはチップの外部ピンには出ていない（design_notes参照）
が、IRSIM上では実機のプローブと同様、どの内部ノードも直接watch可能。

`sda_in`はSDAの実ボンドパッド自体（GIOのP13、`N58`と同一ノード）。このダイの
SDAドライバはオープンドレイン専用（`OSS_ESD_5V_DIO`のOUT端子がGnd固定配線——
`sda_oe=1`でLOWを駆動、`sda_oe=0`で解放）で、オンダイのプルアップが無いため、
外付けプルアップ相当のデバイスを`.sim`に追加している。当初`r`（抵抗）素子で
実装したところ実機IRSIM 9.7.121の`connect_txtors`で**確実に再現する
セグメンテーションフォールト**を引き起こすことが判明した（`r`素子無しでは
2082トランジスタ・867ノードが正常にロード・接続できることを実機で確認済み、
design_notes.md §76.9）。そのため弱いPMOSプルアップ（`20/1`、通常セルより
長チャネル・細幅で高抵抗相当）に置き換えた。ゲートは最終的に`XN1.XN16.N9`
（パッド自身の内部駆動インジケータ、上記参照）——実チップのオンダイI2Cプル
アップも抵抗ではなくこの種の弱いトランジスタで実装されることが多く、妥当な
代替。

### DIS（P7）信号

`DIS`（GIOの`P7`、`N2`）は8個の他パッド（`P1/P3/P4/P5/P6/P11/P12/P14`）の
HIZ制御を共有している。これら8パッドは全て真の双方向GIOで、パッド自身の
ボンドパッドノードがI2Cコアの「送信データ」（`TX`定数、コード中`tx_data`と
表記——実はレジスタではなく外部ピン電圧を直接組み合わせ的にサンプルしている
だけ）そのものであり、パッドの内部OUTドライバ（`DIS`解放時のみ有効）は実際の
`rx_data`DFFRBレジスタ（直近のI2C WRITEで受信した値）から配線されている
（design_notes.md §76.25）。`DIS=H`（本検証のデフォルト）ならパッド自身の
ドライバはHi-Zなので外部から`TX`を自由にforceできる。`DIS=L`にすると同じ
パッドが`rx_data`を能動駆動するため、直近のWRITE内容がそのままREADで読める
（見かけ上のループバックだが、実体はコア内部マルチプレクサではなくパッド共有）
——ただし`DIS=L`中に`TX`を外部forceするとチップ自身の出力と衝突するため
厳禁。`preamble()`/`gen_reset_check()`は`DIS`を`H`に強制している。

導出方法（コア側インスタンス`X$3`の実引数リストを`i2c_slave_async_nrow_fm`の
`.SUBCKT`仮引数順と突き合わせる、GIO側`X$1`の実引数リストとの相互検証込み）の
詳細はdesign_notes.mdを参照。
