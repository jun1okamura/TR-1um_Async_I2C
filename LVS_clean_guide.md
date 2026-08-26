# KLayout LVS を Clean にする方法まとめ

対象: `i2c_slave_async_nrow_fm`（`script/*.lvs`, `layout/steps_v7_v2/*.gds`, `~/.xschem/simulations/i2c_slave_async_nrow_fm.spice`）

## 1. 現状の問題の切り分け

KLayoutのLVSは**名前に依存しないトポロジー一致**を基本とする（"LVS is basically
name-agnostic... Topology matching has priority"）。つまりMismatch/Ambiguousが出ても、
必ずしも実際の配線ミスとは限らない。今回のプロジェクトで実際に遭遇した問題は3種類に
分類できる。

| 分類 | 例 | 対処 |
|---|---|---|
| **実在するバグ** | `tx_data[0]`/`_074_`のM2物理ショート（stub net が `pin_map`/`net_shapes_log` から漏れていた） | v49/v50で修正済み（§69-70） |
| **ネット等価性のズレ** | schematic export時に未接続DFFR.QB（23本）がxschemで`net1`..`net23`と自動採番され、Verilog netlistの命名と食い違う | `gen_schematic_v7.py` v51で修正済み（§71） |
| **比較器のあいまいさ（真のバグではない）** | MUX2+DFFRシフトレジスタ×7段、busy/qnクロスカップルNOR2ラッチ — 対称構造でbacktrackingが誤ったペアを掴む | **未対応**（§72、今回のガイドの主題） |
| **トップピン照合の失敗** | `busy`⇔`RST_N`のクロス表示（Netlist Database Browserのcross reference） | 上記あいまいさの波及、または実バグ。要検証（下記手順） |

## 2. なぜ「あいまいさ」が起きるか（KLayout比較アルゴリズム）

- 抽出ネットリスト（`.extracted`）は**純粋な幾何学的抽出**で、内部ネットに文字ラベルが
  一切付かない（`04_Custom.lvs`のwriterはネット名を持たない）。
- 比較アルゴリズムは近傍トポロジー（gate→source/drainの経路パターン）でネットを
  一意識別しようとするが、シフトレジスタや対称ラッチのように**構造が繰り返される**と
  一意に決まらず、backtrackingで「とりあえず妥当な組み合わせ」を採用し
  "ambiguous match" として報告する。
- この時、選ばれた組み合わせがたまたま**間違っている**と、以降の周辺ネット比較も
  連鎖的にMismatchになる（busy/rst_n/addr_match/rx_validが同時にエラーになるのはこのため）。
