import json
import shutil
from pathlib import Path

import pytest

from pipeline.config import load_yaml
from pipeline.schema_validation import validate
from pipeline.timeline import TimelineError, build_timeline, main, render_srt, split_subtitle

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
CFG = load_yaml("config/timeline.yaml")["timeline"]


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def manifest():
    from pipeline.assets import build_manifest
    return build_manifest(episode_id="EP0001_sample", storyboard=load("storyboard_rich.json"),
                          script=load("script_valid.json"), research=load("research_valid.json"),
                          layout=load_yaml("config/layout.yaml"), visual=load_yaml("config/visual_style.yaml"),
                          persona=load_yaml("config/persona.yaml")["persona"], project_root=REPO)


SECONDS = {"b01": 2.0, "b02": 8.0, "b03": 6.0, "b04": 2.0, "b05": 5.0, "b06": 7.0}


def narration(seconds=SECONDS):
    return {"items": [{"target": "main", "block_id": b, "file": f"audio/generated/main_{b}.wav", "seconds": s,
                       "text": "", "kind": "legend"} for b, s in seconds.items()]}


def build(**over):
    kw = dict(episode_id="EP0001_sample", storyboard=load("storyboard_rich.json"), manifest=manifest(),
              narration=narration(), script=load("script_valid.json"), research=load("research_valid.json"), cfg=CFG,
              sfx_cfg=None)
    kw.update(over)
    return build_timeline(**kw)


@pytest.fixture
def tl():
    return build()


def test_matches_schema(tl):
    validate(tl, "timeline")


def test_scene_durations_follow_narration(tl):
    s = {x["scene_id"]: x for x in tl["scenes"]}
    lead, gap, tail = CFG["scene_lead_in"], CFG["block_gap"], CFG["scene_tail"]
    assert s["s01"]["duration"] == pytest.approx(lead + 2.0 + tail)
    assert s["s02"]["duration"] == pytest.approx(lead + 8.0 + gap + 6.0 + tail)
    assert s["s04"]["duration"] == pytest.approx(lead + 5.0 + gap + 7.0 + tail)
    starts = [x["start"] for x in tl["scenes"]]
    ends = [x["start"] + x["duration"] for x in tl["scenes"]]
    assert starts[0] == 0 and starts[1:] == pytest.approx(ends[:-1])
    assert tl["total_seconds"] == pytest.approx(ends[-1])


def test_min_scene_seconds():
    tl = build(narration=narration(dict(SECONDS, b01=0.5)))
    assert tl["scenes"][0]["duration"] == pytest.approx(CFG["min_scene_seconds"])


def test_audio_is_placed_in_order_inside_scenes(tl):
    a = {x["block_id"]: x for x in tl["audio"]}
    s02 = next(x for x in tl["scenes"] if x["scene_id"] == "s02")
    assert a["b02"]["start"] == pytest.approx(s02["start"] + CFG["scene_lead_in"])
    assert a["b03"]["start"] == pytest.approx(a["b02"]["start"] + 8.0 + CFG["block_gap"])
    assert a["b02"]["file"] == "audio/generated/main_b02.wav"


def test_transitions(tl):
    t = [x["transition_in"]["type"] for x in tl["scenes"]]
    assert t == ["fade_from_black", "crossfade", "crossfade", "card_pull"]


def test_motion_from_storyboard_and_defaults(tl):
    m = {x["scene_id"]: x["motion"] for x in tl["scenes"]}
    assert m["s01"]["name"] == "slow_push_in"
    assert m["s02"]["name"] == "static"              # card の既定
    assert m["s03"]["name"] == "slow_pan" and m["s03"]["camera_from"] == [1.1, -0.04, 0.0]
    assert m["s04"]["name"] == "slow_push_in"        # storyboard が null → stage の既定


def test_unknown_motion_falls_back_to_layout_default():
    sb = load("storyboard_rich.json")
    sb["scenes"][2]["suggested_motion"] = "spin_wildly"
    tl = build(storyboard=sb)
    assert tl["scenes"][2]["motion"]["name"] == "slow_push_in"


