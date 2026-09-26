# HANDOFF.md

## Project
大仏飴のインド異聞 — 紙芝居YouTube自動化

## Ownerの意図
チンチラのキャラクター「大仏飴」を語り部として、日本では十分に紹介されていないインドの民話・伝説・怪異・言い伝えを紹介する。
映像はインド細密画を基調にした紙芝居風。
背景・人物・小物をパーツ化し、GPT/画像生成を使ってできる限り自動制作する。

## キャラクター正本
`assets/reference/daibutsuame_reference.jpeg`
- チンチラ
- 赤い首輪
- 鈴
- 草を持つ
この基準を崩さない。

## 自動化目標
テーマ候補 → リサーチ → 出典整理 → 台本 → 絵コンテ → パーツ生成 → TTS → 字幕 → 紙芝居レンダリング → サムネ → YouTubeメタデータ。
最終公開はOwner確認後。

## 現在
- PHASE 0（Foundation）完了：config loader、logging、episode workspace、JSON Schema validation、dry-run。`python -m pytest` で確認。
- 画面レイアウト確定：`docs/LAYOUT.md` / `config/layout.yaml`（モック：`docs/mockup/layout_mockup.html`）
- 大仏飴の動き・表情確定：`docs/CHARACTER_MOTION.md` / `config/character_motion.yaml`
- 本番API統合は未実装。次は PHASE 1（Research Contract）。

## 次の担当者
`docs/PHASE.md` の PHASE 0 から順に監査し、最初の未完了PHASEのみ実装すること。
