# ローカル（Windows + VS Code）での作業

## 1. ファイルを置く
どちらか一方でよい。
- **Git（おすすめ）**：`git clone https://github.com/bookriverjp/indo.git` → `git checkout claude/charming-keller-1kjs6q`
- **zip**：Claude から受け取った `indo_local_*.zip` を展開する（ナレーション音声など Git に入らない成果物も入っている）

既存の `E:\daibutsuame_india_folklore_automation_v1` は古い版なので、別フォルダに展開して置き換える。

## 2. Python（3.11 以上）
VS Code のターミナル（PowerShell）で、プロジェクトのフォルダから：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest -q          # すべて passed になれば準備完了
```

ffmpeg は `imageio-ffmpeg` に同梱されているので別途入れなくてよい。

## 3. VOICEVOX（ナレーションを作り直すときだけ）
- VOICEVOX（アプリ版）を起動しておけば `http://localhost:50021` で使える（Docker は不要）。
- 台本を直したら `python -m pipeline.tts EP0001_nishi_daak`。変わったブロックだけ作り直す。

## 4. 物語用の画像
- 生成した画像を `episodes/<id>/assets/inbox/<asset_id>.png` に置く（ファイル名は `storyboard/asset_manifest.md`）。
- `python -m pipeline.images check <id>` → 通ったものが `assets/generated/` に入る。
- 画像は Git に入らない（`.gitignore`）。大きなファイルをアップロードする必要はない。

## 5. 動画を作る
```powershell
python -m pipeline.timeline EP0001_nishi_daak
python -m pipeline.render EP0001_nishi_daak --preview --draft   # 下書き（半分の大きさ）
python -m pipeline.thumbnail EP0001_nishi_daak
python -m pipeline.qa serve EP0001_nishi_daak                   # 確認画面 http://127.0.0.1:8765/
python -m pipeline.render EP0001_nishi_daak                     # 本番（最終関門の前に）
```
大仏飴パーツが未承認のあいだは `--draft` が必要（画面に「下書き」と出る）。

## 6. API を使わない生成（manual モード）
台本・絵コンテ・概要欄は VS Code の Claude Code で `/generate-stage` を使うか、
`python -m pipeline.generate <stage> <id>` が書き出す依頼文を Claude に渡し、返ってきた JSON を
`--response <file>` で取り込む。詳しくは `docs/LLM.md`。

## 注意
- `.env`（API キー）は Git に入れない。
- ベンガル文字などの字形は Pillow の raqm を使う。Windows で字形が崩れる場合は `fribidi` の DLL が必要（`python -c "from PIL import features; print(features.check('raqm'))"` で確認）。
