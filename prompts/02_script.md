# Main script prompt

入力の research.json だけを情報の正本として、大仏飴が語る8〜12分の日本語YouTube台本を作る。
ナレーションは VOICEVOX（中国うさぎ、1.05倍）で読み上げる。1分あたり約300字を目安にする。

構成（section）:
1. hook: 15秒以内のフック。異変や疑問を先に見せる
2. intro: 大仏飴の挨拶
3. background: 地域・言語・背景の短い紹介
4. story: 物語
5. commentary: 異説・民俗的背景
6. comparison: 日本との比較。research に根拠がある場合だけ。なければこの section を作らない
7. ending: 締めと出典への言及

ブロックの種類（kind）:
- legend: research で確認できる伝承内容。source_ids に根拠の出典 id を必ず入れる
- staging: 演出上の補助描写（情景・雰囲気）。事実や伝承の中身を足さない
- comment: 大仏飴のコメント

重要:
- research.json にない内容を legend として書かない。
- uncertain_points にある点は断定しない。
- 大仏飴は穏やかで、怖さを煽りすぎない。
- expression には、そのブロックで大仏飴が見せる表情・動作を schema の選択肢から選ぶ。
  sleep・dust_bath・popcorn は1本に1回まで。
- block_id は b01 から順に振る。
