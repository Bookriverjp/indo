# bgloop_kit：1枚の絵から、継ぎ目のない背景ループ動画を作る

1枚の背景画から、雲が漂い・川が流れ・木と草が風に揺れ・蛍と花びらが舞う、継ぎ目のないループ動画（MP4）を作ります。
AI動画は使いません。絵を層（空・雲・陸・手前の草）に切り分け、層ごとにプログラムで動かします。

見本のシーン（夜の川辺の村）が入っています。

## 1. 準備（最初に一度だけ）
Python 3.10 以上が必要です。このフォルダで：

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
（Mac / Linux は `python3 -m venv .venv` → `source .venv/bin/activate`）

ffmpeg は `imageio-ffmpeg` に同梱のものを使うので、別に入れる必要はありません。

## 2. 見本を動かす
```bat
run_preview.bat          :: 確認用（960x540・約1分）→ output\bgloop\night_river\preview.mp4
run_full.bat             :: 本番（1920x1080・24秒・約4分）→ output\bgloop\night_river\loop.mp4
```
中身はこのコマンドです：
```bat
python -m bgloop assets/bgloop/night_river.yaml --preview
python -m bgloop assets/bgloop/night_river.yaml
```
できたフォルダの `index.html` をブラウザで開くと、ループ再生と切り抜いた層を確認できます。

## 3. 新しい絵で作る
1. 絵を `assets/bgloop/` に置く（例 `assets/bgloop/forest.png`）。16:9 がおすすめ
2. 目盛りとシーン設定のひな形を作る
   ```bat
   python -m bgloop assets/bgloop/forest.png --stage grid
   ```
   → `output/bgloop/forest/grid.png`（絵に座標の目盛りを重ねたもの）と `assets/bgloop/forest.yaml`（ひな形）
3. `grid.png` を見ながら `forest.yaml` の座標を直す（下の「シーン設定の書き方」）。`night_river.yaml` が書き方の見本
4. 切り抜きを確かめる
   ```bat
   python -m bgloop assets/bgloop/forest.yaml --stage cut
   ```
   → `output/bgloop/forest/cut/overlay.png`（空=藍・雲=白・水=水色・蓮=緑・舟=橙・手前の草=黄・灯り=赤）。
   色の付き方がおかしい所があれば 3 に戻る
5. 動きを確かめる → 本番
   ```bat
   python -m bgloop assets/bgloop/forest.yaml --stage render --preview
   python -m bgloop assets/bgloop/forest.yaml --stage render
   ```

ChatGPT に 2〜4 をやってもらうこともできます（`GPT_INSTRUCTIONS.md`）。

## シーン設定の書き方（`assets/bgloop/<name>.yaml`）
座標は **その絵の px**（`ref_size` の大きさ）。点は `[x, y]`、矩形は `[x0, y0, x1, y1]`、多角形は点の並び。
色は OpenCV の HSV（H: 0〜180、S・V: 0〜255）。

| 項目 | 何を書くか |
|---|---|
| `sky.zone` | 空がありうる範囲（多角形）。地平線より少し下まで |
| `sky.hue` | 空の色相。夜の藍は `[98, 118]`、夕焼けなら `[0, 30]` など |
| `sky.sure_sky` / `sure_land` | 必ず空の所・必ず空でない所（矩形・幹の線 `lines: [[x0,y0,x1,y1,太さ]]`・円 `circles`） |
| `sky.grabcut` | 空と色が近い遠くの木立などの矩形。そこだけ色の統計で分ける |
| `sky.moon` | 月のだいたいの中心（あれば） |
| `water.zone` | 水面の範囲（多角形）。岸の線に沿わせる |
| `water.lotus` / `boat` / `jetty` | 蓮の花 `[x, y, 半径]`・舟の矩形（上下に揺れる）・桟橋の矩形（揺らさない） |
| `foreground` | 手前の草の範囲（多角形）。この中の「水の色でない所」が揺れる層になる |
| `lights.spots` | 窓・灯籠 `[x, y, 半径]`。明るく ゆらぐ |
| `depth` | 奥行き（0=空の遠さ、1=手前の草）。`ground` は y ごとの奥行き、`regions` は多角形ごとの上書き |
| `motion.sway` | 揺れる木。ヤシは `base`（根元）と `top`（葉の付け根）と `radius`（葉の半径）。ほかの木は `poly`（範囲）と `base` |
| `motion.protect` | 揺らさない物（家・柵など）の多角形 |
| `motion.*` | 雲の漂い・川の流れの速さ・揺れの大きさなど（`night_river.yaml` の注釈を参照） |
| `fx` | 蛍・花びら・霧・前ボケの枝・光のにじみ・周辺減光。要らなければ消す |

空（`sky`）と水面（`water.zone`）は必須です。水のない絵は今のところ対応していません。

## 書き出しの設定（`config/bgloop.yaml`）
ループの長さ（標準 24 秒）・fps・大きさ・画質・並列の数。ループの長さを変えても、すべての動きがその長さで割り切れるように作られます。

## 困ったとき
- `ModuleNotFoundError` → 1 の `pip install -r requirements.txt`
- 空の切り抜きに木が混じる → `sky.zone` を狭める、`sure_land` を足す、その辺りを `grabcut` の矩形にする
- 手前の草に水が混じる → `foreground` の多角形を草に沿わせる
- 動画が重い・遅い → `--preview`、`--seconds 12`、`--workers`（CPU の数まで）
- 1コマだけ見たい → `--stage render --stills 0,360`（`stills/` に PNG）

## 中身
- `bgloop/cut.py`：切り抜き（ガイド付きフィルタで輪郭に沿わせる、隠れていた所の補完）
- `bgloop/render.py`：動き（変位場・流れ・揺れ・効果・パララックス）
- `bgloop/motion.py` / `matte.py` / `scene.py`：部品
- `bgloop/video.py`：MP4 の書き出し（ffmpeg がなければ OpenCV で書き出す）
- `bgloop/__main__.py`：コマンド
