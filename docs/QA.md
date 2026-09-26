# 確認の関門（PHASE 10）

1話ごとに5つの関門を順に通す。各関門は自動チェックのあと、Owner が承認か差し戻しを決める。

| 順 | 関門 | 自動チェック | 見るもの |
|---|---|---|---|
| 1 | リサーチ | research の信頼度QA（FAILならNG） | research_review.md |
| 2 | 台本・絵コンテ | 台本の自動チェック（断定表現・一人称・構成）、ショート | script_main.md、script_review.md |
| 3 | 画像 | 素材画像がそろっている、大仏飴パーツが承認済み | 素材画像の一覧 |
| 4 | 音声 | 台本の全ブロックに音声がある | ブロックごとに再生 |
| 5 | 最終 | 動画・字幕・サムネイル・文面がそろう、動画の長さがタイムラインと合う、概要欄に出典・クレジットがない | 動画、サムネイル、文面 |

- 前の関門が承認されるまで、次の関門は承認できない
- 承認のあとで対象の中身が変わると「再確認」に戻る（承認時の中身の指紋と比べる）
- 差し戻しには理由が必要
- 記録は `output/qa_gates.yaml`、まとめは `output/qa_report.md`
- 「台本・絵コンテ」は仕様の4関門（リサーチ・画像・音声・最終）に加えた。画像や音声を作る前に台本を確かめるため

## 使い方
```bat
python -m pipeline.qa serve EP0001_nishi_daak      :: ブラウザで http://127.0.0.1:8765/ を開く（自分のパソコンだけ）
python -m pipeline.qa status EP0001_nishi_daak
python -m pipeline.qa approve EP0001_nishi_daak research --note "出典OK"
python -m pipeline.qa reject EP0001_nishi_daak script --note "異説の扱いを直す"
```
確認画面では、レビューの文章、素材画像、音声、動画をその場で確認して、承認・差し戻しのボタンを押せる。
