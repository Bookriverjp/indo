import json
import shutil
from pathlib import Path

import pytest

from pipeline.assets import AssetError, build_manifest, main
from pipeline.config import load_yaml
from pipeline.schema_validation import validate

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
def manifest() -> dict:
    return build_manifest(
        episode_id="EP0001_sample",
        storyboard=load("storyboard_rich.json"),
        script=load("script_valid.json"),
        research=load("research_valid.json"),
        layout=load_yaml("config/layout.yaml"),
        visual=load_yaml("config/visual_style.yaml"),
        persona=load_yaml("config/persona.yaml")["persona"],
        project_root=REPO,
    )


def assets_by(manifest: dict, **kv) -> list[dict]:
    return [a for a in manifest["assets"] if all(a[k] == v for k, v in kv.items())]


def scene(manifest: dict, sid: str) -> dict:
    return next(s for s in manifest["scenes"] if s["scene_id"] == sid)


def test_manifest_matches_schema(manifest: dict) -> None:
    validate(manifest, "asset_manifest")


def test_same_background_is_reused(manifest: dict) -> None:
    bgs = assets_by(manifest, kind="background")
    assert len(bgs) == 2
    river = next(a for a in bgs if a["label"] == "夜の川辺の村")
    assert river["scenes"] == ["s01", "s03"]
    assert river["asset_id"] == "bg_s01_v01"


def test_same_character_is_reused_after_normalizing(manifest: dict) -> None:
    fisher = [a for a in assets_by(manifest, kind="character") if a["label"] == "若い漁師"]
    assert len(fisher) == 1 and fisher[0]["scenes"] == ["s03", "s04"]
    assert fisher[0]["transparent"] is True


def test_narrator_is_shared_not_generated(manifest: dict) -> None:
    assert not [a for a in manifest["assets"] if a["label"] == "大仏飴" and a["scope"] == "episode"]
    narrator = assets_by(manifest, kind="narrator")[0]
    assert narrator["scope"] == "shared" and narrator["prompt"] is None
    assert narrator["reference_image"] == "assets/reference/daibutsuame_reference.jpeg"


def test_template_is_shared(manifest: dict) -> None:
    t = assets_by(manifest, kind="template")[0]
    assert t["scope"] == "shared" and t["prompt"] is None
    assert t["reference_image"] == "assets/reference/layout_stage_reference.webp"


def test_episode_assets_have_prompts_and_files(manifest: dict) -> None:
    for a in assets_by(manifest, scope="episode"):
        assert a["prompt"] and "文字" in a["prompt"]
        assert not a["prompt"].startswith("#")
        assert a["file"] == f"assets/generated/{a['asset_id']}.png"


def test_background_prompt_uses_scene_region_and_tone(manifest: dict) -> None:
    bg = next(a for a in assets_by(manifest, kind="background") if a["label"] == "夜の川辺の村")
    assert "夜の川辺の村" in bg["prompt"]
    assert "West Bengal" in bg["prompt"]
    assert "川、湿潤" in bg["prompt"]          # visual_style.yaml の地域トーン（Bengal）
    assert "{{" not in bg["prompt"]


def test_card_scene_has_no_story_art(manifest: dict) -> None:
    layers = scene(manifest, "s02")["layers"]
    assert {l["slot"] for l in layers} == {"template", "narrator"}


def test_stage_scene_layers_are_ordered_and_placed(manifest: dict) -> None:
    s = scene(manifest, "s03")
    assert s["layout"] == "stage" and s["motion"] == "slow_pan"
    art = [l for l in s["layers"] if l["slot"] == "story_art"]
    assert [l["layer"] for l in art] == sorted([l["layer"] for l in art], key=["background", "character", "prop", "foreground", "fx"].index)
    chars = [l for l in art if l["layer"] == "character"]
    assert len(chars) == 2 and chars[0]["box"][0] < chars[1]["box"][0]
    for l in art:
        x, y, w, h = l["box"]
        assert 0 <= x and 0 <= y and x + w <= 1.0001 and y + h <= 1.0001
    zs = [l["z"] for l in s["layers"]]
    assert zs == sorted(zs)


def test_hook_scene_hides_narrator_in_fullbleed(manifest: dict) -> None:
    layers = scene(manifest, "s01")["layers"]
    assert "narrator" not in {l["slot"] for l in layers}
    assert "template" not in {l["slot"] for l in layers}


def test_every_layer_asset_exists(manifest: dict) -> None:
    ids = {a["asset_id"] for a in manifest["assets"]}
    for s in manifest["scenes"]:
        for l in s["layers"]:
            assert l["asset_id"] in ids


def test_unknown_layout_raises() -> None:
    sb = load("storyboard_rich.json")
    sb["scenes"][0]["layout"] = "weird"
    with pytest.raises(AssetError):
        build_manifest(episode_id="EP0001_sample", storyboard=sb, script=load("script_valid.json"),
                       research=load("research_valid.json"), layout=load_yaml("config/layout.yaml"),
                       visual=load_yaml("config/visual_style.yaml"),
                       persona=load_yaml("config/persona.yaml")["persona"], project_root=REPO)


# --- CLI ---------------------------------------------------------------------

@pytest.fixture
def root(project_root: Path) -> Path:
    shutil.copytree(REPO / "prompts", project_root / "prompts")
    ep = project_root / "episodes" / "EP0001_sample"
    for sub, name, src in [("research", "research.json", "research_valid.json"),
                           ("script", "script_main.json", "script_valid.json"),
                           ("storyboard", "storyboard.json", "storyboard_rich.json")]:
        (ep / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, ep / sub / name)
    return project_root


def test_cli_writes_manifest_and_list(root: Path, capsys) -> None:
    assert main(["EP0001_sample"], project_root=root) == 0
    ep = root / "episodes" / "EP0001_sample" / "storyboard"
    data = json.loads((ep / "asset_manifest.json").read_text(encoding="utf-8"))
    validate(data, "asset_manifest", root)
    md = (ep / "asset_manifest.md").read_text(encoding="utf-8")
    assert "若い漁師" in md and "共通" in md
    assert "生成する素材" in capsys.readouterr().out


def test_cli_refuses_overwrite(root: Path) -> None:
    assert main(["EP0001_sample"], project_root=root) == 0
    assert main(["EP0001_sample"], project_root=root) == 2
    assert main(["EP0001_sample", "--force"], project_root=root) == 0


def test_cli_missing_storyboard(root: Path, capsys) -> None:
    (root / "episodes" / "EP0001_sample" / "storyboard" / "storyboard.json").unlink()
    assert main(["EP0001_sample"], project_root=root) == 2
    assert "storyboard.json" in capsys.readouterr().err
