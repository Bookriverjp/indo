# 素材画像（PHASE 5）

設定は `config/image.yaml`。`image.provider` の標準は `manual`（APIなし）。

## この回の素材
前提: `python -m pipeline.assets <id>` で `storyboard/asset_manifest.json` ができていること。

### manual（APIなし）
```bat
python -m pipeline.images request EP0001_nishi_daak
```
`episodes/<id>/assets/image_requests.md` に、素材ごとの指示文・生成サイズ・透過の要否が並ぶ。
ChatGPT などで画像を作り、`episodes/<id>/assets/inbox/<asset_id>.png`（webp / jpg も可）に保存してから:
```bat
python -m pipeline.images check EP0001_nishi_daak
```
- 背景は 1920x1080 に整える（中央で切り抜き）。短い辺が 720px 未満はやり直し
- 透過が必要な素材（人物・小物・前景・効果）は、透明な部分がなければやり直し
- 合格した画像は `assets/generated/<asset_id>.png` に保存し、状況を `assets/image_status.md` に書く

### openai（API）
```bat
python -m pipeline.images generate EP0001_nishi_daak --provider openai
```
`.env` に `OPENAI_API_KEY` が必要。モデルは `gpt-image-1`（透明背景に対応）。
チェックに落ちた画像は `check_retries` 回まで作り直す。すでにある画像は作り直さない（`--force` で作り直す）。
生成の記録は `logs/image_usage.jsonl`。

## 共通素材（全話で使い回す。最初に一度だけ作る）
### 紙芝居舞台テンプレート
```bat
python -m pipeline.images shared-template
```
構図の正本 `assets/reference/layout_stage_reference.webp` から `assets/shared/stage_template.png` を作る。
物語の絵の窓を透明に抜き、字幕枠・地域ラベル枠の見本文字と、描かれている大仏飴を地の色で塗りつぶす。
大仏飴の部分は仮の塗りつぶしなので、きれいにするなら、正本から大仏飴だけを消した画像（ペイズリー模様と敷物は残す）を
画像編集で作り、`--base その画像` で作り直す。

### 大仏飴パーツ
```bat
python -m pipeline.images shared-request
python -m pipeline.images shared-check
```
`assets/shared/daibutsuame/REQUEST.md` に作るファイルの一覧（`config/character_motion.yaml` のパーツと状態）と仕様がある。
すべて正本と同じ大きさ・位置の透明PNG。Owner が確認して `approval.yaml` の `approved` を `true` にするまで動画に使わない。