def test_layers_come_from_manifest(tl):
    s03 = next(x for x in tl["scenes"] if x["scene_id"] == "s03")
    assert [l["asset_id"] for l in s03["layers"]][0] == "shared_stage_template"


def test_card_contents(tl):
    s02 = next(x for x in tl["scenes"] if x["scene_id"] == "s02")
    assert s02["card"]["kind"] == "region"
    rows = dict(s02["card"]["rows"])
    assert rows["地域"].startswith("West Bengal") and rows["言語"] == "Bengali"
    assert all(x["card"] is None for x in tl["scenes"] if x["layout"] != "card")


def test_sources_card_for_ending():
    sb = load("storyboard_rich.json")
    sb["scenes"][1]["block_ids"] = ["b02", "b03"]
    sb["scenes"][3]["layout"] = "card"
    tl = build(storyboard=sb)
    card = tl["scenes"][3]["card"]
    assert card["kind"] == "sources"   # s04 は b05(commentary), b06(ending) → 最後のブロックの section
    assert any("TEST FIXTURE primary collection" in r[1] for r in card["rows"])


def test_region_label(tl):
    assert tl["region_label"] == "West Bengal (TEST FIXTURE) ・ Bengali"


def test_narrator_track(tl):
    n = {x["block_id"]: x for x in tl["narrator"]}
    assert n["b02"]["expression"] == "greet_namaste" and n["b02"]["speaking"] is True
    assert n["b02"]["duration"] == pytest.approx(8.0)


def test_missing_narration_block_raises():
    s = dict(SECONDS); del s["b04"]
    with pytest.raises(TimelineError, match="b04"):
        build(narration=narration(s))


# --- subtitles ----------------------------------------------------------------------

def test_split_subtitle_respects_limits():
    text = "むかしむかし、川のほとりの小さな村に、夜になると、どこからともなく灯りがともる、と語られています。そのお話をしましょう。"
    caps = split_subtitle(text, max_chars=21, max_lines=2)
    assert "".join("".join(c) for c in caps) == text
    for c in caps:
        assert 1 <= len(c) <= 2 and all(len(line) <= 21 for line in c)


def test_split_long_run_without_punctuation():
    caps = split_subtitle("あ" * 50, max_chars=21, max_lines=2)
    assert "".join("".join(c) for c in caps) == "あ" * 50
    assert all(len(line) <= 21 for c in caps for line in c)


def test_subtitles_cover_each_block_in_time(tl):
    for a in tl["audio"]:
        subs = [s for s in tl["subtitles"] if s["block_id"] == a["block_id"]]
        assert subs[0]["start"] == pytest.approx(a["start"])
        assert subs[-1]["end"] == pytest.approx(a["start"] + a["duration"])
        for x, y in zip(subs, subs[1:]):
            assert x["end"] == pytest.approx(y["start"])
    assert [s["index"] for s in tl["subtitles"]] == list(range(1, len(tl["subtitles"]) + 1))


def test_render_srt():
    srt = render_srt([{"index": 1, "block_id": "b01", "start": 0.4, "end": 62.05, "lines": ["一行目", "二行目"]}])
    assert srt == "1\n00:00:00,400 --> 00:01:02,050\n一行目\n二行目\n\n"


# --- CLI --------------------------------------------------------------------------

@pytest.fixture
def root(project_root: Path) -> Path:
    shutil.copytree(REPO / "prompts", project_root / "prompts")
    ep = project_root / "episodes" / "EP0001_sample"
    for sub, name, src in [("research", "research.json", "research_valid.json"),
                           ("script", "script_main.json", "script_valid.json"),
                           ("storyboard", "storyboard.json", "storyboard_rich.json")]:
        (ep / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, ep / sub / name)
    from pipeline.assets import main as assets_main
    assert assets_main(["EP0001_sample"], project_root=project_root) == 0
    (ep / "audio").mkdir(exist_ok=True)
    (ep / "audio" / "narration.json").write_text(json.dumps(narration(), ensure_ascii=False), encoding="utf-8")
    return project_root


