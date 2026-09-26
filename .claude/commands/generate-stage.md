---
description: APIを使わずに台本・絵コンテを生成する（manual モード）
argument-hint: <script|storyboard> <episode_id>
---

大仏飴のインド異聞の $1 を、エピソード $2 について API を使わずに生成する。

1. `python -m pipeline.generate $1 $2 --provider manual` を実行し、書き出された依頼ファイル（`*_request.md`）を読む。
2. 依頼ファイルの System・指示・入力に従い、「出力 schema」に合う JSON を1つ作って、依頼ファイルに書かれた `*_response.json` に保存する。
   - 入力にない内容を legend（伝承）として書かない。根拠の出典 id を必ず付ける。
3. `python -m pipeline.generate $1 $2 --response <保存したファイル>` を実行する。
4. エラーが出たら内容を直して保存し直し、通るまで 3 を繰り返す。
5. 通ったら、保存先と、Owner に確認してほしい点（断定表現、異説の扱い、表情の選び方）を短く報告する。
