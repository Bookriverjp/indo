# 動画の書き出し（PHASE 8）

```bat
python -m pipeline.render EP0001_nishi_daak                 # 本番: output/episode.mp4（1920x1080, 30fps）と episode.srt
python -m pipeline.render EP0001_nishi_daak --preview       # 確認用: output/preview.mp4（960x540, 15fps）
python -m pipeline.render EP0001_nishi_daak --preview --start 60 --duration 20   # 一部分だけ
```
前提: `python -m pipeline.timeline <id>` で `render/timeline.json` ができていること。設定は `config/render.yaml`。
目安の速さ: 1920x1080・30fps で動画の長さの約2倍の時間（10分の本編で約20分）。

## 書き出しの前に止まる場合
- 素材画像がない → `python -m pipeline.images check <id>`。確認だけなら `--placeholders`（名前入りの仮の絵）
- 大仏飴パーツが Owner 未承認 → `assets/shared/daibutsuame/approval.yaml`。確認だけなら `--draft`（画面左下に「下書き」と出る）

## 画面の組み立て
- 物語の絵: 背景・人物・小物・前景・効果を重ね、窓の中でカメラを動かす（ゆっくり寄る・横に流す）。霧や炎などの効果は揺らす
- 紙芝居舞台テンプレート（`assets/shared/stage_template.png`）を上に重ねる。全面の場面は使わない
- 解説カード: 見出しは明朝、本文は丸ゴシック。現地名は現地の文字のフォント（`fonts.scripts`、research の `local_script` で選ぶ）
- 地域ラベル・字幕: 生成り地には焦げ茶、全面の場面の字幕は白に縁取り
- 大仏飴: 瞬き（毎回同じ位置に出るよう乱数を固定）、口パク（音量で開閉）、呼吸、表情ごとの体全体の動き。全面の場面では丸窓
- 切り替え: 黒からフェード／紙芝居の絵の引き抜き／クロスフェード
- 音声: ブロックごとの WAV をタイムラインの時刻に置いて1本にまとめ、AAC で入れる

## 使うもの
- ffmpeg: `imageio-ffmpeg` に同梱のものを使う（別途インストール不要）
- フォント: `assets/fonts/`（すべて SIL OFL）。インドの文字の表示には Pillow の raqm が必要
