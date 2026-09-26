# 台本・絵コンテの生成（PHASE 2）

## 2つのモード
`config/llm.yaml` の `llm.provider` で選ぶ。標準は `manual`。

| モード | APIキー | 使い方 |
|---|---|---|
| `manual` | 不要 | 依頼ファイルを書き出し、VS Code の Claude Code などで JSON を作って取り込む |
| `claude` | `.env` の `ANTHROPIC_API_KEY` | Anthropic API（`claude-opus-5`）を直接呼ぶ |

どちらのモードでも、保存する前に同じ検証を通す。
- schema（`schemas/script.schema.json` / `schemas/storyboard.schema.json`）
- 台本：伝承（legend）ブロックには research の出典 id が必要。存在しない出典 id は不可。居眠り・砂浴び・ポップコーンジャンプは1本に1回まで、毛づくろいは2回まで
- 絵コンテ：台本の全ブロックがちょうど1回ずつどれかの scene に入っている

## manual（VS Code + Claude Code、API不要）
```bat
python -m pipeline.generate script EP0001_nishi_daak
```
`episodes/EP0001_nishi_daak/script/script_request.md` ができる。
Claude Code で `/generate-stage script EP0001_nishi_daak` を実行すると、依頼ファイルを読んで JSON を作り、取り込みと修正まで進める。
手作業で取り込む場合は次のとおり。
```bat
python -m pipeline.generate script EP0001_nishi_daak --response episodes/EP0001_nishi_daak/script/script_response.json
```
絵コンテも同じ手順で `storyboard` を指定する（台本の取り込みが先）。

## claude（Anthropic API）
```bat
python -m pipeline.generate script EP0001_nishi_daak --provider claude
```
- モデル `claude-opus-5`、adaptive thinking、effort `high`、JSON schema による構造化出力、ストリーミング受信
- 安全分類器で断られたときはサーバー側で推奨モデルへ切り替える（`fallbacks: "default"`）。不要なら `null`
- 429 / 5xx / 接続エラーは SDK が再試行。検証に通らなかった出力は理由を添えて `validation_retries` 回まで作り直す
- トークン数と費用の目安は `logs/llm_usage.jsonl` に記録する

## 既存の出力
出力がすでにあるときは上書きしない。作り直すときは `--force` を付ける。
