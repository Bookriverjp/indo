# Asset manifest prompt

storyboard.jsonを読み、再利用可能な素材とscene固有素材を分離する。

特に：
- 大仏飴は共通ポーズを優先再利用
- 背景とキャラクターを分離
- 小物・前景・霧・雨・炎を別パーツ化
- 透明背景が適切なものにはtransparent=true
- 画像内に日本語テキストを生成しない