- 参考: [LVS Compare](https://www.klayout.org/downloads/master/doc-qt4/manual/lvs_compare.html),
  [Ambiguity resolution issue in LVS (forum)](https://www.klayout.de/forum/discussion/1457/ambiguity-resolution-issue-in-lvs)

## 3. Cleanにする手順（推奨の順番）

### Step 1 — 電源ネットを最初に固定する
あいまいさが電源ネットに波及すると、そこから繋がる全部が連鎖的に崩れる。
`05_Compare.lvs`の`compare`の前に:
```ruby
same_nets!("i2c_slave_async_nrow_fm", "VDD")
same_nets!("i2c_slave_async_nrow_fm", "VSS")
```
を入れておくと安全（現状VSSはポート名一致、VDDはトップに明示ポートが無く`$49`という
無名ネットなので要注意 — `same_nets`で明示ペアリングするか、`make_top_level_pins`で
VDDにも名前を付けるかの検討が必要）。

### Step 2 — 実バグを先に潰す（完了済み）
tx_data[0]ショート、net1-23エイリアシングは修正済み。実バグが残っているとあいまいさと
区別がつかなくなるので、**必ずこの順番**（実バグ→あいまいさ）で対応する。

### Step 3 — あいまいな内部ネットにラベルヒントを与える（§72で保留していたオプション3）
KLayout公式ドキュメントも「ラベルによるネット名ヒントがbranch complexityを下げる
“preferred solution”」と明記している。方法は2通り:

**(a) レイアウト側に実際のテキストラベルを置く**
`01_Extract.lvs`/`02_Extract.lvs`のextract_devices/connect後、シフトレジスタ段の
D/Q配線やbusy/qnラッチの内部ノードにGDSテキストラベル（layer上の`TEXT`）を配置し、
抽出時にそれをネット名として拾わせる。KLayoutは`Layout#texts_on_net`的な仕組みで
ラベルをネット名候補として使う。恒久対策として最も確実。

**(b) `.lvs`スクリプトに`same_nets`ヒントを追加する**
GDSにラベルを打つのが大掛かりな場合、§72で直接ジオメトリ検証済みの80ネットの
対応関係が分かっているので、それを使って:
```ruby
same_nets("i2c_slave_async_nrow_fm", "<layout_net>", "<schematic_net>")
```
を該当ネットぶんだけ`compare`前に列挙する。`same_nets`（`!`なし）はヒントとして
働き、`!`付きは不一致を即エラーにする — まずはヒント版で全体のambiguityを崩し、
残った本当の不一致だけ`!`版で最終確認する2段構成が良い。

### Step 4 — `max_branch_complexity`を一時的に上げて様子を見る
デフォルト500では対称構造の組み合わせ爆発で探索を打ち切っている可能性がある。
```ruby
max_branch_complexity(2000)  # 要runtime増加を許容
```
これでambiguousが解消するなら、根本原因は「本当に対称で区別不能」なケース
（ラベル無しでは原理的に一意化できない）と判断できる。

### Step 5 — トップレベルピンを`flag_missing_ports`で厳格に検証する
`05_Compare.lvs`には既に`flag_missing_ports`が組み込まれている
（`IGNORE_TOP_PORTS_MISMATCH`で切替可能）。Step 1-4を適用した後にこれを実行し、
`busy`/`rst_n`/`addr_match`/`rx_valid`が正しい名前同士でペアになるか確認する。
まだクロスするようなら、それは**あいまいさの波及ではなく実際のピン割当バグ**の
可能性が高くなる（この場合は`pin_map_nrow_fm_v7rr.json`と実レイアウトのGDS上の
テキスト/パッド位置を直接突き合わせる — スクリプト側のリスト順には既に問題が
無いことは確認済み）。

### Step 6 — ボトムアップで階層的に検証する（`align`の副次効果）
`align`はトップセル以外の階層を落として**サブセル単位のLVS**を可能にする。
リーフセル（NOR4/OR2/OR3/OR4等の標準セル）→ MUX2+DFFR１段 → シフトレジスタ全体 →
トップ、の順に対象セルを絞って`compare`を繰り返すと、あいまいさがどの階層構造
（1段のMUX2+DFFRか、7段連結後か）で発生するかを切り分けられる。

### Step 7 — 最終確認
- `compare`が`true`、かつ`flag_missing_ports`もクリーン。
- 意図的に残す`same_nets`/`tolerance`等のヒントは最終版スクリプトから
  **必ずコメントアウトまたは削除**する（ドキュメントにも明記されている注意点:
  "Don't leave this statement in the script for final verification as it may
  mask real errors"）。

## 4. このプロジェクトでの次のアクション（優先順）
1. `same_nets!("i2c_slave_async_nrow_fm", "VDD")` / `"VSS"` をCompare前に追加。
2. §72で直接検証済みの80ネットの対応関係を`same_nets`ヒントとして`05_Compare.lvs`に
   投入し、再`compare`＋`flag_missing_ports`でbusy/rst_n/addr_match/rx_valid が
   解消するか確認。
3. 解消しない場合、`max_branch_complexity`を上げて再試行。
4. それでも解消しない場合は、シフトレジスタ／busy-qnラッチの内部ノードに
   実ラベルを追加する恒久対策（Step 3-a）に進む。
5. 全部クリーンになったら、デバッグ用ヒント（`same_nets`類）を外した最終版で
   もう一度`compare`を回して確定させる。

## 参考
- [KLayout LVS Compare](https://www.klayout.org/downloads/master/doc-qt4/manual/lvs_compare.html)
- [KLayout Ambiguity resolution issue in LVS (forum)](https://www.klayout.de/forum/discussion/1457/ambiguity-resolution-issue-in-lvs)
- [KLayout Issue #1921: unexpected LVS fail (ambiguous matching)](https://github.com/KLayout/klayout/issues/1921)
- [KLayout Issue #1135: LVS mismatch on parallel devices / ambiguity resolution](https://github.com/KLayout/klayout/issues/1135)
- design_notes.md §69-74（本プロジェクトの経緯・direct geometry検証結果）
