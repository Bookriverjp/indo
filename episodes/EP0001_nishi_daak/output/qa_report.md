# QA レポート: EP0001_nishi_daak

## リサーチ — 確認待ち

## 台本・絵コンテ — 前の関門の承認待ち
- 警告: W_HOOK_LONG hook が90字（約15秒）を超えています
- 警告: W_LENGTH 長さが約7.3分です（目安 8〜12分）

## 画像 — 前の関門の承認待ち
- NG: 素材画像がありません: bg_s01_v01, bg_s03_v01, bg_s05_v01, bg_s06_v01, bg_s07_v01, bg_s08_v01, bg_s09_v01, bg_s10_v01, bg_s11_v01, bg_s13_v01, bg_s15_v01, bg_s18_v01（python -m pipeline.images check）
- NG: 大仏飴パーツが Owner 未承認です（assets/shared/daibutsuame/approval.yaml）

## 音声 — 前の関門の承認待ち

## 最終（動画・サムネイル・文面） — 前の関門の承認待ち
- NG: output/episode.mp4 がありません
- NG: output/episode.srt がありません
- NG: output/thumbnail.png がありません
