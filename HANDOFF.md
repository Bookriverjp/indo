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
- PHASE 5（Image Provider）完了：`python -m pipeline.images`（request / check / generate、shared-template / shared-request / shared-check）。標準は manual、`--provider openai` で API。詳細は `docs/IMAGES.md`。
- 大仏飴パーツ：最小セット（体・目の開閉・口の開閉）は作成済み・Owner未承認。目と口の開きは基準画像から切り出し、ほかは仮版（`shared-draft`）。追加セットは未作成（`assets/shared/daibutsuame/REQUEST.md`）。
- PHASE 6（TTS）完了：`python -m pipeline.tts <id>`（VOICEVOX、ブロックごとの WAV と `audio/narration.json`、読み方の辞書、栃木弁の抑揚）。詳細は `docs/TTS.md`。
- PHASE 7（Timeline）完了：`python -m pipeline.timeline <id>` で `render/timeline.json` と `script/subtitles.srt`（`config/timeline.yaml`）。
- PHASE 8（Renderer）完了：`python -m pipeline.render <id>`（`--preview` / `--placeholders` / `--draft`）。詳細は `docs/RENDER.md`。
- 大仏飴の体（body_base）は基準画像の白い背景を透明にした。舞台テンプレートは大仏飴の輪郭まわりを補間して作り直した。
- 概要欄には出典もクレジットも載せない（Owner決定）。出典は動画の締めの出典カード、VOICEVOX のクレジットは動画の最後の場面に小さく表示。
- PHASE 9（Thumbnail / Metadata）完了：`python -m pipeline.generate metadata <id>`（チャプター自動）、`python -m pipeline.thumbnail <id>`。詳細は `docs/LLM.md`。
- PHASE 10（QA Dashboard）完了：5つの関門（リサーチ・台本・画像・音声・最終）と確認画面 `python -m pipeline.qa serve <id>`。詳細は `docs/QA.md`。
- チャンネル方針と最初の10本の計画: `docs/CHANNEL.md`（怖い話だけのチャンネルにしない）。
- 第1話 `EP0001_nishi_daak`：research.json を取り込み（自動QA PASS）。本文を確認できていない資料があるため、`research/fact_check.md` の確認が済むまで Research Gate は承認しない。
  - Owner の台本（シナリオ）を取り込み済み（40ブロック・約7.3分）。物語（hook・story）はです・ます調、それ以外は栃木弁。女性の声は VOICEVOX:四国めたん（ささやき）。
  - 絵コンテ20場面・効果音（虫・川・風・鈴）・ナレーション・タイムライン・概要欄まで作成済み。下書きプレビュー `output/preview.mp4`（Git には入れない）。
  - 残り：物語用の背景12枚（Owner が生成中 → `assets/inbox/<asset_id>.png` → `python -m pipeline.images check`）、大仏飴パーツの Owner 承認、Research Gate 承認、本番の書き出しとサムネイル。
- ローカル（Windows + VS Code）への移行手順: `docs/LOCAL_SETUP.md`。
- 背景ループ（Owner依頼 2026-09-27）：1枚の背景画から、雲・川・木と草・蛍・花びら・前ボケが動く継ぎ目のないループ動画を作る `python -m pipeline.bgloop <scene.yaml>`。1シーン目は夜の川辺の村（`assets/bgloop/night_river.yaml`）。詳細は `docs/BGLOOP.md`。紙芝居の書き出し（`pipeline.render`）にはまだつないでいない。
- 次は PHASE 11（YouTube Upload）。最終関門の承認済みの動画だけをアップロードする。

## 次の担当者
`docs/PHASE.md` の PHASE 0 から順に監査し、最初の未完了PHASEのみ実装すること。
