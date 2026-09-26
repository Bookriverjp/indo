# AGENTS.md

## 目的
大仏飴のインド異聞・紙芝居YouTube自動制作システムを、仕様優先・差分最小・再現可能な工程で実装する。

## 絶対ルール
1. 仕様一致を速度より優先する。
2. 既存プロジェクトを新しい雛形へ丸ごと置換しない。
3. 未承認のUI・機能・投稿自動化を勝手に追加しない。
4. 1回に1 PHASEのみ進める。
5. 実装前に変更計画と対象ファイルを提示する。
6. TDD: Red → Green → Refactor → Debug/Release確認 → 監査 → Owner確認 → ローカルGitコミット。
7. APIキー、Cookie、OAuthトークンをコミットしない。
8. `assets/reference/daibutsuame_reference.jpeg` を大仏飴の外見正本とする。
9. 伝承内容をAIが創作して「現地伝承」として混ぜない。
10. 自動公開は最後のPHASEまで禁止。最終Owner承認を保持する。

## 正本優先順位
1. 最新Owner指示
2. `docs/SPEC.md`
3. `docs/STYLE_GUIDE.md`
4. `docs/RESEARCH_POLICY.md`
5. `docs/PHASE.md`
6. `HANDOFF.md`

## ファイル形式
- UTF-8
- LF
- Python 3.11+
- パスは相対パス優先
- Windowsでも動作すること

## Git
- ローカルGitを使用可能
- 各PHASE終了時にコミット
- reset/rebase/amendで過去承認済み履歴を書き換えない
