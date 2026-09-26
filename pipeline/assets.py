"""PHASE 4: storyboard から1話分の素材一覧（asset manifest）とレイヤー配置を作る。

LLM は使わない。同じ表記の背景・人物・小物は1つの素材にまとめて使い回し、
大仏飴と舞台テンプレートは全話共通の素材として参照だけする（生成しない）。

使い方:
  python -m pipeline.assets EP0001_nishi_daak [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.prompts import PromptError, load_prompt, render
from pipeline.schema_validation import SchemaValidationError, validate
from pipeline.workspace import create_episode_workspace, episode_paths


class AssetError(Exception):
    pass


# storyboard の項目 → (kind, id接頭辞, 透過, レイヤー)
_PARTS = [
    ("characters", "character", "char", True),
    ("props", "prop", "prop", True),
    ("foreground", "foreground", "fg", True),
    ("fx", "fx", "fx", True),
]
_KIND_JA = {"prop": "小物", "foreground": "前景", "fx": "効果"}
_Z = {"template": 0, "background": 10, "character": 20, "prop": 30, "foreground": 40, "fx": 50, "narrator": 60}

SHARED_TEMPLATE = {
    "asset_id": "shared_stage_template", "kind": "template", "scope": "shared", "label": "紙芝居舞台テンプレート",
    "prompt": None, "transparent": True, "reference_image": "assets/reference/layout_stage_reference.webp",
    "file": "assets/shared/stage_template.png",
}
SHARED_NARRATOR = {
    "asset_id": "shared_daibutsuame", "kind": "narrator", "scope": "shared", "label": "大仏飴（パーツ一式）",
    "prompt": None, "transparent": True, "reference_image": "assets/reference/daibutsuame_reference.jpeg",
    "file": "assets/shared/daibutsuame/",
}


def _norm(text: str) -> str:
    return " ".join(text.split())


def _template(name: str, project_root: Path) -> str:
    """prompts/<name>.md から見出し行（# ...）を除いた本文。"""
    lines = load_prompt(name, project_root).splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def region_tone(region: str, visual: dict) -> str:
    low = region.lower()
    for t in visual.get("region_tones", []):
        if any(m.lower() in low for m in t["match"]):
            return f"{t['tradition']}: {t['tone']}"
    return visual.get("default_region_tone", "")


def _spread(n: int, width: float, y: float, h: float) -> list[list[float]]:
    """n 個を横に均等に並べる box（slot 相対）。"""
    boxes = []
    for i in range(n):
        cx = (i + 1) / (n + 1)
        w = min(width, 1.0 / max(n, 1))
        boxes.append([round(max(0.0, min(1.0 - w, cx - w / 2)), 4), y, round(w, 4), h])
    return boxes


def _placements(layer: str, n: int) -> list[list[float]]:
    if layer == "background" or layer == "fx":
        return [[0.0, 0.0, 1.0, 1.0]] * n
    if layer == "character":
        return _spread(n, 0.28, 0.3, 0.65)
    if layer == "prop":
        return _spread(n, 0.15, 0.68, 0.22)
    if layer == "foreground":
        return [[0.0, 0.72, 1.0, 0.28]] * n
    raise AssertionError(layer)


