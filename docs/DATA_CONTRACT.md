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
    script_main.md             本編の台本（セリフ）
    script_shorts.md           ショートの台本
    subtitles.srt              字幕
  storyboard/
    storyboard.json            絵コンテ
    asset_manifest.json        この回の素材一覧
  assets/generated/            この回の背景・人物・小物・FX（Git管理外）
  audio/generated/             この回のナレーション音声（Git管理外）
  render/timeline.json         紙芝居タイムライン（Git管理外）
  output/
    episode.mp4                本編
    shorts.mp4                 ショート
    thumbnail.png              サムネイル
    youtube_metadata.json      タイトル・説明文・タグ
    qa_report.md               Final Gate の確認レポート
  logs/pipeline.log
```

## 共通素材（全話で使い回すもの）
エピソードフォルダには入れず、リポジトリ直下に置く。
- `assets/reference/`：大仏飴の基準画像、紙芝居舞台の構図の正本
- `assets/`：大仏飴のパーツ、舞台テンプレート、共通BGM・効果音（PHASE 5 以降で追加）
- `config/`：レイアウト、動き、声などの設定

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
