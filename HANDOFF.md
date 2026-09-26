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
- ナレーション確定：VOICEVOX 中国うさぎ、速さ1.05倍（`config/voice.yaml`、規約は `docs/licenses/VOICEVOX.md`）
- 紙芝居舞台の構図の正本：`assets/reference/layout_stage_reference.webp`
- PHASE 1（Research Contract）完了：research schema（RESEARCH_POLICY の必須項目）、出典の信頼度QA、手動取り込み、research_review.md。`python -m pipeline.research`。
- 1話分の成果物は `episodes/<id>/` にまとめる。パスは `pipeline/workspace.py` の `ARTIFACTS`。
- PHASE 2（LLM Provider）完了：`python -m pipeline.generate script|storyboard <id>`。標準は manual（API不要、VS Code の Claude Code で `/generate-stage`）。`config/llm.yaml` の provider を claude にすると Anthropic API（claude-opus-5）を直接呼ぶ。詳細は `docs/LLM.md`。
- PHASE 3（Script）完了：ショート台本（`generate shorts`）、台本の自動チェック（`pipeline/script_guard.py`、ルールは `config/script_rules.yaml`、口調は `config/persona.yaml`）、`script_review.md`。
- 大仏飴の口調（Owner決定）：一人称「おら」、物語はです・ます調、コメントは栃木弁（`config/persona.yaml`）。
- PHASE 4（Storyboard / Asset Manifest）完了：`python -m pipeline.assets <id>` で素材一覧・レイヤー配置・画像の指示文を自動作成（`docs/DATA_CONTRACT.md`）。
- 次は PHASE 5（Image Provider）。

## 次の担当者
`docs/PHASE.md` の PHASE 0 から順に監査し、最初の未完了PHASEのみ実装すること。
