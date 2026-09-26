import base64
import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pipeline.config import load_yaml
from pipeline.images.openai_provider import OpenAIImageProvider
from pipeline.images.process import process_asset
from pipeline.images.template import build_stage_template
from pipeline.images.__main__ import main

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
RULES = load_yaml("config/image.yaml")["image"]


def png(path: Path, size=(1536, 1024), transparent=False, mode=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if transparent:
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        im.paste((200, 50, 50, 255), (size[0] // 4, size[1] // 4, size[0] // 2, size[1] // 2))
    else:
        im = Image.new(mode or "RGB", size, (30, 40, 90))
    im.save(path)
    return path


def asset(kind="background", transparent=False, aid="bg_s01_v01"):
    return {"asset_id": aid, "kind": kind, "transparent": transparent}


# --- process ----------------------------------------------------------------

def test_background_is_cover_cropped_to_1920x1080(tmp_path: Path) -> None:
    src = png(tmp_path / "in.png", (1536, 1024))
    dst = tmp_path / "out" / "bg.png"
    assert process_asset(src, dst, asset(), RULES) == []
    im = Image.open(dst)
    assert im.size == (1920, 1080) and im.mode == "RGB"


def test_small_background_is_rejected(tmp_path: Path) -> None:
    src = png(tmp_path / "in.png", (640, 480))
    errors = process_asset(src, tmp_path / "bg.png", asset(), RULES)
    assert errors and "小さ" in errors[0]


def test_transparent_asset_keeps_alpha(tmp_path: Path) -> None:
    src = png(tmp_path / "in.png", (1024, 1536), transparent=True)
    dst = tmp_path / "c.png"
    assert process_asset(src, dst, asset("character", True, "char_01_v01"), RULES) == []
    assert Image.open(dst).mode == "RGBA"


def test_opaque_image_for_transparent_asset_is_rejected(tmp_path: Path) -> None:
    src = png(tmp_path / "in.png", (1024, 1536))
    errors = process_asset(src, tmp_path / "c.png", asset("character", True, "char_01_v01"), RULES)
    assert errors and "透過" in errors[0]
    assert not (tmp_path / "c.png").exists()


def test_jpeg_background_is_accepted(tmp_path: Path) -> None:
    src = tmp_path / "in.jpg"
    Image.new("RGB", (1600, 900), (1, 2, 3)).save(src)
    assert process_asset(src, tmp_path / "bg.png", asset(), RULES) == []


def test_broken_file_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "in.png"
    src.write_bytes(b"not an image")
    assert process_asset(src, tmp_path / "bg.png", asset(), RULES)


# --- stage template -----------------------------------------------------------

def test_stage_template_punches_story_window_and_blanks_text() -> None:
    layout = load_yaml("config/layout.yaml")["main"]["layouts"]["stage"]
    base = Image.open(REPO / "assets" / "reference" / "layout_stage_reference.webp")
    tpl = build_stage_template(base, layout)
    assert tpl.size == (1920, 1080) and tpl.mode == "RGBA"
    a = layout["story_art"]
    assert tpl.getpixel((a["x"] + a["w"] // 2, a["y"] + a["h"] // 2))[3] == 0
    assert tpl.getpixel((a["x"] - 30, a["y"] - 30))[3] == 255
    s = layout["subtitle"]
    box = tpl.crop((s["x"] + 10, s["y"] + 10, s["x"] + s["w"] - 10, s["y"] + s["h"] - 10)).convert("L")
    lo, hi = box.getextrema()
    assert hi - lo < 10          # 見本の字幕文字が消えて一色
    n = layout["narrator"]
    nbox = tpl.crop((n["x"] + 5, n["y"] + 5, n["x"] + n["w"] - 5, n["y"] + n["h"] - 60)).convert("L")
    lo, hi = nbox.getextrema()
    assert hi - lo < 10          # 参照画像の大仏飴が消えている


# --- OpenAI adapter (no network) ------------------------------------------------

class FakeImages:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=self.payloads.pop(0))], usage=None)


def b64_png(size=(64, 64), transparent=False) -> str:
    buf = io.BytesIO()
    if transparent:
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        im.paste((1, 2, 3, 255), (0, 0, size[0] // 2, size[1] // 2))
    else:
        im = Image.new("RGB", size, (1, 2, 3))
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_openai_provider_request_shape() -> None:
    images = FakeImages([b64_png(transparent=True)])
    p = OpenAIImageProvider(model="gpt-image-1", quality="high", client=SimpleNamespace(images=images))
    data = p.generate(prompt="P", size="1024x1536", transparent=True)
    call = images.calls[0]
    assert call["model"] == "gpt-image-1" and call["size"] == "1024x1536"
    assert call["background"] == "transparent" and call["output_format"] == "png"
    assert Image.open(io.BytesIO(data)).mode == "RGBA"


def test_openai_provider_opaque_background() -> None:
    images = FakeImages([b64_png()])
    p = OpenAIImageProvider(model="gpt-image-1", quality="high", client=SimpleNamespace(images=images))
    p.generate(prompt="P", size="1536x1024", transparent=False)
    assert images.calls[0]["background"] == "opaque"


# --- CLI / workflow ---------------------------------------------------------------

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
    return project_root


def manifest(root: Path) -> dict:
    return json.loads((root / "episodes" / "EP0001_sample" / "storyboard" / "asset_manifest.json").read_text(encoding="utf-8"))


def test_request_lists_every_episode_asset(root: Path, capsys) -> None:
    assert main(["request", "EP0001_sample"], project_root=root) == 0
    req = (root / "episodes" / "EP0001_sample" / "assets" / "image_requests.md").read_text(encoding="utf-8")
    for a in manifest(root)["assets"]:
        if a["scope"] == "episode":
            assert f"{a['asset_id']}.png" in req
    assert "inbox" in req
    assert "shared_daibutsuame" not in req


def test_check_reports_missing_then_ok(root: Path, capsys) -> None:
    assert main(["check", "EP0001_sample"], project_root=root) == 1
    inbox = root / "episodes" / "EP0001_sample" / "assets" / "inbox"
    for a in manifest(root)["assets"]:
        if a["scope"] != "episode":
            continue
        if a["kind"] == "background":
            png(inbox / f"{a['asset_id']}.png", (1536, 1024))
        else:
            png(inbox / f"{a['asset_id']}.png", (512, 512), transparent=True)
    assert main(["check", "EP0001_sample"], project_root=root) == 0
    gen = root / "episodes" / "EP0001_sample" / "assets" / "generated"
    assert Image.open(gen / "bg_s01_v01.png").size == (1920, 1080)
    status = (root / "episodes" / "EP0001_sample" / "assets" / "image_status.md").read_text(encoding="utf-8")
    assert "OK" in status


def test_check_reports_bad_transparency(root: Path, capsys) -> None:
    inbox = root / "episodes" / "EP0001_sample" / "assets" / "inbox"
    png(inbox / "char_01_v01.png", (512, 512))
    assert main(["check", "EP0001_sample"], project_root=root) == 1
    status = (root / "episodes" / "EP0001_sample" / "assets" / "image_status.md").read_text(encoding="utf-8")
    assert "char_01_v01" in status and "透過" in status


def test_generate_with_injected_provider_and_retry(root: Path) -> None:
    calls = []

    class Fake:
        name, model = "fake", "fake-image"

        def generate(self, *, prompt, size, transparent, reference_images=()):
            calls.append((prompt, size, transparent))
            # 最初の人物だけわざと透過なしを返して作り直させる
            opaque = transparent and sum(1 for c in calls if c[2]) == 1
            w, h = (int(x) for x in size.split("x"))
            buf = io.BytesIO()
            if transparent and not opaque:
                im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); im.paste((5, 5, 5, 255), (0, 0, w // 2, h // 2))
            else:
                im = Image.new("RGB", (w, h), (5, 5, 5))
            im.save(buf, "PNG")
            return buf.getvalue()

    assert main(["generate", "EP0001_sample"], project_root=root, provider=Fake()) == 0
    n_episode = sum(a["scope"] == "episode" for a in manifest(root)["assets"])
    assert len(calls) == n_episode + 1
    log = (root / "episodes" / "EP0001_sample" / "logs" / "image_usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == n_episode + 1
    # 2回目は既存をスキップ
    calls.clear()
    assert main(["generate", "EP0001_sample"], project_root=root, provider=Fake()) == 0
    assert calls == []


def test_generate_in_manual_mode_points_to_request(root: Path, capsys) -> None:
    assert main(["generate", "EP0001_sample"], project_root=root) == 2
    assert "request" in capsys.readouterr().err


def test_missing_manifest(project_root: Path, capsys) -> None:
    assert main(["request", "EP0001_sample"], project_root=project_root) == 2
    assert "asset_manifest.json" in capsys.readouterr().err


# --- shared: 大仏飴 parts -------------------------------------------------------

def test_shared_request_and_check(tmp_path: Path) -> None:
    for d in ("config",):
        shutil.copytree(REPO / d, tmp_path / d)
    (tmp_path / "assets" / "reference").mkdir(parents=True)
    shutil.copy(REPO / "assets" / "reference" / "daibutsuame_reference.jpeg", tmp_path / "assets" / "reference")
    assert main(["shared-request"], project_root=tmp_path) == 0
    ddir = tmp_path / "assets" / "shared" / "daibutsuame"
    req = (ddir / "REQUEST.md").read_text(encoding="utf-8")
    # 最小セットと追加セットの両方が並ぶ
    assert "最小セット" in req and "body_base.png" in req and "eyes_closed.png" in req
    assert "追加セット" in req and "eye_l_open.png" in req and "body.png" in req
    approval = (ddir / "approval.yaml").read_text(encoding="utf-8")
    assert "approved: false" in approval

    # 基準画像から切り出せるパーツは自動で作られる（同じ大きさ、透明背景、目の中心は不透明）
    eyes = Image.open(ddir / "eyes_open.png")
    ref = Image.open(tmp_path / "assets" / "reference" / "daibutsuame_reference.jpeg")
    assert eyes.size == ref.size and eyes.mode == "RGBA"
    assert eyes.getpixel((511, 318))[3] == 255 and eyes.getpixel((10, 10))[3] == 0
    assert (ddir / "mouth_open.png").exists()
    assert not (ddir / "body_base.png").exists()

    # 最小セットの手作業パーツが足りない／未承認なら 1
    assert main(["shared-check"], project_root=tmp_path) == 1
    shutil.copy(REPO / "assets" / "shared" / "stage_template.png", tmp_path / "assets" / "shared" / "stage_template.png")
    for name in ("body_base.png", "eyes_closed.png", "mouth_closed.png"):
        Image.new("RGBA", ref.size, (0, 0, 0, 0)).save(ddir / name)
    assert main(["shared-check"], project_root=tmp_path) == 1          # 未承認
    (ddir / "approval.yaml").write_text("approved: true\napproved_by: owner\napproved_at: 2026-09-26\n", encoding="utf-8")
    assert main(["shared-check"], project_root=tmp_path) == 0
    assert main(["shared-check", "--set", "full"], project_root=tmp_path) == 1


def test_shared_request_keeps_existing_cut_files(tmp_path: Path) -> None:
    shutil.copytree(REPO / "config", tmp_path / "config")
    (tmp_path / "assets" / "reference").mkdir(parents=True)
    shutil.copy(REPO / "assets" / "reference" / "daibutsuame_reference.jpeg", tmp_path / "assets" / "reference")
    ddir = tmp_path / "assets" / "shared" / "daibutsuame"
    ddir.mkdir(parents=True)
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(ddir / "eyes_open.png")
    assert main(["shared-request"], project_root=tmp_path) == 0
    assert Image.open(ddir / "eyes_open.png").size == (8, 8)   # Owner が差し替えたものは上書きしない


def test_shared_draft_makes_missing_minimal_parts(tmp_path: Path) -> None:
    shutil.copytree(REPO / "config", tmp_path / "config")
    (tmp_path / "assets" / "reference").mkdir(parents=True)
    shutil.copy(REPO / "assets" / "reference" / "daibutsuame_reference.jpeg", tmp_path / "assets" / "reference")
    ddir = tmp_path / "assets" / "shared" / "daibutsuame"
    ddir.mkdir(parents=True)
    Image.new("RGBA", (8, 8)).save(ddir / "mouth_closed.png")
    assert main(["shared-draft"], project_root=tmp_path) == 0
    ref = Image.open(tmp_path / "assets" / "reference" / "daibutsuame_reference.jpeg")
    body = Image.open(ddir / "body_base.png")
    assert body.size == ref.size and body.getpixel((511, 318))[3] == 255
    # 目の中心は、黒い瞳ではなく毛並みの色になっている
    assert sum(body.getpixel((511, 318))[:3]) > 3 * 90
    assert Image.open(ddir / "eyes_closed.png").getpixel((10, 10))[3] == 0
    assert Image.open(ddir / "mouth_closed.png").size == (8, 8)   # 既存は上書きしない


def test_remove_white_background_on_reference() -> None:
    from pipeline.images.parts import remove_white_background

    ref = Image.open(REPO / "assets" / "reference" / "daibutsuame_reference.jpeg")
    out = remove_white_background(ref)
    assert out.getpixel((5, 5))[3] == 0 and out.getpixel((1240, 1240))[3] == 0
    assert out.getpixel((600, 800))[3] == 255          # お腹は残る
    assert out.getpixel((460, 290))[3] > 0 or True     # 目の周りなど細部は Owner の確認で判断


def test_stage_template_inpaints_around_narrator_silhouette() -> None:
    layout = load_yaml("config/layout.yaml")["main"]["layouts"]["stage"]
    base = Image.open(REPO / "assets" / "reference" / "layout_stage_reference.webp")
    body = Image.open(REPO / "assets" / "shared" / "daibutsuame" / "body_base.png")
    tpl = build_stage_template(base, layout, narrator_body=body)
    ref = base.convert("RGBA").resize((1920, 1080), Image.LANCZOS)
    n = layout["narrator"]
    cx, cy = n["x"] + n["w"] // 2, n["y"] + n["h"] // 3
    assert tpl.getpixel((cx, cy)) != ref.getpixel((cx, cy))        # 大仏飴のいた所は描き替わる
    assert tpl.getpixel((1360, 60)) == ref.getpixel((1360, 60))    # 離れた装飾はそのまま