def test_cli_writes_timeline_and_srt(root, capsys):
    assert main(["EP0001_sample"], project_root=root) == 0
    ep = root / "episodes" / "EP0001_sample"
    validate(json.loads((ep / "render" / "timeline.json").read_text(encoding="utf-8")), "timeline", root)
    srt = (ep / "script" / "subtitles.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,400 --> ")
    assert "合計" in capsys.readouterr().out


def test_cli_missing_narration(root, capsys):
    (root / "episodes" / "EP0001_sample" / "audio" / "narration.json").unlink()
    assert main(["EP0001_sample"], project_root=root) == 2
    assert "narration.json" in capsys.readouterr().err


# --- voices, sources card, transitions, sfx (第1話で追加) ---------------------------

def test_character_voice_does_not_move_narrator_mouth():
    nar = narration()
    nar["items"][3]["voice"] = "woman"          # b04
    tl = build(narration=nar)
    n = {x["block_id"]: x for x in tl["narrator"]}
    assert n["b04"]["speaking"] is False and n["b03"]["speaking"] is True


def test_sources_card_uses_script_selection():
    sb = load("storyboard_rich.json")
    sb["scenes"][3]["layout"] = "card"
    script = load("script_valid.json")
    script["sources_card"] = ["s02"]
    tl = build(storyboard=sb, script=script)
    rows = tl["scenes"][3]["card"]["rows"]
    assert len(rows) == 1 and "s02" in rows[0][0]


def test_sources_card_defaults_to_sources_used_in_legend_blocks():
    sb = load("storyboard_rich.json")
    sb["scenes"][3]["layout"] = "card"
    tl = build(storyboard=sb)
    ids = [r[0].split("（")[0] for r in tl["scenes"][3]["card"]["rows"]]
    assert ids == ["s01", "s02"]


def test_transition_override_from_storyboard():
    sb = load("storyboard_rich.json")
    sb["scenes"][1]["transition"] = "fade_from_black"
    tl = build(storyboard=sb)
    assert tl["scenes"][1]["transition_in"]["type"] == "fade_from_black"


def test_ambience_and_sfx_events():
    sfx_cfg = load_yaml("config/sfx.yaml")["sfx"]
    sb = load("storyboard_rich.json")
    sb["scenes"][0]["ambience"] = ["night_insects"]
    sb["scenes"][1]["ambience"] = ["night_insects"]
    sb["scenes"][3]["sfx"] = [{"name": "bell", "at": "end"}]
    tl = build(storyboard=sb, sfx_cfg=sfx_cfg)
    s = tl["scenes"]
    amb = [e for e in tl["sfx"] if e["name"] == "night_insects"]
    assert len(amb) == 1                                   # 続く場面の同じ環境音はつなげる
    assert amb[0]["start"] == 0 and amb[0]["duration"] == pytest.approx(s[1]["start"] + s[1]["duration"])
    assert amb[0]["loop"] is True and amb[0]["volume"] == sfx_cfg["library"]["night_insects"]["volume"]
    bell = next(e for e in tl["sfx"] if e["name"] == "bell")
    end = s[3]["start"] + s[3]["duration"]
    assert s[3]["start"] <= bell["start"] < end and bell["loop"] is False


def test_unknown_sfx_raises():
    sb = load("storyboard_rich.json")
    sb["scenes"][0]["sfx"] = [{"name": "thunder", "at": "start"}]
    with pytest.raises(TimelineError, match="thunder"):
        build(storyboard=sb, sfx_cfg=load_yaml("config/sfx.yaml")["sfx"])


def test_split_long_clause_breaks_after_particle_not_mid_word():
    text = "インドの東のほうからバングラデシュまで広がってる、ベンガル地方の話なんだ。"
    caps = split_subtitle(text, max_chars=21, max_lines=2)
    lines = [line for c in caps for line in c]
    assert "".join(lines) == text
    assert lines[0] == "インドの東のほうからバングラデシュまで"
    assert lines[1].startswith("広がってる、")


def test_split_long_clause_breaks_after_closing_quote():
    text = "「夜は危ねえよ」「知らねえもんについてっちゃだめだよ」って教えてたんだ。"
    lines = [line for c in split_subtitle(text, max_chars=21, max_lines=2) for line in c]
    assert lines[0] == "「夜は危ねえよ」"
