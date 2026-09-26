# 大仏飴パーツの依頼書

外見の正本: `assets/reference/daibutsuame_reference.jpeg`（1254x1254）。外見（灰白色の毛、赤い首輪、金色の鈴、草）を変えない。

## 共通の仕様
- すべて 1254x1254 の透明背景 PNG。正本と同じ位置・同じ大きさで描き、重ねるとぴったり合うこと
- body.png は目・口・耳・腕を除いた頭と胴。ほかのパーツは自分の部分だけを描く
- 表情の違いは目・口・耳・腕の組み合わせで作る（docs/CHARACTER_MOTION.md）
- ぴくっ・揺れ・鳴る（twitch / sway / swing / ring / droop）は画像を作らず、動画で回転・移動させる
- 仕上がったら Owner が確認し、approval.yaml の approved を true にする。承認前のパーツは動画に使わない

## 作るファイル

- [ ] `body.png` — body
- [ ] `ear_l_up.png` — ear_l: up
- [ ] `ear_l_down.png` — ear_l: down
- [ ] `ear_r_up.png` — ear_r: up
- [ ] `ear_r_down.png` — ear_r: down
- [ ] `eye_l_open.png` — eye_l: open
- [ ] `eye_l_half.png` — eye_l: half
- [ ] `eye_l_closed.png` — eye_l: closed
- [ ] `eye_l_smile.png` — eye_l: smile
- [ ] `eye_l_wide.png` — eye_l: wide
- [ ] `eye_l_teary.png` — eye_l: teary
- [ ] `eye_l_sleepy.png` — eye_l: sleepy
- [ ] `eye_r_open.png` — eye_r: open
- [ ] `eye_r_half.png` — eye_r: half
- [ ] `eye_r_closed.png` — eye_r: closed
- [ ] `eye_r_smile.png` — eye_r: smile
- [ ] `eye_r_wide.png` — eye_r: wide
- [ ] `eye_r_teary.png` — eye_r: teary
- [ ] `eye_r_sleepy.png` — eye_r: sleepy
- [ ] `mouth_closed.png` — mouth: closed
- [ ] `mouth_small.png` — mouth: small
- [ ] `mouth_open.png` — mouth: open
- [ ] `mouth_wide.png` — mouth: wide
- [ ] `mouth_smile.png` — mouth: smile
- [ ] `mouth_frown.png` — mouth: frown
- [ ] `mouth_o.png` — mouth: o
- [ ] `mouth_munch.png` — mouth: munch
- [ ] `nose_rest.png` — nose: rest
- [ ] `whisker_l_rest.png` — whisker_l: rest
- [ ] `whisker_r_rest.png` — whisker_r: rest
- [ ] `arm_grass_hold.png` — arm_grass: hold
- [ ] `arm_grass_point.png` — arm_grass: point
- [ ] `arm_grass_chin.png` — arm_grass: chin
- [ ] `arm_grass_cover_mouth.png` — arm_grass: cover_mouth
- [ ] `arm_grass_hug.png` — arm_grass: hug
- [ ] `arm_grass_raise.png` — arm_grass: raise
- [ ] `arm_free_rest.png` — arm_free: rest
- [ ] `arm_free_raise.png` — arm_free: raise
- [ ] `arm_free_namaste.png` — arm_free: namaste
- [ ] `bell_rest.png` — bell: rest
- [ ] `tail_rest.png` — tail: rest
- [ ] `fx_tear.png` — 効果: tear
- [ ] `fx_sweat.png` — 効果: sweat
- [ ] `fx_zzz.png` — 効果: zzz
- [ ] `fx_exclaim.png` — 効果: exclaim
- [ ] `fx_question.png` — 効果: question
- [ ] `fx_sparkle.png` — 効果: sparkle
- [ ] `fx_gloom.png` — 効果: gloom
- [ ] `fx_dust.png` — 効果: dust
- [ ] `fx_ring.png` — 効果: ring
- [ ] `fx_whisper_dots.png` — 効果: whisper_dots
- [ ] `prop_scroll.png` — 小物: scroll
