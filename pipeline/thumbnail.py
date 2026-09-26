"""PHASE 9: サムネイル（1280x720）を作る。

使い方:
  python -m pipeline.thumbnail EP0001_nishi_daak [--text "文字"] [--draft] [--placeholders]

背景は最初の場面の物語の絵、文字は youtube_metadata.json のサムネイル文字案の1つ目（--text で指定可）、
右に大仏飴。文字は画像生成に描かせず、ここで重ねる。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.render.narrator import NarratorRig
from pipeline.workspace import episode_paths

DAIBUTSUAME_DIR = "assets/shared/daibutsuame"


class ThumbnailError(Exception):
    pass


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ThumbnailError(f"input not found: {path}") from None


def _cover(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    k = max(size[0] / im.width, size[1] / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    left, top = (im.width - size[0]) // 2, (im.height - size[1]) // 2
    return im.crop((left, top, left + size[0], top + size[1]))


def _background(paths: dict, manifest: dict, placeholders: bool, size: tuple[int, int]) -> Image.Image:
    bgs = [a for a in manifest["assets"] if a["kind"] == "background"]
    ep_dir = paths["asset_manifest"].parents[1]
    for a in bgs:
        if (ep_dir / a["file"]).exists():
            with Image.open(ep_dir / a["file"]) as im:
                return _cover(im.convert("RGB"), size)
    if not placeholders:
        raise ThumbnailError("背景の画像がありません: " + ", ".join(a["asset_id"] for a in bgs) +
                             "（python -m pipeline.images check、または --placeholders）")
    img = Image.new("RGB", size, (28, 36, 80))
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        d.line([(0, y), (size[0], y)], fill=(28 + y // 20, 36 + y // 16, 80 + y // 10))
    return img


def _split(text: str, max_lines: int) -> list[str]:
    if len(text) <= 7 or max_lines == 1:
        return [text]
    cut = (len(text) + 1) // 2
    for sep in "、。？！ ":
        i = text.find(sep)
        if 0 < i < len(text) - 1:
            cut = i + 1
            break
    return [text[:cut], text[cut:]]


def build_thumbnail(root: Path, episode_id: str, text: str, *, draft: bool, placeholders: bool) -> Image.Image:
    cfg = load_yaml("config/thumbnail.yaml", root)["thumbnail"]
    rcfg = load_yaml("config/render.yaml", root)["render"]
    paths = episode_paths(root, episode_id)
    research = _read_json(paths["research"])
    manifest = _read_json(paths["asset_manifest"])

    if not draft:
        approval = root / DAIBUTSUAME_DIR / "approval.yaml"
        ok = approval.exists() and bool((yaml.safe_load(approval.read_text(encoding="utf-8")) or {}).get("approved"))
        if not ok:
            raise ThumbnailError("大仏飴パーツが Owner 未承認です（approval.yaml）。確認用なら --draft を付ける")

    size = tuple(cfg["size"])
    img = _background(paths, manifest, placeholders, size).convert("RGBA")

    shade = Image.new("L", size, 0)
    sd = ImageDraw.Draw(shade)
    w_shade = int(size[0] * cfg["shade"]["width"])
    for x in range(w_shade):
        sd.line([(x, 0), (x, size[1])], fill=int(cfg["shade"]["alpha"] * (1 - x / w_shade)))
    img = Image.composite(Image.new("RGBA", size, (0, 0, 0, 255)), img, shade)

    n = cfg["narrator"]
    rig = NarratorRig(root / DAIBUTSUAME_DIR, rcfg["narrator"])
    img.alpha_composite(rig.render((n["w"], n["h"]), "full_body", t=0.0, expression="neutral",
                                   eyes_closed=False, mouth_open=True), (n["x"], n["y"]))

    t = cfg["text"]
    font_path = str(root / rcfg["fonts"][t["font"]])
    lines = _split(text, t["max_lines"])
    d = ImageDraw.Draw(img)
    px = t["max_px"]
    while px > 40:
        font = ImageFont.truetype(font_path, px)
        widest = max(d.textlength(l, font=font) for l in lines)
        if widest <= t["box"]["w"] and px * 1.2 * len(lines) <= t["box"]["h"]:
            break
        px -= 4
    top = t["box"]["y"] + (t["box"]["h"] - round(px * 1.2 * len(lines))) // 2
    for i, line in enumerate(lines):
        d.text((t["box"]["x"], top + i * round(px * 1.2)), line, font=font, fill=tuple(t["fill"]),
               stroke_width=t["stroke_px"], stroke_fill=tuple(t["stroke"]))

    lab = cfg["label"]
    lfont = ImageFont.truetype(str(root / rcfg["fonts"]["gothic"]), lab["size"])
    label = f"{research['region']} ・ {research['language']}"
    lw = d.textlength(label, font=lfont)
    d.rectangle((lab["x"], lab["y"], lab["x"] + lw + 44, lab["y"] + lab["h"]), fill=tuple(rcfg["colors"]["chip_bg"]) + (240,))
    d.rectangle((lab["x"], lab["y"], lab["x"] + 10, lab["y"] + lab["h"]), fill=tuple(rcfg["colors"]["card_accent"]) + (255,))
    d.text((lab["x"] + 26, lab["y"] + (lab["h"] - lab["size"]) // 2 - 4), label, font=lfont, fill=tuple(rcfg["colors"]["ink"]))

    fr = cfg["frame"]
    d.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=tuple(fr["outer"]), width=fr["outer_px"])
    o = fr["outer_px"]
    d.rectangle((o, o, size[0] - 1 - o, size[1] - 1 - o), outline=tuple(fr["inner"]), width=fr["inner_px"])
    return img.convert("RGB")


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make the YouTube thumbnail")
    parser.add_argument("episode_id")
    parser.add_argument("--text", help="thumbnail text (default: first thumbnail_text_candidates)")
    parser.add_argument("--draft", action="store_true", help="allow narrator parts not yet approved by the Owner")
    parser.add_argument("--placeholders", action="store_true", help="use a placeholder background if none exists")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        paths = episode_paths(root, args.episode_id)
        text = args.text or _read_json(paths["youtube_metadata"])["thumbnail_text_candidates"][0]
        img = build_thumbnail(root, args.episode_id, text, draft=args.draft, placeholders=args.placeholders)
        cfg = load_yaml("config/thumbnail.yaml", root)["thumbnail"]
        out = paths["thumbnail"]
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG", optimize=True)
        if out.stat().st_size > cfg["max_bytes"]:
            jpg = out.with_suffix(".jpg")
            img.save(jpg, "JPEG", quality=90)
            print(f"PNG が 2MB を超えたので JPEG も保存: {jpg}")
    except (ThumbnailError, ValueError, ConfigError, KeyError, IndexError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"文字: {text}")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
