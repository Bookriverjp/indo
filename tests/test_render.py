import io
import json
import math
import shutil
import struct
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pipeline.config import load_yaml
from pipeline.render.audio import frame_levels, mix_narration
from pipeline.render.narrator import NarratorRig, blink_frames
from pipeline.render.__main__ import main

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
RCFG = load_yaml("config/render.yaml")["render"]


def tone(path: Path, seconds: float, rate=24000, amp=8000, silent_head=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(rate * seconds); head = int(rate * silent_head)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", 0 if i < head else int(amp * math.sin(i / 20))) for i in range(n)))


# --- audio ------------------------------------------------------------------------

def test_mix_places_blocks(tmp_path: Path) -> None:
    tone(tmp_path / "a.wav", 0.5); tone(tmp_path / "b.wav", 0.5)
    audio = [{"block_id": "a", "file": "a.wav", "start": 0.2, "duration": 0.5},
             {"block_id": "b", "file": "b.wav", "start": 1.0, "duration": 0.5}]
    samples, rate = mix_narration(audio, tmp_path, total_seconds=2.0)
    assert rate == 24000 and len(samples) == 48000
    assert np.abs(samples[: int(0.19 * rate)]).max() == 0
    assert np.abs(samples[int(0.3 * rate): int(0.6 * rate)]).max() > 1000
    assert np.abs(samples[int(0.75 * rate): int(0.95 * rate)]).max() == 0


def test_frame_levels_open_mouth_only_when_loud(tmp_path: Path) -> None:
    tone(tmp_path / "a.wav", 1.0, silent_head=0.5)
    audio = [{"block_id": "a", "file": "a.wav", "start": 0.0, "duration": 1.0}]
    samples, rate = mix_narration(audio, tmp_path, total_seconds=1.0)
    opened = frame_levels(samples, rate, fps=10, audio=audio, threshold=0.25)
    assert len(opened) == 10
    assert not any(opened[:4]) and all(opened[6:])


# --- narrator ---------------------------------------------------------------------

def test_blink_frames_deterministic_and_short() -> None:
    a = blink_frames(total_seconds=60, fps=30, cfg=RCFG["narrator"]["blink"], seed="EP0001")
    b = blink_frames(total_seconds=60, fps=30, cfg=RCFG["narrator"]["blink"], seed="EP0001")
    assert a == b and 8 <= len(a) // 4 <= 40


def test_narrator_rig_variants() -> None:
    rig = NarratorRig(REPO / "assets" / "shared" / "daibutsuame", RCFG["narrator"])
    box = (419, 534)
    open_ = rig.render(box, "full_body", t=0.0, expression="neutral", eyes_closed=False, mouth_open=True)
    closed = rig.render(box, "full_body", t=0.0, expression="neutral", eyes_closed=True, mouth_open=False)
    assert open_.size == box and open_.mode == "RGBA"
    assert np.abs(np.asarray(open_, dtype=int) - np.asarray(closed, dtype=int)).sum() > 0
    medal = rig.render((300, 340), "medallion", t=0.0, expression="neutral", eyes_closed=False, mouth_open=False)
    assert medal.size == (300, 340) and medal.getpixel((0, 0))[3] == 0 and medal.getpixel((150, 170))[3] == 255


def test_narrator_motion_moves_body() -> None:
    rig = NarratorRig(REPO / "assets" / "shared" / "daibutsuame", RCFG["narrator"])
    a = rig.render((419, 534), "full_body", t=0.1, expression="neutral", eyes_closed=False, mouth_open=False)
    b = rig.render((419, 534), "full_body", t=0.1, expression="joy", eyes_closed=False, mouth_open=False)
    assert np.abs(np.asarray(a, dtype=int) - np.asarray(b, dtype=int)).sum() > 0


# --- CLI（小さい解像度で短く書き出す） ------------------------------------------------

@pytest.fixture
def root(project_root: Path) -> Path:
    for d in ("prompts",):
        shutil.copytree(REPO / d, project_root / d)
    shutil.copytree(REPO / "assets", project_root / "assets")
    ep = project_root / "episodes" / "EP0001_sample"
    for sub, name, src in [("research", "research.json", "research_valid.json"),
                           ("script", "script_main.json", "script_valid.json"),
                           ("storyboard", "storyboard.json", "storyboard_rich.json")]:
        (ep / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, ep / sub / name)
    from pipeline.assets import main as assets_main
    assert assets_main(["EP0001_sample"], project_root=project_root) == 0
    items = []
    for b in ["b01", "b02", "b03", "b04", "b05", "b06"]:
        tone(ep / "audio" / "generated" / f"main_{b}.wav", 0.4)
        items.append({"target": "main", "block_id": b, "file": f"audio/generated/main_{b}.wav", "seconds": 0.4})
    (ep / "audio" / "narration.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    from pipeline.timeline import main as tl_main
    assert tl_main(["EP0001_sample"], project_root=project_root) == 0
    return project_root


def test_render_requires_images_or_placeholders(root: Path, capsys) -> None:
    assert main(["EP0001_sample", "--preview", "--draft"], project_root=root) == 2
    assert "bg_s01_v01" in capsys.readouterr().err


def test_render_requires_narrator_approval(root: Path, capsys) -> None:
    assert main(["EP0001_sample", "--preview", "--placeholders"], project_root=root) == 2
    assert "承認" in capsys.readouterr().err


def test_render_preview_mp4(root: Path) -> None:
    import imageio_ffmpeg

    code = main(["EP0001_sample", "--preview", "--placeholders", "--draft", "--scale", "0.25", "--fps", "10",
                 "--start", "3.0", "--duration", "2.0"], project_root=root)
    assert code == 0
    out = root / "episodes" / "EP0001_sample" / "output" / "preview.mp4"
    frames, secs = imageio_ffmpeg.count_frames_and_secs(str(out))
    assert frames == 20 and secs == pytest.approx(2.0, abs=0.15)


def test_compose_stage_frame_shows_art_inside_template(root: Path) -> None:
    from pipeline.render.__main__ import Renderer

    gen = root / "episodes" / "EP0001_sample" / "assets" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1920, 1080), (10, 200, 30)).save(gen / "bg_s01_v01.png")
    r = Renderer(root, "EP0001_sample", scale=0.5, fps=10, placeholders=True, draft=True)
    s03 = next(s for s in r.timeline["scenes"] if s["scene_id"] == "s03")
    frame = r.frame(s03["start"] + s03["duration"] - 0.05)
    art = load_yaml("config/layout.yaml")["main"]["layouts"]["stage"]["story_art"]
    # 窓の左上寄り（人物・小物のない所）は背景の緑、窓の外は舞台テンプレート
    px = frame.getpixel((int((art["x"] + 30) * 0.5), int((art["y"] + 30) * 0.5)))
    assert px[1] > 150 and px[0] < 80
    outside = frame.getpixel((int(20 * 0.5), int(540 * 0.5)))
    assert not (outside[1] > 150 and outside[0] < 80)


