# 実装PHASE

各PHASEは Red → Green → Refactor → Debug/Release確認 → 監査 → Owner確認 → ローカルGitコミット。

## PHASE 0 — Foundation
- Python環境
- config loader
- logging
- episode workspace
- JSON Schema validation
- dry-run
完了条件：APIなしで1 episode folderを生成できる。

## PHASE 1 — Research Contract
- research schema
- source record
- reliability
- manual import
- research QA
完了条件：サンプル題材をschemaで検証できる。

## PHASE 2 — LLM Provider
- provider interface
- prompt loader
- structured output
- retry
- token/cost log
完了条件：researchからscript/storyboard JSONを生成。

## PHASE 3 — Script
- main script
- shorts script
- Daibutsuame persona
- fact/legend phrasing guard
完了条件：台本品質テスト。

## PHASE 4 — Storyboard / Asset Manifest
- scene分割
- part分解
- placement hints
完了条件：1話のasset manifestが自動生成。

## PHASE 5 — Image Provider
- background
- character
- prop
- fx
- output naming
- retry
- reference image support
完了条件：大仏飴参照画像を保持した素材生成ワークフロー。

## PHASE 6 — TTS
- narration
- pronunciation dictionary
- per-block WAV
完了条件：台本から音声素材生成。

## PHASE 7 — Timeline
- scene duration
- pan/zoom
- transition
- subtitle timing
完了条件：timeline.json生成。

## PHASE 8 — Renderer
- 16:9
- layers
- motion
- audio mix
- SRT
完了条件：紙芝居MP4をローカル書き出し。

## PHASE 9 — Thumbnail / Metadata
- thumbnail brief
- thumbnail generation
- title/description/tags
完了条件：投稿一式を出力。

## PHASE 10 — QA Dashboard
- research gate
- visual gate
- audio gate
- final gate
完了条件：Ownerが確認してapprove/reject可能。

## PHASE 11 — YouTube Upload
- OAuth
- upload
- private/unlisted default
- schedule
完了条件：Owner承認済み動画のみアップロード。

## PHASE 12 — Batch
- queue
- resume
- per-episode isolation
- failure report
完了条件：複数話を安全に順次生成。

## PHASE 13 — Optimization
- cost
- cache
- duplicate assets
- reusable Daibutsuame poses
- performance
