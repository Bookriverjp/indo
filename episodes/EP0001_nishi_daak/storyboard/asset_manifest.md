# 素材一覧: EP0001_nishi_daak

## この回で生成する素材（12件）

| ID | 種類 | 内容 | 透過 | 使う scene |
|---|---|---|---|---|
| bg_s01_v01 | 背景 | 夜の川と月、ベンガルの小さな村（家々の灯りが消えていく） |  | s01, s19 |
| bg_s03_v01 | 背景 | 竹林と村はずれの夜の家 |  | s03, s04 |
| bg_s05_v01 | 背景 | 雨季のあとの川沿いの家（夜） |  | s05 |
| bg_s06_v01 | 背景 | 眠る少年アニク（室内・夜・窓の外に大きな木） |  | s06 |
| bg_s07_v01 | 背景 | 窓の外の闇と大きな木 |  | s07, s17 |
| bg_s08_v01 | 背景 | 霧の立つ暗い川辺（誰もいない） |  | s08 |
| bg_s09_v01 | 背景 | ランプの灯りと祖母の思い出 |  | s09 |
| bg_s10_v01 | 背景 | 閉ざされた木の扉と、その向こうの闇 |  | s10 |
| bg_s11_v01 | 背景 | 夜明けの川辺の村 |  | s11, s12 |
| bg_s13_v01 | 背景 | 夜道を歩く人と、闇からの呼び声 |  | s13, s14 |
| bg_s15_v01 | 背景 | 昔の村の暗い夜道（川・池・森・ぬかるみ） |  | s15, s16 |
| bg_s18_v01 | 背景 | 祖母が子どもたちに昔話を語る夜（ランプの灯り） |  | s18 |

## 共通素材（2件、生成しない）

- shared_stage_template: 紙芝居舞台テンプレート（assets/shared/stage_template.png）
- shared_daibutsuame: 大仏飴（パーツ一式）（assets/shared/daibutsuame/）

## scene ごとのレイヤー

- s01（fullbleed, 29.2秒）: bg_s01_v01
- s02（card, 30.4秒）: shared_stage_template → shared_daibutsuame
- s03（stage, 40.6秒）: shared_stage_template → bg_s03_v01 → shared_daibutsuame
- s04（stage, 22.0秒）: shared_stage_template → bg_s03_v01 → shared_daibutsuame
- s05（stage, 12.4秒）: shared_stage_template → bg_s05_v01 → shared_daibutsuame
- s06（stage, 10.2秒）: shared_stage_template → bg_s06_v01 → shared_daibutsuame
- s07（stage, 17.2秒）: shared_stage_template → bg_s07_v01 → shared_daibutsuame
- s08（fullbleed, 8.4秒）: bg_s08_v01 → shared_daibutsuame
- s09（stage, 21.8秒）: shared_stage_template → bg_s09_v01 → shared_daibutsuame
- s10（fullbleed, 14.0秒）: bg_s10_v01 → shared_daibutsuame
- s11（stage, 6.0秒）: shared_stage_template → bg_s11_v01 → shared_daibutsuame
- s12（stage, 16.0秒）: shared_stage_template → bg_s11_v01 → shared_daibutsuame
- s13（stage, 34.4秒）: shared_stage_template → bg_s13_v01 → shared_daibutsuame
- s14（stage, 31.6秒）: shared_stage_template → bg_s13_v01 → shared_daibutsuame
- s15（stage, 20.2秒）: shared_stage_template → bg_s15_v01 → shared_daibutsuame
- s16（stage, 27.0秒）: shared_stage_template → bg_s15_v01 → shared_daibutsuame
- s17（stage, 30.4秒）: shared_stage_template → bg_s07_v01 → shared_daibutsuame
- s18（stage, 30.0秒）: shared_stage_template → bg_s18_v01 → shared_daibutsuame
- s19（fullbleed, 14.0秒）: bg_s01_v01 → shared_daibutsuame
- s20（card, 19.8秒）: shared_stage_template → shared_daibutsuame