def test_full_body_fills_box_width_and_stands_on_bottom() -> None:
    rig = NarratorRig(REPO / "assets" / "shared" / "daibutsuame", RCFG["narrator"])
    img = rig.render((419, 534), "full_body", t=0.0, expression="neutral", eyes_closed=False, mouth_open=False)
    alpha = np.asarray(img.getchannel("A"))
    cols = np.where(alpha.max(axis=0) > 20)[0]
    rows = np.where(alpha.max(axis=1) > 20)[0]
    assert cols.max() - cols.min() > 419 * 0.9       # 余白を切り詰めて枠いっぱい
    assert rows.max() >= 534 - 12                    # 下端に立つ
    assert alpha[0, 0] == 0                          # 背景は透明


def test_credit_is_drawn_only_in_last_scene(root: Path, monkeypatch) -> None:
    from pipeline.render import __main__ as rmain

    drawn = []
    real = rmain.Renderer._draw_credit

    def spy(self, canvas):
        drawn.append(True)
        return real(self, canvas)

    monkeypatch.setattr(rmain.Renderer, "_draw_credit", spy)
    r = rmain.Renderer(root, "EP0001_sample", scale=0.5, fps=10, placeholders=True, draft=True)
    scenes = r.timeline["scenes"]
    r.frame(scenes[0]["start"] + 0.5)
    assert drawn == []
    last = scenes[-1]
    r.frame(last["start"] + last["duration"] - 0.05)
    assert drawn == [True]
    assert r.credit == "VOICEVOX:中国うさぎ"
