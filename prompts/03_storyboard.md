# Storyboard prompt

入力の script_main.json を 8〜16 scene に分解する。
各 scene に、そのナレーションを構成する block_id（script の block_id）を順番どおりに入れる。
すべての block_id をどれか1つの scene に1回だけ含める。

layout（config/layout.yaml）:
- fullbleed: hook と、story の山場だけ
- stage: story の基本（紙芝居舞台）
- card: intro / background / commentary / comparison / ending

各 scene に:
- scene_id（s01 から）
- layout
- block_ids
- narration_text（block の text をつなげたもの）
- visual_summary
- location
- time_of_day
- characters
- background
- props
- foreground
- fx
- suggested_motion（slow_push_in / slow_pan / parallax / fog_drift / flame_flicker / rain / cloud_drift など）
- estimated_seconds（1.05倍の読み上げで1秒あたり約5字）

同じ人物・小物・背景は全 scene で同じ表記にする（素材を使い回すため）。語り部の大仏飴は characters に入れない。
紙芝居なので1 scene へ要素を詰め込みすぎない。画像内に文字を描かせる指示を書かない。
