v6 配置配線ステップ別レイアウト（アニメーション用）
====================================================
design_notes.md 43節・44節参照。全ステップDRC 0違反。
step0〜6はコア高さ1181.2um、step7は1111.2um、step8は891.2um
（KLayoutでアニメーション表示する際、コア高さが途中で変わる点に注意）。

v6_step_0_placement.gds
  配置直後（配線なし、セルのみ）

v6_step_1_tap_power_mesh.gds
  TAP2電源メッシュ（VDD/GND M2ストラップ）配線後
  レイヤー(258,1)=このステップ終了時点の実残余チャネル容量

v6_step_2_pass0_per_row_local.gds
  pass 0：per-row-localネット（RSTB1, RSTB2, sda_in, scl, addr_ok,
  _071_, _086_）のトランク＋スパイン配線後
  レイヤー(258,2)=同上

v6_step_3_pass1_high_fo_row_only_adjacent.gds
  pass 1：高FO＋行内／隣接行ペアネット配線後
  レイヤー(258,3)=同上

v6_step_4_pass2_spanning.gds
  pass 2：行またぎ（spanning）ネット配線後（v6は該当0件のためstep3と
  幾何学的に同一）
  レイヤー(258,4)=同上

v6_step_5_pass3_force_jog_nets.gds
  pass 3：FORCE_JOG_NETS（診断済み16ネットの最終ライブチェック付き
  配線）後＝最終配線結果
  レイヤー(258,5)=同上（最も信頼できる実残余容量）
  短絡0件・DRC 0違反（43.6節：draw_jogのトラック再利用優先化により
  解消）

v6_step_6_with_err_highlight.gds
  エラーハイライト付き最終版（レイヤー253系）。短絡0件のため
  (253,0)/(253,3)は空。

v6_step_7_minheight_compressed.gds
  43.7/43.8節：CH_HEIGHTSを実測トラック数ぴったりまで縮小し配置
  配線をやり直した後処理版。コア高さ1181.2um→1111.2um（-5.9%）。

v6_step_8_squeezed_final.gds
  44節：step7の配線を一切変更せず、幾何学的にY軸方向へ後圧縮した
  最終版。コア高さ1111.2um→891.2um（-19.8%、元の未圧縮版からは
  通算-24.6%）。レイヤー253系のエラーハイライトは別ファイル
  `../i2c_slave_async_nrow_fm_v6_squeezed_with_err.gds`。
