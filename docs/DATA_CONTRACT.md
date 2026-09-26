# データ契約

## Episode ID
`EP0001_nishi_daak` のような形式を推奨。

## Episode directory
1話で使う素材・構成・セリフなど、その回だけの成果物はすべて `episodes/<episode_id>/` にまとめる（2026-09-26 Owner指示）。
パスの正本は `pipeline/workspace.py` の `ARTIFACTS`。各stageは `episode_paths()` からパスを受け取り、エピソードフォルダの外へ書かない。

```
episodes/<episode_id>/
  episode.json                 エピソードの基本情報
  research/
    research.json              リサーチ（schemas/research.schema.json）
    research_review.md         Research Gate の確認レポート
  script/
    script_request.md          manual モードの生成依頼（プロンプト・入力・schema）
    script_response.json       manual モードで外から作った JSON
    script_main.json           本編の台本（schemas/script.schema.json）
    script_main.md             本編の台本（人が読む版）
    script_review.md           台本の自動チェック結果と Owner 確認欄
    script_shorts_request.md   manual モードの生成依頼（ショート）
    script_shorts_response.json
    script_shorts.json         ショートの台本（schemas/shorts.schema.json）
    script_shorts.md           ショートの台本（人が読む版）
    script_shorts_review.md    ショートの自動チェック結果
    subtitles.srt              字幕
  storyboard/
    storyboard_request.md      manual モードの生成依頼
    storyboard_response.json   manual モードで外から作った JSON
    storyboard.json            絵コンテ
    asset_manifest.json        この回の素材一覧とレイヤー配置（schemas/asset_manifest.schema.json）
    asset_manifest.md          素材一覧（人が読む版）
  assets/
    image_requests.md          画像の生成依頼（manual）
    image_status.md            画像の取り込み状況
    inbox/                     生成した画像を置く場所（Git管理外）
    generated/                 チェック済みの背景・人物・小物・FX（Git管理外）
  audio/generated/             この回のナレーション音声（Git管理外）
  render/timeline.json         紙芝居タイムライン（Git管理外）
  output/
    episode.mp4                本編
    shorts.mp4                 ショート
    thumbnail.png              サムネイル
    youtube_metadata.json      タイトル・説明文・タグ
    qa_report.md               Final Gate の確認レポート
  logs/pipeline.log
  logs/llm_usage.jsonl         LLM のトークン数と費用の目安（claude モード）
  logs/image_usage.jsonl       画像生成の記録（openai モード）
```

## 共通素材（全話で使い回すもの）
エピソードフォルダには入れず、リポジトリ直下に置く。
- `assets/reference/`：大仏飴の基準画像、紙芝居舞台の構図の正本
- `assets/shared/stage_template.png`：紙芝居舞台テンプレート
- `assets/shared/daibutsuame/`：大仏飴のパーツ（REQUEST.md、approval.yaml）
- `assets/`：共通BGM・効果音（PHASE 6 以降で追加）
- `config/`：レイアウト、動き、声などの設定

## Asset manifest（PHASE 4）
`python -m pipeline.assets <episode_id>` で storyboard.json から作る。LLM は使わない。
- 同じ表記の背景・人物・小物・前景・効果は1つの素材にまとめ、複数 scene で使い回す（asset_id は `bg_s01_v01`、`char_01_v01` など）
- 大仏飴（`shared_daibutsuame`）と舞台テンプレート（`shared_stage_template`）は共通素材として参照するだけで、この回では生成しない
- 画像の指示文は `prompts/05_image_background.md`・`06_image_character.md`・`09_image_part.md` から作り、`config/visual_style.yaml` の地域トーンを入れる
- scene ごとのレイヤーは、layout の窓（template / story_art / narrator）に対する相対 box [x, y, w, h] と重ね順 z で持つ。card には物語の絵を置かない。hook の fullbleed では大仏飴を出さない

## Research
- 手作業で書いたリサーチは `templates/research_template.yaml` をコピーして埋め、`python -m pipeline.research import <episode_id> <file>` で取り込む。
- 自動QAの判定は PASS / WARN / FAIL。FAIL のときは research.json を保存せず、research_review.md だけ出す。
- 取り込み済みの research.json は `python -m pipeline.research check <episode_id>` で再確認できる。

## Asset naming
- bg_s01_v01.png
- char_daibutsuame_talk_v01.png
- char_main_scared_v01.png
- prop_lamp_v01.png
- fx_fog_v01.png

## Provider-independent
LLM、image、TTS、publisherはすべてinterface経由。
コアのworkflowが特定サービスへ直接依存しないこと。
