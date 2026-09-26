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
ルールは `config/script_rules.yaml`、大仏飴の口調は `config/persona.yaml`（一人称「おら」、物語はです・ます調、コメントは栃木弁）。どちらも Owner が編集できる。

作り直しになる（エラー）:
- 断定・一般化の表現（「実際に起きた」「本当にあった」「インド人はみんな」「日本初」など）。「実話かどうかは分かりません」のような否定の形は対象外
- 大仏飴のコメントで決めた一人称（おら）以外を使う。伝承の登場人物のセリフは対象外
- 本編の section が足りない・順番が違う、intro で「大仏飴」と名乗っていない
- ショートが300字（60秒）を超える

警告（`script_review.md` に書き、Owner が判断）:
- 長さが8〜12分の目安から外れる、フックが長い
- 「〜と語られています」のような伝承であることを示す言い回しが1つもない
- 締めで出典・資料に触れていない
- 物語（legend）の文がです・ます調で終わっていない、大仏飴のコメントに栃木弁が入っていない
- コメントに「こわい」（栃木弁で疲れた）がある。怖い話の中では誤解されやすい

## YouTube の文面（PHASE 9）
タイムラインを作ったあとに実行すると、チャプターも自動で付く。
```bat
python -m pipeline.generate metadata EP0001_nishi_daak
```
- タイトル案3つ（100字以内）、サムネイルの文字案3つ（14字以内）、概要欄、ハッシュタグ、タグ
- 概要欄に出典・参考文献・クレジット・VOICEVOX を書いたら作り直し（出典は動画の出典カード、クレジットは動画の最後に出す。Owner決定）
- 地域名か伝承名がタイトルにも概要欄にもなければ作り直し。断定・一般化の表現も作り直し
- チャプターは場面の section から自動で作る（最初は 0:00、各10秒以上、3つ未満なら付けない）
- 出力: `output/youtube_metadata.json`（`description_full` がチャプターとハッシュタグ入りの概要欄）と、貼り付け用の `output/youtube_metadata.md`

## サムネイル（PHASE 9）
```bat
python -m pipeline.thumbnail EP0001_nishi_daak [--text "文字"]
```
1280x720。背景は最初の場面の物語の絵、左に大きな文字（サムネイルの文字案の1つ目）、右に大仏飴、左下に地域ラベル、赤と金の枠。
設定は `config/thumbnail.yaml`。2MB を超えたら JPEG も保存する。大仏飴パーツが未承認なら `--draft`、背景がなければ `--placeholders`。

## 既存の出力
出力がすでにあるときは上書きしない。作り直すときは `--force` を付ける。
