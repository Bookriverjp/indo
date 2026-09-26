# 大仏飴のインド異聞 — 紙芝居YouTube全自動化プロジェクト v1

チンチラの語り部「大仏飴」が、日本では十分に知られていないインド各地の民話・伝説・怪異・言い伝えを紹介するYouTubeチャンネルを、できる限り自動制作するための設計・実装スターターパックです。

## 目標
題材候補 → リサーチ → 出典整理 → 台本 → 絵コンテ → インド細密画風パーツ → 音声 → 紙芝居動画 → 字幕 → サムネイル → YouTubeメタデータまでを1本のパイプラインにします。

## 大原則
- 最初から完全無人公開にはしない。
- 「自動生成 → Research Gate → Final Gate → Owner公開承認」を基本にする。
- 民話・伝説・怪異を史実のように断定しない。
- 地域・言語・異説・出典を記録する。
- 本編ビジュアルはインド細密画を基調とする。
- 語り部は大仏飴。
- 紙芝居方式で背景・人物・前景・小物・FXを可能な限り分離する。
- 激しいAI動画化ではなく、パン・ズーム・パララックス・微小モーション中心。
- UTF-8 / LF。秘密情報やAPIキーをリポジトリへ保存しない。

## 大仏飴の参考画像
`assets/reference/daibutsuame_reference.jpeg`

ユーザー提供の基準画像をそのまま同梱しています。キャラクター継続性の正本として扱ってください。

## 最初に読む順番
1. `docs/SPEC.md`
2. `docs/STYLE_GUIDE.md`
3. `docs/RESEARCH_POLICY.md`
4. `docs/AUTOMATION_FLOW.md`
5. `docs/PHASE.md`
6. `AGENTS.md`
7. `CLAUDE.md`
8. `HANDOFF.md`

## 開発開始
最初に `START_PROMPT_FOR_CLAUDE.md` または `START_PROMPT_FOR_CODEX.md` を開き、AIコーディングエージェントへ渡してください。

## セットアップ（Windows）
```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest
python -m pipeline.main EP0001_nishi_daak --dry-run
```

## v1の位置づけ
これは「仕様・工程・プロンプト・データ契約・実装雛形」のスターターパックです。
APIキーを設定しただけで全機能が完成するものではありません。`docs/PHASE.md` に従って、1 PHASEずつTDDで実装します。
