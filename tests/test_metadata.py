import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from pipeline.config import load_yaml
from pipeline.generate import GenerateError, run_stage
from pipeline.metadata import chapters_from_timeline, format_chapters

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def timeline(seconds):
    from pipeline.assets import build_manifest
    from pipeline.timeline import build_timeline

    m = build_manifest(episode_id="EP0001_sample", storyboard=load("storyboard_rich.json"), script=load("script_valid.json"),
                       research=load("research_valid.json"), layout=load_yaml("config/layout.yaml"),
                       visual=load_yaml("config/visual_style.yaml"), persona=load_yaml("config/persona.yaml")["persona"],
                       project_root=REPO)
    nar = {"items": [{"target": "main", "block_id": b, "file": f"audio/generated/main_{b}.wav", "seconds": s}
                     for b, s in seconds.items()]}
    return build_timeline(episode_id="EP0001_sample", storyboard=load("storyboard_rich.json"), manifest=m, narration=nar,
                          script=load("script_valid.json"), research=load("research_valid.json"),
                          cfg=load_yaml("config/timeline.yaml")["timeline"])


LONG = {"b01": 12.0, "b02": 20.0, "b03": 30.0, "b04": 60.0, "b05": 40.0, "b06": 20.0}


# --- chapters -----------------------------------------------------------------------

def test_chapters_start_at_zero_and_follow_sections():
    ch = chapters_from_timeline(timeline(LONG), load("script_valid.json"))
    assert ch[0]["start"] == 0 and ch[0]["label"] == "はじまり"
    assert [c["label"] for c in ch] == ["はじまり", "ごあいさつ", "お話", "異説と背景"]
    assert all(b["start"] - a["start"] >= 10 for a, b in zip(ch, ch[1:]))


def test_short_video_has_no_chapters():
    ch = chapters_from_timeline(timeline({k: 1.0 for k in LONG}), load("script_valid.json"))
    assert ch == []


def test_format_chapters():
    assert format_chapters([{"start": 0, "label": "はじまり"}, {"start": 75.4, "label": "お話"},
                            {"start": 3700, "label": "おわりに"}]) == "0:00 はじまり\n1:15 お話\n1:01:40 おわりに"


# --- metadata stage -------------------------------------------------------------------

class FakeProvider:
    name, model = "fake", "fake-model"

    def __init__(self, *outs):
        self.outs = list(outs)
        self.calls = []

    def generate_json(self, *, system, user, schema, max_tokens=None):
        from pipeline.llm.base import LLMResult, LLMUsage
        self.calls.append(user)
        return LLMResult(data=self.outs.pop(0), model="m", usage=LLMUsage(1, 1), request_id=None, stop_reason="end_turn")


@pytest.fixture
def root(project_root: Path) -> Path:
    shutil.copytree(REPO / "prompts", project_root / "prompts")
    ep = project_root / "episodes" / "EP0001_sample"
    for sub, name, src in [("research", "research.json", "research_valid.json"),
                           ("script", "script_main.json", "script_valid.json")]:
        (ep / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, ep / sub / name)
    (ep / "render").mkdir()
    (ep / "render" / "timeline.json").write_text(json.dumps(timeline(LONG), ensure_ascii=False), encoding="utf-8")
    return project_root


def test_metadata_stage_adds_chapters(root):
    p = FakeProvider(load("youtube_metadata_valid.json"))
    out = run_stage(root, "EP0001_sample", "metadata", p, pricing={})
    assert out.name == "youtube_metadata.json" and out.parent.name == "output"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["description_full"].startswith(data["description"])
    assert "0:00 はじまり" in data["description_full"]
    assert "#インド" in data["description_full"]
    assert '<input name="research">' in p.calls[0] and "canonical_title" in p.calls[0]   # research も入力に入る
    md = (out.parent / "youtube_metadata.md").read_text(encoding="utf-8")
    assert "タイトル案" in md and "チャプター" in md


@pytest.mark.parametrize("mutate,word", [
    (lambda d: d.__setitem__("description", d["description"] + "\\n出典: テスト"), "出典"),
    (lambda d: d.__setitem__("description", d["description"] + "\\nVOICEVOX:中国うさぎ"), "VOICEVOX"),
    (lambda d: d["title_candidates"].__setitem__(1, "日本初公開の伝説"), "日本初"),
    (lambda d: (d.__setitem__("description", "インドの話です。"), d["title_candidates"].__setitem__(0, "不思議な話")), "地域名"),
])
def test_metadata_rules(root, mutate, word):
    bad = load("youtube_metadata_valid.json")
    mutate(bad)
    with pytest.raises(GenerateError, match=word):
        run_stage(root, "EP0001_sample", "metadata", FakeProvider(bad, bad), pricing={}, validation_retries=1)


def test_metadata_without_timeline_has_no_chapters(root):
    (root / "episodes" / "EP0001_sample" / "render" / "timeline.json").unlink()
    out = run_stage(root, "EP0001_sample", "metadata", FakeProvider(load("youtube_metadata_valid.json")), pricing={})
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["chapters"] == [] and data["description_full"].startswith(data["description"])


# --- thumbnail --------------------------------------------------------------------------

@pytest.fixture
def troot(project_root: Path) -> Path:
    shutil.copytree(REPO / "prompts", project_root / "prompts")
    shutil.copytree(REPO / "assets", project_root / "assets")
    ep = project_root / "episodes" / "EP0001_sample"
    for sub, name, src in [("research", "research.json", "research_valid.json"),
                           ("script", "script_main.json", "script_valid.json"),
                           ("storyboard", "storyboard.json", "storyboard_rich.json")]:
        (ep / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, ep / sub / name)
    from pipeline.assets import main as assets_main
    assert assets_main(["EP0001_sample"], project_root=project_root) == 0
    (ep / "output").mkdir(exist_ok=True)
    shutil.copy(FIX / "youtube_metadata_valid.json", ep / "output" / "youtube_metadata.json")
    return project_root


def test_thumbnail(troot, capsys):
    from pipeline.thumbnail import main as thumb_main

    gen = troot / "episodes" / "EP0001_sample" / "assets" / "generated"
    gen.mkdir(parents=True)
    Image.new("RGB", (1920, 1080), (20, 30, 120)).save(gen / "bg_s01_v01.png")
    assert thumb_main(["EP0001_sample", "--draft", "--placeholders"], project_root=troot) == 0
    out = troot / "episodes" / "EP0001_sample" / "output" / "thumbnail.png"
    im = Image.open(out)
    assert im.size == (1280, 720)
    assert out.stat().st_size < 2 * 1024 * 1024
    assert "夜の川の灯り" in capsys.readouterr().out


def test_thumbnail_custom_text_and_gates(troot, capsys):
    from pipeline.thumbnail import main as thumb_main

    assert thumb_main(["EP0001_sample", "--placeholders"], project_root=troot) == 2          # 大仏飴 未承認
    assert "承認" in capsys.readouterr().err
    assert thumb_main(["EP0001_sample", "--draft"], project_root=troot) == 2                 # 背景画像なし
    assert thumb_main(["EP0001_sample", "--draft", "--placeholders", "--text", "灯りの正体"], project_root=troot) == 0
    assert "灯りの正体" in capsys.readouterr().out
