# データ契約

## Episode ID
`EP0001_nishi_daak` のような形式を推奨。

## Episode directory
episodes/<episode_id>/
  research/
  script/
  storyboard/
  assets/
  audio/
  render/
  output/
  logs/

## Asset naming
- bg_s01_v01.png
- char_daibutsuame_talk_v01.png
- char_main_scared_v01.png
- prop_lamp_v01.png
- fx_fog_v01.png

## Provider-independent
LLM、image、TTS、publisherはすべてinterface経由。
コアのworkflowが特定サービスへ直接依存しないこと。
