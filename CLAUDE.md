# CLAUDE.md

このプロジェクトでは、Claudeは実装担当として動く。

## 作業前
- README、SPEC、STYLE_GUIDE、RESEARCH_POLICY、PHASE、HANDOFFを読む。
- 現在のPHASEを確認する。
- 変更計画・対象ファイル・テスト方法を先に提示する。
- Owner承認前に広範な改修を開始しない。

## 実装方針
- 既存構造を尊重し、最小差分。
- 1 PHASEずつ。
- 外部APIはprovider adapterで分離する。
- 画像生成、LLM、TTS、YouTube投稿を直接コアロジックへ埋め込まない。
- 失敗時の再実行ができるよう、各stageは成果物をファイル保存する。
- research / script / storyboard / visual / audio / render / metadata を分離する。

## 禁止
- 出典なしの伝承を事実扱いすること
- 大仏飴の外見を無断変更すること
- 公開承認を飛ばすこと
- `.env` をGitへ含めること
