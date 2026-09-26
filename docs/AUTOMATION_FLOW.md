# 自動化フロー

## Stage 01: Theme Discovery
入力：テーマ条件
出力：候補一覧

## Stage 02: Research
入力：採用候補
出力：research.json
停止条件：根拠不足

## Stage 03: Research Gate
自動QA + Owner確認。
出典、地域、言語、異説を確認。

## Stage 04: Script
大仏飴の語りと物語本文を生成。
物語と解説を明確に分離。

## Stage 05: Storyboard
台本を8〜16カット程度へ分解。
各カットにナレーション範囲を紐付ける。

## Stage 06: Asset Manifest
各sceneを以下へ分解：
- background
- character
- foreground
- prop
- fx

## Stage 07: Image Generation
provider adapter経由。
キャラ継続性、細密画スタイル、16:9を維持。

## Stage 08: Voice
TTSでナレーション。
固有名詞辞書を利用。

## Stage 09: Subtitles
音声または台本タイミングからSRT生成。

## Stage 10: Timeline
scene duration、asset placement、pan/zoom、transitionをJSON化。

## Stage 11: Render
FFmpeg/MoviePy等で紙芝居合成。
テキストは編集段階で描画。

## Stage 12: Thumbnail & Metadata
サムネ、タイトル案、説明文、タグ、チャプター。

## Stage 13: Final QA
音声、字幕、画面破綻、出典表記を確認。

## Stage 14: Publish
Ownerが承認した場合のみYouTube APIへ渡す。
v1初期ではdisabledを標準とする。

## 再実行
各stageの成果物をディスクへ保存し、失敗したstageだけ再実行できる構成にする。
