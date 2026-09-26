# ナレーション音声（PHASE 6）

```bat
python -m pipeline.tts EP0001_nishi_daak
```
VOICEVOX（`config/voice.yaml` の `endpoint`、標準は `http://localhost:50021`）を起動しておく。APIキーは不要。
ローカルでは VOICEVOX アプリを起動すればエンジンも動く。

## 読み上げのしかた
- 話者は中国うさぎ、速さ 1.05 倍
- 物語（legend / staging）はふつうの抑揚、大仏飴のコメント（comment）は栃木弁らしく平坦＋尻上がり（`prosody`）
- 声色は大仏飴の表情で切り替える（`expression_to_style`。驚く→おどろき、怖がる・ひそひそ→こわがり、居眠り→へろへろ）
- 本編は1ブロックずつ、ショートはブロックと本編への導線（cta）を1つずつ WAV にする

## 読み方の辞書
- 全話共通: `config/pronunciation.yaml`
- 1話だけ: `episodes/<id>/script/pronunciation.yaml`（同じ形式。同じ表記はこちらが優先）

字幕は元の表記のまま、音声だけ reading で読む。長い表記から先に置き換える。

## 出力
- `audio/generated/main_b01.wav`、`audio/generated/shorts_sb01.wav`、`audio/generated/shorts_cta.wav` …
- `audio/narration.json`: ブロックごとの表記・読み・声色・抑揚・秒数。次の工程（タイムライン）が使う

内容（読み・声色・抑揚・速さ）が変わったブロックだけ作り直す。全部作り直すときは `--force`。
