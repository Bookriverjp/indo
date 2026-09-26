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

## ショート台本（PHASE 3）
本編の台本を取り込んだあとに作る。
```bat
python -m pipeline.generate shorts EP0001_nishi_daak
```

## 台本の自動チェック（PHASE 3）
ルールは `config/script_rules.yaml`、大仏飴の口調は `config/persona.yaml`。どちらも Owner が編集できる。

作り直しになる（エラー）:
- 断定・一般化の表現（「実際に起きた」「本当にあった」「インド人はみんな」「日本初」など）。「実話かどうかは分かりません」のような否定の形は対象外
- 大仏飴のコメントで決めた一人称（ぼく）以外を使う。伝承の登場人物のセリフは対象外
- 本編の section が足りない・順番が違う、intro で「大仏飴」と名乗っていない
- ショートが300字（60秒）を超える

警告（`script_review.md` に書き、Owner が判断）:
- 長さが8〜12分の目安から外れる、フックが長い
- 「〜と語られています」のような伝承であることを示す言い回しが1つもない
- 締めで出典・資料に触れていない

## 既存の出力
出力がすでにあるときは上書きしない。作り直すときは `--force` を付ける。