def build_manifest(*, episode_id: str, storyboard: dict, script: dict, research: dict, layout: dict,
                   visual: dict, persona: dict, project_root: Path) -> dict:
    layouts = layout["main"]["layouts"]
    hook_blocks = {b["block_id"] for s in script["sections"] if s["section"] == "hook" for b in s["blocks"]}
    region = research["region"]
    tone = region_tone(region, visual)
    tpl_bg = _template("05_image_background", project_root)
    tpl_char = _template("06_image_character", project_root)
    tpl_part = _template("09_image_part", project_root)

    assets: dict[tuple[str, str], dict] = {}   # (kind, 正規化ラベル) → asset
    counters: dict[str, int] = {}

    def get_asset(kind: str, prefix: str, label: str, scene: dict, transparent: bool) -> dict:
        key = (kind, _norm(label))
        if key not in assets:
            if kind == "background":
                aid = f"bg_{scene['scene_id'].lower()}_v01"
                prompt = render(tpl_bg, scene_description=f"{_norm(label)} / {scene['visual_summary']}",
                                region=region, region_tone=tone, time_of_day=scene.get("time_of_day") or "指定なし")
            else:
                counters[prefix] = counters.get(prefix, 0) + 1
                aid = f"{prefix}_{counters[prefix]:02d}_v01"
                if kind == "character":
                    prompt = render(tpl_char, description=_norm(label), region=region, region_tone=tone)
                else:
                    prompt = render(tpl_part, kind=_KIND_JA[kind], description=_norm(label), region=region, region_tone=tone)
            assets[key] = {"asset_id": aid, "kind": kind, "scope": "episode", "label": _norm(label),
                           "prompt": prompt, "transparent": transparent, "reference_image": None,
                           "file": f"assets/generated/{aid}.png", "scenes": []}
        a = assets[key]
        if scene["scene_id"] not in a["scenes"]:
            a["scenes"].append(scene["scene_id"])
        return a

    shared_used: dict[str, dict] = {}

    def use_shared(base: dict, scene_id: str) -> dict:
        a = shared_used.setdefault(base["asset_id"], dict(base, scenes=[]))
        if scene_id not in a["scenes"]:
            a["scenes"].append(scene_id)
        return a

    scenes = []
    for sc in storyboard["scenes"]:
        name = sc["layout"]
        if name not in layouts:
            raise AssetError(f"{sc['scene_id']}: unknown layout {name!r} (config/layout.yaml)")
        cfg = layouts[name]
        is_hook = bool(sc["block_ids"]) and set(sc["block_ids"]) <= hook_blocks
        layers = []

        if "template" in cfg:
            layers.append({"asset_id": use_shared(SHARED_TEMPLATE, sc["scene_id"])["asset_id"], "layer": "template",
                           "slot": "template", "box": [0.0, 0.0, 1.0, 1.0], "z": _Z["template"]})

        if "story_art" in cfg:
            if sc.get("background"):
                a = get_asset("background", "bg", sc["background"], sc, False)
                layers.append({"asset_id": a["asset_id"], "layer": "background", "slot": "story_art",
                               "box": [0.0, 0.0, 1.0, 1.0], "z": _Z["background"]})
            for field, kind, prefix, transparent in _PARTS:
                labels = [x for x in sc.get(field, []) if _norm(x) and _norm(x) != persona["name"]]
                for i, (label, box) in enumerate(zip(labels, _placements(kind, len(labels)))):
                    a = get_asset(kind, prefix, label, sc, transparent)
                    layers.append({"asset_id": a["asset_id"], "layer": kind, "slot": "story_art",
                                   "box": box, "z": _Z[kind] + i})

        narrator_cfg = cfg.get("narrator")
        if narrator_cfg and not (is_hook and narrator_cfg.get("visible_in_hook") is False):
            layers.append({"asset_id": use_shared(SHARED_NARRATOR, sc["scene_id"])["asset_id"], "layer": "narrator",
                           "slot": "narrator", "box": [0.0, 0.0, 1.0, 1.0], "z": _Z["narrator"]})

        scenes.append({"scene_id": sc["scene_id"], "layout": name, "motion": sc.get("suggested_motion"),
                       "estimated_seconds": sc["estimated_seconds"], "layers": layers})

    return {"schema_version": 1, "episode_id": episode_id,
            "assets": list(shared_used.values()) + list(assets.values()), "scenes": scenes}


_KIND_LABEL = {"background": "背景", "character": "人物", "prop": "小物", "foreground": "前景", "fx": "効果",
               "template": "舞台テンプレート", "narrator": "語り部"}


def render_manifest_md(manifest: dict) -> str:
    episode = [a for a in manifest["assets"] if a["scope"] == "episode"]
    shared = [a for a in manifest["assets"] if a["scope"] == "shared"]
    lines = [f"# 素材一覧: {manifest['episode_id']}", "",
             f"## この回で生成する素材（{len(episode)}件）", "",
             "| ID | 種類 | 内容 | 透過 | 使う scene |", "|---|---|---|---|---|"]
    lines += [f"| {a['asset_id']} | {_KIND_LABEL[a['kind']]} | {a['label']} | {'○' if a['transparent'] else ''} "
              f"| {', '.join(a['scenes'])} |" for a in episode]
    lines += ["", f"## 共通素材（{len(shared)}件、生成しない）", ""]
    lines += [f"- {a['asset_id']}: {a['label']}（{a['file']}）" for a in shared]
    lines += ["", "## scene ごとのレイヤー", ""]
    for s in manifest["scenes"]:
        order = " → ".join(l["asset_id"] for l in s["layers"]) or "(なし)"
        lines.append(f"- {s['scene_id']}（{s['layout']}, {s['estimated_seconds']}秒）: {order}")
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AssetError(f"input not found: {path}") from None
    except json.JSONDecodeError as e:
        raise AssetError(f"cannot parse {path}: {e}") from None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the asset manifest from storyboard.json")
    parser.add_argument("episode_id")
    parser.add_argument("--force", action="store_true", help="overwrite existing asset_manifest.json")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        paths = episode_paths(root, args.episode_id)
        if paths["asset_manifest"].exists() and not args.force:
            raise AssetError(f"{paths['asset_manifest']} already exists (use --force to overwrite)")
        manifest = build_manifest(
            episode_id=args.episode_id,
            storyboard=_read_json(paths["storyboard"]),
            script=_read_json(paths["script_json"]),
            research=_read_json(paths["research"]),
            layout=load_yaml("config/layout.yaml", root),
            visual=load_yaml("config/visual_style.yaml", root),
            persona=load_yaml("config/persona.yaml", root)["persona"],
            project_root=root,
        )
        validate(manifest, "asset_manifest", root)
    except (AssetError, ValueError, ConfigError, PromptError, SchemaValidationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    create_episode_workspace(root, args.episode_id)
    _write_text(paths["asset_manifest"], json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _write_text(paths["asset_manifest_md"], render_manifest_md(manifest))
    n_episode = sum(a["scope"] == "episode" for a in manifest["assets"])
    print(f"saved: {paths['asset_manifest']}")
    print(f"生成する素材: {n_episode}件（共通素材 {len(manifest['assets']) - n_episode}件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
