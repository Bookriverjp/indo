# Fonts

動画の字幕・地域ラベル・解説カードに使うフォント。どちらも SIL Open Font License 1.1（同梱・再配布可）。入手元は Google Fonts。

| ファイル | 用途 | ライセンス |
|---|---|---|
| `ZenMaruGothic-Bold.ttf` | 字幕・地域ラベル・カード本文 | `OFL-ZenMaruGothic.txt` |
| `ShipporiMinchoB1-ExtraBold.ttf` | 解説カードの見出し | `OFL-ShipporiMinchoB1.txt` |
| `NotoSans{Bengali,Devanagari,Tamil,Telugu,Kannada,Malayalam,Gujarati,Gurmukhi,Oriya}-Bold.ttf` | 解説カードの現地名（現地の文字） | `OFL-NotoSans*.txt` |

インドの文字は字形の組み立て（シェーピング）が必要。Pillow が raqm 付きで動いていること（`python -c "from PIL import features; print(features.check('raqm'))"` が True）。
